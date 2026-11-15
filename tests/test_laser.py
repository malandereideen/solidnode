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
    assert msg.startswith("6 Teile") and len(files) == 2


def test_fenster_und_hinge(laser):
    L, c, _ = laser
    L.kasten(120, 80, 60)
    c.execute("select.set", {"items": [{"type": "face", "body": "Kasten 1 Front",
                                        "point": [60, 0, 30]}]})
    L.fenster(30, 36)
    assert "Fenster 1 Rahmen" in L.body_names()
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
    assert "Hinge 1: Streifen" in L.hinge(15, 90)
    assert _total(c) < before


def test_elemente_aendern_speichern_loeschen(laser):
    L, c, tmp = laser
    L.kasten(120, 80, 60)
    L.zinken()
    c.execute("select.set", {"items": [{"type": "face",
                                        "body": "Kasten 1 Front",
                                        "point": [60, 0, 30]}]})
    L.fenster(30, 36)
    k, z, f = (e["id"] for e in L.elements())
    L.edit(f, {"breite": 40, "x": -20, "sprossen_v": 2})
    assert "nachgezogen" in L.edit(k, {"hoehe": 80})
    assert json.loads(c.execute("inspect.interference", {}))["count"] == 0
    assert not [x for x in L.design()["timeline"] if x.get("error")]
    c.tool("save", {"path": str(tmp / "k.sc")})
    c.tool("new_design", {})
    c.tool("open", {"path": str(tmp / "k.sc")})
    els = L.elements()
    assert [e["name"] for e in els] == ["Kasten 1", "Zinken 1", "Fenster 1"]
    assert set(L.status(els).values()) == {"ok"}
    L.delete(f)
    assert abs(_total(c) - (120 * 80 * 80 - 114 * 74 * 77)) < 0.01


def _sel(c, body, pt):
    c.execute("select.set", {"items": [{"type": "face", "body": body,
                                        "point": pt}]})


def test_wandelemente_und_export(laser):
    L, c, tmp = laser
    L.kasten(140, 90, 80)
    L.zinken()
    _sel(c, "Kasten 1 Front", [70, 0, 40])        # liegt auf einer Fuge
    L.create("muster", {"muster": "backstein"})
    _sel(c, "Kasten 1 Front", [70, 0, 40])
    for form, x in (("bogen", -40), ("spitz", 40), ("rund", 0)):
        L.create("fenster", {"form": form, "breite": 12, "hoehe": 20,
                             "x": x, "y": 12})
    L.create("tuer", {})
    L.create("uhr", {"x": 40, "y": -20})
    L.create("band", {"art": "sockel", "hoehe": 4})
    L.create("band", {"art": "fries", "z": 66, "hoehe": 6})
    L.create("eckquader", {})
    assert not [x for x in L.design()["timeline"] if x.get("error")]
    fr = next(b for b in json.loads(c.tool("measure", {"summary": True}))[
        "bodies"] if b["name"] == "Fenster 1 Rahmen")
    assert abs(fr["bbox"]["max"][1] - 0) < 0.01     # vor der Front, stehend
    assert fr["bbox"]["max"][2] - fr["bbox"]["min"][2] > 20
    msg, files = L.export(ordner=str(tmp / "exp"))
    assert "⚠" not in msg, msg
    assert len(files) == 2 and files[1].endswith(".dxf")
    svg = open(files[0], encoding="utf-8").read()
    assert svg.count('stroke="#0000FF"') == 1 and svg.count("<path") > 500


def test_haus_turm_ohne_durchdringung(laser):
    from solidnode.laser import _common, _volume
    L, c, _ = laser
    L.create("haus", {"dach": "sattel"})
    L.zinken([b for b in L.body_names() if b.startswith("Haus 1")])
    L.create("kamin", {}, {"haus": L.elements()[0]["id"]})
    L.create("haus", {"dach": "walm", "x": 150, "neigung": 40,
                      "boden": False})
    L.create("turm", {"x": 0, "y": 150})
    assert not [x for x in L.design()["timeline"] if x.get("error")]
    names = L.body_names()
    shapes = {n: L.shape(n) for n in names
              if n.startswith(("Haus 1 Dach", "Haus 2 Dach", "Turm 1"))}
    ks = list(shapes)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            assert _volume(_common(shapes[a], shapes[b])) < 0.01, (a, b)


def test_gravur_standard_nur_skizze_und_schalter(laser):
    L, c, _ = laser
    rillen = lambda: [f for f in L.design()["timeline"]  # noqa: E731
                      if f["name"].endswith(" Gravur")]
    L.kasten(120, 80, 60)
    _sel(c, "Kasten 1 Front", [60, 0, 30])
    L.create("muster", {"muster": "backstein"})
    v0 = _total(c)
    assert not rillen() and not L.gravur_sichtbar()
    L.set_gravur(True)
    assert len(rillen()) == 1 and _total(c) < v0
    L.set_gravur(False)
    assert not rillen() and abs(_total(c) - v0) < 0.01


