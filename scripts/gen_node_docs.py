"""Write docs/nodes.md from the node classes (run after adding nodes).

    QT_QPA_PLATFORM=offscreen python scripts/gen_node_docs.py
"""

import os
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
from PySide6 import QtWidgets  # noqa: E402


# English name and a one-line description per node (the app UI is German).
EN = {
    "Zahl": ("Number slider", "Slider with editable min, max and decimals."),
    "Geometrie holen": ("Pick geometry", "Take the selection from SolidCraft or Serpentine3D; a copy is stored in the graph, *linked* re-reads it when the CAD model changes."),
    "Folge": ("Series", "start, start+step, … (count values)."),
    "Bereich": ("Range", "Divide [from, to] into n equal steps (n+1 values)."),
    "Punkt": ("Point", "Point from x, y, z."),
    "Anzeige": ("Panel", "Shows values and the data tree."),
    "Rechnen": ("Math", "+ − × ÷ ^ min max remainder."),
    "Funktion": ("Expression", "Formula in x y z a b, with sin, cos, pi, sqrt …"),
    "Listen-Element": ("List item", "Item at index (wraps around)."),
    "Listen-Länge": ("List length", "Number of items per branch."),
    "Umkehren": ("Reverse list", ""),
    "Liste versetzen": ("Shift list", "Shift by n, optionally wrapping."),
    "Teilen": ("Partition list", "Split into chunks; each chunk becomes a branch."),
    "Aufpfropfen": ("Graft", "Every item into its own branch."),
    "Glätten": ("Flatten", "All branches into one."),
    "Vereinfachen": ("Simplify", "Remove the common path prefix."),
    "Matrix tauschen": ("Flip matrix", "Swap branches and items."),
    "Zweig wählen": ("Tree branch", "Pick a branch by index."),
    "Zusammenführen": ("Merge", "Merge two trees branch by branch."),
    "Linie": ("Line", ""),
    "Polylinie": ("Polyline", "Through points; open or closed."),
    "Kurve durch Punkte": ("Interpolated curve", "Smooth curve through points."),
    "Kreis": ("Circle", ""),
    "Rechteck": ("Rectangle", ""),
    "Polygon": ("Polygon", "Regular n-gon."),
    "Kurve teilen": ("Divide curve", "Points along a curve."),
    "Kurve versetzen": ("Offset curve", "Planar offset; negative = inwards."),
    "Text": ("Text", "Text outlines as curves."),
    "Extrudieren": ("Extrude", "Profile along Z, optionally capped to a solid."),
    "Loft": ("Loft", "Through a list of profiles."),
    "Drehkörper": ("Revolve", ""),
    "Box": ("Box", ""),
    "Zylinder": ("Cylinder", ""),
    "Kugel": ("Sphere", ""),
    "Boolean": ("Boolean", "Difference, union or intersection; b is a list."),
    "Schale": ("Shell", "Hollow out, optionally open at the top."),
    "Abrunden": ("Fillet", "Round all edges."),
    "Sweep": ("Sweep", "Profile along a path."),
    "Rohr": ("Pipe", "Tube around a curve."),
    "Verschieben": ("Move", ""),
    "Drehen": ("Rotate", "About X, Y or Z."),
    "Skalieren": ("Scale", ""),
    "Spiegeln": ("Mirror", ""),
    "Kreisförmig anordnen": ("Polar array", ""),
    "Zufall": ("Random numbers", "Seeded."),
    "Zufallspunkte": ("Random points", "In a rectangle, seeded."),
    "Voronoi": ("Voronoi", "Cells clipped to a rectangle (no SciPy needed)."),
    "Export": ("Export", "STL, 3MF or STEP — writes only while *write* is ticked."),
    "Fingerzinken": ("Finger joint edge", "Toothed edge between two points."),
    "Zinken-Box": ("Finger-jointed box", "Six (or five) panels, flat for the laser and assembled in 3D; exact joints."),
    "Living Hinge": ("Living hinge", "Bend pattern: cut length, bridge, spacing."),
    "Kerf-Ausgleich": ("Kerf compensation", "Outlines grow, holes shrink by half the kerf."),
    "Verschachteln": ("Nesting", "Pack parts onto sheets (shelf packing); one branch per sheet."),
    "SVG-Export (Laser)": ("Laser SVG export", "mm-exact SVG: red = cut, blue = engrave."),
    "Schlitze": ("Slots", "Cross slots for slotted (waffle) assemblies."),
    "Konturschnitt": ("Contour slices", "Sections along an axis, laid out flat."),
    "Waffel": ("Waffle", "Body → interlocking ribs with half-slots, laid out flat."),
    "Druck-Check": ("Print check", "Overhang %, thinnest wall, watertight; overhangs shown red."),
    "Auf Bett legen": ("Place on bed", "Largest flat face down, centred, z = 0."),
    "Toleranz-Paar": ("Clearance pair", "Pin and hole with clearance."),
    "Gitter-Füllung": ("Lattice infill", "Honeycomb or cubic lattice inside a skin."),
    "Gyroid": ("Gyroid", "Gyroid sheet in a box or cylinder (mesh)."),
    "Gewinde": ("Thread", "Metric-style bolt thread or hole tool with clearance."),
    "Prägen": ("Emboss", "Raised or engraved text on the top face."),
    "Mehrfarb-Teilen": ("Multi-colour split", "Cut a body at heights into parts (one per tool/colour)."),
    "Pyramide, vierseitig": ("Square pyramid", ""),
    "Pyramide, dreiseitig": ("Triangular pyramid", ""),
    "Bipyramide": ("Bipyramid", ""),
    "Antiprisma": ("Antiprism", "Uniform: all edges equal."),
    "Tetraeder": ("Tetrahedron", ""), "Hexaeder": ("Cube", ""),
    "Oktaeder": ("Octahedron", ""), "Dodekaeder": ("Dodecahedron", ""),
    "Ikosaeder": ("Icosahedron", ""),
    "Tetraederstumpf": ("Truncated tetrahedron", ""),
    "Würfelstumpf": ("Truncated cube", ""),
    "Oktaederstumpf": ("Truncated octahedron", ""),
    "Dodekaederstumpf": ("Truncated dodecahedron", ""),
    "Ikosaederstumpf": ("Truncated icosahedron", "The football."),
    "Kuboktaeder": ("Cuboctahedron", ""),
    "Ikosidodekaeder": ("Icosidodecahedron", ""),
    "Rhombenkuboktaeder": ("Rhombicuboctahedron", ""),
    "Großes Rhombenkuboktaeder": ("Truncated cuboctahedron", ""),
    "Rhombenikosidodekaeder": ("Rhombicosidodecahedron", ""),
    "Großes Rhombenikosidodekaeder": ("Truncated icosidodecahedron", ""),
    "Abgeschrägter Würfel": ("Snub cube", "One handedness."),
    "Abgeschrägtes Dodekaeder": ("Snub dodecahedron", "One handedness."),
}

