"""
Backlog 2.4 API acceptance: POST /projects/{id}/generate-storyboard authors
a v1 Shot Spec per shot via the cinematographer agent, persists it, and
returns the project with `shots` populated. The agent and B2 write are
monkeypatched (same convention as tests/test_api_projects.py) so this needs
neither an OpenAI nor a B2 credential.
"""

import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker
from sqlalchemy.pool import StaticPool

import nova.api.routes as routes
from nova.api.app import app
from nova.models.project import Base, get_session
from nova.models.shot_list import ShotListItem
from nova.models.shot_spec import Camera, Framing, Grade, Lens, Lighting, ShotSpec, Subject

_FAKE_SHOT_LIST = [
    ShotListItem(
        shot_id="s1", order=0, description="Wide establishing shot", intent="establish", shot_size="wide"
    ),
    ShotListItem(
        shot_id="s2", order=1, description="Medium on the subject", intent="introduce", shot_size="medium"
    ),
]


def _fake_spec(shot: ShotListItem) -> ShotSpec:
    return ShotSpec(
        shot_id=shot.shot_id,
        version=1,
        intent=shot.intent or shot.description,
        camera=Camera(angle="eye-level", height_m=1.5, movement="static"),
        lens=Lens(focal_length_mm=35, aperture_f=2.8),
        framing=Framing(shot_size=shot.shot_size, composition="centered"),
        lighting=Lighting(key="natural", mood="neutral", practicals=[]),
        grade=Grade(look="neutral", contrast="medium"),
        subject=Subject(primary="subject", blocking="standing"),
        world=[],
    )


@pytest.fixture()
def client(monkeypatch):
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    Base.metadata.create_all(bind=engine)
    TestingSession = sessionmaker(bind=engine, expire_on_commit=False)

    def override_get_session():
        session = TestingSession()
        try:
            yield session
        finally:
            session.close()

    monkeypatch.setattr("nova.api.app.init_db", lambda: None)
    monkeypatch.setattr(routes, "break_down_scene", lambda scene_text: list(_FAKE_SHOT_LIST))
    monkeypatch.setattr(routes, "put_json", lambda key, data: key)
    monkeypatch.setattr(
        routes,
        "generate_shot_specs",
        lambda shot_list, *, scene_text: [_fake_spec(s) for s in shot_list],
    )

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def _create_project(client) -> str:
    res = client.post("/api/projects", json={"scene_text": "A woman walks through a ruined city."})
    return res.json()["project_id"]


def test_generate_storyboard_populates_shots(client):
    project_id = _create_project(client)

    res = client.post(f"/api/projects/{project_id}/generate-storyboard")
    assert res.status_code == 200
    body = res.json()

    assert [s["shot_id"] for s in body["shots"]] == ["s1", "s2"]
    for shot in body["shots"]:
        assert shot["status"] == "DRAFT"
        assert shot["current_version"] == 1
        assert len(shot["versions"]) == 1
        assert shot["versions"][0]["version"] == 1
        assert shot["versions"][0]["frame_url"] is None
        assert shot["versions"][0]["spec"]["shot_id"] == shot["shot_id"]
        assert shot["locked_frame_url"] is None


def test_generate_storyboard_persists_across_refetch(client):
    project_id = _create_project(client)
    client.post(f"/api/projects/{project_id}/generate-storyboard")

    refetched = client.get(f"/api/projects/{project_id}").json()
    assert [s["shot_id"] for s in refetched["shots"]] == ["s1", "s2"]


def test_generate_storyboard_missing_project_returns_404(client):
    res = client.post("/api/projects/does-not-exist/generate-storyboard")
    assert res.status_code == 404


def test_generate_storyboard_regenerate_replaces_prior_shots(client):
    project_id = _create_project(client)
    client.post(f"/api/projects/{project_id}/generate-storyboard")
    res = client.post(f"/api/projects/{project_id}/generate-storyboard")

    assert res.status_code == 200
    body = res.json()
    assert [s["shot_id"] for s in body["shots"]] == ["s1", "s2"]
    # Exactly one row per shot survives the regenerate, not a duplicate.
    assert len(body["shots"]) == 2


def test_generate_storyboard_propagates_agent_failure_as_502(client, monkeypatch):
    project_id = _create_project(client)

    def failing_generate(shot_list, *, scene_text):
        raise RuntimeError("agent output failed schema validation after 3 attempts")

    monkeypatch.setattr(routes, "generate_shot_specs", failing_generate)

    res = client.post(f"/api/projects/{project_id}/generate-storyboard")
    assert res.status_code == 502
