"""Module de journalisation JSON structurée (Observabilité Niveau 1).

Ce module assure la traçabilité technique et l'auditabilité locale du microservice
FastAPI en enregistrant chaque événement (requêtes entrantes, succès d'inférence,
rejets d'authentification HTTP 401/403 et rejets de validation Pydantic comme
le cas CLI-099) au format JSON Lines (`logs/app.jsonl`).
"""

from datetime import datetime, timezone
import json
from pathlib import Path
import sys
from typing import Any, Optional

from loguru import logger

from src.backend.core.config import get_settings


def configure_logger() -> None:
    """Configure le gestionnaire global Loguru pour la sortie console standard.

    Supprime le handler par défaut de Loguru et attache un formateur lisible
    sur `sys.stderr` filtré selon le niveau `LOG_LEVEL` défini dans `.env`.

    Args:
        Aucun argument requis.

    Returns:
        None.
    """
    settings = get_settings()
    # Nettoyage des handlers préexistants pour éviter les doublons de logs
    logger.remove()
    # Ajout d'une sortie console structurée pour l'inspection via `make logs`
    logger.add(
        sys.stderr,
        level=settings.log_level.upper(),
        format=(
            "<green>{time:YYYY-MM-DD HH:mm:ss.SSS}</green> | "
            "<level>{level: <8}</level> | "
            "<cyan>{extra[event]}</cyan> - <level>{message}</level>"
        ),
    )


def log_structured_event(
    event: str,
    message: str,
    level: str = "INFO",
    session_id: Optional[str] = None,
    operator_id: Optional[str] = None,
    operator_role: Optional[str] = None,
    client_id: Optional[str] = None,
    severity: Optional[str] = None,
    trace_id: Optional[str] = None,
    status_code: Optional[int] = None,
    extra_data: Optional[dict[str, Any]] = None,
    log_file_override: Optional[Path] = None,
) -> dict[str, Any]:
    """Enregistre un événement technique ou métier sous forme d'entrée JSONL locale.

    Construit un dictionnaire normalisé conforme aux exigences d'auditabilité, 
    l'écrit de façon atomique dans le fichier `logs/app.jsonl`
    et le diffuse sur la sortie standard via Loguru.

    Args:
        event: Code court identifiant la nature de l'événement (ex: `auth_failure`).
        message: Description explicite de l'événement en français.
        level: Niveau de sévérité (`INFO`, `WARNING`, `ERROR`). Par défaut `"INFO"`.
        session_id: Identifiant de la session conversationnelle Chainlit.
        operator_id: Identifiant de l'opérateur support connecté.
        operator_role: Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).
        client_id: Identifiant du client concerné par le ticket (ex: `CLI-003`).
        severity: Niveau de criticité du ticket (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
        trace_id: Identifiant unique de corrélation (commun avec Langfuse).
        status_code: Code de statut HTTP associé à la requête ou à l'erreur.
        extra_data: Métadonnées complémentaires éventuelles (ex: erreurs Pydantic).
        log_file_override: Chemin de fichier spécifique (utile pour l'isolation des tests).

    Returns:
        Le dictionnaire `log_entry` tel qu'il a été sérialisé dans le fichier JSONL.

    Raises:
        OSError: Si l'écriture dans le fichier de journalisation local échoue.
    """
    settings = get_settings()
    normalized_level = level.upper()

    # Construction de l'enregistrement JSON normalisé en UTC (ISO 8601)
    log_entry: dict[str, Any] = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "level": normalized_level,
        "event": event,
        "message": message,
        "session_id": session_id,
        "operator_id": operator_id,
        "operator_role": operator_role,
        "client_id": client_id,
        "severity": severity,
        "trace_id": trace_id,
        "status_code": status_code,
        "extra": extra_data or {},
    }

    # Détermination du chemin cible (priorité à l'override de test, sinon configuration)
    target_path = (
        log_file_override
        if log_file_override is not None
        else settings.get_resolved_log_path()
    )
    target_path.parent.mkdir(parents=True, exist_ok=True)

    # Écriture synchrone d'une ligne JSON (format JSON Lines / .jsonl)
    with target_path.open("a", encoding="utf-8") as log_file:
        log_file.write(json.dumps(log_entry, ensure_ascii=False) + "\n")

    # Journalisation simultanée sur la console via Loguru avec liaison du champ `event`
    bound_logger = logger.bind(event=event)
    if normalized_level == "ERROR":
        bound_logger.error(message)
    elif normalized_level == "WARNING":
        bound_logger.warning(message)
    else:
        bound_logger.info(message)

    return log_entry


# Initialisation de la configuration console au chargement du module
configure_logger()
