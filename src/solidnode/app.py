"""Node-Editor als eigene App, mit eigener 3D-Vorschau.

Arbeitet wahlweise mit Serpentine3D (über die Plugin-Brücke) oder
SolidCraft (Steuerport 7878) zusammen, oder nur für sich.

Start: solidnode
Optionen:
  --laden graph.json      Graph beim Start laden
  --ziel auto|vorschau|serpentine|solidcraft
  --solidcraft-headless   zum Testen: eigene unsichtbare SolidCraft-Instanz
  --skript datei.py       nach dem Start ausführen (Tests); sieht app, win
"""

from __future__ import annotations

import os
import sys
import time
import traceback

os.environ.setdefault("QT_API", "pyside6")
import numpy as np                                        # noqa: E402
from PySide6 import QtCore, QtGui, QtWidgets              # noqa: E402

from . import hosts, update                               # noqa: E402



# ------------------------------------------------------------ 3D-Vorschau

class Viewer(QtWidgets.QWidget):
    """Serpentine3Ds eigener Viewport mit leerer Szene: zeigt chans als
    Overlay (grün/rot), genau wie im Plugin."""

    def __init__(self):
        super().__init__()
        from serpentine3d.core.scene import Scene
        from serpentine3d.core.selection import SelectionManager
        from serpentine3d.ui.viewport import Viewport
        self.scene = Scene()
        self.scene.script_preview = None
        self.vp = Viewport(self.scene, SelectionManager(self.scene))
        lay = QtWidgets.QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.addWidget(self.vp)
        self._fitted = False
        self._chans = None

    def show_chans(self, chans):
        self._chans = chans
        self.scene.script_preview = chans
        if chans is not None and not self._fitted and any(
                len(a) for ch in chans for a in ch):
            QtCore.QTimer.singleShot(50, self.fit)
        self.vp.update()

    def fit(self, lo=None, hi=None):
        if lo is None:
            if self._chans is None:
                return
            pts = [np.asarray(a, float) for ch in self._chans for a in ch
                   if len(a)]
            if not pts:
                return
            allp = np.concatenate(pts)
            lo, hi = allp.min(axis=0), allp.max(axis=0)
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        pad = (hi - lo) * 0.15 + 1.0
        self.vp.zoom_to_points(lo - pad, hi + pad)
        self._fitted = True
        self.vp.update()

    def save(self, path):
        self.vp.grabFramebuffer().save(path)


# ---------------------------------------------------------------- Weiche

class Router(hosts.Host):
    """Eigene Vorschau immer, dazu das gewählte Ziel."""

    def __init__(self, viewer, serpentine, solidcraft, report):
        self.viewer = viewer
        self.serp = serpentine
        self.sc = solidcraft
        self.report = report
        self.target = None            # None | serp | sc
        self.last = (None, [])

    def show(self, chans, items):
        self.last = (chans, items)
        self.viewer.show_chans(chans)
        t = self.target
        try:
            if t is not None:
                t.show(chans, items)
        except Exception as exc:              # noqa: BLE001
            self.report(f"{t.name}: {exc}")

    def bake(self, items):
        if self.target is None:
            return self.bake_file(items)
        return self.target.bake(items)

    def bake_file(self, items):
        path, _ = QtWidgets.QFileDialog.getSaveFileName(
            None, "Ergebnis speichern", os.path.expanduser("~/Desktop/nodes.step"),
            "STEP (*.step);;3MF (*.3mf);;STL (*.stl)")
        if not path:
            return "Bake abgebrochen"
        from serpentine3d.core.mesh import MeshShape
        shapes = [hosts.as_shape(i) for _n, i in items]
        ext = os.path.splitext(path)[1].lower()
        named = [(n, s) for (n, _i), s in zip(items, shapes)]
        if ext == ".step":
            from serpentine3d.fileio.step import export_step
            export_step([s for s in shapes if not isinstance(s, MeshShape)],
                        path)
        elif ext == ".3mf":
            from serpentine3d.fileio.threemf import export_3mf
            export_3mf(named, path)
        else:
            from serpentine3d.fileio.stl import export_stl
            export_stl(named, path)
        return f"gespeichert: {path}"

    def fit(self, lo, hi):
        self.viewer.fit(lo, hi)
        if self.target is self.serp:
            try:
                self.serp.fit(lo, hi)
            except Exception:                 # noqa: BLE001
                pass

    # Geometrie aus dem CAD holen: an das aktuelle Ziel weiterreichen
    def pick(self):
        if self.target is None:
            raise RuntimeError("Kein CAD-Programm als Ziel verbunden")
        return self.target.pick()

    def refetch(self, refs):
        src = {"serpentine": self.serp, "solidcraft": self.sc}
        host = src.get(refs[0].get("src")) if refs else None
        if host is None:
            raise RuntimeError("Quelle unbekannt")
        return host.refetch(refs)

    def revision(self, src=None):
        host = {"serpentine": self.serp, "solidcraft": self.sc}.get(src)
        if host is None:
            return None
        if host is self.serp and not self.serp.available():
            return None
        if host is self.sc and not self.sc.available():
            return None
        return host.revision()

    def set_target(self, target):
        if target is self.target:
            return
        old = self.target
        self.target = target
        if old is self.serp:
            self.serp.clear()
        if target is not None and self.last[0] is not None:
            self.show(*self.last)


