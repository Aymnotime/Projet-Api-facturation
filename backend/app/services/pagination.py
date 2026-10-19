"""Helpers de pagination réutilisables pour les endpoints en liste."""
import math
from typing import Any, Sequence, TypeVar

from sqlalchemy import Select, func, select
from sqlalchemy.orm import Session

T = TypeVar("T")


def paginate(
    db: Session,
    stmt: Select[tuple[T]],
    page: int,
    per_page: int,
) -> dict[str, Any]:
    """Applique une pagination offset/limit sur une requête SQLAlchemy.

    Retourne un dict prêt pour les schémas Paginated* :
    items, total, page, per_page, pages.
    """
    count_stmt = select(func.count()).select_from(stmt.order_by(None).subquery())
    total = db.scalar(count_stmt) or 0
    pages = math.ceil(total / per_page) if total > 0 else 1

    offset = (page - 1) * per_page
    items: Sequence[T] = list(db.scalars(stmt.offset(offset).limit(per_page)))

    return {"items": items, "total": total, "page": page, "per_page": per_page, "pages": pages}
