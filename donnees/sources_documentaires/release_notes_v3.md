# Release Notes — Nexus Platform v3

## v3.1.1 (1er mars 2024)

### Corrections de bugs

| Issue | Description |
|-------|-------------|
| KI-007 | ImportError DataConnector corrigé — utilisation de `nexus.connectors` |
| KI-008 | Notifications email — SMTP_TLS correctement géré |
| KI-013 | Pagination cursor — le bug de répétition est corrigé |
| KI-014 | Custom fields — l'autosave fonctionne maintenant correctement |
| KI-015 | Backup — DB_BACKUP_PORT correctement utilisé |
| KI-016 | Webhooks — la déduplication fonctionne |

### Améliorations

- Meilleure gestion des timeouts sur les opérations longues
- Optimisation des performances du module Analytics

---

## v3.1.0 (1er février 2024)

### Breaking Changes

| Breaking Change | Description |
|-----------------|-------------|
| Import DataConnector | Le module `nexus.core` a été restructuré. Voir guide de migration |
| Configuration SMTP | `SMTP_TLS` est maintenant obligatoire |
| Port backup | Le port par défaut a changé, voir configuration |

### Nouvelles fonctionnalités

- **Nouveau système de backup** : Sauvegarde automatique avec planification
- **Amélioration webhooks** : Plus d'events disponibles, configuration simplifiée
- **Nouvelle pagination** : Pagination cursor (note: bug corrigé en 3.1.1)

### Régressions

| Regression | Description |
|------------|-------------|
| KI-015 | Le job de backup échoue si DB_BACKUP_PORT n'est pas explicite |
| KI-016 | Webhooks dupliqués sans déduplication activée |

---

## v3.0.1 (15 janvier 2024)

### Corrections

- KI-009 : Dashboard blanc — problème de cache résolu
- KI-011 : Migration v2→v3 — cleanup legacy intégré

---

## v3.0.0 (1er janvier 2024)

### Breaking Changes majeurs

| Breaking Change | Description |
|-----------------|-------------|
| Refactoring API | Toutes les endpoints passent de `/api/v2/*` à `/api/v3/*` |
| Nouveau système d'authentification | 2FA obligatoire pour les comptes Enterprise |
| Migration v2→v3 | Procédure de migration nécessaire |

### Nouvelles fonctionnalités

- **Authentification 2FA** : TOTP avec tolérance réduite (±15s)
- **Export asynchrone** : Pour les volumes importants
- **Nouveau module Analytics** : Plus performant

### Notes de migration

Pour migrer depuis la v2.4.2 :

1. Exécuter `nexus db cleanup-legacy`
2. Lancer `nexus db migrate-v2-v3`
3. Mettre à jour les imports Python (nexus.core → nexus.connectors)
4. Mettre à jour la configuration SMTP avec `SMTP_TLS=true`

**Chemin recommandé** : 2.4.2 → 3.0.1 → 3.1.1

---

## Historique v2.x

### v2.4.2 (20 septembre 2023)

- Dernière version en maintenance
- Plus de nouveaux développements
- Support jusqu'à fin 2024

### v2.4.0 (1er juin 2023)

- Breaking change : format d'export modifié
- API dépréciée : `/api/v2/export` timeout à 30s

---

## Calendrier de fin de vie

| Version | Statut | Fin de support |
|---------|--------|----------------|
| 2.3.5 | End of Life | 2023-06-01 |
| 2.4.0 | End of Life | 2023-12-01 |
| 2.4.2 | Maintenance | 2024-12-31 |
| 3.0.0 | Supported | - |
| 3.1.1 | Current | - |
