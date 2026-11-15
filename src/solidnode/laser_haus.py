"""Baukörper der Laser-Palette: Haus mit Sattel-, Pult-, Walm- oder
Flachdach (Zinnen), Vieleckturm mit Zeltdach oder Zinnen, Schornstein.

Wände überlappen an den Ecken wie beim Kasten (danach „Zinken → Alle
Stöße“). Dachplatten liegen mit der Unterseite auf der Dachfläche und
wachsen nach außen — so treffen sie sich an First und Graten mit der
Unterkante, ohne sich zu durchdringen (oben bleibt eine kleine Kerbe).
"""

from __future__ import annotations

import math

import numpy as np

from . import laser_geom as G


def _r(v, n=5):
    return round(float(v), n)


def _f(v):
    return [round(float(x), 6) for x in v]


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


class HausMixin:

    # -- Baustein: ebene Platte aus 3D-Polygon

    def _plate3d(self, name, pts, n_out, t, inward=False, holes=()):
        """Polygon (Weltpunkte, eben) als Platte; wächst entlang n_out
        (oder nach innen)."""
        pts = [np.asarray(p, float) for p in pts]
        n = _unit(n_out)
        x = _unit(pts[1] - pts[0])
        y = np.cross(n, x)
        o = pts[0]
        loc = lambda q: [_r((q - o) @ x, 4), _r((q - o) @ y, 4)]  # noqa: E731
        cmds = [{"command": "sketch.create", "params": {
            "plane": {"origin": _f(o), "x_dir": _f(x), "y_dir": _f(y)},
            "name": f"{name} Skizze"}}]
        for loop in [pts, *[[np.asarray(h, float) for h in hl]
                            for hl in holes]]:
            q = [loc(p) for p in loop]
            cmds.append({"command": "sketch.line",
                         "params": {"points": q + [q[0]]}})
        cmds.append({"command": "sketch.finish", "params": {}})
        cmds.append({"command": "solid.extrude", "params": {
            "distance": _r(t, 4), "operation": "new",
            "direction": "negative" if inward else "positive",
            "body_name": name, "name": name}})
        return cmds

    def _wall_box(self, name, lo, hi):
        return self._box_plate(name, lo, hi)

    # -- Haus

    def ctx_haus(self):
        return {}

    def _haus_geom(self, p):
        B, T, H, t = p["breite"], p["tiefe"], p["hoehe"], p["staerke"]
        a = math.radians(p["neigung"])
        return B, T, H, t, a, math.tan(a), p["ueberstand"]

    def cmds_haus(self, name, ctx, p):
        B, T, H, t, a, ta, ov = self._haus_geom(p)
        o = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        X, Y, Z = np.eye(3)
        dach = p["dach"]
        cmds, bodies = [], []

        def add(nm, c):
            cmds.extend(c)
            bodies.append(f"{name} {nm}")

        if p["boden"]:
            add("Boden", self._wall_box(f"{name} Boden", o, o + [B, T, t]))
        zh = p["zinnen_h"] if dach == "flach" and p["zinnen"] else 0.0
        # Traufwände vorn/hinten
        hv = H
        hh = H + (T - t) * ta if dach == "pult" else H
        add("Front", self._wall_box(f"{name} Front", o, o + [B, t, hv + zh]))
        add("Rueckwand", self._wall_box(f"{name} Rueckwand", o + [0, T - t, 0],
                                        o + [B, T, hh + zh]))
        # Seitenwände (Giebel)
        for side, x0, n_out in (("Seite links", 0.0, -X),
                                ("Seite rechts", B, X)):
            P = lambda y, z: o + [x0, y, z]       # noqa: E731
            if dach == "sattel":
                poly = [P(0, 0), P(T, 0), P(T, H), P(T / 2, H + T / 2 * ta),
                        P(0, H)]
            elif dach == "pult":
                poly = [P(0, 0), P(T, 0), P(T, H + T * ta), P(0, H)]
            else:
                poly = [P(0, 0), P(T, 0), P(T, H + zh), P(0, H + zh)]
            add(side, self._plate3d(f"{name} {side}", poly, n_out, t,
                                    inward=True))
        # Dach
        ze = H - ov * ta                           # Traufkante mit Überstand
        if dach == "sattel":
            zr = H + T / 2 * ta
            r0, r1 = o[0] - ov, o[0] + B + ov
            add("Dach vorn", self._plate3d(f"{name} Dach vorn", [
                [r0, o[1] - ov, o[2] + ze], [r1, o[1] - ov, o[2] + ze],
                [r1, o[1] + T / 2, o[2] + zr], [r0, o[1] + T / 2, o[2] + zr]],
                [0, -math.sin(a), math.cos(a)], t))
            add("Dach hinten", self._plate3d(f"{name} Dach hinten", [
                [r1, o[1] + T + ov, o[2] + ze], [r0, o[1] + T + ov, o[2] + ze],
                [r0, o[1] + T / 2, o[2] + zr], [r1, o[1] + T / 2, o[2] + zr]],
                [0, math.sin(a), math.cos(a)], t))
        elif dach == "pult":
            r0, r1 = o[0] - ov, o[0] + B + ov
            zb = H + (T + ov) * ta
            add("Dach", self._plate3d(f"{name} Dach", [
                [r0, o[1] - ov, o[2] + ze], [r1, o[1] - ov, o[2] + ze],
                [r1, o[1] + T + ov, o[2] + zb], [r0, o[1] + T + ov, o[2] + zb]],
                [0, -math.sin(a), math.cos(a)], t))
        elif dach == "walm":
            if B < T:
                raise RuntimeError("Walmdach: Breite muss ≥ Tiefe sein")
            zr = H + T / 2 * ta
            e = [o + [-ov, -ov, ze], o + [B + ov, -ov, ze],
                 o + [B + ov, T + ov, ze], o + [-ov, T + ov, ze]]
            r = [o + [T / 2, T / 2, zr], o + [B - T / 2, T / 2, zr]]
            s, c = math.sin(a), math.cos(a)
            add("Dach vorn", self._plate3d(f"{name} Dach vorn",
                                           [e[0], e[1], r[1], r[0]],
                                           [0, -s, c], t))
            add("Dach hinten", self._plate3d(f"{name} Dach hinten",
                                             [e[2], e[3], r[0], r[1]],
                                             [0, s, c], t))
            add("Dach rechts", self._plate3d(f"{name} Dach rechts",
                                             [e[1], e[2], r[1]], [s, 0, c], t))
            add("Dach links", self._plate3d(f"{name} Dach links",
                                            [e[3], e[0], r[0]], [-s, 0, c], t))
        else:                                       # flach
            add("Dach", self._wall_box(f"{name} Dach", o + [0, 0, H - t],
                                       o + [B, T, H]))
            if zh:
                for c2 in self.kasten_walls({"name": name, "id": "",
                                             "params": dict(p, hoehe=H + zh)}):
                    L = c2["bounds"][2]
                    cuts = G.zinnen_cuts(0, L, H + zh, zh, p["zinnen_b"])
                    from shapely.geometry import box
                    from shapely.ops import unary_union
                    g = unary_union([box(*q) for q in cuts])
                    cmds.extend(self._cut_through(
                        c2, f"{c2['wall']} Zinnen", g))
        info = f"{B:g}×{T:g}×{H:g}, {dach}dach"
        if dach in ("sattel", "pult", "walm"):
            info += f" {p['neigung']:g}°"
        if zh:
            info += ", Zinnen"
        return cmds, bodies, info

    # -- Vieleckturm

    def ctx_turm(self):
        return {}

    def cmds_turm(self, name, ctx, p):
        n, D, H, t = int(p["ecken"]), p["durchmesser"], p["hoehe"], \
            p["staerke"]
        c = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        R = D / 2
        ang = [2 * math.pi * (i + 0.5) / n for i in range(n)]
        V = [c + [R * math.cos(q), R * math.sin(q), 0] for q in ang]
        zh = p["zinnen_h"] if p["dach"] == "zinnen" else 0.0
        cmds, bodies = [], []
        trim = t / math.sin(2 * math.pi / n)      # stumpf an die Vorgängerin
        for i in range(n):
            a, b = V[i], V[(i + 1) % n]
            mid = (a + b) / 2 - c
            n_out = _unit([mid[0], mid[1], 0])
            a = a + _unit(b - a) * trim
            nm = f"{name} Wand {i + 1}"
            Ht = H + zh
            cmds += self._plate3d(nm, [a, b, b + [0, 0, Ht], a + [0, 0, Ht]],
                                  n_out, t, inward=True)
            bodies.append(nm)
            if zh:
                L = float(np.linalg.norm(b - a))
                cuts = G.zinnen_cuts(0, L, Ht, zh, p["zinnen_b"])
                x = _unit(b - a)
                for k, (x0, z0, x1, z1) in enumerate(cuts):
                    cmds += self._plate_cut(a, x, n_out, x0, z0, x1, z1, t,
                                            nm, f"{nm} Zinne {k + 1}")
        Ri = R - t / math.cos(math.pi / n)          # innen, ohne Wände
        Vi = [c + [Ri * math.cos(q), Ri * math.sin(q), 0] for q in ang]
        if p["boden"]:
            cmds += self._plate3d(f"{name} Boden", Vi, [0, 0, 1], t)
            bodies.append(f"{name} Boden")
        if p["dach"] == "zelt":
            ov, a_ = p["ueberstand"], math.radians(p["neigung"])
            Ro = R + ov / math.cos(math.pi / n)
            ze = H - ov * math.tan(a_)
            apex = c + [0, 0, H + (R * math.cos(math.pi / n)) * math.tan(a_)]
            Vo = [c + [Ro * math.cos(q), Ro * math.sin(q), ze] for q in ang]
            for i in range(n):
                a, b = Vo[i], Vo[(i + 1) % n]
                mid = (a + b) / 2 - c
                nh = _unit([mid[0], mid[1], 0])
                n_out = nh * math.sin(a_) + np.array([0, 0, math.cos(a_)])
                nm = f"{name} Dach {i + 1}"
                cmds += self._plate3d(nm, [a, b, apex], n_out, t)
                bodies.append(nm)
        elif p["dach"] == "flach" or zh:
            cmds += self._plate3d(f"{name} Dach",
                                  [v + [0, 0, H - t] for v in Vi], [0, 0, 1],
                                  t)
            bodies.append(f"{name} Dach")
        return cmds, bodies, \
            f"{n}-Eck Ø{D:g}×{H:g}, " + {"zelt": f"Zeltdach {p['neigung']:g}°",
                                         "zinnen": "Zinnen",
                                         "flach": "flach"}[p["dach"]]

    def _plate_cut(self, a, x, n_out, x0, z0, x1, z1, t, target, nm):
        """Rechteck in Wandkoordinaten (x längs, z hoch) durch die Wand."""
        z = np.array([0, 0, 1.0])
        o = a + x * x0 + z * z0
        cmds = [{"command": "sketch.create", "params": {
            "plane": {"origin": _f(o), "x_dir": _f(x), "y_dir": _f(z)},
            "name": f"{nm} Skizze"}},
            {"command": "sketch.rectangle.two_point", "params": {
                "p0": [0, 0], "p1": [_r(x1 - x0, 4), _r(z1 - z0, 4)]}},
            {"command": "sketch.finish", "params": {}},
            {"command": "solid.extrude", "params": {
                "distance": _r(t * 3, 4), "direction": "symmetric",
                "operation": "cut", "targets": [target], "name": nm}}]
        return cmds

    # -- Schornstein

    def ctx_kamin(self):
        sel = self.selection()
        names = {x.get("body") or x.get("name") for x in sel}
        for e in self.elements():
            if e["typ"] == "haus" and names & set(e.get("bodies", [])):
                return {"haus": e["id"]}
        hs = [e for e in self.elements() if e["typ"] == "haus"]
        if not hs:
            raise RuntimeError("Erst ein Haus anlegen (oder anklicken)")
        return {"haus": hs[-1]["id"]}

    def cmds_kamin(self, name, ctx, p):
        h = next((e for e in self.elements() if e["id"] == ctx["haus"]), None)
        if h is None:
            raise RuntimeError("Haus des Schornsteins fehlt")
        hp = h["params"]
        B, T, H, t, a, ta, _ov = self._haus_geom(hp)
        o = np.array([hp.get("x", 0), hp.get("y", 0), hp.get("z", 0)], float)
        if hp["dach"] == "flach":
            top_roof = H
        elif hp["dach"] == "pult":
            top_roof = H + T * ta
        else:
            top_roof = H + T / 2 * ta
        w, d = p["breite"], p["tiefe"]
        cx, cy = o[0] + p["x"], o[1] + T / 2 - p["y"]
        z0, z1 = o[2] + H - t, o[2] + top_roof + p["hoehe"]
        x0, x1, y0, y1 = cx - w / 2, cx + w / 2, cy - d / 2, cy + d / 2
        tk = p["staerke"]
        parts = [("vorn", (x0, y0, z0), (x1, y0 + tk, z1)),
                 ("hinten", (x0, y1 - tk, z0), (x1, y1, z1)),
                 ("links", (x0, y0 + tk, z0), (x0 + tk, y1 - tk, z1)),
                 ("rechts", (x1 - tk, y0 + tk, z0), (x1, y1 - tk, z1))]
        cmds, bodies = [], []
        roofs = [b for b in h.get("bodies", []) if " Dach" in b]
        if roofs:                                   # Loch ins Dach
            cmds += [{"command": "sketch.create", "params": {
                "plane": {"origin": [0, 0, _r(z1 + 1)], "x_dir": [1, 0, 0],
                          "y_dir": [0, 1, 0]}, "name": f"{name} Loch Skizze"}},
                {"command": "sketch.rectangle.two_point", "params": {
                    "p0": [_r(x0), _r(y0)], "p1": [_r(x1), _r(y1)]}},
                {"command": "sketch.finish", "params": {}},
                {"command": "solid.extrude", "params": {
                    "distance": _r(z1 - z0 + 2), "direction": "negative",
                    "operation": "cut", "targets": roofs,
                    "name": f"{name} Loch"}}]
        for nm, lo, hi in parts:
            cmds += self._box_plate(f"{name} {nm}", lo, hi)
            bodies.append(f"{name} {nm}")
        return cmds, bodies, f"{w:g}×{d:g}, {p['hoehe']:g} über First"
