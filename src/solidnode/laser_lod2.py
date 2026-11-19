"""LoD2 für die Laser-Palette: Adresse → amtliches 3D-Gebäudemodell →
Grundmaße im Maßstab.

Den Abruf (Kacheln aller 16 Länder, Cache) teilt sich das mit dem
bausatzmaker: `~/thebrain/bausatzmaker/lod2/lod2.py` (außerhalb
Deutschlands `osm.py`, Grundrisse aus OpenStreetMap). Die Auswertung je
Gebäudeteil folgt `stadtmodell.js` (partsToBodies): Hauptrichtung,
Rechteck, Traufe, First, Dachform, Neigung, Firstrichtung.
"""

from __future__ import annotations

import json
import math
import os
import subprocess
import sys
import urllib.parse

LOD2_DIR = os.environ.get("SOLIDNODE_LOD2",
                          os.path.expanduser("~/thebrain/bausatzmaker/lod2"))
ROOF = {"1000": "flach", "2100": "pult", "2200": "pult", "3100": "sattel",
        "3200": "walm", "3300": "walm", "3400": "sattel", "3500": "walm",
        "3600": "kegel", "3700": "kegel", "3800": "sattel", "3900": "sattel"}
MASSSTAEBE = [(22.5, "G"), (32, "Spur 1"), (45, "Spur 0"), (50, ""),
              (64, "S"), (87, "H0"), (100, ""), (120, "TT"), (160, "N"),
              (200, ""), (220, "Z"), (250, ""), (300, ""), (500, ""),
              (1000, "")]


def gesamt(parts, massstab):
    """Gesamtmaße des Gebäudes am Modell (Länge, Tiefe, Höhe in mm)."""
    k = 1000.0 / massstab
    return ((max(p["x1"] for p in parts) - min(p["x0"] for p in parts)) * k,
            (max(p["y1"] for p in parts) - min(p["y0"] for p in parts)) * k,
            (max(p["top"] for p in parts) - min(p["z0"] for p in parts)) * k)


def passend(parts, laengste_mm):
    """Maßstab, bei dem die längste Gebäudeseite `laengste_mm` lang wird
    (auf ganze Zahl gerundet)."""
    g = gesamt(parts, 1000.0)               # 1:1000 → mm = Meter
    return max(1, round(max(g) * 1000.0 / laengste_mm))


def _mods():
    if LOD2_DIR not in sys.path:
        sys.path.insert(0, LOD2_DIR)
    import lod2                                      # noqa: PLC0415
    import osm                                       # noqa: PLC0415
    return lod2, osm


def geocode(q):
    """Adresse → dict(lat, lon, land, de, name) über Nominatim."""
    url = ("https://nominatim.openstreetmap.org/search?format=jsonv2&"
           "addressdetails=1&limit=1&accept-language=de&q="
           + urllib.parse.quote(q))
    r = subprocess.run(["curl", "-sfL", "--max-time", "20", "-A",
                        "solidnode-laser/1.0", url], capture_output=True)
    if r.returncode:
        raise RuntimeError("Adresssuche nicht erreichbar")
    d = json.loads(r.stdout or b"[]")
    if not d:
        raise RuntimeError("Adresse nicht gefunden")
    a = d[0].get("address", {})
    return {"lat": float(d[0]["lat"]), "lon": float(d[0]["lon"]),
            "land": a.get("state", ""), "de": a.get("country_code") == "de",
            "name": d[0].get("display_name", q)}


def buildings(place, r=80):
    """Gebäude im Umkreis (Meter relativ zum Punkt, x Ost, y Nord)."""
    lod2, osm = _mods()
    if place["de"] and place["land"] in lod2.LAND:
        d = lod2.query(place["lat"], place["lon"], place["land"], r)
        d["quelle"] = "lod2"
    else:
        d = osm.query(place["lat"], place["lon"], r)
    return d


# -------------------------------------------------------- Auswertung

def _rot(q, a):
    c, s = math.cos(a), math.sin(a)
    return (q[0] * c + q[1] * s, -q[0] * s + q[1] * c, q[2] if len(q) > 2
            else 0.0)


def _area2(g):
    return sum(g[i][0] * g[(i + 1) % len(g)][1]
               - g[(i + 1) % len(g)][0] * g[i][1] for i in range(len(g)))


def _normal(g):
    nx = ny = nz = 0.0
    for i in range(len(g)):
        a, b = g[i], g[(i + 1) % len(g)]
        nx += (a[1] - b[1]) * (a[2] + b[2])
        ny += (a[2] - b[2]) * (a[0] + b[0])
        nz += (a[0] - b[0]) * (a[1] + b[1])
    ln = math.sqrt(nx * nx + ny * ny + nz * nz) or 1.0
    return (nx / ln, ny / ln, nz / ln), ln / 2


def _foot(p):
    if p["ground"]:
        return p["ground"]
    return [[(q[0], q[1], 0.0) for q in g] for g in p["roofs"]]


