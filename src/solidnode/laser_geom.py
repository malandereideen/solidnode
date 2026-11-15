"""2D-Bausteine der Laser-Palette (Wandkoordinaten: x nach rechts, y nach
oben, mm). Formen und Muster folgen dem bausatzmaker (`geom.js`), damit
beide Werkzeuge gleich aussehen."""

from __future__ import annotations

import math
import random

from shapely.geometry import (LineString, MultiLineString, MultiPolygon,
                              Polygon, box)
from shapely.ops import unary_union

# Stein-/Rastermaße je Muster (Höhe h, Länge l) wie im bausatzmaker
MUSTER_MASS = {"backstein": (5, 10), "quader": (7, 14), "feldstein": (4.6, 6),
               "fischgrat": (3, 6), "bretter": (3, 24), "streifen": (12, 12),
               "fachwerk": (14, 16), "putz": (0, 0)}
MUSTER = list(MUSTER_MASS)
FORMEN = ["rechteck", "bogen", "spitz", "rund"]


def arch_poly(cx, y0, w, top, form="bogen"):
    """Umriss Rechteck/Rundbogen/Spitzbogen/Kreis, Unterkante y0."""
    if form == "rechteck":
        return [(cx - w / 2, y0), (cx + w / 2, y0), (cx + w / 2, top),
                (cx - w / 2, top)]
    if form == "rund":
        r = w / 2
        cy = y0 + r
        return [(cx + r * math.cos(2 * math.pi * i / 64),
                 cy + r * math.sin(2 * math.pi * i / 64)) for i in range(64)]
    R, h = w / 2, top - y0
    pts = [(cx - R, y0), (cx + R, y0)]
    if form == "spitz":
        rise = min(w * 0.866, h * 0.75)
        k, ys = rise / (w * 0.866), top - rise
        for i in range(17):
            th = (math.pi / 3) * (i / 16)
            pts.append((cx - R + w * math.cos(th), ys + k * w * math.sin(th)))
        for i in range(15, -1, -1):
            th = (math.pi / 3) * (i / 16)
            pts.append((cx + R - w * math.cos(th), ys + k * w * math.sin(th)))
        return pts
    rise = R if h >= R else h * 0.6
    ys = top - rise
    for i in range(33):
        th = math.pi * i / 32
        pts.append((cx + R * math.cos(th), ys + rise * math.sin(th)))
    return pts


def polys_of(geom):
    """shapely → [(außen, [löcher])] als Punktlisten."""
    if geom.is_empty:
        return []
    gs = geom.geoms if isinstance(geom, MultiPolygon) else [geom]
    out = []
    for g in gs:
        if isinstance(g, Polygon) and g.area > 1e-6:
            out.append((list(g.exterior.coords)[:-1],
                        [list(i.coords)[:-1] for i in g.interiors]))
    return out


def lines_of(geom):
    """shapely → [[(x, y), …]] offene Polylinien."""
    if geom.is_empty:
        return []
    if isinstance(geom, LineString):
        return [list(geom.coords)]
    if hasattr(geom, "geoms"):
        return [c for g in geom.geoms for c in lines_of(g)]
    if isinstance(geom, Polygon):
        return [list(geom.exterior.coords)]
    return []


def clip(lines, area):
    """Polylinien auf eine Fläche (shapely) beschneiden."""
    if not lines:
        return []
    ml = MultiLineString([ln for ln in lines if len(ln) >= 2])
    return [ln for ln in lines_of(ml.intersection(area))
            if LineString(ln).length > 0.05]


def _closed(p):
    return list(p) + [p[0]]


