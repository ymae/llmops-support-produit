"""Tests d'intégration conteneurisés pour le microservice Backend API.

Ces tests ne s'exécutent que lorsque la variable `RUN_CONTAINER_TESTS=true` est
définie (par exemple lors de l'exécution de `make tests` via Docker Compose).
"""

import os

import httpx
import pytest


RUN_CONTAINER_TESTS: bool = os.getenv("RUN_CONTAINER_TESTS") == "true"
BACKEND_API_URL: str = os.getenv("BACKEND_API_URL", "http://backend-api:8080").rstrip("/")

pytestmark = pytest.mark.skipif(
    not RUN_CONTAINER_TESTS,
    reason="Ces tests sont destinés au conteneur d'intégration Docker (RUN_CONTAINER_TESTS=true).",
)


@pytest.mark.asyncio
async def test_container_health_and_jwt_auth_flow() -> None:
    """Vérifie en conditions réelles Docker la sonde `/health`, l'émission JWT et `/api/v1/history`.

    Args:
        Aucun argument requis.

    Returns:
        None.
    """
    async with httpx.AsyncClient(timeout=30.0) as client:
        health_res = await client.get(f"{BACKEND_API_URL}/health")
        health_res.raise_for_status()
        assert health_res.json()["status"] == "ok"

        login_res = await client.post(
            f"{BACKEND_API_URL}/api/v1/auth/login",
            json={"username": "agent", "password": "agent-pass"},
        )
        login_res.raise_for_status()
        token = login_res.json()["access_token"]
        headers = {"Authorization": f"Bearer {token}"}

        me_res = await client.get(f"{BACKEND_API_URL}/api/v1/auth/me", headers=headers)
        me_res.raise_for_status()
        assert me_res.json()["username"] == "agent"

        hist_res = await client.get(
            f"{BACKEND_API_URL}/api/v1/history/sess-docker-check",
            headers=headers,
        )
        hist_res.raise_for_status()
        assert hist_res.json()["history"] == []
