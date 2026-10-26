"""Module définissant les règles d'interface Pydantic.

Ce module utilise les bonnes pratiques :
- Usage de `NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]`
  pour éliminer automatiquement les espaces superflus et rejeter les chaînes vides (`HTTP 422`).
- Validation stricte de la liste blanche des identifiants clients (`CLI-001` à `CLI-015`)
  afin de rejeter tout identifiant inconnu (tel que `CLI-099` du cas de test `GD-08`)
  avant même d'invoquer LiteLLM Proxy / Groq.
- Schémas d'authentification JWT (`LoginRequest`, `TokenResponse`, `OperatorUser`) et
  de consultation de l'historique conversationnel (`HistoryEntry`, `HistoryResponse`).
"""

from enum import Enum
from typing import Annotated, Literal, Optional

from pydantic import BaseModel, Field, StringConstraints, field_validator

from src.backend.core.constants import VALID_CLIENT_IDS


# Chaîne obligatoire : les espaces autour sont retirés et elle ne doit pas être vide
NonEmptyStr = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1)]


class OperatorRole(str, Enum):
    """Énumération des rôles métiers autorisés pour les opérateurs support.

    Attributes:
        AGENT: Agent du support technique de niveau 1/2.
        MANAGER: Responsable support habilité à traiter les escalades critiques.
    """

    AGENT = "AGENT"
    MANAGER = "MANAGER"


class SeverityLevel(str, Enum):
    """Énumération des niveaux de criticité d'un ticket support.

    Attributes:
        LOW: Impact mineur ou question documentaire simple.
        MEDIUM: Anomalie gênante disposant d'un contournement potentiel.
        HIGH: Fonctionnalité majeure dégradée en production.
        CRITICAL: Arrêt de service, perte de données ou faille de sécurité.
    """

    LOW = "LOW"
    MEDIUM = "MEDIUM"
    HIGH = "HIGH"
    CRITICAL = "CRITICAL"


# ---------------------------------------------------------------------------
# Schémas d'Authentification Opérateur (JWT HS256)
# ---------------------------------------------------------------------------


class LoginRequest(BaseModel):
    """Identifiants envoyés par un opérateur pour obtenir un jeton JWT signé.

    Attributes:
        username: Identifiant de connexion de l'opérateur (`agent` ou `manager`).
        password: Mot de passe à vérifier.
    """

    username: NonEmptyStr = Field(
        ...,
        description="Identifiant de l'opérateur support.",
        examples=["agent"],
    )
    password: NonEmptyStr = Field(
        ...,
        description="Mot de passe de l'opérateur support.",
        examples=["agent-pass"],
    )


class OperatorUser(BaseModel):
    """Représentation publique d'un opérateur authentifié (sans donnée sensible).

    Attributes:
        username: Identifiant de l'opérateur authentifié.
        role: Rôle métier attribué (`AGENT` ou `MANAGER`).
    """

    username: NonEmptyStr = Field(
        ...,
        description="Identifiant de l'opérateur authentifié.",
        examples=["agent"],
    )
    role: OperatorRole = Field(
        default=OperatorRole.AGENT,
        description="Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).",
    )


class TokenResponse(BaseModel):
    """Jeton d'accès JWT renvoyé après une authentification réussie.

    Attributes:
        access_token: Jeton JWT signé en HS256.
        token_type: Type de schéma HTTP (`bearer`).
        operator_id: Identifiant de l'opérateur authentifié.
        operator_role: Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).
    """

    access_token: str = Field(
        ...,
        description="Jeton JWT signé en HS256 à transmettre dans Authorization: Bearer.",
    )
    token_type: str = Field(
        default="bearer",
        description="Type de jeton d'authentification HTTP.",
    )
    operator_id: str = Field(
        ...,
        description="Identifiant de l'opérateur support.",
    )
    operator_role: OperatorRole = Field(
        ...,
        description="Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).",
    )


# ---------------------------------------------------------------------------
# Schémas du Contrat d'Entrée / Sortie Support (/api/v1/chat)
# ---------------------------------------------------------------------------


class ChatMessage(BaseModel):
    """Représente un message unitaire au sein de l'historique conversationnel.

    Attributes:
        role: Émetteur du message (`user`, `assistant` ou `system`).
        content: Contenu textuel non vide du message échangé.
    """

    role: Literal["user", "assistant", "system"] = Field(
        ...,
        description="Rôle de l'auteur du message dans l'historique de conversation.",
        examples=["user"],
    )
    content: NonEmptyStr = Field(
        ...,
        description="Contenu textuel non vide du message.",
        examples=["Bonjour, j'ouvre un ticket pour le client CLI-003."],
    )


