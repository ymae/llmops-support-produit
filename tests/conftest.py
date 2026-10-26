"""Configuration partagée et fixtures `pytest` pour les tests du Backend API.

Ce module fournit des fixtures isolées permettant de tester la sécurité Bearer & JWT,
la validation Pydantic, la mémoire conversationnelle et l'orchestration LLM avec
`httpx.AsyncClient` tout en redirigeant le Logger JSON structuré vers un fichier
temporaire dédié à chaque test.
"""

from collections.abc import AsyncGenerator, Callable
import json
from pathlib import Path
from typing import Any

import httpx
import pytest
import pytest_asyncio

from src.backend.api.main import app
from src.backend.core.chains import get_support_chat_chain
from src.backend.core.config import get_settings
from src.backend.core.llm import get_llm
from src.backend.core.schemas import OperatorRole
from src.backend.core.security import create_access_token
from src.backend.memory import session_memory


TEST_API_TOKEN: str = "nexus-pytest-secret-bearer-token-2026"
TEST_JWT_SECRET: str = "nexus-pytest-jwt-hs256-secret-key-2026-secure"


@pytest.fixture(autouse=True)
def isolated_test_environment(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> Path:
    """Isole la configuration, la mémoire et le fichier de log JSONL pour chaque test.

    Surcharge les variables d'environnement via `monkeypatch`, vide les caches
    singletons (`get_settings`, `get_llm`, `get_support_chat_chain`) ainsi que
    la mémoire de session (`session_memory.clear_history()`).

    Args:
        tmp_path: Répertoire temporaire unique fourni nativement par `pytest`.
        monkeypatch: Utilitaire `pytest` pour modifier l'environnement de manière sûre.

    Returns:
        Le chemin `Path` du fichier de journalisation JSONL isolé pour le test.
    """
    log_file = tmp_path / "test_app.jsonl"

    # Surcharge des variables critiques pour garantir des tests déterministes et hors-ligne
    monkeypatch.setenv("API_SECRET_TOKEN", TEST_API_TOKEN)
    monkeypatch.setenv("JWT_SECRET_KEY", TEST_JWT_SECRET)
    monkeypatch.setenv("LOG_FILE_PATH", str(log_file))
    monkeypatch.setenv("LANGFUSE_ENABLED", "false")
    monkeypatch.setenv("LANGFUSE_HOST", "http://localhost:3000")
    monkeypatch.setenv("LANGFUSE_PUBLIC_KEY", "pk-lf-local-nexus")
    monkeypatch.setenv("LANGFUSE_SECRET_KEY", "sk-lf-local-nexus")

    # Réinitialisation des caches singletons et de la mémoire avant le test
    get_settings.cache_clear()
    get_llm.cache_clear()
    get_support_chat_chain.cache_clear()
    session_memory.clear_history()

    yield log_file

    # Réinitialisation des caches singletons et de la mémoire après le test
    get_settings.cache_clear()
    get_llm.cache_clear()
    get_support_chat_chain.cache_clear()
    session_memory.clear_history()


@pytest.fixture
def read_json_logs(
    isolated_test_environment: Path,
) -> Callable[[], list[dict[str, Any]]]:
    """Fournit une fonction utilitaire lisant toutes les entrées du log JSONL de test.

    Args:
        isolated_test_environment: Chemin du fichier de log temporaire injecté.

    Returns:
        Une fonction sans argument retournant la liste des dictionnaires JSON journalisés.
    """

    def _reader() -> list[dict[str, Any]]:
        """Lit et désérialise chaque ligne du fichier JSONL temporaire.

        Args:
            Aucun argument requis.

        Returns:
            Liste ordonnée des événements JSON enregistrés pendant le test.
        """
        if not isolated_test_environment.exists():
            return []
        lines = isolated_test_environment.read_text(encoding="utf-8").splitlines()
        return [json.loads(line) for line in lines if line.strip()]

    return _reader


@pytest.fixture
def valid_auth_headers() -> dict[str, str]:
    """Construit l'en-tête HTTP Authorization contenant le Bearer Token valide.

    Args:
        Aucun argument requis.

    Returns:
        Un dictionnaire d'en-têtes HTTP prêt à être transmis à `httpx.AsyncClient`.
    """
    return {"Authorization": f"Bearer {TEST_API_TOKEN}"}


@pytest.fixture
def valid_jwt_headers() -> dict[str, str]:
    """Construit l'en-tête HTTP Authorization contenant un jeton JWT signé (HS256) valide.

    Args:
        Aucun argument requis.

    Returns:
        Un dictionnaire d'en-têtes HTTP contenant un jeton JWT opérateur `AGENT`.
    """
    jwt_token = create_access_token(
        operator_id="agent",
        operator_role=OperatorRole.AGENT,
    )
    return {"Authorization": f"Bearer {jwt_token}"}


@pytest_asyncio.fixture
async def async_client() -> AsyncGenerator[httpx.AsyncClient, None]:
    """Fournit un client HTTP asynchrone `httpx.AsyncClient` branché sur l'application FastAPI.

    Args:
        Aucun argument requis.

    Returns:
        Un générateur asynchrone exposant l'instance `httpx.AsyncClient`.
    """
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(
        transport=transport,
        base_url="http://testserver",
    ) as client:
        yield client
