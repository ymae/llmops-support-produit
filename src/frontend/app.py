"""Interface conversationnelle Streamlit de l'Assistant Support Produit Nexus.

Ce module implémente l'interface utilisateur destinée aux agents du support technique
(`AGENT`) et aux responsables support (`MANAGER`) :
- Page de connexion obligatoire générant un jeton JWT signé en HS256
  (`create_access_token`) pour l'opérateur connecté.
- Sélecteurs de contexte ticket (`CLI-001`..`CLI-015` et `severity`) dans la barre latérale.
- Communication HTTP sécurisée par jeton JWT Bearer avec le microservice `backend-api`.
- Panneau latéral de restitution et boutons d'action pour la validation humaine
  obligatoire (Human-in-the-Loop) et l'escalade.

Lancement : `uv run streamlit run src/frontend/app.py`
"""

from dataclasses import dataclass
from pathlib import Path
import sys
import os
from typing import Any, Optional
import uuid

import httpx
import streamlit as st

# `streamlit run` n'ajoute que le dossier du script à sys.path : on ajoute la
# racine du projet pour que les imports `src.*` fonctionnent aussi hors Docker.
# sinon, ça plante avec le message : ModuleNotFoundError: No module named 'src'
PROJECT_ROOT = str(Path(__file__).resolve().parents[2])
if PROJECT_ROOT not in sys.path:
    sys.path.insert(0, PROJECT_ROOT)

from src.backend.core.config import get_settings
from src.backend.core.constants import CLIENT_ID_OPTIONS, SEVERITY_OPTIONS
from src.backend.core.schemas import OperatorRole
from src.backend.core.security import (
    authenticate_operator_credentials,
    create_access_token,
    verify_credentials_constant_time,
)

DEFAULT_CLIENT_ID = "CLI-003"
DEFAULT_SEVERITY = "MEDIUM"


@dataclass(frozen=True)
class OperatorSession: # pour remplacer cl.User de Chainlit
    """Opérateur authentifié avec son rôle et son jeton JWT"""
    identifier: str
    role: str
    display_name: str
    access_token: str


@dataclass(frozen=True)
class HumanAction:  # pour remplacer cl.Action
    """Action de validation humaine (valider, escalader ou rejeter)"""
    name: str
    label: str
    payload: dict[str, Any]


def authenticate_operator(username: str, password: str) -> Optional[OperatorSession]:
    """Authentifie l'opérateur support, lui attribue son rôle et génère un jeton JWT (HS256).

    Args:
        username: Nom d'utilisateur saisi dans le formulaire de connexion.
        password: Mot de passe saisi dans le formulaire de connexion.

    Returns:
        Une `OperatorSession` enrichie du rôle métier (`AGENT` ou `MANAGER`) et
        d'un jeton `access_token` JWT signé en HS256, ou `None` si invalide.
    """
    operator_user = authenticate_operator_credentials(username, password)
    if operator_user is None:
        return None

    # Émission d'un jeton JWT signé (HS256) propre à la session de l'opérateur
    jwt_token = create_access_token(
        operator_id=operator_user.username,
        operator_role=operator_user.role,
    )
    display_name = (
        "Agent Support Technique"
        if operator_user.role == OperatorRole.AGENT
        else "Responsable Support (Manager)"
    )

    return OperatorSession(
        identifier=operator_user.username,
        role=operator_user.role.value,
        display_name=display_name,
        access_token=jwt_token,
    )


