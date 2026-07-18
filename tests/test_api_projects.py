"""
Backlog 2.1/2.2/2.3 API acceptance: create a project (agent-proposed shot
list persisted to DB + B2), fetch it, and edit its shot list (add/remove/
reorder/reword all reduce to a shot-list replace). The agent and B2 write
are monkeypatched so this needs neither an OpenAI credential nor a B2
credential — matches the skip-if-no-creds convention used for the real
B2-hitting tests in this repo. The DB dependency is overridden to an
in-memory SQLite session so no state leaks between tests or touches a real
nova.db file.
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

_FAKE_SHOT_LIST = [
    ShotListItem(
        shot_id="s1", order=0, description="Wide establishing shot", intent="establish", shot_size="wide"
    ),
    ShotListItem(
        shot_id="s2", order=1, description="Medium on the subject", intent="introduce", shot_size="medium"
    ),
]


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

    app.dependency_overrides[get_session] = override_get_session
    try:
        with TestClient(app) as test_client:
            yield test_client
    finally:
        app.dependency_overrides.clear()


def test_create_project_returns_agent_shot_list(client):
    res = client.post("/api/projects", json={"scene_text": "A woman walks through a ruined city."})
    assert res.status_code == 200
    body = res.json()
    assert body["scene_text"] == "A woman walks through a ruined city."
    assert [s["shot_id"] for s in body["shot_list"]] == ["s1", "s2"]
    assert body["shots"] == []
    assert body["sequence_url"] is None


def test_get_project_round_trips(client):
    created = client.post("/api/projects", json={"scene_text": "Scene text"}).json()
    res = client.get(f"/api/projects/{created['project_id']}")
    assert res.status_code == 200
    assert res.json()["project_id"] == created["project_id"]


def test_get_project_missing_returns_404(client):
    res = client.get("/api/projects/does-not-exist")
    assert res.status_code == 404


def test_update_shot_list_persists_edits(client):
    created = client.post("/api/projects", json={"scene_text": "Scene text"}).json()
    project_id = created["project_id"]

    edited = [
        {"shot_id": "s2", "order": 0, "description": "Reordered to first", "intent": "", "shot_size": "medium"},
        {"shot_id": "s1", "order": 1, "description": "Wide establishing shot", "intent": "", "shot_size": "wide"},
        {"shot_id": "s3", "order": 2, "description": "New added shot", "intent": "", "shot_size": "close-up"},
    ]
    res = client.put(f"/api/projects/{project_id}/shot-list", json={"shot_list": edited})
    assert res.status_code == 200
    body = res.json()
    assert [s["shot_id"] for s in body["shot_list"]] == ["s2", "s1", "s3"]
    assert body["shot_list"][0]["description"] == "Reordered to first"

    refetched = client.get(f"/api/projects/{project_id}").json()
    assert [s["shot_id"] for s in refetched["shot_list"]] == ["s2", "s1", "s3"]


def test_list_projects_returns_summaries(client):
    client.post("/api/projects", json={"scene_text": "First scene"})
    client.post("/api/projects", json={"scene_text": "Second scene"})

    res = client.get("/api/projects")
    assert res.status_code == 200
    summaries = res.json()
    assert len(summaries) == 2
    assert all(s["shot_count"] == 2 for s in summaries)
