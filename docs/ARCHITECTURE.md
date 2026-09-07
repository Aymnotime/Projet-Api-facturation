# Architecture initiale

## Périmètre livré

Cette première tranche fournit un socle exécutable :

- API FastAPI avec OpenAPI automatique ;
- PostgreSQL via Docker Compose et SQLite pour le développement local ;
- organisations et clés API hashées ;
- clients et factures avec isolation par organisation ;
- émission d'une facture depuis l'état `draft` ;
- tests d'intégration ;
- dashboard Next.js relié au endpoint `/health`.

## Choix structurants

Le domaine reste dans des modules Python simples afin de pouvoir introduire ensuite des services applicatifs, des migrations Alembic et des workers sans coupler l'API aux fournisseurs externes. Les montants sont exprimés en unités mineures (`total_minor`) pour éviter les erreurs d'arrondi.

La clé API complète n'est renvoyée qu'à sa création. Seul son hash SHA-256 est conservé en base. Les requêtes métier doivent utiliser `Authorization: Bearer <clé>`.

## Limites connues

La validation réglementaire EN 16931, la génération Factur-X/PDF-A-3, les webhooks, la file Redis/Celery, les PDP et la facturation SaaS ne sont pas encore implémentés. Ils doivent faire l'objet de tranches séparées avec vérification des sources officielles et tests contractuels.
