"""
Service de gestion des clés d'idempotence.
Permet d'éviter les traitements en double lors de requêtes répétées.
"""
import hashlib
import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session

from app.models import IdempotencyKey


class IdempotencyService:
    """Service pour gérer les clés d'idempotence."""
    
    # TTL par défaut : 24 heures
    DEFAULT_TTL_HOURS = 24
    
    @staticmethod
    def _hash_key(key: str) -> str:
        """Hache la clé d'idempotence pour le stockage sécurisé."""
        return hashlib.sha256(key.encode('utf-8')).hexdigest()
    
    @classmethod
    def get_key(
        cls, 
        db: Session, 
        organization_id: str, 
        key: str
    ) -> Optional[IdempotencyKey]:
        """
        Récupère une clé d'idempotence existante.
        
        Args:
            db: Session de base de données
            organization_id: ID de l'organisation
            key: La clé d'idempotence brute
            
        Returns:
            L'objet IdempotencyKey s'il existe, None sinon
        """
        key_hash = cls._hash_key(key)
        return db.scalar(
            select(IdempotencyKey).where(
                IdempotencyKey.organization_id == organization_id,
                IdempotencyKey.key == key_hash
            )
        )
    
    @classmethod
    def create_key(
        cls,
        db: Session,
        organization_id: str,
        key: str,
        method: str,
        path: str,
        ttl_hours: int = DEFAULT_TTL_HOURS
    ) -> IdempotencyKey:
        """
        Crée une nouvelle clé d'idempotence.
        
        Args:
            db: Session de base de données
            organization_id: ID de l'organisation
            key: La clé d'idempotence brute
            method: Méthode HTTP (POST, PUT, PATCH)
            path: Chemin de la requête
            ttl_hours: Durée de vie en heures
            
        Returns:
            L'objet IdempotencyKey créé
        """
        key_hash = cls._hash_key(key)
        expires_at = datetime.now(timezone.utc) + timedelta(hours=ttl_hours)
        
        idempotency_key = IdempotencyKey(
            organization_id=organization_id,
            key=key_hash,
            method=method.upper(),
            path=path,
            expires_at=expires_at
        )
        
        db.add(idempotency_key)
        db.flush()  # Pour obtenir l'ID sans committer
        
        return idempotency_key
    
    @classmethod
    def store_response(
        cls,
        db: Session,
        idempotency_key: IdempotencyKey,
        response_status: int,
        response_body: Any
    ) -> None:
        """
        Stocke la réponse associée à une clé d'idempotence.
        
        Args:
            db: Session de base de données
            idempotency_key: L'objet IdempotencyKey
            response_status: Code HTTP de la réponse
            response_body: Corps de la réponse (sera sérialisé en JSON)
        """
        # Sérialiser le corps de la réponse en JSON
        if isinstance(response_body, dict) or isinstance(response_body, list):
            response_body_str = json.dumps(response_body, default=str)
        else:
            response_body_str = str(response_body)
        
        idempotency_key.response_status = response_status
        idempotency_key.response_body = response_body_str
        
        db.add(idempotency_key)
        db.commit()
    
    @classmethod
    def is_expired(cls, idempotency_key: IdempotencyKey) -> bool:
        """Vérifie si une clé d'idempotence est expirée."""
        now = datetime.now(timezone.utc)
        expires_at = idempotency_key.expires_at
        # Ensure expires_at is timezone-aware
        if expires_at.tzinfo is None:
            from datetime import timezone as tz
            expires_at = expires_at.replace(tzinfo=tz.utc)
        return now > expires_at
    
    @classmethod
    def cleanup_expired(cls, db: Session, organization_id: Optional[str] = None) -> int:
        """
        Nettoie les clés d'idempotence expirées.
        
        Args:
            db: Session de base de données
            organization_id: Optionnel, filtre par organisation
            
        Returns:
            Nombre de clés supprimées
        """
        from sqlalchemy import delete
        
        now = datetime.now(timezone.utc)
        stmt = delete(IdempotencyKey).where(IdempotencyKey.expires_at < now)
        
        if organization_id:
            stmt = stmt.where(IdempotencyKey.organization_id == organization_id)
        
        result = db.execute(stmt)
        db.commit()
        
        return result.rowcount
