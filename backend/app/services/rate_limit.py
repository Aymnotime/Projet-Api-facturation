"""Rate limiting distribué basé sur Redis (fenêtre glissante, INCR + EXPIRE).

Conception :
* ``RateLimiter`` encapsule un client Redis et applique une politique
  (max requêtes / fenêtre en secondes) sur une clé donnée.
* La décision est atomique au sens pratique : ``INCR`` renvoie le compteur
  courant ; si la valeur passe le seuil on pose ``EXPIRE`` uniquement sur la
  première incrément (clé fraîchement créée), ce qui garantit une fenêtre
  fixe par bucket sans TTL reset infini.
* Si Redis est indisponible, on **échoue ouvert** (fail-open) : le service
  n'interdit pas le trafic légitime ; l'événement est loggé.
* ``get_redis()`` construit le client depuis les settings ; les tests
  injectent un client ``fakeredis`` via l'override FastAPI de
  ``get_rate_limiter``/``get_strict_rate_limiter``.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from typing import Protocol

import redis

from app.config import Settings, get_settings

logger = logging.getLogger(__name__)


class RedisLike(Protocol):
    """Sous-ensemble d'API Redis utilisé ici (compatible fakeredis)."""

    def incr(self, name: str) -> int: ...

    def expire(self, name: str, seconds: int) -> bool: ...

    def ttl(self, name: str) -> int: ...


@dataclass(frozen=True)
class RateLimitDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after: int  # secondes ; 0 si autorisé


class RateLimiter:
    def __init__(self, client: RedisLike, *, limit: int, window_seconds: int, prefix: str = "rl") -> None:
        self.client = client
        self.limit = limit
        self.window_seconds = window_seconds
        self.prefix = prefix

    def hit(self, bucket_key: str) -> RateLimitDecision:
        """Compte une requête pour ``bucket_key`` et décide allow/deny."""
        key = f"{self.prefix}:{bucket_key}"
        try:
            count = self.client.incr(key)
            if count == 1:
                self.client.expire(key, self.window_seconds)
            if count > self.limit:
                ttl = self.client.ttl(key)
                retry_after = ttl if ttl and ttl > 0 else self.window_seconds
                return RateLimitDecision(
                    allowed=False, limit=self.limit, remaining=0, retry_after=int(retry_after)
                )
            return RateLimitDecision(
                allowed=True, limit=self.limit, remaining=max(self.limit - count, 0), retry_after=0
            )
        except Exception:  # fail-open si Redis est HS
            logger.warning("Rate limiter Redis unavailable, failing open", exc_info=True)
            return RateLimitDecision(allowed=True, limit=self.limit, remaining=self.limit, retry_after=0)


def get_redis(settings: Settings | None = None) -> redis.Redis | None:
    """Client Redis partagé (None si non configuré → désactivation du LLM)."""
    settings = settings or get_settings()
    if not settings.redis_url:
        return None
    return redis.Redis.from_url(settings.redis_url, decode_responses=True)


# ---------------------------------------------------------------------------
# Dépendances FastAPI
# ---------------------------------------------------------------------------

_client_cache: dict[str, RedisLike] = {}


def _resolve_client(explicit: RedisLike | None = None) -> RedisLike | None:
    if explicit is not None:
        return explicit
    settings = get_settings()
    if not settings.redis_url:
        return None
    cached = _client_cache.get(settings.redis_url)
    if cached is None:
        cached = redis.Redis.from_url(settings.redis_url, decode_responses=True)
        _client_cache[settings.redis_url] = cached
    return cached


def build_standard_limiter(client: RedisLike | None = None) -> RateLimiter | None:
    settings = get_settings()
    if not settings.rate_limit_enabled:
        return None
    resolved = _resolve_client(client)
    if resolved is None:
        return None
    return RateLimiter(
        resolved,
        limit=settings.rate_limit_requests,
        window_seconds=settings.rate_limit_window_seconds,
        prefix="rl",
    )


def build_strict_limiter(client: RedisLike | None = None) -> RateLimiter | None:
    settings = get_settings()
    if not settings.rate_limit_strict_enabled:
        return None
    resolved = _resolve_client(client)
    if resolved is None:
        return None
    return RateLimiter(
        resolved,
        limit=settings.rate_limit_strict_requests,
        window_seconds=settings.rate_limit_strict_window_seconds,
        prefix="rl-strict",
    )


def get_rate_limiter() -> RateLimiter | None:
    """Dépendance : limiteur standard (trafic API authentifié)."""
    return build_standard_limiter()


def get_strict_rate_limiter() -> RateLimiter | None:
    """Dépendance : limiteur strict (endpoints sensibles non authentifiés)."""
    return build_strict_limiter()
