# FAQ — Erreurs Fréquentes Nexus Platform

## Erreurs d'authentification

### TOTP.code refusé alors que le code est correct

**Symptôme** : Le code 2FA est systématiquement rejeté par le système.

**Cause** : Décalage horaire entre le serveur et l'appareil d'authentification. À partir de la v3.0, la tolérance est réduite à ±15 secondes.

**Solution** : Synchroniser l'horloge du serveur avec NTP :

```bash
# Linux
sudo ntpdate -u pool.ntp.org

# Vérifier la synchronisation
timedatectl status
```

Si le problème persiste, vérifier que l'heure de l'application TOTP (Google Authenticator, Authy, etc.) est correcte.

---

### SSO SAML : "invalid_audience"

**Symptôme** : L'assertion SAML est rejetée avec l'erreur `invalid_audience` lors du login SSO.

**Cause** : L'Entity ID configuré côté IdP (Okta, Azure AD) ne correspond pas à la configuration attendue par Nexus.

**Solution** : Mettre à jour la configuration SAML dans le fichier `.env` :

```
SAML_ENTITY_ID=nexus://prod
```

ou via l'interface d'admin dans **Settings > Auth > SAML**.

---

### Token expiré avec message "401 Unauthorized"

**Symptôme** : Les API calls retournent 401 après quelques minutes.

**Cause** : Le token d'accès a une durée de vie limitée (par défaut 15 minutes).

**Solution** : Utiliser le refresh token pour renouvellement :

```python
# Refresh du token
POST /api/v3/auth/refresh
{
  "refresh_token": "votre_refresh_token"
}
```

---

## Erreurs d'import/export

### Export CSV : caractères spéciaux corrompus

**Symptôme** : Les caractères accentués (é, à, ü) sont illisibles dans le fichier CSV exporté.

**Cause** : Encodage UTF-8 non appliqué lors de la génération du fichier.

**Solution** : Utiliser l'encodage UTF-8 avec BOM :

```
GET /api/v3/export?format=csv&encoding=utf-8-sig
```

**Versions affectées** : 2.3.5, 2.4.0, 2.4.2 — Corrigé en 3.0.0.

---

### Timeout sur export de grands datasets

**Symptôme** : L'export via `/api/v2/export` timeout après 30 secondes pour des datasets > 10 000 lignes.

**Cause** : Export synchrone en v2, pas adapté aux volumes importants.

**Solution** : Utiliser l'export asynchrone disponible en v3 :

```bash
# Demander l'export
POST /api/v3/export/async
{
  "format": "csv",
  "filters": {...}
}

# Récupérer le résultat (polling)
GET /api/v3/export/async/{job_id}
```

**Versions affectées** : 2.4.0, 2.4.2 — Corrigé en 3.0.0.

---

## Erreurs de démarrage

### ImportError: cannot import name 'DataConnector'

**Symptôme** : Le service ne démarre pas, erreur `ImportError: cannot import name 'DataConnector' from 'nexus.core'`.

**Cause** : Refactoring de l'API en version 3. Le module `nexus.core` a été restructuré.

**Solution** : Modifier les imports dans le code personnalisé :

```python
# Avant (v2)
from nexus.core import DataConnector

# Après (v3)
from nexus.connectors import DataConnector
```

**Versions affectées** : 3.0.0, 3.1.0 — Corrigé en 3.1.1.

---

### Ports occupés

**Symptôme** : `Error: port 8080 is already in use`.

**Cause** : Un autre service utilise le port ou une instance précédente ne s'est pas arrêtée proprement.

**Solution** :

```bash
# Identifier le processus
lsof -i :8080

# Arrêter le processus
kill <PID>

# Ou modifier le port dans docker-compose.yml
ports:
  - "8081:8080"
```

---

## Erreurs de migration

### AlembicError: relation 'projects_v2' does not exist

**Symptôme** : La migration v2→v3 échoue à l'étape 3/7 avec l'erreur `relation 'projects_v2' does not exist`.

**Cause** : Des tables obsolètes de la v2 interferent avec le processus de migration.

**Solution** : Exécuter le nettoyage des tables legacy avant migration :

```bash
nexus db cleanup-legacy
nexus db migrate-v2-v3
```

**Versions affectées** : 3.0.0 — Corrigé en 3.0.1.

---

### Séquence de migration incorrecte

**Symptôme** : La migration bloque ou produit des données incohérentes.

**Cause** : Tentative de migration sans avoir fait les prérequis.

**Solution** : Respecter la séquence suivante :

1. **Sauvegarde** :Exporter les données v2
2. **Nettoyage legacy** : `nexus db cleanup-legacy`
3. **Vérification pré-migration** : `nexus db preflight-check`
4. **Migration** : `nexus db migrate-v2-v3`
5. **Vérification post-migration** : `nexus db verify`

---

## Problèmes de performance

### Requêtes lentes sur le module Reporting

**Symptôme** : Les requêtes sur Reporting prennent 8-15 secondes au lieu de <2 secondes.

**Cause** : Index manquants sur les tables de reporting, ou cache Redis non activé.

**Solution** :

1. Vérifier que Redis est bien configuré etconnected
2. Ajouter des index sur les colonnes fréquemment requêtées :

```sql
CREATE INDEX idx_reporting_date ON reporting_events(created_at);
CREATE INDEX idx_reporting_user ON reporting_events(user_id);
```

3. Activer le cache Redis dans `config.yaml` :

```yaml
cache:
  enabled: true
  ttl: 3600
```

---

### Mémoire insuffisante sur le module Analytics

**Symptôme** : `MemoryError` sur datasets > 50 000 lignes.

**Cause** : Limite mémoire par défaut trop basse pour les opérations analytiques lourdes.

**Solution** : Augmenter la mémoire allouée dans Docker :

```yaml
services:
  nexus:
    deploy:
      resources:
        limits:
          memory: 4G
```

Ou en ligne de commande :

```bash
docker run -m 4g nexusplatform/app:v3.1.1
```