def test_gaube_vordach_rundturm(laser):
    from solidnode.laser import _common, _volume
    L, c, tmp = laser
    L.create("haus", {"dach": "sattel", "breite": 120, "tiefe": 80,
                      "hoehe": 60})
    hid = L.elements()[0]["id"]
    L.create("gaube", {"x": 35}, {"haus": hid, "seite": "vorn"})
    L.create("gaube", {"x": 60}, {"haus": hid, "seite": "hinten"})
    _sel(c, "Haus 1 Seite rechts", [120, 40, 20])
    L.create("vordach", {"breite": 50, "z": 35})
    L.create("rundturm", {"x": -40, "y": 40})
    L.create("rundturm", {"x": -40, "y": 110, "dach": "zinnen",
                          "durchmesser": 36})
    assert not [x for x in L.design()["timeline"] if x.get("error")]
    sh = {n: L.shape(n) for n in L.body_names()
          if n.startswith(("Gaube", "Vordach", "Rundturm", "Haus 1 Dach"))}
    ks = list(sh)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            assert _volume(_common(sh[a], sh[b])) < 0.01, (a, b)
    # Gauben ziehen mit, wenn das Haus höher wird
    assert "Gaube 1" in L.edit(hid, {"hoehe": 70})
    msg, _files = L.export(ordner=str(tmp / "exp"))
    assert "⚠" not in msg, msg
    flats = [n for n, *_ in [(e,) for e in ("Rundturm 1 Mantel Lasche", "Rundturm 1 Mantel",
                                            "Rundturm 1 Kegeldach",
                                            "Rundturm 2 Mantel")]]
    svg = "".join(open(f, encoding="utf-8").read() for f in _files
                  if f.endswith(".svg"))
    for n in flats:
        assert f">{n}<" in svg


def test_restliche_bauten(laser):
    from solidnode.laser import _common, _vertices, _volume
    L, c, tmp = laser
    eid = lambda n: next(e["id"] for e in L.elements()  # noqa: E731
                         if e["name"] == n)
    L.create("haus", {"dach": "sattel", "breite": 120, "tiefe": 80,
                      "hoehe": 60})
    L.zinken([b for b in L.body_names() if b.startswith("Haus 1")])
    L.create("zwerch", {"x": 40}, {"haus": eid("Haus 1"), "seite": "vorn"})
    L.create("dachreiter", {"x": 90}, {"host": eid("Haus 1")})
    L.create("podest", {}, {"host": eid("Haus 1")})
    _sel(c, "Haus 1 Rueckwand", [60, 80, 30])
    L.create("apsis", {})
    L.create("kasten", {"breite": 80, "tiefe": 60, "hoehe": 50, "x": 200,
                        "deckel": True})
    L.zinken([b for b in L.body_names() if b.startswith("Kasten 1")])
    L.create("ecktuerme", {"dach": "kegel"}, {"host": eid("Kasten 1")})
    L.create("turm", {"dach": "flach", "x": -80, "y": 40})
    L.create("helm", {}, {"host": eid("Turm 1")})
    L.create("muehle", {"x": -80, "y": 200})
    L.create("leuchtturm", {"x": 20, "y": 220})
    L.create("steinbruecke", {"x": 120, "y": 180})
    L.create("fachwerkbruecke", {"x": 120, "y": 260})
    L.create("pagode", {"x": 300, "y": 180})
    assert not [x for x in L.design()["timeline"] if x.get("error")]
    sh = {n: L.shape(n) for n in L.body_names()}
    bb = {n: (_vertices(s).min(0), _vertices(s).max(0))
          for n, s in sh.items()}
    wand = ("Boden", "Front", "Rueckwand", "Seite links", "Seite rechts",
            "Deckel")
    ks = list(sh)
    for i, a in enumerate(ks):
        for b in ks[i + 1:]:
            (al, ah), (bl, bh) = bb[a], bb[b]
            if (al > bh + 1e-6).any() or (bl > ah + 1e-6).any():
                continue
            if a.split()[:2] == b.split()[:2] and a.endswith(wand) \
                    and b.endswith(wand):
                continue                       # Zinkenstoß
            assert _volume(_common(sh[a], sh[b])) < 0.05, (a, b)
    assert "Turmhelm 1" in L.edit(eid("Turm 1"), {"hoehe": 100})
    msg, files = L.export(ordner=str(tmp / "exp"))
    assert "⚠" not in msg, msg
    svg = "".join(open(f, encoding="utf-8").read() for f in files
                  if f.endswith(".svg"))
    for part in ("Haube Lage 1", "Treppe Lage 1", "Gewölbe 1",
                 "Ecktürmchen 1 vl Kegel Lage 1", "Kragplatte"):
        assert part in svg, part
