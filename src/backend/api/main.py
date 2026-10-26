"""Point d'entrée principal du microservice FastAPI (Backend API).

Ce module expose :
- `GET /health` : sonde de disponibilité du conteneur `backend-api`.
- `POST /api/v1/auth/login` : authentification opérateur et émission d'un jeton JWT signé (HS256).
- `GET /api/v1/auth/me` : vérification du jeton Bearer / JWT et restitution du profil opérateur.
- `POST /api/v1/chat` : route métier sécurisée par `HTTPBearer`, validée par
  Pydantic (`ChatRequest` / `ChatResponse`), orchestrée par LangChain et tracée
  dans le Logger JSON structuré ainsi que dans Langfuse local.
- `GET /api/v1/history/{session_id}` : consultation de l'historique conversationnel d'une session.
- `DELETE /api/v1/history/{session_id}` : réinitialisation de l'historique d'une session.
"""

from typing import Any

from fastapi import Depends, FastAPI, HTTPException, Request, status
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse

from src.backend.api.dependencies import get_current_operator, run_llm_safely
from src.backend.core.chains import generate_chat_response
from src.backend.core.schemas import (
    ChatRequest,
    ChatResponse,
    HistoryResponse,
    LoginRequest,
    OperatorUser,
    TokenResponse,
)
from src.backend.core.security import (
    authenticate_operator_credentials,
    create_access_token,
    verify_bearer_token,
)
from src.backend.memory import session_memory
from src.backend.observability.logger import log_structured_event


# Instanciation de l'application FastAPI
app = FastAPI(
    title="API Backend pour l'assistant Support Produit Nexus",
    description=(
        "API Backend pour l'assistant Support Produit Nexus "
        "destiné aux agents et responsables du support technique."
    ),
    version="1.0.0",
)


@app.exception_handler(RequestValidationError)
async def validation_exception_handler(
    request: Request,
    exc: RequestValidationError,
) -> JSONResponse:
    """Intercepte et journalise toutes les erreurs de validation du contrat Pydantic.

    Permet de tracer dans `logs/app.jsonl` les rejets déterministes d'entrée
    (notamment le cas `CLI-099` / `GD-08` ou les payloads incomplets) avant
    tout appel au modèle LLM.

    Args:
        request: Objet `Request` HTTP FastAPI.
        exc: Exception `RequestValidationError` levée par Pydantic/FastAPI.

    Returns:
        Une réponse `JSONResponse` avec le code `HTTP 422 Unprocessable Entity`.
    """
    # Extraction prudente des métadonnées présentes dans le corps de la requête
    body_data: dict[str, Any] = exc.body if isinstance(exc.body, dict) else {}
    raw_session_id = body_data.get("session_id")
    raw_operator_id = body_data.get("operator_id")
    raw_operator_role = body_data.get("operator_role")
    raw_client_id = body_data.get("client_id")
    raw_severity = body_data.get("severity")

    # Sérialisation propre des détails d'erreur Pydantic pour l'audit JSON
    sanitized_errors = [
        {
            "loc": [str(item) for item in err.get("loc", [])],
            "msg": str(err.get("msg", "")),
            "type": str(err.get("type", "")),
        }
        for err in exc.errors()
    ]

    log_structured_event(
        event="validation_error",
        message="Rejet du contrat d'entrée Pydantic sur la requête API.",
        level="WARNING",
        session_id=str(raw_session_id) if raw_session_id else None,
        operator_id=str(raw_operator_id) if raw_operator_id else None,
        operator_role=str(raw_operator_role) if raw_operator_role else None,
        client_id=str(raw_client_id) if raw_client_id else None,
        severity=str(raw_severity) if raw_severity else None,
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        extra_data={
            "path": str(request.url.path),
            "errors": sanitized_errors,
        },
    )

    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_CONTENT,
        content={"detail": sanitized_errors},
    )


@app.get("/health", tags=["Monitoring"])
async def health_check() -> dict[str, str]:
    """Vérifie l'état de santé du microservice Backend API.

    Args:
        Aucun argument requis.

    Returns:
        Un dictionnaire indiquant le statut opérationnel et la version du service.
    """
    return {
        "status": "ok",
        "service": "nexus-support-backend-api",
        "version": "1.0.0-baseline",
    }


