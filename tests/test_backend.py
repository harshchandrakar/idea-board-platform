import importlib
import os
import sys

import pytest


@pytest.fixture()
def client(tmp_path, monkeypatch):
    # Point the backend at a throwaway SQLite file BEFORE importing it,
    # since db.py reads DATABASE_URL at import time.
    monkeypatch.setenv("DATABASE_URL", f"sqlite:///{tmp_path/'test.db'}")
    for mod in ("db", "main"):
        sys.modules.pop(mod, None)
    main = importlib.import_module("main")
    from fastapi.testclient import TestClient
    with TestClient(main.app) as c:  # triggers lifespan -> init_db()
        yield c


def test_health(client):
    r = client.get("/api/health")
    assert r.status_code == 200
    assert r.json() == {"status": "ok"}


def test_create_and_list_ideas(client):
    assert client.get("/api/ideas").json() == []

    r = client.post("/api/ideas", json={"content": "ship it"})
    assert r.status_code == 201
    body = r.json()
    assert body["content"] == "ship it"
    assert "id" in body and "created_at" in body

    ideas = client.get("/api/ideas").json()
    assert len(ideas) == 1
    assert ideas[0]["content"] == "ship it"


def test_empty_content_rejected(client):
    r = client.post("/api/ideas", json={"content": ""})
    assert r.status_code == 422  # pydantic min_length validation


def test_get_single_idea(client):
    idea_id = client.post("/api/ideas", json={"content": "read me"}).json()["id"]

    r = client.get(f"/api/ideas/{idea_id}")
    assert r.status_code == 200
    assert r.json()["content"] == "read me"


def test_get_missing_idea_404(client):
    assert client.get("/api/ideas/999").status_code == 404


def test_update_idea(client):
    idea_id = client.post("/api/ideas", json={"content": "before"}).json()["id"]

    r = client.put(f"/api/ideas/{idea_id}", json={"content": "after"})
    assert r.status_code == 200
    assert r.json()["content"] == "after"

    # persisted
    assert client.get(f"/api/ideas/{idea_id}").json()["content"] == "after"


def test_update_missing_idea_404(client):
    assert client.put("/api/ideas/999", json={"content": "x"}).status_code == 404


def test_update_empty_content_rejected(client):
    idea_id = client.post("/api/ideas", json={"content": "keep"}).json()["id"]
    assert client.put(f"/api/ideas/{idea_id}", json={"content": ""}).status_code == 422


def test_delete_idea(client):
    idea_id = client.post("/api/ideas", json={"content": "remove me"}).json()["id"]

    r = client.delete(f"/api/ideas/{idea_id}")
    assert r.status_code == 200
    assert r.json() == {"deleted": idea_id}

    # gone
    assert client.get(f"/api/ideas/{idea_id}").status_code == 404
    assert client.get("/api/ideas").json() == []


def test_delete_missing_idea_404(client):
    assert client.delete("/api/ideas/999").status_code == 404
