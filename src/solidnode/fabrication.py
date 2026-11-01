"""Fertigungs-Nodes für Lasercutting und 3D-Druck.

Wird von core.make_core() geladen; bekommt die Basisklassen hereingereicht,
damit dieses Modul ohne Qt-Import auskommt.
"""

from __future__ import annotations

import math
import os

import numpy as np


# ------------------------------------------------------------- OCC-Helfer

def bbox(shape):
    from OCP.Bnd import Bnd_Box
    from OCP.BRepBndLib import BRepBndLib
    from serpentine3d.core.mesh import MeshShape
    if isinstance(shape, MeshShape):
        lo, hi = shape.bbox()
        return np.array(lo, float), np.array(hi, float)
    b = Bnd_Box()
    BRepBndLib.Add_s(shape, b)
    x0, y0, z0, x1, y1, z1 = b.Get()
    return np.array([x0, y0, z0]), np.array([x1, y1, z1])


def faces_of(shape):
    from OCP.TopAbs import TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    exp = TopExp_Explorer(shape, TopAbs_FACE)
    while exp.More():
        yield TopoDS.Face_s(exp.Current())
        exp.Next()


def edges_of(shape):
    from OCP.TopAbs import TopAbs_EDGE
    from OCP.TopExp import TopExp_Explorer
    from OCP.TopoDS import TopoDS
    exp = TopExp_Explorer(shape, TopAbs_EDGE)
    while exp.More():
        yield TopoDS.Edge_s(exp.Current())
        exp.Next()


def area(face):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    p = GProp_GProps()
    BRepGProp.SurfaceProperties_s(face, p)
    return p.Mass()


def prism(face, vec):
    from OCP.BRepPrimAPI import BRepPrimAPI_MakePrism
    from OCP.gp import gp_Vec
    return BRepPrimAPI_MakePrism(face, gp_Vec(*vec)).Shape()


def prisms(geo, faces, vec):
    """Jede Fläche einzeln extrudieren — ein Prisma über eine Sammlung von
    Flächen ergibt einen ungültigen Körper."""
    return geo.make_compound([prism(f, vec) for f in faces])


def fix(shape):
    """Geometrie reparieren (Schrift-Glyphen sind oft ungültig)."""
    from OCP.ShapeFix import ShapeFix_Shape
    sf = ShapeFix_Shape(shape)
    sf.Perform()
    return sf.Shape()


def is_null(shape):
    return shape is None or shape.IsNull() or not list(faces_of(shape))


def matrix(cols, t=(0, 0, 0)):
    """4x4 aus den Bildern der drei Achsen (Spalten) und einer Verschiebung."""
    m = np.eye(4)
    m[:3, :3] = np.column_stack(cols)
    m[:3, 3] = t
    return m


def odd_count(length, target):
    n = max(1, int(round(length / max(target, 1e-6))))
    return n if n % 2 else n + 1


def to_face(geo, shape):
    """Fläche aus Fläche oder geschlossener Kurve."""
    if list(faces_of(shape)):
        return next(faces_of(shape))
    return geo.planar_face(shape)


# Abbildungen Platte (u, v, Dicke w) -> Welt, alle mit Determinante +1
def box_placements(B, T, H, t):
    X, Y, Z = (1, 0, 0), (0, 1, 0), (0, 0, 1)
    nY = (0, -1, 0)
    return {
        "Boden": matrix((X, Y, Z)),
        "Deckel": matrix((X, Y, Z), (0, 0, H - t)),
        "Vorne": matrix((X, Z, nY), (0, t, 0)),
        "Hinten": matrix((X, Z, nY), (0, T, 0)),
        "Links": matrix((Y, Z, X)),
        "Rechts": matrix((Y, Z, X), (B - t, 0, 0)),
    }


