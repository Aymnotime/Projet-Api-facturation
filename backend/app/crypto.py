"""Primitives de sécurité : chiffrement réversible des credentials externes.

Utilisé par les adaptateurs PDP (Chorus Pro…) pour stocker les secrets
d'API *au repos* sous forme chiffrée (Fernet = AES-128-CBC + HMAC-SHA256).

La clé maître provient de la variable d'environnement ``CREDENTIALS_KEY``
(clef Fernet base64, 32 octets). En développement, une clé déterministe
dérivée du ``JWT_SECRET`` est acceptée ; en production une ``CREDENTIALS_KEY``
explicite est obligatoire.

Génération d'une clé :
    python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
"""
from __future__ import annotations

import base64
import hashlib

from cryptography.fernet import Fernet, InvalidToken

from app.config import get_settings


class CredentialsKeyError(RuntimeError):
    """Clé de chiffrement absente, invalide ou interdite par l'environnement."""


def _master_key() -> bytes:
    settings = get_settings()
    raw = getattr(settings, "credentials_key", "") or ""
    if raw:
        try:
            # Valide le format Fernet dès maintenant (échec rapide si mal formé).
            Fernet(raw.encode() if isinstance(raw, str) else raw)
            return raw.encode() if isinstance(raw, str) else raw
        except Exception as exc:  # noqa: BLE001 - tout format invalide est fatal ici
            raise CredentialsKeyError("CREDENTIALS_KEY is not a valid Fernet key") from exc
    # Pas de clé explicite : dérivation depuis JWT_SECRET (dev/test uniquement),
    # ou clé de secours déterministe hors production pour ne jamais bloquer le
    # développement local sans configuration.
    if settings.is_production:
        raise CredentialsKeyError(
            "CREDENTIALS_KEY must be explicitly set in production"
        )
    seed = settings.jwt_secret or "insecure-dev-credentials-key"
    digest = hashlib.sha256(f"credentials:{seed}".encode()).digest()
    return base64.urlsafe_b64encode(digest)


def encrypt_secret(plaintext: str) -> str:
    """Chiffre un secret (token OAuth, mot de passe API) → chaîne Fernet."""
    if plaintext is None or plaintext == "":
        raise ValueError("Cannot encrypt an empty secret")
    return Fernet(_master_key()).encrypt(plaintext.encode("utf-8")).decode("utf-8")


def decrypt_secret(token: str) -> str:
    """Déchiffre un token Fernet stocké. Lève ``CredentialsKeyError`` si corrompu."""
    try:
        return Fernet(_master_key()).decrypt(token.encode("utf-8")).decode("utf-8")
    except InvalidToken as exc:
        raise CredentialsKeyError(
            "Stored credential is corrupted or encrypted with another key"
        ) from exc


def looks_encrypted(value: str) -> bool:
    """Vrai si ``value`` ressemble à un token Fernet (préfixe gAAAAA…)."""
    return isinstance(value, str) and value.startswith("gAAAAA")


def resolve_secret(stored: str) -> str:
    """Renvoie le secret en clair : déchiffre si stocké chiffré, sinon passe-through.

    Permet une migration progressive : les valeurs déjà enregistrées en clair
    continuent de fonctionner hors production ; en production le clair est refusé.
    """
    if not stored:
        return ""
    if looks_encrypted(stored):
        return decrypt_secret(stored)
    if get_settings().is_production:
        raise CredentialsKeyError(
            "Plaintext credentials are forbidden in production; store them via encrypt_secret()"
        )
    return stored
