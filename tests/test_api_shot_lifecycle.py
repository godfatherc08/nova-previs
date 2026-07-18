"""
Backlog 3.5/3.6/4.1/7.x/8.6 API acceptance: the full shot lifecycle through
the HTTP surface — generate a frame, refine to a new version, lock (writing
an Object-Locked frame + sealed manifest), assemble the sequence, and the
media proxy that serves private-bucket objects.

Everything external is faked so this runs with no credentials:
  * an in-memory B2 (dict) replaces every b2_client function routes.py uses,
  * the image stage is monkeypatched to a deterministic fake StageResult,
  * ffmpeg assembly is monkeypatched (real ffmpeg concat is covered in
    test_assembly.py; here we only assert the endpoint's orchestration).
"""

import json

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import nova.api.routes as routes
from nova.api.app import app
from nova.models.project import Base, get_session
from nova.models.shot_list import ShotListItem
from nova.models.shot_spec import (
    Camera,
    Framing,
    Grade,
    Lens,
    Lighting,
    ShotSpec,
    Subject,
)
from nova.models.stage import StageResult

_FAKE_SHOT_LIST = [
    ShotListItem(shot_id="s1", order=0, description="Wide establisher", intent="establish", shot_size="wide"),
    ShotListItem(shot_id="s2", order=1, description="Medium on subject", intent="introduce", shot_size="medium"),
]


def _fake_spec(shot_id: str, version: int = 1, refs=None) -> ShotSpec:
    return ShotSpec(
        shot_id=shot_id,
        version=version,
        intent="a shot",
        camera=Camera(angle="eye-level", height_m=1.5, movement="static"),
        lens=Lens(focal_length_mm=35, aperture_f=2.8),
        framing=Framing(shot_size="wide", composition="centered"),
        lighting=Lighting(key="natural", mood="neutral", practicals=[]),
        grade=Grade(look="neutral", contrast="medium"),
        subject=Subject(primary="subject", blocking="standing"),
        world=[],
        continuity_refs=refs or [],
    )


class _FakeImageStage:
    """Deterministic stand-in for default_image_stage() — no providers."""

    def __init__(self, *, fail: bool = False):
        self._fail = fail

    def run(self, spec, *, project_id=None, reference_assets=None):
        if self._fail:
            return StageResult(status="failed", assets=[], error="all providers failed")
        from genblaze_core.models.asset import Asset

        asset = Asset(url="https://mock.test/frame.png", media_type="image/png", size_bytes=10)
        asset.set_hash(b"frame-v%d" % spec.version)
        return StageResult(
            status="succeeded",
            assets=[asset],
            prompt="compiled prompt",
            provider="google-nano-banana",
            model="gemini-2.5-flash-image",
        )

    def refine(self, spec, prior_frame, *, instruction, project_id=None, reference_assets=None):
        return self.run(spec, project_id=project_id, reference_assets=reference_assets)


@pytest.fixture()
def b2():
    """In-memory B2 keyed by object key -> bytes."""
    return {}


