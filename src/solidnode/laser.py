"""Laser-Werkzeuge für SolidCraft: Bausätze aus Platten direkt im CAD.

Jedes Werkzeug liest die Auswahl bzw. die Körper aus dem offenen Design,
rechnet mit OpenCASCADE und schreibt das Ergebnis als **native**
SolidCraft-Features zurück (Skizze + Extrusion), damit es in der Timeline
steht und sich wie selbst konstruiert anfühlt.

Werkzeuge:
- kasten       Kasten aus sich überlappenden Platten (Startpunkt)
- zinken       Fingerzinken an jedem Stoß zweier Platten
- hinge        Living Hinge um eine Biegelinie oder in einem Rechteck
- fenster      Fenster aufsetzen: Öffnung schneiden + Rahmen mit Sprossen
- export_svg   alle Platten flach legen, verschachteln, SVG für xTool
"""

from __future__ import annotations

import json
import math
import os
import time

import numpy as np

from .hosts import UEBERGABE, sc_read_step

EPS = 1e-6
META = "de.malandereideen.laser"        # Elementliste im Design (Metadaten)

# Felder je Elementtyp: (Schlüssel, Beschriftung, Art, Default, min, max,
# Schritt). Art: mm, deg, int, bool. Daraus baut die Palette das Formular.
SCHEMA = {
    "kasten": {"label": "Kasten", "fields": [
        ("breite", "Breite", "mm", 120, 10, 2000, 5),
        ("tiefe", "Tiefe", "mm", 80, 10, 2000, 5),
        ("hoehe", "Höhe", "mm", 60, 10, 2000, 5),
        ("deckel", "Deckel", "bool", False, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "zinken": {"label": "Zinken", "fields": [
        ("zinke", "Zinke", "mm", 10.0, 3, 60, 1)]},
    "hinge": {"label": "Hinge", "fields": [
        ("radius", "Radius", "mm", 15.0, 1, 500, 1),
        ("winkel", "Winkel", "deg", 90.0, 5, 360, 5),
        ("schnitt", "Schnitt", "mm", 15.0, 3, 100, 1),
        ("steg", "Steg", "mm", 3.0, 1, 20, 0.5),
        ("abstand", "Abstand", "mm", 1.5, 0.5, 10, 0.25),
        ("schlitz", "Schlitz", "mm", 0.5, 0.1, 3, 0.1)]},
    "fenster": {"label": "Fenster", "fields": [
        ("breite", "Breite", "mm", 20.0, 2, 500, 1),
        ("hoehe", "Höhe", "mm", 30.0, 2, 500, 1),
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("y", "↓ ↑", "mm", 0.0, -2000, 2000, 1),
        ("rahmen", "Rahmen", "mm", 3.0, 0.5, 30, 0.5),
        ("sprosse", "Sprosse", "mm", 1.5, 0.5, 10, 0.5),
        ("sprossen_v", "Sprossen ↕", "int", 1, 0, 10, 1),
        ("sprossen_h", "Sprossen ↔", "int", 1, 0, 10, 1),
        ("oeffnung", "Öffnung", "bool", True, 0, 1, 1),
        ("lagen", "Lagen", "int", 1, 1, 5, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
}


def defaults(typ):
    return {k: d for k, _l, _a, d, *_ in SCHEMA[typ]["fields"]}


# ------------------------------------------------------------ Geometrie

def _vertices(shape):
    from OCP.BRep import BRep_Tool
    from OCP.TopAbs import TopAbs_VERTEX
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    out = []
    exp = TopExp_Explorer(shape, TopAbs_VERTEX)
    while exp.More():
        p = BRep_Tool.Pnt_s(TopoDS.Vertex_s(exp.Current()))
        out.append((p.X(), p.Y(), p.Z()))
        exp.Next()
    return np.array(out) if out else np.zeros((0, 3))


def _volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g)
    return g.Mass()


def _planar_faces(shape):
    """[(face, normal, area, point)] aller ebenen Flächen."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepGProp import BRepGProp
    from OCP.GeomAbs import GeomAbs_Plane
    from OCP.GProp import GProp_GProps
    from OCP.TopAbs import TopAbs_FACE, TopAbs_REVERSED
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    out = []
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        f = TopoDS.Face_s(exp.Current())
        s = BRepAdaptor_Surface(f)
        if s.GetType() == GeomAbs_Plane:
            pl = s.Plane()
            d = pl.Axis().Direction()
            n = np.array([d.X(), d.Y(), d.Z()])
            if f.Orientation() == TopAbs_REVERSED:
                n = -n
            g = GProp_GProps()
            BRepGProp.SurfaceProperties_s(f, g)
            c = g.CentreOfMass()
            out.append((f, n, g.Mass(), np.array([c.X(), c.Y(), c.Z()])))
        exp.Next()
    return out


def plate_info(shape):
    """Ebene Platte? → dict(normal, thickness, face, area) oder None.

    Normale = die der größten ebenen Fläche; Dicke = Ausdehnung entlang
    der Normalen. Eine Platte hat eine gleich große Gegenfläche."""
    faces = _planar_faces(shape)
    if not faces:
        return None
    f, n, a, c = max(faces, key=lambda x: x[2])
    v = _vertices(shape)
    d = v @ n
    t = float(d.max() - d.min())
    opp = [x for x in faces if np.dot(x[1], n) < -0.999
           and abs(x[2] - a) / a < 0.05]
    return dict(normal=n, thickness=t, face=f, area=a, center=c,
                plate=bool(opp))


def _common(a, b):
    from OCP.BRepAlgoAPI import BRepAlgoAPI_Common
    op = BRepAlgoAPI_Common(a, b)
    op.Build()
    return op.Shape() if op.IsDone() else None


def odd_count(length, target):
    n = max(3, int(round(length / target)))
    return n if n % 2 else n + 1


def _priority(n):
    """Wer behält beim Stoß die Enden (und damit die Ecke)? Böden/Deckel
    vor Front/Rück vor Seiten — so gehört jede Ecke genau einer Platte."""
    a = np.abs(n)
    return (round(a[2], 3), round(a[1], 3), round(a[0], 3))


def _frame_up(n):
    """Rechts/oben auf einer Fläche mit Außennormale n (Blick von außen)."""
    up = np.array([0.0, 0.0, 1.0])
    if abs(np.dot(up, n)) > 0.9:
        up = np.array([0.0, 1.0, 0.0])
    up = up - n * np.dot(up, n)
    up /= np.linalg.norm(up)
    right = np.cross(up, n)
    return right, up


def _f(v):
    return [round(float(x), 6) for x in v]


# --------------------------------------------------------- SolidCraft

class Laser:
    """Werkzeuge gegen einen McpClient (laufende App oder headless)."""

    def __init__(self, client, staerke=3.0, finger=10.0):
        self.c = client
        self.staerke = staerke
        self.finger = finger
        os.makedirs(UEBERGABE, exist_ok=True)
        self._cache = {}

    # -- lesen

    def design(self, sketches=False, measure=False):
        return json.loads(self.c.tool("inspect_design", {
            "measure": measure, "sketches": sketches, "joints": False}))

    def body_names(self):
        d = self.design()
        return [b["name"] for b in d.get("bodies", [])
                if b.get("visible", True)]

    def shape(self, name):
        p = os.path.join(UEBERGABE, "laser_" + name.replace(" ", "_")
                         .replace("/", "_") + ".step")
        self.c.tool("export", {"format": "step", "bodies": [name],
                               "path": p})
        return sc_read_step(p)

    def selection(self):
        return self.design().get("selection") or []

    def batch(self, commands):
        r = json.loads(self.c.tool("batch", {"commands": commands}))
        if r.get("error") or r.get("failed_step") is not None:
            raise RuntimeError(json.dumps(r)[:600])
        return r

    # -- Bausteine

    def _sketch_rects(self, origin, x_dir, y_dir, rects, name):
        """Skizze auf freier Ebene mit Rechtecken (lokale Koordinaten)."""
        cmds = [{"command": "sketch.create", "params": {
            "plane": {"origin": _f(origin), "x_dir": _f(x_dir),
                      "y_dir": _f(y_dir)}, "name": name}}]
        for (x0, y0, x1, y1) in rects:
            cmds.append({"command": "sketch.rectangle.two_point", "params": {
                "p0": [round(x0, 5), round(y0, 5)],
                "p1": [round(x1, 5), round(y1, 5)]}})
        cmds.append({"command": "sketch.finish", "params": {}})
        return cmds

    def _box_plate(self, name, lo, hi):
        lo, hi = np.array(lo, float), np.array(hi, float)
        cmds = self._sketch_rects([0, 0, lo[2]], [1, 0, 0], [0, 1, 0],
                                  [(lo[0], lo[1], hi[0], hi[1])],
                                  f"Skizze {name}")
        cmds.append({"command": "solid.extrude", "params": {
            "distance": round(float(hi[2] - lo[2]), 5), "operation": "new",
            "body_name": name, "name": name}})
        return cmds

    def _zinken_cmds(self, na, sa, nb, sb, tag):
        ia, ib = plate_info(sa), plate_info(sb)
        if ia is None or ib is None:
            return None, "keine ebene Platte"
        c = _common(sa, sb)
        if c is None or _volume(c) < 1e-3:
            return None, "kein Stoß"
        nA, nB = ia["normal"], ib["normal"]
        if abs(np.dot(nA, nB)) > 0.01:
            return None, "nicht rechtwinklig"
        if _priority(nB) > _priority(nA):          # A behält die Enden
            na, sa, nb, sb, nA, nB = nb, sb, na, sa, nB, nA
        ax = np.cross(nA, nB)
        ax /= np.linalg.norm(ax)
        v = _vertices(c)
        s0, s1 = (v @ ax).min(), (v @ ax).max()
        a0, a1 = (v @ nA).min(), (v @ nA).max()
        b0, b1 = (v @ nB).min(), (v @ nB).max()
        L = s1 - s0
        n = odd_count(L, self.finger)
        seg = [(s0 + k * L / n, s0 + (k + 1) * L / n) for k in range(n)]
        o = ax * 0 + nA * (a0 + a1) / 2 + nB * (b0 + b1) / 2
        hb, ha = (b1 - b0) / 2, (a1 - a0) / 2
        # A behält gerade k (Enden), verliert ungerade
        ra = [(x0, -hb, x1, hb) for k, (x0, x1) in enumerate(seg) if k % 2]
        rb = [(x0, -ha, x1, ha) for k, (x0, x1) in enumerate(seg)
              if not k % 2]
        cmds = self._sketch_rects(o, ax, nB, ra, f"Zinken {tag} {na}")
        cmds.append({"command": "solid.extrude", "params": {
            "distance": round(float(a1 - a0) + 0.02, 5),
            "direction": "symmetric", "operation": "cut",
            "targets": [na], "name": f"Zinken {tag} {na}"}})
        cmds += self._sketch_rects(o, ax, nA, rb, f"Zinken {tag} {nb}")
        cmds.append({"command": "solid.extrude", "params": {
            "distance": round(float(b1 - b0) + 0.02, 5),
            "direction": "symmetric", "operation": "cut",
            "targets": [nb], "name": f"Zinken {tag} {nb}"}})
        return cmds, f"{na}–{nb}: {n} Zinken"


    def _plate_for_plane(self, origin, normal):
        """Körper, auf dessen großer Fläche die Skizzenebene liegt."""
        best = None
        for n in self.body_names():
            s = self.shape(n)
            info = plate_info(s)
            if info is None or abs(abs(np.dot(info["normal"], normal))
                                   - 1) > 1e-3:
                continue
            d = _vertices(s) @ normal
            o = float(np.dot(origin, normal))
            if d.min() - 1e-3 <= o <= d.max() + 1e-3:
                best = (n, s, info)
                break
        return best

    # -- Kontext aus der Auswahl (nur beim Anlegen / Neu platzieren)

    def ctx_kasten(self):
        return {}

    def ctx_zinken(self, namen=None):
        if not namen:
            namen = sorted({x.get("body") or x.get("name")
                            for x in self.selection()
                            if x.get("type") in ("body", "face", "edge")}
                           - {None})
        if not namen or len(namen) < 2:
            namen = self.body_names()
        return {"bodies": list(namen)}

    def ctx_hinge(self):
        sel = [x for x in self.selection() if x.get("type") == "sketch_curve"]
        if not sel:
            raise RuntimeError("Biegelinie (Skizzenlinie) in SolidCraft "
                               "auswählen")
        ctx = {"sketch": sel[0]["sketch"], "curves": [x["id"] for x in sel]}
        ctx.update(self._hinge_lines(ctx))
        n = np.cross(ctx["X"], ctx["Y"])
        p = (np.array(ctx["O"]) + np.array(ctx["X"]) * ctx["lines"][0][0][0]
             + np.array(ctx["Y"]) * ctx["lines"][0][0][1])
        found = self._plate_for_plane(p, n)
        if found is None:
            raise RuntimeError("Keine Platte unter der Skizze gefunden")
        ctx["plate"] = found[0]
        ctx["thickness"] = found[2]["thickness"]
        return ctx

    def _hinge_lines(self, ctx):
        """Linien frisch aus der Skizze (folgt, wenn Mario sie verschiebt)."""
        d = self.design(sketches=True)
        sk = next((s for s in d.get("sketches", [])
                   if s["id"] == ctx["sketch"]), None)
        if sk is None:
            return {}
        cv = {c["id"]: c for c in sk["curves"]}
        lines = [[cv[i]["start_at"], cv[i]["end_at"]] for i in ctx["curves"]
                 if i in cv and cv[i]["type"] == "line"]
        if not lines:
            raise RuntimeError("Nur gerade Skizzenlinien")
        pl = sk["plane"]
        return {"O": pl["origin"], "X": pl["x_dir"], "Y": pl["y_dir"],
                "lines": lines}

    def ctx_fenster(self):
        sel = [x for x in self.selection() if x.get("type") == "face"]
        if not sel:
            raise RuntimeError("Wandfläche in SolidCraft anklicken")
        f = sel[0]
        wall = f["body"]
        p = np.array(f.get("point") or [0, 0, 0], float)
        s = self.shape(wall)
        from .hosts import nearest_sub
        face = nearest_sub(s, "face", tuple(p))
        n = next(x[1] for x in _planar_faces(face))
        right, up = _frame_up(n)
        return {"wall": wall, "p": _f(p), "right": _f(right), "up": _f(up),
                "thickness": round(plate_info(s)["thickness"], 4)}

    # -- Neubau aus Kontext + Werten → Befehle

    def cmds_kasten(self, name, ctx, p):
        t = p["staerke"]
        B, T, H = p["breite"], p["tiefe"], p["hoehe"]
        o = np.array([p.get("x", 0), p.get("y", 0), p.get("z", 0)], float)
        teile = [("Boden", (0, 0, 0), (B, T, t)),
                 ("Front", (0, 0, 0), (B, t, H)),
                 ("Rueckwand", (0, T - t, 0), (B, T, H)),
                 ("Seite links", (0, 0, 0), (t, T, H)),
                 ("Seite rechts", (B - t, 0, 0), (B, T, H))]
        if p.get("deckel"):
            teile.append(("Deckel", (0, 0, H - t), (B, T, H)))
        cmds = []
        for n, lo, hi in teile:
            cmds += self._box_plate(f"{name} {n}", o + lo, o + hi)
        return cmds, [f"{name} {n}" for n, _, _ in teile], \
            f"{B:g}×{T:g}×{H:g}, {len(teile)} Platten"

    def cmds_zinken(self, name, ctx, p):
        self.finger = p["zinke"]
        vorhanden = set(self.body_names())
        namen = [n for n in ctx["bodies"] if n in vorhanden]
        shapes = {n: self.shape(n) for n in namen}
        boxes = {n: (_vertices(s).min(0), _vertices(s).max(0))
                 for n, s in shapes.items()}
        cmds, meld = [], []
        for i, a in enumerate(namen):
            for b in namen[i + 1:]:
                (alo, ahi), (blo, bhi) = boxes[a], boxes[b]
                if np.any(alo > bhi + 1e-6) or np.any(blo > ahi + 1e-6):
                    continue
                c, m = self._zinken_cmds(a, shapes[a], b, shapes[b],
                                         f"{name}.{len(meld) + 1}")
                if c:
                    cmds += c
                    meld.append(m)
        if not cmds:
            raise RuntimeError("Keine Stöße gefunden (Platten müssen sich "
                               "überlappen)")
        return cmds, namen, f"{len(meld)} Stöße, Zinke {p['zinke']:g}"

    def cmds_hinge(self, name, ctx, p):
        try:
            ctx.update(self._hinge_lines(ctx))
        except RuntimeError:
            pass
        O, X, Y = (np.array(ctx[k], float) for k in ("O", "X", "Y"))
        N = np.cross(X, Y)
        lines = [np.array(ln, float) for ln in ctx["lines"]]
        if len(lines) == 1:
            p0, p1 = lines[0]
            u = (p1 - p0) / np.linalg.norm(p1 - p0)
            length = float(np.linalg.norm(p1 - p0))
            width = p["radius"] * math.radians(p["winkel"])
            corner = p0 - np.array([-u[1], u[0]]) * width / 2
        else:
            pts = np.array([q for ln in lines for q in ln])
            lo, hi = pts.min(0), pts.max(0)
            if hi[0] - lo[0] >= hi[1] - lo[1]:
                u, length, width, corner = (np.array([1.0, 0.0]),
                                            hi[0] - lo[0], hi[1] - lo[1], lo)
            else:
                u, length, width = (np.array([0.0, 1.0]), hi[1] - lo[1],
                                    hi[0] - lo[0])
                corner = np.array([hi[0], lo[1]])
        v = np.array([-u[1], u[0]])
        world_o = O + X * corner[0] + Y * corner[1]
        ux = X * u[0] + Y * u[1]
        vy = X * v[0] + Y * v[1]
        if np.dot(np.cross(ux, vy), N) < 0:
            world_o = world_o + vy * width
            vy = -vy
        schnitt, steg, abstand, schlitz = (p["schnitt"], p["steg"],
                                           p["abstand"], p["schlitz"])
        pitch = schnitt + steg
        rects, rows = [], max(2, int(width // abstand))
        gap = (width - (rows - 1) * abstand) / 2
        for r in range(rows):
            y = gap + r * abstand
            x = -(0.0 if r % 2 else pitch / 2) - pitch
            while x < length:
                x0, x1 = max(x, -2 * steg), min(x + schnitt, length + 2 * steg)
                if x1 - x0 > steg:
                    rects.append((x0, y - schlitz / 2, x1, y + schlitz / 2))
                x += pitch
        cmds = self._sketch_rects(world_o, ux, vy, rects, f"{name} Skizze")
        cmds.append({"command": "solid.extrude", "params": {
            "distance": round(ctx["thickness"] * 2 + 2, 4),
            "direction": "symmetric", "operation": "cut",
            "targets": [ctx["plate"]], "name": name}})
        return cmds, [ctx["plate"]], \
            f"{ctx['plate']}: Zone {width:.1f}×{length:.1f}, {len(rects)} Schlitze"

    def cmds_fenster(self, name, ctx, p):
        right, up = np.array(ctx["right"]), np.array(ctx["up"])
        c = np.array(ctx["p"]) + right * p["x"] + up * p["y"]
        B, H, R, sp = p["breite"], p["hoehe"], p["rahmen"], p["sprosse"]
        w2, h2 = B / 2, H / 2
        cmds = []
        if p["oeffnung"]:
            cmds += self._sketch_rects(c, right, up, [(-w2, -h2, w2, h2)],
                                       f"{name} Öffnung Skizze")
            cmds.append({"command": "solid.extrude", "params": {
                "distance": round(ctx["thickness"] + 1, 4),
                "direction": "negative", "operation": "cut",
                "targets": [ctx["wall"]], "name": f"{name} Öffnung"}})
        rects = [(-w2 - R, -h2 - R, w2 + R, h2 + R)]
        nv, nh = int(p["sprossen_v"]), int(p["sprossen_h"])
        pw = (B - nv * sp) / (nv + 1)
        ph = (H - nh * sp) / (nh + 1)
        if pw <= 0.2 or ph <= 0.2:
            raise RuntimeError("Zu viele/zu breite Sprossen für das Fenster")
        for i in range(nv + 1):
            for j in range(nh + 1):
                x0, y0 = -w2 + i * (pw + sp), -h2 + j * (ph + sp)
                rects.append((x0, y0, x0 + pw, y0 + ph))
        cmds += self._sketch_rects(c, right, up, rects, f"{name} Rahmen Skizze")
        cmds.append({"command": "solid.extrude", "params": {
            "distance": round(p["staerke"] * p["lagen"], 4),
            "operation": "new", "body_name": f"{name} Rahmen",
            "name": f"{name} Rahmen"}})
        sprossen = f", Sprossen {nv}×{nh}" if nv or nh else ""
        return cmds, [ctx["wall"], f"{name} Rahmen"], \
            f"{B:g}×{H:g} auf {ctx['wall']}{sprossen}"

    # -- Elemente: Liste im Design, Neubau an derselben Timeline-Stelle

    def elements(self):
        meta = json.loads(self.c.execute("document.metadata", {}))
        return (meta.get("metadata", {}).get(META) or {}).get("elements", [])

    def _save(self, els):
        self.c.execute("document.metadata.set",
                       {"key": META, "value": {"elements": els}})

    def _timeline(self):
        return self.design()["timeline"]

    def _new_name(self, typ, els):
        label = SCHEMA[typ]["label"]
        nums = [int(e["name"].rsplit(" ", 1)[1]) for e in els
                if e["typ"] == typ and e["name"].rsplit(" ", 1)[-1].isdigit()]
        return f"{label} {max(nums, default=0) + 1}"

    def _build(self, el):
        """Befehle laufen an der Timeline-Marke; neue Features → Ordner."""
        before = {f["id"] for f in self._timeline()}
        cmds, bodies, info = getattr(self, "cmds_" + el["typ"])(
            el["name"], el["ctx"], el["params"])
        self.batch(cmds)
        new = [f["id"] for f in self._timeline() if f["id"] not in before]
        g = json.loads(self.c.execute("timeline.group", {
            "name": el["name"], "features": new}))
        el.update(features=new, group=g.get("group"), bodies=bodies,
                  info=info)
        return el

    def create(self, typ, params, ctx=None):
        els = self.elements()
        p = defaults(typ)
        p.update(params or {})
        if ctx is None:
            ctx = getattr(self, "ctx_" + typ)()
        el = {"id": f"{typ}-{int(time.time() * 1000)}", "typ": typ,
              "name": self._new_name(typ, els), "params": p, "ctx": ctx}
        self._build(el)
        els.append(el)
        self._save(els)
        return f"{el['name']}: {el['info']}"

    def _rebuild(self, el):
        tl = [f["id"] for f in self._timeline()]
        pos = min((tl.index(i) for i in el.get("features", []) if i in tl),
                  default=len(tl))
        self.c.execute("timeline.roll_to", {"position": pos})
        try:
            alive = [i for i in el.get("features", []) if i in tl]
            if alive:
                self.c.execute("timeline.delete", {"features": alive})
            self._build(el)
        finally:
            self.c.execute("timeline.roll_to", {})

    def edit(self, eid, params=None, replace_ctx=False):
        els = self.elements()
        el = next(e for e in els if e["id"] == eid)
        if params:
            el["params"].update(params)
        if replace_ctx:
            el["ctx"] = getattr(self, "ctx_" + el["typ"])()
        self._rebuild(el)
        extra = []
        if el["typ"] == "kasten":                 # Zinken folgen dem Kasten
            for z in els:
                if z["typ"] == "zinken" and set(z["ctx"]["bodies"]) & set(
                        el["bodies"]):
                    self._rebuild(z)
                    extra.append(z["name"])
        self._save(els)
        msg = f"{el['name']} neu: {el['info']}"
        return msg + (f" · {', '.join(extra)} nachgezogen" if extra else "")

    def delete(self, eid):
        els = self.elements()
        el = next(e for e in els if e["id"] == eid)
        tl = {f["id"] for f in self._timeline()}
        alive = [i for i in el.get("features", []) if i in tl]
        if alive:
            self.c.execute("timeline.delete", {"features": alive})
        self._save([e for e in els if e["id"] != eid])
        return f"{el['name']} gelöscht"

    def status(self, els=None):
        """Je Element: 'ok', 'Fehler …' oder 'fehlt' (in SolidCraft gelöscht)."""
        tl = {f["id"]: f for f in self._timeline()}
        out = {}
        for e in els if els is not None else self.elements():
            fs = [tl.get(i) for i in e.get("features", [])]
            if not fs or all(f is None for f in fs):
                out[e["id"]] = "fehlt"
            elif any(f and f.get("error") for f in fs):
                out[e["id"]] = "Fehler"
            elif any(f is None for f in fs):
                out[e["id"]] = "teilweise"
            else:
                out[e["id"]] = "ok"
        return out

    def highlight(self, eid):
        el = next(e for e in self.elements() if e["id"] == eid)
        names = set(self.body_names())
        items = [{"type": "body", "name": b} for b in el.get("bodies", [])
                 if b in names]
        if el["typ"] == "fenster" and len(items) > 1:
            items = items[1:]                    # nur den Rahmen
        if items:
            self.c.execute("select.set", {"items": items})

    # -- Kurzformen (Tests, Skripte)

    def kasten(self, breite, tiefe, hoehe, deckel=False):
        return self.create("kasten", {"breite": breite, "tiefe": tiefe,
                                      "hoehe": hoehe, "deckel": deckel,
                                      "staerke": self.staerke})

    def zinken(self, namen=None):
        return self.create("zinken", {"zinke": self.finger},
                           self.ctx_zinken(namen))

    def hinge(self, radius=20.0, winkel=90.0, **kw):
        return self.create("hinge", dict(radius=radius, winkel=winkel, **kw))

    def fenster(self, breite=20.0, hoehe=30.0, **kw):
        kw.setdefault("staerke", self.staerke)
        return self.create("fenster", dict(breite=breite, hoehe=hoehe, **kw))

    # -- Export

    def export_svg(self, ordner=None, platte=(400.0, 300.0), abstand=3.0):
        """Alle sichtbaren Platten flach, verschachtelt, rot = schneiden."""
        ordner = ordner or os.path.expanduser(
            "~/Downloads/Laser-Export/" + time.strftime("%Y-%m-%d_%H%M%S"))
        os.makedirs(ordner, exist_ok=True)
        teile, warn = [], []
        for name in self.body_names():
            s = self.shape(name)
            info = plate_info(s)
            if info is None or not info["plate"]:
                warn.append(f"{name}: keine Platte")
                continue
            if abs(info["thickness"] - self.staerke) > 0.05:
                warn.append(f"{name}: {info['thickness']:.2f} mm statt "
                            f"{self.staerke:g}")
            teile.append((name, flat_outline(info)))
        sheets = nest([p for _, p in teile], platte, abstand)
        files = []
        for k, sheet in enumerate(sheets):
            path = os.path.join(ordner, f"Platte {k + 1}.svg")
            write_svg(path, platte, [(teile[i][0], polys, dx, dy)
                                     for i, polys, dx, dy in sheet])
            files.append(path)
        msg = f"{len(teile)} Teile auf {len(sheets)} Platte(n) → {ordner}"
        if warn:
            msg += " · ⚠ " + "; ".join(warn)
        return msg, files


# ------------------------------------------------------------ Abwicklung

def flat_outline(info):
    """Umriss + Löcher der großen Fläche als 2D-Polylinien (mm)."""
    from OCP.BRepAdaptor import BRepAdaptor_Curve
    from OCP.BRepTools import BRepTools_WireExplorer
    from OCP.GCPnts import GCPnts_QuasiUniformDeflection
    from OCP.TopAbs import TopAbs_WIRE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    n = info["normal"]
    right, up = _frame_up(n)
    polys = []
    exp = TopExp_Explorer(info["face"], TopAbs_WIRE)
    while exp.More():
        w = TopoDS.Wire_s(exp.Current())
        pts = []
        we = BRepTools_WireExplorer(w)
        while we.More():
            c = BRepAdaptor_Curve(we.Current())
            d = GCPnts_QuasiUniformDeflection(c, 0.01)
            seg = [c.Value(d.Parameter(i)) for i in range(1, d.NbPoints() + 1)]
            seg = [np.array([q.X(), q.Y(), q.Z()]) for q in seg]
            from OCP.TopAbs import TopAbs_REVERSED
            if we.Current().Orientation() == TopAbs_REVERSED:
                seg.reverse()
            pts += [(float(q @ right), float(q @ up)) for q in seg]
            we.Next()
        if pts:
            pts.append(pts[0])
            polys.append(pts)
        exp.Next()
    allp = np.array([p for pl in polys for p in pl])
    lo = allp.min(0)
    return [[(x - lo[0], y - lo[1]) for x, y in pl] for pl in polys]


def nest(parts, platte, gap):
    """Regal-Packen nach Höhe. → [[(index, polys, dx, dy)], …] je Platte."""
    W, H = platte
    sizes = []
    for i, polys in enumerate(parts):
        a = np.array([p for pl in polys for p in pl])
        w, h = a.max(0)
        if w > h and w > W - 2 * gap:                 # hochkant drehen
            polys = [[(y, w - x) for x, y in pl] for pl in polys]
            w, h = h, w
        sizes.append((i, polys, w, h))
    sizes.sort(key=lambda x: -x[3])
    sheets, cur, x, y, row = [], [], gap, gap, 0.0
    for i, polys, w, h in sizes:
        if x + w > W - gap:
            x, y, row = gap, y + row + gap, 0.0
        if y + h > H - gap:
            sheets.append(cur)
            cur, x, y, row = [], gap, gap, 0.0
        cur.append((i, polys, x, y))
        x += w + gap
        row = max(row, h)
    if cur:
        sheets.append(cur)
    return sheets


def write_svg(path, platte, placed):
    W, H = platte
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" '
           f'height="{H}mm" viewBox="0 0 {W} {H}">']
    for name, polys, dx, dy in placed:
        out.append(f'<g id="{name}">')
        for pl in polys:
            d = " ".join(f"{'M' if k == 0 else 'L'}{x + dx:.3f},"
                         f"{H - (y + dy):.3f}" for k, (x, y) in enumerate(pl))
            out.append(f'<path d="{d} Z" fill="none" stroke="#FF0000" '
                       f'stroke-width="0.1"/>')
        a = np.array([p for pl in polys for p in pl])
        cx, cy = a.mean(0)
        out.append(f'<text x="{cx + dx:.2f}" y="{H - (cy + dy):.2f}" '
                   f'font-size="3" fill="#0000FF" text-anchor="middle">'
                   f'{name}</text>')
        out.append("</g>")
    out.append("</svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))
