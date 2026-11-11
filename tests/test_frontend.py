"""Tests unitaires du module Frontend Streamlit (`src/frontend/app.py`).

Vérifie :
- L'authentification obligatoire pour les profils
  `agent` (rôle `AGENT`) et `manager` (rôle `MANAGER`), la génération d'un jeton
  JWT signé en HS256 dans les métadonnées utilisateur, ainsi que le rejet des
  identifiants invalides.
- Les listes de sélection `CLIENT_ID_OPTIONS` (`CLI-001` à `CLI-015`) et
  `SEVERITY_OPTIONS` (`LOW`, `MEDIUM`, `HIGH`, `CRITICAL`).
- Le rendu Markdown du panneau latéral (`ElementSidebar`) et les actions HitL.
"""

from src.backend.core.schemas import OperatorRole
from src.backend.core.security import decode_access_token
from src.frontend.app import (
    CLIENT_ID_OPTIONS,
    SEVERITY_OPTIONS,
    authenticate_operator,
    build_human_validation_actions,
    build_sidebar_markdown,
)


def test_streamlit_client_and_severity_options() -> None:
    """Vérifie que les listes de sélection Streamlit respectent le contrat métier V1/V2.

    Args:
        Aucun argument requis.

    Returns:
        None.
    """
    assert len(CLIENT_ID_OPTIONS) == 15
    assert CLIENT_ID_OPTIONS[0] == "CLI-001"
    assert CLIENT_ID_OPTIONS[-1] == "CLI-015"
    assert "CLI-099" not in CLIENT_ID_OPTIONS
    assert SEVERITY_OPTIONS == ["LOW", "MEDIUM", "HIGH", "CRITICAL"]


def test_authenticate_operator_agent_and_manager_profiles_with_jwt() -> None:
    """Vérifie que `authenticate_operator` distingue `AGENT`, `MANAGER`, génère un JWT HS256 et rejette un intrus.

    Args:
        Aucun argument requis.

    Returns:
        None.
    """
    # Profil Agent Support
    agent_user = authenticate_operator("agent", "agent-pass")
    assert agent_user is not None
    assert agent_user.identifier == "agent"
    assert agent_user.role == "AGENT"
    decoded_agent = decode_access_token(agent_user.access_token)
    assert decoded_agent.username == "agent"
    assert decoded_agent.role == OperatorRole.AGENT

    # Profil Responsable Support (Manager)
    manager_user = authenticate_operator("manager", "manager-pass")
    assert manager_user is not None
    assert manager_user.identifier == "manager"
    assert manager_user.role == "MANAGER"
    decoded_manager = decode_access_token(manager_user.access_token)
    assert decoded_manager.username == "manager"
    assert decoded_manager.role == OperatorRole.MANAGER

    # Rejet d'un mot de passe erroné ou d'un utilisateur inconnu
    assert authenticate_operator("agent", "wrong-password") is None
    assert authenticate_operator("unknown", "agent-pass") is None


def test_build_sidebar_markdown_and_actions() -> None:
    """Vérifie le contenu du panneau latéral `ElementSidebar` et des boutons HitL.

    Args:
        Aucun argument requis.

    Returns:
        None.
    """
    markdown = build_sidebar_markdown(
        operator_id="agent",
        operator_role="AGENT",
        client_id="CLI-004",
        severity="CRITICAL",
        response_data={
            "client_context": {
                "product_version": "Non résolue (Mode Baseline V1 - sans RAG/CSV)",
                "sla_level": "Non résolu (Mode Baseline V1 - sans RAG/CSV)",
            },
            "requires_human_validation": True,
            "escalation_required": True,
            "trace_id": "trace-abc123",
            "sources": [],
        },
    )
    assert "CLI-004" in markdown
    assert "CRITICAL" in markdown
    assert "trace-abc123" in markdown
    assert "OUI (CRITIQUE / SENSIBLE)" in markdown

    actions = build_human_validation_actions(
        trace_id="trace-abc123",
        client_id="CLI-004",
        severity="CRITICAL",
        escalation_required=True,
    )
    assert len(actions) == 3
    action_names = [act.name for act in actions]
    assert action_names == [
        "validate_response",
        "escalate_response",
        "reject_response",
    ]
