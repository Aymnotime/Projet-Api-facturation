"""
Middleware et dépendances pour la gestion de l'idempotence.
"""
import hashlib
import json
from typing import Any, Optional

from fastapi import Depends, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import IdempotencyKey, Organization
from app.services.idempotency_service import IdempotencyService


class IdempotencyHandler:
    """
    Gestionnaire d'idempotence pour les requêtes HTTP.
    
    Utilisation:
        @app.post("/v1/invoices")
        async def create_invoice(
            payload: InvoiceCreate,
            idempotency_result: dict = Depends(IdempotencyHandler()),
            db: Session = Depends(get_db)
        ):
            # Si une réponse existe déjà, elle est retournée automatiquement
            if idempotency_result.get("cached_response"):
                return idempotency_result["cached_response"]
            
            # Traitement normal...
            result = await process_invoice(payload)
            
            # La réponse sera automatiquement stockée après exécution
            return result
    """
    
    def __init__(self, ttl_hours: int = 24):
        """
        Initialise le gestionnaire d'idempotence.
        
        Args:
            ttl_hours: Durée de vie des clés en heures (défaut: 24)
        """
        self.ttl_hours = ttl_hours
    
    async def __call__(
        self,
        request: Request,
        db: Session = Depends(get_db)
    ) -> dict[str, Any]:
        """
        Intercepte la requête pour vérifier/gérer l'idempotence.
        
        Args:
            request: La requête HTTP
            db: Session de base de données
            
        Returns:
            Un dictionnaire contenant:
                - has_key: booléen indiquant si une clé a été fournie
                - is_duplicate: booléen indiquant si c'est un doublon
                - cached_response: La réponse cachée si disponible
                - idempotency_key: L'objet IdempotencyKey si créé
        """
        result = {
            "has_key": False,
            "is_duplicate": False,
            "cached_response": None,
            "idempotency_key": None,
            "should_process": True
        }
        
        # Vérifier si c'est une méthode supportée
        if request.method not in ["POST", "PUT", "PATCH"]:
            return result
        
        # Récupérer la clé d'idempotence depuis les headers
        idempotency_key_header = request.headers.get("Idempotency-Key")
        if not idempotency_key_header:
            return result
        
        result["has_key"] = True
        
        # Récupérer l'organisation depuis le header Authorization
        auth_header = request.headers.get("Authorization", "")
        organization_id = None
        
        if auth_header.startswith("Bearer "):
            api_key_raw = auth_header.removeprefix("Bearer ").strip()
            api_key_hash = hashlib.sha256(api_key_raw.encode()).hexdigest()
            from app.models import ApiKey
            from sqlalchemy import select
            api_key_obj = db.scalar(
                select(ApiKey).where(
                    ApiKey.key_hash == api_key_hash,
                    ApiKey.revoked_at.is_(None)
                )
            )
            if api_key_obj:
                organization_id = api_key_obj.organization_id
        
        if not organization_id:
            # Si pas d'organisation, on ne peut pas faire d'idempotence multi-tenant
            return result
        
        # Chercher la clé existante
        existing_key = IdempotencyService.get_key(db, organization_id, idempotency_key_header)
        
        if existing_key:
            # Vérifier si expirée
            if IdempotencyService.is_expired(existing_key):
                # Clé expirée, on la supprime et on traite comme nouvelle
                db.delete(existing_key)
                db.commit()
                existing_key = None
            else:
                # Clé valide, vérifier si réponse déjà stockée
                if existing_key.response_body is not None:
                    # Réponse déjà disponible, la retourner
                    result["is_duplicate"] = True
                    result["cached_response"] = await self._build_cached_response(
                        existing_key.response_status,
                        existing_key.response_body
                    )
                    result["should_process"] = False
                    result["idempotency_key"] = existing_key
                    return result
        
        # Créer une nouvelle clé si nécessaire
        if not existing_key:
            new_key = IdempotencyService.create_key(
                db=db,
                organization_id=organization_id,
                key=idempotency_key_header,
                method=request.method,
                path=request.url.path,
                ttl_hours=self.ttl_hours
            )
            db.commit()
            result["idempotency_key"] = new_key
        
        return result
    
    async def _get_request_body(self, request: Request) -> Optional[dict]:
        """Récupère le corps de la requête."""
        try:
            body = await request.json()
            return body
        except Exception:
            return None
    
    async def _build_cached_response(self, status_code: int, body_str: str) -> Response:
        """Construit une réponse HTTP depuis les données cachées."""
        try:
            body = json.loads(body_str)
        except json.JSONDecodeError:
            body = {"detail": body_str}
        
        return JSONResponse(
            status_code=status_code,
            content=body,
            headers={"X-Idempotency-Cache": "true"}
        )


def require_idempotency_key(request: Request) -> str:
    """
    Dépendance pour exiger une clé d'idempotence.
    
    Raises:
        HTTPException: Si la clé n'est pas fournie
    """
    key = request.headers.get("Idempotency-Key")
    if not key:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Idempotency-Key header is required for this endpoint"
        )
    return key


def store_response_after_request(
    response: Response,
    idempotency_key: Optional[IdempotencyKey],
    db: Session
) -> None:
    """
    Stocke la réponse après exécution de la requête.
    
    Args:
        response: La réponse HTTP
        idempotency_key: L'objet IdempotencyKey
        db: Session de base de données
    """
    if idempotency_key and hasattr(response, "body"):
        try:
            # Extraire le corps de la réponse
            body = response.body.decode('utf-8') if isinstance(response.body, bytes) else response.body
            IdempotencyService.store_response(
                db=db,
                idempotency_key=idempotency_key,
                response_status=response.status_code,
                response_body=body
            )
        except Exception:
            # En cas d'erreur, on log mais on ne bloque pas
            pass
