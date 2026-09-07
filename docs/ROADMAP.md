# Feuille de route

## Tranche 1 - livree

- socle FastAPI et OpenAPI ;
- PostgreSQL/SQLite ;
- organisations et cles API ;
- clients et factures ;
- dashboard de demarrage ;
- tests et Docker Compose.

## Tranche 2 - fiabilisation

- Alembic et migrations versionnees ;
- idempotency keys ;
- pagination et filtres ;
- RBAC utilisateurs ;
- journal d'audit ;
- rate limiting Redis ;
- CI lint, type-check et tests.

## Tranche 3 - documents

- moteur de templates ;
- PDF et Factur-X ;
- validation EN 16931 basee sur les sources officielles ;
- stockage objet S3-compatible ;
- jobs asynchrones et suivi des traitements.

## Tranche 4 - echanges

- webhooks signes et retries ;
- abstraction PDP ;
- premier adaptateur fournisseur ;
- statuts de transmission et e-reporting.

Chaque tranche doit etre livree avec ses tests, sa documentation et une validation executable avant d'ouvrir la suivante.
