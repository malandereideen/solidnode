"""Restliche bausatzmaker-Bauten für die Laser-Palette.

Ecktürmchen, Podest mit Treppe, Turmhelm mit Kreuz, Dachreiter,
Zwerchgiebel, Apsis, Windmühle, Leuchtturm, Steinbrücke, Fachwerkbrücke,
Pagode.

Zwei Bauweisen:
- Platten (wie bisher): Wände, Dächer, Fachwerk — Dachplatten wachsen nach
  außen, so stoßen sie an Graten nur mit der Unterkante.
- Scheibenbau: massive Körper (Ecktürmchen, Podest, Treppe, Mühlenhaube,
  Widerlager), deren Höhe ein Vielfaches der Materialstärke ist. Der Export
  schneidet sie Lage für Lage — so entstehen Stufenkegel und Kuppeln.
"""

from __future__ import annotations

import math

import numpy as np
from shapely.geometry import LineString, Polygon, box
from shapely.ops import unary_union

from . import laser_geom as G


def _r(v, n=4):
    return round(float(v), n)


def _f(v):
    return [round(float(x), 6) for x in v]


def _unit(v):
    v = np.asarray(v, float)
    return v / np.linalg.norm(v)


def _lagen(h, t):
    """Höhe auf ganze Lagen runden (mindestens eine)."""
    return max(1, round(h / t)) * t


