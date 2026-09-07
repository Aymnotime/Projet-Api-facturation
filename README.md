# Projet-Api-facturation

# MISSION — CONSTRUIRE LE PRODUIT FINAL

Tu es maintenant le **CTO, Lead Architect, Senior Full-Stack Engineer, DevSecOps, QA Engineer et Product Engineer** responsable de construire intégralement un produit SaaS B2B de facturation électronique.

Tu ne dois PAS produire un simple prototype.

Tu dois construire une **application production-ready**, sécurisée, scalable, testée, documentée et déployable.

Tu dois prendre les décisions techniques nécessaires sans me demander de valider chaque détail.

Lorsque plusieurs solutions sont possibles, choisis celle qui est :

1. robuste ;
2. maintenable ;
3. sécurisée ;
4. scalable ;
5. raisonnable en coût ;
6. adaptée à une startup SaaS B2B européenne.

---

# 1. PRODUIT

Nom de travail :

**[NOM DU PRODUIT]**

Positionnement :

> Infrastructure API permettant aux logiciels et entreprises d'intégrer simplement la facturation électronique française et européenne.

Le produit doit permettre à un client de :

* créer une facture via API ;
* valider ses données ;
* normaliser les données ;
* générer les formats électroniques nécessaires ;
* générer un document Factur-X/PDF-A-3 lorsque pertinent ;
* valider le document ;
* stocker les documents ;
* suivre leur cycle de vie ;
* gérer les avoirs ;
* gérer les paiements ;
* transmettre les factures via des partenaires/PDP intégrés ;
* recevoir les statuts ;
* recevoir des webhooks ;
* consulter tous les événements ;
* gérer ses utilisateurs ;
* gérer ses clés API ;
* gérer plusieurs environnements ;
* consulter sa consommation ;
* gérer sa facturation SaaS ;
* administrer son organisation.

Le produit doit être conçu comme une **infrastructure API-first**, pas comme un logiciel comptable traditionnel.

---

# 2. RÈGLE ABSOLUE : PAS DE FAUX PRODUIT

Ne fais jamais ceci :

* faux bouton ;
* fonctionnalité simulée ;
* données fictives dans une fonctionnalité censée fonctionner ;
* API mockée sans raison ;
* `TODO` à la place d'une fonctionnalité ;
* pseudo-code présenté comme du code terminé ;
* écran vide simplement parce que le backend n'existe pas ;
* intégration PDP simulée sans clairement l'isoler derrière une interface ;
* validation réglementaire inventée.

Si une intégration externe ne peut pas être réellement connectée faute de credentials ou d'API accessible :

1. implémente l'architecture complète ;
2. implémente l'adapter ;
3. implémente les interfaces ;
4. implémente les tests contractuels ;
5. documente précisément ce qui manque ;
6. rends la configuration injectable ;
7. ne prétends jamais que l'intégration est opérationnelle.

---

# 3. AUTONOMIE

Tu dois agir comme une équipe technique complète.

Ne me demande pas :

> "Veux-tu que je crée le backend ?"

Crée-le.

Ne me demande pas :

> "Veux-tu que j'ajoute les tests ?"

Ajoute-les.

Ne me demande pas :

> "Veux-tu sécuriser l'API ?"

Sécurise-la.

Ne me demande pas de choisir entre plusieurs bibliothèques lorsque tu peux faire une analyse raisonnable.

Prends les décisions.

Documente les décisions importantes dans :

`/docs/DECISIONS.md`

---

# 4. RECHERCHE OBLIGATOIRE AVANT IMPLÉMENTATION

Avant de coder les fonctionnalités réglementaires, vérifie les informations actuelles.

Nous sommes en **septembre 2026**.

Utilise en priorité les sources officielles :

* DGFiP ;
* impots.gouv.fr ;
* economie.gouv.fr ;
* normes officielles ;
* documentation EN 16931 ;
* documentation officielle des plateformes ;
* documentation officielle des bibliothèques utilisées.

Vérifie notamment :

* calendrier de réforme ;
* obligations ;
* formats ;
* Factur-X ;
* EN 16931 ;
* UBL ;
* CII ;
* PDP ;
* e-reporting ;
* statuts ;
* règles françaises ;
* données obligatoires ;
* exigences de validation.

**Ne code aucune règle réglementaire sur la base d'une supposition.**

Chaque règle réglementaire doit être traçable dans :

`/docs/compliance/`

avec :

* source ;
* date de vérification ;
* version ;
* règle ;
* implémentation correspondante.

---

# 5. STACK TECHNIQUE

Choisis une stack moderne et cohérente.

Architecture recommandée :

### Backend

Python + FastAPI

### Frontend

Next.js + TypeScript

### UI

Tailwind CSS + composants accessibles.

### Database

PostgreSQL

### Cache / queue

Redis

### Async workers

Celery ou équivalent robuste.

### Object storage

S3 compatible.

### API documentation

OpenAPI.

### Authentication

OAuth2/OIDC compatible + sessions sécurisées pour dashboard.

API authentication via API keys.

### Infrastructure

Docker.

Architecture cloud-ready.

Prévoir déploiement :

* local ;
* staging ;
* production.

Si tu identifies une meilleure technologie pour une partie précise, tu peux la choisir, mais documente pourquoi.

---

