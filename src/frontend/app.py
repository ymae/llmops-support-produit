"""Interface conversationnelle Chainlit de l'Assistant Support Produit Nexus.

Ce module implémente l'interface utilisateur destiné aux agents du support technique
(`AGENT`) et aux responsables support (`MANAGER`) :
- Page de connexion obligatoire (`@cl.password_auth_callback`) générant un jeton
  JWT signé en HS256 (`create_access_token`) pour l'opérateur connecté.
- Sélecteurs de contexte ticket (`ChatSettings` : `CLI-001`..`CLI-015` et `severity`).
- Communication HTTP sécurisée par jeton JWT Bearer avec le microservice `backend-api`.
- Panneau latéral de restitution (`ElementSidebar`) et boutons d'action pour la
  validation humaine obligatoire (Human-in-the-Loop) et l'escalade.
"""

import os
from typing import Any, Optional
import uuid

# Suppression préventive de DATABASE_URL pour éviter l'activation implicite
# de ChainlitDataLayer (asyncpg) lors de l'authentification opérateur.
os.environ.pop("DATABASE_URL", None)

import chainlit as cl
from chainlit.input_widget import Select
import httpx

from src.backend.core.config import get_settings
from src.backend.core.constants import CLIENT_ID_OPTIONS, SEVERITY_OPTIONS
from src.backend.core.schemas import OperatorRole
from src.backend.core.security import (
    authenticate_operator_credentials,
    create_access_token,
    verify_credentials_constant_time,
)


@cl.password_auth_callback
def authenticate_operator(username: str, password: str) -> Optional[cl.User]:
    """Authentifie l'opérateur support, lui attribue son rôle et génère un jeton JWT (HS256).

    Cette fonction est appelée automatiquement par Chainlit lors de la soumission
    du formulaire de connexion protégé par `CHAINLIT_AUTH_SECRET`.

    Args:
        username: Nom d'utilisateur saisi dans l'interface Chainlit.
        password: Mot de passe saisi dans l'interface Chainlit.

    Returns:
        Une instance `cl.User` enrichie du rôle métier (`AGENT` ou `MANAGER`) et
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

    return cl.User(
        identifier=operator_user.username,
        metadata={
            "role": operator_user.role.value,
            "display_name": display_name,
            "access_token": jwt_token,
        },
    )


def build_sidebar_markdown(
    operator_id: str,
    operator_role: str,
    client_id: str,
    severity: str,
    response_data: Optional[dict[str, Any]] = None,
) -> str:
    """Génère le contenu Markdown affiché dans le panneau latéral `ElementSidebar`.

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
        Une chaîne Markdown formatée pour le composant `cl.Text` du panneau latéral.
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


async def update_context_sidebar(
    operator_id: str,
    operator_role: str,
    client_id: str,
    severity: str,
    response_data: Optional[dict[str, Any]] = None,
) -> None:
    """Met à jour le panneau latéral `ElementSidebar` de Chainlit.

    Args:
        operator_id: Identifiant de l'opérateur authentifié.
        operator_role: Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).
        client_id: Identifiant du client actif.
        severity: Niveau de sévérité actif.
        response_data: Dictionnaire optionnel issu de la réponse `ChatResponse`.

    Returns:
        None.
    """
    markdown_content = build_sidebar_markdown(
        operator_id=operator_id,
        operator_role=operator_role,
        client_id=client_id,
        severity=severity,
        response_data=response_data,
    )
    sidebar_element = cl.Text(
        name="Contexte Ticket & Gouvernance",
        content=markdown_content,
        display="inline",
    )
    await cl.ElementSidebar.set_title("Contexte Support Nexus")
    await cl.ElementSidebar.set_elements([sidebar_element])


