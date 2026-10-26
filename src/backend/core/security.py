"""Module de sécurité, d'authentification JWT (HS256) et de protection HTTPBearer.

Ce module combine les bonnes pratiques suivantes :
- hachage PBKDF2-SHA256 avec sel aléatoire
- jetons JWT signés en HS256 avec expiration
- protection par `HTTPBearer`
- journalisation systématique des rejets HTTP 401/403
"""

from datetime import datetime, timedelta, timezone
import hashlib
import hmac
import secrets
from typing import Optional

from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
import jwt

from src.backend.core.config import get_settings
from src.backend.core.schemas import OperatorRole, OperatorUser
from src.backend.observability.logger import log_structured_event


# Nombre d'itérations PBKDF2 pour ralentir toute tentative d'attaque par force brute
PASSWORD_HASH_ITERATIONS: int = 100_000

# Schéma d'extraction Bearer sans erreur automatique afin de personnaliser l'audit JSON
bearer_scheme = HTTPBearer(
    auto_error=False,
    description="Jeton Bearer (JWT HS256 ou API_SECRET_TOKEN) requis pour interroger l'API Support Produit Nexus.",
)


def hash_password(password: str) -> str:
    """Hache un mot de passe avec PBKDF2-SHA256 et un sel aléatoire de 16 octets.

    Args:
        password: Mot de passe à protéger.

    Returns:
        Une chaîne au format `<sel_hex>$<empreinte_hex>` prête à être stockée.
    """
    salt = secrets.token_bytes(16)
    digest = hashlib.pbkdf2_hmac(
        "sha256",
        password.encode("utf-8"),
        salt,
        PASSWORD_HASH_ITERATIONS,
    )
    return f"{salt.hex()}${digest.hex()}"


def verify_password(password: str, stored_hash: str) -> bool:
    """Vérifie en temps constant qu'un mot de passe correspond à son hachage PBKDF2.

    Args:
        password: Mot de passe soumis par l'opérateur.
        stored_hash: Chaîne `<sel_hex>$<empreinte_hex>` produite par `hash_password`.

    Returns:
        True si le mot de passe correspond exactement, False sinon.
    """
    try:
        salt_hex, digest_hex = stored_hash.split("$", maxsplit=1)
        digest = hashlib.pbkdf2_hmac(
            "sha256",
            password.encode("utf-8"),
            bytes.fromhex(salt_hex),
            PASSWORD_HASH_ITERATIONS,
        )
        # Comparaison en temps constant pour prévenir les attaques temporelles
        return hmac.compare_digest(digest.hex(), digest_hex)
    except ValueError:
        return False


def verify_credentials_constant_time(
    provided_user: str,
    provided_pass: str,
    expected_user: str,
    expected_pass: str,
) -> bool:
    """Compare en temps constant un couple identifiant/mot de passe avec la référence.

    Args:
        provided_user: Identifiant saisi par l'opérateur.
        provided_pass: Mot de passe saisi par l'opérateur.
        expected_user: Identifiant de référence configuré dans `.env`.
        expected_pass: Mot de passe de référence configuré dans `.env`.

    Returns:
        True si l'identifiant et le mot de passe correspondent exactement, False sinon.
    """
    user_matches = secrets.compare_digest(
        provided_user.encode("utf-8"),
        expected_user.encode("utf-8"),
    )
    pass_matches = secrets.compare_digest(
        provided_pass.encode("utf-8"),
        expected_pass.encode("utf-8"),
    )
    return user_matches and pass_matches


def authenticate_operator_credentials(
    username: str,
    password: str,
) -> Optional[OperatorUser]:
    """Vérifie les identifiants d'un opérateur et retourne son profil métier (`AGENT` ou `MANAGER`).

    Args:
        username: Nom d'utilisateur soumis (ex: `agent` ou `manager`).
        password: Mot de passe soumis.

    Returns:
        Une instance `OperatorUser` si les identifiants sont valides, ou `None` sinon.
    """
    settings = get_settings()
    cleaned_username = username.strip()

    # Vérification du profil Agent du Support Technique (rôle AGENT)
    if verify_credentials_constant_time(
        cleaned_username,
        password,
        settings.agent_username,
        settings.agent_password,
    ):
        return OperatorUser(
            username=settings.agent_username,
            role=OperatorRole.AGENT,
        )

    # Vérification du profil Responsable Support (rôle MANAGER)
    if verify_credentials_constant_time(
        cleaned_username,
        password,
        settings.manager_username,
        settings.manager_password,
    ):
        return OperatorUser(
            username=settings.manager_username,
            role=OperatorRole.MANAGER,
        )

    return None