class BautenMixin:

    # ------------------------------------------------------ Bausteine

    def _host(self, typen=("kasten", "haus")):
        """Element aus der Auswahl (oder das zuletzt angelegte)."""
        names = {x.get("body") or x.get("name") for x in self.selection()}
        els = self.elements()
        for e in els:
            if e["typ"] in typen and names & set(e.get("bodies", [])):
                return e
        hs = [e for e in els if e["typ"] in typen]
        return hs[-1] if hs else None

    def _get(self, eid):
        e = next((e for e in self.elements() if e["id"] == eid), None)
        if e is None:
            raise RuntimeError("Bezugselement fehlt (gelöscht?)")
        return e

    def _solid_cmds(self, nm, kind, **kw):
        cmd = {"cylinder": "solid.cylinder", "cone": "solid.cone"}[kind]
        params = {k: (_f(v) if isinstance(v, (list, np.ndarray)) else _r(v))
                  for k, v in kw.items()}
        params.update(operation="new", body_name=nm, name=nm)
        return [{"command": cmd, "params": params}]

    def _revolve(self, nm, c, prof):
        """Profil (r, z) um die senkrechte Achse durch c drehen."""
        q = [[_r(x), _r(z)] for x, z in prof]
        return [{"command": "sketch.create", "params": {
            "plane": {"origin": _f([c[0], c[1], 0]), "x_dir": [1, 0, 0],
                      "y_dir": [0, 0, 1]}, "name": f"{nm} Skizze"}},
            {"command": "sketch.line", "params": {"points": q + [q[0]]}},
            {"command": "sketch.finish", "params": {}},
            {"command": "solid.revolve", "params": {
                "axis": {"origin": _f([c[0], c[1], 0]), "dir": [0, 0, 1]},
                "operation": "new", "body_name": nm, "name": nm}}]

    def _cut_plan(self, nm, poly_xy, z_top, depth, targets):
        """Grundrissfläche senkrecht von oben aus Körpern schneiden."""
        q = [[_r(x), _r(y)] for x, y in poly_xy]
        return [{"command": "sketch.create", "params": {
            "plane": {"origin": [0, 0, _r(z_top)], "x_dir": [1, 0, 0],
                      "y_dir": [0, 1, 0]}, "name": f"{nm} Skizze"}},
            {"command": "sketch.line", "params": {"points": q + [q[0]]}},
            {"command": "sketch.finish", "params": {}},
            {"command": "solid.extrude", "params": {
                "distance": _r(depth), "direction": "negative",
                "operation": "cut", "targets": targets, "name": nm}}]

    def _ring_walls(self, name, c, n, R, z0, h, t, hole=None, prefix="Wand"):
        """Vieleckwände (außen Radius R), stumpf gestoßen; hole(L, h) →
        Rechteck (x0, z0, x1, z1) in Wandkoordinaten oder None."""
        ang = [2 * math.pi * (i + 0.5) / n for i in range(n)]
        V = [np.array([c[0] + R * math.cos(q), c[1] + R * math.sin(q), z0])
             for q in ang]
        trim = t / math.sin(2 * math.pi / n)
        cmds, bodies = [], []
        for i in range(n):
            a, b = V[i], V[(i + 1) % n]
            mid = (a + b) / 2 - np.array([c[0], c[1], z0])
            n_out = _unit([mid[0], mid[1], 0])
            x = _unit(b - a)
            a = a + x * trim
            Z = np.array([0, 0, 1.0])
            pts = [a, b, b + Z * h, a + Z * h]
            holes = []
            if hole:
                L = float(np.linalg.norm(b - a))
                hr = hole(L, h)
                if hr:
                    x0, h0, x1, h1 = hr
                    holes = [[a + x * x0 + Z * h0, a + x * x1 + Z * h0,
                              a + x * x1 + Z * h1, a + x * x0 + Z * h1]]
            nm = f"{name} {prefix} {i + 1}"
            cmds += self._plate3d(nm, pts, n_out, t, inward=True, holes=holes)
            bodies.append(nm)
        return cmds, bodies

    def _zelt(self, name, c, n, R, z_eave, a, ov, t, prefix="Dach"):
        """Zeltdach aus n Dreiecken (Unterseite durch die Wandoberkanten)."""
        ang = [2 * math.pi * (i + 0.5) / n for i in range(n)]
        Ro = R + ov / math.cos(math.pi / n)
        ze = z_eave - ov * math.tan(a)
        apex = np.array([c[0], c[1],
                         z_eave + R * math.cos(math.pi / n) * math.tan(a)])
        Vo = [np.array([c[0] + Ro * math.cos(q), c[1] + Ro * math.sin(q), ze])
              for q in ang]
        cmds, bodies = [], []
        for i in range(n):
            p0, p1 = Vo[i], Vo[(i + 1) % n]
            mid = (p0 + p1) / 2 - np.array([c[0], c[1], ze])
            nh = _unit([mid[0], mid[1], 0])
            n_out = nh * math.sin(a) + np.array([0, 0, math.cos(a)])
            nm = f"{name} {prefix} {i + 1}"
            cmds += self._plate3d(nm, [p0, p1, apex], n_out, t)
            bodies.append(nm)
        return cmds, bodies, apex

    def _walm_plates(self, name, o, B, T, H, a, ov, t, prefix="Dach"):
        """Walm-/Zeltdach über dem Rechteck o…o+(B,T) mit Traufe auf H.
        B < T wird gedreht (First längs der längeren Seite)."""
        ta, s, c = math.tan(a), math.sin(a), math.cos(a)
        ze = H - ov * ta
        cmds, bodies = [], []

        def P(x, y, z):
            return np.array([o[0] + x, o[1] + y, o[2] + z], float)

        if B >= T:
            zr = H + T / 2 * ta
            e = [P(-ov, -ov, ze), P(B + ov, -ov, ze), P(B + ov, T + ov, ze),
                 P(-ov, T + ov, ze)]
            r = [P(T / 2, T / 2, zr), P(B - T / 2, T / 2, zr)]
            faces = [("vorn", [e[0], e[1], r[1], r[0]], [0, -s, c]),
                     ("hinten", [e[2], e[3], r[0], r[1]], [0, s, c]),
                     ("rechts", [e[1], e[2], r[1]], [s, 0, c]),
                     ("links", [e[3], e[0], r[0]], [-s, 0, c])]
        else:
            zr = H + B / 2 * ta
            e = [P(-ov, -ov, ze), P(B + ov, -ov, ze), P(B + ov, T + ov, ze),
                 P(-ov, T + ov, ze)]
            r = [P(B / 2, B / 2, zr), P(B / 2, T - B / 2, zr)]
            faces = [("vorn", [e[0], e[1], r[0]], [0, -s, c]),
                     ("hinten", [e[2], e[3], r[1]], [0, s, c]),
                     ("rechts", [e[1], e[2], r[1], r[0]], [s, 0, c]),
                     ("links", [e[3], e[0], r[0], r[1]], [-s, 0, c])]
        for nm, pts, n in faces:
            clean = [pts[0]]
            for q in pts[1:]:                          # Zelt: doppelte Punkte
                if np.linalg.norm(q - clean[-1]) > 1e-6:
                    clean.append(q)
            if len(clean) >= 3 and np.linalg.norm(clean[-1] - clean[0]) < 1e-6:
                clean.pop()
            if len(clean) < 3:
                continue
            full = f"{name} {prefix} {nm}"
            cmds += self._plate3d(full, clean, n, t)
            bodies.append(full)
        return cmds, bodies, zr

    def _kreuz(self, name, apex, h, t, a=None):
        """Kreuz als stehende Platte auf der Spitze (auf der Oberseite der
        Dachplatten, damit es nicht in sie hineinragt)."""
        if a is not None:
            apex = np.array(apex, float) + [0, 0, t / math.cos(a)]
        b = max(1.2, h * 0.12)
        arm = h * 0.6
        g = unary_union([box(-b / 2, 0, b / 2, h),
                         box(-arm / 2, h * 0.58, arm / 2, h * 0.58 + b)])
        ring = list(g.exterior.coords)[:-1]
        o = np.array(apex, float) - np.array([0, t / 2, 0])
        pts = [o + np.array([x, 0, z]) for x, z in ring]
        return self._plate3d(f"{name} Kreuz", pts, [0, 1, 0], t)

    # -------------------------------------------------- Ecktürmchen

    def ctx_ecktuerme(self):
        h = self._host()
        if h is None:
            raise RuntimeError("Erst einen Kasten oder ein Haus anlegen")
        return {"host": h["id"]}

    def cmds_ecktuerme(self, name, ctx, p):
        h = self._get(ctx["host"])
        hp = h["params"]
        t = p["staerke"]
        B, T, H = hp["breite"], hp["tiefe"], hp["hoehe"]
        o = np.array([hp.get("x", 0), hp.get("y", 0), hp.get("z", 0)], float)
        R = p["durchmesser"] / 2
        if p["auf"] == "krone":
            if h["typ"] == "haus" and hp["dach"] != "flach":
                raise RuntimeError("Auf der Krone nur bei Kasten oder "
                                   "Flachdach — sonst „boden“ wählen")
            z0 = o[2] + H + (hp.get("zinnen_h", 0) if h["typ"] == "haus"
                             and hp.get("zinnen") else 0)
            off = 0.0
        else:
            z0, off = o[2], R                      # außen an die Ecke
        hs = _lagen(p["hoehe"], t)
        ecken = [("vl", o[0] - off, o[1] - off), ("vr", o[0] + B + off,
                                                    o[1] - off),
                 ("hr", o[0] + B + off, o[1] + T + off),
                 ("hl", o[0] - off, o[1] + T + off)]
        cmds, bodies = [], []
        for tag, cx, cy in ecken:
            nm = f"{name} {tag}"
            cmds += self._solid_cmds(f"{nm} Schaft", "cylinder", radius=R,
                                     height=hs, base=[cx, cy, z0])
            bodies.append(f"{nm} Schaft")
            top = z0 + hs
            if p["dach"] == "zinnen":
                zh = _lagen(p["zinnen_h"], t)
                cmds += self._solid_cmds(f"{nm} Krone", "cylinder", radius=R,
                                         height=zh, base=[cx, cy, top])
                bodies.append(f"{nm} Krone")
                k = max(4, round(2 * math.pi * R / max(3.0, R * 0.8)))
                k += k % 2
                cuts = []
                for j in range(0, k, 2):
                    a0, a1 = 2 * math.pi * j / k, 2 * math.pi * (j + 1) / k
                    cuts.append([(cx + rr * math.cos(aa), cy + rr * math.sin(aa))
                                 for rr, aa in ((R * 0.45, a0), (R + 1, a0),
                                                (R + 1, a1), (R * 0.45, a1))])
                for j, poly in enumerate(cuts):
                    cmds += self._cut_plan(f"{nm} Zinne {j + 1}", poly,
                                           top + zh + 1, zh / 2 + 1,
                                           [f"{nm} Krone"])
            elif p["dach"] == "kegel":
                hc = _lagen((R + 1) * math.tan(math.radians(p["neigung"])), t)
                cmds += self._solid_cmds(f"{nm} Kegel", "cone", radius=R + 1,
                                         height=hc, base=[cx, cy, top])
                bodies.append(f"{nm} Kegel")
        return cmds, bodies, \
            f"4× Ø{2 * R:g}×{hs:g} ({p['auf']}, {p['dach']}) an {h['name']}"

    # -------------------------------------------------------- Podest

    def ctx_podest(self):
        h = self._host()
        return {"host": h["id"]} if h else {}

    def cmds_podest(self, name, ctx, p):
        t = p["staerke"]
        hp_ = _lagen(p["hoehe"], t)
        if ctx.get("host"):
            h = self._get(ctx["host"])["params"]
            B, T = h["breite"], h["tiefe"]
            o = np.array([h.get("x", 0), h.get("y", 0), h.get("z", 0)], float)
        else:
            B, T = p["breite"], p["tiefe"]
            o = np.array([p.get("x", 0), p.get("y", 0), hp_], float)
        r = p["rand"]
        lo = o + [-r, -r, -hp_]
        hi = o + [B + r, T + r, 0]
        cmds = self._box_plate(f"{name} Block", lo, hi)
        bodies = [f"{name} Block"]
        if p["treppe"]:
            n = int(round(hp_ / t))
            sw, tr = p["treppe_breite"], p["stufe"]
            x0 = o[0] + B / 2 - sw / 2
            yf, zb = lo[1], lo[2]
            prof = [(yf, zb), (yf - n * tr, zb)]
            for k in range(n):
                prof.append((yf - (n - k) * tr, zb + (k + 1) * t))
                if k < n - 1:
                    prof.append((yf - (n - k - 1) * tr, zb + (k + 1) * t))
            prof.append((yf, zb + n * t))
            pts = [np.array([x0, y, z]) for y, z in prof]
            cmds += self._plate3d(f"{name} Treppe", pts, [1, 0, 0], sw)
            bodies.append(f"{name} Treppe")
        return cmds, bodies, f"{hp_:g} hoch, Rand {r:g}" + (
            ", Treppe" if p["treppe"] else "")

    # ---------------------------------------------- Turmhelm + Kreuz

    def ctx_helm(self):
        h = self._host(("turm", "rundturm"))
        if h is None:
            raise RuntimeError("Erst einen Turm anlegen (oder anklicken)")
        return {"host": h["id"]}

    def cmds_helm(self, name, ctx, p):
        h = self._get(ctx["host"])
        hp = h["params"]
        if hp["dach"] in ("zelt", "kegel"):
            raise RuntimeError("Der Turm hat schon ein Spitzdach — dort "
                               "„flach“ oder „zinnen“ wählen")
        t = p["staerke"]
        c = np.array([hp.get("x", 0), hp.get("y", 0), hp.get("z", 0)], float)
        R = hp["durchmesser"] / 2
        n = int(hp.get("ecken", 16))
        zb = c[2] + hp["hoehe"] + (hp.get("zinnen_h", 0)
                                   if hp["dach"] == "zinnen" else 0)
        a = math.atan(p["hoehe"] / (R * math.cos(math.pi / n)))
        cmds, bodies, apex = self._zelt(name, c, n, R, zb, a, p["ueberstand"],
                                        t, prefix="Helm")
        if p["kreuz"]:
            cmds += self._kreuz(name, apex, p["kreuz_h"], t, a)
            bodies.append(f"{name} Kreuz")
        return cmds, bodies, f"{p['hoehe']:g} hoch auf {h['name']}" + (
            " + Kreuz" if p["kreuz"] else "")

    # ---------------------------------------------------- Dachreiter

    def ctx_dachreiter(self):
        h = self._host(("haus",))
        if h is None or h["params"]["dach"] != "sattel":
            raise RuntimeError("Dachreiter braucht ein Haus mit Satteldach")
        return {"host": h["id"]}

    def cmds_dachreiter(self, name, ctx, p):
        h = self._get(ctx["host"])
        hp = h["params"]
        B, T, H, t, a, ta, _ov = self._haus_geom(hp)
        ca = math.cos(a)
        o = np.array([hp.get("x", 0), hp.get("y", 0), hp.get("z", 0)], float)
        top = lambda y: H + min(y, T - y) * ta + t / ca     # noqa: E731
        w, d = p["breite"], p["tiefe"]
        x0, x1 = p["x"] - w / 2, p["x"] + w / 2
        y0, y1 = T / 2 - d / 2, T / 2 + d / 2
        tk = p["staerke"]
        zb = top(y0 + tk) + 0.2
        zt = top(T / 2) + p["hoehe"]
        W = lambda x, y, z: o + [x, y, z]                  # noqa: E731
        cmds, bodies = [], []
        for nm, yy, n_out in (("vorn", y0, [0, -1, 0]),
                              ("hinten", y1, [0, 1, 0])):
            pts = [W(x0, yy, zb), W(x1, yy, zb), W(x1, yy, zt), W(x0, yy, zt)]
            cmds += self._plate3d(f"{name} {nm}", pts, n_out, tk, inward=True)
            bodies.append(f"{name} {nm}")
        for nm, xx, n_out in (("links", x0, [-1, 0, 0]),
                              ("rechts", x1, [1, 0, 0])):
            ya, yb = y0 + tk, y1 - tk
            pts = [W(xx, ya, top(ya) + 0.2), W(xx, T / 2, top(T / 2) + 0.2),
                   W(xx, yb, top(yb) + 0.2), W(xx, yb, zt), W(xx, ya, zt)]
            cmds += self._plate3d(f"{name} {nm}", pts, n_out, tk, inward=True)
            bodies.append(f"{name} {nm}")
        c2, b2, zr = self._walm_plates(name, o + [x0, y0, 0], w, d, zt,
                                       math.radians(p["neigung"]),
                                       p["ueberstand"], tk)
        cmds += c2
        bodies += b2
        if p["kreuz"]:
            apex = o + [p["x"], T / 2, zr]
            cmds += self._kreuz(name, apex, p["kreuz_h"], tk,
                                math.radians(p["neigung"]))
            bodies.append(f"{name} Kreuz")
        return cmds, bodies, f"{w:g}×{d:g}, {p['hoehe']:g} über First auf " \
            f"{h['name']}"

    # -------------------------------------------------- Zwerchgiebel

    def ctx_zwerch(self):
        return self.ctx_gaube()

    def cmds_zwerch(self, name, ctx, p):
        return self._giebelgaube(name, ctx, p, zwerch=True)

    # ---------------------------------------------------------- Apsis

    def cmds_apsis(self, name, ctx, p):
        P, R_, U, N = (np.array(ctx[k], float) for k in ("p", "right", "up",
                                                          "n"))
        t, n = p["staerke"], int(p["segmente"])
        r = p["breite"] / 2
        y0 = ctx["bounds"][1]
        H = p["hoehe"]
        a = math.radians(p["neigung"])
        c = P + R_ * p["x"] + U * y0
        phis = [math.pi * k / n for k in range(n + 1)]
        V = [c + R_ * (r * math.cos(f)) + N * (r * math.sin(f)) for f in phis]
        trim = t / math.sin(math.pi / n)
        cmds, bodies = [], []
        for k in range(n):
            a0, b0 = V[k], V[k + 1]
            fm = (phis[k] + phis[k + 1]) / 2
            n_out = R_ * math.cos(fm) + N * math.sin(fm)
            x = _unit(b0 - a0)
            if k > 0:
                a0 = a0 + x * trim
            else:                                   # innen nicht hinter
                a0 = a0 + x * (t * (n_out @ N) / (x @ N))   # die Hauswand
            if k == n - 1:
                b0 = b0 - x * (t * (n_out @ N) / -(x @ N))
            pts = [a0, b0, b0 + U * H, a0 + U * H]
            nm = f"{name} Wand {k + 1}"
            cmds += self._plate3d(nm, pts, n_out, t, inward=True)
            bodies.append(nm)
        ov = p["ueberstand"]
        ap = r * math.cos(math.pi / (2 * n))
        top_max = ctx["bounds"][3] - 8 - y0       # Platz für Dachüberstand
        info_a = ""
        if H + ap * math.tan(a) > top_max:
            if top_max - H < 2:
                raise RuntimeError("Apsis zu hoch für diese Wand")
            a = math.atan((top_max - H) / ap)
            info_a = f", Neigung auf {math.degrees(a):.0f}° begrenzt"
        Ro = r + ov / math.cos(math.pi / (2 * n))
        ze = H - ov * math.tan(a)
        apex = c + U * (H + ap * math.tan(a))
        E = [c + R_ * (Ro * math.cos(f)) + N * (Ro * math.sin(f)) + U * ze
             for f in phis]
        for k in range(n):
            e0, e1 = E[k], E[k + 1]
            nn = np.cross(e1 - e0, apex - e0)
            nn = _unit(nn)
            if nn @ U < 0:
                nn = -nn
            nm = f"{name} Dach {k + 1}"
            cmds += self._plate3d(nm, [e0, e1, apex], nn, t)
            bodies.append(nm)
        return cmds, bodies, f"Ø{2 * r:g}, {n} Segmente, {H:g} hoch an " \
            f"{ctx['wall']}{info_a}"

    def fp_apsis(self, el):
        ctx, p = el["ctx"], el["params"]
        r = p["breite"] / 2 + p["ueberstand"]
        y0 = ctx["bounds"][1]
        return [(ctx, box(p["x"] - r, y0 - 50, p["x"] + r,
                          y0 + p["hoehe"] + r * 2))]

    # ------------------------------------------------------ Windmühle

    def ctx_muehle(self):
        return {}

    def cmds_muehle(self, name, ctx, p):
        t, n = p["staerke"], int(p["ecken"])
        c = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        R, H = p["durchmesser"] / 2, p["hoehe"]
        cmds, bodies = self._ring_walls(name, c, n, R, c[2], H, t)
        Ri = R - t / math.cos(math.pi / n)
        ang = [2 * math.pi * (i + 0.5) / n for i in range(n)]
        Vi = [c + [Ri * math.cos(q), Ri * math.sin(q), 0] for q in ang]
        cmds += self._plate3d(f"{name} Boden", Vi, [0, 0, 1], t)
        bodies.append(f"{name} Boden")
        cmds += self._plate3d(f"{name} Decke",
                              [v + [0, 0, H - t] for v in Vi], [0, 0, 1], t)
        bodies.append(f"{name} Decke")
        # Haube: massive Kuppel (Scheibenbau)
        Rh = R + 2
        hh = _lagen(p["haube_h"], t)
        prof = [(0.001, c[2] + H)] + [
            (Rh * math.cos(th), c[2] + H + hh * math.sin(th))
            for th in np.linspace(0, math.pi / 2, 24)][:-1] + \
            [(0.001, c[2] + H + hh)]
        cmds += self._revolve(f"{name} Haube", c, prof)
        bodies.append(f"{name} Haube")
        # Flügel: eine stehende Platte vor der Haube
        L, bw = p["fluegel"], p["fluegel"] * 0.2
        blades = []
        for k in range(4):
            ang_ = math.pi / 4 + k * math.pi / 2
            d = np.array([math.cos(ang_), math.sin(ang_)])
            nrm = np.array([-d[1], d[0]])
            q0, q1 = d * 4, d * L
            frame = Polygon([tuple(q0 - nrm * bw / 2), tuple(q1 - nrm * bw / 2),
                             tuple(q1 + nrm * bw / 2),
                             tuple(q0 + nrm * bw / 2)])
            holes = []
            m = 1.2
            cells = max(2, int((L - 8) // (bw * 0.9)))
            for j in range(cells):
                s0 = 8 + j * (L - 10) / cells + m / 2
                s1 = 8 + (j + 1) * (L - 10) / cells - m / 2
                for side in (-1, 1):
                    w0 = side * m / 2
                    w1 = side * (bw / 2 - m)
                    lo_, hi_ = min(w0, w1), max(w0, w1)
                    holes.append(Polygon([
                        tuple(d * s0 + nrm * lo_), tuple(d * s1 + nrm * lo_),
                        tuple(d * s1 + nrm * hi_), tuple(d * s0 + nrm * hi_)]))
            blades.append(frame.difference(unary_union(holes)))
        hub = Polygon(G.arch_poly(0, -5, 10, 5, "rund"))
        sail = unary_union(blades + [hub]).buffer(0)
        zc = c[2] + H + hh * 0.5
        yf = c[1] - Rh * math.cos(math.asin(0.5)) - 0.5
        from .laser_geom import polys_of
        outer, holes = polys_of(sail)[0]
        to3 = lambda q: np.array([c[0] + q[0], yf, zc + q[1]])  # noqa: E731
        cmds += self._plate3d(f"{name} Flügel", [to3(q) for q in outer],
                              [0, -1, 0], t,
                              holes=[[to3(q) for q in hl] for hl in holes])
        bodies.append(f"{name} Flügel")
        return cmds, bodies, f"{n}-Eck Ø{2 * R:g}×{H:g}, Flügel {L:g}"

    # ----------------------------------------------------- Leuchtturm

    def ctx_leuchtturm(self):
        return {}

    def cmds_leuchtturm(self, name, ctx, p):
        t, n = p["staerke"], int(p["ecken"])
        c = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        R, H = p["durchmesser"] / 2, p["hoehe"]
        cmds, bodies = self._ring_walls(name, c, n, R, c[2], H, t)
        # Galerie (volle Scheibe auf den Wänden)
        Rg = R + p["umgang"]
        disk = lambda rr, zz, nm: self._plate3d(            # noqa: E731
            nm, [c + [rr * math.cos(2 * math.pi * i / 48),
                      rr * math.sin(2 * math.pi * i / 48), zz]
                 for i in range(48)], [0, 0, 1], t)
        cmds += disk(Rg, c[2] + H, f"{name} Galerie")
        bodies.append(f"{name} Galerie")
        zg = c[2] + H + t
        # Geländer: Vieleck mit Fenstern (Pfosten bleiben stehen)
        ng = max(8, n * 2)
        gh = 5.0
        c2, b2 = self._ring_walls(
            name, c, ng, Rg - 0.3, zg, gh, t,
            hole=lambda L, h: (1.2, 1.2, L - 1.2, h - 1.2) if L > 4 else None,
            prefix="Geländer")
        cmds += c2
        bodies += b2
        # Laterne mit Fenstern und Zeltdach
        Rl = p["laterne_d"] / 2
        lh = p["laterne_h"]
        c3, b3 = self._ring_walls(
            name, c, n, Rl, zg, lh, t,
            hole=lambda L, h: (1.2, 1.5, L - 1.2, h - 1.5) if L > 4 else None,
            prefix="Laterne")
        cmds += c3
        bodies += b3
        c4, b4, apex = self._zelt(name, c, n, Rl, zg + lh, math.radians(55),
                                  1.5, t, prefix="Kappe")
        cmds += c4
        bodies += b4
        return cmds, bodies, f"{n}-Eck Ø{2 * R:g}×{H:g}, Galerie, Laterne"

    # ---------------------------------------------------- Steinbrücke

    def ctx_steinbruecke(self):
        return {}

    def _sb_geom(self, p):
        L, W, h, n = p["laenge"], p["breite"], p["hoehe"], int(p["boegen"])
        t = p["staerke"]
        sb = L / (n + 0.3 * (n + 1))
        pw = 0.3 * sb
        ks = max(0.0, h - t - 3 - sb / 2)
        xs = [pw + sb / 2 + i * (sb + pw) for i in range(n)]
        return L, W, h, n, t, sb, pw, ks, xs

    def cmds_steinbruecke(self, name, ctx, p):
        L, W, h, n, t, sb, pw, ks, xs = self._sb_geom(p)
        o = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        side = box(0, 0, L, h + p["bruestung"]).difference(unary_union(
            [Polygon(G.arch_poly(x, -1, sb, ks + sb / 2, "bogen"))
             for x in xs]))
        from .laser_geom import polys_of
        cmds, bodies = [], []
        for nm, yy, n_out in (("Wand vorn", 0.0, [0, -1, 0]),
                              ("Wand hinten", W, [0, 1, 0])):
            outer, holes = polys_of(side)[0]
            to3 = lambda q, yy=yy: o + [q[0], yy, q[1]]       # noqa: E731
            cmds += self._plate3d(f"{name} {nm}", [to3(q) for q in outer],
                                  n_out, t, inward=True,
                                  holes=[[to3(q) for q in hl] for hl in holes])
            bodies.append(f"{name} {nm}")
        cmds += self._box_plate(f"{name} Fahrbahn", o + [0, t, h - t],
                                o + [L, W - t, h])
        bodies.append(f"{name} Fahrbahn")
        for i, x in enumerate(xs):                  # Gewölbe (gebogen)
            ro, ri = sb / 2, sb / 2 - t
            prof = [(x + ro * math.cos(a_), ks + ro * math.sin(a_))
                    for a_ in np.linspace(0, math.pi, 33)] + \
                   [(x + ri * math.cos(a_), ks + ri * math.sin(a_))
                    for a_ in np.linspace(math.pi, 0, 33)]
            pts = [o + [xx, t, zz] for xx, zz in prof]
            nm = f"{name} Gewölbe {i + 1}"
            cmds += self._plate3d(nm, pts, [0, 1, 0], W - 2 * t)
            bodies.append(nm)
        return cmds, bodies, f"{L:g}×{W:g}, {n} Bögen"

    def flat_steinbruecke(self, el):
        p = el["params"]
        L, W, h, n, t, sb, pw, ks, xs = self._sb_geom(p)
        from .laser_extra import hinge_slots
        out = []
        La = math.pi * (sb / 2 - t / 2)
        for i in range(n):
            strip = box(0, 0, La, W - 2 * t)
            slots = hinge_slots(La, W - 2 * t, 12.0, 3.0, 1.5, 0.5)
            out.append((f"{el['name']} Gewölbe {i + 1}",
                        strip.difference(slots), []))
        return out

    # ------------------------------------------------ Fachwerkbrücke

    def ctx_fachwerkbruecke(self):
        return {}

    def cmds_fachwerkbruecke(self, name, ctx, p):
        L, W, ht = p["laenge"], p["breite"], p["hoehe"]
        n, sw, t = int(p["felder"]), p["stab"], p["staerke"]
        o = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        pw = L / n
        members = []
        for i in range(n):
            x0, x1 = i * pw, (i + 1) * pw
            if i % 2 == 0:
                members.append(LineString([(x0, 0), (x1, ht)]))
            else:
                members.append(LineString([(x0, ht), (x1, 0)]))
            members.append(LineString([(x1, 0), (x1, ht)]))
        bars = unary_union([m.buffer(sw / 2, cap_style=2) for m in members])
        inner = box(sw, sw, L - sw, ht - sw)
        truss = box(0, 0, L, ht).difference(inner.difference(bars))
        from .laser_geom import polys_of
        cmds, bodies = [], []
        for nm, yy, n_out in (("Träger vorn", 0.0, [0, -1, 0]),
                              ("Träger hinten", W, [0, 1, 0])):
            outer, holes = polys_of(truss)[0]
            to3 = lambda q, yy=yy: o + [q[0], yy, t + q[1]]   # noqa: E731
            cmds += self._plate3d(f"{name} {nm}", [to3(q) for q in outer],
                                  n_out, t, inward=True,
                                  holes=[[to3(q) for q in hl] for hl in holes])
            bodies.append(f"{name} {nm}")
        cmds += self._box_plate(f"{name} Fahrbahn", o, o + [L, W, t])
        bodies.append(f"{name} Fahrbahn")
        ha = _lagen(p["auflage"], t)
        for nm, x0 in (("Auflager links", 0.0), ("Auflager rechts", L - 6)):
            cmds += self._box_plate(f"{name} {nm}", o + [x0, 0, -ha],
                                    o + [x0 + 6, W, 0])
            bodies.append(f"{name} {nm}")
        return cmds, bodies, f"{L:g}×{W:g}, {n} Felder"

    # --------------------------------------------------------- Pagode

    def ctx_pagode(self):
        return {}

    def cmds_pagode(self, name, ctx, p):
        n, t = int(p["stockwerke"]), p["staerke"]
        a = math.radians(p["neigung"])
        ta = math.tan(a)
        s, c_ = math.sin(a), math.cos(a)
        cx = p.get("x", 0) + p["breite"] / 2
        cy = p.get("y", 0) + p["tiefe"] / 2
        z = p.get("z", 0)
        cmds, bodies = [], []
        dims = [(p["breite"] * p["schrumpf"] ** k, p["tiefe"] * p["schrumpf"]
                 ** k) for k in range(n)]
        for k, (B, T) in enumerate(dims):
            hgt = p["geschoss"] * (0.85 ** k)
            o = np.array([cx - B / 2, cy - T / 2, z])
            tag = f"{name} G{k + 1}"
            if k == 0:
                cmds += self._box_plate(f"{tag} Boden", o + [t, t, 0],
                                        o + [B - t, T - t, t])
                bodies.append(f"{tag} Boden")
            walls = [("vorn", o, o + [B, t, hgt]),
                     ("hinten", o + [0, T - t, 0], o + [B, T, hgt]),
                     ("links", o + [0, t, 0], o + [t, T - t, hgt]),
                     ("rechts", o + [B - t, t, 0], o + [B, T - t, hgt])]
            for nm, lo, hi in walls:
                cmds += self._box_plate(f"{tag} {nm}", lo, hi)
                bodies.append(f"{tag} {nm}")
            ov = p["ueberstand"] * (0.85 ** k)
            H = hgt
            if k < n - 1:
                Bn, Tn = dims[k + 1]
                d = min((B - Bn) / 2, (T - Tn) / 2) - 1
                zt = H + d * ta
                ze = H - ov * ta

                def P(x, y, zz, o=o):
                    return o + [x, y, zz]

                e = [P(-ov, -ov, ze), P(B + ov, -ov, ze), P(B + ov, T + ov, ze),
                     P(-ov, T + ov, ze)]
                i_ = [P(d, d, zt), P(B - d, d, zt), P(B - d, T - d, zt),
                      P(d, T - d, zt)]
                faces = [("vorn", [e[0], e[1], i_[1], i_[0]], [0, -s, c_]),
                         ("rechts", [e[1], e[2], i_[2], i_[1]], [s, 0, c_]),
                         ("hinten", [e[2], e[3], i_[3], i_[2]], [0, s, c_]),
                         ("links", [e[3], e[0], i_[0], i_[3]], [-s, 0, c_])]
                for nm, pts, nn in faces:
                    cmds += self._plate3d(f"{tag} Dach {nm}", pts, nn, t)
                    bodies.append(f"{tag} Dach {nm}")
                cmds += self._box_plate(f"{tag} Kragplatte",
                                        o + [d, d, zt], o + [B - d, T - d,
                                                             zt + t])
                bodies.append(f"{tag} Kragplatte")
                z = z + zt + t
            else:
                c2, b2, zr = self._walm_plates(tag, o, B, T, H, a, ov, t)
                cmds += c2
                bodies += b2
                if p["spitze"]:
                    apex = np.array([cx, cy, z + zr])
                    cmds += self._kreuz(tag, apex, max(6.0, B * 0.3), t, a)
                    bodies.append(f"{tag} Kreuz")
        return cmds, bodies, f"{n} Geschosse, {p['breite']:g}×" \
            f"{p['tiefe']:g}"