@pytest.fixture()
def client(monkeypatch, b2):
    engine = create_engine(
        "sqlite:///:memory:", connect_args={"check_same_thread": False}, poolclass=StaticPool
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    def fake_put_json(key, data, *, object_lock=False):
        b2[key] = json.dumps(data).encode("utf-8")
        return key

    def fake_put_bytes(key, data, *, content_type, object_lock=False):
        b2[key] = data
        return key

    def fake_get_bytes(key):
        if key not in b2:
            raise FileNotFoundError(key)
        return b2[key]

    monkeypatch.setattr("nova.api.app.init_db", lambda: None)
    monkeypatch.setattr(routes, "break_down_scene", lambda scene_text: list(_FAKE_SHOT_LIST))
    monkeypatch.setattr(
        routes, "generate_shot_specs",
        lambda shot_list, *, scene_text: [_fake_spec(s.shot_id) for s in shot_list],
    )
    monkeypatch.setattr(routes, "put_json", fake_put_json)
    monkeypatch.setattr(routes, "put_bytes", fake_put_bytes)
    monkeypatch.setattr(routes, "get_bytes", fake_get_bytes)
    monkeypatch.setattr(routes, "_asset_bytes", lambda asset: b"frame-bytes")
    monkeypatch.setattr(routes, "default_image_stage", lambda: _FakeImageStage())
    monkeypatch.setattr(routes, "_reference_assets_for", lambda spec, project_id: None)
    # refine's spec-authoring agent would hit the LLM — stand in a
    # deterministic bump (the agent itself is covered in test_refine_agent.py).
    monkeypatch.setattr(
        routes,
        "refine_shot_spec",
        lambda current, instruction, *, scene_text="": current.model_copy(
            update={"version": current.version + 1}
        ),
    )
    # Lock's background advance would hit real providers — no-op it here; the
    # advance flow itself is covered in test_advance.py.
    monkeypatch.setattr(routes, "advance_locked_shot", lambda *a, **k: None)

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as tc:
            yield tc, b2
    finally:
        app.dependency_overrides.clear()


def _project_with_storyboard(tc) -> str:
    pid = tc.post("/api/projects", json={"scene_text": "A ruined city."}).json()["project_id"]
    tc.post(f"/api/projects/{pid}/generate-storyboard")
    return pid


def test_generate_frame_persists_versioned_png_and_flips_to_refining(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)

    res = tc.post(f"/api/projects/{pid}/shots/s1/generate")
    assert res.status_code == 200
    shot = res.json()
    assert shot["status"] == "REFINING"
    assert shot["versions"][0]["frame_url"] == f"/api/media/projects/{pid}/shots/s1/frames/v1.png"
    assert f"projects/{pid}/shots/s1/frames/v1.png" in b2


def test_generate_failure_returns_error_card_not_5xx(client, monkeypatch):
    tc, b2 = client
    monkeypatch.setattr(routes, "default_image_stage", lambda: _FakeImageStage(fail=True))
    pid = _project_with_storyboard(tc)

    res = tc.post(f"/api/projects/{pid}/shots/s1/generate")
    assert res.status_code == 200
    shot = res.json()
    assert shot["status"] == "DRAFT"
    assert "all providers failed" in shot["error"]


def test_refine_creates_new_version_and_regenerates(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    tc.post(f"/api/projects/{pid}/shots/s1/generate")

    res = tc.post(f"/api/projects/{pid}/shots/s1/refine", json={"instruction": "denser fog"})
    assert res.status_code == 200
    shot = res.json()
    assert shot["current_version"] == 2
    assert len(shot["versions"]) == 2
    assert f"projects/{pid}/shots/s1/frames/v2.png" in b2


def test_lock_writes_object_locked_frame_and_sealed_manifest(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    tc.post(f"/api/projects/{pid}/shots/s1/generate")

    res = tc.post(f"/api/projects/{pid}/shots/s1/lock", json={})
    assert res.status_code == 200
    shot = res.json()
    assert shot["status"] == "LOCKED"
    assert shot["locked_frame_url"] == f"/api/media/projects/{pid}/shots/s1/locked/frame.png"
    assert f"projects/{pid}/shots/s1/locked/frame.png" in b2
    manifest = json.loads(b2[f"projects/{pid}/shots/s1/locked/manifest.json"])
    # The manifest is sealed and independently verifiable.
    from nova.storage.manifest import ShotManifest, verify_shot_manifest

    report = verify_shot_manifest(ShotManifest.model_validate(manifest), b2[f"projects/{pid}/shots/s1/locked/frame.png"])
    assert report.ok


def test_cannot_lock_a_version_with_no_frame(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    # No generate() call -> no frame.
    res = tc.post(f"/api/projects/{pid}/shots/s1/lock", json={})
    assert res.status_code == 409


def test_media_proxy_serves_stored_object(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    tc.post(f"/api/projects/{pid}/shots/s1/generate")

    res = tc.get(f"/api/media/projects/{pid}/shots/s1/frames/v1.png")
    assert res.status_code == 200
    assert res.headers["content-type"] == "image/png"


def test_media_proxy_rejects_paths_outside_nova_prefixes(client):
    tc, b2 = client
    assert tc.get("/api/media/etc/passwd").status_code == 404
    assert tc.get("/api/media/projects/../secret").status_code == 404


def test_manifest_endpoint_404s_before_lock(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    assert tc.get(f"/api/projects/{pid}/shots/s1/manifest").status_code == 404


def test_assemble_requires_a_ready_shot(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    assert tc.post(f"/api/projects/{pid}/assemble").status_code == 409


def test_full_assemble_flow_writes_sequence_and_marks_assembled(client, monkeypatch):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    # Drive both shots to ANIMATIC_READY by hand (the advance flow is tested
    # elsewhere): generate, lock, then stage the animatic artifacts + status.
    from nova.models.project import ShotRecord

    for shot_id in ("s1", "s2"):
        tc.post(f"/api/projects/{pid}/shots/{shot_id}/generate")
        tc.post(f"/api/projects/{pid}/shots/{shot_id}/lock", json={})
        b2[f"projects/{pid}/shots/{shot_id}/animatic/clip.mp4"] = b"clip"
        b2[f"projects/{pid}/shots/{shot_id}/animatic/audio.mp3"] = b"audio"

    # Flip statuses to ANIMATIC_READY via the overridden session.
    session = app.dependency_overrides[get_session]().__next__()
    for shot in session.query(ShotRecord).all():
        shot.status = "ANIMATIC_READY"
    session.commit()

    captured = {}

    def fake_assemble(shot_media, out_path, *, workdir):
        captured["n"] = len(shot_media)
        out_path.write_bytes(b"assembled-sequence")
        return out_path

    monkeypatch.setattr(routes, "assemble_sequence", fake_assemble)

    res = tc.post(f"/api/projects/{pid}/assemble")
    assert res.status_code == 200
    body = res.json()
    assert captured["n"] == 2
    assert body["sequence_url"] == f"/api/media/projects/{pid}/previs/sequence.mp4"
    assert f"projects/{pid}/previs/sequence.mp4" in b2
    assert all(s["status"] == "ASSEMBLED" for s in body["shots"])
    # Sequence manifest chains both shots' locked manifests.
    seq_manifest = json.loads(b2[f"projects/{pid}/previs/manifest.json"])
    assert [s["shot_id"] for s in seq_manifest["shots"]] == ["s1", "s2"]


def test_multi_take_fanout_returns_candidates_under_scratch(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)

    res = tc.post(f"/api/projects/{pid}/shots/s1/takes", json={"count": 3})
    assert res.status_code == 200
    takes = res.json()["takes"]
    assert len(takes) == 3
    for take in takes:
        assert take["frame_url"].startswith(f"/api/media/scratch/{pid}/s1/")
    assert sum(1 for k in b2 if k.startswith(f"scratch/{pid}/s1/")) == 3


def test_promote_take_creates_numbered_version(client):
    tc, b2 = client
    pid = _project_with_storyboard(tc)
    takes = tc.post(f"/api/projects/{pid}/shots/s1/takes", json={"count": 2}).json()["takes"]

    res = tc.post(
        f"/api/projects/{pid}/shots/s1/takes/promote", json={"take_id": takes[0]["take_id"]}
    )
    assert res.status_code == 200
    shot = res.json()
    assert shot["current_version"] == 2
    # Promoted frame is re-written under frames/ (lifecycle-safe), not scratch/.
    assert f"projects/{pid}/shots/s1/frames/v2.png" in b2
