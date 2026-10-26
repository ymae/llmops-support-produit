"""Module de configuration centralisée du microservice Backend API.

Ce module utilise `pydantic-settings` pour charger et valider les variables
d'environnement depuis le fichier `.env` ou l'environnement système Docker.
Il garantit notamment que l'observabilité cognitive Langfuse pointe par défaut
vers l'instance locale auto-hébergée (`http://localhost:3000`) et jamais vers
le cloud public.
"""

from functools import lru_cache
from pathlib import Path

from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """Classe de configuration principale.

    Centralise les paramètres de connexion à LiteLLM Proxy, les secrets de
    sécurité API (Bearer Token et JWT HS256), ainsi que la
    configuration du système d'observabilité (Logger JSON + Langfuse).
    """

    # Configuration du chargement depuis le fichier .env à la racine du projet
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
        case_sensitive=False,
    )

    # --- 1. Fournisseur LLM Externe (Groq via LiteLLM Proxy) ---
    groq_api_key: str = Field(
        default="gsk_placeholder_key",
        description="Clé API externe Groq (utilisée par le conteneur litellm-proxy).",
    )
    groq_model_name: str = Field(
        default="groq/openai/gpt-oss-20b",
        description="Identifiant du modèle Groq cible routé par LiteLLM Proxy.",
    )
    litellm_master_key: str = Field(
        default="sk-nexus-litellm-master-key-v1",
        description="Clé maîtresse d'authentification auprès du conteneur LiteLLM Proxy.",
    )
    litellm_proxy_url: str = Field(
        default="http://litellm-proxy:4000/v1",
        description="URL interne du serveur LiteLLM Proxy compatible OpenAI.",
    )
    litellm_model_name: str = Field(
        default="nexus-support-llm",
        description="Alias du modèle déclaré dans la configuration LiteLLM Proxy.",
    )
    llm_temperature: float = Field(
        default=0.1,
        ge=0.0,
        le=2.0,
        description="Température d'inférence faible pour privilégier la rigueur factuelle.",
    )
    llm_request_timeout: float = Field(
        default=30.0,
        gt=0.0,
        description="Délai maximal d'attente (en secondes) lors d'un appel à LiteLLM Proxy.",
    )

    # --- 2. Sécurité API Backend (FastAPI HTTPBearer & JWT HS256) ---
    api_secret_token: str = Field(
        default="nexus-v1-secret-bearer-token-2026",
        description="Jeton secret Bearer statique autorisé pour accéder aux routes métiers FastAPI.",
    )
    jwt_secret_key: str = Field(
        default="nexus-v1-jwt-hs256-secret-key-2026-change-me",
        description="Clé secrète de signature des jetons JWT inter-services (HS256).",
    )
    jwt_algorithm: str = Field(
        default="HS256",
        description="Algorithme cryptographique utilisé pour signer les jetons JWT.",
    )
    jwt_expire_minutes: int = Field(
        default=60,
        gt=0,
        description="Durée de validité (en minutes) d'un jeton JWT opérateur.",
    )
    backend_api_url: str = Field(
        default="http://backend-api:8080",
        description="URL du microservice backend appelée par le frontend Chainlit.",
    )

    # --- 3. Authentification Opérateurs Frontend (Chainlit) ---
    chainlit_auth_secret: str = Field(
        default="nexus-chainlit-auth-secret-key-v1-2026-change-me",
        description="Secret de signature des sessions d'authentification Chainlit.",
    )
    agent_username: str = Field(
        default="agent",
        description="Identifiant de connexion du profil Agent Support (rôle AGENT).",
    )
    agent_password: str = Field(
        default="agent-pass",
        description="Mot de passe du profil Agent Support.",
    )
    manager_username: str = Field(
        default="manager",
        description="Identifiant de connexion du profil Responsable Support (rôle MANAGER).",
    )
    manager_password: str = Field(
        default="manager-pass",
        description="Mot de passe du profil Responsable Support.",
    )

    # --- 4. Observabilité Niveau 1 : Logger JSON Structuré Local ---
    log_level: str = Field(
        default="INFO",
        description="Niveau de sévérité minimal pour la journalisation système.",
    )
    log_file_path: str = Field(
        default="logs/app.jsonl",
        description="Chemin relatif ou absolu du fichier local de traces JSONL.",
    )

    # --- 5. Observabilité Niveau 2 : Langfuse Auto-Hébergé Local ---
    langfuse_enabled: bool = Field(
        default=True,
        description="Active ou désactive l'envoi des traces cognitives vers Langfuse local.",
    )
    langfuse_public_key: str = Field(
        default="pk-lf-local-nexus",
        description="Clé publique locale du projet Langfuse auto-hébergé.",
    )
    langfuse_secret_key: str = Field(
        default="sk-lf-local-nexus",
        description="Clé secrète locale du projet Langfuse auto-hébergé.",
    )
    langfuse_host: str = Field(
        default="http://localhost:3000",
        description="Hôte de l'instance Langfuse locale (surchargé par http://langfuse-server:3000 dans Docker).",
    )

    def get_resolved_log_path(self) -> Path:
        """Résout le chemin du fichier de log JSON et garantit l'existence du dossier parent.

        Args:
            Aucun argument requis.

        Returns:
            Un objet `Path` pointant vers le fichier de journalisation JSONL.

        Raises:
            OSError: Si la création du répertoire parent échoue pour des raisons de permissions.
        """
        # Conversion de la chaîne de configuration en chemin système Path
        log_path = Path(self.log_file_path)
        # Création automatique de l'arborescence parente (ex: logs/) si elle n'existe pas
        log_path.parent.mkdir(parents=True, exist_ok=True)
        return log_path


@lru_cache(maxsize=1)
def get_settings() -> Settings:
    """Retourne une instance singleton mise en cache de la configuration `Settings`.

    Permet d'éviter la relecture disque répétée du fichier `.env` à chaque requête
    HTTP tout en facilitant la surcharge lors des tests unitaires `pytest`.

    Args:
        Aucun argument requis.

    Returns:
        L'instance unique de `Settings` initialisée avec les variables courantes.
    """
    # Instanciation unique mise en cache mémoire
    return Settings()