def build_sidebar_markdown(
    operator_id: str,
    operator_role: str,
    client_id: str,
    severity: str,
    response_data: Optional[dict[str, Any]] = None,
) -> str:
    """Génère le contenu Markdown affiché dans le panneau latéral.

    Restitue l'état courant du ticket, le profil de l'opérateur connecté et,
    lorsqu'une réponse LLM a été reçue, les indicateurs de gouvernance humaine
    et l'identifiant de trace `trace_id`.

    Args:
        operator_id: Identifiant de l'opérateur authentifié.
        operator_role: Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).
        client_id: Identifiant du client sélectionné (`CLI-001` à `CLI-015`).
        severity: Sévérité sélectionnée (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
        response_data: Dictionnaire optionnel issu de `ChatResponse`.

    Returns:
        Une chaîne Markdown formatée pour le panneau latéral.
    """
    lines = [
        "### Opérateur Connecté",
        f"- **Identifiant :** `{operator_id}`",
        f"- **Rôle Métier :** `{operator_role}`",
        "",
        "### Contexte du Ticket Actif",
        f"- **Client ID :** `{client_id}`",
        f"- **Sévérité :** `{severity}`",
    ]

    if response_data is None:
        lines.extend(
            [
                "- **Version Produit :** *En attente de requête (Mode V1 Baseline)*",
                "- **Contrat SLA :** *En attente de requête (Mode V1 Baseline)*",
                "",
                "---",
                "### Gouvernance",
                "- **Validation humaine requise :** `OUI (Systématique)`",
                "- **Statut :** En attente d'une question support.",
            ]
        )
    else:
        client_ctx = response_data.get("client_context", {})
        product_version = client_ctx.get("product_version", "Non résolue (V1)")
        sla_level = client_ctx.get("sla_level", "Non résolu (V1)")
        requires_validation = response_data.get("requires_human_validation", True)
        escalation_required = response_data.get("escalation_required", False)
        trace_id = response_data.get("trace_id", "N/A")
        sources = response_data.get("sources", [])

        lines.extend(
            [
                f"- **Version Produit :** `{product_version}`",
                f"- **Contrat SLA :** `{sla_level}`",
                "",
                "---",
                "### Gouvernance & Traçabilité",
                f"- **Validation humaine requise :** `{'OUI' if requires_validation else 'NON'}`",
                (
                    f"- **Escalade Manager requise :** "
                    f"`{'OUI (CRITIQUE / SENSIBLE)' if escalation_required else 'NON'}`"
                ),
                f"- **Trace ID :** `{trace_id}`",
                (
                    f"- **Sources mobilisées :** "
                    f"{', '.join(sources) if sources else '*Aucune (Mode Baseline V1 sans RAG)*'}"
                ),
            ]
        )

    return "\n".join(lines)


