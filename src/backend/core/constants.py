"""Constantes métiers partagées entre le microservice Backend API et le Frontend Chainlit.

Ce module constitue la source unique de vérité pour :
- La liste blanche des identifiants clients reconnus (`CLI-001` à `CLI-015`).
- Les options de sélection de l'interface opérateur (`CLIENT_ID_OPTIONS`, `SEVERITY_OPTIONS`).
- Les mots-clés critiques déclenchant une escalade obligatoire vers un profil `MANAGER`.
"""

# Liste ordonnée des 15 identifiants clients configurables dans Chainlit (CLI-001 à CLI-015)
CLIENT_ID_OPTIONS: list[str] = [f"CLI-{index:03d}" for index in range(1, 16)]

# Ensemble immuable utilisé par le validateur Pydantic pour un contrôle en O(1)
VALID_CLIENT_IDS: frozenset[str] = frozenset(CLIENT_ID_OPTIONS)

# Liste ordonnée des niveaux de sévérité conformes au contrat Pydantic et à la matrice SLA
SEVERITY_OPTIONS: list[str] = ["LOW", "MEDIUM", "HIGH", "CRITICAL"]

# Mots-clés sensibles déclenchant une escalade obligatoire vers le Responsable Support (MANAGER)
CRITICAL_ESCALATION_KEYWORDS: tuple[str, ...] = (
    "faille",
    "sécurité",
    "security",
    "avoir financier",
    "indemnisation",
    "pénalité",
    "fuite de données",
)