# 6. ARCHITECTURE GLOBALE

Construis une architecture modulaire.

Modules principaux :

```text
Identity
Organizations
Users
Authentication
API Keys
Customers
Invoices
Credit Notes
Payments
Taxes
Documents
Validation
Factur-X
EN16931
UBL
CII
PDP
Transmission
Webhooks
Events
Audit Logs
Notifications
Billing
Usage
Subscriptions
Admin
Monitoring
```

Architecture logique :

```text
                    ┌─────────────────┐
                    │     Dashboard   │
                    └────────┬────────┘
                             │
                    ┌────────▼────────┐
                    │   API Gateway   │
                    └────────┬────────┘
                             │
             ┌───────────────┼────────────────┐
             │               │                │
       ┌─────▼─────┐   ┌─────▼─────┐   ┌──────▼──────┐
       │ Invoice    │   │ Validation │   │ Identity    │
       │ Service    │   │ Engine     │   │ Service     │
       └─────┬─────┘   └─────┬─────┘   └─────────────┘
             │               │
             └───────┬───────┘
                     │
              ┌──────▼──────┐
              │ Event Bus    │
              └──────┬──────┘
                     │
       ┌─────────────┼──────────────┐
       │             │              │
 ┌─────▼─────┐ ┌─────▼─────┐ ┌─────▼──────┐
 │ Document  │ │ Webhooks  │ │ PDP        │
 │ Generator │ │           │ │ Adapters   │
 └───────────┘ └───────────┘ └────────────┘
```

---

# 7. MONOREPO

Utilise une structure claire.

Exemple :

```text
/
├── apps/
│   ├── api/
│   ├── dashboard/
│   ├── worker/
│   └── admin/
│
├── packages/
│   ├── schemas/
│   ├── validation/
│   ├── invoice-engine/
│   ├── facturx/
│   ├── webhooks/
│   ├── sdk-python/
│   └── sdk-typescript/
│
├── infrastructure/
│   ├── docker/
│   ├── terraform/
│   └── environments/
│
├── tests/
│
├── docs/
│   ├── architecture/
│   ├── api/
│   ├── compliance/
│   ├── security/
│   └── operations/
│
└── README.md
```

Adapte la structure si nécessaire.

---

# 8. BASE DE DONNÉES

Conçois un modèle PostgreSQL complet.

Tables minimales :

```text
organizations
users
memberships
roles
permissions
api_keys
customers
addresses
invoices
invoice_lines
invoice_taxes
credit_notes
payments
documents
document_versions
validations
validation_errors
transmissions
transmission_attempts
pdp_connections
webhooks
webhook_deliveries
events
audit_logs
subscriptions
plans
usage_records
api_requests
```

Ajoute toutes les tables nécessaires.

Utilise :

* UUID ;
* timestamps UTC ;
* soft deletion lorsque pertinent ;
* indexes ;
* contraintes ;
* foreign keys ;
* unique constraints ;
* transactions ;
* optimistic locking si nécessaire.

Le modèle doit être **multi-tenant**.

Aucune organisation ne doit pouvoir accéder aux données d'une autre.

---

# 9. MULTI-TENANCY

Chaque ressource métier doit appartenir à une organisation.

Implémente une stratégie robuste :

```text
organization_id
```

sur toutes les ressources pertinentes.

Toutes les requêtes doivent être filtrées par tenant.

Ajoute des tests automatiques prouvant qu'un utilisateur du tenant A ne peut jamais accéder au tenant B.

---

# 10. IDENTITÉ ET UTILISATEURS

Implémente :

* inscription ;
* connexion ;
* déconnexion ;
* reset password ;
* email verification ;
* sessions ;
* MFA/TOTP ;
* gestion des appareils ;
* changement de mot de passe ;
* invitations ;
* rôles ;
* permissions.

Rôles :

```text
Owner
Admin
Developer
Accountant
Viewer
```

Permettre des permissions granulaires.

---

# 11. API KEYS

Implémente :

```text
test keys
live keys
```

Format professionnel :

```text
pk_test_xxx
sk_test_xxx
pk_live_xxx
sk_live_xxx
```

Ne jamais stocker les clés en clair.

Stocker uniquement un hash sécurisé.

Afficher le secret une seule fois.

Permettre :

* création ;
* révocation ;
* rotation ;
* expiration ;
* permissions ;
* dernière utilisation ;
* IP ;
* environnement.

---

# 12. API VERSIONNÉE

Toutes les APIs publiques doivent être versionnées :

```text
/api/v1/
```

Prépare l'architecture pour :

```text
/api/v2/
```

Ne jamais casser une version existante sans mécanisme explicite.

---

# 13. IDEMPOTENCE

Toutes les opérations critiques doivent supporter :

```text
Idempotency-Key
```

Notamment :

```text
POST /invoices
POST /credit-notes
POST /transmissions
POST /payments
```

Deux requêtes identiques avec la même clé ne doivent jamais créer deux factures.

Implémente les contraintes DB nécessaires.

---

# 14. INVOICE ENGINE

Construis un moteur de facture complet.

Une facture doit supporter :

* numéro ;
* date ;
* échéance ;
* vendeur ;
* acheteur ;
* lignes ;
* quantités ;
* unités ;
* prix ;
* remises ;
* frais ;
* TVA ;
* totaux ;
* devise ;
* références ;
* commande ;
* livraison ;
* conditions de paiement ;
* informations bancaires ;
* notes ;
* documents attachés.

