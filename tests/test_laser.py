"""Laser-Palette gegen eine unsichtbare SolidCraft-Instanz."""

import json
import shutil

import pytest

from solidnode import hosts

pytestmark = pytest.mark.skipif(
    not (shutil.which(hosts.solidcraft_cli()) or
         __import__("os").path.exists(hosts.solidcraft_cli())),
    reason="solidcraft-cli fehlt")


@pytest.fixture
def laser(tmp_path):
    from solidnode.laser import Laser
    c = hosts.McpClient(["--headless", "--allow-path", hosts.UEBERGABE,
                         "--allow-path", str(tmp_path)])
    yield Laser(c), c, tmp_path
    c.close()


def _total(c):
    return json.loads(c.tool("measure", {"summary": True}))["total"][
        "volume_mm3"]


def test_kasten_zinken_exakt_ohne_ueberlappung(laser):
    L, c, tmp = laser
    L.kasten(120, 80, 60, deckel=True)
    assert "12 Stöße" in L.zinken()
    assert abs(_total(c) - (120 * 80 * 60 - 114 * 74 * 54)) < 0.01
    inter = json.loads(c.execute("inspect.interference", {}))
    assert inter["count"] == 0
    msg, files = L.export_svg(ordner=str(tmp / "exp"))
    assert msg.startswith("6 Teile") and len(files) == 1


def test_fenster_und_hinge(laser):
    L, c, _ = laser
    L.kasten(120, 80, 60)
    c.execute("select.set", {"items": [{"type": "face", "body": "Front",
                                        "point": [60, 0, 30]}]})
    L.fenster(30, 36)
    assert any(n.startswith("Fenster ") for n in L.body_names())
    c.tool("new_design", {})
    L.batch(L._box_plate("Streifen", (0, 0, 0), (150, 60, 3)))
    c.execute("sketch.create", {"plane": {"origin": [0, 0, 3],
                                          "x_dir": [1, 0, 0],
                                          "y_dir": [0, 1, 0]}})
    c.execute("sketch.line", {"points": [[75, -5], [75, 65]]})
    c.execute("sketch.finish", {})
    sk = L.design(sketches=True)["sketches"][-1]
    c.execute("select.set", {"items": [{"type": "sketch_curve",
                                        "sketch": sk["id"],
                                        "id": sk["curves"][0]["id"]}]})
    before = _total(c)
    assert "Living Hinge in Streifen" in L.hinge(15, 90)
    assert _total(c) < before
