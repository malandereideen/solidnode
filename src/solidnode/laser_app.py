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
from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QTabWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from . import hosts
from .laser import SCHEMA, Laser, defaults


def _field(kind, value, lo, hi, step):
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
        v = self._group(lay, "Kasten")
        self.f_kasten = Form("kasten", keys=["breite", "tiefe", "hoehe",
                                             "deckel"], cols=3)
        v.addWidget(self.f_kasten.box)
        v.addWidget(self._btn("Kasten anlegen", self.do_kasten))

        v = self._group(lay, "Zinken", "Platten überlappen lassen.")
        row = QHBoxLayout()
        row.addWidget(self._btn("Auswahl", lambda: self.do_zinken(True)))
        row.addWidget(self._btn("Alle Stöße", lambda: self.do_zinken(False)))
        v.addLayout(row)

        v = self._group(lay, "Living Hinge", "Biegelinie (oder Rechteck) "
                        "auf die Platte skizzieren und auswählen.")
        self.f_hinge = Form("hinge", keys=["radius", "winkel", "schnitt",
                                           "steg", "abstand", "schlitz"])
        v.addWidget(self.f_hinge.box)
        v.addWidget(self._btn("Hinge schneiden", self.do_hinge))

        v = self._group(lay, "Fenster", "Wandfläche an der Fenstermitte "
                        "anklicken.")
        self.f_fenster = Form("fenster", keys=[
            "breite", "hoehe", "rahmen", "sprosse", "sprossen_v",
            "sprossen_h", "oeffnung"])
        v.addWidget(self.f_fenster.box)
        v.addWidget(self._btn("Fenster setzen", self.do_fenster))

        v = self._group(lay, "Export")
        row = QHBoxLayout()
        self.pw = _field("mm", 400, 50, 2000, 10)
        self.ph = _field("mm", 300, 50, 2000, 10)
        row.addWidget(QLabel("Platte"))
        row.addWidget(self.pw)
        row.addWidget(self.ph)
        v.addLayout(row)
        v.addWidget(self._btn("SVG für xTool", self.do_export))
        lay.addStretch(1)
        return w

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

    def _mat(self, p):
        p["staerke"] = self.staerke.value()
        return p

    def do_kasten(self):
        self.run("Kasten", lambda L: L.create(
            "kasten", self._mat(self.f_kasten.values())))

    def do_zinken(self, auswahl):
        self.run("Zinken", lambda L: L.create(
            "zinken", {"zinke": self.finger.value()},
            L.ctx_zinken(None if auswahl else L.body_names())))

    def do_hinge(self):
        self.run("Living Hinge", lambda L: L.create(
            "hinge", self.f_hinge.values()))

    def do_fenster(self):
        self.run("Fenster", lambda L: L.create(
            "fenster", self._mat(self.f_fenster.values())))

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
    w.resize(320, 10)
    w.show()
    sys.exit(app.exec())
