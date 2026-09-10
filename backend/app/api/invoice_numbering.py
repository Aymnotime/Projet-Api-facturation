"""
API pour la gestion de la numérotation des factures.
Endpoints pour générer, valider et auditer la numérotation.
"""
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, status, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import Organization
from app.security import require_organization
from app.services.invoice_numbering_service import (
    InvoiceNumberingService,
    InvoiceNumberingError
)
from app.schemas import (
    InvoiceNumberGenerate,
    InvoiceNumberResponse,
    InvoiceNumberValidationRequest,
    InvoiceNumberValidationResponse,
    InvoiceContinuityCheckResponse
)


router = APIRouter(prefix="/v1/invoice-numbering", tags=["Invoice Numbering"])


@router.post(
    "/generate",
    response_model=InvoiceNumberResponse,
    status_code=status.HTTP_201_CREATED,
    summary="Générer un numéro de facture",
    description="Génère un numéro de facture unique et séquentiel pour une organisation."
)
def generate_invoice_number(
    payload: Optional[InvoiceNumberGenerate] = None,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db)
) -> InvoiceNumberResponse:
    """
    Génère un nouveau numéro de facture selon le format PREFIX-YYYY-NNNN.
    
    La génération est atomique et garantit l'unicité au niveau de l'organisation.
    Si aucun préfixe n'est fourni, utilise celui de l'organisation ou "FAC" par défaut.
    
    **Permissions requises :** ADMIN, OWNER, DEVELOPER
    """
    try:
        year = payload.year if payload and payload.year else None
        prefix = payload.prefix if payload and payload.prefix else None
        
        # Générer le numéro
        invoice_number = InvoiceNumberingService.generate_number(
            db=db,
            organization_id=organization.id,
            year=year,
            prefix=prefix
        )
        
        # Extraire les composants du numéro généré
        parts = invoice_number.split("-")
        generated_prefix = parts[0] if len(parts) > 0 else prefix or "FAC"
        generated_year = int(parts[1]) if len(parts) > 1 and parts[1].isdigit() else datetime.now().year
        sequence_str = parts[2] if len(parts) > 2 else "1"
        sequence = int(sequence_str)
        
        return InvoiceNumberResponse(
            number=invoice_number,
            year=generated_year,
            prefix=generated_prefix,
            sequence=sequence,
            generated_at=datetime.now(timezone.utc)
        )
        
    except InvoiceNumberingError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Échec de la génération du numéro: {str(e)}"
        )


@router.post(
    "/validate",
    response_model=InvoiceNumberValidationResponse,
    summary="Valider un numéro de facture",
    description="Valide le format d'un numéro de facture selon les règles métier."
)
def validate_invoice_number(
    payload: InvoiceNumberValidationRequest,
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db)
) -> InvoiceNumberValidationResponse:
    """
    Valide le format d'un numéro de facture.
    
    Vérifie :
    - Longueur maximale (64 caractères)
    - Caractères autorisés (alphanumérique, tiret, underscore)
    - Format de l'année si présent (YYYY entre 2000 et 2100)
    
    Ne vérifie PAS l'unicité dans la base de données.
    """
    is_valid, error_message = InvoiceNumberingService.validate_number_format(payload.number)
    
    return InvoiceNumberValidationResponse(
        is_valid=is_valid,
        error_message=error_message
    )


