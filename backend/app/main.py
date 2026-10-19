"""Point d'entrée de l'API de facturation.

La logique métier est répartie dans des routers dédiés (app/api/*) ;
ce module ne contient que la création de l'application, le câblage des
middlewares de sécurité (CORS restreint + en-têtes de durcissement) et le
montage des routers.
"""
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .db import Base, engine
from .api.auth import router as auth_router
from .api.customers import router as customers_router
from .api.invoice_numbering import router as invoice_numbering_router
from .api.invoices import router as invoices_router
from .api.organizations import router as organizations_router
from .api.transmissions import router as transmissions_router
from .api.users import router as users_router
from .api.webhooks import router as webhooks_router
from .services.security_middleware import SecurityHeadersMiddleware

# TODO: remplacer par les migrations Alembic une fois le schéma stabilisé.
Base.metadata.create_all(bind=engine)

settings = get_settings()

app = FastAPI(
    title=settings.app_name,
    version="0.4.0",
    description=(
        "API-first billing infrastructure with Identity, Users, RBAC and full business logic"
    ),
)

# --- Sécurité HTTP ---------------------------------------------------------
# CORS restreint à l'allowlist configurée (jamais "*" hors développement).
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PATCH", "DELETE", "OPTIONS"],
    allow_headers=[
        "Authorization",
        "Content-Type",
        "X-API-Key",
        "Idempotency-Key",
        "X-Forwarded-For",
    ],
)
# En-têtes de durcissement sur toutes les réponses.
app.add_middleware(SecurityHeadersMiddleware)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(organizations_router)
app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(invoice_numbering_router)
app.include_router(transmissions_router)
app.include_router(webhooks_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