async def call_backend_chat_api(
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

    async with httpx.AsyncClient(timeout=settings.llm_request_timeout + 5.0) as client:
        response = await client.post(endpoint_url, headers=headers, json=payload)
        response.raise_for_status()
        return response.json()


def build_human_validation_actions(
    trace_id: str,
    client_id: str,
    severity: str,
    escalation_required: bool,
) -> list[cl.Action]:
    """Construit les boutons d'action permettant la validation humaine ou l'escalade.

    Args:
        trace_id: Identifiant unique de la trace d'inférence.
        client_id: Identifiant du client concerné.
        severity: Niveau de sévérité du ticket.
        escalation_required: Booléen indiquant si l'escalade Manager est requise.

    Returns:
        Une liste d'objets `cl.Action` attachés au message de réponse Chainlit.
    """
    action_payload = {
        "trace_id": trace_id,
        "client_id": client_id,
        "severity": severity,
        "escalation_required": escalation_required,
    }

    return [
        cl.Action(
            name="validate_response",
            payload=action_payload,
            label="✅ Valider la réponse (Prêt pour envoi client)",
        ),
        cl.Action(
            name="escalate_response",
            payload=action_payload,
            label="🚨 Escalader au Responsable Support (MANAGER)",
        ),
        cl.Action(
            name="reject_response",
            payload=action_payload,
            label="❌ Rejeter / Reformuler le brouillon",
        ),
    ]


@cl.on_chat_start
async def on_chat_start() -> None:
    """Initialise la session opérateur, le jeton JWT, les `ChatSettings` et l'`ElementSidebar`.

    Récupère l'utilisateur authentifié dans la session Chainlit, configure les
    valeurs par défaut (`CLI-003`, `MEDIUM`) et affiche les sélecteurs de contexte.

    Args:
        Aucun argument requis.

    Returns:
        None.
    """
    user: Optional[cl.User] = cl.user_session.get("user")
    operator_id = user.identifier if user else "agent"
    operator_role = (
        str(user.metadata.get("role", "AGENT"))
        if user and user.metadata
        else "AGENT"
    )
    access_token = (
        str(user.metadata.get("access_token"))
        if user and user.metadata and user.metadata.get("access_token")
        else create_access_token(
            operator_id=operator_id,
            operator_role=OperatorRole(operator_role),
        )
    )
    session_id = f"sess-{uuid.uuid4().hex[:10]}"

    # Valeurs initiales par défaut du contexte ticket (alignées sur le cas GD-01)
    default_client_id = "CLI-003"
    default_severity = "MEDIUM"

    # Enregistrement de l'état initial et du JWT dans la session utilisateur Chainlit
    cl.user_session.set("session_id", session_id)
    cl.user_session.set("operator_id", operator_id)
    cl.user_session.set("operator_role", operator_role)
    cl.user_session.set("access_token", access_token)
    cl.user_session.set("client_id", default_client_id)
    cl.user_session.set("severity", default_severity)
    cl.user_session.set("history", [])

    # Déclaration des sélecteurs ChatSettings pour le choix du client et de la sévérité
    await cl.ChatSettings(
        [
            Select(
                id="client_id",
                label="Client concerné par le ticket (CLI-001 à CLI-015)",
                values=CLIENT_ID_OPTIONS,
                initial_value=default_client_id,
            ),
            Select(
                id="severity",
                label="Niveau de sévérité du ticket (SLA)",
                values=SEVERITY_OPTIONS,
                initial_value=default_severity,
            ),
        ]
    ).send()

    # Ouverture et initialisation du panneau latéral de contexte
    await update_context_sidebar(
        operator_id=operator_id,
        operator_role=operator_role,
        client_id=default_client_id,
        severity=default_severity,
    )

    # Message d'accueil rappelant le contexte et la règle de validation humaine
    await cl.Message(
        content=(
            f"Bonjour **{operator_id}** (Profil : `{operator_role}`).\n\n"
            f"Le contexte actif est initialisé sur le client **`{default_client_id}`** "
            f"avec une sévérité **`{default_severity}`** (modifiable via l'icône ⚙️ "
            "des paramètres de chat).\n\n"
            "> **Rappel de gouvernance :** Toute réponse proposée par cet assistant "
            "doit faire l'objet d'une validation humaine explicite avant envoi au client."
        )
    ).send()


@cl.on_settings_update
async def on_settings_update(updated_settings: dict[str, Any]) -> None:
    """Met à jour la session et le panneau latéral lorsque l'opérateur modifie `ChatSettings`.

    Args:
        updated_settings: Dictionnaire contenant les nouvelles valeurs `client_id` et `severity`.

    Returns:
        None.
    """
    client_id = str(updated_settings.get("client_id", "CLI-003"))
    severity = str(updated_settings.get("severity", "MEDIUM"))
    operator_id = str(cl.user_session.get("operator_id", "agent"))
    operator_role = str(cl.user_session.get("operator_role", "AGENT"))

    # Persistance des nouveaux paramètres dans la session courante
    cl.user_session.set("client_id", client_id)
    cl.user_session.set("severity", severity)

    # Rafraîchissement immédiat du panneau latéral de contexte
    await update_context_sidebar(
        operator_id=operator_id,
        operator_role=operator_role,
        client_id=client_id,
        severity=severity,
    )

    await cl.Message(
        content=(
            f"⚙️ **Contexte ticket mis à jour :** Client = `{client_id}` | "
            f"Sévérité = `{severity}`."
        )
    ).send()


@cl.on_message
async def on_message(message: cl.Message) -> None:
    """Traite chaque message saisi par l'opérateur support et affiche la restitution.

    Assemble le payload `ChatRequest`, interroge le microservice FastAPI avec le
    jeton JWT Bearer, rafraîchit le panneau latéral `ElementSidebar` et affiche les
    boutons de validation humaine / escalade.

    Args:
        message: Objet `cl.Message` contenant la question de l'opérateur.

    Returns:
        None.
    """
    session_id = str(cl.user_session.get("session_id", f"sess-{uuid.uuid4().hex[:8]}"))
    operator_id = str(cl.user_session.get("operator_id", "agent"))
    operator_role = str(cl.user_session.get("operator_role", "AGENT"))
    access_token: Optional[str] = cl.user_session.get("access_token")
    client_id = str(cl.user_session.get("client_id", "CLI-003"))
    severity = str(cl.user_session.get("severity", "MEDIUM"))
    history: list[dict[str, str]] = list(cl.user_session.get("history", []))

    request_payload: dict[str, Any] = {
        "session_id": session_id,
        "operator_id": operator_id,
        "operator_role": operator_role,
        "client_id": client_id,
        "severity": severity,
        "message": message.content,
        "history": history,
    }

    try:
        response_data = await call_backend_chat_api(
            payload=request_payload,
            access_token=access_token,
        )
    except httpx.HTTPStatusError as http_err:
        status_code = http_err.response.status_code
        detail = http_err.response.text
        await cl.Message(
            content=(
                f"⚠️ **Erreur API Backend (`HTTP {status_code}`) :**\n"
                f"```json\n{detail}\n```"
            )
        ).send()
        return
    except Exception as exc:
        await cl.Message(
            content=(
                f"❌ **Impossible de joindre le microservice `backend-api` :** `{exc}`"
            )
        ).send()
        return

    answer_text = str(response_data.get("answer", ""))
    trace_id = str(response_data.get("trace_id", "N/A"))
    escalation_required = bool(response_data.get("escalation_required", False))

    # Mise à jour de l'historique conversationnel en session
    history.append({"role": "user", "content": message.content})
    history.append({"role": "assistant", "content": answer_text})
    cl.user_session.set("history", history)

    # Mise à jour du panneau latéral avec les métadonnées de la réponse
    await update_context_sidebar(
        operator_id=operator_id,
        operator_role=operator_role,
        client_id=client_id,
        severity=severity,
        response_data=response_data,
    )

    # Ajout d'un bandeau d'alerte explicite si une escalade Manager est requise
    governance_banner = (
        "\n\n---\n🚨 **ALERTE GOUVERNANCE :** Ce ticket présente un caractère critique "
        "ou sensible (`escalation_required = True`). **L'envoi direct est déconseillé : "
        "veuillez escalader au Responsable Support (`MANAGER`).**"
        if escalation_required
        else (
            "\n\n---\n🛡️ *Validation humaine requise avant toute communication "
            f"externe au client `{client_id}` (Trace : `{trace_id}`).* "
        )
    )

    actions = build_human_validation_actions(
        trace_id=trace_id,
        client_id=client_id,
        severity=severity,
        escalation_required=escalation_required,
    )

    await cl.Message(
        content=f"{answer_text}{governance_banner}",
        actions=actions,
    ).send()


@cl.action_callback("validate_response")
async def on_validate_response(action: cl.Action) -> None:
    """Enregistre la validation humaine de la réponse par l'opérateur connecté.

    Args:
        action: Objet `cl.Action` contenant les métadonnées (`trace_id`, `client_id`).

    Returns:
        None.
    """
    operator_id = str(cl.user_session.get("operator_id", "agent"))
    operator_role = str(cl.user_session.get("operator_role", "AGENT"))
    payload = action.payload or {}
    trace_id = payload.get("trace_id", "N/A")
    client_id = payload.get("client_id", "N/A")
    escalation_required = bool(payload.get("escalation_required", False))

    # Si une escalade est requise et que l'opérateur est simple AGENT, avertir
    if escalation_required and operator_role == "AGENT":
        await cl.Message(
            content=(
                f"⚠️ **Validation bloquée pour le profil `AGENT` :** Le ticket `{client_id}` "
                f"(Trace `{trace_id}`) requiert une escalade vers un profil **`MANAGER`** "
                "avant toute communication externe."
            )
        ).send()
        return

    await cl.Message(
        content=(
            f"✅ **Réponse validée** par `{operator_id}` (`{operator_role}`) "
            f"pour envoi au client **`{client_id}`** *(Trace : `{trace_id}`)*."
        )
    ).send()


@cl.action_callback("escalate_response")
async def on_escalate_response(action: cl.Action) -> None:
    """Déclenche l'escalade du ticket vers le Responsable Support (`MANAGER`).

    Args:
        action: Objet `cl.Action` contenant les métadonnées du ticket.

    Returns:
        None.
    """
    operator_id = str(cl.user_session.get("operator_id", "agent"))
    operator_role = str(cl.user_session.get("operator_role", "AGENT"))
    payload = action.payload or {}
    trace_id = payload.get("trace_id", "N/A")
    client_id = payload.get("client_id", "N/A")
    severity = payload.get("severity", "N/A")

    await cl.Message(
        content=(
            f"🚨 **Escalade enregistrée vers le Responsable Support (`MANAGER`)** "
            f"par `{operator_id}` (`{operator_role}`) — Client : **`{client_id}`**, "
            f"Sévérité : **`{severity}`**, Trace : `{trace_id}`."
        )
    ).send()


@cl.action_callback("reject_response")
async def on_reject_response(action: cl.Action) -> None:
    """Enregistre le rejet du brouillon LLM par l'opérateur et invite à reformuler.

    Args:
        action: Objet `cl.Action` contenant les métadonnées de la trace.

    Returns:
        None.
    """
    operator_id = str(cl.user_session.get("operator_id", "agent"))
    payload = action.payload or {}
    trace_id = payload.get("trace_id", "N/A")

    await cl.Message(
        content=(
            f"❌ **Brouillon rejeté** par `{operator_id}` *(Trace : `{trace_id}`)*. "
            "Vous pouvez préciser votre question ou ajuster le contexte dans les paramètres ⚙️."
        )
    ).send()


__all__ = [
    "CLIENT_ID_OPTIONS",
    "SEVERITY_OPTIONS",
    "authenticate_operator",
    "build_human_validation_actions",
    "build_sidebar_markdown",
    "call_backend_chat_api",
    "verify_credentials_constant_time",
]
