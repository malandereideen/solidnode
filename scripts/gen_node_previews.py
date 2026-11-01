"""Render the small preview images shown when hovering a node in the palette.

    QT_QPA_PLATFORM=offscreen python scripts/gen_node_previews.py

Each node is built in a tiny graph — nodes with geometry inputs get a demo
source wired in (DEMO below) — evaluated, and drawn as a shaded isometric
picture with QPainter (no OpenGL needed): the node's result in green, red
for warnings, its inputs as grey wireframe. Nodes without geometry output
(math, lists, export …) get no picture. Run again after adding nodes.
"""

import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtCore, QtGui, QtWidgets  # noqa: E402
import numpy as np  # noqa: E402

W, H = 160, 110            # logical size; written as 1x and @2x

# target node class → its own properties and the sources wired into it:
# {"set": {prop: value}, "in": {port: [(source class, {props}, output)]}}
BOX = ("BoxNode", {"in_ecke": "20 0 0", "in_x": "40", "in_y": "30",
                   "in_z": "20"}, "form")
KUGEL = ("KugelNode", {"in_radius": "35"}, "form")
WUERFEL = ("BoxNode", {"in_x": "60", "in_y": "40", "in_z": "40"}, "form")
PUNKTE = ("ZufallspunkteNode", {"in_anzahl": "7"}, "punkte")
DEMO = {
    "PolylinieNode": {"in": {"punkte": [PUNKTE]}},
    "InterpKurveNode": {"in": {"punkte": [PUNKTE]}},
    "ExtrudierenNode": {"in": {"profil": [("PolygonNode", {}, "kurve")]}},
    "LoftNode": {"in": {"profile": [
        ("KreisNode", {"in_radius": "40"}, "kurve"),
        ("PolygonNode", {"in_mitte": "0 0 50", "in_radius": "25"}, "kurve"),
        ("KreisNode", {"in_mitte": "0 0 100", "in_radius": "35"}, "kurve")]}},
    "DrehkoerperNode": {"set": {"in_richtung": "0 1 0"}, "in": {"profil": [
        ("KreisNode", {"in_mitte": "40 0 0", "in_radius": "12"}, "kurve")]}},
    "BooleanNode": {"in": {"a": [WUERFEL], "b": [
        ("KugelNode", {"in_mitte": "60 40 40", "in_radius": "30"}, "form")]}},
    "SchaleNode": {"in": {"koerper": [WUERFEL]}},
    "AbrundenNode": {"set": {"in_radius": "8"}, "in": {"koerper": [WUERFEL]}},
    "VerschiebenNode": {"set": {"in_x": "30", "in_z": "30"},
                        "in": {"geometrie": [BOX]}},
    "DrehenNode": {"set": {"in_winkel": "40"}, "in": {"geometrie": [BOX]}},
    "SkalierenNode": {"set": {"in_faktor": "1.6"}, "in": {"geometrie": [BOX]}},
    "SpiegelnNode": {"in": {"geometrie": [BOX]}},
    "PolarNode": {"in": {"geometrie": [BOX]}},
    "KurveTeilenNode": {"in": {"kurve": [("KreisNode", {}, "kurve")]}},
    "KurveVersetzenNode": {"set": {"in_abstand": "8"},
                           "in": {"kurve": [("PolygonNode", {}, "kurve")]}},
    "SweepNode": {"in": {
        "profil": [("PolygonNode", {"in_radius": "10", "in_seiten": "5"},
                    "kurve")],
        "pfad": [("LinieNode", {"in_b": "0 0 80"}, "kurve")]}},
    "RohrNode": {"set": {"in_radius": "5"}, "in": {"pfad": [
        ("InterpKurveNode", {}, "kurve")]}},
    "VoronoiNode": {"in": {"punkte": [("ZufallspunkteNode", {
        "in_anzahl": "14"}, "punkte")]}},
    "KerfNode": {"set": {"in_kerf": "6"}, "in": {"teile": [
        ("PolygonNode", {}, "kurve")]}},
    "VerschachtelnNode": {"in": {"teile": [("ZinkenBoxNode", {}, "flach")]}},
    "SchlitzeNode": {"in": {
        "platte": [("BoxNode", {"in_x": "100", "in_y": "60", "in_z": "3"},
                    "form")],
        "punkte": [("ZufallspunkteNode", {"in_breite": "100", "in_hoehe": "60",
                                          "in_anzahl": "4"}, "punkte")]}},
    "KonturschnittNode": {"in": {"koerper": [KUGEL]}},
    "WaffelNode": {"in": {"koerper": [KUGEL]}},
    "DruckCheckNode": {"solid_src": True, "in": {"koerper": [KUGEL]}},
    "AufBettNode": {"in": {"koerper": [
        ("ZylinderNode", {"in_hoehe": "30"}, "form")]}},
    "GitterNode": {"in": {"koerper": [WUERFEL]}},
    "PraegenNode": {"in": {"koerper": [
        ("BoxNode", {"in_x": "70", "in_y": "30", "in_z": "10"}, "form")]}},
    "MehrfarbNode": {"in": {"koerper": [KUGEL], "hoehen": [
        ("BereichNode", {"in_von": "-12", "in_bis": "12", "in_teile": "1"},
         "liste")]}, "multi": True},
}

