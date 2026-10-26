"""Suite de tests unitaires et fonctionnels du Backend API.

(a) Sécurité API : rejet HTTP 401/403 si le Bearer Token ou JWT est absent ou invalide,
    avec vérification de l'écriture dans le Logger JSON structuré.
(b) Contrat Pydantic : rejet HTTP 422 des payloads malformés ou d'un `client_id`
    non conforme (ex: `CLI-099` du cas `GD-08`), et validation du contrat de sortie.
(c) Flux nominal mocké : appel de `POST /api/v1/chat` en simulant la réponse de
    `litellm-proxy`, contrôle de `ChatResponse` et des traces dans `logs/app.jsonl`.
(d) Gestion fine des erreurs fournisseur : HTTP 429 (Rate Limit) et HTTP 502 (Bad Gateway).
"""

from collections.abc import Callable
from typing import Any
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.backend.core.config import Settings
from src.backend.core.schemas import ChatResponse, SeverityLevel


def build_valid_chat_payload(
    client_id: str = "CLI-003",
    severity: str = "MEDIUM",
    operator_id: str = "agent",
    operator_role: str = "AGENT",
    message: str = (
        "Le service plante au démarrage avec le message : "
        "ImportError: cannot import name 'DataConnector' from 'nexus.core'."
    ),
) -> dict[str, Any]:
    """Construit un payload JSON valide inspiré du Golden Dataset (GD-01 par défaut).

    Args:
        client_id: Identifiant du client cible (`CLI-001` à `CLI-015`).
        severity: Niveau de criticité du ticket (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
        operator_id: Identifiant de l'opérateur support.
        operator_role: Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).
        message: Question ou symptôme soumis par l'agent support.

    Returns:
        Un dictionnaire représentant un corps de requête `ChatRequest` valide.
    """
    return {
        "session_id": "sess-pytest-gd01",
        "operator_id": operator_id,
        "operator_role": operator_role,
        "client_id": client_id,
        "severity": severity,
        "message": message,
        "history": [
            {"role": "user", "content": "Bonjour, j'ouvre un ticket pour ce client."},
            {"role": "assistant", "content": "Bonjour, quel est le symptôme observé ?"},
        ],
    }


@pytest.mark.asyncio
async def test_health_endpoint_returns_ok(async_client: httpx.AsyncClient) -> None:
    """Vérifie que la sonde `GET /health` répond `HTTP 200` avec le statut `ok`.

    Args:
        async_client: Client HTTP asynchrone de test branché sur FastAPI.

    Returns:
        None.
    """
    response = await async_client.get("/health")
    assert response.status_code == 200
    data = response.json()
    assert data["status"] == "ok"
    assert data["service"] == "nexus-support-backend-api"


# ==============================================================================
# (a) Tests de Sécurité API (HTTPBearer : 401 Unauthorized / 403 Forbidden)
# ==============================================================================


