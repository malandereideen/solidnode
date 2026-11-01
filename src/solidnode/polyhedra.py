"""Polyeder-Nodes: Pyramiden, platonische, abgestumpfte und weitere
archimedische Körper.

Übertragen aus druckteil-cad/src/neu/polyeder.ts. Ein Körper ist eine
Eckenmenge; die Flächen liefert die konvexe Hülle. Abgestumpft wird mit dem
Schnitt, der aus jedem p-Eck ein regelmäßiges 2p-Eck macht (beim Würfel
1/(2+√2) statt pauschal 1/3), rektifiziert an den Kantenmitten.
"""

from __future__ import annotations

import math

import numpy as np

PHI = (1 + 5 ** 0.5) / 2
T = 1 + 2 ** 0.5


# ------------------------------------------------------------- Eckenmengen

def varianten(p, art="alle", vorzeichen="alle"):
    gerade = [(0, 1, 2), (1, 2, 0), (2, 0, 1)]
    ungerade = [(0, 2, 1), (2, 1, 0), (1, 0, 2)]
    tausch = {"gerade": gerade, "ungerade": ungerade}.get(art,
                                                          gerade + ungerade)
    out = []
    for t in tausch:
        for s in range(8):
            z = [-1 if s & (1 << k) else 1 for k in range(3)]
            minus = z.count(-1)
            if vorzeichen == "gerade" and minus % 2:
                continue
            if vorzeichen == "ungerade" and not minus % 2:
                continue
            out.append((p[t[0]] * z[0], p[t[1]] * z[1], p[t[2]] * z[2]))
    return entdoppelt(out)


def entdoppelt(punkte, tol=1e-9):
    out = []
    for p in punkte:
        if not any(math.dist(p, q) < tol for q in out):
            out.append(tuple(p))
    return out


TETRA = [(1, 1, 1), (1, -1, -1), (-1, 1, -1), (-1, -1, 1)]
HEXA = varianten((1, 1, 1))
OKTA = varianten((1, 0, 0))
IKOSA = varianten((0, 1, PHI), "gerade")
DODEKA = varianten((1, 1, 1)) + varianten((0, 1 / PHI, PHI), "gerade")


def kanten(ecken):
    """Ecken-Paare im kürzesten Abstand (die Kanten eines gleichmäßigen
    Körpers)."""
    e = np.asarray(ecken, float)
    d = np.linalg.norm(e[:, None] - e[None], axis=2)
    m = d[d > 1e-9].min()
    return [(i, j) for i in range(len(e)) for j in range(i + 1, len(e))
            if abs(d[i, j] - m) < 1e-6 * m]


def abgestumpft(ecken, p):
    """Jede Ecke abschneiden, so dass aus jedem p-Eck ein regelmäßiges 2p-Eck
    wird: Schnitt bei x = 1 / (2 + 2·sin(Innenwinkel/2))."""
    alpha = math.pi * (p - 2) / p
    x = 1 / (2 + 2 * math.sin(alpha / 2))
    e = np.asarray(ecken, float)
    out = []
    for i, j in kanten(ecken):
        out.append(tuple(e[i] + (e[j] - e[i]) * x))
        out.append(tuple(e[j] + (e[i] - e[j]) * x))
    return out


def rektifiziert(ecken):
    e = np.asarray(ecken, float)
    return [tuple((e[i] + e[j]) / 2) for i, j in kanten(ecken)]


def tribonacci():
    x = 1.8
    for _ in range(60):
        x = (x * x + x + 1) ** (1 / 3)
    return x