@app.post(
    "/api/v1/auth/login",
    response_model=TokenResponse,
    status_code=status.HTTP_200_OK,
    tags=["Authentification"],
)
async def login_endpoint(credentials: LoginRequest) -> TokenResponse:
    """Authentifie un opérateur support (`agent` ou `manager`) et délivre un jeton JWT signé (HS256).

    Args:
        credentials: Couple identifiant/mot de passe soumis par l'opérateur.

    Returns:
        Un objet `TokenResponse` contenant le jeton JWT signé et le rôle de l'opérateur.

    Raises:
        HTTPException: `401 Unauthorized` si les identifiants sont incorrects.
    """
    operator_user = authenticate_operator_credentials(
        credentials.username,
        credentials.password,
    )
    if operator_user is None:
        log_structured_event(
            event="auth_login_failed",
            message="Échec d'authentification opérateur sur /api/v1/auth/login.",
            level="WARNING",
            operator_id=credentials.username,
            status_code=status.HTTP_401_UNAUTHORIZED,
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Identifiant ou mot de passe opérateur incorrect.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    access_token = create_access_token(
        operator_id=operator_user.username,
        operator_role=operator_user.role,
    )
    log_structured_event(
        event="auth_login_success",
        message="Authentification opérateur réussie et émission du jeton JWT HS256.",
        level="INFO",
        operator_id=operator_user.username,
        operator_role=operator_user.role.value,
        status_code=status.HTTP_200_OK,
    )
    return TokenResponse(
        access_token=access_token,
        operator_id=operator_user.username,
        operator_role=operator_user.role,
    )


@app.get(
    "/api/v1/auth/me",
    response_model=OperatorUser,
    status_code=status.HTTP_200_OK,
    tags=["Authentification"],
)
async def me_endpoint(
    current_operator: OperatorUser = Depends(get_current_operator),
) -> OperatorUser:
    """Retourne le profil de l'opérateur authentifié par son jeton Bearer / JWT.

    Args:
        current_operator: Profil extrait du jeton validé par `get_current_operator`.

    Returns:
        L'objet `OperatorUser` contenant `username` et `role`.
    """
    return current_operator


@app.post(
    "/api/v1/chat",
    response_model=ChatResponse,
    status_code=status.HTTP_200_OK,
    tags=["Support Copilot"],
)
async def chat_endpoint(
    payload: ChatRequest,
    _token: str = Depends(verify_bearer_token),
) -> ChatResponse:
    """Traite une requête conversationnelle d'un agent ou responsable support.

    Cette route :
    1. Vérifie le jeton Bearer / JWT via la dépendance `verify_bearer_token`.
    2. Valide strictement le payload d'entrée via le schéma `ChatRequest`.
    3. Journalise la réception du ticket dans `logs/app.jsonl`.
    4. Appelle `generate_chat_response` via `run_llm_safely` (LangChain -> LiteLLM Proxy -> Groq + Langfuse local).
    5. Journalise le succès technique (`HTTP 200`) et retourne `ChatResponse`.

    Args:
        payload: Requête support validée par Pydantic (`ChatRequest`).
        _token: Jeton d'authentification Bearer ou JWT validé par `verify_bearer_token`.

    Returns:
        Un objet `ChatResponse` contenant la réponse, le contexte client,
        les indicateurs de gouvernance humaine et le `trace_id`.

    Raises:
        HTTPException: `413`/`429` en cas de limite fournisseur ou `502 Bad Gateway`
            si la passerelle LiteLLM Proxy est injoignable.
    """
    # Journalisation de la requête entrante validée
    log_structured_event(
        event="chat_request_received",
        message="Réception d'une requête support valide sur /api/v1/chat.",
        level="INFO",
        session_id=payload.session_id,
        operator_id=payload.operator_id,
        operator_role=payload.operator_role.value,
        client_id=payload.client_id,
        severity=payload.severity.value,
        status_code=status.HTTP_200_OK,
        extra_data={"history_length": len(payload.history)},
    )

    # Orchestration LangChain, LiteLLM & Langfuse
    response = await run_llm_safely(
        action=lambda: generate_chat_response(payload),
        payload=payload,
    )

    # Clôture de la trace système dans le Logger JSON
    log_structured_event(
        event="chat_response_success",
        message="Réponse générée et validée avec succès pour l'agent support.",
        level="INFO",
        session_id=payload.session_id,
        operator_id=payload.operator_id,
        operator_role=payload.operator_role.value,
        client_id=payload.client_id,
        severity=payload.severity.value,
        trace_id=response.trace_id,
        status_code=status.HTTP_200_OK,
        extra_data={
            "requires_human_validation": response.requires_human_validation,
            "escalation_required": response.escalation_required,
            "sources_count": len(response.sources),
        },
    )

    return response


@app.get(
    "/api/v1/history/{session_id}",
    response_model=HistoryResponse,
    status_code=status.HTTP_200_OK,
    tags=["Assistant Support"],
)
async def get_session_history_endpoint(
    session_id: str,
    _token: str = Depends(verify_bearer_token),
) -> HistoryResponse:
    """Retourne l'historique complet des échanges enregistrés pour une session support.

    Args:
        session_id: Identifiant unique de la session conversationnelle.
        _token: Jeton Bearer / JWT validé.

    Returns:
        Un objet `HistoryResponse` contenant les entrées de la session.
    """
    entries = session_memory.get_history(session_id)
    return HistoryResponse(session_id=session_id, history=entries)


@app.delete(
    "/api/v1/history/{session_id}",
    status_code=status.HTTP_200_OK,
    tags=["Assistant Support"],
)
async def clear_session_history_endpoint(
    session_id: str,
    _token: str = Depends(verify_bearer_token),
) -> dict[str, str]:
    """Efface l'historique en mémoire d'une session support donnée.

    Args:
        session_id: Identifiant unique de la session conversationnelle à purger.
        _token: Jeton Bearer / JWT validé.

    Returns:
        Un dictionnaire confirmant la suppression de l'historique de la session.
    """
    session_memory.clear_history(session_id)
    return {"status": "cleared", "session_id": session_id}
