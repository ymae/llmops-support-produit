# Référence API — Nexus Platform v3

## Authentification

### Bearer Token

Tous les endpoints nécessite un token d'accès Bearer.

```bash
curl -H "Authorization: Bearer <token>" https://api.nexusplatform.com/api/v3/...
```

### Refresh Token

```bash
POST /api/v3/auth/refresh
Content-Type: application/json

{
  "refresh_token": "eyJhbGciOiJIUzI1NiIsInR5cCI6IkpXVCJ9..."
}
```

Réponse :
```json
{
  "access_token": "nouveau_token",
  "expires_in": 900
}
```

### Token expiration

- Access token : 15 minutes
- Refresh token : 7 jours

---

## Endpoints principaux

### Tasks

```bash
GET /api/v3/tasks
```

Paramètres :
| Paramètre | Type | Description |
|-----------|------|-------------|
| page | int | Numéro de page (défaut: 1) |
| limit | int | Nombre de résultats (défaut: 20, max: 100) |
| status | string | Filtrer par status (open, resolved, closed) |
| assigned_to | string | ID utilisateur |

---

### Export

#### Export synchrone (petits volumes)

```bash
POST /api/v3/export
Content-Type: application/json

{
  "format": "csv",
  "entity": "tasks",
  "filters": {
    "created_after": "2024-01-01"
  }
}
```

**Limite** : 10 000 lignes, timeout 30 secondes.

#### Export asynchrone (grands volumes)

```bash
POST /api/v3/export/async
Content-Type: application/json

{
  "format": "csv",
  "entity": "tasks",
  "filters": {...}
}
```

Réponse :
```json
{
  "job_id": "export_abc123",
  "status": "processing"
}
```

Polling :
```bash
GET /api/v3/export/async/export_abc123
```

---

### Administration utilisateurs

```bash
POST /api/v3/admin/users
Content-Type: application/json
Authorization: Bearer <admin_token>

{
  "email": "user@example.com",
  "role": "viewer",
  "groups": ["group1"]
}
```

**Note** : Nécessite le rôle `admin`.

---

### Webhooks

#### Configuration

```bash
POST /api/v3/webhooks
Content-Type: application/json

{
  "url": "https://votre-service.com/webhook",
  "events": ["task_completed", "project_created"],
  "active": true
}
```

#### Events disponibles

| Event | Description |
|-------|-------------|
| `task_created` | Nouvelle tâche créée |
| `task_completed` | Tâche marquée comme terminée |
| `project_created` | Nouveau projet créé |
| `user_invited` | Utilisateur invité |

#### Payload exemple

```json
{
  "event": "task_completed",
  "timestamp": "2024-02-15T10:30:00Z",
  "data": {
    "task_id": "TSK-123",
    "title": "Implémenter export",
    "completed_by": "user@example.com"
  }
}
```

---

## Rate Limiting

| Plan | Limite |
|------|--------|
| Starter | 100 req/min |
| Business | 100 req/min |
| Enterprise | 1000 req/min |

Les headers de réponse :
- `X-RateLimit-Limit`: 100
- `X-RateLimit-Remaining`: 95
- `X-RateLimit-Reset`: 1707991200

En cas de dépassement : HTTP 429

---

## Pagination

### Cursor-based

```bash
GET /api/v3/tasks?cursor=eyJpZCI6MTAwfQ&limit=20
```

**Note** : Un bug affectait la pagination cursor en v3.1.0 (KI-013). Les résultats pouvaient se répéter après la page 2. Ce bug est corrigé en v3.1.1. En attendant le fix, utiliser `offset` et `limit`.

### Offset-based

```bash
GET /api/v3/tasks?offset=0&limit=20
```

---

## Codes d'erreur

| Code | Description |
|------|-------------|
| 400 | Requête invalide |
| 401 | Token expiré ou invalide |
| 403 | Accès refusé (permissions insuffisantes) |
| 404 | Ressource non trouvée |
| 429 | Rate limit dépassé |
| 500 | Erreur serveur interne |

---

## Codes d'erreur courants

### 401 — Unauthorized

```json
{
  "error": "token_expired",
  "message": "The access token has expired"
}
```

Utiliser le refresh token.

### 403 — Forbidden

```json
{
  "error": "insufficient_permissions",
  "message": "Admin role required for this operation"
}
```

### 404 — Not Found

```json
{
  "error": "entity_not_found",
  "message": "Task TSK-999 not found"
}
```

### 429 — Too Many Requests

```json
{
  "error": "rate_limit_exceeded",
  "message": "Rate limit: 100 req/min",
  "retry_after": 30
}
```

### 503 — Service Unavailable

```json
{
  "error": "maintenance_mode",
  "message": "Service en maintenance prévue à 02:00 UTC"
}
```