def call_backend_chat_api(
    payload: dict[str, Any],
    access_token: Optional[str] = None,
) -> dict[str, Any]:
    """Envoie la requête conversationnelle signée par JWT au microservice `backend-api`.

    Transmet l'en-tête `Authorization: Bearer <JWT_TOKEN>` (ou à défaut un jeton
    JWT généré à la volée pour l'opérateur du payload) et retourne le dictionnaire
    JSON validé par le contrat `ChatResponse`.

    Args:
        payload: Dictionnaire conforme au schéma d'entrée `ChatRequest`.
        access_token: Jeton JWT HS256 de la session opérateur (optionnel).

    Returns:
        Le dictionnaire JSON retourné par `POST /api/v1/chat`.

    Raises:
        httpx.HTTPStatusError: Si le backend retourne un code d'erreur HTTP (401, 403, 422, 429, 502).
        httpx.RequestError: Si le microservice backend est injoignable.
    """
    settings = get_settings()
    endpoint_url = f"{settings.backend_api_url.rstrip('/')}/api/v1/chat"

    # Utilisation prioritaire du jeton JWT HS256 de la session opérateur
    token_to_send = access_token or create_access_token(
        operator_id=str(payload.get("operator_id", settings.agent_username)),
        operator_role=OperatorRole(str(payload.get("operator_role", "AGENT"))),
    )
    headers = {
        "Authorization": f"Bearer {token_to_send}",
        "Content-Type": "application/json",
    }

    with httpx.Client(timeout=settings.llm_request_timeout + 5.0) as client:
        response = client.post(endpoint_url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def build_human_validation_actions(
    trace_id: str,
    client_id: str,
    severity: str,
    escalation_required: bool,
) -> list[HumanAction]:
    """Construit les actions permettant la validation humaine ou l'escalade.

    Args:
        trace_id: Identifiant unique de la trace d'inférence.
        client_id: Identifiant du client concerné.
        severity: Niveau de sévérité du ticket.
        escalation_required: Booléen indiquant si l'escalade Manager est requise.

    Returns:
        Une liste de `HumanAction` affichées sous le message de réponse.
    """
    action_payload = {
        "trace_id": trace_id,
        "client_id": client_id,
        "severity": severity,
        "escalation_required": escalation_required,
    }

    return [
        HumanAction(
            name="validate_response",
            label="✅ Valider la réponse (Prêt pour envoi client)",
            payload=action_payload,
        ),
        HumanAction(
            name="escalate_response",
            label="🚨 Escalader au Responsable Support (MANAGER)",
            payload=action_payload,
        ),
        HumanAction(
            name="reject_response",
            label="❌ Rejeter / Reformuler le brouillon",
            payload=action_payload,
        ),
    ]


def build_action_feedback(
    action: HumanAction,
    operator_id: str,
    operator_role: str,
) -> str:
    """Construit le message de confirmation d'une action de validation humaine.

    Args:
        action: Action déclenchée par l'opérateur.
        operator_id: Identifiant de l'opérateur connecté.
        operator_role: Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).

    Returns:
        Le message Markdown à ajouter à la conversation.
    """
    payload = action.payload
    trace_id = payload.get("trace_id", "N/A")
    client_id = payload.get("client_id", "N/A")

    if action.name == "validate_response":
        # Si une escalade est requise et que l'opérateur est simple AGENT, bloquer
        if payload.get("escalation_required") and operator_role == "AGENT":
            return (
                f"⚠️ **Validation bloquée pour le profil `AGENT` :** Le ticket `{client_id}` "
                f"(Trace `{trace_id}`) requiert une escalade vers un profil **`MANAGER`** "
                "avant toute communication externe."
            )
        return (
            f"✅ **Réponse validée** par `{operator_id}` (`{operator_role}`) "
            f"pour envoi au client **`{client_id}`** *(Trace : `{trace_id}`)*."
        )

    if action.name == "escalate_response":
        return (
            f"🚨 **Escalade enregistrée vers le Responsable Support (`MANAGER`)** "
            f"par `{operator_id}` (`{operator_role}`) — Client : **`{client_id}`**, "
            f"Sévérité : **`{payload.get('severity', 'N/A')}`**, Trace : `{trace_id}`."
        )

    return (
        f"❌ **Brouillon rejeté** par `{operator_id}` *(Trace : `{trace_id}`)*. "
        "Vous pouvez préciser votre question ou ajuster le contexte dans la barre latérale."
    )


def build_governance_banner(
    escalation_required: bool,
    client_id: str,
    trace_id: str,
) -> str:
    """Construit le bandeau de gouvernance ajouté à chaque réponse de l'assistant.

    Args:
        escalation_required: Indique si une escalade Manager est requise.
        client_id: Identifiant du client concerné.
        trace_id: Identifiant de la trace d'inférence.

    Returns:
        Le bandeau Markdown (alerte d'escalade ou rappel de validation humaine).
    """
    if escalation_required:
        return (
            "\n\n---\n🚨 **ALERTE GOUVERNANCE :** Ce ticket présente un caractère critique "
            "ou sensible (`escalation_required = True`). **L'envoi direct est déconseillé : "
            "veuillez escalader au Responsable Support (`MANAGER`).**"
        )
    return (
        "\n\n---\n🛡️ *Validation humaine requise avant toute communication "
        f"externe au client `{client_id}` (Trace : `{trace_id}`).* "
    )


# ==============================================================================
# Interface Streamlit
# ==============================================================================


def init_session_state() -> None:
    """Initialise les clés de `st.session_state` absentes (opérateur, contexte, historique)."""
    defaults: dict[str, Any] = {
        "operator": None,
        "session_id": f"sess-{uuid.uuid4().hex[:10]}",
        "client_id": DEFAULT_CLIENT_ID,
        "severity": DEFAULT_SEVERITY,
        "messages": [],
        "last_response": None,
    }
    for key, value in defaults.items():
        st.session_state.setdefault(key, value)


def render_login() -> None:
    """Affiche le formulaire de connexion et enregistre l'opérateur en session."""
    st.title("Support Produit - Nexus Platform")
    st.caption("Connexion opérateur requise.")
    with st.form("login"):
        username = st.text_input("Identifiant")
        password = st.text_input("Mot de passe", type="password")
        submitted = st.form_submit_button("Se connecter")

    if submitted:
        operator = authenticate_operator(username, password)
        if operator is None:
            st.error("Identifiant ou mot de passe invalide.")
            return
        st.session_state.operator = operator
        st.session_state.messages = [
            {
                "role": "assistant",
                "content": (
                    f"Bonjour **{operator.identifier}** (Profil : `{operator.role}`).\n\n"
                    f"Le contexte actif est initialisé sur le client **`{DEFAULT_CLIENT_ID}`** "
                    f"avec une sévérité **`{DEFAULT_SEVERITY}`** (modifiable dans la barre "
                    "latérale).\n\n"
                    "> **Rappel de gouvernance :** Toute réponse proposée par cet assistant "
                    "doit faire l'objet d'une validation humaine explicite avant envoi au client."
                ),
            }
        ]
        st.rerun()


def on_context_change() -> None:
    """Ajoute une notification à la conversation quand le client ou la sévérité change."""
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": (
                f"⚙️ **Contexte ticket mis à jour :** Client = `{st.session_state.client_id}` | "
                f"Sévérité = `{st.session_state.severity}`."
            ),
        }
    )