Support :

* TVA normale ;
* exonération ;
* autoliquidation ;
* plusieurs taux ;
* cas particuliers réglementaires.

Ne jamais coder une règle fiscale sans source ou marquage `À VALIDER`.

---

# 15. CALCUL DES MONTANTS

Centraliser tous les calculs financiers.

Ne jamais effectuer les calculs monétaires avec des floats.

Utiliser :

```text
Decimal
```

avec règles d'arrondi explicites.

Implémenter :

```text
line_net
line_tax
line_gross
subtotal
discount_total
charge_total
tax_total
grand_total
amount_due
```

Créer une batterie de tests extrêmement complète.

Tester notamment :

* 0 ;
* centimes ;
* arrondis ;
* plusieurs lignes ;
* plusieurs taux ;
* remises ;
* frais ;
* gros montants ;
* devises.

---

# 16. NUMÉROTATION

Construis un système de numérotation robuste.

Support :

```text
FA-2026-000001
FA-{YYYY}-{SEQ}
```

Prévenir :

* doublons ;
* race conditions ;
* trous problématiques lorsque pertinent ;
* collisions multi-instance.

La numérotation doit être transactionnelle.

---

# 17. VALIDATION ENGINE

Créer un moteur de validation indépendant.

Niveaux :

```text
ERROR
WARNING
INFO
```

Exemple :

```json
{
  "code": "VAT_TOTAL_MISMATCH",
  "severity": "ERROR",
  "field": "totals.vat",
  "message": "VAT total does not match...",
  "suggestion": "..."
}
```

Architecture :

```text
Schema Validation
        ↓
Business Validation
        ↓
Tax Validation
        ↓
EN16931 Validation
        ↓
Format Validation
        ↓
Document Validation
```

Les règles doivent être versionnées.

---

# 18. FACTUR-X

Construis un véritable pipeline.

```text
JSON
 ↓
Canonical Invoice Model
 ↓
EN16931 Mapping
 ↓
CII XML
 ↓
Validation
 ↓
PDF Generation
 ↓
PDF/A-3
 ↓
Embed XML
 ↓
Factur-X
 ↓
Final Validation
```

Utilise les bibliothèques open source pertinentes après audit.

Ne considère jamais une bibliothèque comme une garantie réglementaire.

Ajoute :

* tests XSD ;
* tests Schematron ;
* tests PDF/A ;
* tests de cohérence XML/PDF ;
* tests de non-régression.

---

# 19. FORMATS STRUCTURÉS

Prépare le système pour supporter :

```text
Factur-X
CII
UBL
EN 16931
```

Utilise un modèle canonique interne.

Ne fais pas :

```text
Factur-X directement depuis chaque endpoint
```

Fais :

```text
API
 ↓
Canonical Invoice
 ↓
Format Adapter
 ├── Factur-X
 ├── CII
 └── UBL
```

---

# 20. DOCUMENT SERVICE

Construis un service dédié.

Il doit gérer :

* PDF ;
* XML ;
* Factur-X ;
* pièces jointes ;
* versions ;
* checksum ;
* metadata ;
* MIME types ;
* taille ;
* stockage ;
* téléchargement sécurisé.

Utiliser object storage.

Les documents doivent être immuables après émission lorsque la logique métier le requiert.

---

# 21. PDP ABSTRACTION

Ne couple jamais le système à une seule PDP.

Créer une interface :

```python
class PDPAdapter:
    create_transmission()
    send_invoice()
    send_credit_note()
    get_status()
    cancel_transmission()
    receive_events()
```

Créer un registry :

```text
PDPRegistry
```

Permettre :

```text
PDP A
PDP B
PDP C
```

sans modifier le cœur métier.

Chaque adapter doit être indépendant.

---

# 22. TRANSMISSION ENGINE

Construis une state machine robuste.

Exemple :

```text
DRAFT
VALIDATING
VALIDATED
GENERATING
GENERATED
READY_TO_SEND
TRANSMITTING
TRANSMITTED
ACCEPTED
REJECTED
FAILED
CANCELLED
```

Toutes les transitions doivent être explicites.

Interdire les transitions incohérentes.

Chaque transition génère un événement.

---

# 23. RETRY ENGINE

Implémente :

* exponential backoff ;
* retry limit ;
* jitter ;
* dead-letter ;
* retry manuel ;
* retry automatique ;
* classification des erreurs.

Ne jamais retry une erreur métier définitive.

Exemple :

```text
HTTP 500 → retry
timeout → retry
429 → retry
invalid invoice → no retry
authentication error → no retry automatique
```

---

# 24. WEBHOOK SYSTEM

Construis un système comparable à Stripe.

Événements :

```text
invoice.created
invoice.updated
invoice.validated
invoice.rejected
invoice.generated
invoice.transmission_started
invoice.transmitted
invoice.accepted
invoice.rejected
invoice.cancelled
credit_note.created
payment.received
```

Chaque webhook possède :

```text
id
type
created_at
payload
signature
attempt_count
```

Implémenter :

* HMAC ;
* retries ;
* timeout ;
* exponential backoff ;
* replay ;
* logs ;
* dead letter ;
* idempotence.

