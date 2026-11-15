"""LoD2-Auswertung ohne Netz: Satteldachhaus aus Flächen."""

import math

from solidnode import laser_lod2 as L2


def _haus(B=12.0, T=8.0, H=6.0, a=45, drehen=0.0):
    r = math.radians(drehen)
    rot = lambda x, y, z: [x * math.cos(r) - y * math.sin(r),  # noqa: E731
                           x * math.sin(r) + y * math.cos(r), z]
    zr = H + T / 2 * math.tan(math.radians(a))
    ground = [[rot(0, 0, 0), rot(B, 0, 0), rot(B, T, 0), rot(0, T, 0),
               rot(0, 0, 0)]]
    roofs = [[rot(0, 0, H), rot(B, 0, H), rot(B, T / 2, zr), rot(0, T / 2, zr)],
             [rot(B, T, H), rot(0, T, H), rot(0, T / 2, zr), rot(B, T / 2, zr)]]
    return {"parts": [{"roofType": "3100", "h": zr, "ground": ground,
                       "roofs": roofs, "walls": []}]}


def test_satteldach_masse_und_massstab():
    for drehen in (0, 30, 90):
        parts, _ = L2.analyse(_haus(drehen=drehen))
        p = parts[0]
        assert p["dach"] == "sattel" and p["first_x"]
        assert abs(p["laenge"] - 12) < 0.05 and abs(p["tiefe"] - 8) < 0.05
        assert abs(p["traufe"] - 6) < 0.05 and abs(p["neigung"] - 45) < 1
        e = L2.to_elements(parts, 100)[0]
        assert (e["breite"], e["tiefe"], e["hoehe"]) == (120, 80, 60)


def test_gesamtmass_und_passender_massstab():
    parts, _ = L2.analyse(_haus())
    L, T, H = L2.gesamt(parts, 100)
    assert abs(L - 120) < 0.5 and abs(T - 80) < 0.5
    assert abs(H - (60 + 40)) < 0.5                 # First 6 m + 4 m
    assert L2.passend(parts, 240) == 50             # 12 m → 240 mm
