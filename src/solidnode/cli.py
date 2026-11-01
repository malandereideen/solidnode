"""Command line: `solidnode` starts the app; a few helper sub-commands."""

from __future__ import annotations

import argparse
import os
import sys

PLUGIN_STUB = '''"""SolidNode dock and bridge for Serpentine3D (installed by
`solidnode install-serpentine-plugin`)."""
from solidnode.core import serpentine3d_plugin  # noqa: F401
'''


def install_serpentine_plugin():
    """Write a tiny plugin file into Serpentine3D's plugin folder.

    Must be run with the Python that runs Serpentine3D, so that this Python
    can import solidnode."""
    d = os.environ.get("SERP3D_PLUGIN_DIR",
                       os.path.expanduser("~/.serpentine3d/plugins"))
    os.makedirs(d, exist_ok=True)
    path = os.path.join(d, "solidnode_plugin.py")
    with open(path, "w", encoding="utf-8") as f:
        f.write(PLUGIN_STUB)
    print(f"Plugin geschrieben: {path}")
    print("Serpentine3D neu starten; dann Menü Plugins ▸ SolidNode.")


def doctor():
    """Check what SolidNode needs and say what is missing."""
    from . import __version__, hosts
    ok = True

    def line(good, text):
        nonlocal ok
        ok &= bool(good)
        print(("  ok   " if good else "  FEHLT ") + text)

    print(f"SolidNode {__version__}, Python {sys.version.split()[0]}")
    for mod, why in (("PySide6", "Qt"), ("OCP", "OpenCASCADE"),
                     ("NodeGraphQt", "Node-Editor"),
                     ("serpentine3d", "Geometrie und Vorschau")):
        try:
            __import__(mod)
            line(True, f"{mod} ({why})")
        except Exception as exc:              # noqa: BLE001
            line(False, f"{mod} ({why}): {exc}")
    cli = hosts.solidcraft_cli()
    import shutil
    found = os.path.exists(cli) or shutil.which(cli)
    line(found, f"solidcraft-cli: {cli}")
    port = hosts.SOLIDCRAFT_PORT
    line(hosts.port_open(port),
         f"SolidCraft mit Steuerport {port} erreichbar "
         "(sonst: SolidCraft mit --control %d starten)" % port)
    print("Alles bereit." if ok else "Siehe oben, was fehlt.")
    return 0 if ok else 1


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("install-serpentine-plugin", "doctor",
                            "-h", "--help", "--version"):
        p = argparse.ArgumentParser(prog="solidnode",
                                    description="Node-basiertes Modellieren "
                                    "für SolidCraft.")
        p.add_argument("befehl", nargs="?",
                       choices=["install-serpentine-plugin", "doctor"])
        p.add_argument("--version", action="store_true")
        a = p.parse_args(argv)
        if a.version:
            from . import __version__
            print(__version__)
            return 0
        if a.befehl == "doctor":
            sys.exit(doctor())
        if a.befehl == "install-serpentine-plugin":
            install_serpentine_plugin()
        return 0
    from . import app
    sys.argv = ["solidnode", *argv]
    app.main()