# ------------------------------------------------------------------ App

class Main(QtWidgets.QMainWindow):
    CHOICES = ["Automatisch", "Nur Vorschau", "Serpentine3D", "SolidCraft"]

    def __init__(self, args):
        super().__init__()
        self.setWindowTitle("SolidNode")
        self.resize(1500, 900)
        from . import core
        NodePanel = core.make_core()

        self.viewer = Viewer()
        sc_args = ["--headless"] if args.get("solidcraft_headless") else None
        self.serp = hosts.SerpentineRemote()
        self.sc = hosts.SolidCraftHost(sc_args)
        self.router = Router(self.viewer, self.serp, self.sc, self.message)
        self.panel = NodePanel(self.router)

        # oben Vorschau, unten Nodes
        split = QtWidgets.QSplitter(QtCore.Qt.Orientation.Vertical)
        split.addWidget(self.viewer)
        split.addWidget(self.panel)
        split.setSizes([450, 450])
        self.setCentralWidget(split)

        bar = QtWidgets.QToolBar("Ziel")
        bar.setMovable(False)
        self.addToolBar(QtCore.Qt.ToolBarArea.TopToolBarArea, bar)
        bar.addWidget(QtWidgets.QLabel(" Ziel: "))
        self.choice = QtWidgets.QComboBox()
        self.choice.addItems(self.CHOICES)
        self.choice.currentIndexChanged.connect(lambda _i: self.poll())
        bar.addWidget(self.choice)
        self.active = QtWidgets.QLabel("")
        bar.addWidget(self.active)
        bar.addSeparator()
        self.dot_serp = QtWidgets.QLabel()
        self.dot_sc = QtWidgets.QLabel()
        bar.addWidget(self.dot_serp)
        bar.addWidget(self.dot_sc)
        bar.addSeparator()
        self.live = QtWidgets.QCheckBox("live in SolidCraft")
        self.live.toggled.connect(self._live)
        bar.addWidget(self.live)
        self.send_btn = bar.addAction("An SolidCraft senden", self.send)
        self.rm_btn = bar.addAction("Vorschau dort entfernen",
                                    lambda: self.sc.remove_preview())
        self.start_btn = bar.addAction("SolidCraft starten",
                                       lambda: self.message(
                                           hosts.start_solidcraft()))
        spacer = QtWidgets.QWidget()
        spacer.setSizePolicy(QtWidgets.QSizePolicy.Policy.Expanding,
                             QtWidgets.QSizePolicy.Policy.Preferred)
        bar.addWidget(spacer)
        self.msg = QtWidgets.QLabel("")
        bar.addWidget(self.msg)
        self.update_btn = QtWidgets.QToolButton()
        self.update_btn.setStyleSheet(
            "QToolButton { background: #c9832c; color: white; border-radius: 3px;"
            " padding: 2px 8px; font-weight: bold; }"
            "QToolButton:disabled { background: #6b5536; color: #ddd; }")
        self.update_btn.clicked.connect(self.run_update)
        self.update_act = bar.addWidget(self.update_btn)
        self.update_act.setVisible(False)
        self.remote_version = None
        self.update_proc = None
        self.checker = UpdateCheck(self)
        self.checker.found.connect(self.offer_update)
        self.checker.start()

        self.serp_pid = None
        self.sc_ok = False
        self.last_front = None          # "serp" | "sc"
        self.timer = QtCore.QTimer(self)
        self.timer.timeout.connect(self.poll)
        self.timer.start(1500)
        want = {"auto": 0, "vorschau": 1, "serpentine": 2,
                "solidcraft": 3}.get(args.get("ziel", "auto"), 0)
        self.choice.setCurrentIndex(want)
        self.poll()

    # -- Erkennung

    def poll(self):
        self.serp_pid = self.serp.available()
        self.sc_ok = bool(self.sc.available())
        sc_pid = hosts.solidcraft_pid()
        front = hosts.frontmost_pid()
        if front is not None and front != os.getpid():
            if self.serp_pid and front == self.serp_pid:
                self.last_front = "serp"
            elif sc_pid and front == sc_pid:
                self.last_front = "sc"
        self.start_btn.setVisible(not self.sc_ok)
        on, off = "●", "○"
        self.dot_serp.setText(f" {on if self.serp_pid else off} Serpentine3D ")
        self.dot_sc.setText(f" {on if self.sc_ok else off} SolidCraft ")
        for lbl, ok in ((self.dot_serp, self.serp_pid), (self.dot_sc,
                                                          self.sc_ok)):
            lbl.setStyleSheet(f"color: {'#6fdcab' if ok else '#777'}")
        mode = self.choice.currentIndex()
        if mode == 0:
            avail = [k for k, ok in (("serp", self.serp_pid),
                                     ("sc", self.sc_ok)) if ok]
            if len(avail) == 2 and self.last_front in avail:
                pick = self.last_front
            else:
                pick = avail[0] if avail else None
        else:
            pick = {1: None, 2: "serp", 3: "sc"}[mode]
            if (pick == "serp" and not self.serp_pid) or (
                    pick == "sc" and not self.sc_ok):
                self.active.setText(" (nicht erreichbar)")
                self.router.set_target(None)
                self._buttons(None)
                return
        target = {"serp": self.serp, "sc": self.sc, None: None}[pick]
        self.router.set_target(target)
        self.active.setText(f" → {target.name if target else 'nur Vorschau'}")
        self._buttons(pick)
        if self.sc.status and pick == "sc":
            self.msg.setText(self.sc.status + "  ")

    def _buttons(self, pick):
        is_sc = pick == "sc"
        self.live.setEnabled(is_sc)
        self.send_btn.setEnabled(is_sc)
        self.rm_btn.setEnabled(is_sc)
        self.sc.live = is_sc and self.live.isChecked()

    def _live(self, on):
        self.sc.live = on and self.router.target is self.sc
        if self.sc.live:
            self.send()

    def send(self):
        self.message("SolidCraft: sende …")
        self.sc.send()

    # -- Update

    def offer_update(self, remote):
        self.remote_version = remote
        self.update_btn.setText(f"Update auf {remote}")
        self.update_btn.setToolTip(
            f"Installiert ist {update.__version__}, auf GitHub gibt es "
            f"{remote}.\nKlick installiert das Update und startet neu.")
        self.update_act.setVisible(True)

    def run_update(self):
        what, prog, args, cwd = update.plan()
        self.update_btn.setEnabled(False)
        self.update_btn.setText("Update läuft …")
        self.message(f"Update per {what} …")
        proc = self.update_proc = QtCore.QProcess(self)
        proc.setProcessChannelMode(
            QtCore.QProcess.ProcessChannelMode.MergedChannels)
        if cwd:
            proc.setWorkingDirectory(cwd)
        proc.finished.connect(self._update_done)
        proc.errorOccurred.connect(lambda _e: self._update_done(-1, None))
        proc.start(prog, args)

    def _update_done(self, code, _status):
        proc, self.update_proc = self.update_proc, None
        if proc is None:                      # errorOccurred und finished
            return
        out = bytes(proc.readAll()).decode("utf-8", "replace").strip()
        if code != 0:
            self.update_btn.setEnabled(True)
            self.update_btn.setText(f"Update auf {self.remote_version}")
            self.message("Update fehlgeschlagen")
            box = QtWidgets.QMessageBox(self)
            box.setIcon(QtWidgets.QMessageBox.Icon.Warning)
            box.setWindowTitle("Update fehlgeschlagen")
            box.setText("Das Update ließ sich nicht installieren.")
            box.setDetailedText(out[-4000:] or proc.errorString())
            box.exec()
            return
        self.update_btn.setText("Update installiert")
        self.message(f"Update auf {self.remote_version} installiert")
        ask = QtWidgets.QMessageBox.question(
            self, "Update installiert",
            f"SolidNode {self.remote_version} ist installiert.\n"
            "Jetzt neu starten? Der offene Graph wird mitgenommen.")
        if ask == QtWidgets.QMessageBox.StandardButton.Yes:
            self.restart()

    def restart(self):
        os.makedirs(hosts.STATE, exist_ok=True)
        keep = os.path.join(hosts.STATE, "vor_update.json")
        self.panel.graph.save_session(keep)
        prog, args = update.restart_command()
        clean, skip = [], False
        for a in args:                        # altes --laden ersetzen
            if skip:
                skip = False
            elif a == "--laden":
                skip = True
            else:
                clean.append(a)
        QtCore.QProcess.startDetached(prog, [*clean, "--laden", keep])
        QtWidgets.QApplication.quit()

    def message(self, text):
        self.msg.setText(text + "  ")

    def closeEvent(self, ev):
        self.serp.clear()
        super().closeEvent(ev)


