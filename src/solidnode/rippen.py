"""Rippen-Relief: parametrische Rippenobjekte (Wanduhren, Paneele) planen.

Reine numpy-Rechnung ohne OCC: Umriss und Fenster als Polygone, daraus die
Lage jeder Rippe und ihr Höhenprofil. Die Node in ``fabrication`` baut aus
dem Plan die Körper und die flachen Teile für den Laser.

Aufbau: eine Grundplatte (zugleich das Zifferblatt im Fenster), darauf
stehende Rippen der Stärke t. Jede Rippe hat unten Zapfen, die in Schlitze
der Grundplatte greifen und hinten bündig abschließen.
"""

from __future__ import annotations

import math

import numpy as np

FORMEN = ["Kiesel", "Kreis", "Tropfen", "Sechseck", "Dreieck rund",
          "Quadrat rund"]
HOEHEN = ["Rand zum Fenster", "Krater", "Trichter", "Welle", "Ringwellen",
          "Sattel", "Zwei Hügel", "Eigene Formel"]
FORMEL_NS = {k: getattr(math, k) for k in (
    "sin", "cos", "tan", "atan2", "sqrt", "exp", "log", "pi", "fabs")}
FORMEL_NS.update(abs=abs, min=min, max=max)


# ------------------------------------------------------------------ Formen

def form(name, groesse, n=360):
    """Umriss als Polygon (n×2), längste Ausdehnung = groesse, Mitte 0."""
    th = np.linspace(0, 2 * np.pi, n, endpoint=False)
    if name == "Kreis":
        r = np.ones_like(th)
    elif name == "Kiesel":            # breites, weich gerundetes Dreieck
        a = np.pi / 3
        r = np.cos(a) / np.cos(((th - np.pi / 2) % (2 * a)) - a)
        r = r * 0.5 + 0.5
    elif name == "Tropfen":
        r = 1 + 0.45 * np.cos(th - np.pi / 2) ** 9 * (np.sin(th) > 0) \
            - 0.12 * np.sin(th)
    elif name in ("Sechseck", "Dreieck rund", "Quadrat rund"):
        k = {"Sechseck": 6, "Dreieck rund": 3, "Quadrat rund": 4}[name]
        rund = {"Sechseck": 0.02, "Dreieck rund": 0.12, "Quadrat rund": 0.1}[name]
        a = np.pi / k
        phase = np.pi / 2 if k == 3 else (a if k == 4 else 0)
        r = np.cos(a) / np.cos(((th - phase) % (2 * a)) - a)
        r = r * (1 - rund) + rund                     # Ecken abrunden
    else:
        raise ValueError(f"Unbekannte Form {name}")
    pts = np.c_[r * np.cos(th), r * np.sin(th)]
    if name == "Kiesel":
        pts[:, 0] *= 1.55                              # breiter als hoch
        pts[:, 0] -= 0.15 * (pts[:, 1] - pts[:, 1].min())   # Spitze schief
    pts -= (pts.max(0) + pts.min(0)) / 2
    return pts * groesse / (pts.max(0) - pts.min(0)).max()


def area_centroid(P):
    x, y = P[:, 0], P[:, 1]
    x1, y1 = np.roll(x, -1), np.roll(y, -1)
    c = x * y1 - x1 * y
    A = c.sum() / 2
    return np.array([((x + x1) * c).sum(), ((y + y1) * c).sum()]) / (6 * A)


# --------------------------------------------------------------- Schnitte

def ray_hits(P, o, d):
    """Abstände t > 0, an denen der Strahl o + t·d das Polygon P schneidet."""
    A, B = P, np.roll(P, -1, axis=0)
    e = B - A
    den = d[0] * e[:, 1] - d[1] * e[:, 0]
    ok = np.abs(den) > 1e-12
    w = A - o
    t = np.where(ok, (w[:, 0] * e[:, 1] - w[:, 1] * e[:, 0]) / np.where(ok, den, 1), -1)
    s = np.where(ok, (w[:, 0] * d[1] - w[:, 1] * d[0]) / np.where(ok, den, 1), -1)
    m = ok & (s >= 0) & (s < 1) & (t > 1e-9)
    return np.sort(t[m])


