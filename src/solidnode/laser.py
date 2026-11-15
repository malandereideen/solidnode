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
from .laser_geom import FORMEN, MUSTER
from .laser_bauten import BautenMixin
from .laser_extra import ExtraMixin
from .laser_haus import HausMixin
from .laser_wand import WandMixin

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
        ("form", "Form", "choice", "rechteck", FORMEN, None, None),
        ("breite", "Breite", "mm", 20.0, 2, 500, 1),
        ("hoehe", "Höhe", "mm", 30.0, 2, 500, 1),
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("y", "↓ ↑", "mm", 0.0, -2000, 2000, 1),
        ("rahmen", "Rahmen", "mm", 3.0, 0, 30, 0.5),
        ("sprosse", "Sprosse", "mm", 1.5, 0.5, 10, 0.5),
        ("sprossen_v", "Sprossen ↕", "int", 1, 0, 10, 1),
        ("sprossen_h", "Sprossen ↔", "int", 1, 0, 10, 1),
        ("oeffnung", "Öffnung", "bool", True, 0, 1, 1),
        ("sims", "Fensterbank", "bool", False, 0, 1, 1),
        ("lagen", "Lagen", "int", 1, 1, 5, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "tuer": {"label": "Tür", "fields": [
        ("form", "Form", "choice", "bogen", FORMEN[:3], None, None),
        ("breite", "Breite", "mm", 12.0, 2, 500, 1),
        ("hoehe", "Höhe", "mm", 22.0, 2, 500, 1),
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("rahmen", "Rahmen", "mm", 2.0, 0, 30, 0.5),
        ("blatt", "Türblatt", "bool", True, 0, 1, 1),
        ("bretter", "Bretter", "bool", True, 0, 1, 1),
        ("brett", "Brett", "mm", 2.5, 1, 20, 0.5),
        ("lagen", "Lagen", "int", 1, 1, 5, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "blende": {"label": "Blende", "fields": [
        ("form", "Form", "choice", "spitz", FORMEN, None, None),
        ("breite", "Breite", "mm", 8.0, 2, 500, 1),
        ("hoehe", "Höhe", "mm", 20.0, 2, 500, 1),
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("y", "↓ ↑", "mm", 0.0, -2000, 2000, 1),
        ("rand", "Rand", "mm", 2.0, 0.5, 30, 0.5),
        ("anzahl", "Anzahl", "int", 1, 1, 30, 1),
        ("abstand", "Abstand", "mm", 12.0, 2, 500, 1),
        ("lagen", "Lagen", "int", 1, 1, 5, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "muster": {"label": "Muster", "fields": [
        ("muster", "Muster", "choice", "backstein", MUSTER, None, None),
        ("bereich", "Bereich", "choice", "flaeche", ["flaeche", "feld"],
         None, None),
        ("breite", "Breite", "mm", 30.0, 2, 2000, 1),
        ("hoehe", "Höhe", "mm", 30.0, 2, 2000, 1),
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("y", "↓ ↑", "mm", 0.0, -2000, 2000, 1),
        ("form", "Feldform", "choice", "rechteck", FORMEN, None, None),
        ("stein_h", "Stein h", "mm", 0.0, 0, 50, 0.5),
        ("stein_l", "Stein l", "mm", 0.0, 0, 100, 0.5),
        ("rand", "Rand", "bool", True, 0, 1, 1),
        ("tiefe", "Tiefe", "mm", 0.2, 0.05, 2, 0.05)]},
    "uhr": {"label": "Uhr", "fields": [
        ("durchmesser", "Ø", "mm", 12.0, 3, 200, 1),
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("y", "↓ ↑", "mm", 0.0, -2000, 2000, 1),
        ("lagen", "Lagen", "int", 1, 1, 5, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "pfeiler": {"label": "Pfeiler", "fields": [
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("breite", "Breite", "mm", 6.0, 1, 100, 1),
        ("hoehe", "Höhe", "mm", 40.0, 5, 1000, 1),
        ("tiefe", "Tiefe", "mm", 8.0, 2, 200, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "band": {"label": "Band", "fields": [
        ("art", "Art", "choice", "gesims", ["gesims", "sockel", "trauf",
                                            "fries"], None, None),
        ("z", "Höhe ab", "mm", 30.0, 0, 2000, 1),
        ("hoehe", "Bandhöhe", "mm", 3.0, 0.5, 100, 0.5),
        ("bogen", "Bogenweite", "mm", 6.0, 3, 50, 0.5),
        ("rundum", "Rundum", "bool", True, 0, 1, 1),
        ("lagen", "Lagen", "int", 1, 1, 5, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "eckquader": {"label": "Eckquader", "fields": [
        ("hoehe", "Quaderhöhe", "mm", 5.0, 1, 50, 0.5),
        ("lang", "Lang", "mm", 10.0, 2, 100, 0.5),
        ("kurz", "Kurz", "mm", 6.0, 1, 100, 0.5),
        ("fuge", "Fuge", "mm", 1.2, 0.3, 10, 0.1),
        ("lagen", "Lagen", "int", 1, 1, 5, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "haus": {"label": "Haus", "fields": [
        ("dach", "Dach", "choice", "sattel", ["sattel", "pult", "walm",
                                              "flach"], None, None),
        ("breite", "Breite", "mm", 100, 10, 2000, 5),
        ("tiefe", "Tiefe", "mm", 70, 10, 2000, 5),
        ("hoehe", "Traufhöhe", "mm", 60, 10, 2000, 5),
        ("neigung", "Neigung", "deg", 45, 10, 75, 5),
        ("ueberstand", "Überstand", "mm", 5, 0, 50, 1),
        ("zinnen", "Zinnen", "bool", False, 0, 1, 1),
        ("zinnen_h", "Zinnenhöhe", "mm", 8, 2, 50, 1),
        ("zinnen_b", "Zinnenbreite", "mm", 8, 2, 50, 1),
        ("boden", "Boden", "bool", True, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "turm": {"label": "Turm", "fields": [
        ("dach", "Dach", "choice", "zelt", ["zelt", "zinnen", "flach"],
         None, None),
        ("ecken", "Ecken", "int", 8, 3, 24, 1),
        ("durchmesser", "Ø", "mm", 50, 10, 1000, 5),
        ("hoehe", "Höhe", "mm", 90, 10, 2000, 5),
        ("neigung", "Neigung", "deg", 60, 10, 80, 5),
        ("ueberstand", "Überstand", "mm", 3, 0, 50, 1),
        ("zinnen_h", "Zinnenhöhe", "mm", 8, 2, 50, 1),
        ("zinnen_b", "Zinnenbreite", "mm", 6, 2, 50, 1),
        ("boden", "Boden", "bool", True, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "kamin": {"label": "Schornstein", "fields": [
        ("x", "von links", "mm", 20, -2000, 2000, 1),
        ("y", "vor First", "mm", 10, -2000, 2000, 1),
        ("breite", "Breite", "mm", 10, 4, 200, 1),
        ("tiefe", "Tiefe", "mm", 10, 4, 200, 1),
        ("hoehe", "über First", "mm", 10, 0, 300, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "gaube": {"label": "Gaube", "fields": [
        ("x", "von links", "mm", 30, -2000, 2000, 1),
        ("breite", "Breite", "mm", 14, 6, 300, 1),
        ("hoehe", "Höhe", "mm", 10, 3, 200, 1),
        ("tiefe", "ab Traufe", "mm", 8, 0, 500, 1),
        ("neigung", "Neigung", "deg", 45, 15, 70, 5),
        ("fenster", "Fenster", "bool", True, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "vordach": {"label": "Vordach", "fields": [
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("z", "Höhe ab", "mm", 30.0, 3, 2000, 1),
        ("breite", "Breite", "mm", 40.0, 10, 1000, 1),
        ("tiefe", "Tiefe", "mm", 20.0, 5, 300, 1),
        ("neigung", "Neigung", "deg", 12, 0, 45, 1),
        ("stuetzen", "Stützen", "bool", True, 0, 1, 1),
        ("volant", "Volant", "bool", True, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "rundturm": {"label": "Rundturm", "fields": [
        ("dach", "Dach", "choice", "kegel", ["kegel", "zinnen", "flach"],
         None, None),
        ("durchmesser", "Ø", "mm", 44, 10, 1000, 2),
        ("hoehe", "Höhe", "mm", 80, 10, 2000, 5),
        ("neigung", "Neigung", "deg", 60, 20, 80, 5),
        ("ueberstand", "Überstand", "mm", 3, 0, 30, 1),
        ("zinnen_h", "Zinnenhöhe", "mm", 8, 2, 50, 1),
        ("zinnen_b", "Zinnenbreite", "mm", 6, 2, 50, 1),
        ("schnitt", "Schnitt", "mm", 15.0, 3, 100, 1),
        ("steg", "Steg", "mm", 3.0, 1, 20, 0.5),
        ("abstand", "Abstand", "mm", 1.5, 0.5, 10, 0.25),
        ("schlitz", "Schlitz", "mm", 0.5, 0.1, 3, 0.1),
        ("boden", "Boden", "bool", True, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "zwerch": {"label": "Zwerchgiebel", "fields": [
        ("x", "von links", "mm", 50, -2000, 2000, 1),
        ("breite", "Breite", "mm", 30, 8, 500, 1),
        ("kniestock", "Kniestock", "mm", 12, 3, 200, 1),
        ("neigung", "Neigung", "deg", 45, 15, 70, 5),
        ("fenster", "Fenster", "bool", True, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "dachreiter": {"label": "Dachreiter", "fields": [
        ("x", "von links", "mm", 50, -2000, 2000, 1),
        ("breite", "Breite", "mm", 14, 6, 200, 1),
        ("tiefe", "Tiefe", "mm", 14, 6, 200, 1),
        ("hoehe", "über First", "mm", 14, 3, 300, 1),
        ("neigung", "Neigung", "deg", 70, 20, 85, 5),
        ("ueberstand", "Überstand", "mm", 1.5, 0, 20, 0.5),
        ("kreuz", "Kreuz", "bool", True, 0, 1, 1),
        ("kreuz_h", "Kreuzhöhe", "mm", 8, 3, 60, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "ecktuerme": {"label": "Ecktürmchen", "fields": [
        ("auf", "Stehen", "choice", "krone", ["krone", "boden"], None, None),
        ("dach", "Dach", "choice", "zinnen", ["zinnen", "kegel", "flach"],
         None, None),
        ("durchmesser", "Ø", "mm", 14, 4, 200, 1),
        ("hoehe", "Höhe", "mm", 24, 3, 500, 3),
        ("zinnen_h", "Zinnenhöhe", "mm", 6, 3, 30, 3),
        ("neigung", "Neigung", "deg", 60, 20, 80, 5),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "podest": {"label": "Podest", "fields": [
        ("hoehe", "Höhe", "mm", 9, 3, 200, 3),
        ("rand", "Rand", "mm", 8, 0, 200, 1),
        ("treppe", "Treppe", "bool", True, 0, 1, 1),
        ("treppe_breite", "Treppe breit", "mm", 24, 6, 500, 1),
        ("stufe", "Auftritt", "mm", 4, 2, 30, 0.5),
        ("breite", "Breite (frei)", "mm", 80, 10, 2000, 5),
        ("tiefe", "Tiefe (frei)", "mm", 60, 10, 2000, 5),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5)]},
    "helm": {"label": "Turmhelm", "fields": [
        ("hoehe", "Höhe", "mm", 50, 5, 1000, 5),
        ("ueberstand", "Überstand", "mm", 2, 0, 30, 0.5),
        ("kreuz", "Kreuz", "bool", True, 0, 1, 1),
        ("kreuz_h", "Kreuzhöhe", "mm", 12, 3, 100, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "apsis": {"label": "Apsis", "fields": [
        ("x", "← →", "mm", 0.0, -2000, 2000, 1),
        ("breite", "Breite", "mm", 40, 10, 1000, 2),
        ("hoehe", "Höhe", "mm", 40, 5, 1000, 5),
        ("segmente", "Segmente", "int", 5, 3, 16, 1),
        ("neigung", "Neigung", "deg", 45, 15, 75, 5),
        ("ueberstand", "Überstand", "mm", 3, 0, 30, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5)]},
    "muehle": {"label": "Windmühle", "fields": [
        ("ecken", "Ecken", "int", 8, 5, 16, 1),
        ("durchmesser", "Ø", "mm", 50, 20, 500, 5),
        ("hoehe", "Höhe", "mm", 70, 20, 1000, 5),
        ("haube_h", "Haube", "mm", 18, 6, 200, 3),
        ("fluegel", "Flügel", "mm", 60, 15, 500, 5),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "leuchtturm": {"label": "Leuchtturm", "fields": [
        ("ecken", "Ecken", "int", 8, 5, 16, 1),
        ("durchmesser", "Ø", "mm", 40, 15, 500, 5),
        ("hoehe", "Höhe", "mm", 90, 20, 1000, 5),
        ("umgang", "Umgang", "mm", 6, 2, 50, 1),
        ("laterne_d", "Laterne Ø", "mm", 24, 8, 300, 2),
        ("laterne_h", "Laterne h", "mm", 14, 5, 200, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "steinbruecke": {"label": "Steinbrücke", "fields": [
        ("laenge", "Länge", "mm", 120, 30, 2000, 5),
        ("breite", "Breite", "mm", 36, 10, 500, 2),
        ("hoehe", "Höhe", "mm", 32, 10, 500, 2),
        ("boegen", "Bögen", "int", 2, 1, 12, 1),
        ("bruestung", "Brüstung", "mm", 6, 0, 50, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "fachwerkbruecke": {"label": "Fachwerkbrücke", "fields": [
        ("laenge", "Spannweite", "mm", 120, 30, 2000, 5),
        ("breite", "Breite", "mm", 36, 10, 500, 2),
        ("hoehe", "Trägerhöhe", "mm", 26, 8, 300, 1),
        ("felder", "Felder", "int", 6, 2, 30, 1),
        ("stab", "Stab", "mm", 3, 1.5, 20, 0.5),
        ("auflage", "Auflager", "mm", 6, 3, 100, 3),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
    "pagode": {"label": "Pagode", "fields": [
        ("stockwerke", "Geschosse", "int", 3, 1, 9, 1),
        ("breite", "Breite", "mm", 60, 20, 1000, 5),
        ("tiefe", "Tiefe", "mm", 60, 20, 1000, 5),
        ("geschoss", "Geschoss h", "mm", 26, 10, 300, 1),
        ("schrumpf", "Verjüngung", "float", 0.75, 0.4, 0.95, 0.05),
        ("neigung", "Neigung", "deg", 30, 15, 60, 5),
        ("ueberstand", "Überstand", "mm", 8, 0, 50, 1),
        ("spitze", "Spitze", "bool", True, 0, 1, 1),
        ("staerke", "Stärke", "mm", 3.0, 0.5, 20, 0.5),
        ("x", "X", "mm", 0, -5000, 5000, 5),
        ("y", "Y", "mm", 0, -5000, 5000, 5),
        ("z", "Z", "mm", 0, -5000, 5000, 5)]},
}


WAND_TYPES = ("fenster", "tuer", "blende", "muster", "uhr", "pfeiler",
              "band", "eckquader", "vordach", "apsis")


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


def best_normal(shape, staerke, fallback):
    """Plattennormale: die Flächennormale, entlang der der Körper eine
    ganze Zahl Lagen dick ist (bei Gleichstand die dünnste Richtung)."""
    v = _vertices(shape)
    best, key = np.asarray(fallback, float), None
    seen = []
    for _f_, n, _a, _c in _planar_faces(shape):
        if any(abs(np.dot(n, m)) > 0.999 for m in seen):
            continue
        seen.append(n)
        d = v @ n
        t = d.max() - d.min()
        lagen = t / staerke
        k = (round(abs(lagen - round(lagen)), 2) if round(lagen) >= 1 else 9,
             t)
        if key is None or k < key:
            best, key = n, k
    return best


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

class Laser(WandMixin, HausMixin, ExtraMixin, BautenMixin):
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

    # -- Elemente: Liste im Design, Neubau an derselben Timeline-Stelle

    def leer(self):
        """True, wenn das offene Design noch nichts enthält."""
        d = self.design()
        return not d.get("timeline") and not d.get("bodies")

    def speichern(self, ordner, name):
        """Kopie als `<ordner>/<name>.sc`; vorhandene Dateien bleiben
        unangetastet (dann „name (2).sc“ usw.). Gibt den Pfad zurück."""
        os.makedirs(ordner, exist_ok=True)
        name = "".join(ch if ch not in '/\\:*?"<>|' else "-" for ch in name)
        pfad, i = os.path.join(ordner, name + ".sc"), 2
        while os.path.exists(pfad):
            pfad, i = os.path.join(ordner, f"{name} ({i}).sc"), i + 1
        self.c.tool("save", {"path": pfad})
        return pfad

    def neues_design(self, name):
        self.c.tool("new_design", {"name": name})

    def _meta(self):
        meta = json.loads(self.c.execute("document.metadata", {}))
        return dict(meta.get("metadata", {}).get(META) or {})

    def elements(self):
        return self._meta().get("elements", [])

    def _save(self, els=None, **extra):
        m = self._meta()
        if els is not None:
            m["elements"] = els
        m.update(extra)
        self.c.execute("document.metadata.set", {"key": META, "value": m})

    # -- Gravur: Standard nur Skizzenlinien, Rillen per Schalter

    def gravur_sichtbar(self):
        return bool(self._meta().get("gravur", False))

    def set_gravur(self, an):
        """Schalter: Elemente mit Gravur einmal neu bauen — mit Rillen
        (Extrusion) oder nur mit den Skizzenlinien."""
        self._save(gravur=bool(an))
        els = self.elements()
        n = 0
        for el in els:
            if getattr(self, "engr_" + el["typ"], None) and \
                    self.engr_has(el):
                self._rebuild(el)
                n += 1
        self._save(els)
        return (f"Gravur als Rillen: {n} Muster eingeschaltet" if an else
                f"Gravur nur als Skizze: {n} Muster ausgeschaltet")

    def _timeline(self):
        return self.design()["timeline"]

    def _new_name(self, typ, els):
        label = SCHEMA[typ]["label"]
        nums = [int(e["name"].rsplit(" ", 1)[1]) for e in els
                if e["typ"] == typ and e["name"].rsplit(" ", 1)[-1].isdigit()]
        return f"{label} {max(nums, default=0) + 1}"

    def engr_has(self, el):
        try:
            return any(ln for *_x, ln in getattr(self, "engr_" + el["typ"])(el))
        except Exception:                     # noqa: BLE001
            return False

    def _build(self, el):
        """Befehle laufen an der Timeline-Marke; neue Features → Ordner."""
        self._rillen = self.gravur_sichtbar()
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

    def _ctx_for(self, typ):
        if typ in WAND_TYPES:
            return self.ctx_wand()
        return getattr(self, "ctx_" + typ)()

    def create(self, typ, params, ctx=None):
        els = self.elements()
        p = defaults(typ)
        p.update(params or {})
        if ctx is None:
            ctx = self._ctx_for(typ)
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
            el["ctx"] = self._ctx_for(el["typ"])
        self._rebuild(el)
        self._save(els)                 # Abhängige lesen die neuen Werte
        extra = []
        if el["typ"] in ("kasten", "haus", "turm", "rundturm"):  # mitziehen
            for z in els:
                folgt = (
                    (z["typ"] == "zinken"
                     and set(z["ctx"]["bodies"]) & set(el["bodies"]))
                    or (z["typ"] in ("band", "eckquader")
                        and z["ctx"].get("kasten") == el["id"]
                        and (z["typ"] == "eckquader"
                             or z["params"].get("rundum")))
                    or (z["typ"] in ("kamin", "gaube", "zwerch")
                        and z["ctx"].get("haus") == el["id"])
                    or z["ctx"].get("host") == el["id"]
                    or (z["typ"] == "muster"
                        and z["ctx"].get("kasten") == el["id"]
                        and z["params"].get("bereich") == "flaeche"))
                if folgt:
                    self._rebuild(z)
                    self._save(els)
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

    def _engravings(self):
        """Körpername → [(ctx, linien in ctx-Koordinaten)] aller Gravuren."""
        out = {}
        for el in self.elements():
            fn = getattr(self, "engr_" + el["typ"], None)
            if fn is None:
                continue
            try:
                for body, ctx, _off, lines in fn(el):
                    out.setdefault(body, []).append((ctx, lines))
            except Exception:                 # noqa: BLE001
                continue
        return out

    def export(self, ordner=None, platte=(400.0, 300.0), abstand=3.0,
               formate=("svg", "dxf")):
        """Alle sichtbaren Platten flach und verschachtelt.
        Rot = schneiden (Umriss + Durchbrüche aus dem Schnitt durch die
        Plattenmitte), blau = gravieren (Musterlinien der Elemente)."""
        from shapely.affinity import translate
        from shapely.geometry import LineString

        from .laser_wand import plate_section
        ordner = ordner or os.path.expanduser(
            "~/Downloads/Laser-Export/" + time.strftime("%Y-%m-%d_%H%M%S"))
        os.makedirs(ordner, exist_ok=True)
        engr = self._engravings()
        teile, warn, flach = [], [], set()
        for el in self.elements():               # gebogene Teile abwickeln
            fn = getattr(self, "flat_" + el["typ"], None)
            if fn is None:
                continue
            for nm, g, lines in fn(el):
                if g.is_empty:
                    continue
                x0, y0, _x1, _y1 = g.bounds
                teile.append((nm, translate(g, -x0, -y0),
                              [[(x - x0, y - y0) for x, y in ln]
                               for ln in lines]))
                flach.add(nm)
        for name in self.body_names():
            if name in flach:
                continue
            s = self.shape(name)
            info = plate_info(s)
            if info is None:
                warn.append(f"{name}: keine Platte")
                continue
            n = best_normal(s, self.staerke, info["normal"])
            if name in engr:                      # Gravurseite nach oben
                n = np.array(engr[name][0][0]["n"], float)
            d = _vertices(s) @ n
            t = float(d.max() - d.min())
            right, up = _frame_up(n)
            o = n * d.max()
            st = self.staerke
            k = int(round(t / st))
            if k >= 2 and abs(t - k * st) < 0.05 and k <= 60:
                # mehrere Lagen: jede Lage auf ihrer Höhe schneiden
                # (Scheibenbau: Stufenkegel, Kuppeln, Podeste, Doppelrahmen)
                lagen = [(f"{name} Lage {i + 1}",
                          plate_section(s, n * (d.min() + (i + 0.5) * st), n,
                                        o, right, up)) for i in range(k)]
                summe = sum(g.area for _nm, g in lagen) * st
            else:
                lagen = [(name, plate_section(s, n * (d.min() + d.max()) / 2,
                                              n, o, right, up))]
                summe = lagen[0][1].area * t
                if abs(t - st) > 0.05:
                    warn.append(f"{name}: {t:.2f} mm statt {st:g}")
            if all(g.is_empty for _nm, g in lagen) or \
                    abs(summe - _volume(s)) > 0.15 * _volume(s):
                warn.append(f"{name}: keine ebene Platte")
                continue
            for li, (nm, geom) in enumerate(lagen):
                if geom.is_empty or geom.area < 0.5:
                    continue
                lines = []
                if li == len(lagen) - 1:          # Gravur auf die oberste
                    inner = geom.buffer(-0.15)
                    for ctx, ls in engr.get(name, []):
                        P, R, U = (np.array(ctx[q], float)
                                   for q in ("p", "right", "up"))
                        for ln in ls:
                            w = [P + R * x + U * y - o for x, y in ln]
                            loc = [(float(q @ right), float(q @ up))
                                   for q in w]
                            if len(loc) >= 2:
                                from .laser_geom import lines_of
                                lines += lines_of(
                                    LineString(loc).intersection(inner))
                x0, y0, _x1, _y1 = geom.bounds
                geom = translate(geom, -x0, -y0)
                lines = [[(x - x0, y - y0) for x, y in ln] for ln in lines]
                teile.append((nm, geom, lines))
        sheets = nest(teile, platte, abstand)
        files = []
        for k, sheet in enumerate(sheets):
            base = os.path.join(ordner, f"Platte {k + 1}")
            if "svg" in formate:
                write_svg(base + ".svg", platte, sheet)
                files.append(base + ".svg")
            if "dxf" in formate:
                write_dxf(base + ".dxf", sheet)
                files.append(base + ".dxf")
        n_g = sum(len(ln) for _n, _g, ln in teile)
        msg = (f"{len(teile)} Teile auf {len(sheets)} Platte(n), "
               f"{n_g} Gravurlinien → {ordner}")
        if warn:
            msg += " · ⚠ " + "; ".join(warn)
        return msg, files

    def export_svg(self, ordner=None, platte=(400.0, 300.0), abstand=3.0):
        return self.export(ordner, platte, abstand)


# ------------------------------------------------------------ Abwicklung

def nest(teile, platte, gap):
    """Regal-Packen nach Höhe → je Platte [(name, geom, linien), …]
    (schon verschoben, ggf. um 90° gedreht)."""
    from shapely.affinity import rotate, translate
    W, H = platte
    items = []
    for name, g, lines in teile:
        x0, y0, x1, y1 = g.bounds
        w, h = x1 - x0, y1 - y0
        if (w > h and w > W - 2 * gap) or h > H - 2 * gap:
            g = rotate(g, 90, origin=(0, 0))
            lines = [[(-y, x) for x, y in ln] for ln in lines]
            x0, y0, x1, y1 = g.bounds
            g = translate(g, -x0, -y0)
            lines = [[(x - x0, y - y0) for x, y in ln] for ln in lines]
            w, h = x1 - x0, y1 - y0
        items.append((name, g, lines, w, h))
    items.sort(key=lambda it: -it[4])
    sheets, cur, x, y, row = [], [], gap, gap, 0.0
    for name, g, lines, w, h in items:
        if x + w > W - gap:
            x, y, row = gap, y + row + gap, 0.0
        if y + h > H - gap and cur:
            sheets.append(cur)
            cur, x, y, row = [], gap, gap, 0.0
        cur.append((name, translate(g, x, y),
                    [[(px + x, py + y) for px, py in ln] for ln in lines]))
        x += w + gap
        row = max(row, h)
    if cur:
        sheets.append(cur)
    return sheets


def _loops(g):
    from .laser_geom import polys_of
    for outer, holes in polys_of(g):
        yield outer
        yield from holes


def write_svg(path, platte, placed):
    W, H = platte
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{W}mm" '
           f'height="{H}mm" viewBox="0 0 {W} {H}">',
           '<g id="schneiden" fill="none" stroke="#FF0000" '
           'stroke-width="0.1">']
    for name, g, _l in placed:
        for loop in _loops(g):
            d = " ".join(f"{'M' if k == 0 else 'L'}{x:.3f},{H - y:.3f}"
                         for k, (x, y) in enumerate(loop))
            out.append(f'<path d="{d} Z"/>')
    out.append('</g><g id="gravieren" fill="none" stroke="#0000FF" '
               'stroke-width="0.1">')
    for name, _g, lines in placed:
        for ln in lines:
            d = " ".join(f"{'M' if k == 0 else 'L'}{x:.3f},{H - y:.3f}"
                         for k, (x, y) in enumerate(ln))
            out.append(f'<path d="{d}"/>')
    out.append('</g><g id="info" fill="#999999" font-size="2.5">')
    for name, g, _l in placed:
        p = g.representative_point()
        out.append(f'<text x="{p.x:.2f}" y="{H - p.y:.2f}" '
                   f'text-anchor="middle">{name}</text>')
    out.append("</g></svg>")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(out))


def write_dxf(path, placed):
    import ezdxf
    doc = ezdxf.new("R2010", setup=True)
    doc.units = ezdxf.units.MM
    for nm, col in (("SCHNITT", 1), ("GRAVUR", 5), ("INFO", 8)):
        doc.layers.add(nm, color=col)
    msp = doc.modelspace()
    for name, g, lines in placed:
        for loop in _loops(g):
            msp.add_lwpolyline(loop, close=True,
                               dxfattribs={"layer": "SCHNITT"})
        for ln in lines:
            msp.add_lwpolyline(ln, dxfattribs={"layer": "GRAVUR"})
        p = g.representative_point()
        msp.add_text(name, height=2.5, dxfattribs={
            "layer": "INFO", "insert": (p.x, p.y)})
    doc.saveas(path)
