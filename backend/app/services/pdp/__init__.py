"""Couche d'abstraction PDP (Plateformes de Dématérialisation Partenaires).

Exposition publique :
- ``PDPAdapter``      : interface contractuelle (ABC) à implémenter par chaque PDP.
- ``PDPDocument``     : DTO document électronique transmis à une plateforme.
- ``TransmissionResult`` / ``LifecycleInfo`` : objets valeur normalisés.
- ``MockPDPAdapter``  : implémentation contractuelle de test (respecte le contrat).
- ``get_pdp_adapter`` : fabrique de l'adaptateur enregistré pour un fournisseur.
"""
from .chorus_pro import ChorusProAdapter
from .adapter import (
    LifecycleInfo,
    MockPDPAdapter,
    PDPAdapter,
    PDPDocument,
    PDPTransmissionError,
    TransmissionResult,
    get_pdp_adapter,
    register_pdp_adapter,
    registered_providers,
)

from . import chorus_pro as _chorus_pro  # noqa: F401 — enregistre 'chorus_pro' dans le registre

__all__ = [
    "LifecycleInfo",
    "MockPDPAdapter",
    "ChorusProAdapter",
    "PDPAdapter",
    "PDPDocument",
    "PDPTransmissionError",
    "TransmissionResult",
    "get_pdp_adapter",
    "register_pdp_adapter",
    "registered_providers",
]