def line_intervals(P, o, d):
    """Abschnitte [a, b] der Geraden o + s·d innerhalb von P (gerade/ungerade)."""
    A, B = P, np.roll(P, -1, axis=0)
    e = B - A
    den = d[0] * e[:, 1] - d[1] * e[:, 0]
    ok = np.abs(den) > 1e-12
    w = A - o
    t = (w[:, 0] * e[:, 1] - w[:, 1] * e[:, 0]) / np.where(ok, den, 1)
    s = (w[:, 0] * d[1] - w[:, 1] * d[0]) / np.where(ok, den, 1)
    ts = np.sort(t[ok & (s >= 0) & (s < 1)])
    return [(ts[i], ts[i + 1]) for i in range(0, len(ts) - 1, 2)]


def subtract(ivs, holes):
    out = []
    for a, b in ivs:
        parts = [(a, b)]
        for c, d in holes:
            nxt = []
            for p, q in parts:
                if d <= p or c >= q:
                    nxt.append((p, q))
                    continue
                if c > p:
                    nxt.append((p, c))
                if d < q:
                    nxt.append((d, q))
            parts = nxt
        out += parts
    return out


class Radien:
    """r_innen(θ) und r_aussen(θ) um die Mitte c, für den Parameter t."""

    def __init__(self, outline, window, c, n=720):
        self.c = c
        self.th = np.linspace(-np.pi, np.pi, n + 1)
        ro, rw = [], []
        for a in self.th:
            d = np.array([math.cos(a), math.sin(a)])
            ho, hw = ray_hits(outline, c, d), ray_hits(window, c, d)
            ro.append(ho[0] if len(ho) else 0.0)
            rw.append(hw[0] if len(hw) else 0.0)
        self.ro, self.rw = np.array(ro), np.array(rw)

    def t(self, pts):
        v = pts - self.c
        r = np.hypot(v[:, 0], v[:, 1])
        a = np.arctan2(v[:, 1], v[:, 0])
        ro = np.interp(a, self.th, self.ro)
        rw = np.interp(a, self.th, self.rw)
        return np.clip((r - rw) / np.maximum(ro - rw, 1e-6), 0, 1)


# ------------------------------------------------------------------ Höhen

def hoehe_fn(name, wellen, formel):
    w = max(wellen, 0.1)
    if name == "Rand zum Fenster":
        return lambda t, u, v: (1 - t) ** 0.7
    if name == "Krater":
        return lambda t, u, v: np.sin(np.pi * np.clip(t * 1.6, 0, 1)) ** 0.8 \
            * (1 - 0.4 * t)
    if name == "Trichter":
        return lambda t, u, v: t ** 0.8
    if name == "Welle":
        return lambda t, u, v: (0.5 + 0.5 * np.sin(np.pi * w * (u + v))) \
            * (0.4 + 0.6 * np.sin(np.pi * np.clip(t, 0, 1)) ** 0.5)
    if name == "Ringwellen":
        return lambda t, u, v: (0.5 + 0.5 * np.cos(2 * np.pi * w * t)) \
            * (1 - 0.6 * t)
    if name == "Sattel":
        return lambda t, u, v: 0.5 + 0.5 * np.clip(u * u - v * v, -1, 1)
    if name == "Zwei Hügel":
        return lambda t, u, v: np.exp(-((u - .5) ** 2 + (v - .25) ** 2) / .1) \
            + np.exp(-((u + .45) ** 2 + (v - .3) ** 2) / .1)
    if name == "Eigene Formel":
        code = compile(formel, "Formel", "eval")

        def f(t, u, v):
            return np.array([float(eval(code, {"__builtins__": {}}, dict(
                FORMEL_NS, t=a, u=b, v=c, w=w))) for a, b, c in zip(t, u, v)])
        return f
    raise ValueError(f"Unbekannte Höhe {name}")


# ------------------------------------------------------------------- Plan

def zapfen(L, breite):
    """Zapfen (von, bis) entlang einer Rippe der Länge L."""
    if L < 14:
        return []
    w = min(breite, L / 4)
    mids = [L * 0.25, L * 0.75] if L > 45 else [L / 2]
    return [(m - w / 2, m + w / 2) for m in mids]


