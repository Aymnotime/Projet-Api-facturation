"""Point d'entrée de l'API de facturation.

La logique métier est répartie dans des routers dédiés (app/api/*) ;
ce module ne contient que la création de l'application et le montage
des routers.
"""
from fastapi import FastAPI

from .db import Base, engine
from .api.auth import router as auth_router
from .api.customers import router as customers_router
from .api.invoice_numbering import router as invoice_numbering_router
from .api.invoices import router as invoices_router
from .api.organizations import router as organizations_router
from .api.users import router as users_router

# TODO: remplacer par les migrations Alembic une fois le schéma stabilisé.
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title="Projet API Facturation",
    version="0.4.0",
    description=(
        "API-first billing infrastructure with Identity, Users, RBAC and full business logic"
    ),
)

app.include_router(auth_router)
app.include_router(users_router)
app.include_router(organizations_router)
app.include_router(customers_router)
app.include_router(invoices_router)
app.include_router(invoice_numbering_router)


@app.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
