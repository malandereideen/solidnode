"""Ziele für den Node-Editor: wohin Vorschau und Bake gehen.

- SerpentineHost: im Serpentine3D-Prozess (Plugin-Dock).
- Bridge: kleiner TCP-Server im Serpentine3D-Plugin, über den die
  eigenständige Node-App Vorschau und Bake in Serpentine3D schickt.
- SerpentineRemote: die Gegenseite der Brücke, für die Node-App.
- SolidCraftHost: spricht per `solidcraft-cli mcp` mit der laufenden App
  (Steuerport 7878) und legt Geometrie als Komponente ins offene Design.

Die Vorschau kommt als `chans`: ((dreiecke, segmente, punkte) grün,
(…) rot) — dieselbe Form wie Serpentine3Ds script_preview.
"""

from __future__ import annotations

import json
import os
import socket
import subprocess
import time

import numpy as np

STATE = os.path.expanduser("~/.solidnode")
UEBERGABE = os.path.join(STATE, "transfer")
BRIDGE_FILE = os.path.expanduser("~/.serpentine3d/nodes-bridge.json")
SOLIDCRAFT_PORT = int(os.environ.get("SOLIDNODE_SOLIDCRAFT_PORT", "7878"))


def solidcraft_cli():
    """Pfad zu solidcraft-cli: Umgebungsvariable, PATH oder App-Bundle."""
    import shutil
    import sys
    env = os.environ.get("SOLIDNODE_SOLIDCRAFT_CLI")
    if env:
        return env
    found = shutil.which("solidcraft-cli")
    if found:
        return found
    for cand in ("/Applications/SolidCraft.app/Contents/MacOS/solidcraft-cli",
                 os.path.expanduser("~/Applications/SolidCraft.app/Contents/"
                                    "MacOS/solidcraft-cli"),
                 r"C:\Program Files\SolidCraft\solidcraft-cli.exe"):
        if os.path.exists(cand):
            return cand
    if sys.platform == "win32":
        return "solidcraft-cli.exe"
    return "solidcraft-cli"


def start_solidcraft():
    """SolidCraft mit Steuerport starten. Gibt eine Meldung zurück."""
    import sys
    port = str(SOLIDCRAFT_PORT)
    try:
        if sys.platform == "darwin":
            subprocess.Popen(["open", "-n", "-a", "SolidCraft", "--args",
                              "--control", port])
        else:
            exe = os.environ.get("SOLIDNODE_SOLIDCRAFT_APP") or (
                "SolidCraft.exe" if sys.platform == "win32" else "solidcraft")
            subprocess.Popen([exe, "--control", port])
    except OSError as exc:
        return f"SolidCraft ließ sich nicht starten: {exc}"
    return f"SolidCraft startet mit Steuerport {port} …"


def empty_chans():
    e = np.empty((0, 3), np.float32)
    return ((e, e, e), (e, e, e))


class Host:
    name = "Nur Vorschau"

    def show(self, chans, items):
        """chans None = Vorschau aus. items: [(name, geometrie)]."""

    def bake(self, items) -> str:
        return "Dieses Ziel kann nicht baken"

    def fit(self, lo, hi):
        pass

    # Geometrie aus dem CAD holen: [(ref, name, form)]
    def pick(self):
        raise RuntimeError("Kein CAD-Programm verbunden")

    def refetch(self, refs):
        raise RuntimeError("Kein CAD-Programm verbunden")

    def revision(self, src=None):
        return None


# ------------------------------------------------------- Geometrie-Transport

def encode_shape(shape):
    """Form als Text (für die Kopie im Graph)."""
    import base64
    import tempfile
    from serpentine3d.core.mesh import MeshShape
    with tempfile.TemporaryDirectory() as d:
        path = write_shape(os.path.join(d, "s"), shape)
        with open(path, "rb") as f:
            data = base64.b64encode(f.read()).decode()
    kind = "mesh" if isinstance(shape, MeshShape) else "brep"
    return {"kind": kind, "data": data}


def decode_shape(entry):
    import base64
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        path = os.path.join(d, "s." + ("npz" if entry["kind"] == "mesh"
                                       else "brep"))
        with open(path, "wb") as f:
            f.write(base64.b64decode(entry["data"]))
        return read_shape(path)

def write_shape(path_base, shape):
    """Form in eine Datei, die die andere Seite wieder lesen kann."""
    from serpentine3d.core.mesh import MeshShape
    if isinstance(shape, MeshShape):
        path = path_base + ".npz"
        np.savez(path, v=shape.vertices, t=shape.triangles)
        return path
    from OCP.BRepTools import BRepTools
    path = path_base + ".brep"
    BRepTools.Write_s(shape, path)
    return path