def render_action_buttons(message_index: int, operator: OperatorSession) -> None:
    """Affiche les boutons de validation humaine sous la dernière réponse de l'assistant.

    Args:
        message_index: Position du message dans `st.session_state.messages`.
        operator: Opérateur connecté.
    """
    message = st.session_state.messages[message_index]
    actions: list[HumanAction] = message["actions"]
    for action in actions:
        if st.button(action.label, key=f"{action.name}-{message_index}"):
            message["actions"] = []
            st.session_state.messages.append(
                {
                    "role": "assistant",
                    "content": build_action_feedback(
                        action, operator.identifier, operator.role
                    ),
                }
            )
            st.rerun()


def handle_user_message(prompt: str, operator: OperatorSession) -> None:
    """Interroge le backend, puis ajoute la question et la réponse à la conversation.

    Args:
        prompt: Question saisie par l'opérateur.
        operator: Opérateur connecté.
    """
    client_id = st.session_state.client_id
    severity = st.session_state.severity
    history = [
        {"role": m["role"], "content": m.get("history_content", m["content"])}
        for m in st.session_state.messages
        if m.get("in_history")
    ]
    request_payload: dict[str, Any] = {
        "session_id": st.session_state.session_id,
        "operator_id": operator.identifier,
        "operator_role": operator.role,
        "client_id": client_id,
        "severity": severity,
        "message": prompt,
        "history": history,
    }

    st.session_state.messages.append(
        {"role": "user", "content": prompt, "in_history": True}
    )

    try:
        with st.spinner("Interrogation de l'assistant..."):
            response_data = call_backend_chat_api(
                payload=request_payload,
                access_token=operator.access_token,
            )
    except httpx.HTTPStatusError as http_err:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    f"⚠️ **Erreur API Backend (`HTTP {http_err.response.status_code}`) :**\n"
                    f"```json\n{http_err.response.text}\n```"
                ),
            }
        )
        return
    except Exception as exc:
        st.session_state.messages.append(
            {
                "role": "assistant",
                "content": (
                    f"❌ **Impossible de joindre le microservice `backend-api` :** `{exc}`"
                ),
            }
        )
        return

    answer_text = str(response_data.get("answer", ""))
    trace_id = str(response_data.get("trace_id", "N/A"))
    escalation_required = bool(response_data.get("escalation_required", False))

    st.session_state.last_response = response_data
    # La réponse brute est conservée dans l'historique envoyé au backend ;
    # le bandeau de gouvernance n'est ajouté qu'à l'affichage.
    st.session_state.messages.append(
        {
            "role": "assistant",
            "content": answer_text
            + build_governance_banner(escalation_required, client_id, trace_id),
            "history_content": answer_text,
            "in_history": True,
            "actions": build_human_validation_actions(
                trace_id=trace_id,
                client_id=client_id,
                severity=severity,
                escalation_required=escalation_required,
            ),
        }
    )


def main() -> None:
    """Point d'entrée Streamlit : connexion, barre latérale de contexte et conversation."""
    st.set_page_config(
        page_title="Support Produit - Nexus Platform",
        layout="wide",
    )
    init_session_state()

    operator: Optional[OperatorSession] = st.session_state.operator
    if operator is None:
        render_login()
        return

    with st.sidebar:
        st.header("Contexte Support Nexus")
        st.selectbox(
            "Client concerné par le ticket (CLI-001 à CLI-015)",
            CLIENT_ID_OPTIONS,
            key="client_id",
            on_change=on_context_change,
        )
        st.selectbox(
            "Niveau de sévérité du ticket (SLA)",
            SEVERITY_OPTIONS,
            key="severity",
            on_change=on_context_change,
        )
        context_placeholder = st.empty()
        if st.button("Se déconnecter"):
            for key in ("operator", "messages", "last_response", "session_id"):
                del st.session_state[key]
            st.rerun()

    st.title("Support Produit - Nexus Platform")

    last_message_index = len(st.session_state.messages) - 1
    for index, message in enumerate(st.session_state.messages):
        with st.chat_message(message["role"]):
            st.markdown(message["content"])
            if message.get("actions") and index == last_message_index:
                render_action_buttons(index, operator)

    if prompt := st.chat_input("Posez votre question support..."):
        handle_user_message(prompt, operator)
        st.rerun()

    # Rendu en dernier pour refléter la réponse la plus récente
    context_placeholder.markdown(
        build_sidebar_markdown(
            operator_id=operator.identifier,
            operator_role=operator.role,
            client_id=st.session_state.client_id,
            severity=st.session_state.severity,
            response_data=st.session_state.last_response,
        )
    )


if __name__ == "__main__":
    main()


__all__ = [
    "CLIENT_ID_OPTIONS",
    "SEVERITY_OPTIONS",
    "authenticate_operator",
    "build_human_validation_actions",
    "build_sidebar_markdown",
    "call_backend_chat_api",
    "verify_credentials_constant_time",
]