AUSGLEICH = ["aus", "Fenster seitlich", "Ganzes drehen"]


def polygon_flaeche(P):
    P = np.asarray(P, float)
    x, y = P[:, 0], P[:, 1]
    return (x * np.roll(y, -1) - np.roll(x, -1) * y).sum() / 2


def schwerpunkt(p, staerke, *, dichte=0.75, werk_g=70.0, haken=20.0):
    """Masse und Schwerpunkt (MDF, g/cm³) samt Uhrwerk an der Welle.

    Der Aufhänger sitzt am Uhrwerk, ``haken`` mm über der Welle. Die Uhr
    pendelt sich so ein, dass der Schwerpunkt senkrecht unter dem Haken
    liegt; ``neigung`` ist der Winkel, um den sie dann schief hängt
    (positiv = gegen den Uhrzeigersinn, von vorn gesehen).
    """
    rho = dichte / 1000.0                              # g/mm³
    c = np.asarray(p["mitte"], float)
    teile = []                                         # (masse, x, y, z)
    A = abs(polygon_flaeche(p["outline"]))
    gp = area_centroid(p["outline"])
    teile.append((A * staerke * rho, gp[0], gp[1], -staerke / 2))
    for r in p["rippen"]:
        prof = np.asarray(r["profil"], float)
        a = polygon_flaeche(prof)
        if abs(a) < 1e-9:
            continue
        sc, zc = area_centroid(prof)
        q = r["p0"] + r["d"] * sc
        teile.append((abs(a) * staerke * rho, q[0], q[1], zc))
    if werk_g > 0:
        teile.append((werk_g, c[0], c[1], -staerke - 8.0))
    T = np.array(teile)
    m = T[:, 0].sum()
    g = (T[:, 1:] * T[:, :1]).sum(0) / m
    dx, dy = g[0] - c[0], g[1] - c[1]
    neigung = -math.degrees(math.atan2(dx, haken - dy))
    return dict(masse=float(m), punkt=g, dx=float(dx), dy=float(dy),
                neigung=float(neigung), stabil=bool(dy < haken),
                haken=c + np.array([0.0, haken]))


def drehen(p, winkel_grad):
    """Ganzen Plan starr um die Welle drehen."""
    c = np.asarray(p["mitte"], float)
    a = math.radians(winkel_grad)
    M = np.array([[math.cos(a), -math.sin(a)], [math.sin(a), math.cos(a)]])

    def rot(P):
        P = np.asarray(P, float)
        return (P - c) @ M.T + c if len(P) else P
    q = dict(p, outline=rot(p["outline"]), window=rot(p["window"]))
    q["rippen"] = [dict(r, p0=rot(r["p0"][None])[0], d=M @ r["d"])
                   for r in p["rippen"]]
    return q


def ausgleichen(outline, modus, staerke, sp_args, **kw):
    """Plan erzeugen und so korrigieren, dass die Uhr gerade hängt.

    ``Fenster seitlich`` verschiebt Fenster samt Welle waagerecht, bis der
    Schwerpunkt unter dem Haken liegt; ``Ganzes drehen`` dreht das fertige
    Objekt um die Welle (die Zwölf bleibt oben, das Design steht schräg).
    """
    p = plan(outline, staerke=staerke, **kw)
    sp = schwerpunkt(p, staerke, **sp_args)
    if modus == "Fenster seitlich" and p["rippen"]:
        fx0 = kw.pop("fx", 0.0)
        x0, f0 = fx0, sp["dx"]
        x1 = fx0 + f0
        for _ in range(12):
            q = plan(outline, staerke=staerke, fx=x1, **kw)
            if not q["rippen"]:
                break
            s1 = schwerpunkt(q, staerke, **sp_args)
            p, sp = q, s1
            f1 = s1["dx"]
            if abs(f1) < 0.05 or abs(f1 - f0) < 1e-9:
                break
            x0, x1, f0 = x1, x1 - f1 * (x1 - x0) / (f1 - f0), f1
        p["fx"] = x1
    elif modus == "Ganzes drehen" and p["rippen"]:
        if math.hypot(sp["dx"], sp["dy"]) > 1e-6:   # Schwerpunkt unter Welle
            a = math.degrees(math.atan2(sp["dy"], sp["dx"]))
            p = drehen(p, -90.0 - a)
            sp = schwerpunkt(p, staerke, **sp_args)
    return p, sp


