"""Laser-Palette: Fenster neben SolidCraft (`solidnode laser`).

Reiter:
- Bauen: Baukasten wie im bausatzmaker — Kacheln mit Symbol, nach Gruppen
  sortiert; darunter Hinweis, Werte und „Anlegen“.
- Elemente: alles, was die Palette im offenen Design gebaut hat; anklicken
  = in SolidCraft markieren, Werte ändern + Übernehmen = an derselben
  Timeline-Stelle neu bauen (Liste in den Metadaten der .sc-Datei).
- LoD2: Adresse → amtliches Gebäudemodell → Grundmaße im Maßstab, als
  Häuser anlegen oder in die Werte übernehmen.
- Export: SVG + DXF für den Laser.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import QByteArray, QPointF, QSize, Qt, QThread, Signal
from PySide6.QtGui import QColor, QIcon, QPainter, QPainterPath, QPen, \
    QPixmap, QPolygonF
from PySide6.QtSvg import QSvgRenderer
from PySide6.QtWidgets import (QApplication, QButtonGroup, QCheckBox,
                               QComboBox, QDoubleSpinBox, QFormLayout,
                               QFrame, QGridLayout, QGroupBox, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QScrollArea,
                               QSizePolicy, QSpinBox, QSplitter, QTabWidget,
                               QToolButton, QTreeWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from . import hosts
from .laser import SCHEMA, WAND_TYPES, Laser, defaults
from .laser_icons import ICONS

_WAND = "Wandfläche anklicken"
# Baukasten: Gruppe → [(Name, Symbol, Typ, Voreinstellung, Hinweis)]
KATALOG = [
    ("Baukörper", [
        ("Kasten", "kasten", "kasten", {}, "Wird bei X/Y/Z angelegt; danach "
         "„Zinken“."),
        ("Haus", "haus", "haus", {"dach": "sattel"}, "Satteldach. Wird bei "
         "X/Y/Z angelegt; danach „Zinken“."),
        ("Walmhaus", "walmhaus", "haus", {"dach": "walm", "neigung": 40},
         "Walmdach (Breite ≥ Tiefe)."),
        ("Anbau", "anbau", "haus", {"dach": "pult", "neigung": 25,
                                    "breite": 40}, "Pultdach."),
        ("Burghaus", "krone", "haus", {"dach": "flach", "zinnen": True},
         "Flachdach mit Zinnen."),
        ("Turm", "turm", "turm", {"dach": "zinnen"}, "Vieleckturm mit "
         "Zinnen."),
        ("Zeltdachturm", "rund_vieleck", "turm", {"dach": "zelt"},
         "Vieleckturm mit Zeltdach."),
        ("Rundturm", "rund_biegen", "rundturm", {"dach": "zinnen"},
         "Gebogener Mantel; im Export als Streifen mit Living Hinge."),
        ("Kegelturm", "rund_kegel", "rundturm", {"dach": "kegel"},
         "Gebogener Mantel mit Kegeldach (beides abgewickelt)."),
        ("Ecktürmchen", "ecktuerme", "ecktuerme", {}, "Kasten/Haus "
         "anklicken; „krone“ = auf der Mauerkrone, „boden“ = außen."),
        ("Podest", "podest", "podest", {}, "Kasten/Haus anklicken; liegt "
         "unter dem Gebäude, Treppe vorn."),
        ("Apsis", "apsis", "apsis", {}, _WAND + " (Mitte der Apsis)."),
        ("Pagode", "pagode", "pagode", {}, "Wird bei X/Y/Z angelegt."),
        ("Windmühle", "muehle", "muehle", {}, "Wird bei X/Y/Z angelegt."),
        ("Leuchtturm", "leuchtturm", "leuchtturm", {}, "Wird bei X/Y/Z "
         "angelegt."),
        ("Steinbrücke", "bruecke", "steinbruecke", {}, "Wird bei X/Y/Z "
         "angelegt; Gewölbe abgewickelt."),
        ("Fachwerk­brücke", "fachwerkbruecke", "fachwerkbruecke", {},
         "Wird bei X/Y/Z angelegt."),
    ]),
    ("Dach", [
        ("Gaube", "gaube", "gaube", {}, "Dachfläche anklicken (vorn/hinten); "
         "„von links“ = Mitte."),
        ("Zwerch­giebel", "zwerch", "zwerch", {}, "Dachfläche anklicken; "
         "steht in der Fassade."),
        ("Dachreiter", "dachreiter", "dachreiter", {}, "Haus mit "
         "Satteldach anklicken."),
        ("Turmhelm", "helm", "helm", {}, "Turm anklicken (dort Dach „flach“ "
         "oder „zinnen“)."),
        ("Schorn­stein", "kamin", "kamin", {}, "Haus anklicken."),
        ("Vordach", "vordach", "vordach", {}, _WAND + " (Mitte); „Höhe ab“ "
         "= Anschluss über der Wandunterkante."),
    ]),
    ("Öffnungen", [
        ("Rundbogen", "fenster_bogen", "fenster", {"form": "bogen",
                                                   "breite": 9, "hoehe": 18},
         _WAND + " (Fenstermitte)."),
        ("Eckig", "fenster_eckig", "fenster", {"form": "rechteck",
                                               "breite": 9, "hoehe": 14},
         _WAND + " (Fenstermitte)."),
        ("Spitzbogen", "fenster_spitz", "fenster", {"form": "spitz",
                                                    "breite": 9, "hoehe": 20},
         _WAND + " (Fenstermitte)."),
        ("Rund", "fenster_rund", "fenster", {"form": "rund", "breite": 10,
                                             "sprossen_v": 1,
                                             "sprossen_h": 1},
         _WAND + " (Fenstermitte)."),
        ("Schlitz", "schlitz", "fenster", {"form": "rechteck", "breite": 2,
                                           "hoehe": 7, "rahmen": 0,
                                           "sprossen_v": 0, "sprossen_h": 0},
         _WAND + " (Mitte)."),
        ("Tür", "tuer", "tuer", {}, _WAND + " (Türmitte; sitzt unten auf "
         "der Wandkante bzw. dem Boden)."),
        ("Tor", "tor", "tuer", {"blatt": False, "breite": 26, "hoehe": 30,
                                "rahmen": 3}, _WAND + " (Tormitte)."),
    ]),
    ("Blenden & Nischen", [
        ("Spitz­blende", "blende_spitz", "blende", {"form": "spitz",
                                                   "breite": 14, "hoehe": 26},
         _WAND + " (Mitte)."),
        ("Putz­blende", "putzblende", "blende", {"form": "bogen", "breite": 6,
                                                "hoehe": 34}, _WAND + "."),
        ("Dreieck", "dreieck", "blende", {"form": "spitz", "breite": 6,
                                          "hoehe": 5}, _WAND + "."),
        ("Nischen­reihe", "nischen", "blende", {"anzahl": 5, "breite": 5,
                                               "hoehe": 11, "abstand": 9},
         _WAND + " (Mitte der Reihe)."),
    ]),
    ("Muster (Gravur)", [
        (n.capitalize() if n != "fischgrat" else "Fischgrät", "m_" + n,
         "muster", {"muster": n}, _WAND + ". Bereich „feld“ = Feld um den "
         "Klickpunkt, sonst die ganze Fläche.")
        for n in ("backstein", "feldstein", "quader", "fischgrat",
                  "fachwerk", "bretter", "streifen")
    ]),
    ("Bänder & Schmuck", [
        ("Gesims", "gesims", "band", {"art": "gesims"}, _WAND + "; rundum = "
         "alle vier Wände."),
        ("Sockel", "sockel", "band", {"art": "sockel", "hoehe": 4},
         _WAND + "."),
        ("Trauf­gesims", "trauf", "band", {"art": "trauf"}, _WAND + "."),
        ("Bogenfries", "fries", "band", {"art": "fries", "hoehe": 6},
         _WAND + "."),
        ("Eckquader", "quader", "eckquader", {}, "Eine Wand des "
         "Kastens/Hauses anklicken."),
        ("Strebe­pfeiler", "pfeiler", "pfeiler", {}, _WAND + " (Mitte)."),
        ("Uhr", "uhr", "uhr", {}, _WAND + " (Uhrmitte)."),
    ]),
    ("Platten", [
        ("Zinken", "zinken", "zinken", {}, "Platten auswählen — oder "
         "nichts, dann alle Stöße."),
        ("Living Hinge", "hinge", "hinge", {}, "Biegelinie (oder Rechteck) "
         "auf die Platte skizzieren und auswählen."),
    ]),
]
_VERSTECKT = {"x", "y"}        # Lage kommt beim Anlegen vom Klick


def svg_icon(svg, color, size=32):
    """SVG mit currentColor → QIcon (2× für Retina)."""
    data = svg.replace("currentColor", color)
    r = QSvgRenderer(QByteArray(data.encode()))
    pm = QPixmap(size * 2, size * 2)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    r.render(p)
    p.end()
    pm.setDevicePixelRatio(2)
    return QIcon(pm)


def _field(kind, value, lo, hi, step):
    if kind == "choice":
        w = QComboBox()
        w.addItems(list(lo))
        w.setCurrentText(str(value))
        return w
    if kind == "bool":
        w = QCheckBox()
        w.setChecked(bool(value))
        return w
    if kind == "float":
        w = QDoubleSpinBox()
        w.setRange(lo, hi)
        w.setDecimals(2)
        w.setSingleStep(step)
        w.setValue(float(value))
        w.setKeyboardTracking(False)
        return w
    if kind == "int":
        w = QSpinBox()
        w.setRange(int(lo), int(hi))
        w.setValue(int(value))
        return w
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(2 if step < 0.5 else 1)
    w.setSingleStep(step)
    w.setValue(float(value))
    w.setSuffix("°" if kind == "deg" else " mm")
    w.setKeyboardTracking(False)
    return w


def _value(w):
    if isinstance(w, QCheckBox):
        return w.isChecked()
    if isinstance(w, QComboBox):
        return w.currentText()
    return w.value()


class Form:
    """Formular aus SCHEMA[typ]; `keys` begrenzt die gezeigten Felder."""

    def __init__(self, typ, values=None, keys=None, cols=2):
        self.typ = typ
        self.widgets = {}
        self.box = QWidget()
        f = QFormLayout(self.box)
        f.setContentsMargins(0, 0, 0, 0)
        f.setSpacing(3)
        vals = defaults(typ)
        vals.update(values or {})
        row, n = None, 0
        for key, label, kind, _d, lo, hi, step in SCHEMA[typ]["fields"]:
            if keys and key not in keys:
                continue
            w = _field(kind, vals.get(key, _d), lo, hi, step)
            self.widgets[key] = w
            if kind == "bool":
                w.setText(label)
            if n % cols == 0:
                row = QHBoxLayout()
                row.setSpacing(4)
                f.addRow(row)
            if kind != "bool":
                lab = QLabel(label)
                lab.setStyleSheet("color: #999;")
                lab.setMinimumWidth(62)
                row.addWidget(lab)
            row.addWidget(w, 1)
            n += 1

    def values(self):
        return {k: _value(w) for k, w in self.widgets.items()}


# ------------------------------------------------------------- LoD2

class Lod2Worker(QThread):
    """Adresse suchen und Gebäude holen (erste Kachel kann Minuten dauern)."""
    fertig = Signal(object)

    def __init__(self, adresse, radius):
        super().__init__()
        self.adresse, self.radius = adresse, radius

    def run(self):
        from . import laser_lod2 as L2
        try:
            place = L2.geocode(self.adresse)
            d = L2.buildings(place, self.radius)
            d["place"] = place
            self.fertig.emit(d)
        except Exception as exc:              # noqa: BLE001
            self.fertig.emit({"error": f"{type(exc).__name__}: {exc}"})


class Lageplan(QWidget):
    """Grundrisse von oben; Klick wählt ein Gebäude."""
    gewaehlt = Signal(int)

    def __init__(self):
        super().__init__()
        self.setMinimumHeight(170)
        self.blds, self.sel = [], -1
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Expanding)

    def setze(self, blds):
        self.blds, self.sel = blds, -1
        self.update()

    def _rings(self, b):
        out = []
        for p in b["parts"]:
            for g in (p["ground"] or p["roofs"]):
                out.append([(q[0], q[1]) for q in g])
        return out

    def _xf(self):
        pts = [q for b in self.blds for g in self._rings(b) for q in g] or \
            [(-1, -1), (1, 1)]
        x0, x1 = min(q[0] for q in pts), max(q[0] for q in pts)
        y0, y1 = min(q[1] for q in pts), max(q[1] for q in pts)
        w, h = self.width() - 10, self.height() - 10
        k = min(w / max(x1 - x0, 1), h / max(y1 - y0, 1))
        ox = 5 + (w - (x1 - x0) * k) / 2
        oy = 5 + (h - (y1 - y0) * k) / 2
        return lambda q: QPointF(ox + (q[0] - x0) * k,
                                 oy + (y1 - q[1]) * k)

    def paintEvent(self, _ev):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        pal = self.palette()
        p.fillRect(self.rect(), pal.base())
        if not self.blds:
            p.setPen(QColor("#888"))
            p.drawText(self.rect(), Qt.AlignCenter, "Adresse suchen …")
            return
        f = self._xf()
        for i, b in enumerate(self.blds):
            sel = i == self.sel
            p.setPen(QPen(QColor("#e07a2f" if sel else "#888"),
                          2 if sel else 1))
            p.setBrush(QColor(224, 122, 47, 90) if sel else
                       QColor(128, 128, 128, 40))
            for g in self._rings(b):
                p.drawPolygon(QPolygonF([f(q) for q in g]))
        c = f((0, 0))
        p.setPen(QPen(QColor("#d33"), 1.5))
        p.drawLine(c + QPointF(-5, 0), c + QPointF(5, 0))
        p.drawLine(c + QPointF(0, -5), c + QPointF(0, 5))

    def mousePressEvent(self, ev):
        if not self.blds:
            return
        f = self._xf()
        pt = ev.position()
        for i, b in enumerate(self.blds):
            for g in self._rings(b):
                path = QPainterPath()
                path.addPolygon(QPolygonF([f(q) for q in g]))
                if path.contains(pt):
                    self.sel = i
                    self.update()
                    self.gewaehlt.emit(i)
                    return


# ----------------------------------------------------------- Palette

class Palette(QWidget):
    def __init__(self, headless=False):
        super().__init__()
        self.setWindowTitle("Laser")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.headless = headless
        self.client = None
        self.files = []
        self.els = []
        self.edit_form = None
        self.neu_form = None
        self.auswahl = None
        self.lod2 = None
        self.worker = None
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        g = QHBoxLayout()
        self.staerke = _field("mm", 3.0, 0.5, 20, 0.5)
        self.finger = _field("mm", 10.0, 3, 60, 1)
        for lab, w in (("Stärke", self.staerke), ("Zinke", self.finger)):
            g.addWidget(QLabel(lab))
            g.addWidget(w, 1)
        self.rillen = QCheckBox("Rillen")
        self.rillen.setToolTip("Aus: Muster nur als Skizzenlinien — schnell, "
                               "der Export ist gleich.\nAn: echte 0,2-mm-"
                               "Rillen für Ansicht/Render (langsamer).")
        self.rillen.toggled.connect(self.do_rillen)
        g.addWidget(self.rillen)
        root.addLayout(g)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs, 1)
        self.tabs.addTab(self._tab_bauen(), "Bauen")
        self.tabs.addTab(self._tab_elemente(), "Elemente")
        self.tabs.addTab(self._tab_lod2(), "LoD2")
        self.tabs.addTab(self._tab_export(), "Export")
        self.tabs.currentChanged.connect(
            lambda i: self.refresh() if i == 1 else None)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #888;")
        root.addWidget(self.status)
        if not headless and not hosts.port_open(hosts.SOLIDCRAFT_PORT):
            root.addWidget(self._btn("SolidCraft starten", self.start_sc))
            self.say("SolidCraft läuft nicht mit Steuerport "
                     f"{hosts.SOLIDCRAFT_PORT}.")

    # -- Aufbau

    def _btn(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        return b

    def _farbe(self):
        return self.palette().color(self.foregroundRole()).name()

    def _tab_bauen(self):
        split = QSplitter(Qt.Vertical)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QFrame.NoFrame)
        inner = QWidget()
        lay = QVBoxLayout(inner)
        lay.setContentsMargins(2, 2, 2, 2)
        lay.setSpacing(2)
        self.kacheln = QButtonGroup(self)
        self.kacheln.setExclusive(True)
        self.kachel_daten = {}
        farbe = self._farbe()
        spalten = 5
        for gruppe, items in KATALOG:
            head = QLabel(gruppe.upper())
            head.setStyleSheet("color: #999; font-size: 10px; "
                               "font-weight: 600; margin-top: 6px;")
            lay.addWidget(head)
            grid = QGridLayout()
            grid.setSpacing(3)
            for i, it in enumerate(items):
                name, icon, typ, _p, hint = it
                b = QToolButton()
                b.setText(name.replace("\u00ad", "-\n"))
                b.setIcon(svg_icon(ICONS.get(icon, ICONS["kasten"]), farbe))
                b.setIconSize(QSize(30, 30))
                b.setToolButtonStyle(Qt.ToolButtonTextUnderIcon)
                b.setCheckable(True)
                b.setAutoRaise(True)
                b.setFixedSize(QSize(74, 70))
                b.setToolTip(f"{name.replace(chr(173), '')}: {hint}")
                b.setStyleSheet("QToolButton { font-size: 10px; "
                                "border-radius: 6px; } "
                                "QToolButton:checked { background: "
                                "rgba(224,122,47,0.25); }")
                self.kacheln.addButton(b)
                self.kachel_daten[b] = it
                grid.addWidget(b, i // spalten, i % spalten)
            lay.addLayout(grid)
        lay.addStretch(1)
        scroll.setWidget(inner)
        split.addWidget(scroll)

        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(2, 4, 2, 2)
        pl.setSpacing(4)
        kopf = QHBoxLayout()
        self.sel_icon = QLabel()
        self.sel_icon.setFixedSize(32, 32)
        self.sel_name = QLabel("Element wählen")
        self.sel_name.setStyleSheet("font-weight: 600; font-size: 13px;")
        kopf.addWidget(self.sel_icon)
        kopf.addWidget(self.sel_name, 1)
        pl.addLayout(kopf)
        self.hint = QLabel("Oben eine Kachel anklicken.")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #999;")
        pl.addWidget(self.hint)
        self.neu_box = QWidget()
        self.neu_lay = QVBoxLayout(self.neu_box)
        self.neu_lay.setContentsMargins(0, 0, 0, 0)
        pl.addWidget(self.neu_box)
        pl.addStretch(1)
        self.b_neu = self._btn("Anlegen", self.do_neu)
        self.b_neu.setEnabled(False)
        self.b_neu.setDefault(True)
        pl.addWidget(self.b_neu)
        split.addWidget(panel)
        split.setSizes([360, 260])
        self.kacheln.buttonClicked.connect(self.show_neu)
        return split

    def show_neu(self, b):
        while self.neu_lay.count():
            it = self.neu_lay.takeAt(0).widget()
            if it:
                it.setParent(None)
                it.deleteLater()
        name, icon, typ, preset, hint = self.kachel_daten[b]
        self.auswahl = self.kachel_daten[b]
        vals = dict(preset)
        vals.setdefault("staerke", self.staerke.value())
        if typ == "zinken":
            vals.setdefault("zinke", self.finger.value())
        keys = [f[0] for f in SCHEMA[typ]["fields"]
                if not (f[0] in _VERSTECKT and typ in WAND_TYPES)
                and f[0] != "staerke"]
        self.neu_form = Form(typ, vals, keys=keys)
        self.neu_lay.addWidget(self.neu_form.box)
        self.sel_name.setText(name.replace("­", ""))
        self.sel_icon.setPixmap(svg_icon(ICONS.get(icon, ICONS["kasten"]),
                                         self._farbe()).pixmap(32, 32))
        self.hint.setText(hint)
        self.b_neu.setEnabled(True)

    def _tab_elemente(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Element", "Info"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 120)
        self.tree.setMinimumHeight(140)
        self.tree.itemSelectionChanged.connect(self.on_select)
        lay.addWidget(self.tree, 1)
        self.edit_box = QGroupBox("–")
        self.edit_lay = QVBoxLayout(self.edit_box)
        self.edit_lay.setContentsMargins(6, 4, 6, 4)
        lay.addWidget(self.edit_box)
        row = QHBoxLayout()
        self.b_apply = self._btn("Übernehmen", self.do_apply)
        self.b_place = self._btn("Neu platzieren", self.do_place)
        self.b_del = self._btn("Löschen", self.do_delete)
        for b in (self.b_apply, self.b_place, self.b_del):
            row.addWidget(b)
            b.setEnabled(False)
        lay.addLayout(row)
        lay.addWidget(self._btn("Liste neu laden", self.refresh))
        return w

    def _tab_lod2(self):
        from .laser_lod2 import MASSSTAEBE
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        row = QHBoxLayout()
        self.adresse = QLineEdit()
        self.adresse.setPlaceholderText("Adresse oder Bauwerk, z. B. "
                                        "„Uenglinger Tor Stendal“")
        self.adresse.returnPressed.connect(self.do_lod2)
        row.addWidget(self.adresse, 1)
        self.b_lod2 = self._btn("Suchen", self.do_lod2)
        row.addWidget(self.b_lod2)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Umkreis"))
        self.radius = _field("int", 80, 20, 300, 10)
        self.radius.setSuffix(" m")
        row.addWidget(self.radius)
        row.addStretch(1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("Maßstab 1:"))
        self.massstab = QComboBox()
        self.massstab.setEditable(True)
        self.massstab.setToolTip("Auswählen oder eigene Zahl eintippen "
                                 "(z. B. 75). In der Liste steht die "
                                 "Modellgröße des gewählten Gebäudes.")
        self.massstab_liste = MASSSTAEBE
        self._massstab_texte()
        self.massstab.setCurrentIndex(
            [m for m, _n in MASSSTAEBE].index(160))
        self.massstab.currentTextChanged.connect(self.zeige_teile)
        row.addWidget(self.massstab, 1)
        lay.addLayout(row)
        row = QHBoxLayout()
        row.addWidget(QLabel("oder längste Seite"))
        self.ziel = _field("mm", 150, 20, 1500, 10)
        self.ziel.setToolTip("Gewünschte Länge der längsten Gebäudeseite am "
                             "Modell — der Maßstab wird passend gerechnet.")
        row.addWidget(self.ziel)
        b = self._btn("→ Maßstab", self.do_zielgroesse)
        row.addWidget(b)
        row.addStretch(1)
        lay.addLayout(row)
        self.groesse = QLabel("")
        self.groesse.setStyleSheet("font-weight: bold;")
        lay.addWidget(self.groesse)
        self.plan = Lageplan()
        self.plan.gewaehlt.connect(lambda _i: self.zeige_teile())
        lay.addWidget(self.plan, 1)
        self.teile = QTreeWidget()
        self.teile.setHeaderLabels(["Teil", "Grundriss", "Traufe/First",
                                    "Dach", "Modell"])
        self.teile.setRootIsDecorated(False)
        self.teile.setMinimumHeight(90)
        lay.addWidget(self.teile)
        row = QHBoxLayout()
        self.b_haeuser = self._btn("Als Häuser anlegen", self.do_lod2_haeuser)
        self.b_masse = self._btn("Maße in „Bauen“", self.do_lod2_masse)
        for b in (self.b_haeuser, self.b_masse):
            b.setEnabled(False)
            row.addWidget(b)
        lay.addLayout(row)
        quelle = QLabel("Daten: amtliches 3D-Gebäudemodell LoD2 der Länder "
                        "(dl-de); Ausland: OpenStreetMap. Erster Abruf einer "
                        "Gegend dauert 1–4 min.")
        quelle.setWordWrap(True)
        quelle.setStyleSheet("color: #999; font-size: 10px;")
        lay.addWidget(quelle)
        return w

    def _tab_export(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(6)
        row = QHBoxLayout()
        self.pw = _field("mm", 400, 50, 2000, 10)
        self.ph = _field("mm", 300, 50, 2000, 10)
        row.addWidget(QLabel("Laserplatte"))
        row.addWidget(self.pw)
        row.addWidget(QLabel("×"))
        row.addWidget(self.ph)
        lay.addLayout(row)
        info = QLabel("Alle sichtbaren Platten werden flach gelegt und "
                      "verschachtelt. Rot = schneiden, blau = gravieren, "
                      "grau = Teilename. Massive Teile werden in Lagen "
                      "geschnitten, gebogene abgewickelt.")
        info.setWordWrap(True)
        info.setStyleSheet("color: #999;")
        lay.addWidget(info)
        lay.addWidget(self._btn("SVG + DXF für xTool", self.do_export))
        lay.addStretch(1)
        return w

    def say(self, text, error=False):
        self.status.setStyleSheet("color: %s;" % ("#d55" if error else "#888"))
        self.status.setText(text)
        QApplication.processEvents()

    def start_sc(self):
        self.say(hosts.start_solidcraft())

    # -- Verbindung

    def laser(self):
        if self.client is None or not self.client.alive():
            args = (["--headless"] if self.headless else
                    ["--connect", f"127.0.0.1:{hosts.SOLIDCRAFT_PORT}"])
            self.client = hosts.McpClient([*args, "--allow-path",
                                           hosts.UEBERGABE])
        return Laser(self.client, self.staerke.value(), self.finger.value())

    def run(self, label, fn, refresh=True, silent=False):
        if not silent:
            self.say(label + " …")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        ok = False
        try:
            msg = fn(self.laser())
            if msg:
                self.say(msg)
            ok = True
        except Exception as exc:              # noqa: BLE001
            if not (self.client and self.client.alive()):
                self.client = None
            self.say(f"{label}: {str(exc)[:300]}", error=True)
        finally:
            QApplication.restoreOverrideCursor()
        if ok and refresh:
            self.refresh(quiet=True)
        return ok

    def do_rillen(self, an):
        self.run("Gravur", lambda L: L.set_gravur(an))

    # -- Bauen

    def do_neu(self):
        if not self.auswahl:
            return
        name, _i, typ, preset, _h = self.auswahl
        p = dict(preset)
        p.update(self.neu_form.values())
        p["staerke"] = self.staerke.value()

        def fn(L):
            ctx = L.ctx_zinken() if typ == "zinken" else None
            return L.create(typ, p, ctx)
        self.run(name.replace("­", ""), fn)

    def do_export(self):
        def fn(L):
            msg, files = L.export_svg(platte=(self.pw.value(),
                                              self.ph.value()))
            self.files = files
            if files and sys.platform == "darwin" and not self.headless:
                subprocess.Popen(["open", "-R", files[0]])
            return msg
        self.run("Export", fn, refresh=False)

    # -- LoD2

    def do_lod2(self):
        q = self.adresse.text().strip()
        if not q or (self.worker and self.worker.isRunning()):
            return
        self.b_lod2.setEnabled(False)
        self.say("LoD2: Adresse und Gebäude werden geladen (beim ersten Mal "
                 "in einer Gegend 1–4 min) …")
        self.worker = Lod2Worker(q, self.radius.value())
        self.worker.fertig.connect(self._lod2_da)
        self.worker.start()

    def _lod2_da(self, d):
        self.b_lod2.setEnabled(True)
        if d.get("error"):
            self.say(f"LoD2: {d['error']}", error=True)
            return
        self.lod2 = d
        import math
        blds = sorted(d["buildings"], key=lambda b: math.hypot(*b["c"]))
        d["buildings"] = blds
        self.plan.setze(blds)
        quelle = "OpenStreetMap" if d.get("quelle") == "osm" else "LoD2"
        self.say(f"{len(blds)} Gebäude ({quelle}) — "
                 f"{d['place']['name'][:80]}. Gebäude im Plan anklicken.")
        if blds:
            self.plan.sel = 0
            self.plan.update()
            self.zeige_teile()

    def _gewaehltes(self):
        if not self.lod2 or self.plan.sel < 0:
            return None
        return self.lod2["buildings"][self.plan.sel]

    def _massstab(self):
        import re
        m = re.search(r"\d+(?:[.,]\d+)?",
                      self.massstab.currentText().replace("1:", "", 1))
        try:
            return max(1.0, float(m.group().replace(",", "."))) if m else 160.0
        except ValueError:
            return 160.0

    def _massstab_texte(self, parts=None):
        """Listeneinträge „87 · H0 · 120×95×140 mm“ (Größe, wenn ein
        Gebäude gewählt ist). Die freie Eingabe bleibt erhalten."""
        import re
        from . import laser_lod2 as L2
        aktuell = self.massstab.currentText()
        self.massstab.blockSignals(True)
        self.massstab.clear()
        for m, name in self.massstab_liste:
            t = f"{m:g}" + (f" · {name}" if name else "")
            if parts:
                g = L2.gesamt(parts, m)
                t += f" · {g[0]:.0f}×{g[1]:.0f}×{g[2]:.0f} mm"
            self.massstab.addItem(t, m)
        if aktuell:
            m = re.match(r"\s*(?:1:)?(\d+(?:[.,]\d+)?)", aktuell)
            v = m.group(1).replace(",", ".") if m else None
            idx = next((i for i, (q, _n) in enumerate(self.massstab_liste)
                        if v is not None and abs(q - float(v)) < 1e-6), -1)
            if idx >= 0:
                self.massstab.setCurrentIndex(idx)
            else:
                self.massstab.setEditText(aktuell)
        self.massstab.blockSignals(False)

    def do_zielgroesse(self):
        from . import laser_lod2 as L2
        if not getattr(self, "lod2_teile", None):
            self.say("Erst ein Gebäude suchen und im Plan anklicken.",
                     error=True)
            return
        m = L2.passend(self.lod2_teile, self.ziel.value())
        self.massstab.setEditText(str(m))      # löst zeige_teile aus

    def zeige_teile(self):
        from . import laser_lod2 as L2
        b = self._gewaehltes()
        self.teile.clear()
        self.lod2_teile = []
        self.groesse.setText("")
        if b is None:
            return
        parts, _ang = L2.analyse(b)
        self.lod2_teile = parts
        if not parts:
            return
        if getattr(self, "_texte_fuer", None) is not b:
            self._texte_fuer = b
            self._massstab_texte(parts)
        g = L2.gesamt(parts, self._massstab())
        self.groesse.setText(f"Modell bei 1:{self._massstab():g}: "
                             f"{g[0]:.0f} × {g[1]:.0f} × {g[2]:.0f} mm "
                             "(L × T × H)")
        els = L2.to_elements(parts, self._massstab())
        for i, (p, e) in enumerate(zip(parts, els)):
            it = QTreeWidgetItem([
                chr(65 + i), f"{p['laenge']:.1f} × {p['tiefe']:.1f} m",
                f"{p['traufe']:.1f} / {p['firsthoehe']:.1f} m",
                (p["dach"] if p["dach"] == "flach" else
                 f"{p['dach']} {p['neigung']:.0f}°") + (" ⟂" if e["quer"]
                                                       else ""),
                f"{e['breite']:g}×{e['tiefe']:g}×{e['hoehe']:g} mm"])
            if e["quer"]:
                it.setToolTip(3, "First liegt quer zum Hauptteil — das "
                              "Haus-Element hat den First immer längs; "
                              "bitte prüfen.")
            self.teile.addTopLevelItem(it)
        for c in range(5):
            self.teile.resizeColumnToContents(c)
        self.b_haeuser.setEnabled(True)
        self.b_masse.setEnabled(True)

    def do_lod2_haeuser(self):
        from . import laser_lod2 as L2
        if not getattr(self, "lod2_teile", None):
            return
        els = L2.to_elements(self.lod2_teile, self._massstab())
        b = self._gewaehltes()

        def fn(L):
            msgs = []
            for e in els:
                p = {k: v for k, v in e.items() if k != "quer"}
                p["staerke"] = self.staerke.value()
                if p["dach"] == "walm" and p["breite"] < p["tiefe"]:
                    p["dach"] = "sattel"
                msgs.append(L.create("haus", p))
            L._save(massstab=self._massstab(),
                    lod2={"adresse": b.get("addr"),
                          "ort": self.lod2["place"]["name"]})
            return f"1:{self._massstab():g} — " + " · ".join(msgs)
        self.run("LoD2", fn)

    def do_lod2_masse(self):
        from . import laser_lod2 as L2
        if not getattr(self, "lod2_teile", None):
            return
        els = L2.to_elements(self.lod2_teile, self._massstab())
        e = max(els, key=lambda q: q["breite"] * q["tiefe"])  # Hauptteil
        haus = next(b for b, it in self.kachel_daten.items()
                    if it[2] == "haus")
        haus.setChecked(True)
        self.show_neu(haus)
        for k in ("dach", "breite", "tiefe", "hoehe", "neigung"):
            w = self.neu_form.widgets.get(k)
            if w is None:
                continue
            if isinstance(w, QComboBox):
                w.setCurrentText(str(e[k]))
            else:
                w.setValue(e[k])
        self.tabs.setCurrentIndex(0)
        self.say(f"Hauptteil bei 1:{self._massstab():g} in „Bauen“ → Haus "
                 f"übernommen ({e['breite']:g}×{e['tiefe']:g}×{e['hoehe']:g} "
                 "mm).")

    # -- Elemente

    def refresh(self, quiet=False):
        keep = self.current_id()

        def fn(L):
            self.els = L.elements()
            self.rillen.blockSignals(True)
            self.rillen.setChecked(L.gravur_sichtbar())
            self.rillen.blockSignals(False)
            st = L.status(self.els)
            self.tree.blockSignals(True)
            self.tree.clear()
            for e in self.els:
                s = st.get(e["id"], "?")
                it = QTreeWidgetItem([e["name"], e.get("info", "")
                                      if s == "ok" else f"⚠ {s}"])
                it.setData(0, Qt.UserRole, e["id"])
                it.setToolTip(1, e.get("info", ""))
                icon = self._icon_fuer(e)
                if icon:
                    it.setIcon(0, icon)
                self.tree.addTopLevelItem(it)
                if e["id"] == keep:
                    self.tree.setCurrentItem(it)
            self.tree.blockSignals(False)
            self.show_form()
            return None if quiet else f"{len(self.els)} Elemente"
        self.run("Liste", fn, refresh=False, silent=quiet)

    def _icon_fuer(self, el):
        for _g, items in KATALOG:
            for _n, icon, typ, preset, _h in items:
                if typ == el["typ"] and all(
                        el["params"].get(k) == v for k, v in preset.items()
                        if k in ("dach", "muster", "art", "form")):
                    return svg_icon(ICONS.get(icon, ""), self._farbe(), 16)
        return None

    def current_id(self):
        it = self.tree.currentItem() if self.tree.selectedItems() else None
        return it.data(0, Qt.UserRole) if it else None

    def current(self):
        eid = self.current_id()
        return next((e for e in self.els if e["id"] == eid), None)

    def show_form(self):
        while self.edit_lay.count():
            w = self.edit_lay.takeAt(0).widget()
            if w:
                w.setParent(None)
                w.deleteLater()
        el = self.current()
        self.edit_form = None
        for b in (self.b_apply, self.b_place, self.b_del):
            b.setEnabled(el is not None)
        if el is None:
            self.edit_box.setTitle("–")
            return
        self.edit_box.setTitle(el["name"])
        self.edit_form = Form(el["typ"], el["params"])
        self.edit_lay.addWidget(self.edit_form.box)
        neu = el["typ"] in WAND_TYPES or el["typ"] in ("hinge", "zinken",
                                                       "gaube", "zwerch")
        self.b_place.setEnabled(neu)
        self.b_place.setToolTip(
            "Neue Stelle/Auswahl in SolidCraft anklicken, dann hier" if neu
            else "")

    def on_select(self):
        self.show_form()
        el = self.current()
        if el:
            self.run("Markieren", lambda L: L.highlight(el["id"])
                     or f"{el['name']}: {el.get('info', '')}",
                     refresh=False, silent=True)

    def do_apply(self):
        el = self.current()
        if el and self.edit_form:
            vals = self.edit_form.values()
            self.run(el["name"], lambda L: L.edit(el["id"], vals))

    def do_place(self):
        el = self.current()
        if el:
            vals = self.edit_form.values() if self.edit_form else None
            self.run(el["name"], lambda L: L.edit(el["id"], vals,
                                                  replace_ctx=True))

    def do_delete(self):
        el = self.current()
        if el:
            self.run(el["name"], lambda L: L.delete(el["id"]))

    def closeEvent(self, ev):
        if self.client:
            self.client.close()
        super().closeEvent(ev)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    w = Palette(headless="--headless" in argv)
    w.resize(420, 780)
    w.show()
    sys.exit(app.exec())