# The pipe needs points for its path; wire them into the source curve.
SOURCE_INPUTS = {"InterpKurveNode": {"punkte": PUNKTE}}


MULTI = ["#6fdcab", "#e8b04a", "#6aa7e8", "#e0605a"]


class Single:
    """One item dressed as a tree for collect()."""

    def __init__(self, item):
        self.item = item

    def items(self):
        return iter([self.item])


def ascii_name(cls):
    name = cls.__name__
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        name = name.replace(a, b)
    return name


def collect(tree, mesh_of):
    """Triangles, segments and points of all items in a tree."""
    tris, segs, pts = [], [], []
    if tree is None:
        return tris, segs, pts
    for item in tree.items():
        if isinstance(item, tuple) and len(item) == 3:
            pts.append(np.asarray([item], float))
            continue
        try:
            m = mesh_of(item)
        except Exception:                       # noqa: BLE001
            continue
        if len(m.triangles):
            tris.append(m.vertices[m.triangles])
        if len(m.edge_segments):
            segs.append(m.edge_segments.reshape(-1, 2, 3))
        if len(m.points):
            pts.append(m.points)
    return tris, segs, pts


def iso(p):
    """Isometric view as SolidCraft's home view: x right-down, y right-up,
    z up (seen from +x, −y, +z)."""
    c, s = np.cos(np.pi / 6), np.sin(np.pi / 6)
    return np.stack([(p[..., 0] + p[..., 1]) * c,
                     (p[..., 0] - p[..., 1]) * s - p[..., 2]], -1)


def nearness(t):
    """Larger = closer to the viewer at (+x, −y, +z)."""
    return (t[..., 0] - t[..., 1] + t[..., 2]).sum(axis=1)


def render(layers, path):
    """layers: list of (tris, segs, pts, colour, wire_only)."""
    allp = [a.reshape(-1, 3) for tris, segs, pts, *_ in layers
            for group in (tris, segs, pts) for a in group]
    if not allp:
        return False
    flat = iso(np.concatenate(allp))
    lo, hi = flat.min(0), flat.max(0)
    span = np.maximum(hi - lo, 1e-6)
    k = min((W - 16) / span[0], (H - 16) / span[1])
    off = np.array([W, H]) / 2 - (lo + hi) / 2 * k
    light = np.array([0.3, -0.6, 1.0])
    light /= np.linalg.norm(light)
    for scale in (1, 2):
        img = QtGui.QImage(W * scale, H * scale,
                           QtGui.QImage.Format.Format_ARGB32_Premultiplied)
        img.fill(QtCore.Qt.GlobalColor.transparent)
        img.setDevicePixelRatio(scale)
        p = QtGui.QPainter(img)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        for tris, segs, pts, colour, wire in layers:
            base = QtGui.QColor(colour)
            if tris and not wire:
                t = np.concatenate(tris)
                n = np.cross(t[:, 1] - t[:, 0], t[:, 2] - t[:, 0])
                n /= np.maximum(np.linalg.norm(n, axis=1, keepdims=True),
                                1e-12)
                shade = 0.45 + 0.55 * np.abs(n @ light)
                order = np.argsort(nearness(t))   # far → near
                scr = iso(t) * k + off
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                for i in order:
                    c = QtGui.QColor.fromRgbF(base.redF() * shade[i],
                                              base.greenF() * shade[i],
                                              base.blueF() * shade[i])
                    p.setBrush(c)
                    p.setPen(QtGui.QPen(c, 0.4))
                    p.drawPolygon(QtGui.QPolygonF(
                        [QtCore.QPointF(*v) for v in scr[i]]))
            if segs:
                s = iso(np.concatenate(segs)) * k + off
                line = QtGui.QColor(base)
                if tris and not wire:
                    line = line.darker(260)
                    line.setAlpha(110)
                p.setPen(QtGui.QPen(line, 1.0 if wire or tris else 1.6))
                for a, b in s:
                    p.drawLine(QtCore.QPointF(*a), QtCore.QPointF(*b))
            if pts:
                q = iso(np.concatenate(pts)) * k + off
                p.setPen(QtCore.Qt.PenStyle.NoPen)
                p.setBrush(base)
                for x, y in q:
                    p.drawEllipse(QtCore.QPointF(x, y), 2.2, 2.2)
        p.end()
        name = path if scale == 1 else path.replace(".png", "@2x.png")
        img.save(name)
    return True


