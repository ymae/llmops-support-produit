"""Dépendances FastAPI et gestionnaire d'erreurs d'inférence LLM - Support Produit Nexus.

Ce module intercepte proprement les erreurs de quotas/limites du fournisseur (`413`, `429`)
et les pannes de passerelle (`502`), tout en les journalisant dans le Logger JSONL local.
"""

from collections.abc import Awaitable, Callable
from typing import TypeVar

from fastapi import Depends, HTTPException, Request, status

from src.backend.core.config import get_settings
from src.backend.core.schemas import ChatRequest, OperatorRole, OperatorUser
from src.backend.core.security import verify_bearer_token
from src.backend.observability.logger import log_structured_event


T = TypeVar("T")


async def get_current_operator(
    request: Request,
    _token: str = Depends(verify_bearer_token),
) -> OperatorUser:
    """Retourne le profil `OperatorUser` extrait lors de la validation du Bearer Token / JWT.

    Args:
        request: Objet `Request` HTTP contenant `request.state.operator_user`.
        _token: Jeton Bearer validé par la dépendance `verify_bearer_token`.

    Returns:
        L'instance `OperatorUser` correspondant à l'opérateur authentifié.
    """
    operator_user = getattr(request.state, "operator_user", None)
    if isinstance(operator_user, OperatorUser):
        return operator_user

    settings = get_settings()
    return OperatorUser(
        username=settings.agent_username,
        role=OperatorRole.AGENT,
    )


async def run_llm_safely(
    action: Callable[[], Awaitable[T]],
    payload: ChatRequest,
) -> T:
    """Exécute une action asynchrone d'inférence LLM et convertit ses erreurs en `HTTPException`.

    - Si le fournisseur (Groq via LiteLLM) renvoie un code `413` ou `429` (requête
      trop volumineuse ou limite de débit atteinte), journalise `llm_rate_limit_error`
      et renvoie le code HTTP correspondant avec un message clair.
    - Pour toute autre erreur, journalise `llm_inference_error` dans `logs/app.jsonl`
      et renvoie `HTTP 502 Bad Gateway`.

    Args:
        action: Coroutine sans argument exécutant l'appel à la chaîne LLM.
        payload: Requête `ChatRequest` associée pour enrichir les traces JSONL.

    Returns:
        Le résultat produit par `action()`.

    Raises:
        HTTPException: `413` / `429` en cas de limite fournisseur, ou `502` sinon.
    """
    try:
        return await action()
    except Exception as exc:
        provider_status = getattr(exc, "status_code", None)
        if provider_status in (
            status.HTTP_413_CONTENT_TOO_LARGE,
            status.HTTP_429_TOO_MANY_REQUESTS,
        ):
            log_structured_event(
                event="llm_rate_limit_error",
                message=f"Limite du fournisseur LLM atteinte (HTTP {provider_status}) : {exc}",
                level="WARNING",
                session_id=payload.session_id,
                operator_id=payload.operator_id,
                operator_role=payload.operator_role.value,
                client_id=payload.client_id,
                severity=payload.severity.value,
                status_code=provider_status,
            )
            raise HTTPException(
                status_code=provider_status,
                detail="Limite du fournisseur de modèle atteinte. Veuillez réessayer dans une minute.",
            ) from exc

        log_structured_event(
            event="llm_inference_error",
            message=f"Échec lors de l'appel à LiteLLM Proxy : {exc}",
            level="ERROR",
            session_id=payload.session_id,
            operator_id=payload.operator_id,
            operator_role=payload.operator_role.value,
            client_id=payload.client_id,
            severity=payload.severity.value,
            status_code=status.HTTP_502_BAD_GATEWAY,
        )
        raise HTTPException(
            status_code=status.HTTP_502_BAD_GATEWAY,
            detail=f"Erreur de communication avec la passerelle d'inférence LLM : {exc}",
        ) from exc
