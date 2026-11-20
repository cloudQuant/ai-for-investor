"""Backend end-to-end smoke tests for Iteration 205.

These exercise the real ASGI app and the real in-memory database through HTTP
routes (not direct service calls).  They are deliberately small and
deterministic: authentication round-trip, workspace lifecycle, health and a
paper-runtime read.  Keep them free of external providers and local .env data.
"""

from __future__ import annotations

import uuid

import pytest

pytestmark = pytest.mark.e2e


async def test_e2e_health_endpoint(client):
    response = await client.get("/api/v1/health")
    assert response.status_code == 200
    payload = response.json()
    assert payload.get("status") in {"ok", "healthy", "degraded"} or "status" in payload


async def test_e2e_auth_register_login_refresh_and_me(client):
    username = f"e2e_{uuid.uuid4().hex[:10]}"
    password = "Test12345678!"
    email = f"{username}@example.com"

    registered = await client.post(
        "/api/v1/auth/register",
        json={"username": username, "email": email, "password": password},
    )
    assert registered.status_code in {200, 201}, registered.text

    login = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": password},
    )
    assert login.status_code == 200, login.text
    tokens = login.json()
    assert tokens["access_token"]
    assert tokens["refresh_token"]

    refreshed = await client.post(
        "/api/v1/auth/refresh",
        json={"refresh_token": tokens["refresh_token"]},
    )
    assert refreshed.status_code == 200, refreshed.text
    new_access = refreshed.json()["access_token"]

    me = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {new_access}"},
    )
    assert me.status_code == 200, me.text
    assert me.json()["username"] == username


async def test_e2e_workspace_create_list_and_get(client, auth_headers):
    created = await client.post(
        "/api/v1/workspace/",
        json={"name": "Iteration 205 e2e", "description": "http smoke"},
        headers=auth_headers,
    )
    assert created.status_code in {200, 201}, created.text
    workspace = created.json()
    workspace_id = workspace["id"]

    listed = await client.get("/api/v1/workspace/", headers=auth_headers)
    assert listed.status_code == 200, listed.text
    ids = {item["id"] for item in listed.json().get("items", listed.json())}
    assert workspace_id in ids

    fetched = await client.get(f"/api/v1/workspace/{workspace_id}", headers=auth_headers)
    assert fetched.status_code == 200, fetched.text
    assert fetched.json()["name"] == "Iteration 205 e2e"


async def test_e2e_paper_runtime_risk_rules_are_readable(client, auth_headers):
    response = await client.get("/api/v1/paper-runtimes/risk-rules/", headers=auth_headers)
    assert response.status_code == 200, response.text
    assert isinstance(response.json(), list)
