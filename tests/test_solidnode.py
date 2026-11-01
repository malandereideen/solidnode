"""Headless tests: every example computes, the core nodes measure right.

Run with:  QT_QPA_PLATFORM=offscreen pytest
"""

import json
import math
import os
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QT_API", "pyside6")

from PySide6 import QtWidgets  # noqa: E402

EXAMPLES = Path(__file__).resolve().parents[1] / "src" / "solidnode" / "examples"


class RecordingHost:
    """Stands in for SolidCraft/Serpentine3D: remembers what it was shown."""

    def __init__(self):
        self.chans = None
        self.items = []

    def show(self, chans, items):
        self.chans, self.items = chans, items

    def bake(self, items):
        return f"{len(items)} baked"

    def fit(self, lo, hi):
        pass


@pytest.fixture(scope="module")
def panel():
    app = QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from solidnode import core
    p = core.make_core()(RecordingHost())
    yield p
    del app


def volume(shape):
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps()
    BRepGProp.VolumeProperties_s(shape, g, 1e-6)
    return g.Mass()


def first(panel, node, out):
    tree = panel.cache[node.id][out]
    assert tree is not None, node.message
    return next(tree.items())


def errors(panel):
    return [f"{n.name()}: {n.message}" for n in panel.graph.all_nodes()
            if getattr(n, "message", "") and n.color()[0] > 120]


@pytest.mark.parametrize("path", sorted(EXAMPLES.glob("*.json")),
                         ids=lambda p: p.stem)
def test_examples_compute(panel, path):
    panel.load(str(path))
    panel.evaluate()
    assert not errors(panel)
    assert panel.host.items, "example shows nothing"


def test_slider_drives_geometry(panel):
    panel.load(str(EXAMPLES / "voronoi_platte.json"))
    panel.evaluate()
    by = {n.name(): n for n in panel.graph.all_nodes()}
    v1 = volume(first(panel, by["Platte gelocht"], "form"))
    by["Dicke"].set_property("wert", 6.0)
    panel.evaluate()
    v2 = volume(first(panel, by["Platte gelocht"], "form"))
    assert v2 == pytest.approx(2 * v1, rel=1e-6)


def test_data_tree_graft_and_flatten(panel):
    g = panel.graph
    panel.new()
    rng = g.create_node("serp.Parameter.BereichNode", pos=[0, 0])
    rng.set_property("in_teile", "4")
    graft = g.create_node("serp.Baum.AufpfropfenNode", pos=[200, 0])
    flat = g.create_node("serp.Baum.GlaettenNode", pos=[400, 0])
    rng.get_output("liste").connect_to(graft.get_input("daten"))
    graft.get_output("daten").connect_to(flat.get_input("daten"))
    panel.evaluate()
    t = panel.cache[graft.id]["daten"]
    assert len(t.b) == 5 and all(len(v) == 1 for v in t.b.values())
    assert list(panel.cache[flat.id]["daten"].b) == [(0,)]


def test_finger_jointed_box_is_exact(panel):
    g = panel.graph
    panel.new()
    box = g.create_node("serp.Laser.ZinkenBoxNode", pos=[0, 0])
    box.set_property("deckel", True)
    panel.evaluate()
    parts = list(panel.cache[box.id]["montiert"].items())
    assert len(parts) == 6
    total = sum(volume(p) for p in parts)
    assert total == pytest.approx(100 * 70 * 50 - 94 * 64 * 44, rel=1e-6)


POLY_FACES = {
    "Tetraeder": 4, "Hexaeder": 6, "Oktaeder": 8, "Dodekaeder": 12,
    "Ikosaeder": 20, "Ikosaederstumpf": 32, "Würfelstumpf": 14,
    "Abgeschrägtes Dodekaeder": 92, "Großes Rhombenikosidodekaeder": 62,
}


@pytest.mark.parametrize("name,faces", POLY_FACES.items())
def test_polyhedra(panel, name, faces):
    from OCP.BRepCheck import BRepCheck_Analyzer
    from solidnode.fabrication import faces_of
    cls = next(c for c in panel.NODE_CLASSES if c.NODE_NAME == name)
    panel.new()
    node = panel.graph.create_node(f"{cls.__identifier__}.{cls.__name__}",
                                   pos=[0, 0])
    panel.evaluate()
    s = first(panel, node, "form")
    assert BRepCheck_Analyzer(s).IsValid()
    assert len(list(faces_of(s))) == faces