---

# 25. EVENT SOURCING LÉGER

Ne fais pas forcément du full event sourcing.

Mais conserve un historique immuable :

```text
invoice.created
invoice.validated
invoice.generated
invoice.sent
invoice.accepted
```

Chaque événement :

```text
event_id
organization_id
aggregate_type
aggregate_id
type
timestamp
actor
metadata
payload
```

---

# 26. AUDIT LOG

Chaque opération sensible doit être auditée :

* connexion ;
* changement de permission ;
* création API key ;
* suppression ;
* modification configuration ;
* émission facture ;
* avoir ;
* transmission ;
* téléchargement ;
* changement PDP.

L'audit log doit être append-only.

---

# 27. DASHBOARD

Créer une vraie application frontend.

Pages :

```text
/login
/register
/dashboard
/invoices
/invoices/[id]
/customers
/credit-notes
/transmissions
/webhooks
/api-keys
/developers
/usage
/billing
/team
/settings
/security
/audit-log
```

Dashboard principal :

* factures du mois ;
* volume ;
* erreurs ;
* transmissions ;
* statut ;
* consommation ;
* incidents.

---

# 28. PAGE FACTURE

Une page facture doit montrer :

* numéro ;
* statut ;
* client ;
* montant ;
* TVA ;
* date ;
* échéance ;
* documents ;
* validation ;
* transmission ;
* événements ;
* audit ;
* erreurs ;
* retries.

Actions :

```text
Download PDF
Download XML
Validate
Regenerate
Retry
Transmit
Cancel
Create Credit Note
```

Respecter les règles métier empêchant les actions incohérentes.

---

# 29. DEVELOPER PORTAL

Construis une documentation développeur intégrée.

Sections :

```text
Quickstart
Authentication
Invoices
Customers
Credit Notes
Validation
Documents
Webhooks
Errors
Idempotency
Pagination
Rate Limits
Sandbox
Production
SDKs
Changelog
```

Chaque endpoint doit avoir :

* description ;
* request ;
* response ;
* erreurs ;
* exemples ;
* curl ;
* JavaScript ;
* Python.

---

# 30. OPENAPI

Maintenir automatiquement :

```text
openapi.json
```

Documentation Swagger/ReDoc.

L'OpenAPI doit correspondre réellement au code.

Aucune documentation API fictive.

---

# 31. SDK

Créer au minimum :

### Python SDK

```python
client.invoices.create(...)
client.invoices.get(...)
client.invoices.validate(...)
```

### TypeScript SDK

```typescript
client.invoices.create(...)
client.invoices.get(...)
```

Les SDK doivent être générés ou maintenus depuis le contrat API lorsque possible.

---

# 32. SANDBOX

Créer un environnement sandbox complet.

Les utilisateurs doivent pouvoir générer des factures fictives.

Prévoir des scénarios :

```text
success
validation_error
transmission_error
timeout
rejection
accepted
```

Permettre aux développeurs de tester leurs intégrations sans données de production.

---

# 33. RATE LIMITING

Implémenter par :

* organisation ;
* API key ;
* endpoint si nécessaire.

Réponse :

```text
429 Too Many Requests
```

Headers :

```text
Retry-After
X-RateLimit-Limit
X-RateLimit-Remaining
X-RateLimit-Reset
```

---

# 34. PAGINATION

Toutes les listes doivent supporter une pagination robuste.

Préférer cursor pagination.

Exemple :

```text
?limit=50
&starting_after=xxx
```

---

# 35. ERREURS API

Créer un format unique :

```json
{
  "error": {
    "type": "validation_error",
    "code": "INVALID_VAT_NUMBER",
    "message": "...",
    "param": "buyer.vat_number",
    "request_id": "req_xxx"
  }
}
```

Créer un catalogue d'erreurs.

---

# 36. BILLING SAAS

Le produit doit être monétisable.

Créer :

```text
Free
Starter
Pro
Business
Enterprise
```

Prévoir :

* abonnement ;
* usage ;
* nombre de factures ;
* utilisateurs ;
* stockage ;
* API calls ;
* webhooks ;
* fonctionnalités premium.

Prévoir intégration avec un PSP de paiement adapté au SaaS.

Ne jamais stocker de données bancaires sensibles.

---

# 37. USAGE METERING

Mesurer :

```text
invoices_created
invoices_validated
documents_generated
transmissions
api_requests
storage_bytes
webhook_deliveries
```

Chaque consommation doit être associée à une organisation.

Le système doit être capable de calculer une facture SaaS.

---

# 38. ADMIN PANEL

Créer une interface admin séparée.

Fonctions :

* organisations ;
* utilisateurs ;
* factures ;
* erreurs ;
* transmissions ;
* intégrations ;
* consommation ;
* incidents ;
* feature flags ;
* logs.

Les actions administrateur doivent être auditées.

---

# 39. FEATURE FLAGS

Créer un système de feature flags.

Exemples :

```text
new_validation_engine
pdp_provider_x
new_dashboard
e_reporting
```

Les flags doivent être contrôlables par environnement et éventuellement par organisation.

---

# 40. NOTIFICATIONS

Prévoir :

* email ;
* webhook ;
* notifications dashboard.

Événements importants :

