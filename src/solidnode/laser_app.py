"""Laser-Palette: kleines Fenster neben SolidCraft (`solidnode laser`).

Arbeitet auf der Auswahl im offenen SolidCraft-Design; alles, was die
Palette baut, landet als normale Features in der Timeline (Strg+Z geht).
"""

from __future__ import annotations

import subprocess
import sys

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QApplication, QCheckBox, QDoubleSpinBox,
                               QFormLayout, QGroupBox, QHBoxLayout, QLabel,
                               QPushButton, QSpinBox, QVBoxLayout, QWidget)

from . import hosts
from .laser import Laser


def _num(v, lo, hi, step=0.5, dec=1, suffix=" mm"):
    w = QDoubleSpinBox()
    w.setRange(lo, hi)
    w.setDecimals(dec)
    w.setSingleStep(step)
    w.setValue(v)
    w.setSuffix(suffix)
    w.setKeyboardTracking(False)
    return w


def _int(v, lo, hi):
    w = QSpinBox()
    w.setRange(lo, hi)
    w.setValue(v)
    return w


class Palette(QWidget):
    def __init__(self, headless=False):
        super().__init__()
        self.setWindowTitle("Laser")
        self.setWindowFlag(Qt.WindowStaysOnTopHint, True)
        self.headless = headless
        self.client = None
        self.files = []
        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)
        root.setSpacing(6)

        g = self._group(root, "Material")
        self.staerke = _num(3.0, 0.5, 20, 0.5)
        self.finger = _num(10.0, 3, 60, 1)
        g.addRow("Stärke", self.staerke)
        g.addRow("Zinke", self.finger)

        g = self._group(root, "Kasten")
        self.kb, self.kt, self.kh = (_num(120, 10, 2000, 5, 0),
                                     _num(80, 10, 2000, 5, 0),
                                     _num(60, 10, 2000, 5, 0))
        row = QHBoxLayout()
        for w in (self.kb, self.kt, self.kh):
            w.setSuffix("")
            row.addWidget(w)
        g.addRow("B×T×H", row)
        self.deckel = QCheckBox("Deckel")
        g.addRow(self.deckel, self._btn("Kasten anlegen", self.do_kasten))

        g = self._group(root, "Zinken")
        g.addRow(QLabel("Platten überlappen lassen, dann:"))
        row = QHBoxLayout()
        row.addWidget(self._btn("Auswahl", lambda: self.do_zinken(True)))
        row.addWidget(self._btn("Alle Stöße", lambda: self.do_zinken(False)))
        g.addRow(row)

        g = self._group(root, "Living Hinge")
        g.addRow(QLabel("Biegelinie (oder Rechteck) auf die Platte\n"
                        "skizzieren und auswählen."))
        self.hr = _num(15, 1, 500, 1)
        self.hw = _num(90, 5, 360, 5, 0, "°")
        row = QHBoxLayout()
        row.addWidget(self.hr)
        row.addWidget(self.hw)
        g.addRow("Radius/Winkel", row)
        self.hs, self.hst, self.ha = (_num(15, 3, 100, 1), _num(3, 1, 20, 0.5),
                                      _num(1.5, 0.5, 10, 0.25, 2))
        row = QHBoxLayout()
        for w in (self.hs, self.hst, self.ha):
            w.setSuffix("")
            row.addWidget(w)
        g.addRow("Schnitt/Steg/Abst.", row)
        g.addRow(self._btn("Hinge schneiden", self.do_hinge))

        g = self._group(root, "Fenster")
        g.addRow(QLabel("Wandfläche an der Mitte des Fensters anklicken."))
        self.fb, self.fh = _num(20, 2, 500, 1, 0), _num(30, 2, 500, 1, 0)
        row = QHBoxLayout()
        row.addWidget(self.fb)
        row.addWidget(self.fh)
        g.addRow("B×H", row)
        self.fr, self.fs = _num(3, 0.5, 30, 0.5), _num(1.5, 0.5, 10, 0.5)
        row = QHBoxLayout()
        row.addWidget(self.fr)
        row.addWidget(self.fs)
        g.addRow("Rahmen/Sprosse", row)
        self.fv, self.fhz = _int(1, 0, 10), _int(1, 0, 10)
        row = QHBoxLayout()
        row.addWidget(self.fv)
        row.addWidget(self.fhz)
        g.addRow("Sprossen ↕/↔", row)
        self.fo = QCheckBox("Öffnung schneiden")
        self.fo.setChecked(True)
        g.addRow(self.fo, self._btn("Fenster setzen", self.do_fenster))

        g = self._group(root, "Export")
        self.pw, self.ph = _num(400, 50, 2000, 10, 0), _num(300, 50, 2000,
                                                            10, 0)
        row = QHBoxLayout()
        row.addWidget(self.pw)
        row.addWidget(self.ph)
        g.addRow("Platte", row)
        g.addRow(self._btn("SVG für xTool", self.do_export))

        self.status = QLabel("")
        self.status.setWordWrap(True)
        self.status.setStyleSheet("color: #888;")
        root.addWidget(self.status)
        if not headless and not hosts.port_open(hosts.SOLIDCRAFT_PORT):
            row = self._btn("SolidCraft starten", self.start_sc)
            root.addWidget(row)
            self.say("SolidCraft läuft nicht mit Steuerport "
                     f"{hosts.SOLIDCRAFT_PORT}.")

    # -- Aufbau

    def _group(self, root, title):
        box = QGroupBox(title)
        f = QFormLayout(box)
        f.setContentsMargins(6, 4, 6, 4)
        f.setSpacing(4)
        root.addWidget(box)
        return f

    def _btn(self, text, fn):
        b = QPushButton(text)
        b.clicked.connect(fn)
        return b

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

    def run(self, label, fn):
        self.say(label + " …")
        QApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            msg = fn(self.laser())
            self.say(msg)
        except Exception as exc:              # noqa: BLE001
            text = str(exc)
            if "ConnectionError" in type(exc).__name__ or not (
                    self.client and self.client.alive()):
                self.client = None
            self.say(f"{label}: {text[:300]}", error=True)
        finally:
            QApplication.restoreOverrideCursor()

    # -- Werkzeuge

    def do_kasten(self):
        self.run("Kasten", lambda L: L.kasten(
            self.kb.value(), self.kt.value(), self.kh.value(),
            self.deckel.isChecked()))

    def do_zinken(self, auswahl):
        def fn(L):
            if auswahl:
                return L.zinken()
            return L.zinken(L.body_names())
        self.run("Zinken", fn)

    def do_hinge(self):
        self.run("Living Hinge", lambda L: L.hinge(
            self.hr.value(), self.hw.value(), self.hs.value(),
            self.hst.value(), self.ha.value()))

    def do_fenster(self):
        self.run("Fenster", lambda L: L.fenster(
            self.fb.value(), self.fh.value(), self.fr.value(),
            self.fv.value(), self.fhz.value(), self.fs.value(),
            self.fo.isChecked()))

    def do_export(self):
        def fn(L):
            msg, files = L.export_svg(platte=(self.pw.value(),
                                              self.ph.value()))
            self.files = files
            if files and sys.platform == "darwin" and not self.headless:
                subprocess.Popen(["open", "-R", files[0]])
            return msg
        self.run("Export", fn)

    def closeEvent(self, ev):
        if self.client:
            self.client.close()
        super().closeEvent(ev)


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    app = QApplication.instance() or QApplication(sys.argv[:1])
    w = Palette(headless="--headless" in argv)
    w.resize(300, 10)
    w.show()
    if "--quit-after-show" in argv:
        return w
    sys.exit(app.exec())
