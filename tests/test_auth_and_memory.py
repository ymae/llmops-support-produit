"""Tests unitaires et fonctionnels de l'authentification JWT (HS256), du hachage PBKDF2 et de la mémoire de session.

Vérifie :
1. Le hachage et la vérification de mot de passe PBKDF2-SHA256 (`hash_password`, `verify_password`).
2. Le cycle complet d'authentification JWT (`POST /api/v1/auth/login` -> `GET /api/v1/auth/me` -> `POST /api/v1/chat`).
3. Le rejet `HTTP 403` avec journalisation JSONL pour un jeton JWT expiré.
4. L'isolation par `session_id` et la persistance thread-safe de l'historique (`GET /api/v1/history/{session_id}` et `DELETE /api/v1/history/{session_id}`).
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.backend.core.schemas import OperatorRole
from src.backend.core.security import (
    create_access_token,
    hash_password,
    verify_password,
)


def test_pbkdf2_password_hashing_and_verification() -> None:
    """Vérifie que `hash_password` et `verify_password` fonctionnent avec un sel unique.

    Args:
        Aucun argument requis.

    Returns:
        None.
    """
    hashed_1 = hash_password("mon-mot-de-passe-secret")
    hashed_2 = hash_password("mon-mot-de-passe-secret")

    # Deux hachages du même mot de passe doivent différer grâce au sel aléatoire
    assert hashed_1 != hashed_2
    assert verify_password("mon-mot-de-passe-secret", hashed_1) is True
    assert verify_password("mon-mot-de-passe-secret", hashed_2) is True
    assert verify_password("mauvais-mot-de-passe", hashed_1) is False
    assert verify_password("mon-mot-de-passe-secret", "format_invalide_sans_dollar") is False


@pytest.mark.asyncio
async def test_jwt_login_and_me_flow(
    async_client: httpx.AsyncClient,
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie la connexion via `POST /api/v1/auth/login` et la lecture du profil via `GET /api/v1/auth/me`.

    Args:
        async_client: Client HTTP asynchrone de test.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    # 1. Connexion réussie avec le profil Responsable Support (MANAGER)
    login_res = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "manager-pass"},
    )
    assert login_res.status_code == 200
    token_data = login_res.json()
    assert token_data["token_type"] == "bearer"
    assert token_data["operator_id"] == "manager"
    assert token_data["operator_role"] == "MANAGER"
    jwt_token = token_data["access_token"]

    # 2. Consultation de /api/v1/auth/me avec le jeton JWT signé
    me_res = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {jwt_token}"},
    )
    assert me_res.status_code == 200
    assert me_res.json() == {"username": "manager", "role": "MANAGER"}

    # 3. Tentative de connexion avec de mauvais identifiants -> HTTP 401
    bad_login = await async_client.post(
        "/api/v1/auth/login",
        json={"username": "manager", "password": "wrong-password"},
    )
    assert bad_login.status_code == 401

    logs = read_json_logs()
    events = [entry["event"] for entry in logs]
    assert "auth_login_success" in events
    assert "auth_login_failed" in events


@pytest.mark.asyncio
async def test_expired_jwt_is_rejected_with_403_and_logged(
    async_client: httpx.AsyncClient,
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie qu'un jeton JWT expiré est rejeté avec `HTTP 403` et tracé sous `auth_expired_jwt`.

    Args:
        async_client: Client HTTP asynchrone de test.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    expired_token = create_access_token(
        operator_id="agent",
        operator_role=OperatorRole.AGENT,
        expires_delta_minutes=-5,
    )

    response = await async_client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {expired_token}"},
    )
    assert response.status_code == 403
    logs = read_json_logs()
    assert len(logs) == 1
    assert logs[0]["event"] == "auth_expired_jwt"
    assert logs[0]["status_code"] == 403


@pytest.mark.asyncio
async def test_session_memory_is_isolated_and_persisted_across_chat_calls(
    async_client: httpx.AsyncClient,
    valid_jwt_headers: dict[str, str],
) -> None:
    """Vérifie que l'historique conversationnel est isolé par `session_id` et accessible via `/api/v1/history`.

    Args:
        async_client: Client HTTP asynchrone de test.
        valid_jwt_headers: En-têtes HTTP contenant un jeton JWT valide.

    Returns:
        None.
    """
    with patch(
        "src.backend.core.chains.invoke_litellm_chat",
        new=AsyncMock(side_effect=["Réponse pour session A", "Réponse pour session B"]),
    ):
        res_a = await async_client.post(
            "/api/v1/chat",
            headers=valid_jwt_headers,
            json={
                "session_id": "sess-alpha",
                "operator_id": "agent",
                "operator_role": "AGENT",
                "client_id": "CLI-003",
                "severity": "MEDIUM",
                "message": "Question de la session Alpha",
                "history": [],
            },
        )
        res_b = await async_client.post(
            "/api/v1/chat",
            headers=valid_jwt_headers,
            json={
                "session_id": "sess-beta",
                "operator_id": "manager",
                "operator_role": "MANAGER",
                "client_id": "CLI-004",
                "severity": "HIGH",
                "message": "Question de la session Beta",
                "history": [],
            },
        )

    assert res_a.status_code == 200
    assert res_b.status_code == 200

    # Vérification de l'isolation de l'historique entre sess-alpha et sess-beta
    hist_a = await async_client.get(
        "/api/v1/history/sess-alpha",
        headers=valid_jwt_headers,
    )
    hist_b = await async_client.get(
        "/api/v1/history/sess-beta",
        headers=valid_jwt_headers,
    )

    assert hist_a.status_code == 200
    assert hist_b.status_code == 200

    entries_a = hist_a.json()["history"]
    entries_b = hist_b.json()["history"]

    assert len(entries_a) == 2
    assert entries_a[0]["content"] == "Question de la session Alpha"
    assert entries_a[1]["content"] == "Réponse pour session A"
    assert entries_a[0]["client_id"] == "CLI-003"

    assert len(entries_b) == 2
    assert entries_b[0]["content"] == "Question de la session Beta"
    assert entries_b[1]["content"] == "Réponse pour session B"
    assert entries_b[0]["client_id"] == "CLI-004"

    # Suppression de l'historique de sess-alpha uniquement
    del_a = await async_client.delete(
        "/api/v1/history/sess-alpha",
        headers=valid_jwt_headers,
    )
    assert del_a.status_code == 200

    hist_a_after = await async_client.get(
        "/api/v1/history/sess-alpha",
        headers=valid_jwt_headers,
    )
    assert hist_a_after.json()["history"] == []
    # sess-beta reste intacte
    hist_b_after = await async_client.get(
        "/api/v1/history/sess-beta",
        headers=valid_jwt_headers,
    )
    assert len(hist_b_after.json()["history"]) == 2