def read_shape(path):
    from serpentine3d.core.mesh import MeshShape
    if path.endswith(".npz"):
        d = np.load(path)
        return MeshShape(d["v"], d["t"])
    from OCP.BRep import BRep_Builder
    from OCP.BRepTools import BRepTools
    from OCP.TopoDS import TopoDS_Shape
    s = TopoDS_Shape()
    BRepTools.Read_s(s, path, BRep_Builder())
    return s


def as_shape(item):
    from serpentine3d.core import geometry as geo
    if isinstance(item, tuple):
        return geo.make_point(item)
    return item


# ------------------------------------------------- Serpentine3D, im Prozess

def add_to_scene(window, items, layer_name="Nodes"):
    scene = window.scene
    window.history.checkpoint("Nodes: Bake")
    layer = (scene.layers.find_by_name(layer_name)
             or scene.layers.create(layer_name))
    for name, item in items:
        scene.add(as_shape(item), name=name, layer_id=layer.id)
    for vp in window.all_viewports():
        vp.update()
    return f"{len(items)} Objekt(e) in Serpentine3D gebaked"


class SerpentineHost(Host):
    name = "Serpentine3D"

    def __init__(self, window):
        self.window = window

    def show(self, chans, items):
        self.window.scene.script_preview = chans
        for vp in self.window.all_viewports():
            vp.update()

    def bake(self, items):
        return add_to_scene(self.window, items)

    def fit(self, lo, hi):
        lo, hi = np.asarray(lo, float), np.asarray(hi, float)
        pad = (hi - lo) * 0.15
        for vp in self.window.all_viewports():
            if getattr(vp, "space", "model") == "model":
                vp.zoom_to_points(lo - pad, hi + pad)

    def pick(self):
        objs = self.window.selection.objects()
        if not objs:
            raise RuntimeError("In Serpentine3D ist nichts ausgewählt")
        return [({"src": "serpentine", "id": o.id}, o.name, o.shape)
                for o in objs]

    def refetch(self, refs):
        out = []
        for r in refs:
            o = self.window.scene.get(r["id"])
            if o is not None:
                out.append((r, o.name, o.shape))
        return out

    def revision(self, src=None):
        return self.window.scene.revision


class Bridge:
    """TCP-Server im Serpentine3D-Plugin (Qt-Hauptthread, Zeilen-JSON)."""

    def __init__(self, window, host):
        from PySide6.QtNetwork import QHostAddress, QTcpServer
        self.window, self.host = window, host
        self.server = QTcpServer()
        self.server.listen(QHostAddress("127.0.0.1"), 0)
        self.server.newConnection.connect(self._accept)
        os.makedirs(os.path.dirname(BRIDGE_FILE), exist_ok=True)
        with open(BRIDGE_FILE, "w", encoding="utf-8") as f:
            json.dump({"port": self.server.serverPort(), "pid": os.getpid()}, f)
        self._bufs = {}

    def _accept(self):
        while self.server.hasPendingConnections():
            conn = self.server.nextPendingConnection()
            self._bufs[conn] = b""
            conn.readyRead.connect(lambda c=conn: self._read(c))
            conn.disconnected.connect(lambda c=conn: self._bufs.pop(c, None))

    def _read(self, conn):
        self._bufs[conn] = self._bufs.get(conn, b"") + bytes(conn.readAll())
        while b"\n" in self._bufs[conn]:
            line, rest = self._bufs[conn].split(b"\n", 1)
            self._bufs[conn] = rest
            try:
                reply = {"ok": True, **(self.handle(json.loads(line)) or {})}
            except Exception as exc:              # noqa: BLE001
                reply = {"ok": False, "msg": f"{type(exc).__name__}: {exc}"}
            conn.write((json.dumps(reply) + "\n").encode())
            conn.flush()

    def handle(self, msg):
        cmd = msg["cmd"]
        if cmd == "ping":
            return {"pid": os.getpid()}
        if cmd == "preview":
            if msg.get("path") is None:
                self.host.show(None, [])
            else:
                d = np.load(msg["path"])
                chans = tuple(tuple(d[f"{w}{k}"] for k in range(3))
                              for w in ("g", "r"))
                self.host.show(chans, [])
            return {}
        if cmd == "bake":
            items = [(name, read_shape(p)) for name, p in msg["items"]]
            return {"msg": self.host.bake(items)}
        if cmd == "fit":
            self.host.fit(msg["lo"], msg["hi"])
            return {}
        if cmd in ("pick", "fetch"):
            found = (self.host.pick() if cmd == "pick"
                     else self.host.refetch(msg["refs"]))
            os.makedirs(UEBERGABE, exist_ok=True)
            items = []
            for i, (ref, name, shape) in enumerate(found):
                path = write_shape(os.path.join(UEBERGABE, f"hol_{i}"), shape)
                items.append([ref, name, path])
            return {"items": items}
        if cmd == "rev":
            return {"rev": self.host.revision()}
        raise ValueError(f"unbekannt: {cmd}")


