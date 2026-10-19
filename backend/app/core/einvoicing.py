"""Sémantique EN 16931 : unités, codes taxes et catégories de notes.

Références :
- BR-08 : l'unité de la ligne doit figurer dans la liste UNECE Rec 20
- UNTDID 5305 : codes taxe TVA (category codes)
- Factur-X / Cross Industry Invoice (UN/CEFACT CII D16B)
"""
from __future__ import annotations

from decimal import Decimal

# ---------------------------------------------------------------------------
# Unités UNECE Recommandation 20 (sous-ensemble usuel pour la facturation)
# ---------------------------------------------------------------------------

# Mapping interne (models.InvoiceLine.unit) -> code UNECE Rec 20
UNIT_TO_UNECE: dict[str, str] = {
    "unit": "H87",   # pièce / unité
    "piece": "H87",
    "hour": "HUR",   # heure
    "day": "DAY",    # jour
    "week": "WEE",
    "month": "MON",  # mois
    "year": "ANN",
    "kg": "KGM",
    "g": "GRM",
    "tonne": "TNE",
    "m": "MTR",
    "cm": "CMT",
    "km": "KMK",
    "m2": "MTK",
    "m3": "MTQ",
    "l": "LTR",
    "package": "XPK",
    "service": "SAD",  # service à distance
    "lot": "XLT",
    "set": "SET",
}

_VALID_UNECE_UNITS: set[str] = set(UNIT_TO_UNECE.values())


def to_unece_unit(unit: str | None) -> str:
    """Convertit une unité interne en code UNECE Rec 20.

    Une valeur déjà conforme (code 2-3 caractères majuscules) est passée
    telle quelle ; sinon repli sur H87 (unité).
    """
    if not unit:
        return "H87"
    normalized = UNIT_TO_UNECE.get(unit.lower().strip())
    if normalized:
        return normalized
    candidate = unit.strip().upper()
    if candidate in _VALID_UNECE_UNITS:
        return candidate
    return "H87"


# ---------------------------------------------------------------------------
# Codes catégorie TVA — UNTDID 5305 (profil Factur-X / EN 16931)
# ---------------------------------------------------------------------------

TAX_CATEGORY_VAT = "VAT"      # TVA normale applicable
TAX_CATEGORY_AE = "AE"        # Reverse charge (autoliquidation, art. 28c DIR 2006/112/CE)
TAX_CATEGORY_ZE = "ZE"        # Exonération zero-rated
TAX_CATEGORY_E = "E"          # Exempt (autres motifs)
TAX_CATEGORY_S = "S"          # Régime particulier marge
TAX_CATEGORY_O = "O"          # Hors champ TVA
TAX_CATEGORY_K = "K"          # Exonération intracommunautaire
TAX_CATEGORY_G = "G"          # Non assujetti (export hors UE hors IC)

_FRENCH_VAT_EXEMPTION_REASONS: dict[str, tuple[str, str]] = {
    # category -> (libellé français, code motif simplifié Factur-X)
    TAX_CATEGORY_AE: ("Autoliquidation - TVA due par l'acheteur", "VAE"),
    TAX_CATEGORY_ZE: ("Exonération de TVA", "ZRO"),
    TAX_CATEGORY_E: ("Exempté", "EXM"),
    TAX_CATEGORY_K: ("Exonération intracommunautaire", "ICT"),
    TAX_CATEGORY_G: ("Franchise - export hors Union européenne", "EXP"),
}


def tax_category_for_rate(tax_rate: Decimal, buyer_in_other_country: bool = False) -> str:
    """Déduit la catégorie TVA d'un taux (BR-CO-04 : taux 0 => motif obligatoire).

    - taux > 0  -> VAT
    - taux == 0 -> AE si reverse charge implicite (non utilisé ici), sinon ZE
    """
    if tax_rate and tax_rate > 0:
        return TAX_CATEGORY_VAT
    return TAX_CATEGORY_ZE


def tax_exemption_reason(category: str) -> tuple[str, str] | None:
    """Retourne (libellé, code_simplifié) pour les catégories à taux nul."""
    return _FRENCH_VAT_EXEMPTION_REASONS.get(category)


# ---------------------------------------------------------------------------
# Codes document Factur-X (cross-industry invoice types, UNTDID 1001)
# ---------------------------------------------------------------------------

DOC_TYPE_INVOICE = "380"        # Facture
DOC_TYPE_CREDIT_NOTE = "381"    # Avoir
DOC_TYPE_PROFORMA = "325"

# Profil de syntaxe Factur-X
PROFILE_COMFORT = "urn:factur-x:pdfa:CrossIndustryDocument:invoice:1p0#comfort"
DOCUMENT_NAME = "Factur-X Interpretation profile name"
CONFORMANCE_LEVEL = "PDF/A-3B"
