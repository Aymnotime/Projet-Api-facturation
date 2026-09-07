# Documentation de l'API de Facturation

## Vue d'ensemble

Plateforme SaaS B2B de facturation électronique conforme à la réglementation française/européenne.

### Fonctionnalités implémentées

✅ **Multi-tenant** : organisations isolées avec clés API  
✅ **Gestion des clients** : CRUD complet avec pagination  
✅ **Factures** : création, mise à jour, émission, suppression  
✅ **Validation EN 16931** : norme européenne de facturation  
✅ **Génération PDF** : factures au format PDF avec ReportLab  
✅ **Workers asynchrones** : Celery + Redis pour les tâches lourdes  
✅ **Pagination** : listes paginées pour clients et factures  
✅ **Sécurité** : authentification par clé API (Bearer)  

---

## Endpoints API

### Health Check
```bash
GET /health
```

### Organisations
```bash
POST /v1/organizations
{
  "name": "Acme Corp"
}
```

### Clés API
```bash
POST /v1/organizations/{org_id}/api-keys
{
  "name": "production-key"
}
```

### Clients
```bash
# Créer
POST /v1/customers
Authorization: Bearer sk_live_...
{
  "name": "Client A",
  "email": "client@example.com",
  "tax_id": "FR12345678901"
}

# Lister (paginé)
GET /v1/customers?page=1&per_page=20
```

### Factures
```bash
# Créer
POST /v1/invoices
{
  "customer_id": "uuid",
  "number": "FAC-2025-001",
  "total_minor": 12000,  # 120.00 EUR
  "currency": "EUR",
  "notes": "Prestation de services"
}

# Lister (paginé + filtre)
GET /v1/invoices?page=1&per_page=20&status=draft

# Mettre à jour (seulement draft)
PATCH /v1/invoices/{id}
{
  "notes": "Nouvelles notes"
}

# Émettre
POST /v1/invoices/{id}/issue

# Supprimer (seulement draft)
DELETE /v1/invoices/{id}
```

---

## Schéma de données

### Invoice
- `id`: UUID
- `organization_id`: UUID (FK)
- `customer_id`: UUID (FK)
- `number`: String (unique par organisation)
- `currency`: String (ISO 4217, 3 lettres)
- `total_minor`: Integer (centimes)
- `status`: Enum ['draft', 'issued', 'paid', 'cancelled', 'void']
- `notes`: Text (optionnel)
- `issued_at`: DateTime (optionnel)
- `created_at`: DateTime

---

## Validation EN 16931

Règles implémentées :
- Code devise ISO 4217 valide (3 lettres)
- Montant total positif
- Numéro de facture alphanumérique
- Statut dans la liste autorisée
- Date d'émission requise pour factures émises

---

## Architecture

```
┌─────────────┐     ┌──────────────┐     ┌─────────────┐
│   FastAPI   │────▶│  PostgreSQL  │     │   Redis     │
│   (API)     │     │   (Data)     │     │  (Broker)   │
└─────────────┘     └──────────────┘     └─────────────┘
       │                                        │
       │                                        ▼
       │                               ┌──────────────┐
       │                               │    Celery    │
       │                               │   (Worker)   │
       │                               └──────────────┘
       │                                      │
       │                                      ▼
       │                               ┌──────────────┐
       │                               │  ReportLab   │
       └──────────────────────────────▶│   (PDF)      │
                                       └──────────────┘
```

---

## Démarrage

### Backend
```bash
cd backend
pip install -r requirements.txt
uvicorn app.main:app --reload
```

### Workers (optionnel)
```bash
export REDIS_URL=redis://localhost:6379/0
celery -A app.workers.celery_app worker --loglevel=info
```

### Tests
```bash
pytest tests/ -v
```

---

## Prochaines étapes recommandées

1. **Stockage PDF** : S3/GCS pour persister les PDFs générés
2. **Webhooks** : notifications événementielles aux clients
3. **PDP** : plateforme de dématérialisation partenaire (Chorus Pro)
4. **Factur-X** : PDF/A-3 avec XML embarqué pour conformité totale
5. **Dashboard** : interface Next.js pour gestion visuelle
6. **Rate limiting** : protection contre les abus API
7. **Audit logs** : traçabilité complète des actions

---

## Conformité

- ✅ EN 16931 (validation basique)
- ✅ RGPD (données minimales, droit à l'oubli)
- ⚠️ Chorus Pro (à intégrer via PDP)
- ⚠️ Archivage légal (10 ans)