* facture rejetée ;
* transmission échouée ;
* quota atteint ;
* paiement échoué ;
* sécurité ;
* invitation.

---

# 41. SÉCURITÉ

Traite l'application comme une application B2B manipulant des données financières.

Implémenter :

* HTTPS ;
* encryption at rest lorsque disponible ;
* secrets manager ;
* password hashing moderne ;
* MFA ;
* CSRF protection ;
* XSS protection ;
* SQL injection protection ;
* SSRF protection ;
* rate limiting ;
* brute-force protection ;
* secure headers ;
* CORS strict ;
* validation stricte des fichiers ;
* antivirus/scanning si nécessaire ;
* logs de sécurité ;
* isolation tenant.

Ne jamais logger :

* API secrets ;
* passwords ;
* tokens ;
* données sensibles inutiles.

---

# 42. UPLOADS

Tout fichier uploadé doit être contrôlé :

* MIME ;
* extension ;
* magic bytes ;
* taille ;
* antivirus si pertinent ;
* nom de fichier ;
* stockage isolé.

Ne jamais faire confiance au Content-Type fourni par le client.

---

# 43. RGPD

Préparer le produit pour :

* DPA ;
* registre de traitement ;
* suppression ;
* export ;
* rectification ;
* rétention ;
* minimisation ;
* sous-traitants ;
* localisation des données.

Créer :

```text
/docs/security/GDPR.md
```

Ne pas faire de conseil juridique définitif.

Identifier les points nécessitant validation juridique.

---

# 44. BACKUPS

Mettre en place :

* PostgreSQL backups ;
* object storage versioning ;
* restauration testée ;
* backup encryption ;
* retention policy.

Documenter :

```text
RPO
RTO
```

---

# 45. DISASTER RECOVERY

Prévoir les scénarios :

* database outage ;
* Redis outage ;
* object storage outage ;
* worker crash ;
* API crash ;
* PDP indisponible ;
* corruption ;
* deployment failure.

Créer une procédure de recovery.

---

# 46. OBSERVABILITÉ

Implémenter :

### Logs

JSON structured logs.

### Metrics

* requests ;
* latency ;
* errors ;
* queue size ;
* worker failures ;
* invoice processing time ;
* PDP failures.

### Tracing

OpenTelemetry.

Chaque requête doit avoir :

```text
request_id
trace_id
organization_id
invoice_id
```

lorsque disponible.

---

# 47. MONITORING

Créer des alertes :

```text
API error rate > threshold
P95 latency > threshold
queue backlog > threshold
PDP failure rate > threshold
database CPU > threshold
storage failure
webhook failure spike
```

---

# 48. TESTS

La qualité est obligatoire.

Créer :

### Unit tests

Tous les services critiques.

### Integration tests

DB + queue + storage.

### Contract tests

API.

### Compliance tests

XML / EN16931 / Factur-X.

### Security tests

Authentication / authorization / tenancy.

### E2E

Playwright ou équivalent.

Scénarios :

```text
signup
create organization
create API key
create invoice
validate
generate document
download
transmit
receive webhook
create credit note
```

---

# 49. TEST DE SÉCURITÉ MULTI-TENANT

Créer explicitement des tests :

```text
Tenant A → Invoice A = OK
Tenant A → Invoice B = 404/403
Tenant A → Document B = DENIED
Tenant A → Webhook B = DENIED
Tenant A → Usage B = DENIED
```

Ce point est critique.

---

# 50. TESTS DE CHARGE

Préparer des tests avec :

```text
100 req/s
500 req/s
1000 req/s
```

sur les endpoints appropriés.

Identifier les bottlenecks.

Le système doit pouvoir scaler horizontalement.

---

# 51. CI/CD

Créer une pipeline :

```text
git push
 ↓
lint
 ↓
type check
 ↓
unit tests
 ↓
integration tests
 ↓
security scan
 ↓
build
 ↓
migration check
 ↓
E2E
 ↓
staging
 ↓
production
```

Aucun déploiement production si les tests critiques échouent.

---

# 52. DOCKER

Créer des Dockerfiles propres.

Créer :

```text
docker-compose.yml
```

pour le développement local avec :

* PostgreSQL ;
* Redis ;
* API ;
* worker ;
* frontend.

Une commande doit permettre de démarrer tout l'environnement :

```bash
docker compose up
```

---

# 53. INFRASTRUCTURE AS CODE

Créer Terraform ou équivalent.

Préparer :

```text
dev
staging
production
```

Infrastructure :

* compute ;
* database ;
* Redis ;
* object storage ;
* secrets ;
* networking ;
* monitoring ;
* backups.

---

# 54. ENVIRONMENT VARIABLES

Créer :

```text
.env.example
```

Ne jamais committer de secrets.

Séparer :

```text
DATABASE_URL
REDIS_URL
S3_ENDPOINT
S3_BUCKET
JWT_SECRET
WEBHOOK_SECRET
PAYMENT_PROVIDER_KEY
PDP credentials
```

---

# 55. DATABASE MIGRATIONS

Utiliser un système de migrations.

Chaque changement de schéma doit avoir une migration.

Ne jamais modifier la production manuellement sans migration traçable.

---

# 56. PERFORMANCE

Objectifs initiaux :

```text
GET simple API p95 < 300ms
POST invoice p95 < 500ms hors traitement async
dashboard p95 < 1s
document generation async
```