class UpdateCheck(QtCore.QObject):
    """Fragt GitHub im Hintergrund nach der aktuellen Version."""
    found = QtCore.Signal(str)

    def start(self):
        import threading
        threading.Thread(target=self._run, daemon=True).start()

    def _run(self):
        remote = update.latest()
        if remote and update.newer(remote):
            self.found.emit(remote)           # Signal: landet im Qt-Thread


def parse_args(argv):
    out, i = {}, 1
    while i < len(argv):
        a = argv[i]
        if a == "--laden":
            out["laden"] = argv[i + 1]
            i += 1
        elif a == "--ziel":
            out["ziel"] = argv[i + 1]
            i += 1
        elif a == "--skript":
            out["skript"] = argv[i + 1]
            i += 1
        elif a == "--solidcraft-headless":
            out["solidcraft_headless"] = True
        i += 1
    return out


def main():
    args = parse_args(sys.argv)
    # STEP-Statistik von OpenCASCADE nicht bei jedem Senden ins Terminal
    from OCP.Message import Message
    Message.DefaultMessenger_s().ChangePrinters().Clear()
    # wie Serpentine3Ds Starter: GL-Format vor der QApplication setzen
    from serpentine3d.utils.glsetup import match_pyopengl_to_qt, \
        set_default_gl_format
    set_default_gl_format()
    app = QtWidgets.QApplication(sys.argv)
    match_pyopengl_to_qt()
    app.setApplicationName("SolidNode")
    win = Main(args)
    win.show()
    if args.get("laden"):
        win.panel.load(os.path.expanduser(args["laden"]))
        win.panel.evaluate()
        QtCore.QTimer.singleShot(300, win.panel.fit)
    if args.get("skript"):
        def run():
            try:
                exec(open(args["skript"]).read(),
                     {"app": app, "win": win, "hosts": hosts, "np": np,
                      "time": time, "QtCore": QtCore, "QtWidgets": QtWidgets})
            except Exception:                 # noqa: BLE001
                traceback.print_exc()
        QtCore.QTimer.singleShot(800, run)
    sys.exit(app.exec())


if __name__ == "__main__":
    main()
