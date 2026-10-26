"""Chaînes LangChain (LCEL) et orchestration métier de l'assistant Support Produit.

Ce module combine l'approche LCEL avec les règles de gouvernance humaine (Human-in-the-Loop, escalade Manager) 
et d'observabilité locale (Langfuse + Logger JSONL). 
"""

from functools import lru_cache
from typing import Any
import uuid

from langchain_core.messages import BaseMessage
from langchain_core.output_parsers import StrOutputParser
from langchain_core.runnables import Runnable

from src.backend.core.config import Settings, get_settings
from src.backend.core.constants import CRITICAL_ESCALATION_KEYWORDS
from src.backend.core.llm import get_llm
from src.backend.core.schemas import (
    ChatRequest,
    ChatResponse,
    ClientContext,
    SeverityLevel,
)
from src.backend.memory import session_memory
from src.backend.observability.langfuse_client import (
    create_langfuse_handler,
    flush_langfuse_handler,
)
from src.backend.prompts.support_prompts import (
    build_langchain_messages,
    convert_history_to_messages,
    support_chat_prompt,
)


@lru_cache(maxsize=1)
def get_support_chat_chain() -> Runnable:
    """Retourne la chaîne LCEL principale de conversation support mise en cache.

    Compose `support_chat_prompt | get_llm() | StrOutputParser()` et la nomme
    explicitement `nexus_support_chain` pour l'observabilité Langfuse.

    Args:
        Aucun argument requis.

    Returns:
        Un `Runnable` LangChain prenant les variables du ticket et renvoyant `str`.
    """
    chain = support_chat_prompt | get_llm() | StrOutputParser()
    return chain.with_config(run_name="nexus_support_chain")


def evaluate_escalation_needed(request: ChatRequest) -> bool:
    """Détermine de façon déterministe si le ticket requiert une escalade humaine.

    Une escalade vers le Responsable Support est obligatoire lorsque la sévérité
    du ticket est `CRITICAL` ou lorsque le message mentionne un incident de sécurité
    ou une demande d'engagement financier/contractuel.

    Args:
        request: Objet `ChatRequest` soumis par l'opérateur.

    Returns:
        True si une escalade vers un profil `MANAGER` est requise, False sinon.
    """
    # Règle 1 : Tout ticket de sévérité CRITICAL impose une escalade (ex: GD-03, GD-05)
    if request.severity == SeverityLevel.CRITICAL:
        return True

    # Règle 2 : Détection lexicale de sujets sensibles (sécurité, promesse financière)
    lowered_message = request.message.lower()
    return any(keyword in lowered_message for keyword in CRITICAL_ESCALATION_KEYWORDS)


async def invoke_litellm_chat(
    messages: list[BaseMessage],
    callbacks: list[Any],
    settings: Settings,
) -> str:
    """Exécute l'appel asynchrone au modèle via le conteneur LiteLLM Proxy.

    Cette fonction utilise l'instance mise en cache `get_llm()` et isole
    l'interaction réseau, ce qui facilite à la fois le découplage architectural
    et le mocking lors des tests unitaires `pytest`.

    Args:
        messages: Liste des messages LangChain (`SystemMessage`, `HumanMessage`, etc.).
        callbacks: Liste des callbacks d'observabilité (ex: `CallbackHandler` Langfuse).
        settings: Instance de configuration `Settings`.

    Returns:
        Le texte brut de la réponse générée par le LLM via LiteLLM Proxy.

    Raises:
        Exception: Si l'appel réseau vers LiteLLM Proxy ou Groq échoue.
    """
    _ = settings
    chat_model = get_llm()
    run_config: dict[str, Any] = {"callbacks": callbacks} if callbacks else {}
    ai_message = await chat_model.ainvoke(messages, config=run_config)

    if isinstance(ai_message.content, str):
        return ai_message.content
    return str(ai_message.content)


async def generate_chat_response(request: ChatRequest) -> ChatResponse:
    """Orchestre le traitement complet d'une requête support.

    Récupére l'historique depuis `session_memory` si non fourni, assemble les
    messages via `support_chat_prompt`, initialise la trace Langfuse,
    interroge LiteLLM Proxy, enregistre l'échange en mémoire thread-safe et
    construit l'objet `ChatResponse` validé par Pydantic.

    Args:
        request: Objet `ChatRequest` validé contenant la demande de l'agent support.

    Returns:
        Un objet `ChatResponse` conforme.

    Raises:
        Exception: Propulse toute erreur d'inférence pour traitement HTTP par l'API.
    """
    settings = get_settings()
    # Génération d'un identifiant de trace unique partagé entre Logger JSON et Langfuse
    trace_id = f"trace-{uuid.uuid4().hex[:12]}"

    # Si l'appelant n'a pas transmis d'historique explicite, on récupère celui de la session
    effective_history = (
        request.history
        if request.history
        else session_memory.get_chat_messages_for_session(request.session_id)
    )
    enriched_request = request.model_copy(update={"history": effective_history})

    # Assemblage des messages via le ChatPromptTemplate et création du handler Langfuse
    messages = build_langchain_messages(enriched_request)
    langfuse_handler = create_langfuse_handler(enriched_request, trace_id, settings)
    callbacks = [langfuse_handler] if langfuse_handler is not None else []

    # Appel asynchrone au LLM via la passerelle LiteLLM Proxy
    answer_text = await invoke_litellm_chat(
        messages=messages,
        callbacks=callbacks,
        settings=settings,
    )

    # Flush non bloquant du handler Langfuse
    flush_langfuse_handler(langfuse_handler, enriched_request, trace_id)

    # Enregistrement thread-safe de l'échange dans la mémoire de session backend
    session_memory.add_exchange(
        session_id=request.session_id,
        user_message=request.message,
        assistant_answer=answer_text,
        client_id=request.client_id,
        severity=request.severity.value,
        operator_id=request.operator_id,
        trace_id=trace_id,
    )

    # Détermination des indicateurs de gouvernance humaine
    escalation_needed = evaluate_escalation_needed(request)

    return ChatResponse(
        answer=answer_text,
        client_context=ClientContext(
            client_id=request.client_id,
            severity=request.severity,
        ),
        sources=[],
        requires_human_validation=True,
        escalation_required=escalation_needed,
        trace_id=trace_id,
    )


__all__ = [
    "convert_history_to_messages",
    "evaluate_escalation_needed",
    "generate_chat_response",
    "get_support_chat_chain",
    "invoke_litellm_chat",
]