def test_octahedron_volume(panel):
    g = panel.graph
    panel.new()
    t = [t for t in g.registered_nodes() if t.endswith("Poly_Oktaeder")][0]
    n = g.create_node(t, pos=[0, 0])
    panel.evaluate()
    # Ø 40 over the corners → circumradius 20 → V = 4/3 r³
    assert volume(first(panel, n, "form")) == pytest.approx(4 / 3 * 20 ** 3,
                                                            rel=1e-6)


def test_svg_curves_and_sketch_mapping():
    from solidnode import hosts
    from serpentine3d.core import geometry as geo
    svg, at = hosts.curves_svg([geo.make_rectangle((10, 20, 0),
                                                   (110, 70, 0))])
    assert svg.count("<path") == 1 and at == [10.0, 70.0]


def test_sketch_arc_from_solidcraft_json():
    from solidnode import hosts
    design = {"sketches": [{"id": 1, "plane": {
        "origin": [0, 0, 0], "x_dir": [1, 0, 0], "y_dir": [0, 1, 0]},
        "curves": [{"id": "a1", "type": "arc", "center_at": [0, 0],
                    "radius": 10, "start_at": [10, 0], "end_at": [0, 10]}]}]}
    edge = hosts.sketch_curve(design, 1, "a1")
    from OCP.BRepGProp import BRepGProp
    from OCP.GProp import GProp_GProps
    g = GProp_GProps()
    BRepGProp.LinearProperties_s(edge, g)
    assert g.Mass() == pytest.approx(math.pi * 10 / 2, rel=1e-6)


def test_shape_roundtrip_through_graph_copy():
    from solidnode import hosts
    from serpentine3d.core import geometry as geo
    box = geo.make_box((0, 0, 0), 10, 20, 30)
    again = hosts.decode_shape(json.loads(json.dumps(hosts.encode_shape(box))))
    assert volume(again) == pytest.approx(6000, rel=1e-9)


def test_offset_surfaces_converted_for_solidcraft(panel):
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.BRepCheck import BRepCheck_Analyzer
    from OCP.GeomAbs import GeomAbs_OffsetSurface
    from solidnode import hosts
    from solidnode.fabrication import faces_of
    panel.load(str(EXAMPLES / "vase.json"))
    panel.evaluate()
    by = {n.name(): n for n in panel.graph.all_nodes()}
    vase = first(panel, by["Vase"], "form")
    fixed = hosts.no_offset_surfaces(vase)
    assert not any(BRepAdaptor_Surface(f).GetType() == GeomAbs_OffsetSurface
                   for f in faces_of(fixed))
    assert BRepCheck_Analyzer(fixed).IsValid()


def test_every_node_has_a_hover_card(panel):
    from solidnode import nodeinfo
    missing = [c.NODE_NAME for c in panel.NODE_CLASSES
               if c.NODE_NAME not in nodeinfo.DE]
    assert not missing
    with_picture = [c for c in panel.NODE_CLASSES if nodeinfo.preview_file(c)]
    assert len(with_picture) >= 60
    assert "<img" in nodeinfo.card(with_picture[0], "x")


def test_update_version_compare_and_plan(monkeypatch, tmp_path):
    from solidnode import update
    assert update.newer("0.1.10", "0.1.9")
    assert not update.newer("0.1.1", "0.1.1")
    assert not update.newer("0.1.0", "0.2")
    assert not update.newer("kaputt", "0.1")
    f = tmp_path / "init.py"
    f.write_text('__version__ = "9.9.9"\n')
    monkeypatch.setenv("SOLIDNODE_UPDATE_URL", f.as_uri())
    assert update.latest() == "9.9.9"
    monkeypatch.setenv("SOLIDNODE_NO_UPDATE_CHECK", "1")
    assert update.latest() is None
    what, prog, args, _cwd = update.plan()
    assert prog and args
