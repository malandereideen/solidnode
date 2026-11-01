"""SolidNode-Kern: Nodes, Datenbäume, Panel — angelehnt an Grasshopper.

Wird von der App (app.py) und vom optionalen Serpentine3D-Plugin genutzt.

Datenmodell: einfache Listen statt Grasshopper-Datenbäumen. Ein Eingang,
der eine Liste bekommt, wird elementweise abgearbeitet (längste Liste,
kürzere wiederholen ihr letztes Element). Eingänge mit LISTE=True
bekommen die ganze Liste auf einmal (Loft, Polylinie, …).
"""

from __future__ import annotations

import math
import os
import time
import traceback

os.environ.setdefault("QT_API", "pyside6")

IGNORED_PROPS = {
    "pos", "selected", "color", "text_color", "border_color", "disabled",
    "visible", "width", "height", "layout_direction", "name", "id", "type_",
    "icon", "port_deletion_allowed", "subgraph_session",
}

COLOR_OK = (13, 18, 23)
COLOR_WARN = (110, 85, 25)
COLOR_ERROR = (125, 35, 35)


# --------------------------------------------------------------- Werte

def parse(kind, text):
    if text is None:
        return None
    text = str(text).strip()
    if kind == "num":
        return float(text.replace(",", "."))
    if kind == "int":
        return int(round(float(text.replace(",", "."))))
    if kind == "pt":
        parts = text.replace(";", " ").replace(",", " ").split()
        x, y, z = (float(p) for p in (parts + ["0", "0", "0"])[:3])
        return (x, y, z)
    return text


def is_shape(v):
    from OCP.TopoDS import TopoDS_Shape
    from serpentine3d.core.mesh import MeshShape
    return isinstance(v, (TopoDS_Shape, MeshShape))


def is_point(v):
    return (isinstance(v, tuple) and len(v) == 3
            and all(isinstance(c, (int, float)) for c in v))


def flatten(v):
    if isinstance(v, list):
        for item in v:
            yield from flatten(item)
    elif v is not None:
        yield v


class Tree:
    """Datenbaum wie in Grasshopper: Pfad (Tupel) -> Liste von Werten."""

    def __init__(self, branches=None):
        self.b = dict(branches or {})

    @classmethod
    def of(cls, value):
        if isinstance(value, Tree):
            return value
        return cls({(0,): value if isinstance(value, list) else [value]})

    @classmethod
    def merge(cls, trees):
        out = cls()
        for t in trees:
            for path, items in t.b.items():
                out.b.setdefault(path, []).extend(items)
        return out

    def add(self, path, value):
        self.b.setdefault(path, []).append(value)

    def items(self):
        for items in self.b.values():
            yield from flatten(items)

    def count(self):
        return sum(len(v) for v in self.b.values())


def path_str(p):
    return "{" + ";".join(str(i) for i in p) + "}"


def fmt_tree(t):
    if len(t.b) == 1 and next(iter(t.b)) == (0,):
        return fmt(next(iter(t.b.values())))
    lines = [f"{len(t.b)} Zweige · {t.count()} Werte"]
    for path, items in list(t.b.items())[:50]:
        lines.append(f"{path_str(path)} ({len(items)})")
        lines.extend("  " + ln for ln in fmt(items).splitlines()[:20])
    if len(t.b) > 50:
        lines.append(f"… {len(t.b)} Zweige")
    return "\n".join(lines)


def fmt(v):
    if isinstance(v, float):
        return f"{v:.4g}"
    if is_point(v):
        return "(" + ", ".join(f"{c:.4g}" for c in v) + ")"
    if isinstance(v, list):
        lines = [f"{i}: {fmt(x)}" for i, x in enumerate(v[:200])]
        if len(v) > 200:
            lines.append(f"… {len(v)} Einträge")
        return "\n".join(lines) or "(leere Liste)"
    if v is not None and is_shape(v):
        from serpentine3d.core import geometry as geo
        return f"<{geo.shape_kind(v)}>"
    return str(v)


builtins_max = max


class Hinweis(Exception):
    """Kein Fehler, nur ein Zustand (gelb statt rot, ohne Traceback)."""

# verbundene Werte in den Typ des Eingangs bringen (Regler → Ganzzahl usw.)
COERCE = {
    "num": lambda v: float(v) if isinstance(v, (int, float, bool)) else v,
    "int": lambda v: int(round(v)) if isinstance(v, (int, float)) else v,
}


def clip_halfplane(poly, nx, ny, c):
    """Polygon auf die Seite nx*x + ny*y <= c beschneiden."""
    out = []
    for k, (ax, ay) in enumerate(poly):
        bx, by = poly[(k + 1) % len(poly)]
        da, db = nx * ax + ny * ay - c, nx * bx + ny * by - c
        if da <= 0:
            out.append((ax, ay))
        if (da < 0 < db) or (db < 0 < da):
            t = da / (da - db)
            out.append((ax + t * (bx - ax), ay + t * (by - ay)))
    return out


FORMULA_NS = {k: getattr(math, k) for k in dir(math) if not k.startswith("_")}
FORMULA_NS.update(abs=abs, min=min, max=max, round=round)