@pytest.mark.asyncio
async def test_chat_rejects_missing_bearer_token_with_401_and_logs(
    async_client: httpx.AsyncClient,
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie le rejet `HTTP 401` en l'absence d'en-tête Authorization Bearer.

    Contrôle également qu'une entrée `auth_missing_token` est écrite dans le
    fichier du Logger JSON structuré.

    Args:
        async_client: Client HTTP asynchrone de test.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    payload = build_valid_chat_payload()
    response = await async_client.post("/api/v1/chat", json=payload)

    assert response.status_code == 401
    logs = read_json_logs()
    assert len(logs) == 1
    assert logs[0]["event"] == "auth_missing_token"
    assert logs[0]["level"] == "WARNING"
    assert logs[0]["status_code"] == 401


@pytest.mark.asyncio
async def test_chat_rejects_invalid_bearer_token_with_403_and_logs(
    async_client: httpx.AsyncClient,
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie le rejet `HTTP 403` lorsqu'un Bearer Token erroné est transmis.

    Contrôle également qu'une entrée `auth_invalid_token` est écrite dans le
    fichier du Logger JSON structuré.

    Args:
        async_client: Client HTTP asynchrone de test.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    payload = build_valid_chat_payload()
    invalid_headers = {"Authorization": "Bearer jeton-totalement-invalide"}

    response = await async_client.post(
        "/api/v1/chat",
        headers=invalid_headers,
        json=payload,
    )

    assert response.status_code == 403
    logs = read_json_logs()
    assert len(logs) == 1
    assert logs[0]["event"] == "auth_invalid_token"
    assert logs[0]["level"] == "WARNING"
    assert logs[0]["status_code"] == 403


# ==============================================================================
# (b) Tests du Contrat Pydantic (Rejet CLI-099 / GD-08 et payloads malformés)
# ==============================================================================


@pytest.mark.asyncio
async def test_chat_rejects_unknown_client_id_cli_099_gd08(
    async_client: httpx.AsyncClient,
    valid_auth_headers: dict[str, str],
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie le rejet `HTTP 422` pour le client inconnu `CLI-099` (cas `GD-08`).

    S'assure que le validateur Pydantic bloque la requête avant tout appel au LLM
    et que le Logger JSON enregistre l'événement `validation_error` avec `CLI-099`.

    Args:
        async_client: Client HTTP asynchrone de test.
        valid_auth_headers: En-tête HTTP Bearer valide.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    gd08_payload = build_valid_chat_payload(
        client_id="CLI-099",
        severity="MEDIUM",
        message="Notre port 8080 est occupé lors de l'installation, que faire ?",
    )

    response = await async_client.post(
        "/api/v1/chat",
        headers=valid_auth_headers,
        json=gd08_payload,
    )

    assert response.status_code == 422
    error_detail = str(response.json())
    assert "CLI-099" in error_detail

    # Vérification de la trace d'audit dans le Logger JSON structuré
    logs = read_json_logs()
    assert len(logs) == 1
    assert logs[0]["event"] == "validation_error"
    assert logs[0]["client_id"] == "CLI-099"
    assert logs[0]["status_code"] == 422


@pytest.mark.asyncio
async def test_chat_rejects_malformed_payload_and_blank_message(
    async_client: httpx.AsyncClient,
    valid_auth_headers: dict[str, str],
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie le rejet `HTTP 422` si la sévérité est invalide ou le message vide.

    Args:
        async_client: Client HTTP asynchrone de test.
        valid_auth_headers: En-tête HTTP Bearer valide.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    malformed_payload = {
        "session_id": "sess-bad",
        "operator_id": "agent",
        "operator_role": "AGENT",
        "client_id": "CLI-001",
        "severity": "ULTRA_CRITICAL_INVALID",
        "message": "   ",
    }

    response = await async_client.post(
        "/api/v1/chat",
        headers=valid_auth_headers,
        json=malformed_payload,
    )

    assert response.status_code == 422
    logs = read_json_logs()
    assert len(logs) == 1
    assert logs[0]["event"] == "validation_error"


# ==============================================================================
# (c) Tests du Flux Nominal et Critique Mocké (/api/v1/chat + Logger JSON)
# ==============================================================================


@pytest.mark.asyncio
async def test_chat_nominal_flow_mocked_litellm_and_json_logs(
    async_client: httpx.AsyncClient,
    valid_auth_headers: dict[str, str],
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie le flux nominal `POST /api/v1/chat` en mockant `litellm-proxy` (cas GD-01).

    Contrôle la conformité stricte de la réponse au schéma `ChatResponse` ainsi que
    l'écriture des événements `chat_request_received` et `chat_response_success`
    dans le Logger JSON structuré.

    Args:
        async_client: Client HTTP asynchrone de test.
        valid_auth_headers: En-tête HTTP Bearer valide.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    mocked_llm_answer = (
        "En version 3.1.0, l'erreur ImportError sur DataConnector correspond à un "
        "changement d'espace de nommage (`from nexus.connectors import DataConnector`). "
        "Veuillez vérifier la version exacte du client CLI-003 avant d'envoyer cette réponse."
    )

    with patch(
        "src.backend.core.chains.invoke_litellm_chat",
        new=AsyncMock(return_value=mocked_llm_answer),
    ) as mock_litellm:
        payload = build_valid_chat_payload(
            client_id="CLI-003",
            severity="MEDIUM",
            operator_id="agent",
            operator_role="AGENT",
        )
        response = await async_client.post(
            "/api/v1/chat",
            headers=valid_auth_headers,
            json=payload,
        )

    assert response.status_code == 200
    mock_litellm.assert_awaited_once()

    # Validation stricte du contrat de sortie via Pydantic
    parsed_response = ChatResponse.model_validate(response.json())
    assert parsed_response.answer == mocked_llm_answer
    assert parsed_response.client_context.client_id == "CLI-003"
    assert parsed_response.client_context.severity == SeverityLevel.MEDIUM
    assert parsed_response.sources == []
    assert parsed_response.requires_human_validation is True
    assert parsed_response.escalation_required is False
    assert parsed_response.trace_id.startswith("trace-")

    # Vérification des traces écrites dans le fichier JSONL local
    logs = read_json_logs()
    assert len(logs) == 2
    assert logs[0]["event"] == "chat_request_received"
    assert logs[0]["client_id"] == "CLI-003"
    assert logs[0]["operator_id"] == "agent"
    assert logs[0]["operator_role"] == "AGENT"

    assert logs[1]["event"] == "chat_response_success"
    assert logs[1]["trace_id"] == parsed_response.trace_id
    assert logs[1]["status_code"] == 200
    assert logs[1]["extra"]["requires_human_validation"] is True
    assert logs[1]["extra"]["escalation_required"] is False


@pytest.mark.asyncio
async def test_chat_critical_severity_triggers_escalation_gd03_gd05(
    async_client: httpx.AsyncClient,
    valid_auth_headers: dict[str, str],
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie qu'un ticket `CRITICAL` déclenche `escalation_required=True` (GD-03/GD-05).

    Args:
        async_client: Client HTTP asynchrone de test.
        valid_auth_headers: En-tête HTTP Bearer valide.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    with patch(
        "src.backend.core.chains.invoke_litellm_chat",
        new=AsyncMock(
            return_value="Incident critique détecté : escalade immédiate vers le Responsable Support."
        ),
    ):
        payload = build_valid_chat_payload(
            client_id="CLI-010",
            severity="CRITICAL",
            operator_id="manager",
            operator_role="MANAGER",
            message=(
                "Faille d'isolation : un collaborateur ayant uniquement le rôle "
                "'Viewer' peut modifier et supprimer des ressources en production !"
            ),
        )
        response = await async_client.post(
            "/api/v1/chat",
            headers=valid_auth_headers,
            json=payload,
        )

    assert response.status_code == 200
    parsed_response = ChatResponse.model_validate(response.json())
    assert parsed_response.requires_human_validation is True
    assert parsed_response.escalation_required is True

    logs = read_json_logs()
    assert logs[-1]["event"] == "chat_response_success"
    assert logs[-1]["extra"]["escalation_required"] is True


# ==============================================================================
# (d) Tests de Gestion des Erreurs LLM (429 Rate Limit et 502 Bad Gateway)
# ==============================================================================


@pytest.mark.asyncio
async def test_chat_returns_429_when_provider_rate_limit_reached(
    async_client: httpx.AsyncClient,
    valid_auth_headers: dict[str, str],
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie le retour `HTTP 429` et la trace `llm_rate_limit_error` en cas de Rate Limit Groq.

    Args:
        async_client: Client HTTP asynchrone de test.
        valid_auth_headers: En-tête HTTP Bearer valide.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """

    class FakeRateLimitError(Exception):
        """Exception simulée portant un attribut `status_code = 429` comme le SDK OpenAI/Groq."""

        status_code = 429

    with patch(
        "src.backend.core.chains.invoke_litellm_chat",
        new=AsyncMock(side_effect=FakeRateLimitError("Rate limit exceeded")),
    ):
        payload = build_valid_chat_payload()
        response = await async_client.post(
            "/api/v1/chat",
            headers=valid_auth_headers,
            json=payload,
        )

    assert response.status_code == 429
    logs = read_json_logs()
    assert len(logs) == 2
    assert logs[1]["event"] == "llm_rate_limit_error"
    assert logs[1]["level"] == "WARNING"
    assert logs[1]["status_code"] == 429


@pytest.mark.asyncio
async def test_chat_returns_502_and_logs_when_litellm_proxy_fails(
    async_client: httpx.AsyncClient,
    valid_auth_headers: dict[str, str],
    read_json_logs: Callable[[], list[dict[str, Any]]],
) -> None:
    """Vérifie le retour `HTTP 502` et la trace `llm_inference_error` si LiteLLM échoue.

    Args:
        async_client: Client HTTP asynchrone de test.
        valid_auth_headers: En-tête HTTP Bearer valide.
        read_json_logs: Fixture de lecture des traces JSONL générées.

    Returns:
        None.
    """
    with patch(
        "src.backend.core.chains.invoke_litellm_chat",
        new=AsyncMock(side_effect=RuntimeError("Connexion refusée vers litellm-proxy:4000")),
    ):
        payload = build_valid_chat_payload()
        response = await async_client.post(
            "/api/v1/chat",
            headers=valid_auth_headers,
            json=payload,
        )

    assert response.status_code == 502
    logs = read_json_logs()
    assert len(logs) == 2
    assert logs[1]["event"] == "llm_inference_error"
    assert logs[1]["level"] == "ERROR"
    assert logs[1]["status_code"] == 502
