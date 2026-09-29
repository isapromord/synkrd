"""
Unit tests for Dominican Republic coverage, paused zones, and high risk logic.
"""

from core.coverage import (
    is_paused_zone,
    check_high_risk_zone,
    get_agency_for_zone,
    PICKUP_AGENCIES,
)


def test_paused_zones_detection():
    assert is_paused_zone("Residencial en Punta Cana") is True
    assert is_paused_zone("Pueblo Bávaro") is True
    assert is_paused_zone("Cap Cana Marina") is True
    assert is_paused_zone("Verón centro") is True
    assert is_paused_zone("Santo Domingo Este") is False
    assert is_paused_zone("Santiago de los Caballeros") is False


def test_high_risk_zone_detection():
    is_risk, sector, prov = check_high_risk_zone("Calle 42 de Capotillo, Santo Domingo")
    assert is_risk is True
    assert "Capotillo" in sector
    assert prov == "Santo Domingo"

    is_risk_stgo, sector_stgo, prov_stgo = check_high_risk_zone("Sector Cienfuegos, Santiago")
    assert is_risk_stgo is True
    assert prov_stgo == "Santiago"

    is_safe, _, _ = check_high_risk_zone("Av. Winston Churchill, Piantini, Santo Domingo")
    assert is_safe is False


def test_pickup_agencies_consistency():
    assert len(PICKUP_AGENCIES) == 4
    # All agencies must have real URLs and physical addresses
    for ag in PICKUP_AGENCIES:
        assert ag["address"]
        assert "maps.app.goo.gl" in ag["maps_url"]

    # Agency lookup
    bavaro_ag = get_agency_for_zone("Punta Cana")
    assert bavaro_ag is not None
    assert "Bávaro" in bavaro_ag["name"]