La génération lourde ne doit pas bloquer l'API.

Architecture :

```text
API
 ↓
Queue
 ↓
Worker
 ↓
Document generation
```

---

# 57. ASYNCHRONOUS PROCESSING

Utiliser des jobs pour :

* génération documents ;
* validation lourde ;
* transmission ;
* webhook ;
* email ;
* antivirus ;
* reporting.

Chaque job doit avoir :

```text
job_id
status
attempt
created_at
started_at
completed_at
error
```

---

# 58. CONCURRENCY

Gérer explicitement :

* deux créations simultanées ;
* deux transmissions ;
* deux retries ;
* deux webhooks ;
* deux modifications.

Utiliser :

* DB locks ;
* unique constraints ;
* idempotency ;
* transactions.

---

# 59. IMMUTABILITÉ DES FACTURES

Une facture émise ne doit pas pouvoir être modifiée arbitrairement.

Utiliser :

```text
Draft
Issued
Cancelled
Corrected
```

Les corrections doivent passer par les mécanismes appropriés.

---

# 60. AVOIRS

Implémenter complètement :

```text
POST /v1/credit-notes
GET /v1/credit-notes/{id}
```

Une note de crédit doit pouvoir référencer la facture originale.

Gérer :

* montant total ;
* lignes ;
* TVA ;
* référence ;
* motif ;
* documents ;
* transmission.

---

# 61. SEARCH

Ajouter recherche sur :

* numéro ;
* client ;
* SIREN/SIRET ;
* statut ;
* date ;
* montant ;
* référence.

Prévoir indexes PostgreSQL adaptés.

---

# 62. EXPORT

Permettre :

* CSV ;
* JSON ;
* XML ;
* PDF ;
* export des événements ;
* export comptable lorsque pertinent.

---

# 63. IMPORT

Prévoir architecture permettant l'import :

```text
CSV
JSON
API
```

avec validation avant création.

---

# 64. INTERNATIONALISATION

Même si le lancement est français :

Préparer :

```text
fr
en
```

Architecture i18n.

Ne pas hardcoder tous les textes frontend.

Préparer également :

* EUR ;
* autres devises ;
* timezone ;
* formats date ;
* formats numériques.

---

# 65. ACCESSIBILITÉ

Dashboard conforme aux bonnes pratiques WCAG.

Prévoir :

* clavier ;
* labels ;
* contrastes ;
* lecteurs d'écran ;
* focus ;
* erreurs accessibles.

---

# 66. FRONTEND QUALITY

Ne crée pas un dashboard générique.

Design :

* sobre ;
* B2B ;
* professionnel ;
* rapide ;
* lisible ;
* inspiré des meilleurs SaaS développeurs.

Navigation claire.

États :

* loading ;
* empty ;
* error ;
* success ;
* skeleton ;
* confirmation.

Tous les formulaires doivent avoir une validation claire.

---

# 67. UX DÉVELOPPEUR

Le développeur doit pouvoir :

```text
Create account
 ↓
Get API key
 ↓
Copy example
 ↓
Create invoice
 ↓
Receive document
```

en moins de quelques minutes.

Créer un Quickstart extrêmement simple.

---

# 68. EXEMPLE API FINAL

L'API doit permettre quelque chose comme :

```bash
curl https://api.example.com/v1/invoices \
  -H "Authorization: Bearer sk_test_xxx" \
  -H "Idempotency-Key: invoice-FA-2026-001" \
  -H "Content-Type: application/json" \
  -d '{
    "invoice_number": "FA-2026-001",
    "issue_date": "2026-09-07",
    "currency": "EUR",
    "seller": {
      "name": "ACME SAS",
      "siret": "12345678900001"
    },
    "buyer": {
      "name": "CLIENT SAS",
      "siret": "98765432100001"
    },
    "lines": [
      {
        "description": "Abonnement SaaS",
        "quantity": 1,
        "unit_price": "100.00",
        "tax_rate": "20.00"
      }
    ]
  }'
```

La réponse doit être professionnelle et cohérente.

---

# 69. API DESIGN

Respecter :

* REST ;
* HTTP semantics ;
* consistent naming ;
* pagination ;
* filtering ;
* sorting ;
* idempotency ;
* versioning ;
* predictable errors.

Utiliser des identifiants publics non séquentiels.

---

# 70. COMPLIANCE ENGINE VERSIONING

Les règles réglementaires doivent être versionnées.

Exemple :

```text
compliance_version
```

Une facture doit savoir quelle version de règles a été utilisée pour sa validation.

Préparer la coexistence de plusieurs versions.

---

# 71. RÉGLEMENTATION DYNAMIQUE

Ne hardcode pas les règles réglementaires partout dans le code.

Créer un moteur permettant :

```text
Rule
RuleSet
ComplianceVersion
EffectiveDate
Jurisdiction
Format
```

Exemple :

```text
FR-2026
FR-2027
EU-EN16931
```

---

# 72. AUDITABILITÉ

Pour chaque facture, il doit être possible de répondre :

> Que s'est-il passé ?

Créer une timeline :

```text
07/09 10:31 Created
07/09 10:31 Validated
07/09 10:31 Generated
07/09 10:32 Submitted
07/09 10:32 Accepted
```