class ChatRequest(BaseModel):
    """Schéma Pydantic du contrat d'entrée pour la route `POST /api/v1/chat`.

    Valide l'identité de l'opérateur, la conformité du `client_id` par rapport
    au référentiel autorisé (`CLI-001` à `CLI-015`), la sévérité du ticket et
    le message courant accompagné de son historique.
    """

    session_id: NonEmptyStr = Field(
        ...,
        description="Identifiant unique de la session conversationnelle Chainlit.",
        examples=["sess-gd01-demo"],
    )
    operator_id: NonEmptyStr = Field(
        ...,
        description="Identifiant de l'opérateur support authentifié.",
        examples=["agent"],
    )
    operator_role: OperatorRole = Field(
        ...,
        description="Rôle métier de l'opérateur (`AGENT` ou `MANAGER`).",
        examples=[OperatorRole.AGENT],
    )
    client_id: NonEmptyStr = Field(
        ...,
        description="Identifiant du client (`CLI-001` à `CLI-015`).",
        examples=["CLI-003"],
    )
    severity: SeverityLevel = Field(
        ...,
        description="Niveau de sévérité déclaré pour le ticket (`LOW` à `CRITICAL`).",
        examples=[SeverityLevel.MEDIUM],
    )
    message: NonEmptyStr = Field(
        ...,
        description="Question ou description du problème soumise par l'agent support.",
        examples=[
            "Le service plante au démarrage avec le message : "
            "ImportError: cannot import name 'DataConnector' from 'nexus.core'."
        ],
    )
    history: list[ChatMessage] = Field(
        default_factory=list,
        description="Historique des messages précédents de la session.",
    )

    @field_validator("client_id")
    @classmethod
    def validate_client_id(cls, value: str) -> str:
        """Vérifie que l'identifiant client appartient à la liste autorisée `CLI-001`..`CLI-015`.

        Ce garde-fou déterministe bloque immédiatement les clients non reconnus
        (ex: `CLI-099` du scénario `GD-08`) conformément aux règles de refus métier.

        Args:
            value: Identifiant client brut fourni dans le payload JSON.

        Returns:
            L'identifiant client nettoyé et normalisé en majuscules.

        Raises:
            ValueError: Si l'identifiant client ne figure pas dans `VALID_CLIENT_IDS`.
        """
        normalized_id = value.strip().upper()
        # Vérification stricte de l'appartenance au référentiel des 15 clients
        if normalized_id not in VALID_CLIENT_IDS:
            raise ValueError(
                f"Client non reconnu ou non autorisé : '{value}'. "
                f"Les identifiants valides vont de CLI-001 à CLI-015 (règle GD-08)."
            )
        return normalized_id


class ClientContext(BaseModel):
    """Sous-schéma décrivant le contexte client restitué dans la réponse.

    Ce schéma transporte le `client_id` et la sévérité sélectionnée, 
    tout en réservant les champs `product_version` et `sla_level`
    qui seront ajoutés en V2 avec le croisement CSV.
    """

    client_id: str = Field(
        ...,
        description="Identifiant validé du client (`CLI-001` à `CLI-015`).",
    )
    severity: SeverityLevel = Field(
        ...,
        description="Niveau de sévérité pris en compte lors du traitement.",
    )
    product_version: Optional[str] = Field(
        default="Non résolue (Mode Baseline V1 - sans RAG/CSV)",
        description="Version du produit déployée chez le client (enrichie en V2).",
    )
    sla_level: Optional[str] = Field(
        default="Non résolu (Mode Baseline V1 - sans RAG/CSV)",
        description="Niveau d'engagement contractuel SLA du client (enrichi en V2).",
    )
    mode: str = Field(
        default="V1_BASELINE_PASSTHROUGH",
        description="Mode de fonctionnement du moteur d'enrichissement métier.",
    )


class ChatResponse(BaseModel):
    """Schéma Pydantic de réponse pour la route `POST /api/v1/chat`.

    Garantit que chaque réponse de l'assistant s'accompagne des indicateurs de
    gouvernance humaine (`requires_human_validation`, `escalation_required`)
    et de l'identifiant de trace `trace_id`.
    """

    answer: str = Field(
        ...,
        description="Proposition de réponse générée par le LLM à destination de l'agent support.",
    )
    client_context: ClientContext = Field(
        ...,
        description="Métadonnées de contexte associées au client et au ticket.",
    )
    sources: list[str] = Field(
        default_factory=list,
        description="Liste des sources documentaires mobilisées (vide en V1 Baseline).",
    )
    requires_human_validation: bool = Field(
        default=True,
        description="Indique si une validation humaine est obligatoire avant envoi externe.",
    )
    escalation_required: bool = Field(
        default=False,
        description="Indique si le ticket impose une escalade vers le Responsable Support.",
    )
    trace_id: str = Field(
        ...,
        description="Identifiant unique de la trace d'exécution (Logger JSON & Langfuse).",
    )


# ---------------------------------------------------------------------------
# Schémas de l'Historique Conversationnel (/api/v1/history/{session_id})
# ---------------------------------------------------------------------------


class HistoryEntry(BaseModel):
    """Élément unitaire de l'historique conversationnel d'une session support.

    Attributes:
        role: Auteur du message (`user` ou `assistant`).
        content: Contenu du message ou de la réponse.
        client_id: Identifiant du client actif lors de l'échange.
        severity: Niveau de sévérité lors de l'échange.
        operator_id: Identifiant de l'opérateur.
        trace_id: Identifiant de trace associé à l'échange.
    """

    role: Literal["user", "assistant"] = Field(
        ...,
        description="Auteur du message (`user` ou `assistant`).",
    )
    content: str = Field(
        ...,
        description="Contenu textuel du message.",
    )
    client_id: str = Field(
        ...,
        description="Identifiant du client concerné (`CLI-001` à `CLI-015`).",
    )
    severity: str = Field(
        ...,
        description="Sévérité du ticket lors de l'échange.",
    )
    operator_id: str = Field(
        ...,
        description="Identifiant de l'opérateur support.",
    )
    trace_id: str = Field(
        ...,
        description="Identifiant de trace associé.",
    )


class HistoryResponse(BaseModel):
    """Historique complet des échanges d'une session support.

    Attributes:
        session_id: Identifiant de la session support.
        history: Liste ordonnée des échanges enregistrés en mémoire.
    """

    session_id: str = Field(
        ...,
        description="Identifiant de la session support.",
    )
    history: list[HistoryEntry] = Field(
        default_factory=list,
        description="Entrées de l'historique, de la plus ancienne à la plus récente.",
    )