def pattern(typ, area, sh=None, sl=None, seed=1):
    """Gravurlinien des Musters in `area` (shapely Polygon)."""
    if typ == "putz" or area.is_empty:
        return []
    dh, dl = MUSTER_MASS.get(typ, MUSTER_MASS["backstein"])
    mh = sh if sh and sh > 0.5 else dh
    ml = sl if sl and sl > 0.5 else dl
    x0, y0, x1, y1 = area.bounds
    L = []
    if typ == "fachwerk":
        bw = 2.0
        y = y0
        while y < y1 + mh:
            L.append(_closed([(x0 - 1, y), (x1 + 1, y), (x1 + 1, y + bw),
                              (x0 - 1, y + bw)]))
            y += mh
        x, k = x0, 0
        while x < x1 + ml:
            L.append(_closed([(x, y0), (x + bw, y0), (x + bw, y1),
                              (x, y1)]))
            y, j = y0 + bw, 0
            while y < y1:
                if (k + j) % 3 == 0:
                    L.append([(x + bw, y), (x + ml, y + mh - bw)])
                    L.append([(x + bw, y + bw * 1.2),
                              (x + ml - bw * 1.2, y + mh - bw)])
                y += mh
                j += 1
            x += ml
            k += 1
    elif typ == "streifen":
        y, k = y0, 0
        while y < y1:
            L.append([(x0, y), (x1, y)])
            if k % 2:
                x = x0 - mh
                while x < x1:
                    L.append([(x, y), (x + mh, y + mh)])
                    x += 2.2
            y += mh
            k += 1
    elif typ == "bretter":
        y, k = y0 + mh, 0
        while y < y1 + mh:
            L.append([(x0, y), (x1, y)])
            x = x0 + (k % 3) * (ml / 3)
            while x < x1:
                L.append([(x, y - mh), (x, y)])
                x += ml
            y += mh
            k += 1
    elif typ == "fischgrat":
        a, y, k = mh, y0, 0
        while y < y1 + a:
            x = x0 - 2 * a
            while x < x1 + 2 * a:
                L.append([(x, y), (x + a, y + a), (x + 2 * a, y)])
                x += 2 * a
            if k % 2:
                x = x0 - a
                while x < x1 + 2 * a:
                    L.append([(x, y), (x, y + a)])
                    x += 2 * a
            y += a
            k += 1
    elif typ == "feldstein":
        R = random.Random(seed)
        y, k = y0, 0
        while y < y1 + mh:
            x = x0 - ml + (k % 2) * ml / 2
            while x < x1 + ml:
                cx = x + (R.random() - 0.5) * 1.4
                cy = y + (R.random() - 0.5) * 1.0
                rx = ml * (0.36 + R.random() * 0.1)
                ry = mh * (0.36 + R.random() * 0.1)
                pts = []
                for i in range(9):
                    th = i / 9 * 2 * math.pi
                    f = 0.85 + R.random() * 0.3
                    pts.append((cx + math.cos(th) * rx * f,
                                cy + math.sin(th) * ry * f))
                L.append(_closed(pts))
                x += ml
            y += mh
            k += 1
    else:                                       # backstein, quader
        y, k = y0 + mh, 0
        while y < y1 + mh:
            L.append([(x0, y), (x1, y)])
            x = x0 + (ml / 2 if k % 2 else 0)
            while x < x1:
                if x > x0 + 1e-6:
                    L.append([(x, y - mh), (x, y)])
                x += ml
            y += mh
            k += 1
    return clip(L, area)


def fries_shape(x0, x1, z0, h=6.0, p=6.0, form="bogen"):
    """Rundbogenfries: Band mit Bogenreihe darunter (eine Fläche)."""
    p, h = max(3.0, p), max(3.0, h)
    zt = z0 + h
    band = min(2.0, h * 0.3)
    leg = max(1.2, p * 0.22)
    n = max(1, round((x1 - x0) / p))
    pp = (x1 - x0) / n
    holes = [Polygon(arch_poly(x0 + pp * (i + 0.5), z0 - 1, pp - leg,
                               zt - band, "spitz" if form == "spitz"
                               else "bogen")) for i in range(n)]
    shape = box(x0, z0, x1, zt).difference(unary_union(holes))
    return shape


def zinnen_cuts(x0, x1, top, hp, breite=None):
    """Aussparungen der Zinnen an einer Mauerkrone (Rechtecke)."""
    zb = breite or max(4.0, hp)
    n = max(3, round((x1 - x0) / zb))
    if n % 2 == 0:
        n += 1
    w = (x1 - x0) / n
    return [(x0 + i * w, top - hp, x0 + (i + 1) * w, top + 1)
            for i in range(1, n, 2)]


def clock_lines(cx, cy, r):
    """Zifferblatt: Ring, zwölf Striche, zwei Zeiger (10 nach 10)."""
    ring = [(cx + r * 0.82 * math.cos(2 * math.pi * i / 48),
             cy + r * 0.82 * math.sin(2 * math.pi * i / 48))
            for i in range(49)]
    out = [ring]
    for i in range(12):
        a = 2 * math.pi * i / 12
        out.append([(cx + r * 0.62 * math.cos(a), cy + r * 0.62 * math.sin(a)),
                    (cx + r * 0.74 * math.cos(a), cy + r * 0.74 * math.sin(a))])
    for ang, ln in ((math.radians(90 - 300), 0.42),
                    (math.radians(90 - 60), 0.58)):
        out.append([(cx, cy), (cx + r * ln * math.cos(ang),
                               cy + r * ln * math.sin(ang))])
    return out
