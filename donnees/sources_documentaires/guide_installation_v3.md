# Guide d'installation — Nexus Platform v3

Ce guide couvre l'installation de Nexus Platform version 3.x via Docker Compose.

## Prérequis système

- Docker 24.0 ou supérieur
- Python 3.10 ou 3.11 (Python 3.12 NON supporté dans v3)
- 8 Go de RAM minimum
- Ports disponibles : 8080 (application), 5432 (PostgreSQL), 6379 (Redis)

## Installation via Docker Compose

Créez un fichier `docker-compose.yml` dans votre répertoire de projet :

```yaml
version: '3.8'
services:
  nexus:
    image: nexusplatform/app:v3.1.1
    ports:
      - "8080:8080"
    environment:
      - DATABASE_URL=postgresql://nexus:password@postgres:5432/nexus
      - REDIS_URL=redis://redis:6379/0
      - SECRET_KEY=votre-secret-key-securise
      - SMTP_HOST=smtp.example.com
      - SMTP_PORT=587
      - SMTP_TLS=true
      - WEBHOOK_DEDUP=true
      - DB_BACKUP_PORT=5432
    depends_on:
      - postgres
      - redis
    volumes:
      - nexus_data:/app/data

  postgres:
    image: postgres:15
    environment:
      POSTGRES_DB: nexus
      POSTGRES_USER: nexus
      POSTGRES_PASSWORD: password
    volumes:
      - pg_data:/var/lib/postgresql/data

  redis:
    image: redis:7-alpine
    ports:
      - "6379:6379"

volumes:
  nexus_data:
  pg_data:
```

Lancez l'installation :

```bash
docker-compose up -d
docker-compose ps  # Vérifier que tous les services sont up
```

## Configuration des variables d'environnement

Le fichier `.env` doit contenir les variables suivantes :

| Variable | Description | Exemple |
|----------|-------------|---------|
| DATABASE_URL | Chaîne de connexion PostgreSQL | `postgresql://user:pass@host:5432/db` |
| REDIS_URL | URL du cache Redis | `redis://redis:6379/0` |
| SECRET_KEY | Clé secrète pour les sessions (générer avec `openssl rand -hex 32`) | Chaîne aléatoire |
| SMTP_HOST | Serveur SMTP pour les notifications | `smtp.example.com` |
| SMTP_PORT | Port SMTP | 587 |
| SMTP_TLS | Activer TLS pour SMTP | `true` |
| WEBHOOK_DEDUP | Activer la déduplication des webhooks | `true` |
| DB_BACKUP_PORT | Port pour les backups (attention : 5432 par défaut en v3.1.1) | `5432` |

**Important** : En version 3.1.0 uniquement, le paramètre `DB_BACKUP_PORT` doit être explicitement défini à `5432` sinon le job de backup échoue avec "connection refused". Ce bug est corrigé en 3.1.1.

## Première connexion et configuration admin

1. Après démarrage, accédez à `http://localhost:8080`
2. Le premier utilisateur créé devient administrateur
3. Connectez-vous avec les identifiants définis dans `.env`
4. Complétez la configuration dans **Settings > Organisation** :
   - Nom de l'organisation
   - Fuseau horaire
   - Langue par défaut

## Configuration initiale

### Création des premiers utilisateurs

Allez dans **Administration > Utilisateurs** pour créer les comptes utilisateurs.

### Configuration des webhooks

Dans **Settings > Intégrations > Webhooks** :

1. Créez un nouveau webhook
2. Définissez l'URL de destination
3. Sélectionnez les events à écouter (`task_completed`, `project_created`, etc.)
4. Activez la déduplication si activée dans les variables d'environnement

### Vérification post-installation

```bash
# Vérifier les logs
docker-compose logs -f nexus

# Tester l'API
curl http://localhost:8080/api/health

# Vérifier la connectivité PostgreSQL
docker-compose exec nexus python -c "from nexus.db import conn; print(conn)"
```

## Notes de migration depuis v2

Si vous migrez depuis la version 2.x :

1. **Sauvegarde** : Exportez toutes les données depuis v2
2. **Nettoyage** : Exécutez `nexus db cleanup-legacy` pour supprimer les tables obsolètes avant migration
3. **Migration** : Lancez le script de migration `nexus db migrate-v2-v3`
4. **Vérification** : Après migration, vérifiez que les webhooks fonctionnent

**Attention** : La configuration SMTP a changé en v3. Le paramètre `SMTP_TLS` est maintenant obligatoire. Si vous utilisiez une configuration v2, ajoutez `SMTP_TLS=true` dans votre `.env`.

## Résolution des problèmes courants

### Erreur "ImportError: cannot import name 'DataConnector'"

Cette erreur survient en v3.0.x si vous utilisez l'ancien import. Corrigez en utilisant :

```python
from nexus.connectors import DataConnector  # Au lieu de nexus.core
```

### Timeout sur les exports

Pour les datasets volumineux (> 10 000 lignes), utilisez l'export asynchrone :

```
POST /api/v3/export/async
```

Puis poliolez le statut avec le token retourné.

## Support et ressources

- Documentation complète : `https://docs.nexusplatform.com`
- Support : support@nexusplatform.com
- Guide API : voir `api_reference.md`
