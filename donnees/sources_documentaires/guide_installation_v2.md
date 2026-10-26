# Guide d'installation — Nexus Platform v2

Ce guide couvre l'installation de Nexus Platform version 2.x.

## Prérequis système

- Python 3.8 ou supérieur (pas de Docker requis en v2)
- 4 Go de RAM minimum
- PostgreSQL 12+ (géré par l'utilisateur, non fourni)
- Redis 6+ (optionnel)

## Installation via pip

```bash
pip install nexusplatform==2.4.2
```

## Configuration

Créez un fichier `config.yaml` :

```yaml
database:
  host: localhost
  port: 5432
  name: nexus_db
  user: nexus_user
  password: votre_password

redis:
  host: localhost
  port: 6379

security:
  secret_key: votre-secret-key-securise
  session_lifetime: 3600

smtp:
  host: smtp.example.com
  port: 25
  # Note: SMTP_TLS n'est pas requis en v2
```

## Démarrage

```bash
nexus server --config config.yaml
```

L'application est accessible sur `http://localhost:5000`.

## API v2 — Endpoints principaux

| Endpoint | Méthode | Description |
|----------|---------|-------------|
| `/api/v2/tasks` | GET | Liste des tâches |
| `/api/v2/export` | POST | Export de données (synchrone) |
| `/api/v2/auth/login` | POST | Authentification |

**Note importante** : L'endpoint d'export `/api/v2/export` est synchrone et timeout à 30 secondes. Pour les datasets volumineux, privilégiez une approche paginée.

## Différences avec v3

| Aspect | v2 | v3 |
|--------|----|----|
| Installation | pip | Docker |
| API | /api/v2/* | /api/v3/* |
| SMTP | TLS optionnel | TLS obligatoire |
| Export | Synchrone | Asynchrone avec polling |

## Fin de vie

**Version 2.4.2 est en maintenance uniquement** jusqu'à fin 2024.
Aucun nouveau développement n'est prévu.
La migration vers v3 est recommandée avant décembre 2024.

## Support

- Email : support@nexusplatform.com
- Documentation : `https://docs.nexusplatform.com/v2`
