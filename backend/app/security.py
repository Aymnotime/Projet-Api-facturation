import hashlib
import secrets

from fastapi import Depends, Header, HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from .db import get_db
from .models import ApiKey, Organization


def generate_api_key() -> tuple[str, str, str]:
    raw = f"sk_live_{secrets.token_urlsafe(32)}"
    return raw, raw[:16], hashlib.sha256(raw.encode()).hexdigest()


def require_organization(
    authorization: str | None = Header(default=None), db: Session = Depends(get_db)
) -> Organization:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Bearer API key required")
    raw_key = authorization.removeprefix("Bearer ").strip()
    key_hash = hashlib.sha256(raw_key.encode()).hexdigest()
    api_key = db.scalar(select(ApiKey).where(ApiKey.key_hash == key_hash, ApiKey.revoked_at.is_(None)))
    if not api_key:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid or revoked API key")
    return api_key.organization