def plan(outline, *, richtung="parallel", abstand=7.0, anzahl=48,
         winkel=0.0, drall=0.0, staerke=3.0, hmin=4.0, hmax=40.0,
         fenster=0.35, fx=0.0, fy=0.0, hoehe="Rand zum Fenster",
         wellen=2.0, formel="1-t", zapfen_breite=10.0, schritt=1.5,
         min_laenge=8.0):
    """Liefert dict mit outline, window, mitte und rippen.

    Jede Rippe: p0 (Startpunkt 2D), d (Richtung), profil (s, z)-Polygon
    inkl. Zapfen nach unten bis -staerke, zapfen [(s0, s1)], laenge.
    """
    P = np.asarray(outline, float)
    c0 = area_centroid(P)
    span = (P.max(0) - P.min(0)).max()
    c = c0 + np.array([fx, fy])
    W = c + (P - c0) * fenster if fenster > 0 else np.zeros((0, 2))
    R = span / 2
    rad = Radien(P, W if len(W) else (c + (P - c0) * 1e-3), c)
    hf = hoehe_fn(hoehe, wellen, formel)

    def h_at(pts):
        t = rad.t(pts)
        u, v = (pts[:, 0] - c0[0]) / R, (pts[:, 1] - c0[1]) / R
        f = np.clip(np.asarray(hf(t, u, v), float), 0, 1)
        return hmin + (hmax - hmin) * f

    segs = []
    if richtung == "parallel":
        a = math.radians(winkel)
        d = np.array([math.cos(a), math.sin(a)])
        nrm = np.array([-d[1], d[0]])
        proj = (P - c0) @ nrm
        k0 = math.ceil((proj.min() + staerke) / abstand)
        k1 = math.floor((proj.max() - staerke) / abstand)
        for k in range(k0, k1 + 1):
            o = c0 + nrm * (k * abstand)
            ivs = line_intervals(P, o, d)
            if len(W):
                ivs = subtract(ivs, line_intervals(W, o, d))
            segs += [(o + d * s0, d, s1 - s0) for s0, s1 in ivs]
    else:
        n = max(3, int(anzahl))
        dr = math.radians(drall)
        for k in range(n):
            a = 2 * math.pi * k / n + math.radians(winkel)
            e = np.array([math.cos(a), math.sin(a)])
            hw = ray_hits(W, c, e) if len(W) else []
            r0 = hw[0] if len(hw) else 0.0
            r0 = max(r0, n * (staerke + 1.0) / (2 * math.pi))   # Platz innen
            p0 = c + e * r0
            d = np.array([math.cos(a + dr), math.sin(a + dr)])
            ho = ray_hits(P, p0, d)
            if not len(ho):
                continue
            L = ho[0]
            if len(W) and drall:
                hw2 = ray_hits(W, p0 + d * 1e-6, d)   # wieder ins Fenster?
                if len(hw2) and hw2[0] < L:
                    p0, L = p0 + d * hw2[-1], L - hw2[-1]
            segs.append((p0, d, L))

    rippen = []
    for p0, d, L in segs:
        L -= 0.5                                      # nicht über den Rand
        if L < min_laenge:
            continue
        m = max(2, int(math.ceil(L / schritt)) + 1)
        s = np.linspace(0, L, m)
        z = h_at(p0 + np.outer(s, d))
        zp = zapfen(L, zapfen_breite)
        unten = [(L, 0.0)]
        for s0, s1 in reversed(zp):
            unten += [(s1, 0.0), (s1, -staerke), (s0, -staerke), (s0, 0.0)]
        unten.append((0.0, 0.0))
        profil = list(zip(s, z)) + unten
        rippen.append(dict(p0=p0, d=d, laenge=L, profil=profil, zapfen=zp,
                           hoehe=float(z.max())))
    return dict(outline=P, window=W, mitte=c, rippen=rippen)
