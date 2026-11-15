"""Wand-Elemente der Laser-Palette (wie im bausatzmaker): Muster, Fenster,
Tür/Tor, Blende/Nischenreihe, Uhr, Strebepfeiler, Bänder (Gesims, Sockel,
Traufgesims, Rundbogenfries) und Eckquader.

Alles sitzt in Wandkoordinaten: Ursprung `p`, x = `right`, y = `up`, die
Außennormale zeigt aus der Wand. Aufgesetztes ist ein eigener Körper (eine
Lage = Materialstärke), Gravur ist eine 0,2 mm tiefe Rille entlang echter
Skizzenlinien — der Export macht daraus wieder einzelne Gravurlinien.
"""

from __future__ import annotations

import zlib

import numpy as np
from shapely.geometry import Polygon, box
from shapely.ops import unary_union

from . import laser_geom as G

GROOVE_DEPTH = 0.2
GRAVUR = " Gravur"          # Namensendung der Rillen-Features (Schalter)
GROOVE_WIDTH = 0.3


def _r(v, n=4):
    return round(float(v), n)


def _pts(p):
    return [[_r(x), _r(y)] for x, y in p]


def _f(v):
    return [round(float(x), 6) for x in v]


def wire_geom(shape, o, right, up):
    """Kanten einer ebenen Form → shapely-Fläche in (o, right, up).

    OpenCASCADE verbindet die Kanten zu Drahtzügen (Toleranz 1 µm); jeder
    geschlossene Zug wird in seiner Reihenfolge abgetastet und als Ring
    genommen. Gerade/ungerade über alle Ringe ergibt Umriss mit Löchern."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.ShapeAnalysis import ShapeAnalysis_FreeBounds
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    from OCP.TopTools import TopTools_HSequenceOfShape
    o, right, up = (np.asarray(v, float) for v in (o, right, up))
    edges = TopTools_HSequenceOfShape()
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        edges.Append(exp.Current())
        exp.Next()
    wires = TopTools_HSequenceOfShape()
    ShapeAnalysis_FreeBounds.ConnectEdgesToWires_s(edges, 1e-3, False, wires)
    geom = Polygon()
    for i in range(1, wires.Length() + 1):
        w = TopoDS.Wire_s(wires.Value(i))
        ring = []
        we = BRepTools_WireExplorer(w)
        while we.More():
            e = we.Current()
            c = BRepAdaptor_Curve(e)
            d = GCPnts_QuasiUniformDeflection(c, 0.01)
            pts = [c.Value(d.Parameter(k)) for k in range(1, d.NbPoints() + 1)]
            if e.Orientation() == TopAbs_REVERSED:
                pts.reverse()
            for q in pts:
                v = np.array([q.X(), q.Y(), q.Z()]) - o
                ring.append((float(v @ right), float(v @ up)))
            we.Next()
        if len(ring) >= 3:
            pg = Polygon(ring).buffer(0)
            if pg.area > 1e-6:
                geom = geom.symmetric_difference(pg)
    return geom


def plate_section(shape, at, n, o, right, up):
    """Schnitt der Platte in der Ebene durch `at` mit Normale `n` →
    shapely-Fläche in (o, right, up): Umriss + Durchbrüche, ohne Rillen."""
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Section
    from OCP.gp import gp_Dir, gp_Pln, gp_Pnt
    sec = BRepAlgoAPI_Section(shape, gp_Pln(gp_Pnt(*map(float, at)),
                                            gp_Dir(*map(float, n))))
    sec.Build()
    return wire_geom(sec.Shape(), o, right, up)


class WandMixin:
    """Wird in `Laser` gemischt; nutzt dessen batch/shape/selection."""

    # -- Kontext

    def ctx_wand(self):
        sel = [x for x in self.selection() if x.get("type") == "face"]
        if not sel:
            raise RuntimeError("Wandfläche in SolidCraft anklicken")
        f = sel[0]
        wall = f["body"]
        p = np.array(f.get("point") or [0, 0, 0], float)
        s = self.shape(wall)
        from .laser import _frame_up, _vertices, plate_info
        info = plate_info(s)
        if info is None:
            raise RuntimeError(f"{wall} ist keine ebene Platte")
        # Normale von der Platte, nicht von der Klickfläche (die kann eine
        # Fugenflanke oder ein einzelner Ziegel sein); Seite = näher am Klick
        n = np.array(info["normal"], float)
        d = _vertices(s) @ n
        if abs(p @ n - d.min()) < abs(p @ n - d.max()):
            n = -n
            d = -d
        p = p + n * (d.max() - p @ n)          # auf die Außenfläche
        right, up = _frame_up(n)
        g = plate_section(s, p - n * (d.max() - d.min()) / 2, n, p, right, up)
        x0, y0, x1, y1 = g.bounds
        ctx = {"wall": wall, "p": _f(p), "right": _f(right), "up": _f(up),
               "n": _f(n), "thickness": _r(info["thickness"]),
               "face": [_pts(o) for o, _h in G.polys_of(g)][:1],
               "bounds": [_r(x0), _r(y0), _r(x1), _r(y1)]}
        k = self._kasten_of(wall)
        if k:
            ctx["kasten"] = k
        return ctx

    def _kasten_of(self, body):
        for e in self.elements():
            if e["typ"] in ("kasten", "haus") and body in e.get("bodies", []):
                return e["id"]
        return None

    def _face_geom(self, ctx):
        """Wandfläche frisch aus dem Körper (folgt Maßänderungen), sonst
        der beim Anlegen gemerkte Umriss."""
        try:
            s = self.shape(ctx["wall"])
            n = np.array(ctx["n"], float)
            P = np.array(ctx["p"], float)
            g = plate_section(s, P - n * ctx["thickness"] / 2, n, P,
                              ctx["right"], ctx["up"])
            if not g.is_empty:
                return g
        except Exception:                     # noqa: BLE001
            pass
        if ctx.get("face"):
            return Polygon(ctx["face"][0]).buffer(0)
        return box(*ctx["bounds"])

    def kasten_walls(self, el):
        """Vier Außenwände eines Kastens/Hauses als Wand-Kontexte (ohne
        Auswahl). Front/Rück zuerst — sie bekommen bei Bändern die Ecken."""
        p = el["params"]
        B, T, H = p["breite"], p["tiefe"], p["hoehe"]
        o = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        t = p["staerke"]
        nm = el["name"]
        walls = [("Front", [0, -1, 0], [1, 0, 0], o, B),
                 ("Rueckwand", [0, 1, 0], [-1, 0, 0], o + [B, T, 0], B),
                 ("Seite links", [-1, 0, 0], [0, -1, 0], o + [0, T, 0], T),
                 ("Seite rechts", [1, 0, 0], [0, 1, 0], o + [B, 0, 0], T)]
        out = []
        for name, n, r, po, L in walls:
            out.append({"wall": f"{nm} {name}", "p": _f(po), "right": r,
                        "up": [0, 0, 1], "n": n, "thickness": t,
                        "bounds": [0, 0, L, H], "ecke": name in
                        ("Front", "Rueckwand"), "kasten": el["id"]})
        return out

    def _walls_for(self, ctx, rundum):
        if rundum and ctx.get("kasten"):
            el = next((e for e in self.elements()
                       if e["id"] == ctx["kasten"]), None)
            if el:
                return self.kasten_walls(el)
        return [dict(ctx, ecke=False)]

    # -- Befehlsbausteine

    def _sketch(self, ctx, name, polys=(), lines=(), offset=0.0):
        o = np.array(ctx["p"]) + np.array(ctx["n"]) * offset
        cmds = [{"command": "sketch.create", "params": {
            "plane": {"origin": _f(o), "x_dir": _f(ctx["right"]),
                      "y_dir": _f(ctx["up"])}, "name": name}}]
        for outer, holes in polys:
            for loop in [outer, *holes]:
                cmds.append({"command": "sketch.line", "params": {
                    "points": _pts(list(loop) + [loop[0]])}})
        for ln in lines:
            cmds.append({"command": "sketch.line",
                         "params": {"points": _pts(ln)}})
        cmds.append({"command": "sketch.finish", "params": {}})
        return cmds

    def _plate_on(self, ctx, name, geom, lagen, staerke, offset=0.0,
                  inward=False):
        """Fläche (shapely) als aufgesetzte Platte(n) vor der Wand.
        Splitter unter 0,8 mm Breite / 1 mm² fallen weg (nicht laserbar)."""
        geom = geom.buffer(-0.4, join_style=2).buffer(0.4, join_style=2)
        polys = [(o, h) for o, h in G.polys_of(geom)
                 if Polygon(o, h).area >= 1.0]
        if not polys:
            return []
        cmds = self._sketch(ctx, f"{name} Skizze", polys, offset=offset)
        cmds.append({"command": "solid.extrude", "params": {
            "distance": _r(staerke * lagen), "operation": "new",
            "direction": "negative" if inward else "positive",
            "body_name": name, "name": name}})
        return cmds

    def _groove(self, ctx, name, lines, target, offset=0.0, tiefe=None,
                linie=None):
        lines = [ln for ln in lines if len(ln) >= 2]
        if not lines:
            return []
        cmds = self._sketch(ctx, f"{name} Skizze", lines=lines,
                            offset=offset)
        if not getattr(self, "_rillen", False):
            return cmds                         # nur Linien (schnell)
        cmds.append({"command": "solid.extrude", "params": {
            "thin": True, "thickness": _r(linie or GROOVE_WIDTH),
            "distance": _r(tiefe or GROOVE_DEPTH), "direction": "negative",
            "operation": "cut", "targets": [target],
            "name": name + GRAVUR}})
        return cmds

    def _cut_through(self, ctx, name, geom):
        polys = G.polys_of(geom)
        if not polys:
            return []
        cmds = self._sketch(ctx, f"{name} Skizze", polys)
        cmds.append({"command": "solid.extrude", "params": {
            "distance": _r(ctx["thickness"] + 1), "direction": "negative",
            "operation": "cut", "targets": [ctx["wall"]], "name": name}})
        return cmds

    # -- Muster

    def _muster_area(self, ctx, p):
        area = self._face_geom(ctx)
        if p["bereich"] == "feld":
            h2 = p["hoehe"] / 2
            fld = Polygon(G.arch_poly(p["x"], p["y"] - h2, p["breite"],
                                      p["y"] + h2, p.get("form", "rechteck")))
            area = area.intersection(fld) if not area.is_empty else fld
        return area

    def engr_muster(self, el):
        ctx, p = el["ctx"], el["params"]
        area = self._muster_area(ctx, p)
        lines = G.pattern(p["muster"], area, p["stein_h"], p["stein_l"],
                          seed=zlib.crc32(el["name"].encode()))
        if p["rand"] and p["bereich"] == "feld":
            lines += G.lines_of(area.boundary)
        return [(ctx["wall"], ctx, 0.0, lines)]

    def cmds_muster(self, name, ctx, p):
        (_b, _c, _o, lines), = self.engr_muster(
            {"name": name, "ctx": ctx, "params": p})
        if not lines:
            raise RuntimeError("Muster ergibt keine Linien (Putz oder "
                               "leere Fläche)")
        cmds = self._groove(ctx, name, lines, ctx["wall"], tiefe=p["tiefe"])
        return cmds, [ctx["wall"]], \
            f"{p['muster']} auf {ctx['wall']}, {len(lines)} Linien"

    # -- Öffnungen

    def _opening(self, p, y0=None):
        cx = p["x"]
        if y0 is None:
            y0 = p["y"] - p["hoehe"] / 2
        h = p["breite"] if p["form"] == "rund" else p["hoehe"]
        return Polygon(G.arch_poly(cx, y0, p["breite"], y0 + h, p["form"]))

    def cmds_fenster(self, name, ctx, p):
        opening = self._opening(p)
        cmds = []
        if p["oeffnung"]:
            cmds += self._cut_through(ctx, f"{name} Öffnung", opening)
        R, sp = p["rahmen"], p["sprosse"]
        outer = opening.buffer(R, join_style=2) if R > 0 else opening
        if p.get("sims"):
            x0, y0, x1, _y1 = outer.bounds
            outer = outer.union(box(x0 - 2.5, y0 - 1.5, x1 + 2.5, y0 + 0.5))
        bars = []
        x0, y0, x1, y1 = opening.bounds
        nv, nh = int(p["sprossen_v"]), int(p["sprossen_h"])
        for i in range(1, nv + 1):
            x = x0 + (x1 - x0) * i / (nv + 1)
            bars.append(box(x - sp / 2, y0 - 1, x + sp / 2, y1 + 1))
        for j in range(1, nh + 1):
            y = y0 + (y1 - y0) * j / (nh + 1)
            bars.append(box(x0 - 1, y - sp / 2, x1 + 1, y + sp / 2))
        panes = opening.difference(unary_union(bars)) if bars else opening
        frame = outer.difference(panes)
        bodies = [ctx["wall"]]
        if not frame.is_empty and frame.area > 0.01:
            cmds += self._plate_on(ctx, f"{name} Rahmen", frame, p["lagen"],
                                   p["staerke"])
            bodies.append(f"{name} Rahmen")
        sprossen = f", Sprossen {nv}×{nh}" if nv or nh else ""
        return cmds, bodies, \
            f"{p['form']} {p['breite']:g}×{p['hoehe']:g} auf {ctx['wall']}" \
            f"{sprossen}"

    def _door(self, ctx, p):
        y0 = ctx["bounds"][1]
        if ctx.get("kasten"):                   # Schwelle auf dem Boden
            y0 += ctx["thickness"]
        return self._opening(dict(p, form=p["form"] if p["form"] != "rund"
                                  else "bogen"), y0=y0), y0

    def engr_tuer(self, el):
        ctx, p = el["ctx"], el["params"]
        if not (p["blatt"] and p["bretter"]):
            return []
        opening, _y0 = self._door(ctx, p)
        leaf = opening.buffer(1.5, join_style=2)
        x0, y0, x1, y1 = leaf.bounds
        lines = [[(x, y0 - 1), (x, y1 + 1)]
                 for x in np.arange(x0 + p["brett"], x1, p["brett"])]
        return [(f"{el['name']} Blatt", ctx, -ctx["thickness"],
                 G.clip(lines, leaf))]

    def cmds_tuer(self, name, ctx, p):
        opening, y0 = self._door(ctx, p)
        x0, _b, x1, _t = opening.bounds
        # bis ganz unten offen (sonst bleibt ein loser Zapfen unter der Tür)
        opening_cut = opening.union(box(x0, ctx["bounds"][1] - 1, x1, y0 + 1))
        cmds = self._cut_through(ctx, f"{name} Öffnung", opening_cut)
        bodies = [ctx["wall"]]
        R = p["rahmen"]
        if R > 0:
            frame = opening.buffer(R, join_style=2).difference(opening)
            frame = frame.intersection(box(-1e4, y0, 1e4, 1e4))
            cmds += self._plate_on(ctx, f"{name} Rahmen", frame, p["lagen"],
                                   p["staerke"])
            bodies.append(f"{name} Rahmen")
        if p["blatt"]:
            leaf = opening.buffer(1.5, join_style=2).intersection(
                box(-1e4, y0, 1e4, 1e4))
            cmds += self._plate_on(ctx, f"{name} Blatt", leaf, 1,
                                   p["staerke"], offset=-ctx["thickness"],
                                   inward=True)
            bodies.append(f"{name} Blatt")
            for body, c2, off, lines in self.engr_tuer(
                    {"name": name, "ctx": ctx, "params": p}):
                cmds += self._groove(c2, f"{name} Bretter", lines, body,
                                     offset=off)
        art = "Tor" if not p["blatt"] else "Tür"
        return cmds, bodies, \
            f"{art} {p['form']} {p['breite']:g}×{p['hoehe']:g} auf " \
            f"{ctx['wall']}"

    def cmds_blende(self, name, ctx, p):
        n = int(p["anzahl"])
        niches = [self._opening(dict(p, x=p["x"] + (i - (n - 1) / 2)
                                     * p["abstand"])) for i in range(n)]
        plate = unary_union([q.buffer(p["rand"], join_style=2)
                             for q in niches]).difference(unary_union(niches))
        cmds = self._plate_on(ctx, name, plate, p["lagen"], p["staerke"])
        return cmds, [name], \
            f"{n}× {p['form']} {p['breite']:g}×{p['hoehe']:g} auf " \
            f"{ctx['wall']}"

    # -- Schmuck

    def engr_uhr(self, el):
        ctx, p = el["ctx"], el["params"]
        lines = G.clock_lines(p["x"], p["y"], p["durchmesser"] / 2)
        return [(el["name"], ctx, p["staerke"] * p["lagen"], lines)]

    def cmds_uhr(self, name, ctx, p):
        r = p["durchmesser"] / 2
        disk = Polygon(G.arch_poly(p["x"], p["y"] - r, 2 * r, p["y"] + r,
                                   "rund"))
        cmds = self._plate_on(ctx, name, disk, p["lagen"], p["staerke"])
        for body, c2, off, lines in self.engr_uhr(
                {"name": name, "ctx": ctx, "params": p}):
            cmds += self._groove(c2, f"{name} Zifferblatt", lines, body,
                                 offset=off)
        return cmds, [name], f"Ø{p['durchmesser']:g} auf {ctx['wall']}"

    def cmds_pfeiler(self, name, ctx, p):
        """Strebepfeiler: Profilplatten quer zur Wand, abgetreppt."""
        t = p["staerke"]
        n = max(1, round(p["breite"] / t))
        D, H = p["tiefe"], p["hoehe"]
        prof = [(0, 0), (D, 0), (D, H * 0.45), (D * 0.6, H * 0.45 + D * 0.4),
                (D * 0.6, H * 0.8), (0, H)]
        P, R, U, N = (np.array(ctx[k], float) for k in ("p", "right", "up",
                                                         "n"))
        y0 = ctx["bounds"][1]
        cmds, bodies = [], []
        for i in range(n):
            o = P + R * (p["x"] - n * t / 2 + i * t) + U * y0
            c2 = {"p": _f(o), "right": _f(N), "up": _f(U), "n": _f(-R)}
            nm = f"{name} Lage {i + 1}"
            cmds += self._sketch(c2, f"{nm} Skizze", [(prof, [])])
            cmds.append({"command": "solid.extrude", "params": {
                "distance": _r(t), "direction": "negative",
                "operation": "new", "body_name": nm, "name": nm}})
            bodies.append(nm)
        return cmds, bodies, \
            f"{n} Lagen, {D:g} tief, {H:g} hoch an {ctx['wall']}"

    # -- Bänder

    def _band_geom(self, c, p):
        x0, y0, x1, y1 = c["bounds"]
        d = p["staerke"] * p["lagen"]
        if c.get("ecke"):
            x0, x1 = x0 - d, x1 + d
        art, h = p["art"], p["hoehe"]
        if art == "sockel":
            return box(x0, y0, x1, y0 + h)
        if art == "trauf":
            return box(x0, y1 - h, x1, y1)
        if art == "fries":
            return G.fries_shape(x0, x1, y0 + p["z"], h, p["bogen"],
                                 p.get("form", "bogen"))
        return box(x0, y0 + p["z"], x1, y0 + p["z"] + h)

    def cmds_band(self, name, ctx, p):
        walls = self._walls_for(ctx, p["rundum"])
        cmds, bodies = [], []
        for c in walls:
            nm = f"{name} {c['wall'].rsplit(' ', 1)[-1]}" if len(walls) > 1 \
                else name
            g = self._band_geom(c, p).difference(self._occupied(c, name))
            cmds += self._plate_on(c, nm, g, p["lagen"], p["staerke"])
            bodies.append(nm)
        wo = "rundum" if len(walls) > 1 else f"auf {ctx['wall']}"
        return cmds, bodies, f"{p['art']} {p['hoehe']:g} hoch {wo}"

    def cmds_eckquader(self, name, ctx, p):
        walls = self._walls_for(ctx, True)
        d = p["staerke"] * p["lagen"]
        cmds, bodies = [], []
        for c in walls:
            x0, y0, x1, y1 = c["bounds"]
            lang = c.get("ecke", False)
            rects = []
            k, y = 0, y0 + p["fuge"]
            while y + p["hoehe"] <= y1 - p["fuge"] + 1e-6:
                long_row = (k % 2 == 0) == lang
                L = p["lang"] if long_row else p["kurz"]
                ext = d if c.get("ecke") else 0.0
                rects.append(box(x0 - ext, y, x0 + L, y + p["hoehe"]))
                rects.append(box(x1 - L, y, x1 + ext, y + p["hoehe"]))
                y += p["hoehe"] + p["fuge"]
                k += 1
            if not rects:
                continue
            nm = f"{name} {c['wall'].rsplit(' ', 1)[-1]}" if len(walls) > 1 \
                else name
            g = unary_union(rects).difference(self._occupied(c, name))
            cmds += self._plate_on(c, nm, g, p["lagen"], p["staerke"])
            bodies.append(nm)
        if not cmds:
            raise RuntimeError("Wand zu niedrig für Eckquader")
        return cmds, bodies, f"{p['hoehe']:g}er Quader, {len(walls)} Wände"

    # -- Fußabdrücke: was belegt eine Wand schon? (Bänder sparen es aus)

    def fp_fenster(self, el):
        p = el["params"]
        R = p["rahmen"]
        o = self._opening(p)
        g = o.buffer(R, join_style=2) if R > 0 else o
        if p.get("sims"):
            x0, y0, x1, _ = g.bounds
            g = g.union(box(x0 - 2.5, y0 - 1.5, x1 + 2.5, y0 + 0.5))
        return [(el["ctx"], g)]

    def fp_tuer(self, el):
        ctx, p = el["ctx"], el["params"]
        o, y0 = self._door(ctx, p)
        g = o.buffer(max(p["rahmen"], 0.01), join_style=2)
        return [(ctx, g.union(box(o.bounds[0] - p["rahmen"], y0 - 50,
                                  o.bounds[2] + p["rahmen"], y0 + 1)))]

    def fp_blende(self, el):
        p = el["params"]
        n = int(p["anzahl"])
        return [(el["ctx"], unary_union([
            self._opening(dict(p, x=p["x"] + (i - (n - 1) / 2) * p["abstand"]))
            .buffer(p["rand"], join_style=2) for i in range(n)]))]

    def fp_uhr(self, el):
        p = el["params"]
        r = p["durchmesser"] / 2
        return [(el["ctx"], Polygon(G.arch_poly(p["x"], p["y"] - r, 2 * r,
                                                p["y"] + r, "rund")))]

    def fp_pfeiler(self, el):
        ctx, p = el["ctx"], el["params"]
        n = max(1, round(p["breite"] / p["staerke"]))
        w = n * p["staerke"]
        y0 = ctx["bounds"][1]
        return [(ctx, box(p["x"] - w / 2, y0 - 50, p["x"] + w / 2,
                          y0 + p["hoehe"]))]

    def fp_band(self, el):
        p = el["params"]
        return [(c, self._band_geom(c, p))
                for c in self._walls_for(el["ctx"], p["rundum"])]

    def fp_eckquader(self, el):
        out = []
        p = el["params"]
        d = p["staerke"] * p["lagen"]
        for c in self._walls_for(el["ctx"], True):
            x0, y0, x1, y1 = c["bounds"]
            ext = d if c.get("ecke") else 0.0
            L = max(p["lang"], p["kurz"])
            out.append((c, unary_union([box(x0 - ext, y0, x0 + L, y1),
                                        box(x1 - L, y0, x1 + ext, y1)])))
        return out

    def _occupied(self, dst, own_name):
        """Belegte Fläche auf der Wand `dst` (alle anderen Elemente)."""
        P, R, U, N = (np.array(dst[k], float) for k in ("p", "right", "up",
                                                         "n"))
        parts = []
        for el in self.elements():
            if el["name"] == own_name or not hasattr(self, "fp_" + el["typ"]):
                continue
            if el["typ"] == "eckquader" and own_name.startswith("Eckquader"):
                continue
            for src, g in getattr(self, "fp_" + el["typ"])(el):
                Ps, Rs, Us, Ns = (np.array(src[k], float)
                                  for k in ("p", "right", "up", "n"))
                if np.dot(Ns, N) < 0.999 or abs(np.dot(Ps - P, N)) > 0.05:
                    continue                    # andere Wandebene
                from shapely.affinity import affine_transform
                parts.append(affine_transform(g, [
                    Rs @ R, Us @ R, Rs @ U, Us @ U,
                    (Ps - P) @ R, (Ps - P) @ U]).buffer(0.3, join_style=2))
        return unary_union(parts) if parts else Polygon()
