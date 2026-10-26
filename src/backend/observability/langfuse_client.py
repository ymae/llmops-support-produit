"""Client d'observabilité cognitive Langfuse auto-hébergé en local (Niveau 2).

Ce module gère la création et le vidage (`flush`) du `CallbackHandler` Langfuse
pour LangChain, en garantissant que les traces restent strictement locales
(`http://localhost:3000` ou `http://langfuse-server:3000`) et ne bloquent jamais
le flux métier en cas d'indisponibilité temporaire du conteneur Langfuse.
"""

from typing import Optional

from langfuse.callback import CallbackHandler

from src.backend.core.config import Settings
from src.backend.core.schemas import ChatRequest
from src.backend.observability.logger import log_structured_event


def create_langfuse_handler(
    request: ChatRequest,
    trace_id: str,
    settings: Settings,
) -> Optional[CallbackHandler]:
    """Instancie le `CallbackHandler` Langfuse pointant vers le serveur local.

    Si l'observabilité Langfuse est désactivée dans la configuration, ou si une
    erreur d'initialisation survient, retourne `None` sans interrompre le flux métier.

    Args:
        request: Requête `ChatRequest` contenant les identifiants de session et d'opérateur.
        trace_id: Identifiant unique de corrélation généré pour la requête.
        settings: Instance de configuration `Settings`.

    Returns:
        Une instance de `CallbackHandler` configurée pour Langfuse local, ou `None`.
    """
    if not settings.langfuse_enabled:
        return None

    try:
        # Configuration explicite vers l'instance auto-hébergée locale
        handler = CallbackHandler(
            public_key=settings.langfuse_public_key,
            secret_key=settings.langfuse_secret_key,
            host=settings.langfuse_host,
            session_id=request.session_id,
            user_id=request.operator_id,
            trace_name="nexus_support_v1_chat",
            tags=[
                request.client_id,
                request.severity.value,
                request.operator_role.value,
                "v1-baseline",
            ],
            metadata={
                "trace_id": trace_id,
                "client_id": request.client_id,
                "severity": request.severity.value,
                "operator_id": request.operator_id,
                "operator_role": request.operator_role.value,
                "architecture_version": "V1_BASELINE",
            },
        )
        return handler
    except Exception as exc:
        # En cas d'indisponibilité de Langfuse local, on journalise un avertissement
        log_structured_event(
            event="langfuse_init_warning",
            message=f"Impossible d'initialiser le CallbackHandler Langfuse local : {exc}",
            level="WARNING",
            session_id=request.session_id,
            operator_id=request.operator_id,
            operator_role=request.operator_role.value,
            client_id=request.client_id,
            severity=request.severity.value,
            trace_id=trace_id,
        )
        return None


def flush_langfuse_handler(
    handler: Optional[CallbackHandler],
    request: ChatRequest,
    trace_id: str,
) -> None:
    """Force l'envoi asynchrone non bloquant des événements vers Langfuse local.

    Args:
        handler: Instance optionnelle de `CallbackHandler` à vider.
        request: Requête `ChatRequest` associée pour la journalisation en cas d'alerte.
        trace_id: Identifiant unique de corrélation.

    Returns:
        None.
    """
    if handler is None:
        return

    try:
        handler.flush()
    except Exception as flush_exc:
        log_structured_event(
            event="langfuse_flush_warning",
            message=f"Avertissement lors du flush Langfuse local : {flush_exc}",
            level="WARNING",
            session_id=request.session_id,
            operator_id=request.operator_id,
            operator_role=request.operator_role.value,
            client_id=request.client_id,
            severity=request.severity.value,
            trace_id=trace_id,
        )