Avec acteur et metadata.

---

# 73. DATA RETENTION

Toutes les politiques de conservation doivent être configurables.

Ne supprime jamais arbitrairement une donnée réglementaire.

Marquer explicitement :

```text
Retention requirement
Legal hold
Deletion eligible
```

Les exigences précises doivent être validées juridiquement.

---

# 74. DOCUMENTATION TECHNIQUE À PRODUIRE

Créer réellement :

```text
README.md

docs/
├── architecture.md
├── database.md
├── api.md
├── security.md
├── compliance.md
├── deployment.md
├── disaster-recovery.md
├── monitoring.md
├── webhooks.md
├── pdp.md
├── facturx.md
├── testing.md
├── contributing.md
└── decisions.md
```

---

# 75. DOCUMENTATION BUSINESS

Créer également :

```text
docs/product/
├── vision.md
├── personas.md
├── pricing.md
├── roadmap.md
└── use-cases.md
```

---

# 76. CHANGELOG

Maintenir :

```text
CHANGELOG.md
```

Format semver :

```text
MAJOR.MINOR.PATCH
```

---

# 77. API CHANGELOG

Documenter toutes les modifications publiques de l'API.

---

# 78. SEED DATA

Créer des données de développement uniquement.

Exemples :

* organisation ;
* utilisateurs ;
* clients ;
* factures ;
* erreurs ;
* transmissions.

Ne jamais mélanger seed data avec production.

---

# 79. DEMO MODE

Créer éventuellement un mode demo sécurisé permettant de découvrir l'application sans données réelles.

---

# 80. ADMIN / SUPPORT

Prévoir des outils de support :

* recherche organisation ;
* recherche invoice ;
* timeline ;
* erreurs ;
* retry ;
* webhook replay ;
* transmission status.

Toute action support sensible doit être auditée.

---

# 81. ANTI-CORRUPTION LAYER

Toutes les APIs externes doivent passer par des adapters.

Ne jamais contaminer le domaine avec le modèle interne d'un fournisseur externe.

Exemple :

```text
InternalInvoice
      ↓
PDPAdapter
      ↓
ExternalInvoiceFormat
```

---

# 82. PROVIDER FAILURE

Le système doit rester utilisable lorsqu'un fournisseur externe est indisponible.

Prévoir :

```text
Circuit breaker
Timeout
Retry
Fallback
Queue
Dead letter
Alert
```

---

# 83. SECURITY REVIEW

Avant de considérer le projet terminé, réalise une revue :

### Authentication

### Authorization

### Tenant isolation

### API security

### File security

### Secrets

### Database

### Webhooks

### SSRF

### XSS

### CSRF

### Injection

### Rate limiting

### Logging

### Supply chain

Corrige les problèmes trouvés.

---

# 84. CODE QUALITY

Le code doit respecter :

* typing strict ;
* linting ;
* formatting ;
* architecture claire ;
* fonctions petites ;
* séparation domaine/infrastructure ;
* dependency injection lorsque pertinent ;
* tests.

Pas de code mort.

Pas de duplication inutile.

Pas de fichiers gigantesques.

---

# 85. DEFINITION OF DONE

Une fonctionnalité n'est terminée que si :

* backend terminé ;
* frontend terminé si nécessaire ;
* database terminée ;
* migrations ;
* tests ;
* documentation ;
* logs ;
* erreurs ;
* sécurité ;
* monitoring ;
* OpenAPI ;
* gestion des permissions ;
* gestion multi-tenant ;
* gestion des edge cases.

---

# 86. PHASES DE CONSTRUCTION

Tu dois construire le produit dans cet ordre :

## PHASE 1

Architecture + repository + infrastructure locale.

## PHASE 2

Database + migrations + authentication + organizations.

## PHASE 3

Invoice domain + validation + calculs.

## PHASE 4

Document engine + Factur-X + formats structurés.

## PHASE 5

Async jobs + queues + event system.

## PHASE 6

PDP abstraction + transmission.

## PHASE 7

Webhooks.

## PHASE 8

Dashboard complet.

## PHASE 9

Developer portal + OpenAPI + SDK.

## PHASE 10

Billing + usage.

## PHASE 11

Security + observability.

## PHASE 12

Tests E2E + load tests + compliance tests.

## PHASE 13

Infrastructure production.

## PHASE 14

Audit final + documentation + hardening.

---

# 87. ORDRE DE TRAVAIL DE L'IA

À chaque phase :

1. inspecter le repository ;
2. comprendre le code existant ;
3. définir ce qui manque ;
4. implémenter ;
5. lancer les tests ;
6. corriger ;
7. lancer lint/type check ;
8. vérifier migrations ;
9. vérifier sécurité ;
10. mettre à jour documentation ;
11. passer à la phase suivante.

Ne jamais simplement écrire du code sans l'exécuter.

---

# 88. RÈGLE IMPORTANTE SUR LES TESTS

Si un test échoue :

**ne contourne jamais le test simplement pour obtenir un build vert.**

Comprends la cause.

Corrige le code ou, si le test est réellement incorrect, corrige le test avec justification.

---

# 89. RÈGLE IMPORTANTE SUR LES DÉPENDANCES

Avant d'ajouter une dépendance :

