"""Laser-Palette: kleines Fenster neben SolidCraft (`solidnode laser`).

Reiter „Neu“ legt Elemente an, Reiter „Elemente“ listet alles, was die
Palette im offenen Design gebaut hat: anklicken = in SolidCraft markieren,
Werte ändern + Übernehmen = an derselben Timeline-Stelle neu bauen.
Die Liste steht in den Metadaten des Designs und reist mit der .sc-Datei.
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QComboBox,
                               QDoubleSpinBox, QFormLayout, QGroupBox,
                               QHBoxLayout, QLabel, QPushButton,
                               QSpinBox, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import hosts
from .laser import SCHEMA, WAND_TYPES, Laser, defaults


# Baukasten wie im bausatzmaker: (Gruppe, Name, Typ, Voreinstellung, Hinweis)
_WAND = "Wandfläche anklicken"
KATALOG = [
    ("Baukörper", "Kasten", "kasten", {}, "Wird bei X/Y/Z angelegt."),
    ("Baukörper", "Haus", "haus", {}, "Wird bei X/Y/Z angelegt; danach "
     "Zinken für die Wände."),
    ("Baukörper", "Turm (Vieleck)", "turm", {}, "Wird bei X/Y/Z angelegt."),
    ("Baukörper", "Schornstein", "kamin", {}, "Haus anklicken (sonst das "
     "zuletzt angelegte)."),
    ("Öffnungen", "Fenster", "fenster", {}, _WAND + " (Fenstermitte)."),
    ("Öffnungen", "Tür", "tuer", {}, _WAND + " (Türmitte; unten sitzt sie "
     "auf der Wandkante bzw. dem Boden)."),
    ("Öffnungen", "Tor", "tuer", {"blatt": False, "breite": 26, "hoehe": 30,
                                   "rahmen": 3}, _WAND + " (Tormitte)."),
    ("Blenden", "Blende", "blende", {}, _WAND + " (Mitte)."),
    ("Blenden", "Nischenreihe", "blende", {"anzahl": 5, "breite": 5,
                                           "hoehe": 11, "abstand": 9},
     _WAND + " (Mitte der Reihe)."),
    ("Muster", "Muster (Gravur)", "muster", {}, _WAND + ". Bereich „feld“ = "
     "Feld um den Klickpunkt, sonst die ganze Fläche."),
    ("Bänder", "Gesims", "band", {"art": "gesims"}, _WAND + "; rundum = "
     "alle vier Wände des Kastens/Hauses."),
    ("Bänder", "Sockel", "band", {"art": "sockel", "hoehe": 4}, _WAND + "."),
    ("Bänder", "Traufgesims", "band", {"art": "trauf"}, _WAND + "."),
    ("Bänder", "Rundbogenfries", "band", {"art": "fries", "hoehe": 6},
     _WAND + "."),
    ("Schmuck", "Eckquader", "eckquader", {}, "Eine Wand des Kastens/Hauses "
     "anklicken."),
    ("Schmuck", "Strebepfeiler", "pfeiler", {}, _WAND + " (Pfeilermitte)."),
    ("Schmuck", "Uhr", "uhr", {}, _WAND + " (Uhrmitte)."),
    ("Platten", "Zinken", "zinken", {}, "Platten auswählen — oder nichts, "
     "dann alle Stöße."),
    ("Platten", "Living Hinge", "hinge", {}, "Biegelinie (oder Rechteck) auf "
     "die Platte skizzieren und auswählen."),
]
_VERSTECKT = {"x", "y", "z"}        # Lage kommt beim Anlegen vom Klick


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
            if kind in ("bool", "choice") and n % cols:
                n += cols - n % cols            # eigene Zeile
            if kind == "bool":
                w.setText(label)
                f.addRow(w)
                continue
            if n % cols == 0:
                row = QHBoxLayout()
                f.addRow(row)
            lab = QLabel(label)
            lab.setStyleSheet("color: #999;")
            row.addWidget(lab)
            row.addWidget(w, 1)
            n += 1

    def values(self):
        return {k: _value(w) for k, w in self.widgets.items()}


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
        root = QVBoxLayout(self)
        root.setContentsMargins(6, 6, 6, 6)
        root.setSpacing(4)

        g = QHBoxLayout()
        self.staerke = _field("mm", 3.0, 0.5, 20, 0.5)
        self.finger = _field("mm", 10.0, 3, 60, 1)
        g.addWidget(QLabel("Stärke"))
        g.addWidget(self.staerke, 1)
        g.addWidget(QLabel("Zinke"))
        g.addWidget(self.finger, 1)
        root.addLayout(g)

        self.tabs = QTabWidget()
        root.addWidget(self.tabs)
        self.tabs.addTab(self._tab_neu(), "Neu")
        self.tabs.addTab(self._tab_elemente(), "Elemente")
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

    def _group(self, lay, title, hint=None):
        box = QGroupBox(title)
        v = QVBoxLayout(box)
        v.setContentsMargins(6, 4, 6, 4)
        v.setSpacing(3)
        if hint:
            h = QLabel(hint)
            h.setStyleSheet("color: #999;")
            h.setWordWrap(True)
            v.addWidget(h)
        lay.addWidget(box)
        return v

    def _btn(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        return b

    def _tab_neu(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.kat = QComboBox()
        gruppe = None
        for i, (g, name, _t, _p, _h) in enumerate(KATALOG):
            if g != gruppe:
                if gruppe is not None:
                    self.kat.insertSeparator(self.kat.count())
                gruppe = g
            self.kat.addItem(f"{g} · {name}", i)
        self.kat.currentIndexChanged.connect(self.show_neu)
        lay.addWidget(self.kat)
        self.hint = QLabel("")
        self.hint.setWordWrap(True)
        self.hint.setStyleSheet("color: #999;")
        lay.addWidget(self.hint)
        self.neu_box = QWidget()
        self.neu_lay = QVBoxLayout(self.neu_box)
        self.neu_lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.neu_box)
        self.neu_form = None
        lay.addWidget(self._btn("Anlegen", self.do_neu))

        v = self._group(lay, "Export")
        row = QHBoxLayout()
        self.pw = _field("mm", 400, 50, 2000, 10)
        self.ph = _field("mm", 300, 50, 2000, 10)
        row.addWidget(QLabel("Platte"))
        row.addWidget(self.pw)
        row.addWidget(self.ph)
        v.addLayout(row)
        v.addWidget(self._btn("SVG + DXF für xTool", self.do_export))
        lay.addStretch(1)
        self.show_neu()
        return w

    def show_neu(self):
        while self.neu_lay.count():
            it = self.neu_lay.takeAt(0).widget()
            if it:
                it.setParent(None)
                it.deleteLater()
        _g, _n, typ, preset, hint = KATALOG[self.kat.currentData() or 0]
        vals = dict(preset)
        vals.setdefault("staerke", self.staerke.value())
        if typ == "zinken":
            vals.setdefault("zinke", self.finger.value())
        keys = [f[0] for f in SCHEMA[typ]["fields"]
                if not (f[0] in _VERSTECKT and typ in WAND_TYPES)
                and f[0] not in ("staerke",)]
        self.neu_form = Form(typ, vals, keys=keys)
        self.neu_lay.addWidget(self.neu_form.box)
        self.hint.setText(hint)

    def _tab_elemente(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        lay.setContentsMargins(4, 4, 4, 4)
        lay.setSpacing(4)
        self.tree = QTreeWidget()
        self.tree.setHeaderLabels(["Element", "Info"])
        self.tree.setRootIsDecorated(False)
        self.tree.setColumnWidth(0, 95)
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

    # -- Neu

    def do_neu(self):
        _g, name, typ, preset, _h = KATALOG[self.kat.currentData() or 0]
        p = dict(preset)
        p.update(self.neu_form.values())
        p["staerke"] = self.staerke.value()

        def fn(L):
            ctx = None
            if typ == "zinken":
                ctx = L.ctx_zinken()
            return L.create(typ, p, ctx)
        self.run(name, fn)

    def do_export(self):
        def fn(L):
            msg, files = L.export_svg(platte=(self.pw.value(),
                                              self.ph.value()))
            self.files = files
            if files and sys.platform == "darwin" and not self.headless:
                subprocess.Popen(["open", "-R", files[0]])
            return msg
        self.run("Export", fn, refresh=False)

    # -- Elemente

    def refresh(self, quiet=False):
        keep = self.current_id()

        def fn(L):
            self.els = L.elements()
            st = L.status(self.els)
            self.tree.blockSignals(True)
            self.tree.clear()
            for e in self.els:
                s = st.get(e["id"], "?")
                it = QTreeWidgetItem([e["name"], e.get("info", "")
                                      if s == "ok" else f"⚠ {s}"])
                it.setData(0, Qt.UserRole, e["id"])
                it.setToolTip(1, e.get("info", ""))
                self.tree.addTopLevelItem(it)
                if e["id"] == keep:
                    self.tree.setCurrentItem(it)
            self.tree.blockSignals(False)
            self.show_form()
            return None if quiet else f"{len(self.els)} Elemente"
        self.run("Liste", fn, refresh=False, silent=quiet)

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
        self.b_place.setEnabled(el["typ"] in ("fenster", "hinge", "zinken"))
        self.b_place.setToolTip({
            "fenster": "Neue Wandfläche/Mitte in SolidCraft anklicken, dann hier",
            "hinge": "Andere Biegelinie auswählen, dann hier",
            "zinken": "Platten auswählen (oder nichts = alle), dann hier",
        }.get(el["typ"], ""))

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
    w.resize(360, 10)
    w.show()
    sys.exit(app.exec())