# --------------------------------------------------- Serpentine3D, entfernt

def bridge_info():
    try:
        with open(BRIDGE_FILE, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def bridge_call(msg, timeout=5.0):
    info = bridge_info()
    if not info:
        raise ConnectionError("Serpentine3D-Brücke nicht gefunden")
    with socket.create_connection(("127.0.0.1", info["port"]), 0.3) as s:
        s.settimeout(timeout)
        s.sendall((json.dumps(msg) + "\n").encode())
        buf = b""
        while b"\n" not in buf:
            chunk = s.recv(65536)
            if not chunk:
                raise ConnectionError("Brücke hat aufgelegt")
            buf += chunk
    reply = json.loads(buf.split(b"\n", 1)[0])
    if not reply.get("ok"):
        raise RuntimeError(reply.get("msg"))
    return reply


class SerpentineRemote(Host):
    name = "Serpentine3D"

    def __init__(self):
        os.makedirs(UEBERGABE, exist_ok=True)

    def available(self):
        try:
            return bridge_call({"cmd": "ping"}, 0.5)["pid"]
        except Exception:                     # noqa: BLE001
            return None

    def show(self, chans, items):
        if chans is None:
            bridge_call({"cmd": "preview", "path": None})
            return
        path = os.path.join(UEBERGABE, "vorschau.npz")
        tmp = path + ".tmp.npz"
        np.savez(tmp, **{f"{w}{k}": chans[i][k] for i, w in enumerate("gr")
                         for k in range(3)})
        os.replace(tmp, path)
        bridge_call({"cmd": "preview", "path": path})

    def clear(self):
        try:
            bridge_call({"cmd": "preview", "path": None}, 1.0)
        except Exception:                     # noqa: BLE001
            pass

    def bake(self, items):
        files = []
        for i, (name, item) in enumerate(items):
            files.append([name, write_shape(
                os.path.join(UEBERGABE, f"bake_{i}"), as_shape(item))])
        return bridge_call({"cmd": "bake", "items": files}, 60)["msg"]

    def fit(self, lo, hi):
        bridge_call({"cmd": "fit", "lo": list(map(float, lo)),
                     "hi": list(map(float, hi))})

    def pick(self):
        r = bridge_call({"cmd": "pick"}, 60)
        return [(ref, name, read_shape(p)) for ref, name, p in r["items"]]

    def refetch(self, refs):
        r = bridge_call({"cmd": "fetch", "refs": refs}, 60)
        return [(ref, name, read_shape(p)) for ref, name, p in r["items"]]

    def revision(self, src=None):
        try:
            return bridge_call({"cmd": "rev"}, 1.0)["rev"]
        except Exception:                     # noqa: BLE001
            return None


# ------------------------------------------------------------- SolidCraft

def port_open(port, host="127.0.0.1"):
    try:
        with socket.create_connection((host, port), 0.2):
            return True
    except OSError:
        return False


def solidcraft_pid():
    import sys
    if sys.platform == "win32":
        return None
    try:
        out = subprocess.run(["pgrep", "-x", "SolidCraft"], capture_output=True,
                             text=True, timeout=2).stdout.split()
        return int(out[0]) if out else None
    except Exception:                         # noqa: BLE001
        return None


class McpClient:
    """Minimaler MCP-Client über die Standardein-/ausgabe von solidcraft-cli."""

    def __init__(self, args):
        self.p = subprocess.Popen(
            [solidcraft_cli(), "mcp", *args], stdin=subprocess.PIPE,
            stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True)
        self.i = 0
        self._rpc("initialize", {"protocolVersion": "2024-11-05",
                                 "capabilities": {},
                                 "clientInfo": {"name": "solidnode",
                                                "version": "1"}})
        self._send({"jsonrpc": "2.0", "method": "notifications/initialized"})

    def _send(self, msg):
        self.p.stdin.write(json.dumps(msg) + "\n")
        self.p.stdin.flush()

    def _rpc(self, method, params):
        self.i += 1
        self._send({"jsonrpc": "2.0", "id": self.i, "method": method,
                    "params": params})
        while True:
            line = self.p.stdout.readline()
            if not line:
                raise ConnectionError("solidcraft-cli beendet")
            msg = json.loads(line)
            if msg.get("id") == self.i:
                return msg

    def tool(self, name, args):
        r = self._rpc("tools/call", {"name": name, "arguments": args})
        if "error" in r:
            raise RuntimeError(r["error"].get("message"))
        text = r["result"]["content"][0]["text"]
        if r["result"].get("isError"):
            raise RuntimeError(text)
        return text

    def execute(self, command, params):
        return self.tool("execute", {"command": command, "params": params,
                                     "verbose": False})

    def alive(self):
        return self.p.poll() is None

    def close(self):
        if self.alive():
            self.p.kill()


def curves_svg(shapes):
    """Ebene Kurven (ohne Flächen) als SVG in Weltkoordinaten plus `at`."""
    from serpentine3d.core.tessellate import _edge_polyline
    from .fabrication import chain, edges_of
    polys = []
    for s in shapes:
        for e in edges_of(s):
            pl = _edge_polyline(e, 0.02)
            if pl is not None and len(pl) >= 2:
                polys.append([tuple(p[:2]) for p in pl])
    paths = chain(polys)
    if not paths:
        return None, None
    arr = np.array([p for pl in paths for p in pl])
    x0, y0 = arr.min(axis=0)
    x1, y1 = arr.max(axis=0)
    w, h = max(x1 - x0, 1e-3), max(y1 - y0, 1e-3)
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{w:.4f}mm" '
           f'height="{h:.4f}mm" viewBox="0 0 {w:.4f} {h:.4f}">']
    for pl in paths:
        d = " ".join(f"{'M' if i == 0 else 'L'}{x - x0:.4f},{y1 - y:.4f}"
                     for i, (x, y) in enumerate(pl))
        out.append(f'<path d="{d}{" Z" if pl[0] == pl[-1] else ""}" '
                   f'fill="none" stroke="#000"/>')
    out.append("</svg>")
    return "\n".join(out), [float(x0), float(y1)]