def abgeschraegtes_dodekaeder():
    """Eine Ecke setzen, die Drehgruppe des Ikosaeders darauf loslassen
    (siehe polyeder.ts); es müssen genau 60 Ecken herauskommen."""
    xi = 1.0
    for _ in range(80):
        xi = PHI / math.sqrt(xi + 2)
    p = (PHI ** 2 - PHI ** 2 * xi, -PHI ** 3 + PHI * xi + 2 * PHI * xi * xi,
         xi)
    h, g = PHI / 2, 1 / (2 * PHI)

    def m1(v):
        return (g * v[0] - h * v[1] + 0.5 * v[2],
                h * v[0] + 0.5 * v[1] + g * v[2],
                -0.5 * v[0] + g * v[1] + h * v[2])

    def m2(v):
        return (v[2], v[0], v[1])

    ecken, offen = [], [p]
    while offen and len(ecken) <= 60:
        v = offen.pop()
        if any(math.dist(v, q) < 1e-7 for q in ecken):
            continue
        ecken.append(v)
        offen += [m1(v), m2(v)]
    if len(ecken) != 60:
        raise ValueError("Abgeschrägtes Dodekaeder: Bahn falsch")
    return ecken


def ring(n, r=1.0, z=0.0, versatz=0.0):
    return [(r * math.cos(2 * math.pi * (i + versatz) / n),
             r * math.sin(2 * math.pi * (i + versatz) / n), z)
            for i in range(n)]


def pyramide(n, d, h):
    return ring(n, d / 2) + [(0, 0, h)]


def bipyramide(n, d, h):
    return ring(n, d / 2) + [(0, 0, h / 2), (0, 0, -h / 2)]


def antiprisma(n, d):
    r = d / 2
    s = 2 * r * math.sin(math.pi / n)
    h = math.sqrt(max(1e-4, s * s - 4 * r * r
                      * math.sin(math.pi / (2 * n)) ** 2))
    return ring(n, r, -h / 2) + ring(n, r, h / 2, 0.5)


# ----------------------------------------------------------- Konvexe Hülle

def huelle(ecken, tol=1e-6):
    """Flächen einer konvexen Eckenmenge: Ebene durch drei Ecken, auf deren
    einer Seite alle anderen liegen. Liefert Ringe gegen den Uhrzeigersinn
    von außen gesehen."""
    e = np.asarray(ecken, float)
    n = len(e)
    c = e.mean(axis=0)
    scale = np.linalg.norm(e - c, axis=1).max()
    d = np.linalg.norm(e[:, None] - e[None], axis=2)
    if n <= 30:
        nah = [list(range(n))] * n
    else:
        m = d[d > 1e-9].min()
        nah = [[j for j in range(n) if 0 < d[i, j] <= m * 2.05]
               for i in range(n)]
    planes = {}
    for i in range(n):
        for j in nah[i]:
            if j <= i:
                continue
            for k in nah[i]:
                if k <= j:
                    continue
                nrm = np.cross(e[j] - e[i], e[k] - e[i])
                ln = np.linalg.norm(nrm)
                if ln < tol * scale * scale:
                    continue
                nrm /= ln
                off = nrm @ e[i]
                side = e @ nrm - off
                if (side > tol * scale).any():
                    if (side < -tol * scale).any():
                        continue
                    nrm, off, side = -nrm, -off, -side
                key = tuple(np.round(np.append(nrm, off / scale), 5))
                if key in planes:
                    continue
                on = np.where(np.abs(side) <= tol * scale)[0]
                planes[key] = (nrm, on)
    faces = []
    for nrm, on in planes.values():
        pts = e[on]
        fc = pts.mean(axis=0)
        u = pts[0] - fc
        u /= np.linalg.norm(u)
        v = np.cross(nrm, u)
        ang = np.arctan2((pts - fc) @ v, (pts - fc) @ u)
        faces.append([int(on[k]) for k in np.argsort(ang)])
    return faces


