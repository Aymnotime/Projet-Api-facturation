"""Middleware de sécurité HTTP et application du rate limiting par route.

* ``SecurityHeadersMiddleware`` ajoute les en-têtes de durcissement sur
  toutes les réponses (HSTS, nosniff, frame DENY, Referrer-Policy, CSP,
  Permissions-Policy) et masque le bannière serveur FastAPI/Starlette.
* ``apply_rate_limit`` est un helper appelé par les routes sensibles :
  il bucketise par identité API (org/user/IP) puis par IP pour le strict.
"""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware, RequestResponseEndpoint
from starlette.requests import Request
from starlette.responses import Response

from app.services.rate_limit import RateLimiter


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next: RequestResponseEndpoint) -> Response:
        response = await call_next(request)
        h = response.headers
        # Transport
        h.setdefault("Strict-Transport-Security", "max-age=63072000; includeSubDomains")
        # Content sniffing / framing
        h.setdefault("X-Content-Type-Options", "nosniff")
        h.setdefault("X-Frame-Options", "DENY")
        h.setdefault("Referrer-Policy", "no-referrer")
        h.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        # CSP restrictive : API JSON, aucune ressource externe exécutée.
        h.setdefault(
            "Content-Security-Policy",
            "default-src 'none'; frame-ancestors 'none'; base-uri 'none'",
        )
        # Masquer l'implémentation serveur
        h.pop("Server", None)
        return response


def client_ip(request: Request) -> str:
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    return request.client.host if request.client else "unknown"


def apply_rate_limit(request: Request, limiter: RateLimiter | None, *, bucket_prefix: str = "std") -> None:
    """Exécute la politique de rate limiting ; lève HTTP 429 si dépassée.

    No-op si ``limiter`` est None (Redis non configuré ou limite désactivée).
    L'identité utilisée : organisation+utilisateur si déjà résolus sur
    ``request.state``, sinon l'IP cliente.
    """
    from fastapi import HTTPException, status

    if limiter is None:
        return
    org_id = getattr(request.state, "organization_id", None)
    user_id = getattr(request.state, "user_id", None)
    if org_id and user_id:
        bucket = f"{bucket_prefix}:org:{org_id}:user:{user_id}"
    elif org_id:
        bucket = f"{bucket_prefix}:org:{org_id}"
    else:
        bucket = f"{bucket_prefix}:ip:{client_ip(request)}"

    decision = limiter.hit(bucket)
    if not decision.allowed:
        raise HTTPException(
            status_code=status.HTTP_429_TOO_MANY_REQUESTS,
            detail="Too many requests",
            headers={
                "Retry-After": str(decision.retry_after),
                "X-RateLimit-Limit": str(decision.limit),
                "X-RateLimit-Remaining": "0",
            },
        )


def set_rate_limit_headers(response: Response, limiter: RateLimiter | None, bucket: str) -> Response:
    """Enrichit la réponse des en-têtes X-RateLimit-* standards."""
    if limiter is None:
        return response
    try:
        key = f"{limiter.prefix}:{bucket}"
        count = int(limiter.client.get(key) or 0)  # type: ignore[attr-defined]
    except Exception:
        return response
    remaining = max(limiter.limit - count, 0)
    response.headers.setdefault("X-RateLimit-Limit", str(limiter.limit))
    response.headers["X-RateLimit-Remaining"] = str(remaining)
    return response