def no_offset_surfaces(shape):
    """SolidCraft liest Offset-Flächen nicht (Körper kommt offen an):
    solche Formen vor dem STEP-Export nach NURBS wandeln."""
    from OCP.BRepAdaptor import BRepAdaptor_Surface
    from OCP.ShapeCustom import ShapeCustom
    from OCP.GeomAbs import GeomAbs_OffsetSurface
    from .fabrication import faces_of
    if not any(BRepAdaptor_Surface(f).GetType()
               == GeomAbs_OffsetSurface for f in faces_of(shape)):
        return shape
    return ShapeCustom.ConvertToBSpline_s(shape, False, False, True, False)


class SolidCraftHost(Host):
    """Legt die Geometrie als Komponente ins offene SolidCraft-Design.

    Vorschau: Komponente „Nodes Vorschau“, wird bei jedem Senden ersetzt.
    Bake: neue Komponente mit Zeitstempel, bleibt stehen.

    Alles läuft im Qt-Hauptthread: Ein Python-Thread daneben ließ die
    Speicherbereinigung dort Qt-Objekte abräumen, und die App stürzte beim
    nächsten Zeichnen ab. Senden blockiert dafür kurz.
    """
    name = "SolidCraft"
    PREVIEW = "Nodes Vorschau"

    def __init__(self, args=None, live_delay=1.0):
        os.makedirs(UEBERGABE, exist_ok=True)
        self.args = args or ["--connect", f"127.0.0.1:{SOLIDCRAFT_PORT}"]
        self.args = [*self.args, "--allow-path", UEBERGABE]
        self.headless = "--headless" in self.args
        self.live = False
        self.status = ""
        self.client = None
        self._latest = []
        self._timer = None
        self.live_delay = live_delay

    def available(self):
        if self.headless:
            return True
        return port_open(SOLIDCRAFT_PORT)

    def _job(self, fn):
        try:
            if self.client is None or not self.client.alive():
                self.client = McpClient(self.args)
            result = fn(self.client)
        except Exception as exc:              # noqa: BLE001
            result = f"SolidCraft: {type(exc).__name__}: {exc}"
            if self.client is not None:
                self.client.close()
            self.client = None
        if isinstance(result, str):
            self.status = result
        return result

    def _place(self, c, items, name):
        """Komponente `name` mit allen Teilen anlegen."""
        from serpentine3d.fileio.step import export_step
        from serpentine3d.fileio.stl import export_stl
        from serpentine3d.core.mesh import MeshShape
        from .fabrication import faces_of
        breps, meshes, curves = [], [], []
        for _n, item in items:
            if isinstance(item, tuple):
                continue                      # Punkte: in SolidCraft weglassen
            if isinstance(item, MeshShape):
                meshes.append(item)
            elif list(faces_of(item)):
                breps.append(item)
            else:
                curves.append(item)
        tag = name.replace(" ", "_").replace(":", "")
        c.execute("component.create", {"name": name, "activate": True})
        try:
            parts = []
            if breps:
                p = os.path.join(UEBERGABE, f"{tag}.step")
                export_step([no_offset_surfaces(b) for b in breps], p)
                c.execute("file.insert_step", {"path": p, "name": name})
                parts.append(f"{len(breps)} Körper")
            if meshes:
                p = os.path.join(UEBERGABE, f"{tag}.stl")
                export_stl([(f"Netz {i}", m) for i, m in enumerate(meshes)], p)
                c.execute("file.insert_mesh", {"path": p})
                parts.append(f"{len(meshes)} Netz(e)")
            if curves:
                svg, at = curves_svg(curves)
                if svg:
                    p = os.path.join(UEBERGABE, f"{tag}.svg")
                    with open(p, "w", encoding="utf-8") as f:
                        f.write(svg)
                    c.execute("sketch.insert_svg",
                              {"path": p, "plane": "XY", "at": at})
                    c.execute("sketch.finish", {})
                    parts.append(f"{len(curves)} Kurve(n) als Skizze")
        finally:
            c.execute("component.activate", {"component": "root"})
        return ", ".join(parts) or "nichts"

    def _delete_preview(self, c):
        try:
            c.execute("component.delete", {"component": self.PREVIEW})
        except RuntimeError:
            pass                              # war noch keine da

    # -- Host

    def show(self, chans, items):
        self._latest = list(items) if chans is not None else []
        if not self.live:
            return
        from PySide6 import QtCore
        if self._timer is None:
            self._timer = QtCore.QTimer()
            self._timer.setSingleShot(True)
            self._timer.timeout.connect(self.send)
        self._timer.start(int(self.live_delay * 1000))

    def send(self, wait=True):
        items = self._latest

        def job(c):
            self._delete_preview(c)
            if not items:
                return "SolidCraft: Vorschau leer"
            what = self._place(c, items, self.PREVIEW)
            return f"SolidCraft: Vorschau {time.strftime('%H:%M:%S')} · {what}"
        return self._job(job)

    def remove_preview(self, wait=True):
        def job(c):
            self._delete_preview(c)
            return "SolidCraft: Vorschau entfernt"
        return self._job(job)

    def bake(self, items):
        name = f"Nodes {time.strftime('%H:%M:%S')}"
        return self._job(lambda c: f"SolidCraft: „{name}“ · "
                         + self._place(c, items, name))

    # -- Geometrie holen

    def _design(self, c, sketches=False):
        return json.loads(c.tool("inspect_design", {"measure": False,
                                                    "sketches": sketches}))

    def _body(self, c, name, cache):
        """Körper als OCC-Form (per STEP-Export), je Abruf einmal."""
        if name not in cache:
            p = os.path.join(UEBERGABE, "hol_" + name.replace(" ", "_")
                             + ".step")
            c.tool("export", {"format": "step", "bodies": [name], "path": p})
            cache[name] = sc_read_step(p)
        return cache[name]

    def _resolve(self, c, refs):
        cache, out, design = {}, [], None
        for r in refs:
            t = r["type"]
            if t == "body":
                out.append((r, r["name"], self._body(c, r["name"], cache)))
            elif t in ("face", "edge"):
                body = self._body(c, r["body"], cache)
                sub = nearest_sub(body, t, r["point"])
                if sub is not None:
                    out.append((r, f"{r['body']} {t} {r['index']}", sub))
            elif t == "sketch_curve":
                if design is None:
                    design = self._design(c, sketches=True)
                curve = sketch_curve(design, r["sketch"], r["id"])
                if curve is not None:
                    out.append((r, f"Skizze {r['sketch']}:{r['id']}", curve))
        return out

    def pick(self):
        def job(c):
            sel = self._design(c)["selection"]
            if not sel:
                raise RuntimeError("In SolidCraft ist nichts ausgewählt")
            refs = [dict(x, src="solidcraft") for x in sel]
            return self._resolve(c, refs)
        res = self._job(job)
        if isinstance(res, str):
            raise RuntimeError(res)
        return res

    def refetch(self, refs):
        res = self._job(lambda c: self._resolve(c, refs))
        if isinstance(res, str):
            raise RuntimeError(res)
        return res

    def revision(self, src=None):
        res = self._job(lambda c: self._design(c).get("revision"))
        return None if isinstance(res, str) else res

    def inspect(self):
        return self._job(lambda c: c.tool("inspect_design",
                                          {"measure": True,
                                           "sketches": False}))

    def run(self, fn):
        return self._job(fn)