def solid(ecken, faces):
    """Ecken + Flächenringe zu einem geschlossenen OCC-Körper nähen."""
    from OCP.BRepBuilderAPI import (BRepBuilderAPI_MakeFace,
                                    BRepBuilderAPI_MakePolygon,
                                    BRepBuilderAPI_MakeSolid,
                                    BRepBuilderAPI_Sewing)
    from OCP.ShapeFix import ShapeFix_Solid
    from OCP.TopoDS import TopoDS
    from OCP.gp import gp_Pnt
    sew = BRepBuilderAPI_Sewing(1e-6)
    for f in faces:
        poly = BRepBuilderAPI_MakePolygon()
        for i in f:
            poly.Add(gp_Pnt(*map(float, ecken[i])))
        poly.Close()
        sew.Add(BRepBuilderAPI_MakeFace(poly.Wire(), True).Face())
    sew.Perform()
    shell = TopoDS.Shell_s(sew.SewedShape())
    sol = BRepBuilderAPI_MakeSolid(shell).Solid()
    fix = ShapeFix_Solid(sol)
    fix.Perform()
    return fix.Solid()


# --------------------------------------------------------------- Katalog

# Name, Symbolklasse, Eckenfunktion (ohne Maße), Erwartete Flächenzahl
UNIFORM = [
    ("Tetraeder", "Platonisch", lambda: TETRA, 4),
    ("Hexaeder", "Platonisch", lambda: HEXA, 6),
    ("Oktaeder", "Platonisch", lambda: OKTA, 8),
    ("Dodekaeder", "Platonisch", lambda: DODEKA, 12),
    ("Ikosaeder", "Platonisch", lambda: IKOSA, 20),
    ("Tetraederstumpf", "Stumpf", lambda: abgestumpft(TETRA, 3), 8),
    ("Würfelstumpf", "Stumpf", lambda: abgestumpft(HEXA, 4), 14),
    ("Oktaederstumpf", "Stumpf", lambda: abgestumpft(OKTA, 3), 14),
    ("Dodekaederstumpf", "Stumpf", lambda: abgestumpft(DODEKA, 5), 32),
    ("Ikosaederstumpf", "Stumpf", lambda: abgestumpft(IKOSA, 3), 32),
    ("Kuboktaeder", "Archimedisch", lambda: rektifiziert(HEXA), 14),
    ("Ikosidodekaeder", "Archimedisch", lambda: rektifiziert(IKOSA), 32),
    ("Rhombenkuboktaeder", "Archimedisch",
     lambda: varianten((1, 1, T)), 26),
    ("Großes Rhombenkuboktaeder", "Archimedisch",
     lambda: varianten((1, T, 1 + 2 * 2 ** 0.5)), 26),
    ("Rhombenikosidodekaeder", "Archimedisch",
     lambda: entdoppelt(varianten((1, 1, PHI ** 3), "gerade")
                        + varianten((PHI ** 2, PHI, 2 * PHI), "gerade")
                        + varianten((2 + PHI, 0, PHI ** 2), "gerade")), 62),
    ("Großes Rhombenikosidodekaeder", "Archimedisch",
     lambda: entdoppelt(
         varianten((1 / PHI, 1 / PHI, 3 + PHI), "gerade")
         + varianten((2 / PHI, PHI, 1 + 2 * PHI), "gerade")
         + varianten((1 / PHI, PHI ** 2, -1 + 3 * PHI), "gerade")
         + varianten((2 * PHI - 1, 2, 2 + PHI), "gerade")
         + varianten((PHI, 3, 2 * PHI), "gerade")), 62),
    ("Abgeschrägter Würfel", "Archimedisch",
     lambda: varianten((1, 1 / tribonacci(), tribonacci()), "gerade",
                       "gerade")
     + varianten((1, 1 / tribonacci(), tribonacci()), "ungerade",
                 "ungerade"), 38),
    ("Abgeschrägtes Dodekaeder", "Archimedisch", abgeschraegtes_dodekaeder,
     92),
]


def normiert(ecken, d, mitte):
    """Auf Durchmesser über Ecken `d` bringen, Mittelpunkt auf `mitte`."""
    e = np.asarray(ecken, float)
    e -= e.mean(axis=0)
    e *= d / 2 / np.linalg.norm(e, axis=1).max()
    return e + np.asarray(mitte, float)


