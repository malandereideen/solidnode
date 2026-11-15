"""Gaube, Vordach und gebogener Rundturm (wie im bausatzmaker).

- Gaube: Giebelgaube auf der Dachfläche eines Hauses (Sattel/Pult/Walm):
  Front mit Giebel (und Fenster), zwei Wangen, zwei Dachplatten, die hinten
  auf der Hauptdachfläche enden.
- Vordach: geneigte Platte an der Wand, Binder (Balken + Kopfband + Pfosten)
  und Volant (Zackenbrett) vorn.
- Rundturm gebogen: Mantel als Rohr, im Export als flacher Streifen mit
  Living Hinge; Kegeldach als Drehkörper, im Export als Kreissektor mit
  radialen Schlitzen. Oder Zinnen/flach.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.affinity import rotate
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from . import laser_geom as G


def _r(v, n=4):
    return round(float(v), n)


def _f(v):
    return [round(float(x), 6) for x in v]


def _clip_half(poly, a, b, c):
    """Polygon ∩ {a·x + b·y ≤ c}."""
    n = np.array([a, b], float)
    k = np.linalg.norm(n)
    n /= k
    c /= k
    p0 = n * c                                   # Punkt auf der Geraden
    d = np.array([-n[1], n[0]])                  # Richtung der Geraden
    big = 1e4
    hp = Polygon([tuple(p0 + d * big), tuple(p0 - d * big),
                  tuple(p0 - d * big - n * big), tuple(p0 + d * big - n * big)])
    return poly.intersection(hp)


def hinge_slots(L, H, schnitt, steg, abstand, schlitz, vertical=True):
    """Schlitzmuster über eine ganze Fläche L×H (Reihen quer zur Biegung).
    vertical: Schlitze laufen parallel zu H (Mantel eines Zylinders)."""
    pitch = schnitt + steg
    slots = []
    rows = max(2, int(L // abstand))
    gap = (L - (rows - 1) * abstand) / 2
    for r in range(rows):
        x = gap + r * abstand
        y = -(0.0 if r % 2 else pitch / 2) - pitch
        while y < H:
            y0, y1 = max(y, -1.0), min(y + schnitt, H + 1.0)
            if y1 - y0 > steg:
                slots.append(box(x - schlitz / 2, y0, x + schlitz / 2, y1))
            y += pitch
    g = unary_union(slots) if slots else Polygon()
    if not vertical:
        g = rotate(g, 90, origin=(0, 0))
    return g


class ExtraMixin:

    # ------------------------------------------------------------ Gaube

    def ctx_gaube(self):
        ctx = self.ctx_kamin()
        sel = self.selection()
        seite = "vorn"
        h = next((e for e in self.elements() if e["id"] == ctx["haus"]))
        for x in sel:
            b = x.get("body") or x.get("name") or ""
            if b.endswith(("Dach hinten", "Rueckwand")):
                seite = "hinten"
            pt = x.get("point")
            if pt and b.endswith("Dach") and h["params"]["dach"] != "pult":
                yc = h["params"].get("y", 0) + h["params"]["tiefe"] / 2
                seite = "hinten" if pt[1] > yc else "vorn"
        ctx["seite"] = seite
        return ctx

    def _haus_frame(self, h, seite):
        """Weltabbildung von Front-Koordinaten (x längs, y in die Tiefe ab
        Fassade, z) auf die gewählte Hausseite."""
        hp = h["params"]
        o = np.array([hp.get("x", 0), hp.get("y", 0), hp.get("z", 0)], float)
        B, T = hp["breite"], hp["tiefe"]
        if seite == "hinten":
            W = lambda x, y, z: o + [B - x, T - y, z]          # noqa: E731
            V = lambda v: np.array([-v[0], -v[1], v[2]], float)  # noqa: E731
        else:
            W = lambda x, y, z: o + [x, y, z]                  # noqa: E731
            V = lambda v: np.array(v, float)                   # noqa: E731
        return W, V

    def cmds_gaube(self, name, ctx, p):
        return self._giebelgaube(name, ctx, p)

    def _giebelgaube(self, name, ctx, p, zwerch=False):
        """Giebelgaube; zwerch=True: Front in der Fassade, sitzt auf der
        Traufwand, Hauptdach wird dort ausgeschnitten (Zwerchgiebel)."""
        h = next((e for e in self.elements() if e["id"] == ctx["haus"]), None)
        if h is None:
            raise RuntimeError("Haus der Gaube fehlt")
        hp = h["params"]
        if hp["dach"] == "flach":
            raise RuntimeError("Gaube braucht ein geneigtes Dach")
        if hp["dach"] == "pult" and ctx["seite"] == "hinten":
            raise RuntimeError("Pultdach hat nur vorn eine Dachfläche")
        B, T, H, t, a, ta, _ov = self._haus_geom(hp)
        ca = math.cos(a)
        half = T if hp["dach"] == "pult" else T / 2
        W, V = self._haus_frame(h, ctx["seite"])
        w = max(p["breite"], 2 * t + 3)
        u = p["x"]
        u0, u1, hw = u - w / 2, u + w / 2, w / 2
        ag = math.radians(p["neigung"])
        sg, cg, tg = math.sin(ag), math.cos(ag), math.tan(ag)
        top = lambda y: H + y * ta + t / ca                    # noqa: E731
        if zwerch:
            dg = 0.0
            z0 = H                                  # auf der Traufwand
            zT = H + p["kniestock"]
            zc = top(t) + 0.2                       # Wangen ab Dachfläche
        else:
            dg, hg = p["tiefe"], p["hoehe"]
            z0 = zc = top(dg + t) + 0.2
            zT = z0 + hg
        hg = zT - z0
        zG = zT + hw * tg
        if (zG + t / cg - (H + t / ca)) / ta > half - 1:
            raise RuntimeError("Gaube reicht über den First (kleiner oder "
                               "näher an die Traufe)")
        cmds, bodies = [], []
        if zwerch:                                  # Hauptdach aufschneiden
            roof = f"{h['name']} " + ("Dach" if hp["dach"] == "pult" else
                                      "Dach hinten" if ctx["seite"] == "hinten"
                                      else "Dach vorn")
            q = [W(u0, -_ov - 1, 0), W(u1, -_ov - 1, 0), W(u1, t, 0),
                 W(u0, t, 0)]
            xs, ys = [v[0] for v in q], [v[1] for v in q]
            zz = W(0, 0, top(half) + 20)[2]
            cmds += self._cut_plan(f"{name} Dachausschnitt",
                                   [(min(xs), min(ys)), (max(xs), min(ys)),
                                    (max(xs), max(ys)), (min(xs), max(ys))],
                                   zz, zz - W(0, 0, H - 1)[2], [roof])

        def plate(nm, pts, n_out, inward=False, holes=()):
            cmds.extend(self._plate3d(f"{name} {nm}", pts, n_out, t,
                                      inward=inward, holes=holes))
            bodies.append(f"{name} {nm}")

        # Front: Giebelwand bei y = dg … dg+t, Fenster als Loch
        front = [W(u0, dg, z0), W(u1, dg, z0), W(u1, dg, zT), W(u, dg, zG),
                 W(u0, dg, zT)]
        holes = []
        if p["fenster"]:
            fw = min(w - 2 * t - 2, w * 0.55)
            fz0, fz1 = z0 + hg * 0.15, z0 + hg * 0.85
            if fw > 2:
                holes = [[W(u - fw / 2, dg, fz0), W(u + fw / 2, dg, fz0),
                          W(u + fw / 2, dg, fz1), W(u - fw / 2, dg, fz1)]]
        plate("Front", front, V([0, -1, 0]), inward=True, holes=holes)
        # Wangen: Dreiecke auf der Dachfläche
        dEnd = (zT - 0.2 - H - t / ca) / ta
        for nm, xc, n_out in (("Wange links", u0, [-1, 0, 0]),
                              ("Wange rechts", u1, [1, 0, 0])):
            pts = [W(xc, dg + t, zc), W(xc, dEnd, zT), W(xc, dg + t, zT)]
            plate(nm, pts, V(n_out), inward=True)
        # Dachplatten: Unterseite durch die Oberkanten der Wangen, hinten
        # auf der Hauptdachfläche abgeschnitten
        ovd, ovs = 1.5, 1.5
        sP = hw / cg
        dS = dg - ovd
        for nm, ue, side in (("Dach links", u0, 1), ("Dach rechts", u1, -1)):
            poly = box(0, -ovs, 400, sP)               # (s nach hinten, v hoch)
            # z(s, v) = zT + v·sg ≥ top(dS + s) + 0.1
            poly = _clip_half(poly, ta, -sg, zT - H - t / ca - 0.1 - dS * ta)
            if poly.is_empty or poly.area < 1:
                continue
            ring = list(poly.exterior.coords)[:-1]
            pts = [W(ue + side * v * cg, dS + s, zT + v * sg) for s, v in ring]
            n_out = V([-side * sg, 0, cg])
            plate(nm, pts, n_out)
        art = "Zwerchgiebel " if zwerch else ""
        return cmds, bodies, \
            f"{art}{w:g} breit, {hg:g} hoch, {ctx['seite']} auf {h['name']}"

    # ---------------------------------------------------------- Vordach

    def _vd_geom(self, ctx, p):
        t = p["staerke"]
        dv, nk = p["tiefe"], math.radians(p["neigung"])
        y0 = ctx["bounds"][1]
        zv = y0 + p["z"]
        return t, dv, nk, math.tan(nk), zv, y0

    def cmds_vordach(self, name, ctx, p):
        t, dv, nk, tk, zv, y0 = self._vd_geom(ctx, p)
        P, R, U, N = (np.array(ctx[k], float) for k in ("p", "right", "up",
                                                         "n"))
        w, x = p["breite"], p["x"]
        u0 = x - w / 2
        ovv = 2.0
        Lv = (dv + ovv) / math.cos(nk)
        Wp = lambda u, d, z: P + R * u + N * d + U * z    # noqa: E731
        cmds, bodies = [], []
        # Dachplatte: Unterseite beginnt an der Wand auf Höhe zv
        down = N * math.cos(nk) - U * math.sin(nk)
        n2 = N * math.sin(nk) + U * math.cos(nk)
        a0 = Wp(u0, 0, zv)
        pts = [a0, a0 + R * w, a0 + R * w + down * Lv, a0 + down * Lv]
        cmds += self._plate3d(f"{name} Dach", pts, n2, t)
        bodies.append(f"{name} Dach")
        # Binder
        bh, pw, rk = 3.0, max(t, 3.0), 4.0
        zr = lambda d: zv - d * tk                         # noqa: E731
        beam = Polygon([(0, zr(0) - bh), (dv, zr(dv) - bh), (dv, zr(dv) - 0.05),
                        (0, zr(0) - 0.05)])
        xp = dv - pw
        zc = zr(xp) - bh
        knee = box(xp - rk, zc - rk, xp, zc + 0.5).difference(
            Polygon(G.arch_poly(xp - rk, zc - 2 * rk, 2 * rk, zc, "rund")))
        prof = unary_union([beam, knee])
        if p["stuetzen"]:
            prof = prof.union(box(xp, y0, dv, zr(dv) - bh + 0.5))
        else:
            prof = prof.union(box(xp, zc - rk - 2, dv, zr(dv) - bh + 0.5))
        prof = prof.buffer(0)
        nB = max(2, round(w / 30) + 1)
        for j in range(nB):
            ub = u0 + t / 2 + 1 + (w - t - 2) * j / (nB - 1)
            nm = f"{name} Binder {j + 1}"
            ring = list(prof.exterior.coords)[:-1]
            pts3 = [Wp(ub - t / 2, d, z) for d, z in ring]
            cmds += self._plate3d(nm, pts3, R, t)
            bodies.append(nm)
        # Volant: Zackenbrett vor der Dachkante
        if p["volant"]:
            dEnd = dv + ovv + t * math.sin(nk) + 0.15
            zTop = zv - Lv * math.sin(nk) + t * math.cos(nk)
            hv = 5.0
            zz = [(0, zTop)]
            xx = 0.0
            while xx <= w + 0.01:
                zz += [(min(xx, w), zTop - hv + 1.6),
                       (min(xx + 1.5, w), zTop - hv)]
                xx += 3
            zz += [(w, zTop - hv + 1.6), (w, zTop)]
            g = Polygon(zz).buffer(0)
            ring = list(g.exterior.coords)[:-1]
            pts3 = [Wp(u0 + uu, dEnd, z) for uu, z in ring]
            cmds += self._plate3d(f"{name} Volant", pts3, N, t)
            bodies.append(f"{name} Volant")
        return cmds, bodies, \
            f"{w:g}×{dv:g}, {p['neigung']:g}° an {ctx['wall']}"

    def fp_vordach(self, el):
        ctx, p = el["ctx"], el["params"]
        _t, _dv, _nk, _tk, zv, _y0 = self._vd_geom(ctx, p)
        x, w = p["x"], p["breite"]
        return [(ctx, box(x - w / 2 - 0.5, zv - 3 - 4 - 1.5,
                          x + w / 2 + 0.5, zv + p["staerke"] + 1))]

    # ------------------------------------------------- Rundturm gebogen

    def ctx_rundturm(self):
        return {}

    def _rt(self, p):
        R, H, t = p["durchmesser"] / 2, p["hoehe"], p["staerke"]
        c = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        zh = p["zinnen_h"] if p["dach"] == "zinnen" else 0.0
        return R, H, t, c, zh

    def _zinnen_winkel(self, R, zb):
        n = max(3, round(2 * math.pi * R / zb))
        if n % 2:
            n += 1
        return n

    def cmds_rundturm(self, name, ctx, p):
        R, H, t, c, zh = self._rt(p)
        cmds, bodies = [], []
        z0 = c[2]
        sk = {"command": "sketch.create", "params": {
            "plane": {"origin": _f([0, 0, z0]), "x_dir": [1, 0, 0],
                      "y_dir": [0, 1, 0]}, "name": f"{name} Mantel Skizze"}}
        cmds += [sk,
                 {"command": "sketch.circle.center", "params": {
                     "center": [_r(c[0]), _r(c[1])], "radius": _r(R)}},
                 {"command": "sketch.circle.center", "params": {
                     "center": [_r(c[0]), _r(c[1])], "radius": _r(R - t)}},
                 {"command": "sketch.finish", "params": {}},
                 {"command": "solid.extrude", "params": {
                     "distance": _r(H + zh), "operation": "new",
                     "body_name": f"{name} Mantel", "name": f"{name} Mantel"}}]
        bodies.append(f"{name} Mantel")
        if zh:
            n = self._zinnen_winkel(R, p["zinnen_b"])
            dz = 2 * math.pi / n
            polys = []
            for k in range(0, n, 2):
                a0, a1 = k * dz, (k + 1) * dz
                r0, r1 = R - t - 1, R + 1
                pts = [(c[0] + r * math.cos(a), c[1] + r * math.sin(a))
                       for r, a in ((r0, a0), (r1, a0), (r1, a1), (r0, a1))]
                polys.append(pts)
            cmds.append({"command": "sketch.create", "params": {
                "plane": {"origin": _f([0, 0, z0 + H + zh + 1]),
                          "x_dir": [1, 0, 0], "y_dir": [0, 1, 0]},
                "name": f"{name} Zinnen Skizze"}})
            for pts in polys:
                q = [[_r(x), _r(y)] for x, y in pts]
                cmds.append({"command": "sketch.line",
                             "params": {"points": q + [q[0]]}})
            cmds += [{"command": "sketch.finish", "params": {}},
                     {"command": "solid.extrude", "params": {
                         "distance": _r(zh + 1), "direction": "negative",
                         "operation": "cut", "targets": [f"{name} Mantel"],
                         "name": f"{name} Zinnen"}}]
        disk = lambda zz, nm: [                                  # noqa: E731
            {"command": "sketch.create", "params": {
                "plane": {"origin": _f([0, 0, zz]), "x_dir": [1, 0, 0],
                          "y_dir": [0, 1, 0]}, "name": f"{nm} Skizze"}},
            {"command": "sketch.circle.center", "params": {
                "center": [_r(c[0]), _r(c[1])], "radius": _r(R - t)}},
            {"command": "sketch.finish", "params": {}},
            {"command": "solid.extrude", "params": {
                "distance": _r(t), "operation": "new", "body_name": nm,
                "name": nm}}]
        if p["boden"]:
            cmds += disk(z0, f"{name} Boden")
            bodies.append(f"{name} Boden")
        if p["dach"] in ("flach", "zinnen"):
            cmds += disk(z0 + H - t, f"{name} Dach")
            bodies.append(f"{name} Dach")
        elif p["dach"] == "kegel":
            a = math.radians(p["neigung"])
            Ro = R + p["ueberstand"]
            ze = z0 + H - p["ueberstand"] * math.tan(a)
            zap = z0 + H + R * math.tan(a)
            dt = t / math.cos(a)
            prof = [(Ro, ze), (0.001, zap), (0.001, zap + dt), (Ro, ze + dt)]
            cmds.append({"command": "sketch.create", "params": {
                "plane": {"origin": _f([c[0], c[1], 0]), "x_dir": [1, 0, 0],
                          "y_dir": [0, 0, 1]}, "name": f"{name} Kegel Skizze"}})
            q = [[_r(x), _r(z)] for x, z in prof]
            cmds += [{"command": "sketch.line",
                      "params": {"points": q + [q[0]]}},
                     {"command": "sketch.finish", "params": {}},
                     {"command": "solid.revolve", "params": {
                         "axis": {"origin": _f([c[0], c[1], 0]),
                                  "dir": [0, 0, 1]},
                         "operation": "new", "body_name": f"{name} Kegeldach",
                         "name": f"{name} Kegeldach"}}]
            bodies.append(f"{name} Kegeldach")
        dach = {"kegel": f"Kegeldach {p['neigung']:g}°", "zinnen": "Zinnen",
                "flach": "flach"}[p["dach"]]
        return cmds, bodies, f"Ø{2 * R:g}×{H:g} gebogen, {dach}"

    def flat_rundturm(self, el):
        """Mantel und Kegel flach mit Hinge-Schlitzen (für den Export)."""
        p = el["params"]
        R, H, t, _c, zh = self._rt(p)
        out = []
        L = 2 * math.pi * (R - t / 2)                    # neutrale Faser
        Ht = H + zh
        strip = box(0, 0, L, Ht)
        if zh:
            n = self._zinnen_winkel(R, p["zinnen_b"])
            seg = L / n
            strip = strip.difference(unary_union([
                box(k * seg, H, (k + 1) * seg, Ht + 1)
                for k in range(0, n, 2)]))
        slots = hinge_slots(L, H, p["schnitt"], p["steg"], p["abstand"],
                            p["schlitz"])
        out.append((f"{el['name']} Mantel", strip.difference(slots), []))
        # Klebelasche: wird innen über den Stoß geklebt
        out.append((f"{el['name']} Mantel Lasche", box(0, 0, 8, H - 2), []))
        if p["dach"] == "kegel":
            a = math.radians(p["neigung"])
            Ro = R + p["ueberstand"]
            s = Ro / math.cos(a)                          # Mantellinie
            phi = 2 * math.pi * Ro / s                    # Sektorwinkel
            pts = [(0, 0)] + [(s * math.cos(phi * i / 96),
                               s * math.sin(phi * i / 96)) for i in range(97)]
            sector = Polygon(pts).buffer(0)
            r_in = 0.4 * s                       # innen zu eng für Schlitze
            rows = max(4, int(phi * r_in // p["abstand"]))
            sl = []
            pitch = p["schnitt"] + p["steg"]
            for k in range(1, rows):
                ang = phi * k / rows
                d = np.array([math.cos(ang), math.sin(ang)])
                r = r_in + (pitch / 2 if k % 2 else 0.0)
                while r < s + 1:
                    r1 = min(r + p["schnitt"], s + 1)
                    sl.append(LineString([tuple(d * r), tuple(d * r1)])
                              .buffer(p["schlitz"] / 2, cap_style=2))
                    r += pitch
            cone = sector.difference(unary_union(sl)) if sl else sector
            out.append((f"{el['name']} Kegeldach", cone, []))
            out.append((f"{el['name']} Kegeldach Lasche",
                        Polygon([(0, 0), (s * 0.85, 2), (s * 0.85, 6),
                                 (0, 4)]), []))
        return out