def sc_read_step(path):
    from OCP.STEPControl import STEPControl_Reader
    r = STEPControl_Reader()
    if r.ReadFile(path) != 1:
        raise RuntimeError(f"STEP nicht lesbar: {path}")
    r.TransferRoots()
    return r.OneShape()


def nearest_sub(shape, kind, point):
    """Fläche/Kante von `shape`, die `point` am nächsten liegt."""
    from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeVertex
    from OCP.BRepExtrema import BRepExtrema_DistShapeShape
    from OCP.TopAbs import TopAbs_EDGE, TopAbs_FACE
    from OCP.TopExp import TopExp_Explorer
    from OCP.gp import gp_Pnt
    v = BRepBuilderAPI_MakeVertex(gp_Pnt(*point)).Vertex()
    exp = TopExp_Explorer(shape, TopAbs_FACE if kind == "face"
                          else TopAbs_EDGE)
    best, best_d = None, 1e18
    while exp.More():
        d = BRepExtrema_DistShapeShape(exp.Current(), v)
        if d.IsDone() and d.Value() < best_d:
            best, best_d = exp.Current(), d.Value()
        exp.Next()
    return best


def sketch_curve(design, sketch_id, curve_id):
    """Linie, Bogen oder Kreis einer SolidCraft-Skizze als OCC-Kurve."""
    from serpentine3d.core import geometry as geo
    sk = next((s for s in design.get("sketches", [])
               if s["id"] == sketch_id), None)
    if sk is None:
        return None
    cv = next((c for c in sk["curves"] if c["id"] == curve_id), None)
    if cv is None:
        return None
    o = np.array(sk["plane"]["origin"], float)
    xd = np.array(sk["plane"]["x_dir"], float)
    yd = np.array(sk["plane"]["y_dir"], float)
    w = lambda p: tuple(o + xd * p[0] + yd * p[1])        # noqa: E731
    t = cv["type"]
    if t == "line":
        return geo.make_line(w(cv["start_at"]), w(cv["end_at"]))
    if t in ("arc", "circle"):
        c = np.array(cv["center_at"], float)
        r = float(cv["radius"])
        normal = tuple(np.cross(xd, yd))
        if t == "circle" or "start_at" not in cv:
            return geo.make_circle(w(c), r, normal)
        a0 = np.arctan2(*(np.array(cv["start_at"]) - c)[::-1])
        a1 = np.arctan2(*(np.array(cv["end_at"]) - c)[::-1])
        if a1 <= a0:
            a1 += 2 * np.pi                    # gegen den Uhrzeigersinn
        am = (a0 + a1) / 2
        mid = c + r * np.array([np.cos(am), np.sin(am)])
        from OCP.BRepBuilderAPI import BRepBuilderAPI_MakeEdge
        from OCP.GC import GC_MakeArcOfCircle
        from OCP.gp import gp_Pnt
        arc = GC_MakeArcOfCircle(gp_Pnt(*w(cv["start_at"])), gp_Pnt(*w(mid)),
                                 gp_Pnt(*w(cv["end_at"]))).Value()
        return BRepBuilderAPI_MakeEdge(arc).Edge()
    return None


# ------------------------------------------------------- Vordergrund-App

def frontmost_pid():
    """PID der App im Vordergrund (nur macOS; sonst None)."""
    import sys
    if sys.platform != "darwin":
        return None
    try:
        asn = subprocess.run(["lsappinfo", "front"], capture_output=True,
                             text=True, timeout=1).stdout.strip()
        out = subprocess.run(["lsappinfo", "info", "-only", "pid", asn],
                             capture_output=True, text=True,
                             timeout=1).stdout
        return int(out.strip().split("=")[-1])
    except Exception:                         # noqa: BLE001
        return None