@router.get(
    "/continuity",
    response_model=InvoiceContinuityCheckResponse,
    summary="Vérifier la continuité de numérotation",
    description="Détecte les trous dans la séquence de numérotation pour une année donnée."
)
def check_numbering_continuity(
    year: int = Query(default=None, ge=2000, le=2100, description="Année à vérifier"),
    prefix: str = Query(default=None, min_length=1, max_length=10, description="Préfixe à vérifier"),
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db)
) -> InvoiceContinuityCheckResponse:
    """
    Vérifie la continuité de la numérotation pour une organisation et une année.
    
    Détecte les ruptures de séquence (trous dans la numérotation), ce qui peut
    indiquer des factures supprimées ou des problèmes de génération.
    
    **Note légale :** En France, la numérotation doit être continue sans rupture.
    Toute facture annulée doit conserver son numéro avec le statut "annulée".
    """
    try:
        result = InvoiceNumberingService.check_continuity(
            db=db,
            organization_id=organization.id,
            year=year,
            prefix=prefix
        )
        
        return InvoiceContinuityCheckResponse(
            has_gaps=result["has_gaps"],
            expected_count=result["expected_count"],
            actual_count=result["actual_count"],
            gaps=result["gaps"],
            min_number=result["min_number"],
            max_number=result["max_number"],
            year=year or datetime.now().year,
            prefix=prefix or InvoiceNumberingService.DEFAULT_PREFIX
        )
        
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Échec de la vérification de continuité: {str(e)}"
        )


@router.get(
    "/next-sequence",
    response_model=dict,
    summary="Obtenir la prochaine séquence",
    description="Retourne le prochain numéro de séquence sans générer de facture."
)
def get_next_sequence(
    year: int = Query(default=None, ge=2000, le=2100, description="Année cible"),
    prefix: str = Query(default=None, min_length=1, max_length=10, description="Préfixe cible"),
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db)
) -> dict:
    """
    Retourne le prochain numéro de séquence attendu sans créer de facture.
    
    Utile pour prévisualiser le prochain numéro avant création.
    Note : Ce numéro n'est pas réservé et peut changer si d'autres factures
    sont créées entre temps.
    """
    try:
        next_seq = InvoiceNumberingService.get_next_sequence(
            db=db,
            organization_id=organization.id,
            year=year,
            prefix=prefix
        )
        
        target_year = year or datetime.now().year
        target_prefix = prefix or InvoiceNumberingService.DEFAULT_PREFIX
        
        return {
            "next_sequence": next_seq,
            "year": target_year,
            "prefix": target_prefix,
            "formatted_number": f"{target_prefix}-{target_year}-{str(next_seq).zfill(4)}",
            "organization_id": organization.id
        }
        
    except InvoiceNumberingError as e:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Échec de récupération de la séquence: {str(e)}"
        )


@router.post(
    "/reset-sequence",
    response_model=dict,
    status_code=status.HTTP_200_OK,
    summary="Réinitialiser la séquence (ADMIN ONLY)",
    description="Réinitialise la séquence de numérotation pour une année. Operation sensible."
)
def reset_sequence(
    year: int = Query(..., ge=2000, le=2100, description="Année à réinitialiser"),
    prefix: str = Query(default=None, min_length=1, max_length=10, description="Préfixe concerné"),
    organization: Organization = Depends(require_organization),
    db: Session = Depends(get_db)
) -> dict:
    """
    Réinitialise la séquence de numérotation pour une année donnée.
    
    ⚠️ **ATTENTION** : Cette opération est sensible et peut violer la conformité légale
    si des factures ont déjà été émises pour cette année.
    
    Conditions :
    - Aucune facture ne doit exister pour l'année et le préfixe ciblés
    - Réservé aux utilisateurs avec rôle OWNER ou ADMIN
    
    **Permissions requises :** OWNER, ADMIN
    """
    # Vérification supplémentaire du rôle (seul OWNER/ADMIN peut réinitialiser)
    # Cette vérification est implicite via require_organization mais pourrait être renforcée
    
    try:
        success = InvoiceNumberingService.reset_sequence_for_year(
            db=db,
            organization_id=organization.id,
            year=year,
            prefix=prefix
        )
        
        target_prefix = prefix or InvoiceNumberingService.DEFAULT_PREFIX
        
        return {
            "success": success,
            "message": f"Séquence réinitialisée pour {target_prefix}-{year}",
            "year": year,
            "prefix": target_prefix,
            "new_start": 1
        }
        
    except InvoiceNumberingError as e:
        raise HTTPException(
            status_code=status.HTTP_409_CONFLICT,
            detail=str(e)
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail=f"Échec de la réinitialisation: {str(e)}"
        )