def main_angle(parts):
    """Richtung der längsten Grundrisskante (0…90°)."""
    best, bl = 0.0, 0.0
    for p in parts:
        for g in _foot(p):
            for i in range(len(g) - 1):
                dx, dy = g[i + 1][0] - g[i][0], g[i + 1][1] - g[i][1]
                ln = math.hypot(dx, dy)
                if ln > bl:
                    bl, best = ln, math.atan2(dy, dx)
    return best % (math.pi / 2)


def analyse(building):
    """Gebäudeteile → Maße in Metern. Gedreht so, dass der First des
    größten Teils in x läuft (das Haus-Element hat den First längs)."""
    out, ang = _analyse(building["parts"], main_angle(building["parts"]))
    if out:
        main = max(out, key=lambda p: p["laenge"] * p["tiefe"])
        if not main["first_x"] and main["dach"] != "flach":
            out, ang = _analyse(building["parts"], ang + math.pi / 2)
    return out, ang


def _analyse(parts, ang):
    out = []
    for p in parts:
        fp = [[_rot(q, ang) for q in g] for g in _foot(p)]
        roofs = [[_rot(q, ang) for q in g] for g in p.get("roofs", [])]
        pts = [q for g in fp for q in g]
        if not pts:
            continue
        xs, ys = [q[0] for q in pts], [q[1] for q in pts]
        x0, x1, y0, y1 = min(xs), max(xs), min(ys), max(ys)
        zs = [q[2] for g in p["ground"] + p.get("walls", []) for q in g]
        z0 = min(zs) if zs else 0.0
        rn = []
        for g in roofs:
            if len(g) >= 3:
                n, a = _normal(g)
                rn.append((n, a, min(q[2] for q in g), max(q[2] for q in g)))
        slopes = [r for r in rn if math.cos(math.radians(80)) < abs(r[0][2])
                  < math.cos(math.radians(8))]   # keine Senkrechten
        rz = [q[2] for g in roofs for q in g]
        osm_ = not roofs and p.get("eave") is not None
        top = max(rz) if rz else (p["top"] if osm_ else z0 + (p.get("h") or 10))
        # Traufe: unterste Dachkante — aber Dachflächen, die bis fast zum
        # Boden reichen (Artefakte, Durchfahrten), zählen nicht mit.
        hoch = [r for r in slopes if r[2] >= z0 + 0.25 * (top - z0)]
        eave = (min(r[2] for r in (hoch or slopes)) if slopes else
                (p["eave"] if osm_ else top))
        typ = ROOF.get(str(p.get("roofType") or "")) or (
            "flach" if not slopes else "pult" if len(slopes) == 1 else
            "sattel" if len(slopes) == 2 else "walm")
        if not slopes and not osm_:
            typ = "flach"
        A = sum(r[1] for r in slopes) or 1.0
        pitch = (sum(r[1] * math.degrees(math.acos(min(1, abs(r[0][2]))))
                     for r in slopes) / A if slopes else
                 (p.get("pitch") or 45 if osm_ else 45))
        ny = sum(r[1] * abs(r[0][1]) for r in slopes)
        nx = sum(r[1] * abs(r[0][0]) for r in slopes)
        if osm_:
            ny, nx = (1, 0) if x1 - x0 >= y1 - y0 else (0, 1)
        first_x = ny >= nx                      # First läuft in x
        out.append({"x0": x0, "x1": x1, "y0": y0, "y1": y1, "z0": z0,
                    "eave": eave, "top": top, "dach": typ,
                    "neigung": pitch, "first_x": first_x,
                    "laenge": x1 - x0, "tiefe": y1 - y0,
                    "traufe": eave - z0, "firsthoehe": top - z0})
    return out, ang


def to_elements(parts, massstab):
    """Gebäudeteile → Haus-Parameter (mm am Modell, First längs Breite)."""
    k = 1000.0 / massstab
    r1 = lambda v: round(v * k * 2) / 2              # noqa: E731
    X0 = min(p["x0"] for p in parts)
    Y0 = min(p["y0"] for p in parts)
    Z0 = min(p["z0"] for p in parts)
    out = []
    for p in parts:
        dach = p["dach"] if p["dach"] in ("sattel", "pult", "walm",
                                          "flach") else "walm"
        B, T = p["laenge"], p["tiefe"]
        x, y = p["x0"] - X0, p["y0"] - Y0
        quer = not p["first_x"] and dach not in ("flach",)
        out.append({"dach": dach, "breite": max(5.0, r1(B)),
                    "tiefe": max(5.0, r1(T)),
                    "hoehe": max(5.0, r1(p["traufe"])),
                    "neigung": max(10, min(75, round(p["neigung"] / 5) * 5)),
                    "x": r1(x), "y": r1(y), "z": r1(p["z0"] - Z0),
                    "quer": quer})
    return out
