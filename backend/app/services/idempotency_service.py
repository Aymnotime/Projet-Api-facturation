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

    @classmethod
    def process_request(
        cls,
        db: Session,
        organization_id: str,
        key: str,
        method: str,
        path: str
    ) -> tuple[bool, Optional[dict], Optional[IdempotencyKey]]:
        """
        Traite une requête avec gestion d'idempotence.

        Cette méthode vérifie si une réponse existe déjà pour cette clé.
        Si oui, elle retourne la réponse cached.
        Sinon, elle crée une nouvelle clé et retourne un indicateur pour exécuter le handler.

        Args:
            db: Session de base de données
            organization_id: ID de l'organisation
            key: Clé d'idempotence fournie par le client
            method: Méthode HTTP
            path: Chemin de la requête

        Returns:
            Tuple de (is_cached, cached_response_dict, idempotency_key)
            - is_cached: True si une réponse cached existe
            - cached_response_dict: Dict avec status_code et body si cached
            - idempotency_key: L'objet IdempotencyKey (nouveau ou existant)
        """
        # Vérifier si la clé existe déjà
        existing_key = cls.get_key(db, organization_id, key)

        if existing_key:
            # Vérifier si elle n'est pas expirée
            if cls.is_expired(existing_key):
                # Clé expirée, on la supprime et on traite comme nouvelle
                db.delete(existing_key)
                db.commit()
                existing_key = None
            elif existing_key.response_body is not None:
                # Réponse déjà disponible, la retourner
                try:
                    response_body = json.loads(existing_key.response_body)
                except json.JSONDecodeError:
                    response_body = {"detail": existing_key.response_body}
                
                return True, {
                    "status_code": existing_key.response_status,
                    "body": response_body
                }, existing_key

        # Créer une nouvelle clé si nécessaire
        if not existing_key:
            new_key = cls.create_key(db, organization_id, key, method, path)
            db.flush()  # Flush pour obtenir l'ID mais ne pas committer encore
            return False, None, new_key
        
        # Clé existe mais pas encore de réponse (première requête en cours)
        return False, None, existing_key
