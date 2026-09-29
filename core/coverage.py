"""
SynkDR Engine — Dominican Republic Delivery Coverage & Risk Knowledge
Based on official logistics coverage (GINTRACOM RD).

Contains:
1. Verified physical pickup agencies with real GPS Google Maps links.
2. Paused delivery zones (Punta Cana, Cap Cana, Bávaro, Verón, Friusa).
3. High-risk / restricted delivery sectors where couriers require meeting points.
"""

from typing import Optional, Tuple, Dict, List

# ═══════════════════════════════════════════════════════════════
# VERIFIED OFFICIAL PICKUP AGENCIES (GINTRACOM RD)
# Only offer these 100% verified real physical addresses.
# ═══════════════════════════════════════════════════════════════

PICKUP_AGENCIES = [
    {
        "id": "santo_domingo",
        "province": "Distrito Nacional / Santo Domingo",
        "city": "Santo Domingo",
        "name": "Agencia Santo Domingo (La Venta)",
        "address": "Calle Girasoles 3, Sector La Venta, Santo Domingo",
        "maps_url": "https://maps.app.goo.gl/j8htpEh6EDjc4Y4h6",
    },
    {
        "id": "santiago",
        "province": "Santiago",
        "city": "Santiago de los Caballeros",
        "name": "Agencia Santiago (Parque Logístico COBSA)",
        "address": "Parque Logístico COBSA Caribe, Nave industrial nro 4, La Peña, Santiago",
        "maps_url": "https://maps.app.goo.gl/AJpoaHDpnsUnC1PMA",
    },
    {
        "id": "higuey",
        "province": "La Altagracia",
        "city": "Higüey (Salvaleón de Higüey)",
        "name": "Agencia Higüey (Plaza La Zona)",
        "address": "Plaza La Zona, Calle José Adilio Santana, Higüey",
        "maps_url": "https://maps.app.goo.gl/QJFq4oFs9QjPCWkm9",
    },
    {
        "id": "punta_cana",
        "province": "La Altagracia",
        "city": "Punta Cana / Bávaro",
        "name": "Agencia Pueblo Bávaro",
        "address": "Pueblo Bávaro, Av. Circunvalación B",
        "maps_url": "https://maps.app.goo.gl/7SZZf3XjEj47cEWk6",
    },
]

# ═══════════════════════════════════════════════════════════════
# PAUSED DELIVERY ZONES (Delivery to door paused by courier)
# ═══════════════════════════════════════════════════════════════

PAUSED_ZONES = [
    "punta cana",
    "cap cana",
    "bavaro",
    "bávaro",
    "veron",
    "verón",
    "friusa",
]

# ═══════════════════════════════════════════════════════════════
# HIGH-RISK SECTORS (Couriers require meeting points)
# ═══════════════════════════════════════════════════════════════

HIGH_RISK_SECTORS: Dict[str, List[str]] = {
    "Santo Domingo": [
        "el capotillo", "capotillo", "gualey", "guachupita", 
        "los guandules", "villa francisca", "la 42"
    ],
    "Santiago": [
        "cien fuegos", "cienfuegos", "los ciruelitos", 
        "la piña", "la pina", "el elegido", "buenos aires"
    ],
    "Duarte": [
        "los jardines", "vista del valle", "madeja", "los espinolas", "los espínolas"
    ],
    "Espaillat": [
        "los lópez", "los lopez"
    ],
    "La Romana": [
        "cucuma", "camayusa", "villa progreso", "camajon", "camajón", "villa caoba"
    ],
    "La Altagracia": [
        "la otra banda", "santana", "el hoyo de friusa", "barrio nuevo"
    ],
    "La Vega": [
        "el tanque", "maría auxiliadora", "maria auxiliadora", "jima abajo"
    ],
    "Peravia": [
        "el limonal", "cañafito", "canafito"
    ],
    "Barahona": [
        "baitoa", "la delicia", "la raqueta", "la guasará", "la guasara"
    ],
    "Dajabón": [
        "los cartones", "la bomba", "barrio sur"
    ],
    "Hermanas Mirabal": [
        "el madero", "los mangos"
    ],
    "Hato Mayor": [
        "la china"
    ],
    "Monte Plata": [
        "bayaguana"
    ],
    "Puerto Plata": [
        "callejón 30 de marzo", "callejon 30 de marzo"
    ],
    "San Juan": [
        "la sanja", "la zanja", "el batey"
    ],
    "San Pedro de Macorís": [
        "quisqueya", "el socio", "ramón santana", "ramon santana", "cementerio santa fé", "cementerio santa fe"
    ],
    "Sánchez Ramírez": [
        "hernando alonso", "duey"
    ],
    "Valverde": [
        "canca la piedra", "compuerta", "la guarira"
    ],
}


def normalize_text(text: str) -> str:
    """Normalize lowercased text for search."""
    return (
        text.lower()
        .replace("á", "a")
        .replace("é", "e")
        .replace("í", "i")
        .replace("ó", "o")
        .replace("ú", "u")
        .replace("ñ", "n")
        .strip()
    )


def is_paused_zone(address_or_city: str) -> bool:
    """Check if the given address or city belongs to a paused delivery zone."""
    norm = normalize_text(address_or_city)
    return any(normalize_text(pz) in norm for pz in PAUSED_ZONES)


def check_high_risk_zone(address: str) -> Tuple[bool, Optional[str], Optional[str]]:
    """
    Check if the address contains a known high-risk sector.
    Returns: (is_high_risk, matched_sector, province)
    """
    norm = normalize_text(address)
    for province, sectors in HIGH_RISK_SECTORS.items():
        for sector in sectors:
            norm_sec = normalize_text(sector)
            if norm_sec in norm:
                return True, sector.title(), province
    return False, None, None


def get_pickup_agencies() -> List[Dict]:
    """Return all verified physical pickup agencies."""
    return PICKUP_AGENCIES


def get_agency_for_zone(zone_or_province: str) -> Optional[Dict]:
    """Return the closest pickup agency for a given province or zone."""
    norm = normalize_text(zone_or_province)
    if any(k in norm for k in ["bavaro", "punta cana", "veron", "cap cana", "friusa"]):
        return PICKUP_AGENCIES[3]  # Pueblo Bávaro
    if any(k in norm for k in ["higuey", "altagracia", "otra banda"]):
        return PICKUP_AGENCIES[2]  # Higüey
    if any(k in norm for k in ["santiago", "cibao", "licey", "tamboril", "moca", "puerto plata"]):
        return PICKUP_AGENCIES[1]  # Santiago
    if any(k in norm for k in ["santo domingo", "distrito", "dn", "haina", "san cristobal"]):
        return PICKUP_AGENCIES[0]  # Santo Domingo
    return None
