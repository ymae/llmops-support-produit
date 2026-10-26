"""Mémoire conversationnelle en mémoire vive, isolée par session et protégée par verrou.

Ce module gère la mémoire conversationnelle du backend de manière thread-safe:
- Isolation stricte des échanges par `session_id` (et `thread_id`).
- Protection par un `threading.Lock` afin que les requêtes parallèles traitées
  par FastAPI n'altèrent jamais la cohérence des paires question/réponse.
- Possibilité de consulter (`get_history`) ou de réinitialiser (`clear_history`)
  les sessions lors des audits ou des tests automatisés.
"""

from threading import Lock
from typing import Optional

from src.backend.core.schemas import ChatMessage, HistoryEntry


# Dictionnaire interne en mémoire : session_id -> liste d'entrées HistoryEntry
_session_history: dict[str, list[HistoryEntry]] = {}

# Verrou garantissant la thread-safety lors des écritures/lectures concurrentes
_memory_lock = Lock()


def get_thread_id(session_id: str, operator_id: Optional[str] = None) -> str:
    """Construit l'identifiant unique de fil de conversation (`thread_id`).

    Args:
        session_id: Identifiant de la session conversationnelle Chainlit.
        operator_id: Identifiant optionnel de l'opérateur support.

    Returns:
        Une chaîne stable identifiant de manière unique le thread de conversation.
    """
    if operator_id:
        return f"thread-{operator_id}-{session_id}"
    return f"thread-{session_id}"


def add_exchange(
    session_id: str,
    user_message: str,
    assistant_answer: str,
    client_id: str,
    severity: str,
    operator_id: str,
    trace_id: str,
) -> None:
    """Enregistre atomiquement une paire question/réponse dans l'historique de la session.

    Les deux entrées (`user` puis `assistant`) sont ajoutées ensemble sous verrou
    afin que l'historique conserve toujours une séquence cohérente.

    Args:
        session_id: Identifiant de la session support.
        user_message: Question soumise par l'opérateur support.
        assistant_answer: Réponse générée par le copilote LLM.
        client_id: Identifiant du client concerné (`CLI-001` à `CLI-015`).
        severity: Niveau de sévérité du ticket (`LOW` à `CRITICAL`).
        operator_id: Identifiant de l'opérateur connecté.
        trace_id: Identifiant de trace associé à l'échange.

    Returns:
        None.
    """
    with _memory_lock:
        entries = _session_history.setdefault(session_id, [])
        entries.append(
            HistoryEntry(
                role="user",
                content=user_message,
                client_id=client_id,
                severity=severity,
                operator_id=operator_id,
                trace_id=trace_id,
            )
        )
        entries.append(
            HistoryEntry(
                role="assistant",
                content=assistant_answer,
                client_id=client_id,
                severity=severity,
                operator_id=operator_id,
                trace_id=trace_id,
            )
        )


def get_history(session_id: str) -> list[HistoryEntry]:
    """Retourne la copie des échanges enregistrés pour une session donnée.

    Args:
        session_id: Identifiant de la session support à consulter.

    Returns:
        Une liste ordonnée d'objets `HistoryEntry` (vide si la session est inconnue).
    """
    with _memory_lock:
        return [entry.model_copy() for entry in _session_history.get(session_id, [])]


def get_chat_messages_for_session(session_id: str) -> list[ChatMessage]:
    """Convertit l'historique stocké en mémoire en liste de `ChatMessage` pour LangChain.

    Permet au backend de reconstruire automatiquement l'historique conversationnel
    si le client HTTP omet de renvoyer le tableau `history` complet.

    Args:
        session_id: Identifiant de la session support.

    Returns:
        Une liste ordonnée d'instances `ChatMessage`.
    """
    with _memory_lock:
        entries = _session_history.get(session_id, [])
        return [
            ChatMessage(role=entry.role, content=entry.content)
            for entry in entries
        ]


def clear_history(session_id: Optional[str] = None) -> None:
    """Efface l'historique conversationnel d'une session ou de toutes les sessions.

    Args:
        session_id: Identifiant de la session à purger. Si `None`, réinitialise
            l'intégralité de la mémoire (utilisé notamment entre les tests `pytest`).

    Returns:
        None.
    """
    with _memory_lock:
        if session_id is None:
            _session_history.clear()
        else:
            _session_history.pop(session_id, None)