def make_nodes(SerpNode, Tree, geo, is_shape, parse):
    from serpentine3d.core.tessellate import tessellate, _edge_polyline

    def rect_face(x0, y0, x1, y1, z=0.0):
        return geo.planar_face(geo.make_rectangle((x0, y0, z), (x1, y1, z)))

    def panel_face(W, H, t, edges, keep_corners, zinke):
        """Platte W x H mit Zinken; edges: Seite -> zinke|luecke|glatt."""
        cuts = []
        if not keep_corners:
            for x, y in ((0, 0), (W - t, 0), (0, H - t), (W - t, H - t)):
                cuts.append((x, y, x + t, y + t))
        for side, mode in edges.items():
            if mode == "glatt":
                continue
            L = H if side in ("u0", "u1") else W
            Li = L - 2 * t
            n = odd_count(Li, zinke)
            w = Li / n
            for k in range(n):
                recessed = (k % 2 == 1) if mode == "zinke" else (k % 2 == 0)
                if not recessed:
                    continue
                a, b = t + k * w, t + (k + 1) * w
                cuts.append({"v0": (a, 0, b, t), "v1": (a, H - t, b, H),
                             "u0": (0, a, t, b),
                             "u1": (W - t, a, W, b)}[side])
        return geo.planar_face(geo.make_polyline(
            [(x, y, 0.0) for x, y in rect_outline(W, H, cuts)], closed=True))

    def layout_row(shapes, gap, y=0.0):
        """Flache Teile nebeneinander in XY legen."""
        out, x = [], 0.0
        for s in shapes:
            lo, hi = bbox(s)
            out.append(geo.translate(s, (x - lo[0], y - lo[1], -lo[2])))
            x += (hi[0] - lo[0]) + gap
        return out

    def flatten_to_xy(shape, axis):
        """Schnittfläche in die XY-Ebene drehen und auf z=0 legen."""
        if axis == "X":
            m = matrix(((0, 0, 1), (1, 0, 0), (0, 1, 0)))
        elif axis == "Y":
            m = matrix(((1, 0, 0), (0, 0, -1), (0, 1, 0)))
        else:
            m = np.eye(4)
        s = geo.apply_matrix(shape, m)
        lo, _hi = bbox(s)
        return geo.translate(s, (0, 0, -lo[2]))

    def section(body, axis, pos):
        lo, hi = bbox(body)
        pad = 10.0
        a, b = lo - pad, hi + pad
        if axis == "X":
            plane = geo.planar_face(geo.make_polyline(
                [(pos, a[1], a[2]), (pos, b[1], a[2]), (pos, b[1], b[2]),
                 (pos, a[1], b[2])], closed=True))
        elif axis == "Y":
            plane = geo.planar_face(geo.make_polyline(
                [(a[0], pos, a[2]), (b[0], pos, a[2]), (b[0], pos, b[2]),
                 (a[0], pos, b[2])], closed=True))
        else:
            plane = rect_face(a[0], a[1], b[0], b[1], pos)
        return geo.boolean_intersection(body, plane)

    # ========================================================= Laser

    class FingerzinkenNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Fingerzinken"
        INPUTS = [("a", "pt", "0 0 0", False), ("b", "pt", "100 0 0", False),
                  ("staerke", "num", 3, False), ("zinke", "num", 10, False)]
        OUTPUTS = ["kante"]

        def __init__(self):
            super().__init__()
            self.add_combo_menu("start", "Beginnt mit", items=["Zinke", "Lücke"])

        def solve(self, a, b, staerke, zinke):
            a, b = np.array(a, float), np.array(b, float)
            d = b - a
            L = float(np.linalg.norm(d))
            u = d / L
            nrm = np.array([-u[1], u[0], 0.0])        # links der Laufrichtung
            n = odd_count(L, zinke)
            w = L / n
            first = 0 if self.get_property("start") == "Zinke" else 1
            pts = []
            for k in range(n):
                off = 0.0 if (k + first) % 2 == 0 else staerke
                p0 = a + u * (k * w) + nrm * off
                p1 = a + u * ((k + 1) * w) + nrm * off
                pts += [tuple(p0), tuple(p1)]
            return geo.make_polyline(pts)

    class ZinkenBoxNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Zinken-Box"
        INPUTS = [("breite", "num", 100, False), ("tiefe", "num", 70, False),
                  ("hoehe", "num", 50, False), ("staerke", "num", 3, False),
                  ("zinke", "num", 10, False), ("abstand", "num", 5, False)]
        OUTPUTS = ["flach", "montiert"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("deckel", "", text="mit Deckel", state=False)

        def solve(self, breite, tiefe, hoehe, staerke, zinke, abstand):
            B, T, H, t = breite, tiefe, hoehe, staerke
            if min(B, T, H) <= 4 * t:
                raise ValueError("Maße zu klein für die Materialstärke")
            lid = self.get_property("deckel")
            top = "zinke" if lid else "glatt"
            # Vorne/Hinten besitzen alle Würfelecken, die anderen nicht
            spec = {
                "Boden": (B, T, {"v0": "luecke", "v1": "luecke",
                                 "u0": "luecke", "u1": "luecke"}, False),
                "Vorne": (B, H, {"v0": "zinke", "v1": top,
                                 "u0": "zinke", "u1": "zinke"}, True),
                "Hinten": (B, H, {"v0": "zinke", "v1": top,
                                  "u0": "zinke", "u1": "zinke"}, True),
                "Links": (T, H, {"v0": "zinke", "v1": top,
                                 "u0": "luecke", "u1": "luecke"}, False),
                "Rechts": (T, H, {"v0": "zinke", "v1": top,
                                  "u0": "luecke", "u1": "luecke"}, False),
            }
            if lid:
                spec["Deckel"] = spec["Boden"]
            place = box_placements(B, T, H, t)
            faces, solids = [], []
            for name, (W, Hh, edges, keep) in spec.items():
                face = panel_face(W, Hh, t, edges, keep, zinke)
                faces.append(face)
                solids.append(geo.apply_matrix(prism(face, (0, 0, t)),
                                               place[name]))
            flat = layout_row(faces, abstand, y=-(max(T, H) + 30))
            return flat, solids

    class LivingHingeNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Living Hinge"
        INPUTS = [("ecke", "pt", "0 0 0", False), ("breite", "num", 60, False),
                  ("hoehe", "num", 80, False), ("schnitt", "num", 18, False),
                  ("steg", "num", 3, False), ("abstand", "num", 1.5, False)]
        OUTPUTS = ["schnitte"]

        def solve(self, ecke, breite, hoehe, schnitt, steg, abstand):
            x0, y0, z = ecke
            P = schnitt + steg
            cols = max(1, int(breite / abstand))
            lines = []
            for i in range(cols + 1):
                x = x0 + i * breite / cols
                shift = -schnitt / 2 if i % 2 == 0 else steg / 2
                s = shift
                while s < hoehe:
                    a, b = max(s, 0.0), min(s + schnitt, hoehe)
                    if i % 2 == 1:      # innere Spalten lassen den Rand stehen
                        a, b = max(a, steg), min(b, hoehe - steg)
                    if b - a > 0.5:
                        lines.append(geo.make_line((x, y0 + a, z),
                                                   (x, y0 + b, z)))
                    s += P
            return lines

    class KerfNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Kerf-Ausgleich"
        INPUTS = [("teile", "geo", None, True), ("kerf", "num", 0.1, False)]
        OUTPUTS = ["konturen"]

        def solve(self, teile, kerf):
            from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeOffset
            from OCP.GeomAbs import GeomAbs_Intersection
            faces = [f for s in teile for f in faces_of(s)]
            curves = [s for s in teile if not list(faces_of(s))]
            if curves:
                faces += [f for r in geo.planar_regions(curves)
                          for f in faces_of(r)]
            out = []
            for f in faces:
                mk = BRepOffsetAPI_MakeOffset(f, GeomAbs_Intersection)
                mk.Perform(kerf / 2)
                if not mk.IsDone():
                    raise ValueError("Versatz fehlgeschlagen")
                out.append(mk.Shape())
            return out

    class VerschachtelnNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Verschachteln"
        INPUTS = [("teile", "geo", None, True), ("breite", "num", 200, False),
                  ("hoehe", "num", 200, False), ("abstand", "num", 3, False)]
        OUTPUTS = ["platziert", "platten", "rest"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("drehen", "", text="90° drehen erlaubt",
                              state=True)

        def compute(self, inputs):
            W = next(inputs["breite"].items())
            H = next(inputs["hoehe"].items())
            g = next(inputs["abstand"].items())
            turn = self.get_property("drehen")
            items = []
            for s in inputs["teile"].items():
                lo, hi = bbox(s)
                w, h = hi[0] - lo[0], hi[1] - lo[1]
                s = geo.translate(s, (-lo[0], -lo[1], -lo[2]))
                if turn and h > w and h <= W:     # liegend packt dichter
                    s = geo.rotate(s, (0, 0, 0), (0, 0, 1), 90)
                    lo, hi = bbox(s)
                    s = geo.translate(s, (-lo[0], -lo[1], 0))
                    w, h = h, w
                items.append((h, w, s))
            items.sort(key=lambda it: -it[0])
            placed, sheets, rest = Tree(), Tree(), Tree()
            sheet, x, y, shelf = 0, 0.0, 0.0, 0.0
            for h, w, s in items:
                if w > W or h > H:
                    rest.add((0,), s)
                    continue
                if x + w > W:
                    x, y, shelf = 0.0, y + shelf + g, 0.0
                if y + h > H:
                    sheet, x, y, shelf = sheet + 1, 0.0, 0.0, 0.0
                ox = sheet * (W + 20)
                placed.add((sheet,), geo.translate(s, (ox + x, y, 0)))
                x += w + g
                shelf = max(shelf, h)
            for i in range(sheet + 1 if placed.b else 0):
                ox = i * (W + 20)
                sheets.add((i,), geo.make_rectangle((ox, 0, 0),
                                                    (ox + W, H, 0)))
            return {"platziert": placed, "platten": sheets, "rest": rest}

    class SvgExportNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "SVG-Export (Laser)"
        SINK = True
        INPUTS = [("schneiden", "geo", None, True),
                  ("gravieren", "geo", None, True)]
        OPTIONAL = ("schneiden", "gravieren")
        OUTPUTS = ["datei"]

        def __init__(self):
            super().__init__()
            self.add_text_input("pfad", "Datei (.svg)",
                                text="~/Desktop/laser.svg")
            self.add_checkbox("aktiv", "", text="schreiben", state=False)

        def gather_paths(self, shapes):
            polys = []
            for s in shapes:
                if not is_shape(s):
                    continue
                for e in edges_of(s):
                    pl = _edge_polyline(e, 0.02)
                    if pl is not None and len(pl) >= 2:
                        polys.append([tuple(p[:2]) for p in pl])
            return chain(polys)

        def compute(self, inputs):
            groups = {"#FF0000": self.gather_paths(inputs["schneiden"].items()),
                      "#0000FF": self.gather_paths(inputs["gravieren"].items())}
            if not self.get_property("aktiv"):
                n = sum(len(v) for v in groups.values())
                return {"datei": Tree.of(f"aus · {n} Pfade")}
            pts = [p for paths in groups.values() for pl in paths for p in pl]
            if not pts:
                raise ValueError("Keine Kurven")
            arr = np.array(pts)
            x0, y0 = arr.min(axis=0)
            x1, y1 = arr.max(axis=0)
            w, h = x1 - x0, y1 - y0
            lines = [f'<svg xmlns="http://www.w3.org/2000/svg" '
                     f'width="{w:.3f}mm" height="{h:.3f}mm" '
                     f'viewBox="0 0 {w:.3f} {h:.3f}">']
            for color, paths in groups.items():
                for pl in paths:
                    d = " ".join(f"{'M' if i == 0 else 'L'}{x - x0:.3f},"
                                 f"{y1 - y:.3f}" for i, (x, y) in enumerate(pl))
                    if pl[0] == pl[-1]:
                        d += " Z"
                    lines.append(f'<path d="{d}" fill="none" stroke="{color}" '
                                 f'stroke-width="0.1"/>')
            lines.append("</svg>")
            path = os.path.expanduser(self.get_property("pfad"))
            with open(path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines))
            return {"datei": Tree.of(f"{w:.1f}×{h:.1f} mm → {path}")}

    class SchlitzeNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Schlitze"
        INPUTS = [("platte", "geo", None, False), ("punkte", "pt", None, True),
                  ("breite", "num", 3, False), ("tiefe", "num", 20, False)]
        OUTPUTS = ["platte"]

        def __init__(self):
            super().__init__()
            self.add_combo_menu("richtung", "Schlitz", items=["von oben",
                                                              "von unten"])

        def solve(self, platte, punkte, breite, tiefe):
            face = to_face(geo, platte)
            big = 1e4
            down = self.get_property("richtung") == "von oben"
            cuts = []
            for x, y, z in punkte:
                y0, y1 = (y - tiefe, y + big) if down else (y - big, y + tiefe)
                cuts.append(rect_face(x - breite / 2, y0, x + breite / 2, y1, z))
            return geo.boolean_difference(face, geo.make_compound(cuts))

    class KonturschnittNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Konturschnitt"
        INPUTS = [("koerper", "geo", None, False), ("anzahl", "int", 8, False),
                  ("abstand", "num", 5, False)]
        OUTPUTS = ["schnitte", "flach"]

        def __init__(self):
            super().__init__()
            self.add_combo_menu("achse", "Achse", items=["Z", "X", "Y"])

        def compute(self, inputs):
            body = next(inputs["koerper"].items())
            n = max(1, next(inputs["anzahl"].items()))
            gap = next(inputs["abstand"].items())
            axis = self.get_property("achse")
            k = "XYZ".index(axis)
            lo, hi = bbox(body)
            cuts, flats = Tree(), []
            for i in range(n):
                pos = lo[k] + (i + 0.5) * (hi[k] - lo[k]) / n
                s = section(body, axis, pos)
                if is_null(s):
                    continue
                cuts.add((i,), s)
                flats.append(flatten_to_xy(s, axis))
            off = -(hi - lo).max() - 30
            return {"schnitte": cuts,
                    "flach": Tree({(0,): layout_row(flats, gap, y=off)})}

    class WaffelNode(SerpNode):
        __identifier__ = "serp.Laser"
        NODE_NAME = "Waffel"
        INPUTS = [("koerper", "geo", None, False), ("nx", "int", 4, False),
                  ("ny", "int", 4, False), ("staerke", "num", 3, False),
                  ("abstand", "num", 5, False)]
        OUTPUTS = ["montiert", "flach"]

        def solve(self, koerper, nx, ny, staerke, abstand):
            t = staerke
            lo, hi = bbox(koerper)
            pad = 5.0
            xs = [lo[0] + (i + 0.5) * (hi[0] - lo[0]) / nx for i in range(nx)]
            ys = [lo[1] + (j + 0.5) * (hi[1] - lo[1]) / ny for j in range(ny)]
            span = hi - lo + 2 * pad
            rx = [geo.boolean_intersection(koerper, geo.make_box(
                (x - t / 2, lo[1] - pad, lo[2] - pad), t, span[1], span[2]))
                for x in xs]
            ry = [geo.boolean_intersection(koerper, geo.make_box(
                (lo[0] - pad, y - t / 2, lo[2] - pad), span[0], t, span[2]))
                for y in ys]
            cut_x = [[] for _ in xs]
            cut_y = [[] for _ in ys]
            for i, x in enumerate(xs):
                for j, y in enumerate(ys):
                    if is_null(rx[i]) or is_null(ry[j]):
                        continue
                    col = geo.boolean_intersection(rx[i], ry[j])
                    if is_null(col):
                        continue
                    (_, _, z0), (_, _, z1) = bbox(col)
                    zm = (z0 + z1) / 2
                    cut_x[i].append(geo.make_box((x - t, y - t / 2, zm),
                                                 2 * t, t, z1 - zm + pad))
                    cut_y[j].append(geo.make_box((x - t / 2, y - t, z0 - pad),
                                                 t, 2 * t, zm - z0 + pad))
            ribs, flats = [], []
            for rib, cuts, axis, pos in (
                    [(r, c, "X", x) for r, c, x in zip(rx, cut_x, xs)]
                    + [(r, c, "Y", y) for r, c, y in zip(ry, cut_y, ys)]):
                if is_null(rib):
                    continue
                if cuts:
                    rib = geo.boolean_difference(rib, geo.make_compound(cuts))
                ribs.append(rib)
                flats.append(flatten_to_xy(section(rib, axis, pos), axis))
            off = -(hi - lo).max() - 30
            return ribs, layout_row(flats, abstand, y=off)

    # ======================================================= 3D-Druck

    class DruckCheckNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Druck-Check"
        SINK = True                       # Analyse: Eingang bleibt sichtbar
        WARN_OUTPUTS = ("flaechen",)
        INPUTS = [("koerper", "geo", None, False), ("winkel", "num", 45, False),
                  ("wand", "num", 1.0, False)]
        OUTPUTS = ["ueberhang", "flaechen", "bericht"]

        def solve(self, koerper, winkel, wand):
            from serpentine3d.core.printcheck import analyze
            r = analyze(koerper, overhang_deg=winkel, wall_threshold=wand)
            from serpentine3d.core.mesh import MeshShape
            lo, hi = bbox(koerper)
            lim = -math.sin(math.radians(winkel))
            m = tessellate(koerper)
            v, t = m.vertices.astype(float), m.triangles
            nv = np.cross(v[t[:, 1]] - v[t[:, 0]], v[t[:, 2]] - v[t[:, 0]])
            ln = np.linalg.norm(nv, axis=1)
            nz = np.divide(nv[:, 2], ln, out=np.zeros(len(nv)), where=ln > 0)
            cz = v[t, 2].mean(axis=1)
            mask = (nz < lim) & (cz > lo[2] + 1e-3 * max(hi[2] - lo[2], 1))
            # Überhang-Dreiecke als eigenes Netz, leicht abgesenkt sichtbar
            bad = ([MeshShape(v - [0, 0, 0.05], t[mask])]
                   if mask.any() else [])
            wall = r.get("min_wall")
            text = (f"Überhang {r['overhang_fraction'] * 100:.1f} % · "
                    f"Wand min {wall:.2f} mm · " if wall is not None else
                    f"Überhang {r['overhang_fraction'] * 100:.1f} % · ")
            text += ("dicht" if r["watertight"] else "OFFEN") + (
                " · DÜNN" if r.get("thin") else "")
            return round(r["overhang_fraction"] * 100, 2), bad, text

    class AufBettNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Auf Bett legen"
        INPUTS = [("koerper", "geo", None, False)]
        OUTPUTS = ["koerper"]

        def __init__(self):
            super().__init__()
            self.add_combo_menu("lage", "Lage", items=["größte Fläche unten",
                                                       "so lassen"])
            self.add_checkbox("mitte", "", text="auf Bettmitte", state=True)

        def solve(self, koerper):
            from OCP.BRepAdaptor import BRepAdaptor_Surface
            from OCP.GeomAbs import GeomAbs_Plane
            from OCP.TopAbs import TopAbs_REVERSED
            s = koerper
            if self.get_property("lage") == "größte Fläche unten":
                best, normal = 0.0, None
                for f in faces_of(s):
                    ad = BRepAdaptor_Surface(f)
                    if ad.GetType() != GeomAbs_Plane:
                        continue
                    a = area(f)
                    if a > best:
                        d = ad.Plane().Axis().Direction()
                        n = np.array([d.X(), d.Y(), d.Z()])
                        if f.Orientation() == TopAbs_REVERSED:
                            n = -n
                        best, normal = a, n
                if normal is not None:
                    down = np.array([0.0, 0.0, -1.0])
                    axis = np.cross(normal, down)
                    ang = math.degrees(math.acos(max(-1, min(1, normal @ down))))
                    if np.linalg.norm(axis) < 1e-9:
                        axis = np.array([1.0, 0, 0])
                    if ang > 1e-6:
                        s = geo.rotate(s, (0, 0, 0), tuple(axis), ang)
            lo, hi = bbox(s)
            dx = -(lo[0] + hi[0]) / 2 if self.get_property("mitte") else 0
            dy = -(lo[1] + hi[1]) / 2 if self.get_property("mitte") else 0
            return geo.translate(s, (dx, dy, -lo[2]))

    class ToleranzPaarNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Toleranz-Paar"
        INPUTS = [("mitte", "pt", "0 0 0", False),
                  ("durchmesser", "num", 8, False),
                  ("laenge", "num", 20, False), ("spiel", "num", 0.2, False)]
        OUTPUTS = ["stift", "bohrung"]

        def solve(self, mitte, durchmesser, laenge, spiel):
            x, y, z = mitte
            stift = geo.make_cylinder(mitte, durchmesser / 2, laenge)
            bohrung = geo.make_cylinder((x, y, z - 0.5),
                                        durchmesser / 2 + spiel, laenge + 1)
            return stift, bohrung

    class GitterNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Gitter-Füllung"
        INPUTS = [("koerper", "geo", None, False), ("zelle", "num", 10, False),
                  ("steg", "num", 1.5, False), ("haut", "num", 1.2, False)]
        OUTPUTS = ["koerper"]

        def __init__(self):
            super().__init__()
            self.add_combo_menu("typ", "Muster", items=["Waben", "Würfelgitter"])

        def solve(self, koerper, zelle, steg, haut):
            lo, hi = bbox(koerper)
            pad = zelle
            a, b = lo - pad, hi + pad
            if self.get_property("typ") == "Waben":
                r = zelle / 2
                holes = []
                dx, dy = 1.5 * r, math.sqrt(3) * r
                i = 0
                x = a[0]
                while x <= b[0]:
                    y = a[1] + (dy / 2 if i % 2 else 0)
                    while y <= b[1]:
                        ri = r - steg / math.sqrt(3)
                        pts = [(x + ri * math.cos(math.pi / 3 * k),
                                y + ri * math.sin(math.pi / 3 * k), a[2])
                               for k in range(6)]
                        holes.append(geo.planar_face(
                            geo.make_polyline(pts, closed=True)))
                        y += dy
                    x += dx
                    i += 1
                tool = prisms(geo, holes, (0, 0, b[2] - a[2]))
                core = geo.boolean_difference(koerper, tool)
            else:
                n = [int((b[k] - a[k]) / zelle) + 1 for k in range(3)]
                span = b - a
                core = None
                for k in range(3):          # Stäbe entlang Achse k
                    bars = []               # je Achse überlappungsfrei
                    o1, o2 = [m for m in range(3) if m != k]
                    for i1 in range(n[o1]):
                        for i2 in range(n[o2]):
                            c = np.array(a, float)
                            c[o1] += i1 * zelle - steg / 2
                            c[o2] += i2 * zelle - steg / 2
                            size = [steg, steg, steg]
                            size[k] = span[k]
                            bars.append(geo.make_box(tuple(c), *size))
                    part = geo.boolean_intersection(koerper,
                                                    geo.make_compound(bars))
                    core = part if core is None else geo.boolean_union(core,
                                                                       part)
            if haut > 0:
                # shell_solid liefert bei geschlossenem Körper den inneren
                # Versatzkörper, nicht die Schale
                skin = geo.boolean_difference(koerper,
                                              geo.shell_solid(koerper, haut))
                core = geo.boolean_union(skin, core)
            return core

    class GyroidNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Gyroid"
        INPUTS = [("mitte", "pt", "0 0 0", False), ("breite", "num", 40, False),
                  ("tiefe", "num", 40, False), ("hoehe", "num", 40, False),
                  ("zelle", "num", 12, False), ("wand", "num", 1.2, False),
                  ("feinheit", "int", 10, False)]
        OUTPUTS = ["netz"]

        def __init__(self):
            super().__init__()
            self.add_combo_menu("form", "Hülle", items=["Quader", "Zylinder"])

        def solve(self, mitte, breite, tiefe, hoehe, zelle, wand, feinheit):
            from serpentine3d.core.mesh import MeshShape
            step = zelle / max(4, feinheit)
            cx, cy, cz = mitte
            half = np.array([breite, tiefe, hoehe]) / 2
            lo = np.array([cx, cy, cz + half[2]]) - half - step
            hi = np.array([cx, cy, cz + half[2]]) + half + step
            axes = [np.arange(lo[k], hi[k] + step, step) for k in range(3)]
            X, Y, Z = np.meshgrid(*axes, indexing="ij")
            k = 2 * math.pi / zelle
            g = (np.sin(k * X) * np.cos(k * Y) + np.sin(k * Y) * np.cos(k * Z)
                 + np.sin(k * Z) * np.cos(k * X))
            f = (np.abs(g) / (k * 1.2)) - wand / 2      # ~ Abstand zur Wand
            px, py, pz = X - cx, Y - cy, Z - (cz + half[2])
            if self.get_property("form") == "Zylinder":
                hull = np.maximum(np.sqrt(px ** 2 + py ** 2) - half[0],
                                  np.abs(pz) - half[2])
            else:
                hull = np.max(np.stack([np.abs(px) - half[0],
                                        np.abs(py) - half[1],
                                        np.abs(pz) - half[2]]), axis=0)
            f = np.maximum(f, hull)
            v, t = marching_tets(f, lo, step)
            if not len(t):
                raise ValueError("Leeres Netz (Wand zu dünn?)")
            return MeshShape(v, t)

    class GewindeNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Gewinde"
        INPUTS = [("mitte", "pt", "0 0 0", False),
                  ("durchmesser", "num", 10, False),
                  ("steigung", "num", 1.5, False), ("laenge", "num", 12, False),
                  ("toleranz", "num", 0.2, False)]
        OUTPUTS = ["gewinde"]

        def __init__(self):
            super().__init__()
            self.add_combo_menu("art", "Art", items=["Bolzen (außen)",
                                                     "Bohrung (Werkzeug)"])

        def solve(self, mitte, durchmesser, steigung, laenge, toleranz):
            p = steigung
            depth = 0.6134 * p
            rmaj = durchmesser / 2
            if self.get_property("art").startswith("Bohrung"):
                rmaj += toleranz
            rmin = rmaj - depth

            def shape(u):
                u %= 1.0
                if u < 0.125:
                    return 1.0
                if u < 0.4375:
                    return 1 - (u - 0.125) / 0.3125
                if u < 0.6875:
                    return 0.0
                return (u - 0.6875) / 0.3125

            n = 60
            pts = []
            for i in range(n):
                th = 2 * math.pi * i / n
                r = rmin + depth * shape(-th / (2 * math.pi))
                pts.append((r * math.cos(th), r * math.sin(th), 0.0))
            base = geo.make_interp_curve(pts, closed=True)
            secs = max(2, int(math.ceil(laenge / p * 6)) + 1)
            profiles = []
            for s in range(secs):
                z = laenge * s / (secs - 1)
                c = geo.rotate(base, (0, 0, 0), (0, 0, 1), 360 * z / p)
                profiles.append(geo.translate(c, (0, 0, z)))
            solid = geo.loft(profiles, solid=True)
            return geo.translate(solid, mitte)

    class PraegenNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Prägen"
        INPUTS = [("koerper", "geo", None, False), ("hoehe", "num", 8, False),
                  ("tiefe", "num", 0.6, False)]
        OUTPUTS = ["koerper"]

        def __init__(self):
            super().__init__()
            self.add_text_input("text", "Text", text="MW")
            self.add_combo_menu("art", "Art", items=["versenkt", "erhaben"])

        def solve(self, koerper, hoehe, tiefe):
            from serpentine3d.core.text import text_curves
            curves = text_curves(self.get_property("text"), hoehe, bold=True)
            faces = geo.planar_regions(curves)
            if not faces:
                raise ValueError("Kein Text")
            lo, hi = bbox(koerper)
            tl, th = bbox(geo.make_compound(faces))
            dx = (lo[0] + hi[0]) / 2 - (tl[0] + th[0]) / 2
            dy = (lo[1] + hi[1]) / 2 - (tl[1] + th[1]) / 2
            sunk = self.get_property("art") == "versenkt"
            z0 = hi[2] - tiefe if sunk else hi[2] - 0.01
            tool = geo.make_compound([fix(prism(fix(f), (0, 0, tiefe + 0.01)))
                                      for f in faces])
            tool = geo.translate(tool, (dx, dy, z0))
            return (geo.boolean_difference(koerper, tool) if sunk
                    else geo.boolean_union(koerper, tool))

    class MehrfarbNode(SerpNode):
        __identifier__ = "serp.Druck"
        NODE_NAME = "Mehrfarb-Teilen"
        INPUTS = [("koerper", "geo", None, False), ("hoehen", "num", None, True)]
        OUTPUTS = ["teile"]

        def solve(self, koerper, hoehen):
            lo, hi = bbox(koerper)
            cuts = sorted(h for h in hoehen if lo[2] < h < hi[2])
            bounds = [lo[2] - 1] + cuts + [hi[2] + 1]
            pad = 5.0
            parts = []
            for z0, z1 in zip(bounds, bounds[1:]):
                box = geo.make_box((lo[0] - pad, lo[1] - pad, z0),
                                   hi[0] - lo[0] + 2 * pad,
                                   hi[1] - lo[1] + 2 * pad, z1 - z0)
                part = geo.boolean_intersection(koerper, box)
                if not is_null(part):
                    parts.append(part)
            return parts

    return [
        FingerzinkenNode, ZinkenBoxNode, LivingHingeNode, KerfNode,
        VerschachtelnNode, SvgExportNode, SchlitzeNode, KonturschnittNode,
        WaffelNode,
        DruckCheckNode, AufBettNode, ToleranzPaarNode, GitterNode, GyroidNode,
        GewindeNode, PraegenNode, MehrfarbNode,
    ]


# ------------------------------------------------------- Rechteck-Kontur

def rect_outline(W, H, cuts):
    """Umriss von Rechteck W x H minus achsparalleler Rechtecke am Rand.

    Exakt über ein Raster aus allen vorkommenden Koordinaten: Zellen
    behalten/verwerfen, Randkanten gegen den Uhrzeigersinn verketten.
    """
    xs = sorted({0.0, W, *[c[0] for c in cuts], *[c[2] for c in cuts]})
    ys = sorted({0.0, H, *[c[1] for c in cuts], *[c[3] for c in cuts]})
    xs = [x for x in xs if 0 <= x <= W]
    ys = [y for y in ys if 0 <= y <= H]
    nx, ny = len(xs) - 1, len(ys) - 1
    keep = np.ones((nx, ny), bool)
    for x0, y0, x1, y1 in cuts:
        for i in range(nx):
            cx = (xs[i] + xs[i + 1]) / 2
            if not x0 < cx < x1:
                continue
            for j in range(ny):
                if y0 < (ys[j] + ys[j + 1]) / 2 < y1:
                    keep[i, j] = False
    inside = lambda i, j: 0 <= i < nx and 0 <= j < ny and keep[i, j]  # noqa
    nxt = {}
    for i in range(nx):
        for j in range(ny):
            if not keep[i, j]:
                continue
            # Innenseite links der Laufrichtung
            if not inside(i, j - 1):
                nxt[(i, j)] = (i + 1, j)
            if not inside(i + 1, j):
                nxt[(i + 1, j)] = (i + 1, j + 1)
            if not inside(i, j + 1):
                nxt[(i + 1, j + 1)] = (i, j + 1)
            if not inside(i - 1, j):
                nxt[(i, j + 1)] = (i, j)
    start = min(nxt)
    loop, p = [start], nxt[start]
    while p != start:
        loop.append(p)
        p = nxt[p]
    pts = [(xs[i], ys[j]) for i, j in loop]
    out = []
    for k, q in enumerate(pts):         # kollineare Punkte raus
        a, c = pts[k - 1], pts[(k + 1) % len(pts)]
        if (q[0] - a[0]) * (c[1] - q[1]) - (q[1] - a[1]) * (c[0] - q[0]) != 0:
            out.append(q)
    return out


# ------------------------------------------------------------ SVG-Ketten

def chain(polys, tol=1e-3):
    """Einzelne Kantenzüge an gemeinsamen Endpunkten zu Pfaden verbinden."""
    key = lambda p: (round(p[0] / tol), round(p[1] / tol))  # noqa: E731
    ends = {}
    for i, pl in enumerate(polys):
        ends.setdefault(key(pl[0]), []).append(i)
        ends.setdefault(key(pl[-1]), []).append(i)
    used, out = set(), []
    for i in range(len(polys)):
        if i in used:
            continue
        used.add(i)
        path = list(polys[i])
        for _side in range(2):
            while True:
                nxt = [j for j in ends.get(key(path[-1]), []) if j not in used]
                if not nxt:
                    break
                j = nxt[0]
                used.add(j)
                seg = polys[j]
                if key(seg[0]) != key(path[-1]):
                    seg = seg[::-1]
                path.extend(seg[1:])
            path.reverse()
        if key(path[0]) == key(path[-1]):
            path[-1] = path[0]
        out.append(path)
    return out


# ---------------------------------------------------- Marching Tetraeder

# Würfelecken (i, j, k) und Zerlegung in 6 Tetraeder entlang der Diagonale 0-6
_CORNERS = np.array([(0, 0, 0), (1, 0, 0), (1, 1, 0), (0, 1, 0),
                     (0, 0, 1), (1, 0, 1), (1, 1, 1), (0, 1, 1)])
_TETS = [(0, 5, 1, 6), (0, 1, 2, 6), (0, 2, 3, 6), (0, 3, 7, 6),
         (0, 7, 4, 6), (0, 4, 5, 6)]
_TET_EDGES = [(0, 1), (0, 2), (0, 3), (1, 2), (1, 3), (2, 3)]
# Fall (Bitmaske innen) -> Dreiecke aus Kantennummern
_CASES = {1: [(0, 1, 2)], 2: [(0, 4, 3)], 3: [(1, 3, 4), (1, 4, 2)],
          4: [(1, 3, 5)], 5: [(0, 3, 5), (0, 5, 2)], 6: [(0, 1, 5), (0, 5, 4)],
          7: [(2, 4, 5)]}
for _m in list(_CASES):
    _CASES[15 - _m] = [(a, c, b) for a, b, c in _CASES[_m]]


def marching_tets(f, origin, step):
    """Fläche f=0 als Dreiecksnetz; Dreiecke nach dem Gradienten ausgerichtet."""
    nx, ny, nz = (s - 1 for s in f.shape)
    ii, jj, kk = np.meshgrid(np.arange(nx), np.arange(ny), np.arange(nz),
                             indexing="ij")
    base = np.stack([ii.ravel(), jj.ravel(), kk.ravel()], axis=1)
    tris = []
    for tet in _TETS:
        idx = base[:, None, :] + _CORNERS[list(tet)][None, :, :]   # (N,4,3)
        val = f[idx[..., 0], idx[..., 1], idx[..., 2]]             # (N,4)
        mask = ((val < 0) * (1 << np.arange(4))).sum(axis=1)
        for case, faces in _CASES.items():
            sel = mask == case
            if not sel.any():
                continue
            p = idx[sel].astype(float)
            v = val[sel]
            for tri in faces:
                corners = []
                for e in tri:
                    a, b = _TET_EDGES[e]
                    va, vb = v[:, a], v[:, b]
                    t = va / (va - vb)
                    corners.append(p[:, a] + (p[:, b] - p[:, a]) * t[:, None])
                tris.append(np.stack(corners, axis=1))
    if not tris:
        return np.zeros((0, 3)), np.zeros((0, 3), np.uint32)
    T = np.concatenate(tris)                                       # (M,3,3)
    # nach außen (f steigt) ausrichten
    gx, gy, gz = np.gradient(f)
    c = np.clip(np.rint(T.mean(axis=1)).astype(int), 0,
                np.array(f.shape) - 1)
    grad = np.stack([gx[c[:, 0], c[:, 1], c[:, 2]],
                     gy[c[:, 0], c[:, 1], c[:, 2]],
                     gz[c[:, 0], c[:, 1], c[:, 2]]], axis=1)
    n = np.cross(T[:, 1] - T[:, 0], T[:, 2] - T[:, 0])
    flip = (n * grad).sum(axis=1) < 0
    T[flip] = T[flip][:, [0, 2, 1]]
    verts = T.reshape(-1, 3) * step + np.asarray(origin)
    # Punkte verschweißen
    keyed = np.round(verts / (step * 1e-4)).astype(np.int64)
    _, first, inv = np.unique(keyed, axis=0, return_index=True,
                              return_inverse=True)
    tri_idx = inv.reshape(-1, 3).astype(np.uint32)
    keep = ((tri_idx[:, 0] != tri_idx[:, 1]) & (tri_idx[:, 1] != tri_idx[:, 2])
            & (tri_idx[:, 0] != tri_idx[:, 2]))
    return verts[first], tri_idx[keep]
