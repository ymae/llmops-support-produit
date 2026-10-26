"""Initialisation et mise en cache du client LLM branché sur LiteLLM Proxy.

Ce module utilise `@lru_cache(maxsize=1)` pour créer le modèle de chat au premier appel puis
partager la même instance entre toutes les chaînes LangChain, tout en respectant
strictement la règle de découplage (passage obligatoire par le
conteneur `litellm-proxy`, sans jamais interroger l'API Groq en direct).
"""

from functools import lru_cache

from langchain_openai import ChatOpenAI

from src.backend.core.config import get_settings


@lru_cache(maxsize=1)
def get_llm() -> ChatOpenAI:
    """Retourne l'instance singleton du client `ChatOpenAI` pointant sur LiteLLM Proxy.

    Le modèle est instancié uniquement lors du premier appel puis mis en cache,
    ce qui permet d'importer toute l'application sans connexion réseau et d'éviter
    la recréation coûteuse du pool HTTP à chaque requête support.

    Args:
        Aucun argument requis.

    Returns:
        L'instance `ChatOpenAI` configurée avec `LITELLM_PROXY_URL` et `LITELLM_MASTER_KEY`.
    """
    settings = get_settings()
    return ChatOpenAI(
        model=settings.litellm_model_name,
        api_key=settings.litellm_master_key,
        base_url=settings.litellm_proxy_url,
        temperature=settings.llm_temperature,
        timeout=settings.llm_request_timeout,
        max_retries=1,
    )