def main():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from solidnode import core
    from serpentine3d.core.tessellate import tessellate

    class Host:
        def show(self, *_a):
            pass

        def fit(self, *_a):
            pass

    panel = core.make_core()(Host())
    g = panel.graph
    by_name = {c.__name__: c for c in panel.NODE_CLASSES}
    out_dir = Path(__file__).resolve().parents[1] / "src" / "solidnode" \
        / "previews"
    out_dir.mkdir(exist_ok=True)
    for f in out_dir.glob("*.png"):
        f.unlink()

    def make(cname, props, pos):
        cls = by_name[cname]
        node = g.create_node(f"{cls.__identifier__}.{cls.__name__}", pos=pos)
        for k, v in props.items():
            node.set_property(k, v)
        return node

    made, skipped = 0, []
    for cls in panel.NODE_CLASSES:
        panel.new()
        spec = DEMO.get(cls.__name__, {})
        target = make(cls.__name__, spec.get("set", {}), [400, 0])
        sources = []
        for port, items in spec.get("in", {}).items():
            for j, (sname, props, out) in enumerate(items):
                src = make(sname, props, [0, 150 * len(sources)])
                for sport, (s2, p2, o2) in SOURCE_INPUTS.get(sname,
                                                            {}).items():
                    pre = make(s2, p2, [-300, 0])
                    pre.get_output(o2).connect_to(src.get_input(sport))
                src.get_output(out).connect_to(target.get_input(port))
                sources.append((src, out))
        panel.evaluate()
        meshes = {}

        def mesh_of(item):
            if id(item) not in meshes:
                meshes[id(item)] = (item, tessellate(item))
            return meshes[id(item)][1]

        layers = []
        for src, out in sources:
            tris, segs, pts = collect(panel.cache.get(src.id, {}).get(out),
                                      mesh_of)
            if spec.get("solid_src"):
                layers.append((tris, segs, pts, "#6fdcab", False))
                continue
            if tris:          # solids as wireframe outline only
                tris, pts = [], []
            layers.append((tris, segs, pts, "#8a9096", True))
        warn = getattr(target, "WARN_OUTPUTS", ())
        res = panel.cache.get(target.id, {})
        if spec.get("multi"):          # one colour per part
            tree = res.get(target.OUTPUTS[0])
            items = list(tree.items()) if tree is not None else []
            own = [(collect(Single(it), mesh_of), MULTI[i % len(MULTI)])
                   for i, it in enumerate(items)]
        else:
            own = [(collect(res.get(o), mesh_of), "#e0605a" if o in warn
                    else "#6fdcab") for o in target.OUTPUTS]
        if not any(any(t) for (t, _c) in own):
            skipped.append(cls.NODE_NAME)
            continue
        for (tris, segs, pts), colour in own:
            layers.append((tris, segs, pts, colour, False))
        if render(layers, str(out_dir / f"{ascii_name(cls)}.png")):
            made += 1
    print(f"{made} previews in {out_dir}")
    print("no geometry:", ", ".join(skipped))


if __name__ == "__main__":
    sys.exit(main())
