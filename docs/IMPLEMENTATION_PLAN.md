# Plan d'Implémentation - Projet API Facturation

## État Actuel (Septembre 2026)

### ✅ Déjà implémenté
- Backend FastAPI avec endpoints CRUD de base
- Modèles SQLAlchemy : Organization, ApiKey, Customer, Invoice
- Authentification API Keys (Bearer)
- Pagination des listes
- Génération PDF async (ReportLab)
- Validation EN 16931 basique
- Workers Celery configurés
- Webhooks tasks (non intégrés)
- Alembic migrations
- Frontend Next.js basique
- Docker compose (PostgreSQL, Redis)
- Tests unitaires basiques

### ❌ Manquant pour Production

#### 1. Identity & Users (CRITIQUE)
- [ ] Table users, memberships, roles, permissions
- [ ] Inscription / Connexion / Logout
- [ ] Reset password / Email verification
- [ ] MFA/TOTP
- [ ] Sessions sécurisées dashboard
- [ ] RBAC complet (Owner, Admin, Developer, Accountant, Viewer)
- [ ] Invitations utilisateurs

#### 2. Invoice Engine Complet (CRITIQUE)
- [ ] Invoice lines (quantité, prix unitaire, TVA)
- [ ] Calculs financiers avec Decimal
- [ ] Support multi-taux TVA
- [ ] Remises et frais
- [ ] Numérotation séquentielle robuste
- [ ] Avoirs (Credit Notes)
- [ ] Paiements associés

#### 3. Idempotency (CRITIQUE)
- [ ] Table idempotency_keys
- [ ] Middleware/Decorator Idempotency-Key
- [ ] Tests de non-création en double

#### 4. Document Service (CRITIQUE)
- [ ] Stockage S3-compatible
- [ ] Versioning documents
- [ ] PDF/A-3 conforme
- [ ] Embed XML Factur-X
- [ ] Téléchargement sécurisé

#### 5. Factur-X / EN 16931 (CRITIQUE)
- [ ] Modèle canonique Invoice
- [ ] Génération CII XML
- [ ] Validation XSD/Schematron
- [ ] PDF/A-3 generation
- [ ] Embed XML dans PDF
- [ ] Tests de conformité

#### 6. PDP Abstraction
- [ ] Interface PDPAdapter
- [ ] Registry des PDP
- [ ] State machine transmission
- [ ] Retry engine avec backoff exponentiel
- [ ] Dead letter queue

#### 7. Webhooks System (COMPLET)
- [ ] Table webhooks, webhook_deliveries
- [ ] CRUD endpoints webhooks
- [ ] Signature HMAC
- [ ] Replay capability
- [ ] Logs de délivrance

#### 8. Events & Audit (CRITIQUE)
- [ ] Table events (event sourcing léger)
- [ ] Table audit_logs
- [ ] Timeline par facture
- [ ] Immuabilité des logs

#### 9. Rate Limiting
- [ ] Middleware rate limiting
- [ ] Configuration par org/API key
- [ ] Headers X-RateLimit-*
- [ ] Response 429 propre

#### 10. Error Handling Unifié
- [ ] Format d'erreur standardisé
- [ ] Catalogue d'erreurs
- [ ] request_id sur chaque réponse

#### 11. Frontend Dashboard (COMPLET)
- [ ] Login/Register
- [ ] Dashboard avec métriques réelles
- [ ] Liste factures avec filtres
- [ ] Détail facture complet
- [ ] Création/Modification factures
- [ ] Gestion clients
- [ ] Clés API
- [ ] Webhooks configuration
- [ ] Audit log
- [ ] Paramètres organisation
- [ ] Gestion équipe/utilisateurs

#### 12. Tests (CRITIQUE)
- [ ] Tests unitaires complets
- [ ] Tests d'intégration
- [ ] Tests isolation multi-tenant
- [ ] Tests de charge
- [ ] E2E tests (Playwright)
- [ ] Security tests
- [ ] Compliance tests (EN 16931)

#### 13. CI/CD
- [ ] GitHub Actions workflow
- [ ] Lint + Type check
- [ ] Tests automatiques
- [ ] Build Docker
- [ ] Deploy staging/prod

#### 14. Monitoring & Observability
- [ ] Logs structurés JSON
- [ ] Metrics Prometheus
- [ ] Tracing OpenTelemetry
- [ ] Health checks avancés
- [ ] Alertes configurées

#### 15. Sécurité Renforcée
- [ ] HTTPS enforcement
- [ ] Secure headers
- [ ] CORS strict
- [ ] CSRF protection
- [ ] XSS protection
- [ ] SQL injection prevention
- [ ] Secrets management

#### 16. Documentation
- [ ] OpenAPI auto-générée
- [ ] Developer portal
- [ ] SDK Python
- [ ] SDK TypeScript
- [ ] Architecture docs
- [ ] Security docs
- [ ] Compliance docs
- [ ] GDPR docs

#### 17. Billing SaaS & Usage
- [ ] Plans (Free, Starter, Pro, Business)
- [ ] Subscriptions
- [ ] Usage metering
- [ ] Facturation SaaS

#### 18. Admin Panel
- [ ] Interface admin séparée
- [ ] Gestion organisations
- [ ] Support tools

---

## Ordre de Priorité

### Phase 1 - Fondation (Semaine 1)
1. Identity & Users + RBAC
2. Invoice Engine complet avec lignes
3. Idempotency
4. Error handling unifié
5. Tests isolation tenant

### Phase 2 - Documents & Compliance (Semaine 2)
6. Document Service avec S3
7. Factur-X complet
8. Validation EN 16931 avancée

### Phase 3 - Transmission & Events (Semaine 3)
9. PDP Abstraction
10. State machine transmission
11. Events & Audit logs
12. Webhooks system complet

### Phase 4 - Frontend & DX (Semaine 4)
13. Dashboard complet
14. Developer portal
15. SDKs
16. Documentation

### Phase 5 - Production Ready (Semaine 5)
17. Rate limiting
18. Monitoring
19. CI/CD
20. Security hardening
21. Tests E2E & charge
22. Billing SaaS

---

## Décisions Techniques

### Database
- PostgreSQL 16+ avec UUID
- Index sur organization_id + created_at
- Constraints uniques pour numérotation
- Soft delete pour audit

### Cache/Queue
- Redis pour cache sessions
- Redis pour Celery broker/backend
- TTL appropriés

### Storage
- S3-compatible (MinIO dev, AWS prod)
- Versioning activé
- Encryption at rest

### Authentication
- JWT pour sessions dashboard
- API Keys hashées (SHA-256)
- MFA avec TOTP

### Multi-tenancy
- organization_id sur toutes tables
- Filtrage automatique via Depends()
- Tests d'isolation obligatoires

### Code Quality
- Type hints stricts
- ruff + black formatting
- pytest avec coverage > 80%
- Pre-commit hooks

---

## Risques Identifiés

1. **Factur-X complexité** : Bibliothèques Python limitées
   - Mitigation : Utiliser lxml + templates XML validés
   
2. **PDP sans accès réel** : Impossible de tester en production
   - Mitigation : Adapter mockable + tests contractuels
   
3. **Performance génération PDF** : Lent en synchrone
   - Mitigation : Toujours async + worker dédié
   
4. **Conformité réglementaire** : Évolutive
   - Mitigation : Compliance engine versionné

---

## Métriques de Succès

- [ ] 100% tests passing
- [ ] Coverage > 80%
- [ ] p95 API < 300ms
- [ ] Zéro faille sécurité critique
- [ ] Isolation tenant prouvée
- [ ] Documentation complète
- [ ] Démarrage en 1 commande