def make_core():
    """Node-Klassen und Panel, unabhängig davon, wohin die Geometrie geht.

    Gibt die Klasse NodePanel zurück; sie bekommt ein Ziel (hosts.Host),
    das Vorschau, Bake und Einpassen übernimmt.
    """
    from NodeGraphQt import BaseNode, NodeGraph
    from NodeGraphQt.widgets.node_widgets import NodeBaseWidget
    from PySide6 import QtCore, QtGui, QtWidgets
    from serpentine3d.core import geometry as geo
    from serpentine3d.core.tessellate import tessellate

    # ----------------------------------------------------------- Widgets

    class NumField(QtWidgets.QLineEdit):
        """Zahlenfeld mit der Schnittstelle von QDoubleSpinBox (schlicht,
        damit es klein bleibt und die Zahl sichtbar ist)."""
        valueChanged = QtCore.Signal(float)

        def __init__(self):
            super().__init__()
            self._v, self._dec = 0.0, 1
            self.editingFinished.connect(self._commit)

        def setRange(self, *_a):
            pass

        def setButtonSymbols(self, *_a):
            pass

        def setDecimals(self, d):
            self._dec = d
            self._show()

        def value(self):
            return self._v

        def setValue(self, v):
            changed = float(v) != self._v
            self._v = float(v)
            self._show()
            if changed and not self.signalsBlocked():
                self.valueChanged.emit(self._v)

        def _show(self):
            self.setText(f"{self._v:.{self._dec}f}")

        def _commit(self):
            try:
                v = float(self.text().replace(",", "."))
            except ValueError:
                self._show()
                return
            self.setValue(round(v, self._dec))

    class SliderBox(QtWidgets.QWidget):
        changed = QtCore.Signal()

        def __init__(self):
            super().__init__()
            self.lo, self.hi, self.dec = 0.0, 100.0, 1
            lay = QtWidgets.QHBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            self.slider = QtWidgets.QSlider(QtCore.Qt.Orientation.Horizontal)
            self.slider.setRange(0, 1000)
            self.slider.setFixedWidth(96)
            self.spin = NumField()
            self.spin.setRange(-1e9, 1e9)
            self.spin.setDecimals(self.dec)
            self.spin.setFixedSize(54, 18)
            self.spin.setAlignment(QtCore.Qt.AlignmentFlag.AlignRight)
            self.spin.setButtonSymbols(
                QtWidgets.QAbstractSpinBox.ButtonSymbols.NoButtons)
            self.setStyleSheet(COMPACT_CSS)
            lay.addWidget(self.slider)
            lay.addWidget(self.spin)
            self.slider.valueChanged.connect(self._from_slider)
            self.spin.valueChanged.connect(self._from_spin)

        def value(self):
            return round(self.spin.value(), self.dec)

        def set_value(self, v):
            self.spin.blockSignals(True)
            self.spin.setValue(float(v))
            self.spin.blockSignals(False)
            self._place_slider()

        def set_range(self, lo, hi, dec):
            self.lo, self.hi, self.dec = lo, hi, max(0, dec)
            v = self.spin.value()
            self.spin.blockSignals(True)
            self.spin.setDecimals(self.dec)
            self.spin.setValue(v)
            self.spin.blockSignals(False)
            self._place_slider()

        def _place_slider(self):
            span = (self.hi - self.lo) or 1.0
            t = (self.spin.value() - self.lo) / span
            self.slider.blockSignals(True)
            self.slider.setValue(int(round(max(0.0, min(1.0, t)) * 1000)))
            self.slider.blockSignals(False)

        def _from_slider(self, pos):
            v = self.lo + (self.hi - self.lo) * pos / 1000
            self.spin.blockSignals(True)
            self.spin.setValue(round(v, self.dec))
            self.spin.blockSignals(False)
            self.changed.emit()

        def _from_spin(self, _):
            self._place_slider()
            self.changed.emit()

    class NodeSlider(NodeBaseWidget):
        def __init__(self, parent=None, name="", label=""):
            super().__init__(parent, name, label)
            box = SliderBox()
            self.set_custom_widget(box)
            shrink(self)
            box.changed.connect(self.on_value_changed)

        def get_value(self):
            return self.get_custom_widget().value()

        def set_value(self, v):
            self.get_custom_widget().set_value(v)

    class NodeReadout(NodeBaseWidget):
        def __init__(self, parent=None, name="", label=""):
            super().__init__(parent, name, label)
            text = QtWidgets.QPlainTextEdit()
            text.setReadOnly(True)
            text.setFixedSize(170, 96)
            text.setStyleSheet("QPlainTextEdit { background: #1b1d21;"
                               " color: #cfd3da; font-size: 9px;"
                               " border: 1px solid #3a3d44; }")
            self.set_custom_widget(text)

        def get_value(self):
            return ""

        def set_value(self, _):
            pass

        def show(self, s):
            self.get_custom_widget().setPlainText(s)

    PANELS = []

    # ------------------------------------------------- kompakte Darstellung

    COMPACT_CSS = (
        "QWidget { background: transparent; }"
        "QLineEdit { background: #1b1d21; color: #dcdcdc;"
        " border: 1px solid #3a3d44; border-radius: 3px; padding: 0 3px;"
        " font-size: 10px; }"
        "QLineEdit:disabled { color: #555; border-color: #2a2c31; }"
        "QLabel { color: #8b8f97; font-size: 9px; }"
        "QComboBox { background: #1b1d21; color: #dcdcdc; font-size: 10px;"
        " border: 1px solid #3a3d44; border-radius: 3px; padding: 0 4px; }"
        "QComboBox QAbstractItemView { font-size: 11px; }"
        "QCheckBox { color: #b8bcc4; font-size: 10px; }"
        "QDoubleSpinBox { background: #1b1d21; color: #dcdcdc;"
        " border: 1px solid #3a3d44; border-radius: 3px; font-size: 10px;"
        " padding: 0 3px; }")

    def shrink(node_widget):
        """Proxy und Gruppenrahmen auf die Größe des Inhalts bringen."""
        box = node_widget.widget()
        inner = box.layout().itemAt(0).widget()
        inner.setSizePolicy(QtWidgets.QSizePolicy.Policy.Fixed,
                            QtWidgets.QSizePolicy.Policy.Fixed)
        inner.adjustSize()
        box.setStyleSheet(box.styleSheet() + "QGroupBox { padding: 1px; }")
        box.setFixedSize(inner.sizeHint() + QtCore.QSize(4, 4))
        node_widget.resize(box.size())

    def shrink_plain(node_widget):
        box = node_widget.widget()
        box.setStyleSheet(box.styleSheet() + "QGroupBox { padding: 1px; }")
        inner = box.layout().itemAt(0).widget()
        box.setFixedSize(inner.sizeHint() + QtCore.QSize(4, 4))
        node_widget.resize(box.size())

    def _row(label, field, width):
        w = QtWidgets.QWidget()
        w.setAttribute(QtCore.Qt.WidgetAttribute.WA_TranslucentBackground)
        lay = QtWidgets.QHBoxLayout(w)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(3)
        if label:
            lab = QtWidgets.QLabel(label)
            lay.addWidget(lab)
        field.setFixedSize(width, 18)
        lay.addWidget(field)
        w.setStyleSheet(COMPACT_CSS)
        return w

    class NodeValue(NodeBaseWidget):
        """Einzeiliges Wertfeld, optional mit kleiner Beschriftung davor."""

        def __init__(self, parent=None, name="", label="", text="",
                     width=58, tooltip=""):
            super().__init__(parent, name, "")
            self.edit = QtWidgets.QLineEdit(str(text))
            self.edit.editingFinished.connect(self.on_value_changed)
            if tooltip:
                self.edit.setToolTip(tooltip)
            self.set_custom_widget(_row(label, self.edit, width))
            shrink(self)

        def get_value(self):
            return self.edit.text()

        def set_value(self, v):
            if self.edit.text() != str(v):
                self.edit.setText(str(v))

        def get_custom_widget(self):
            return self.edit

    class NodeCombo(NodeBaseWidget):
        def __init__(self, parent=None, name="", label="", items=(),
                     width=96):
            super().__init__(parent, name, "")
            self.combo = QtWidgets.QComboBox()
            self.combo.addItems(list(items))
            self.combo.currentIndexChanged.connect(self.on_value_changed)
            self.set_custom_widget(_row(label, self.combo, width))
            shrink(self)

        def get_value(self):
            return self.combo.currentText()

        def set_value(self, v):
            i = self.combo.findText(str(v))
            if i >= 0 and i != self.combo.currentIndex():
                self.combo.setCurrentIndex(i)

        def get_custom_widget(self):
            return self.combo

    from NodeGraphQt.qgraphics.node_base import NodeItem

    class CompactNodeItem(NodeItem):
        """Wertfelder stehen neben ihrem Eingang statt darunter; Felder
        mit `_inline` teilen sich eine Zeile."""

        ROW = 23.0

        def _parts(self):
            ins = [(p, t) for p, t in self._input_items.items()
                   if p.isVisible()]
            outs = [(p, t) for p, t in self._output_items.items()
                    if p.isVisible()]
            ws = [w for w in self._widgets.values() if w.isVisible()]
            aligned = {w._port_name: w for w in ws
                       if getattr(w, "_port_name", None)}
            rows, cur = [], None
            for w in ws:
                if getattr(w, "_port_name", None):
                    continue
                if getattr(w, "_inline", False) and cur is not None:
                    cur.append(w)
                    continue
                cur = [w]
                rows.append(cur)
            return ins, outs, aligned, rows

        @staticmethod
        def _tw(items):
            return max([t.boundingRect().width() for _p, t in items
                        if t.isVisible()] or [0.0])

        def _calc_size_horizontal(self):
            ins, outs, aligned, rows = self._parts()
            title_w = self._text_item.boundingRect().width()
            port_w = (ins or outs)[0][0].boundingRect().width() if (
                ins or outs) else 0.0
            aw = max([w.boundingRect().width()
                      for w in aligned.values()] or [0.0])
            port_row = port_w + self._tw(ins) + (aw + 6 if aw else 0) \
                + 14 + self._tw(outs)
            free_w = max([sum(w.boundingRect().width() for w in r)
                          + 4 * (len(r) - 1) for r in rows] or [0.0])
            free_h = sum(max(w.boundingRect().height() for w in r)
                         for r in rows)
            width = max(title_w + 20, port_row, free_w + 16)
            height = max(len(ins), len(outs)) * self.ROW + free_h + 4
            return width, max(height, self._text_item.boundingRect()
                              .height())

        def _align_widgets_horizontal(self, v_offset):
            ins, outs, aligned, rows = self._parts()
            port_w = (ins or outs)[0][0].boundingRect().width() if (
                ins or outs) else 0.0
            x0 = port_w / 2 + self._tw(ins) + 4
            for port, _t in ins:
                w = aligned.get(port.name)
                if w is None:
                    continue
                h = w.boundingRect().height()
                w.setPos(x0, port.y() + (port.boundingRect().height()
                                         - h) / 2)
            y = v_offset + max(len(ins), len(outs)) * self.ROW
            for r in rows:
                x = 8.0
                for w in r:
                    try:
                        w.widget().setTitleAlign("left")
                    except AttributeError:
                        pass
                    w.setPos(x, y)
                    x += w.boundingRect().width() + 4
                y += max(w.boundingRect().height() for w in r)

    # ------------------------------------------------------------ Basis

    class SerpNode(BaseNode):
        __identifier__ = "serp"
        # (name, art, standard, ganze Liste)
        INPUTS: list = []
        OUTPUTS: list = []

        def __init__(self):
            super().__init__(CompactNodeItem)
            for name, kind, default, _whole in self.INPUTS:
                self.add_input(name, multi_input=_whole)
                if default is not None:
                    w = NodeValue(self.view, "in_" + name, "", str(default),
                                  width=64 if kind == "pt" else 46,
                                  tooltip=f"{name} (Standard, wenn nichts "
                                          "verbunden ist)")
                    w._port_name = name
                    self.add_custom_widget(w)
            for name in self.OUTPUTS:
                self.add_output(name)
            self.message = ""

        # kompakte Fassungen der NodeGraphQt-Felder
        def add_text_input(self, name, label="", text="", width=150,
                           inline=False, **_kw):
            w = NodeValue(self.view, name, label, text, width=width,
                          tooltip=label)
            w._inline = inline
            self.add_custom_widget(w)

        def add_combo_menu(self, name, label="", items=None, **_kw):
            self.add_custom_widget(NodeCombo(self.view, name, label,
                                             items or []))

        def add_checkbox(self, name, label="", text="", state=False, **_kw):
            super().add_checkbox(name, "", text=text, state=state)
            cb = self.get_widget(name)
            cb.get_custom_widget().setStyleSheet(COMPACT_CSS)

        def on_input_connected(self, in_port, out_port):
            self._enable_default(in_port.name(), False)

        def on_input_disconnected(self, in_port, out_port):
            if not in_port.connected_ports():
                self._enable_default(in_port.name(), True)

        def _enable_default(self, name, on):
            w = self.get_widget("in_" + name)
            if w is not None:
                w.get_custom_widget().setEnabled(on)

        def mark(self, state, msg=""):
            self.message = msg
            self.set_color(*{"ok": COLOR_OK, "warn": COLOR_WARN,
                             "error": COLOR_ERROR}[state])
            self.view.setToolTip(msg)

        def compute(self, inputs):
            """Zweige paarweise (längster gewinnt), darin Elemente paarweise.

            Ein Element-Eingang bekommt je Durchlauf einen Wert, ein
            Listen-Eingang den ganzen Zweig. Liefert solve() eine Liste und
            gab es mehrere Durchläufe, bekommt jeder Durchlauf einen eigenen
            Unterzweig {pfad;i} — wie Grasshopper.
            """
            whole = {n for n, _k, _d, w in self.INPUTS if w}
            outs = {name: Tree() for name in self.OUTPUTS}
            branches = {k: list(t.b.values()) for k, t in inputs.items()}
            if any(not v for v in branches.values()):
                return outs
            master = max(inputs.values(), key=lambda t: len(t.b),
                         default=Tree({(0,): []}))
            paths = list(master.b) or [(0,)]
            nb = max((len(v) for v in branches.values()), default=1)
            for bi in range(nb):
                path = paths[min(bi, len(paths) - 1)]
                branch = {k: v[min(bi, len(v) - 1)]
                          for k, v in branches.items()}
                item_keys = [k for k in branch if k not in whole]
                if any(not branch[k] for k in item_keys):
                    continue
                n = max((len(branch[k]) for k in item_keys), default=1)
                for i in range(n):
                    args = {k: (v[min(i, len(v) - 1)] if k in item_keys
                                else v) for k, v in branch.items()}
                    res = self.solve(**args)
                    vals = (res if len(self.OUTPUTS) > 1
                            and isinstance(res, tuple) else (res,))
                    for name, v in zip(self.OUTPUTS, vals):
                        if isinstance(v, list):
                            p = path + (i,) if n > 1 else path
                            outs[name].b.setdefault(p, []).extend(v)
                        else:
                            outs[name].add(path, v)
            return outs

        def solve(self, **kw):
            raise NotImplementedError

    # ------------------------------------------------------ Parameter

    class ZahlNode(SerpNode):
        __identifier__ = "serp.Parameter"
        NODE_NAME = "Zahl"
        OUTPUTS = ["N"]

        def __init__(self):
            super().__init__()
            self.add_custom_widget(NodeSlider(self.view, "wert", ""))
            self.add_text_input("min", "min", text="0", width=30)
            self.add_text_input("max", "max", text="100", width=30,
                                inline=True)
            self.add_text_input("dezimalen", ".0", text="1", width=18,
                                inline=True)
            self.set_property("wert", 10.0)
            self._apply_range()

        def set_property(self, name, value, push_undo=True):
            super().set_property(name, value, push_undo)
            if name in ("min", "max", "dezimalen"):
                self._apply_range()

        def _apply_range(self):
            try:
                lo = parse("num", self.get_property("min"))
                hi = parse("num", self.get_property("max"))
                dec = parse("int", self.get_property("dezimalen"))
            except (TypeError, ValueError):
                return
            self.get_widget("wert").get_custom_widget().set_range(lo, hi, dec)

        def solve(self):
            return float(self.get_property("wert"))

    class NodeButton(NodeBaseWidget):
        def __init__(self, parent=None, name="", text="", width=150):
            super().__init__(parent, name, "")
            self.btn = QtWidgets.QPushButton(text)
            self.btn.setFixedSize(width, 20)
            self.btn.setStyleSheet(
                "QPushButton { background: #2c4a40; color: #dff5ec;"
                " border: 1px solid #4db39a; border-radius: 3px;"
                " font-size: 10px; } QPushButton:pressed {"
                " background: #4db39a; }")
            self.set_custom_widget(self.btn)
            shrink_plain(self)

        def get_value(self):
            return ""

        def set_value(self, _):
            pass

    class HolenNode(SerpNode):
        """Geometrie aus Serpentine3D oder SolidCraft übernehmen (wie
        „Set one/multiple Geometry“ in Grasshopper). Eine Kopie steht im
        Graph; mit „verknüpft“ wird sie bei Änderungen neu geholt."""
        __identifier__ = "serp.Parameter"
        NODE_NAME = "Geometrie holen"
        OUTPUTS = ["geometrie"]

        def __init__(self):
            super().__init__()
            self.create_property("refs", "[]")
            self.create_property("daten", "[]")
            b = NodeButton(self.view, "holen_knopf", "Auswahl übernehmen")
            b.btn.clicked.connect(self.take_selection)
            self.add_custom_widget(b)
            self.add_checkbox("verknuepft", "", text="verknüpft", state=False)
            self.info = NodeValue(self.view, "holen_info", "", "leer",
                                  width=150)
            self.info.edit.setReadOnly(True)
            self.add_custom_widget(self.info)
            self._decoded = (None, [])
            self._rev = None

        def take_selection(self):
            panel = PANELS[-1] if PANELS else None
            try:
                found = panel.host.pick()
            except Exception as exc:              # noqa: BLE001
                self.mark("error", str(exc))
                self.info.set_value("Fehler: " + str(exc)[:40])
                return
            self.store(found)
            self._rev = None

        def store(self, found):
            import json
            from . import hosts
            refs = [r for r, _n, _s in found]
            data = [dict(hosts.encode_shape(s), name=n) for _r, n, s in found]
            src = refs[0].get("src", "?") if refs else "?"
            self.info.set_value(f"{len(found)} aus {src}")
            new = json.dumps(data)
            if new != self.get_property("daten"):
                self.set_property("refs", json.dumps(refs))
                self.set_property("daten", new)

        def refresh(self, panel):
            """Bei „verknüpft“: neu holen, wenn sich im CAD etwas tat."""
            import json
            if not self.get_property("verknuepft"):
                return
            refs = json.loads(self.get_property("refs") or "[]")
            if not refs:
                return
            rev = panel.host.revision(refs[0].get("src"))
            if rev is None or rev == self._rev:
                return
            first = self._rev is None
            self._rev = rev
            if first and self.get_property("daten") != "[]":
                return                      # Stand beim Laden gilt erstmal
            try:
                self.store(panel.host.refetch(refs))
            except Exception as exc:              # noqa: BLE001
                self.mark("warn", f"Neu holen ging nicht: {exc}")

        def compute(self, inputs):
            import json
            from . import hosts
            daten = self.get_property("daten") or "[]"
            if self._decoded[0] != daten:
                shapes = [hosts.decode_shape(e) for e in json.loads(daten)]
                self._decoded = (daten, shapes)
            if not self._decoded[1]:
                raise Hinweis("Noch nichts übernommen: im CAD auswählen, "
                              "dann „Auswahl übernehmen“")
            return {"geometrie": Tree({(0,): list(self._decoded[1])})}

    class FolgeNode(SerpNode):
        __identifier__ = "serp.Parameter"
        NODE_NAME = "Folge"
        INPUTS = [("start", "num", 0, False), ("schritt", "num", 1, False),
                  ("anzahl", "int", 10, False)]
        OUTPUTS = ["liste"]

        def solve(self, start, schritt, anzahl):
            return [start + i * schritt for i in range(max(0, anzahl))]

    class BereichNode(SerpNode):
        __identifier__ = "serp.Parameter"
        NODE_NAME = "Bereich"
        INPUTS = [("von", "num", 0, False), ("bis", "num", 1, False),
                  ("teile", "int", 10, False)]
        OUTPUTS = ["liste"]

        def solve(self, von, bis, teile):
            teile = max(1, teile)
            return [von + (bis - von) * i / teile for i in range(teile + 1)]

    class PunktNode(SerpNode):
        __identifier__ = "serp.Parameter"
        NODE_NAME = "Punkt"
        INPUTS = [("x", "num", 0, False), ("y", "num", 0, False),
                  ("z", "num", 0, False)]
        OUTPUTS = ["punkt"]

        def solve(self, x, y, z):
            return (x, y, z)

    class AnzeigeNode(SerpNode):
        __identifier__ = "serp.Parameter"
        NODE_NAME = "Anzeige"
        SINK = True
        INPUTS = [("wert", "any", None, True)]
        OUTPUTS = []

        def __init__(self):
            super().__init__()
            self.readout = NodeReadout(self.view, "anzeige", "")
            self.add_custom_widget(self.readout)

        def compute(self, inputs):
            self.readout.show(fmt_tree(inputs["wert"]))
            return {}

    # ---------------------------------------------------------- Mathe

    class RechnenNode(SerpNode):
        __identifier__ = "serp.Mathe"
        NODE_NAME = "Rechnen"
        INPUTS = [("a", "num", 0, False), ("b", "num", 1, False)]
        OUTPUTS = ["ergebnis"]
        OPS = {"+": lambda a, b: a + b, "−": lambda a, b: a - b,
               "×": lambda a, b: a * b, "÷": lambda a, b: a / b,
               "^": lambda a, b: a ** b, "min": min, "max": max,
               "Rest": lambda a, b: a % b}

        def __init__(self):
            super().__init__()
            self.add_combo_menu("op", "Operation", items=list(self.OPS))

        def solve(self, a, b):
            return self.OPS[self.get_property("op")](a, b)

    class FunktionNode(SerpNode):
        __identifier__ = "serp.Mathe"
        NODE_NAME = "Funktion"
        INPUTS = [("x", "num", 0, False), ("y", "num", 0, False),
                  ("z", "num", 0, False), ("a", "num", 0, False),
                  ("b", "num", 0, False)]
        OUTPUTS = ["ergebnis"]

        def __init__(self):
            super().__init__()
            self.add_text_input("formel", "Formel (x y z a b, pi, sin …)",
                                text="sin(x)")

        def solve(self, x, y, z, a, b):
            src = self.get_property("formel")
            if getattr(self, "_src", None) != src:
                self._code = compile(src, "Formel", "eval")
                self._src = src
            ns = dict(FORMULA_NS, x=x, y=y, z=z, a=a, b=b)
            return float(eval(self._code, {"__builtins__": {}}, ns))

    class ListenElementNode(SerpNode):
        __identifier__ = "serp.Listen"
        NODE_NAME = "Listen-Element"
        INPUTS = [("liste", "any", None, True), ("index", "int", 0, False)]
        OUTPUTS = ["element"]

        def solve(self, liste, index):
            if not liste:
                raise ValueError("Liste ist leer")
            return liste[index % len(liste)]

    class ListenLaengeNode(SerpNode):
        __identifier__ = "serp.Listen"
        NODE_NAME = "Listen-Länge"
        INPUTS = [("liste", "any", None, True)]
        OUTPUTS = ["laenge"]

        def solve(self, liste):
            return len(liste)

    class UmkehrenNode(SerpNode):
        __identifier__ = "serp.Listen"
        NODE_NAME = "Umkehren"
        INPUTS = [("liste", "any", None, True)]
        OUTPUTS = ["liste"]

        def solve(self, liste):
            return list(reversed(liste))

    class ListeVersetzenNode(SerpNode):
        __identifier__ = "serp.Listen"
        NODE_NAME = "Liste versetzen"
        INPUTS = [("liste", "any", None, True), ("um", "int", 1, False)]
        OUTPUTS = ["liste"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("rund", "", text="ringförmig", state=True)

        def solve(self, liste, um):
            if not liste:
                return []
            if self.get_property("rund"):
                k = um % len(liste)
                return liste[k:] + liste[:k]
            return liste[um:] if um >= 0 else liste[:um]

    class TeilenNode(SerpNode):
        __identifier__ = "serp.Listen"
        NODE_NAME = "Teilen"
        INPUTS = [("liste", "any", None, True), ("groesse", "int", 2, False)]
        OUTPUTS = ["teile"]

        def compute(self, inputs):
            out = Tree()
            size = max(1, next(inputs["groesse"].items()))
            for path, items in inputs["liste"].b.items():
                for j in range(0, len(items), size):
                    out.b[path + (j // size,)] = items[j:j + size]
            return {"teile": out}

    # ----------------------------------------------------------- Baum

    class BaumNode(SerpNode):
        """Arbeitet auf dem ganzen Baum statt je Zweig."""
        __identifier__ = "serp.Baum"
        INPUTS = [("daten", "any", None, True)]
        OUTPUTS = ["daten"]

        def compute(self, inputs):
            return {"daten": self.tree(inputs["daten"])}

    class AufpfropfenNode(BaumNode):
        NODE_NAME = "Aufpfropfen"

        def tree(self, t):
            out = Tree()
            for path, items in t.b.items():
                for i, v in enumerate(items):
                    out.b[path + (i,)] = [v]
            return out

    class GlaettenNode(BaumNode):
        NODE_NAME = "Glätten"

        def tree(self, t):
            return Tree({(0,): list(t.items())})

    class VereinfachenNode(BaumNode):
        NODE_NAME = "Vereinfachen"

        def tree(self, t):
            paths = list(t.b)
            if len(paths) < 2:
                return Tree({(0,): v for v in t.b.values()})
            k = 0
            while (all(len(p) > k + 1 for p in paths)
                   and len({p[k] for p in paths}) == 1):
                k += 1
            return Tree({p[k:]: v for p, v in t.b.items()})

    class MatrixTauschenNode(BaumNode):
        NODE_NAME = "Matrix tauschen"

        def tree(self, t):
            out = Tree()
            for items in t.b.values():
                for i, v in enumerate(items):
                    out.add((i,), v)
            return out

    class ZweigNode(SerpNode):
        __identifier__ = "serp.Baum"
        NODE_NAME = "Zweig wählen"
        INPUTS = [("daten", "any", None, True), ("index", "int", 0, False)]
        OUTPUTS = ["liste"]

        def compute(self, inputs):
            t = inputs["daten"]
            if not t.b:
                return {"liste": Tree()}
            out = Tree()
            for i in inputs["index"].items():
                path = list(t.b)[i % len(t.b)]
                out.b[path] = list(t.b[path])
            return {"liste": out}

    class ZusammenfuehrenNode(SerpNode):
        __identifier__ = "serp.Baum"
        NODE_NAME = "Zusammenführen"
        INPUTS = [("a", "any", None, True), ("b", "any", None, True)]
        OUTPUTS = ["daten"]

        def compute(self, inputs):
            return {"daten": Tree.merge([inputs["a"], inputs["b"]])}

    # --------------------------------------------------------- Kurven

    class LinieNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Linie"
        INPUTS = [("a", "pt", "0 0 0", False), ("b", "pt", "100 0 0", False)]
        OUTPUTS = ["kurve"]

        def solve(self, a, b):
            return geo.make_line(a, b)

    class PolylinieNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Polylinie"
        INPUTS = [("punkte", "pt", None, True)]
        OUTPUTS = ["kurve"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("zu", "", text="geschlossen", state=False)

        def solve(self, punkte):
            return geo.make_polyline(punkte, closed=self.get_property("zu"))

    class InterpKurveNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Kurve durch Punkte"
        INPUTS = [("punkte", "pt", None, True)]
        OUTPUTS = ["kurve"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("zu", "", text="geschlossen", state=True)

        def solve(self, punkte):
            return geo.make_interp_curve(punkte,
                                         closed=self.get_property("zu"))

    class KreisNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Kreis"
        INPUTS = [("mitte", "pt", "0 0 0", False),
                  ("radius", "num", 50, False)]
        OUTPUTS = ["kurve"]

        def solve(self, mitte, radius):
            return geo.make_circle(mitte, radius)

    class RechteckNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Rechteck"
        INPUTS = [("ecke", "pt", "0 0 0", False), ("breite", "num", 100, False),
                  ("hoehe", "num", 50, False)]
        OUTPUTS = ["kurve"]

        def solve(self, ecke, breite, hoehe):
            x, y, z = ecke
            return geo.make_rectangle(ecke, (x + breite, y + hoehe, z))

    # --------------------------------------------------------- Körper

    class ExtrudierenNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Extrudieren"
        INPUTS = [("profil", "geo", None, False),
                  ("hoehe", "num", 50, False)]
        OUTPUTS = ["form"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("deckel", "", text="Deckel (Körper)", state=True)

        def solve(self, profil, hoehe):
            return geo.extrude(profil, (0, 0, 1), hoehe,
                               cap=self.get_property("deckel"))

    class LoftNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Loft"
        INPUTS = [("profile", "geo", None, True)]
        OUTPUTS = ["form"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("solid", "", text="Körper", state=True)
            self.add_checkbox("ruled", "", text="geradlinig", state=False)

        def solve(self, profile):
            return geo.loft(profile, solid=self.get_property("solid"),
                            ruled=self.get_property("ruled"))

    class DrehkoerperNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Drehkörper"
        INPUTS = [("profil", "geo", None, False),
                  ("achspunkt", "pt", "0 0 0", False),
                  ("richtung", "pt", "0 0 1", False),
                  ("winkel", "num", 360, False)]
        OUTPUTS = ["form"]

        def solve(self, profil, achspunkt, richtung, winkel):
            return geo.revolve(profil, achspunkt, richtung, winkel)

    class BoxNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Box"
        INPUTS = [("ecke", "pt", "0 0 0", False), ("x", "num", 50, False),
                  ("y", "num", 50, False), ("z", "num", 50, False)]
        OUTPUTS = ["form"]

        def solve(self, ecke, x, y, z):
            return geo.make_box(ecke, x, y, z)

    class ZylinderNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Zylinder"
        INPUTS = [("basis", "pt", "0 0 0", False),
                  ("radius", "num", 20, False), ("hoehe", "num", 50, False)]
        OUTPUTS = ["form"]

        def solve(self, basis, radius, hoehe):
            return geo.make_cylinder(basis, radius, hoehe)

    class KugelNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Kugel"
        INPUTS = [("mitte", "pt", "0 0 0", False),
                  ("radius", "num", 25, False)]
        OUTPUTS = ["form"]

        def solve(self, mitte, radius):
            return geo.make_sphere(mitte, radius)

    class BooleanNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Boolean"
        INPUTS = [("a", "geo", None, False), ("b", "geo", None, True)]
        OUTPUTS = ["form"]
        OPS = {"Differenz": geo.boolean_difference,
               "Vereinigung": geo.boolean_union,
               "Schnitt": geo.boolean_intersection}

        def __init__(self):
            super().__init__()
            self.add_combo_menu("op", "Operation", items=list(self.OPS))

        def solve(self, a, b):
            op = self.OPS[self.get_property("op")]
            for other in b:
                a = op(a, other)
            return a

    class SchaleNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Schale"
        INPUTS = [("koerper", "geo", None, False), ("wand", "num", 2, False)]
        OUTPUTS = ["form"]

        def __init__(self):
            super().__init__()
            self.add_checkbox("offen", "", text="oben offen", state=True)

        def solve(self, koerper, wand):
            if not self.get_property("offen"):
                # shell_solid liefert den inneren Versatzkörper
                return geo.boolean_difference(koerper,
                                              geo.shell_solid(koerper, wand))
            from OCP.BRepGProp import BRepGProp
            from OCP.BRepOffsetAPI import BRepOffsetAPI_MakeThickSolid
            from OCP.GProp import GProp_GProps
            from OCP.TopAbs import TopAbs_FACE
            from OCP.TopExp import TopExp_Explorer
            from OCP.TopoDS import TopoDS
            from OCP.TopTools import TopTools_ListOfShape
            top, best = None, -1e18
            exp = TopExp_Explorer(koerper, TopAbs_FACE)
            while exp.More():
                face = TopoDS.Face_s(exp.Current())
                props = GProp_GProps()
                BRepGProp.SurfaceProperties_s(face, props)
                z = props.CentreOfMass().Z()
                if z > best:
                    top, best = face, z
                exp.Next()
            faces = TopTools_ListOfShape()
            faces.Append(top)
            mk = BRepOffsetAPI_MakeThickSolid()
            mk.MakeThickSolidByJoin(koerper, faces, -abs(wand), 1e-3)
            if not mk.IsDone():
                raise ValueError("Schale fehlgeschlagen (Wand zu dick?)")
            return mk.Shape()

    class AbrundenNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Abrunden"
        INPUTS = [("koerper", "geo", None, False),
                  ("radius", "num", 2, False)]
        OUTPUTS = ["form"]

        def solve(self, koerper, radius):
            return geo.fillet_edges(koerper, radius)

    # ------------------------------------------------------ Transform

    class VerschiebenNode(SerpNode):
        __identifier__ = "serp.Transform"
        NODE_NAME = "Verschieben"
        INPUTS = [("geometrie", "geo", None, False), ("x", "num", 0, False),
                  ("y", "num", 0, False), ("z", "num", 10, False)]
        OUTPUTS = ["geometrie"]

        def solve(self, geometrie, x, y, z):
            if is_point(geometrie):
                return tuple(a + b for a, b in zip(geometrie, (x, y, z)))
            return geo.translate(geometrie, (x, y, z))

    class DrehenNode(SerpNode):
        __identifier__ = "serp.Transform"
        NODE_NAME = "Drehen"
        INPUTS = [("geometrie", "geo", None, False),
                  ("winkel", "num", 45, False),
                  ("mitte", "pt", "0 0 0", False)]
        OUTPUTS = ["geometrie"]
        AXES = {"Z": (0, 0, 1), "X": (1, 0, 0), "Y": (0, 1, 0)}

        def __init__(self):
            super().__init__()
            self.add_combo_menu("achse", "Achse", items=list(self.AXES))

        def solve(self, geometrie, winkel, mitte):
            return geo.rotate(geometrie, mitte,
                              self.AXES[self.get_property("achse")], winkel)

    class SkalierenNode(SerpNode):
        __identifier__ = "serp.Transform"
        NODE_NAME = "Skalieren"
        INPUTS = [("geometrie", "geo", None, False),
                  ("faktor", "num", 1, False),
                  ("mitte", "pt", "0 0 0", False)]
        OUTPUTS = ["geometrie"]

        def solve(self, geometrie, faktor, mitte):
            return geo.scale(geometrie, mitte, faktor)

    # ------------------------------------------------ Kurven, erweitert

    class PolygonNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Polygon"
        INPUTS = [("mitte", "pt", "0 0 0", False),
                  ("radius", "num", 30, False), ("seiten", "int", 6, False)]
        OUTPUTS = ["kurve"]

        def solve(self, mitte, radius, seiten):
            n = max(3, seiten)
            cx, cy, cz = mitte
            pts = [(cx + radius * math.cos(2 * math.pi * i / n),
                    cy + radius * math.sin(2 * math.pi * i / n), cz)
                   for i in range(n)]
            return geo.make_polyline(pts, closed=True)

    class KurveTeilenNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Kurve teilen"
        INPUTS = [("kurve", "geo", None, False), ("anzahl", "int", 10, False)]
        OUTPUTS = ["punkte"]

        def solve(self, kurve, anzahl):
            return [tuple(float(c) for c in p)
                    for p in geo.sample_curve(kurve, max(2, anzahl))]

    class KurveVersetzenNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Kurve versetzen"
        INPUTS = [("kurve", "geo", None, False), ("abstand", "num", 2, False)]
        OUTPUTS = ["kurve"]

        def solve(self, kurve, abstand):
            return geo.offset_curve(kurve, abstand)

    class TextNode(SerpNode):
        __identifier__ = "serp.Kurven"
        NODE_NAME = "Text"
        INPUTS = [("hoehe", "num", 10, False)]
        OUTPUTS = ["kurven"]

        def __init__(self):
            super().__init__()
            self.add_text_input("text", "Text", text="Mario")
            self.add_checkbox("fett", "", text="fett", state=True)

        def solve(self, hoehe):
            from serpentine3d.core.text import text_curves
            return list(text_curves(self.get_property("text"), hoehe,
                                    bold=self.get_property("fett")))

    # -------------------------------------------------- Körper, erweitert

    class SweepNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Sweep"
        INPUTS = [("profil", "geo", None, False), ("pfad", "geo", None, False)]
        OUTPUTS = ["form"]

        def solve(self, profil, pfad):
            return geo.sweep1(profil, pfad)

    class RohrNode(SerpNode):
        __identifier__ = "serp.Koerper"
        NODE_NAME = "Rohr"
        INPUTS = [("pfad", "geo", None, False), ("radius", "num", 3, False)]
        OUTPUTS = ["form"]

        def solve(self, pfad, radius):
            return geo.pipe(pfad, radius)

    class SpiegelnNode(SerpNode):
        __identifier__ = "serp.Transform"
        NODE_NAME = "Spiegeln"
        INPUTS = [("geometrie", "geo", None, False),
                  ("punkt", "pt", "0 0 0", False),
                  ("normale", "pt", "1 0 0", False)]
        OUTPUTS = ["geometrie"]

        def solve(self, geometrie, punkt, normale):
            return geo.mirror(geometrie, punkt, normale)

    class PolarNode(SerpNode):
        __identifier__ = "serp.Transform"
        NODE_NAME = "Kreisförmig anordnen"
        INPUTS = [("geometrie", "geo", None, False),
                  ("anzahl", "int", 6, False), ("winkel", "num", 360, False),
                  ("mitte", "pt", "0 0 0", False)]
        OUTPUTS = ["kopien"]

        def solve(self, geometrie, anzahl, winkel, mitte):
            n = max(1, anzahl)
            step = winkel / n if abs(winkel) >= 360 else winkel / max(1, n - 1)
            return [geo.rotate(geometrie, mitte, (0, 0, 1), i * step)
                    for i in range(n)]

    # ---------------------------------------------------------- Muster

    class ZufallNode(SerpNode):
        __identifier__ = "serp.Muster"
        NODE_NAME = "Zufall"
        INPUTS = [("anzahl", "int", 10, False), ("min", "num", 0, False),
                  ("max", "num", 1, False), ("seed", "int", 1, False)]
        OUTPUTS = ["zahlen"]

        def solve(self, anzahl, min, max, seed):   # noqa: A002
            import random
            rnd = random.Random(seed)
            return [rnd.uniform(min, max) for _ in range(builtins_max(0, anzahl))]

    class ZufallspunkteNode(SerpNode):
        __identifier__ = "serp.Muster"
        NODE_NAME = "Zufallspunkte"
        INPUTS = [("ecke", "pt", "0 0 0", False),
                  ("breite", "num", 100, False), ("hoehe", "num", 100, False),
                  ("anzahl", "int", 30, False), ("seed", "int", 1, False)]
        OUTPUTS = ["punkte"]

        def solve(self, ecke, breite, hoehe, anzahl, seed):
            import random
            rnd = random.Random(seed)
            x0, y0, z0 = ecke
            return [(x0 + rnd.uniform(0, breite), y0 + rnd.uniform(0, hoehe),
                     z0) for _ in range(builtins_max(0, anzahl))]

    class VoronoiNode(SerpNode):
        __identifier__ = "serp.Muster"
        NODE_NAME = "Voronoi"
        INPUTS = [("punkte", "pt", None, True),
                  ("ecke", "pt", "0 0 0", False),
                  ("breite", "num", 100, False), ("hoehe", "num", 100, False)]
        OUTPUTS = ["zellen"]

        def solve(self, punkte, ecke, breite, hoehe):
            x0, y0, z0 = ecke
            rect = [(x0, y0), (x0 + breite, y0), (x0 + breite, y0 + hoehe),
                    (x0, y0 + hoehe)]
            sites = [(p[0], p[1]) for p in punkte]
            cells = []
            for i, (sx, sy) in enumerate(sites):
                poly = rect
                for j, (tx, ty) in enumerate(sites):
                    if i == j or (sx, sy) == (tx, ty):
                        continue
                    # Halbebene: näher an s als an t
                    nx, ny = tx - sx, ty - sy
                    c = (tx * tx + ty * ty - sx * sx - sy * sy) / 2
                    poly = clip_halfplane(poly, nx, ny, c)
                    if len(poly) < 3:
                        break
                if len(poly) >= 3:
                    cells.append(geo.make_polyline(
                        [(x, y, z0) for x, y in poly], closed=True))
            return cells

    # ---------------------------------------------------------- Ausgabe

    class ExportNode(SerpNode):
        __identifier__ = "serp.Ausgabe"
        NODE_NAME = "Export"
        SINK = True
        INPUTS = [("geometrie", "geo", None, True)]
        OUTPUTS = ["datei"]

        def __init__(self):
            super().__init__()
            self.add_text_input("pfad", "Datei (.stl .3mf .step)",
                                text="~/Desktop/nodes.stl")
            self.add_checkbox("aktiv", "", text="schreiben", state=False)

        def compute(self, inputs):
            shapes = [s for s in inputs["geometrie"].items() if is_shape(s)]
            path = os.path.expanduser(self.get_property("pfad"))
            if not self.get_property("aktiv"):
                return {"datei": Tree.of("aus")}
            ext = os.path.splitext(path)[1].lower()
            named = [(f"Teil {i + 1}", s) for i, s in enumerate(shapes)]
            if ext == ".stl":
                from serpentine3d.fileio.stl import export_stl
                export_stl(named, path)
            elif ext == ".3mf":
                from serpentine3d.fileio.threemf import export_3mf
                export_3mf(named, path)
            elif ext in (".step", ".stp"):
                from serpentine3d.fileio.step import export_step
                export_step(shapes, path)
            else:
                raise ValueError("Endung .stl, .3mf oder .step")
            return {"datei": Tree.of(f"{len(shapes)} Teil(e) → {path}")}

    NODE_CLASSES = [
        ZahlNode, HolenNode, FolgeNode, BereichNode, PunktNode, AnzeigeNode,
        RechnenNode, FunktionNode, ListenElementNode,
        ListenLaengeNode, UmkehrenNode, ListeVersetzenNode, TeilenNode,
        AufpfropfenNode, GlaettenNode, VereinfachenNode, MatrixTauschenNode,
        ZweigNode, ZusammenfuehrenNode,
        LinieNode, PolylinieNode, InterpKurveNode, KreisNode, RechteckNode,
        ExtrudierenNode, LoftNode, DrehkoerperNode, BoxNode, ZylinderNode,
        KugelNode, BooleanNode, SchaleNode, AbrundenNode,
        VerschiebenNode, DrehenNode, SkalierenNode,
        PolygonNode, KurveTeilenNode, KurveVersetzenNode, TextNode,
        SweepNode, RohrNode, SpiegelnNode, PolarNode,
        ZufallNode, ZufallspunkteNode, VoronoiNode, ExportNode,
    ]

    from . import fabrication, polyhedra
    NODE_CLASSES += fabrication.make_nodes(SerpNode, Tree, geo, is_shape,
                                           parse)
    NODE_CLASSES += polyhedra.make_nodes(SerpNode)

    # ---------------------------------------------------------- Panel

    # -------------------------------------------------------- Palette

    CATEGORIES = [
        ("serp.Parameter", "Parameter", "#5b8fd9"),
        ("serp.Mathe", "Mathe", "#9a7ad6"),
        ("serp.Listen", "Listen", "#c47cc0"),
        ("serp.Baum", "Baum", "#76a85a"),
        ("serp.Kurven", "Kurven", "#d9a248"),
        ("serp.Koerper", "Körper", "#4db39a"),
        ("serp.Pyramiden", "Pyramiden", "#d98a4a"),
        ("serp.Platonisch", "Platonische Körper", "#3fb3a6"),
        ("serp.Stumpf", "Abgestumpfte", "#5b9bd9"),
        ("serp.Archimedisch", "Weitere archimedische", "#9a85dd"),
        ("serp.Transform", "Transform", "#d86e5b"),
        ("serp.Muster", "Muster", "#c8b748"),
        ("serp.Laser", "Laser", "#e35d4d"),
        ("serp.Druck", "3D-Druck", "#56a8ca"),
        ("serp.Ausgabe", "Ausgabe", "#8c929c"),
    ]
    SYMBOLS = {
        "ZahlNode": "N", "HolenNode": "⇲", "FolgeNode": "1‥n", "BereichNode": "[ ]",
        "PunktNode": "×", "AnzeigeNode": "▤",
        "RechnenNode": "±", "FunktionNode": "ƒx",
        "ListenElementNode": "[i]", "ListenLaengeNode": "#",
        "UmkehrenNode": "⇄", "ListeVersetzenNode": "↻", "TeilenNode": "÷",
        "AufpfropfenNode": "Y", "GlaettenNode": "═", "VereinfachenNode": "⇣",
        "MatrixTauschenNode": "⇅", "ZweigNode": "{i}",
        "ZusammenfuehrenNode": "⋈",
        "LinieNode": "╱", "PolylinieNode": "⋀", "InterpKurveNode": "~",
        "KreisNode": "○", "RechteckNode": "▭", "PolygonNode": "◇",
        "KurveTeilenNode": "⋯", "KurveVersetzenNode": "◎", "TextNode": "T",
        "ExtrudierenNode": "⬆", "LoftNode": "≋", "DrehkoerperNode": "⊙",
        "BoxNode": "▣", "ZylinderNode": "▯", "KugelNode": "●",
        "BooleanNode": "◑", "SchaleNode": "◡", "AbrundenNode": "⌒",
        "SweepNode": "⤳", "RohrNode": "⊚",
        "VerschiebenNode": "✥", "DrehenNode": "↺", "SkalierenNode": "⤢",
        "SpiegelnNode": "◧", "PolarNode": "✲",
        "ZufallNode": "⚄", "ZufallspunkteNode": "⁘", "VoronoiNode": "⬢",
        "ExportNode": "⤓",
        "FingerzinkenNode": "⊓⊔", "ZinkenBoxNode": "⧈",
        "LivingHingeNode": "┆", "KerfNode": "◫", "VerschachtelnNode": "⊞",
        "SvgExportNode": "svg", "SchlitzeNode": "‖",
        "KonturschnittNode": "≡", "WaffelNode": "♯",
        "DruckCheckNode": "✓", "AufBettNode": "⊥", "ToleranzPaarNode": "⊘",
        "GitterNode": "▦", "GyroidNode": "≈", "GewindeNode": "≀",
        "PraegenNode": "Aa", "MehrfarbNode": "▥",
    }

    def node_icon(cls, color):
        """Kachel: getönter Grund, Rand und Zeichen in Kategoriefarbe."""
        size, dpr = 26, 2
        pm = QtGui.QPixmap(size * dpr, size * dpr)
        pm.setDevicePixelRatio(dpr)
        pm.fill(QtCore.Qt.GlobalColor.transparent)
        p = QtGui.QPainter(pm)
        p.setRenderHint(QtGui.QPainter.RenderHint.Antialiasing)
        c = QtGui.QColor(color)
        bg = QtGui.QColor(c)
        bg.setAlpha(55)
        p.setBrush(bg)
        p.setPen(QtGui.QPen(c, 1.2))
        p.drawRoundedRect(QtCore.QRectF(1, 1, size - 2, size - 2), 5, 5)
        lines = getattr(cls, "ICON_LINES", None)
        if lines:                       # Polyeder: Drahtansicht statt Zeichen
            pad, span = 4.0, size - 8.0
            for (x0, y0), (x1, y1), front in lines:
                col = c.lighter(150) if front else QtGui.QColor(c)
                if not front:
                    col.setAlpha(110)
                p.setPen(QtGui.QPen(col, 1.0 if front else 0.7))
                p.drawLine(QtCore.QPointF(pad + x0 * span, pad + y0 * span),
                           QtCore.QPointF(pad + x1 * span, pad + y1 * span))
            p.end()
            return QtGui.QIcon(pm)
        sym = SYMBOLS.get(cls.__name__, cls.NODE_NAME[:2])
        f = QtGui.QFont()
        f.setBold(True)
        f.setPixelSize({1: 16, 2: 12, 3: 10}.get(len(sym), 9))
        p.setFont(f)
        p.setPen(c.lighter(150))
        p.drawText(QtCore.QRectF(0, 0, size, size),
                   QtCore.Qt.AlignmentFlag.AlignCenter, sym)
        p.end()
        return QtGui.QIcon(pm)

    class IconGrid(QtWidgets.QListWidget):
        """Kacheln einer Kategorie; ziehen = Node an die Stelle legen."""

        def __init__(self, graph):
            super().__init__()
            self.graph = graph
            self.setViewMode(QtWidgets.QListView.ViewMode.IconMode)
            self.setIconSize(QtCore.QSize(26, 26))
            self.setGridSize(QtCore.QSize(30, 30))
            self.setMovement(QtWidgets.QListView.Movement.Static)
            self.setResizeMode(QtWidgets.QListView.ResizeMode.Adjust)
            self.setWrapping(True)
            self.setDragEnabled(True)
            self.setDragDropMode(
                QtWidgets.QAbstractItemView.DragDropMode.DragOnly)
            self.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            self.setVerticalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            self.setMinimumWidth(0)
            self.setSizePolicy(QtWidgets.QSizePolicy.Policy.Ignored,
                               QtWidgets.QSizePolicy.Policy.Fixed)
            self.setStyleSheet("QListWidget { background: transparent; }"
                               "QListWidget::item { padding: 0; margin: 0; }")
            self.itemClicked.connect(self._add)

        def mimeData(self, items):
            from NodeGraphQt.constants import MIME_TYPE, URN_SCHEME
            urn = URN_SCHEME + ";".join(
                i.data(QtCore.Qt.ItemDataRole.UserRole) for i in items)
            md = QtCore.QMimeData()
            md.setData(MIME_TYPE, QtCore.QByteArray(urn.encode()))
            return md

        def _add(self, item):
            view = self.graph.viewer()
            c = view.mapToScene(view.viewport().rect().center())
            self.graph.create_node(item.data(QtCore.Qt.ItemDataRole.UserRole),
                                   pos=[c.x(), c.y()])

        def fit_height(self):
            n = sum(not self.item(i).isHidden() for i in range(self.count()))
            per_row = max(1, (self.viewport().width() or 120) // 30)
            rows = -(-n // per_row)
            self.setFixedHeight(rows * 30 + 4 if n else 0)

    class NodePalette(QtWidgets.QWidget):
        def __init__(self, graph, parent=None):
            super().__init__(parent)
            self.setMinimumWidth(130)
            self.setMaximumWidth(260)
            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(4, 4, 4, 4)
            lay.setSpacing(2)
            self.search = QtWidgets.QLineEdit()
            self.search.setPlaceholderText("Suchen …")
            self.search.setClearButtonEnabled(True)
            self.search.textChanged.connect(self._filter)
            lay.addWidget(self.search)
            scroll = QtWidgets.QScrollArea()
            scroll.setWidgetResizable(True)
            scroll.setFrameShape(QtWidgets.QFrame.Shape.NoFrame)
            scroll.setHorizontalScrollBarPolicy(
                QtCore.Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
            inner = QtWidgets.QWidget()
            col = QtWidgets.QVBoxLayout(inner)
            col.setContentsMargins(0, 0, 0, 0)
            col.setSpacing(0)
            self.sections = []
            for ident, label, color in CATEGORIES:
                classes = [c for c in NODE_CLASSES
                           if c.__identifier__ == ident]
                if not classes:
                    continue
                head = QtWidgets.QLabel(label.upper())
                head.setStyleSheet(
                    f"color: {color}; font-size: 9px; font-weight: bold;"
                    " padding: 6px 0 1px 2px; letter-spacing: 1px;")
                grid = IconGrid(graph)
                for cls in classes:
                    it = QtWidgets.QListWidgetItem(node_icon(cls, color), "")
                    it.setData(QtCore.Qt.ItemDataRole.UserRole,
                               f"{cls.__identifier__}.{cls.__name__}")
                    it.setToolTip(f"<b>{cls.NODE_NAME}</b><br>{label}")
                    it.setSizeHint(QtCore.QSize(30, 30))
                    grid.addItem(it)
                col.addWidget(head)
                col.addWidget(grid)
                self.sections.append((head, grid, classes))
            col.addStretch(1)
            scroll.setWidget(inner)
            lay.addWidget(scroll)
            QtCore.QTimer.singleShot(0, self._fit)

        def resizeEvent(self, ev):
            super().resizeEvent(ev)
            self._fit()

        def _fit(self):
            for _h, grid, _c in self.sections:
                grid.fit_height()

        def _filter(self, text):
            t = text.strip().lower()
            for head, grid, classes in self.sections:
                shown = 0
                for i, cls in enumerate(classes):
                    hit = not t or t in cls.NODE_NAME.lower()
                    grid.item(i).setHidden(not hit)
                    shown += hit
                head.setVisible(shown > 0)
                grid.setVisible(shown > 0)
            self._fit()

    class NodePanel(QtWidgets.QWidget):
        def __init__(self, host):
            super().__init__()
            PANELS.append(self)
            self.host = host
            self.cache: dict = {}
            self.meshes: dict = {}
            self.dirty: set = set()
            self.full = True
            self.preview_on = True
            self.path = None

            self.graph = NodeGraph()
            self.graph.register_nodes(NODE_CLASSES)

            bar = QtWidgets.QToolBar()
            for label, fn in (("Neu", self.new), ("Öffnen…", self.open),
                              ("Speichern…", self.save),
                              ("Bake", self.bake),
                              ("Alles zeigen", self.fit)):
                bar.addAction(label, fn)
            examples = QtWidgets.QToolButton()
            examples.setText("Beispiele")
            examples.setPopupMode(
                QtWidgets.QToolButton.ToolButtonPopupMode.InstantPopup)
            menu = QtWidgets.QMenu(examples)
            ex_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                  "examples")
            for f in sorted(os.listdir(ex_dir)) if os.path.isdir(ex_dir) else []:
                if f.endswith(".json"):
                    menu.addAction(f[:-5].replace("_", " "),
                                   lambda p=os.path.join(ex_dir, f):
                                   self.load_and_fit(p))
            examples.setMenu(menu)
            bar.addWidget(examples)
            self.preview_action = bar.addAction("Vorschau")
            self.preview_action.setCheckable(True)
            self.preview_action.setChecked(True)
            self.preview_action.toggled.connect(self.set_preview)
            self.status = QtWidgets.QLabel("")
            spacer = QtWidgets.QWidget()
            spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                                 QtWidgets.QSizePolicy.Policy.Preferred)
            bar.addWidget(spacer)
            bar.addWidget(self.status)

            palette = NodePalette(self.graph, self)
            split = QtWidgets.QSplitter()
            split.addWidget(palette)
            split.addWidget(self.graph.widget)
            split.setSizes([150, 1000])
            split.setStretchFactor(1, 1)

            lay = QtWidgets.QVBoxLayout(self)
            lay.setContentsMargins(0, 0, 0, 0)
            lay.setSpacing(0)
            lay.addWidget(bar)
            lay.addWidget(split)

            ctxw = QtCore.Qt.ShortcutContext.WidgetWithChildrenShortcut
            for keys, fn in (
                    ("Delete", self.delete_selected),
                    ("Backspace", self.delete_selected),
                    ("Ctrl+C", self.graph.copy_nodes),
                    ("Ctrl+V", self.graph.paste_nodes),
                    ("Ctrl+D", self.duplicate),
                    ("Ctrl+Z", lambda: self.graph.undo_stack().undo()),
                    ("Ctrl+Shift+Z", lambda: self.graph.undo_stack().redo()),
                    ("F", self.fit)):
                sc = QtGui.QShortcut(QtGui.QKeySequence(keys),
                                     self.graph.widget)
                sc.setContext(ctxw)
                sc.activated.connect(fn)

            self.links = QtCore.QTimer(self)
            self.links.timeout.connect(self.poll_links)
            self.links.start(1500)

            self.timer = QtCore.QTimer(self)
            self.timer.setSingleShot(True)
            self.timer.setInterval(30)
            self.timer.timeout.connect(self.evaluate)

            g = self.graph
            g.property_changed.connect(self._on_prop)
            g.port_connected.connect(lambda i, o: self.touch(i.node()))
            g.port_disconnected.connect(lambda i, o: self.touch(i.node()))
            g.node_created.connect(self.touch)
            g.nodes_deleted.connect(lambda ids: self.touch_all())
            g.node_selection_changed.connect(
                lambda s, d: self.update_preview())

        # -- Änderungen

        def poll_links(self):
            for node in self.graph.all_nodes():
                if isinstance(node, HolenNode):
                    node.refresh(self)

        def _on_prop(self, node, name, value):
            if name not in IGNORED_PROPS:
                self.touch(node)

        def touch(self, node):
            self.dirty.add(node.id)
            self.timer.start()

        def touch_all(self):
            self.full = True
            self.timer.start()

        def downstream(self, ids):
            seen, todo = set(ids), list(ids)
            while todo:
                node = self.graph.get_node_by_id(todo.pop())
                if node is None:
                    continue
                for port in node.output_ports():
                    for p in port.connected_ports():
                        nid = p.node().id
                        if nid not in seen:
                            seen.add(nid)
                            todo.append(nid)
            return seen

        def order(self):
            nodes = [n for n in self.graph.all_nodes()
                     if isinstance(n, SerpNode)]
            deps = {n.id: {p.node().id for port in n.input_ports()
                           for p in port.connected_ports()} for n in nodes}
            by_id = {n.id: n for n in nodes}
            done, out = set(), []
            while len(out) < len(nodes):
                ready = [i for i in by_id if i not in done
                         and deps[i] <= done]
                if not ready:       # Zyklus: Rest ignorieren
                    break
                for i in ready:
                    done.add(i)
                    out.append(by_id[i])
            return out

        # -- Rechnen

        def evaluate(self):
            t0 = time.perf_counter()
            if self.full:
                stale = {n.id for n in self.graph.all_nodes()}
                self.cache.clear()
                self.meshes.clear()
            else:
                stale = self.downstream(self.dirty)
            self.full = False
            self.dirty.clear()
            errors = computed = 0
            for node in self.order():
                if node.id not in stale and node.id in self.cache:
                    continue
                computed += 1
                self.meshes.pop(node.id, None)
                outs = {name: None for name in node.OUTPUTS}
                try:
                    inputs, missing = self.gather(node)
                    if missing:
                        node.mark("warn", "Eingang fehlt: " + ", ".join(missing))
                    else:
                        outs = node.compute(inputs)
                        node.mark("ok")
                except Hinweis as exc:
                    node.mark("warn", str(exc))
                except Exception as exc:        # noqa: BLE001
                    errors += 1
                    node.mark("error", f"{type(exc).__name__}: {exc}")
                    traceback.print_exc()
                self.cache[node.id] = outs
            ms = (time.perf_counter() - t0) * 1000
            if computed:
                self.status.setText(f"{computed} Nodes · {ms:.0f} ms" + (
                    f" · {errors} Fehler" if errors else ""))
            self.update_preview()

        def gather(self, node):
            inputs, missing = {}, []
            for name, kind, default, whole in node.INPUTS:
                port = node.get_input(name)
                sources = port.connected_ports()
                if sources:
                    vals = [self.cache.get(p.node().id, {}).get(p.name())
                            for p in sources]
                    if any(v is None for v in vals):
                        missing.append(name)
                        continue
                    value = Tree.merge(vals)
                    if kind in COERCE:
                        value = Tree({p: [COERCE[kind](v) for v in items]
                                      for p, items in value.b.items()})
                elif default is not None:
                    value = Tree.of(parse(kind,
                                          node.get_property("in_" + name)))
                elif name in getattr(node, "OPTIONAL", ()):
                    value = Tree()
                else:
                    missing.append(name)
                    continue
                inputs[name] = value
            return inputs, missing

        # -- Vorschau

        def preview_nodes(self):
            sel = {n.id for n in self.graph.selected_nodes()}
            out = []
            for node in self.order():
                # Anzeige und Export verarbeiten nicht weiter: wer nur in
                # die führt, ist trotzdem ein Ende des Graphen
                leaf = not any(not getattr(p.node(), "SINK", False)
                               for port in node.output_ports()
                               for p in port.connected_ports())
                if leaf or node.id in sel:
                    out.append(node)
            return out

        def preview_items(self):
            for node in self.preview_nodes():
                warn = getattr(node, "WARN_OUTPUTS", ())
                for name, value in self.cache.get(node.id, {}).items():
                    if value is None:
                        continue
                    for item in value.items():
                        if is_point(item) or is_shape(item):
                            yield node, item, name in warn

        def update_preview(self):
            import numpy as np
            if not self.preview_on:
                self.host.show(None, [])
                return
            # zwei Kanäle des Overlays: grün = Ergebnis, rot = Warnung
            chans = {False: ([], [], []), True: ([], [], [])}
            for node, item, warn in self.preview_items():
                tris, segs, pts = chans[warn]
                if is_point(item):
                    pts.append(np.asarray([item], np.float32))
                    continue
                meshes = self.meshes.setdefault(node.id, {})
                mesh = meshes.get(id(item))
                if mesh is None:
                    mesh = meshes[id(item)] = (item, tessellate(item))
                m = mesh[1]
                if len(m.triangles):
                    tris.append(m.vertices[m.triangles.ravel()])
                if len(m.edge_segments):
                    segs.append(m.edge_segments.reshape(-1, 3))
                if len(m.points):
                    pts.append(m.points)
            join = (lambda a: np.concatenate(a).astype(np.float32) if a
                    else np.empty((0, 3), np.float32))
            chans = tuple(tuple(join(a) for a in chans[w])
                          for w in (False, True))
            self.host.show(chans, self.result_items())

        def result_items(self):
            """(Name, Geometrie) der Vorschau ohne Warnungen — fürs Ziel."""
            return [(node.name(), item) for node, item, warn
                    in self.preview_items() if not warn]

        def set_preview(self, on):
            self.preview_on = on
            self.update_preview()

        # -- Aktionen

        def bake(self):
            items = self.result_items()
            if not items:
                self.status.setText("Nichts zu baken")
                return
            try:
                self.status.setText(self.host.bake(items))
            except Exception as exc:            # noqa: BLE001
                traceback.print_exc()
                self.status.setText(f"Bake fehlgeschlagen: {exc}")

        def delete_selected(self):
            self.graph.delete_nodes(self.graph.selected_nodes())

        def duplicate(self):
            self.graph.duplicate_nodes(self.graph.selected_nodes())

        def fit(self):
            """Graph und Viewports auf alles einpassen."""
            import numpy as np
            self.graph.fit_to_selection()
            pts = []
            for node in self.preview_nodes():
                for _item, m in self.meshes.get(node.id, {}).values():
                    for arr in (m.vertices, m.edge_segments.reshape(-1, 3),
                                m.points):
                        if len(arr):
                            pts.append(np.asarray(arr, float))
            if not pts:
                return
            allp = np.concatenate(pts)
            self.host.fit(allp.min(axis=0), allp.max(axis=0))

        def new(self):
            self.graph.clear_session()
            self.path = None
            self.touch_all()

        def load(self, path):
            self.graph.load_session(path)
            for node in self.graph.all_nodes():
                if hasattr(node, "_apply_range"):   # Laden umgeht set_property
                    node._apply_range()
                for port in node.input_ports():
                    if port.connected_ports():
                        node._enable_default(port.name(), False)
            self.path = path
            self.touch_all()

        def load_and_fit(self, path):
            self.load(path)
            self.evaluate()
            QtCore.QTimer.singleShot(200, self.fit)

        def open(self):
            path, _ = QtWidgets.QFileDialog.getOpenFileName(
                self, "Node-Graph öffnen", self.path or os.path.expanduser("~"),
                "Node-Graph (*.json)")
            if path:
                self.load(path)

        def save(self):
            path, _ = QtWidgets.QFileDialog.getSaveFileName(
                self, "Node-Graph speichern",
                self.path or os.path.expanduser("~/graph.json"),
                "Node-Graph (*.json)")
            if path:
                self.graph.save_session(path)
                self.path = path

    NodePanel.NODE_CLASSES = NODE_CLASSES
    NodePanel.CATEGORIES = CATEGORIES
    return NodePanel


def build(ctx):
    """Einbau als Dock in Serpentine3D, dazu die Brücke für die Node-App."""
    from PySide6 import QtCore, QtWidgets
    from . import hosts
    NodePanel = make_core()
    window = ctx.window
    host = hosts.SerpentineHost(window)
    panel = NodePanel(host)
    window._serp_nodes_bridge = hosts.Bridge(window, host)
    dock = QtWidgets.QDockWidget("SolidNode", window)
    dock.setObjectName("serp_nodes_dock")
    dock.setWidget(panel)
    window.addDockWidget(QtCore.Qt.DockWidgetArea.BottomDockWidgetArea, dock)
    dock.hide()

    def show_dock():
        # eigenes Fenster wie bei Grasshopper; andocken per Doppelklick
        # auf die Titelleiste
        if not dock.isVisible():
            if not getattr(dock, "_placed", False):
                dock.setFloating(True)
                geo_ = window.geometry()
                dock.resize(int(geo_.width() * 0.75),
                            int(geo_.height() * 0.6))
                dock.move(geo_.x() + geo_.width() // 8,
                          geo_.y() + geo_.height() // 3)
                dock._placed = True
            dock.show()
        dock.raise_()

    def toggle():
        if dock.isVisible():
            dock.hide()
        else:
            show_dock()

    ctx.add_menu_action("SolidNode", toggle)
    base = ctx.requests()

    @ctx.command("nodes", mutates=False)
    def cmd_nodes(c):
        toggle()
        c.echo("Node-Editor " + ("offen" if dock.isVisible() else "zu"))
        return
        yield

    @ctx.command("nodesload", mutates=False)
    def cmd_nodesload(c):
        path = yield base.TextReq("Node-Graph (.json)")
        show_dock()
        panel.load(os.path.expanduser(path))
        panel.evaluate()
        QtWidgets.QApplication.processEvents()
        panel.fit()
        c.echo(f"Geladen: {path} · {panel.status.text()}")

    @ctx.command("nodesbake", mutates=False)
    def cmd_nodesbake(c):
        panel.bake()
        c.echo(panel.status.text())
        return
        yield

    @ctx.command("nodesbild", mutates=False)
    def cmd_nodesbild(c):
        path = yield base.TextReq("PNG-Pfad")
        QtWidgets.QApplication.processEvents()
        path = os.path.expanduser(path)
        window.grab().save(path)
        if dock.isVisible() and dock.isFloating():
            dock.grab().save(path.replace(".png", "_nodes.png"))
        c.echo(f"Bild: {path}")

    window._serp_nodes = panel
    return panel


def serpentine3d_plugin(ctx):
    if ctx.window is None:
        return
    build(ctx)