def create_access_token(
    operator_id: str,
    operator_role: OperatorRole = OperatorRole.AGENT,
    expires_delta_minutes: Optional[int] = None,
) -> str:
    """Crée un jeton JWT signé en HS256 pour un opérateur support authentifié.

    Args:
        operator_id: Identifiant de l'opérateur stocké dans le claim `sub`.
        operator_role: Rôle métier (`AGENT` ou `MANAGER`) stocké dans le claim `role`.
        expires_delta_minutes: Durée de validité personnalisée en minutes (optionnelle).

    Returns:
        Le jeton JWT encodé et signé sous forme de chaîne de caractères.
    """
    settings = get_settings()
    now = datetime.now(timezone.utc)
    expire_minutes = (
        expires_delta_minutes
        if expires_delta_minutes is not None
        else settings.jwt_expire_minutes
    )
    expires_at = now + timedelta(minutes=expire_minutes)
    payload = {
        "sub": operator_id,
        "role": operator_role.value,
        "iat": now,
        "exp": expires_at,
    }
    return jwt.encode(
        payload,
        settings.jwt_secret_key,
        algorithm=settings.jwt_algorithm,
    )


def decode_access_token(token: str) -> OperatorUser:
    """Décode et vérifie la signature HS256 ainsi que l'expiration d'un jeton JWT.

    Args:
        token: Chaîne du jeton JWT extrait de l'en-tête HTTP Authorization.

    Returns:
        L'objet `OperatorUser` reconstruit à partir des claims vérifiés (`sub`, `role`).

    Raises:
        jwt.ExpiredSignatureError: Si la date d'expiration (`exp`) du jeton est dépassée.
        jwt.InvalidTokenError: Si la signature ou la structure du jeton est invalide.
    """
    settings = get_settings()
    payload = jwt.decode(
        token,
        settings.jwt_secret_key,
        algorithms=[settings.jwt_algorithm],
    )
    username = payload.get("sub")
    raw_role = payload.get("role", OperatorRole.AGENT.value)
    if not username or not isinstance(username, str):
        raise jwt.InvalidTokenError("Claim 'sub' manquant ou invalide dans le jeton JWT.")

    try:
        role = OperatorRole(str(raw_role))
    except ValueError as exc:
        raise jwt.InvalidTokenError(f"Rôle métier invalide dans le jeton JWT : {raw_role}") from exc

    return OperatorUser(username=username, role=role)


async def verify_bearer_token(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
) -> str:
    """Vérifie la présence et la validité du jeton Bearer (JWT HS256 ou API_SECRET_TOKEN).

    En cas d'absence de l'en-tête `Authorization` ou de schéma invalide, lève une
    erreur `HTTP 401 Unauthorized`. En cas de jeton erroné ou de JWT expiré, lève
    une erreur `HTTP 403 Forbidden`. Dans les deux cas, l'événement de sécurité est
    tracé dans `logs/app.jsonl` avant tout appel à LiteLLM Proxy / Groq.

    Args:
        request: Objet `Request` FastAPI permettant d'extraire le chemin et l'IP.
        credentials: Identifiants extraits par `HTTPBearer` depuis l'en-tête HTTP.

    Returns:
        Le jeton Bearer validé sous forme de chaîne de caractères.

    Raises:
        HTTPException: `401 Unauthorized` si le jeton est absent, ou
            `403 Forbidden` si le jeton n'est ni un JWT valide ni `API_SECRET_TOKEN`.
    """
    settings = get_settings()
    client_host = request.client.host if request.client else "unknown"
    request_path = str(request.url.path)

    # Cas 1 : Aucun en-tête Authorization Bearer fourni par l'appelant
    if credentials is None or not credentials.credentials:
        log_structured_event(
            event="auth_missing_token",
            message="Rejet de sécurité : en-tête Authorization Bearer manquant.",
            level="WARNING",
            status_code=status.HTTP_401_UNAUTHORIZED,
            extra_data={
                "path": request_path,
                "client_host": client_host,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentification requise : jeton Bearer manquant.",
            headers={"WWW-Authenticate": "Bearer"},
        )

    provided_token = credentials.credentials
    expected_static_token = settings.api_secret_token

    # Vérification 1 : Comparaison en temps constant avec le jeton statique API_SECRET_TOKEN
    is_valid_static_token = secrets.compare_digest(
        provided_token.encode("utf-8"),
        expected_static_token.encode("utf-8"),
    )
    if is_valid_static_token:
        request.state.operator_user = OperatorUser(
            username=settings.agent_username,
            role=OperatorRole.AGENT,
        )
        return provided_token

    # Vérification 2 : Décodage et validation cryptographique du jeton JWT (HS256)
    try:
        operator_user = decode_access_token(provided_token)
        request.state.operator_user = operator_user
        return provided_token
    except jwt.ExpiredSignatureError as exc:
        log_structured_event(
            event="auth_expired_jwt",
            message="Rejet de sécurité : jeton JWT expiré fourni à l'API.",
            level="WARNING",
            status_code=status.HTTP_403_FORBIDDEN,
            extra_data={
                "path": request_path,
                "client_host": client_host,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : jeton JWT expiré, veuillez vous reconnecter.",
        ) from exc
    except jwt.InvalidTokenError as exc:
        log_structured_event(
            event="auth_invalid_token",
            message="Rejet de sécurité : jeton Bearer ou JWT invalide fourni à l'API.",
            level="WARNING",
            status_code=status.HTTP_403_FORBIDDEN,
            extra_data={
                "path": request_path,
                "client_host": client_host,
            },
        )
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Accès refusé : jeton Bearer invalide.",
        ) from exc