* vérifier qu'elle est maintenue ;
* vérifier licence ;
* vérifier sécurité ;
* vérifier compatibilité ;
* éviter les dépendances inutiles.

Documenter les dépendances critiques.

---

# 90. LICENCES OPEN SOURCE

Pour toutes les bibliothèques Factur-X/XML/PDF :

vérifier :

* licence ;
* obligations ;
* compatibilité avec usage commercial ;
* dépendances transitives.

Créer :

```text
docs/legal/open-source.md
```

---

# 91. PRODUCTION READINESS CHECKLIST

Avant de déclarer le projet terminé :

```text
[ ] Authentication
[ ] MFA
[ ] RBAC
[ ] Tenant isolation
[ ] API keys
[ ] Rate limiting
[ ] Idempotency
[ ] Invoice engine
[ ] Credit notes
[ ] Validation
[ ] Factur-X
[ ] XML
[ ] PDF/A-3
[ ] Document storage
[ ] PDP abstraction
[ ] Transmission
[ ] Webhooks
[ ] Events
[ ] Audit
[ ] Billing
[ ] Usage
[ ] Dashboard
[ ] Developer portal
[ ] SDK
[ ] OpenAPI
[ ] Tests
[ ] Security
[ ] Monitoring
[ ] Backups
[ ] Disaster recovery
[ ] CI/CD
[ ] Docker
[ ] Infrastructure
[ ] GDPR preparation
[ ] Compliance documentation
[ ] Error handling
[ ] Load tests
[ ] E2E tests
[ ] Documentation
```

---

# 92. CRITÈRES DE QUALITÉ

Le produit final doit être :

### Fiable

Une facture ne doit pas être perdue.

### Idempotent

Une opération ne doit pas être exécutée deux fois accidentellement.

### Observable

Toute opération importante doit être traçable.

### Sécurisé

Les tenants doivent être strictement isolés.

### Scalable

L'architecture doit permettre de multiplier fortement le volume.

### Maintenable

Le domaine ne doit pas être couplé aux fournisseurs.

### Réglementairement évolutif

Les règles doivent pouvoir évoluer sans réécrire toute l'application.

### Developer-friendly

L'API doit être extrêmement simple.

---

# 93. CE QUE TU DOIS PRODUIRE

À la fin de ton travail, le repository doit contenir :

```text
APPLICATION
API
DASHBOARD
WORKERS
DATABASE
MIGRATIONS
DOCUMENT ENGINE
FACTUR-X
VALIDATION ENGINE
PDP ABSTRACTION
WEBHOOKS
AUTH
RBAC
BILLING
USAGE
ADMIN
SDK
OPENAPI
TESTS
CI/CD
DOCKER
INFRASTRUCTURE
MONITORING
DOCUMENTATION
```

Le projet doit démarrer localement avec une procédure documentée.

---

# 94. COMMANDES ATTENDUES

Créer une expérience simple :

```bash
git clone ...
cp .env.example .env
docker compose up
```

Puis :

```text
http://localhost:3000
```

Dashboard.

Et :

```text
http://localhost:8000/docs
```

API documentation.

---

# 95. FINAL AUDIT

Une fois l'ensemble développé, réalise toi-même un audit final.

Produis :

```text
FINAL_AUDIT.md
```

avec :

### Architecture

### Security

### Compliance

### Performance

### Testing

### API

### UX

### Infrastructure

### Observability

### Technical Debt

### Known Limitations

Pour chaque problème :

```text
Severity:
Critical
High
Medium
Low

Issue:
...

Impact:
...

Fix:
...

Status:
...
```

---

# 96. RÈGLE FINALE

**Ne t'arrête pas après avoir créé l'architecture.**

**Ne t'arrête pas après avoir créé le backend.**

**Ne t'arrête pas après avoir créé le frontend.**

**Ne t'arrête pas après avoir créé des tests.**

Continue jusqu'à ce que le repository constitue un produit cohérent et exécutable.

Si une partie ne peut pas être finalisée à cause d'une dépendance externe :

1. implémente tout ce qui est possible ;
2. isole la dépendance ;
3. documente précisément le blocage ;
4. fournis l'interface ;
5. fournis les tests ;
6. fournis la configuration ;
7. ne simule pas silencieusement la fonctionnalité.

---

# 97. PREMIÈRE ACTION

Commence maintenant.

### Étape 1

Inspecte entièrement le repository existant.

### Étape 2

Identifie :

* fichiers existants ;
* technologies ;
* dépendances ;
* architecture ;
* fonctionnalités déjà présentes ;
* problèmes ;
* dette technique.

### Étape 3

Crée :

```text
/docs/IMPLEMENTATION_PLAN.md
```

avec :

* architecture cible ;
* ordre des développements ;
* dépendances ;
* risques ;
* décisions techniques.

### Étape 4

Commence immédiatement l'implémentation.

### Étape 5

Après chaque grande étape, exécute les tests et corrige les erreurs.

### Étape 6

Ne détruis jamais une fonctionnalité existante sans raison.

### Étape 7

À la fin, fournis un résumé :

```text
Implemented
Tests
Security
Compliance
Infrastructure
Remaining external dependencies
Known limitations
How to run
How to deploy
```

**Objectif final : un véritable produit SaaS B2B production-ready, pas une démo, pas un MVP et pas un simple prototype.**
