"""Nach Updates auf GitHub sehen und sie installieren.

Beim Start liest die App die Version aus ``__init__.py`` auf dem
main-Zweig. Ist sie neuer, bietet die Werkzeugleiste ein Update an. Wie
installiert wird, hängt davon ab, wie SolidNode installiert wurde:

- ``uv tool``      → ``uv tool install --force git+…`` (neu von GitHub)
- editierbar aus einem Git-Klon → ``git pull --ff-only`` in diesem Klon
- sonst (pip, pipx, venv) → ``python -m pip install --upgrade git+…``

``SOLIDNODE_NO_UPDATE_CHECK=1`` schaltet die Prüfung ab,
``SOLIDNODE_UPDATE_URL`` liest die Version woanders (zum Testen).
"""

from __future__ import annotations

import os
import re
import shutil
import sys
import urllib.request

from . import __version__

REPO = "https://github.com/malandereideen/solidnode"
SOURCE = f"git+{REPO}"
VERSION_URL = ("https://raw.githubusercontent.com/malandereideen/solidnode/"
               "main/src/solidnode/__init__.py")


def parse(version):
    """'0.1.10' → (0, 1, 10); Unlesbares → ()."""
    m = re.match(r"\s*(\d+(?:\.\d+)*)", version or "")
    return tuple(int(x) for x in m.group(1).split(".")) if m else ()


def newer(remote, local=__version__):
    return parse(remote) > parse(local)


def _ssl_contexts():
    """Standard, dann bekannte Zertifikatsdateien: Python von python.org
    bringt unter macOS ohne „Install Certificates“ keine mit."""
    import ssl
    yield None
    for ca in ("/etc/ssl/cert.pem", "/opt/homebrew/etc/ca-certificates/cert.pem",
               "/usr/local/etc/ca-certificates/cert.pem",
               "/etc/ssl/certs/ca-certificates.crt"):
        if os.path.exists(ca):
            yield ssl.create_default_context(cafile=ca)


def latest(timeout=5.0):
    """Version auf GitHub, oder None (offline, Fehler, abgeschaltet)."""
    if os.environ.get("SOLIDNODE_NO_UPDATE_CHECK"):
        return None
    url = os.environ.get("SOLIDNODE_UPDATE_URL", VERSION_URL)
    req = urllib.request.Request(url, headers={"Cache-Control": "no-cache"})
    text = None
    for ctx in _ssl_contexts():
        try:
            with urllib.request.urlopen(req, timeout=timeout,
                                        context=ctx) as r:
                text = r.read(4096).decode("utf-8", "replace")
            break
        except Exception:                     # noqa: BLE001
            continue
    if text is None:
        return None
    m = re.search(r"""__version__\s*=\s*["']([^"']+)["']""", text)
    return m.group(1) if m else None


def _uv():
    for cand in (shutil.which("uv"), os.path.expanduser("~/.local/bin/uv"),
                 os.path.expanduser("~/.cargo/bin/uv"),
                 "/opt/homebrew/bin/uv", "/usr/local/bin/uv"):
        if cand and os.path.exists(cand):
            return cand
    return None


def _git_checkout():
    """Wurzel des Git-Klons, falls SolidNode editierbar daraus läuft."""
    here = os.path.dirname(os.path.abspath(__file__))
    if "site-packages" in here:
        return None
    root = os.path.dirname(os.path.dirname(here))      # …/src/solidnode → …
    return root if os.path.isdir(os.path.join(root, ".git")) else None


def plan():
    """(Beschreibung, Programm, Argumente, Arbeitsordner) fürs Update."""
    checkout = _git_checkout()
    if checkout:
        return ("git pull im Klon " + checkout, shutil.which("git") or "git",
                ["pull", "--ff-only"], checkout)
    receipt = os.path.join(sys.prefix, "uv-receipt.toml")
    uv = _uv()
    if os.path.exists(receipt) and uv:
        py = f"{sys.version_info.major}.{sys.version_info.minor}"
        return ("uv tool install", uv,
                ["tool", "install", "--force", "--python", py, SOURCE], None)
    return ("pip install --upgrade", sys.executable,
            ["-m", "pip", "install", "--upgrade", SOURCE], None)


def restart_command():
    """Programm und Argumente, um SolidNode neu zu starten."""
    return sys.executable, ["-m", "solidnode", *sys.argv[1:]]


def run_cli():
    """`solidnode update`: prüfen und gleich installieren."""
    import subprocess
    remote = latest()
    if remote is None:
        print("Konnte die Version auf GitHub nicht lesen (offline?).")
        return 1
    if not newer(remote):
        print(f"SolidNode {__version__} ist aktuell (GitHub: {remote}).")
        return 0
    what, prog, args, cwd = plan()
    print(f"Update {__version__} → {remote} per {what} …")
    return subprocess.call([prog, *args], cwd=cwd)