def icon_lines(ecken, faces):
    """Kanten in Schrägansicht, auf [0, 1]² gebracht — fürs Paletten-Icon."""
    e = np.asarray(ecken, float)
    e = e - e.mean(axis=0)
    a, b = math.radians(35), math.radians(-30)
    rz = np.array([[math.cos(b), -math.sin(b), 0],
                   [math.sin(b), math.cos(b), 0], [0, 0, 1]])
    rx = np.array([[1, 0, 0], [0, math.cos(a), -math.sin(a)],
                   [0, math.sin(a), math.cos(a)]])
    p = e @ rz.T @ rx.T
    xy = p[:, [0, 2]] * [1, -1]
    lo, hi = xy.min(axis=0), xy.max(axis=0)
    xy = (xy - (lo + hi) / 2) / (hi - lo).max() + 0.5
    seen, lines = set(), []
    for f in faces:
        for k in range(len(f)):
            i, j = f[k], f[(k + 1) % len(f)]
            key = (min(i, j), max(i, j))
            if key in seen:
                continue
            seen.add(key)
            front = (p[i, 1] + p[j, 1]) / 2 < 0
            lines.append((tuple(xy[i]), tuple(xy[j]), front))
    return lines


def make_nodes(SerpNode):
    out = []

    def uniform_node(name, gruppe, ecken_fn, n_faces):
        base = ecken_fn()
        faces0 = huelle(base)

        class N(SerpNode):
            __identifier__ = "serp." + gruppe
            NODE_NAME = name
            FACES = n_faces
            INPUTS = [("mitte", "pt", "0 0 0", False),
                      ("durchmesser", "num", 40, False)]
            OUTPUTS = ["form"]
            ICON_LINES = icon_lines(base, faces0)

            def solve(self, mitte, durchmesser):
                return solid(normiert(base, durchmesser, mitte), faces0)

        N.__name__ = "Poly_" + "".join(ch for ch in name if ch.isalnum())
        N.__doc__ = f"{name}: {n_faces} Flächen, Ø über die Ecken."
        return N

    pyr = []

    def pyr_node(cls_name, name, ecken_fn, inputs, preview):
        pv = preview()

        class N(SerpNode):
            __identifier__ = "serp.Pyramiden"
            NODE_NAME = name
            INPUTS = [("mitte", "pt", "0 0 0", False)] + inputs
            OUTPUTS = ["form"]
            ICON_LINES = icon_lines(pv, huelle(pv))

            def solve(self, mitte, **kw):
                e = np.asarray(ecken_fn(**kw), float) + np.asarray(mitte)
                return solid(e, huelle(e))

        N.__name__ = cls_name
        return N

    pyr.append(pyr_node(
        "Poly_Pyramide4", "Pyramide, vierseitig",
        lambda durchmesser, hoehe: pyramide(4, durchmesser, hoehe),
        [("durchmesser", "num", 40, False), ("hoehe", "num", 30, False)],
        lambda: pyramide(4, 2, 1.4)))
    pyr.append(pyr_node(
        "Poly_Pyramide3", "Pyramide, dreiseitig",
        lambda durchmesser, hoehe: pyramide(3, durchmesser, hoehe),
        [("durchmesser", "num", 40, False), ("hoehe", "num", 30, False)],
        lambda: pyramide(3, 2, 1.4)))
    pyr.append(pyr_node(
        "Poly_Bipyramide", "Bipyramide",
        lambda durchmesser, hoehe, seiten: bipyramide(max(3, seiten),
                                                      durchmesser, hoehe),
        [("durchmesser", "num", 40, False), ("hoehe", "num", 40, False),
         ("seiten", "int", 5, False)],
        lambda: bipyramide(5, 2, 2)))
    pyr.append(pyr_node(
        "Poly_Antiprisma", "Antiprisma",
        lambda durchmesser, seiten: antiprisma(max(3, seiten), durchmesser),
        [("durchmesser", "num", 40, False), ("seiten", "int", 6, False)],
        lambda: antiprisma(6, 2)))
    return pyr + [uniform_node(*spec) for spec in UNIFORM]