KIND = {"num": "number", "int": "integer", "pt": "point", "geo": "geometry",
        "any": "anything", "text": "text"}


def main():
    QtWidgets.QApplication.instance() or QtWidgets.QApplication([])
    from solidnode import core
    panel_cls = core.make_core()
    classes = panel_cls.NODE_CLASSES
    out = ["# Node reference", "",
           "Generated from the code by `scripts/gen_node_docs.py` — "
           f"{len(classes)} nodes. Node and port names are German (as in the "
           "app); *list* means the input takes a whole branch at once.", ""]
    for ident, label, _color in panel_cls.CATEGORIES:
        group = [c for c in classes if c.__identifier__ == ident]
        if not group:
            continue
        out += [f"## {label}", "", "| Node | English | Inputs | Outputs | Notes |",
                "|---|---|---|---|---|"]
        for c in group:
            ins = []
            for name, kind, default, whole in c.INPUTS:
                s = f"`{name}` {KIND.get(kind, kind)}"
                if default is not None:
                    s += f" = {default}"
                if whole:
                    s += " *(list)*"
                ins.append(s)
            outs = ", ".join(f"`{o}`" for o in c.OUTPUTS) or "—"
            eng, doc = EN.get(c.NODE_NAME, ("", ""))
            out.append(f"| **{c.NODE_NAME}** | {eng} | {'<br>'.join(ins) or '—'} "
                       f"| {outs} | {doc} |")
        out.append("")
    path = Path(__file__).resolve().parents[1] / "docs" / "nodes.md"
    path.write_text("\n".join(out), encoding="utf-8")
    print(f"{path}: {len(classes)} nodes")


if __name__ == "__main__":
    main()
