import pytest_asyncio
from httpx import AsyncClient

from app.api import airflow_dags
from app.config import get_settings
from app.db.database import create_default_admin
from app.services.orchestration.airflow_backend import AirflowBackend


@pytest_asyncio.fixture
async def admin_headers(client: AsyncClient) -> dict[str, str]:
    await create_default_admin()
    settings = get_settings()
    response = await client.post(
        "/api/v1/auth/login",
        json={"username": settings.ADMIN_USERNAME, "password": settings.ADMIN_PASSWORD},
    )
    assert response.status_code == 200
    return {"Authorization": f"Bearer {response.json()['access_token']}"}


class TestAirflowDagsAPI:
    async def test_list_dags_requires_authentication(self, client: AsyncClient):
        response = await client.get("/api/v1/data/airflow/dags")

        assert response.status_code == 401

    async def test_orchestration_status_requires_authentication(self, client: AsyncClient):
        response = await client.get("/api/v1/data/airflow/orchestration/status")

        assert response.status_code == 401

    async def test_non_admin_user_is_forbidden_from_all_airflow_endpoints(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ):
        endpoints = [
            ("GET", "/api/v1/data/airflow/dags"),
            ("GET", "/api/v1/data/airflow/dags/dag_stock_zh_a_hist"),
            ("POST", "/api/v1/data/airflow/dags/dag_stock_zh_a_hist/trigger"),
            ("PATCH", "/api/v1/data/airflow/dags/dag_stock_zh_a_hist/pause"),
            ("GET", "/api/v1/data/airflow/dags/dag_stock_zh_a_hist/runs"),
            ("GET", "/api/v1/data/airflow/dags/dag_stock_zh_a_hist/runs/run_1/tasks"),
            (
                "GET",
                "/api/v1/data/airflow/dags/dag_stock_zh_a_hist/runs/run_1/tasks/t1/logs",
            ),
            ("GET", "/api/v1/data/airflow/orchestration/status"),
        ]
        for method, url in endpoints:
            resp = await client.request(method, url, headers=auth_headers)
            assert resp.status_code == 403, (
                f"expected 403 for {method} {url}, got {resp.status_code}"
            )

    async def test_admin_can_access_and_invalid_identifiers_are_rejected(
        self, client: AsyncClient, admin_headers: dict[str, str]
    ):
        class _FakeAdapter:
            async def list_dags(self, **kwargs):
                return {"dags": []}

            async def get_dag(self, dag_id: str):
                return {"dag_id": dag_id}

            async def trigger_dag_run(self, dag_id: str, conf=None):
                return {"dag_id": dag_id, "conf": conf}

            async def get_task_log(
                self, dag_id: str, dag_run_id: str, task_id: str, try_number: int
            ):
                return f"log:{dag_id}:{dag_run_id}:{task_id}:{try_number}"

        backend = object.__new__(AirflowBackend)
        backend._adapter = _FakeAdapter()
        prev = airflow_dags._orchestration_backend
        airflow_dags.set_orchestration_backend(backend)
        try:
            ok_resp = await client.get(
                "/api/v1/data/airflow/dags/dag_stock_zh_a_hist/runs/manual__2026-11-20T12:00:00+00:00/tasks/task_1/logs",
                headers=admin_headers,
            )
            assert ok_resp.status_code == 200
            assert "log:dag_stock_zh_a_hist:" in ok_resp.json()["log"]

            for bad_url in (
                "/api/v1/data/airflow/dags/bad..dag",
                "/api/v1/data/airflow/dags/bad;dag/trigger",
                "/api/v1/data/airflow/dags/dag_1/runs/bad..run/tasks",
                "/api/v1/data/airflow/dags/dag_1/runs/run_1/tasks/bad$task/logs",
            ):
                method = "POST" if bad_url.endswith("/trigger") else "GET"
                resp = await client.request(method, bad_url, headers=admin_headers)
                assert resp.status_code == 422, (
                    f"expected 422 for {bad_url}, got {resp.status_code}"
                )
        finally:
            airflow_dags.set_orchestration_backend(prev)
