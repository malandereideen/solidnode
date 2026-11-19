//! Kategorien Öffnungen, Blenden & Nischen, Muster (Gravur), Bänder & Schmuck.
//! Portiert aus laser_wand.py + laser_geom.py. Alles sitzt in Wandkoordinaten:
//! Ursprung `p` (Klickpunkt auf der Außenfläche), x = `right`, y = `up`,
//! Außennormale `n`. Aufgesetztes ist ein eigener Körper, Gravur ist eine
//! Skizze (auf Wunsch als 0,2-mm-Rille geschnitten).

use crate::craft::plugin::types::PluginError;
use crate::{add, cross, dot, invalid, mul, r, run, v3, Bx, V3};
use geo::algorithm::buffer::{Buffer, BufferStyle, LineJoin};
use geo::{Area, BooleanOps, BoundingRect, Coord, LineString, MultiLineString, MultiPolygon,
          Polygon};
use serde_json::{json, Map, Value};
use std::f64::consts::PI;

type P2 = (f64, f64);
type MP = MultiPolygon<f64>;

const GROOVE_DEPTH: f64 = 0.2;
const GROOVE_WIDTH: f64 = 0.3;

// ------------------------------------------------------------ Einträge

/// Eintrag → (Typ, Voreinstellung). Voreinstellungen wie in laser_app.py.
fn entry_def(entry: &str) -> Option<(&'static str, Value)> {
    Some(match entry {
        "rundbogen" => ("fenster", json!({"form": "bogen", "breite": 9, "hoehe": 18})),
        "eckig" => ("fenster", json!({"form": "rechteck", "breite": 9, "hoehe": 14})),
        "spitzbogen" => ("fenster", json!({"form": "spitz", "breite": 9, "hoehe": 20})),
        "rund" => ("fenster", json!({"form": "rund", "breite": 10, "sprossen_v": 1,
                                       "sprossen_h": 1})),
        "schlitz" => ("fenster", json!({"form": "rechteck", "breite": 2, "hoehe": 7,
                                          "rahmen": 0, "sprossen_v": 0, "sprossen_h": 0})),
        "tuer" => ("tuer", json!({})),
        "tor" => ("tuer", json!({"blatt": false, "breite": 26, "hoehe": 30, "rahmen": 3})),
        "spitzblende" => ("blende", json!({"form": "spitz", "breite": 14, "hoehe": 26})),
        "putzblende" => ("blende", json!({"form": "bogen", "breite": 6, "hoehe": 34})),
        "dreieck" => ("blende", json!({"form": "spitz", "breite": 6, "hoehe": 5})),
        "nischen" => ("blende", json!({"anzahl": 5, "breite": 5, "hoehe": 11, "abstand": 9})),
        "muster" => ("muster", json!({})),
        "gesims" => ("band", json!({"art": "gesims"})),
        "sockel" => ("band", json!({"art": "sockel", "hoehe": 4})),
        "trauf" => ("band", json!({"art": "trauf"})),
        "fries" => ("band", json!({"art": "fries", "hoehe": 6})),
        "eckquader" => ("eckquader", json!({})),
        "pfeiler" => ("pfeiler", json!({})),
        "uhr" => ("uhr", json!({})),
        _ => return None,
    })
}

/// Standardwerte je Typ (laser.py SCHEMA).
fn defaults(typ: &str) -> Value {
    match typ {
        "fenster" => json!({"form": "rechteck", "breite": 20.0, "hoehe": 30.0, "x": 0.0, "y": 0.0,
            "rahmen": 3.0, "sprosse": 1.5, "sprossen_v": 1, "sprossen_h": 1, "oeffnung": true,
            "sims": false, "lagen": 1, "staerke": 3.0}),
        "tuer" => json!({"form": "bogen", "breite": 12.0, "hoehe": 22.0, "x": 0.0, "rahmen": 2.0,
            "blatt": true, "bretter": true, "brett": 2.5, "lagen": 1, "staerke": 3.0}),
        "blende" => json!({"form": "spitz", "breite": 8.0, "hoehe": 20.0, "x": 0.0, "y": 0.0,
            "rand": 2.0, "anzahl": 1, "abstand": 12.0, "lagen": 1, "staerke": 3.0}),
        "muster" => json!({"muster": "backstein", "bereich": "flaeche", "breite": 30.0,
            "hoehe": 30.0, "x": 0.0, "y": 0.0, "form": "rechteck", "stein_h": 0.0,
            "stein_l": 0.0, "rand": true, "tiefe": 0.2}),
        "uhr" => json!({"durchmesser": 12.0, "x": 0.0, "y": 0.0, "lagen": 1, "staerke": 3.0}),
        "pfeiler" => json!({"x": 0.0, "breite": 6.0, "hoehe": 40.0, "tiefe": 8.0,
            "staerke": 3.0}),
        "band" => json!({"art": "gesims", "z": 30.0, "hoehe": 3.0, "bogen": 6.0, "rundum": true,
            "lagen": 1, "staerke": 3.0, "form": "bogen"}),
        "eckquader" => json!({"hoehe": 5.0, "lang": 10.0, "kurz": 6.0, "fuge": 1.2, "lagen": 1,
            "staerke": 3.0}),
        _ => json!({}),
    }
}

struct Pm(Map<String, Value>);

impl Pm {
    fn f(&self, k: &str) -> f64 {
        match &self.0.get(k) {
            Some(Value::Bool(b)) => *b as i32 as f64,
            Some(v) => v.as_f64().unwrap_or(0.0),
            None => 0.0,
        }
    }
    fn i(&self, k: &str) -> i64 { self.f(k).round() as i64 }
    fn b(&self, k: &str) -> bool {
        match self.0.get(k) {
            Some(Value::Bool(b)) => *b,
            Some(v) => v.as_f64().map(|x| x != 0.0).unwrap_or(false),
            None => false,
        }
    }
    fn s(&self, k: &str) -> String { self.0.get(k).and_then(|v| v.as_str()).unwrap_or("").into() }
    fn with(&self, k: &str, v: Value) -> Pm {
        let mut m = self.0.clone();
        m.insert(k.into(), v);
        Pm(m)
    }
}

pub fn execute(entry: &str, p: &Value) -> Option<Result<Value, PluginError>> {
    let (typ, preset) = entry_def(entry)?;
    let mut m = defaults(typ).as_object().cloned().unwrap_or_default();
    for (k, v) in preset.as_object().into_iter().flatten() {
        m.insert(k.clone(), v.clone());
    }
    for (k, v) in p.as_object().into_iter().flatten() {
        if k != "wand" && !v.is_null() {
            m.insert(k.clone(), v.clone());
        }
    }
    Some(build(typ, &Pm(m), p))
}

fn build(typ: &str, p: &Pm, raw: &Value) -> Result<Value, PluginError> {
    let ctx = ctx_wand(raw)?;
    let rillen = p.b("rillen");
    let mut w = W { rillen, created: vec![] };
    let info = match typ {
        "fenster" => w.fenster(&ctx, p)?,
        "tuer" => w.tuer(&ctx, p)?,
        "blende" => w.blende(&ctx, p)?,
        "muster" => w.muster(&ctx, p)?,
        "uhr" => w.uhr(&ctx, p)?,
        "pfeiler" => w.pfeiler(&ctx, p)?,
        "band" => w.band(&ctx, p)?,
        "eckquader" => w.eckquader(&ctx, p)?,
        _ => return Err(invalid("entry", typ)),
    };
    Ok(json!({"info": info, "wand": ctx.wall, "koerper": w.created}))
}

// ------------------------------------------------------------ 2D-Geometrie

fn ring(pts: &[P2]) -> LineString<f64> {
    LineString::from(pts.iter().map(|&(x, y)| Coord { x, y }).collect::<Vec<_>>())
}
fn poly(pts: &[P2]) -> MP {
    if pts.len() < 3 {
        return MP::new(vec![]);
    }
    // über union normalisieren (Orientierung, Selbstberührung)
    let pg = Polygon::new(ring(pts), vec![]);
    MP::new(vec![pg.clone()]).union(&MP::new(vec![]))
}
fn rect(x0: f64, y0: f64, x1: f64, y1: f64) -> MP {
    poly(&[(x0, y0), (x1, y0), (x1, y1), (x0, y1)])
}
fn empty() -> MP { MP::new(vec![]) }
fn is_empty(g: &MP) -> bool { g.0.is_empty() || g.unsigned_area() < 1e-9 }
fn union_all(gs: impl IntoIterator<Item = MP>) -> MP {
    gs.into_iter().fold(empty(), |a, b| if is_empty(&a) { b } else { a.union(&b) })
}
fn bounds(g: &MP) -> (f64, f64, f64, f64) {
    match g.bounding_rect() {
        Some(rc) => (rc.min().x, rc.min().y, rc.max().x, rc.max().y),
        None => (0.0, 0.0, 0.0, 0.0),
    }
}
/// buffer mit Gehrungsecken (shapely join_style=2)
fn buf(g: &MP, d: f64) -> MP {
    if d.abs() < 1e-9 || is_empty(g) {
        return g.clone();
    }
    g.buffer_with_style(BufferStyle::new(d).line_join(LineJoin::Miter(0.2)))
}
fn polys_of(g: &MP) -> Vec<(Vec<P2>, Vec<Vec<P2>>)> {
    let pts = |ls: &LineString<f64>| {
        let mut v: Vec<P2> = ls.coords().map(|c| (c.x, c.y)).collect();
        if v.len() > 1 && v.first() == v.last() {
            v.pop();
        }
        v
    };
    g.0.iter().filter(|pg| pg.unsigned_area() > 1e-6)
        .map(|pg| (pts(pg.exterior()), pg.interiors().iter().map(pts).collect())).collect()
}
fn plen(l: &[P2]) -> f64 {
    l.windows(2).map(|w| ((w[1].0 - w[0].0).powi(2) + (w[1].1 - w[0].1).powi(2)).sqrt()).sum()
}
/// Polylinien auf eine Fläche beschneiden.
fn clip(lines: Vec<Vec<P2>>, area: &MP) -> Vec<Vec<P2>> {
    let ml = MultiLineString::new(lines.iter().filter(|l| l.len() >= 2).map(|l| ring(l)).collect());
    if ml.0.is_empty() || is_empty(area) {
        return vec![];
    }
    area.clip(&ml, false).0.iter()
        .map(|ls| ls.coords().map(|c| (c.x, c.y)).collect::<Vec<P2>>())
        .filter(|l| l.len() >= 2 && plen(l) > 0.05).collect()
}
fn boundary_lines(g: &MP) -> Vec<Vec<P2>> {
    let mut out = vec![];
    for pg in &g.0 {
        for ls in std::iter::once(pg.exterior()).chain(pg.interiors().iter()) {
            out.push(ls.coords().map(|c| (c.x, c.y)).collect());
        }
    }
    out
}
fn closed(mut p: Vec<P2>) -> Vec<P2> {
    if let Some(&f) = p.first() {
        p.push(f);
    }
    p
}

/// Umriss Rechteck/Rundbogen/Spitzbogen/Kreis, Unterkante y0.
fn arch_poly(cx: f64, y0: f64, w: f64, top: f64, form: &str) -> Vec<P2> {
    if form == "rechteck" {
        return vec![(cx - w / 2.0, y0), (cx + w / 2.0, y0), (cx + w / 2.0, top),
                    (cx - w / 2.0, top)];
    }
    if form == "rund" {
        let rr = w / 2.0;
        let cy = y0 + rr;
        return (0..64).map(|i| {
            let a = 2.0 * PI * i as f64 / 64.0;
            (cx + rr * a.cos(), cy + rr * a.sin())
        }).collect();
    }
    let (rr, h) = (w / 2.0, top - y0);
    let mut pts = vec![(cx - rr, y0), (cx + rr, y0)];
    if form == "spitz" {
        let rise = (w * 0.866).min(h * 0.75);
        let (k, ys) = (rise / (w * 0.866), top - rise);
        for i in 0..17 {
            let th = (PI / 3.0) * (i as f64 / 16.0);
            pts.push((cx - rr + w * th.cos(), ys + k * w * th.sin()));
        }
        for i in (0..16).rev() {
            let th = (PI / 3.0) * (i as f64 / 16.0);
            pts.push((cx + rr - w * th.cos(), ys + k * w * th.sin()));
        }
        return pts;
    }
    let rise = if h >= rr { rr } else { h * 0.6 };
    let ys = top - rise;
    for i in 0..33 {
        let th = PI * i as f64 / 32.0;
        pts.push((cx + rr * th.cos(), ys + rise * th.sin()));
    }
    pts
}

fn muster_mass(typ: &str) -> (f64, f64) {
    match typ {
        "quader" => (7.0, 14.0),
        "feldstein" => (4.6, 6.0),
        "fischgrat" => (3.0, 6.0),
        "bretter" => (3.0, 24.0),
        "streifen" => (12.0, 12.0),
        "fachwerk" => (14.0, 16.0),
        "putz" => (0.0, 0.0),
        _ => (5.0, 10.0),
    }
}

/// kleiner deterministischer Zufall (Feldstein)
struct Rng(u64);
impl Rng {
    fn next(&mut self) -> f64 {
        self.0 = self.0.wrapping_mul(6364136223846793005).wrapping_add(1442695040888963407);
        ((self.0 >> 11) as f64) / ((1u64 << 53) as f64)
    }
}

/// Gravurlinien des Musters in `area` (laser_geom.pattern).
fn pattern(typ: &str, area: &MP, sh: f64, sl: f64, seed: u64) -> Vec<Vec<P2>> {
    if typ == "putz" || is_empty(area) {
        return vec![];
    }
    let (dh, dl) = muster_mass(typ);
    let mh = if sh > 0.5 { sh } else { dh };
    let ml = if sl > 0.5 { sl } else { dl };
    let (x0, y0, x1, y1) = bounds(area);
    let mut l: Vec<Vec<P2>> = vec![];
    match typ {
        "fachwerk" => {
            let bw = 2.0;
            let mut y = y0;
            while y < y1 + mh {
                l.push(closed(vec![(x0 - 1.0, y), (x1 + 1.0, y), (x1 + 1.0, y + bw),
                                   (x0 - 1.0, y + bw)]));
                y += mh;
            }
            let (mut x, mut k) = (x0, 0);
            while x < x1 + ml {
                l.push(closed(vec![(x, y0), (x + bw, y0), (x + bw, y1), (x, y1)]));
                let (mut y, mut j) = (y0 + bw, 0);
                while y < y1 {
                    if (k + j) % 3 == 0 {
                        l.push(vec![(x + bw, y), (x + ml, y + mh - bw)]);
                        l.push(vec![(x + bw, y + bw * 1.2), (x + ml - bw * 1.2, y + mh - bw)]);
                    }
                    y += mh;
                    j += 1;
                }
                x += ml;
                k += 1;
            }
        }
        "streifen" => {
            let (mut y, mut k) = (y0, 0);
            while y < y1 {
                l.push(vec![(x0, y), (x1, y)]);
                if k % 2 == 1 {
                    let mut x = x0 - mh;
                    while x < x1 {
                        l.push(vec![(x, y), (x + mh, y + mh)]);
                        x += 2.2;
                    }
                }
                y += mh;
                k += 1;
            }
        }
        "bretter" => {
            let (mut y, mut k) = (y0 + mh, 0);
            while y < y1 + mh {
                l.push(vec![(x0, y), (x1, y)]);
                let mut x = x0 + (k % 3) as f64 * (ml / 3.0);
                while x < x1 {
                    l.push(vec![(x, y - mh), (x, y)]);
                    x += ml;
                }
                y += mh;
                k += 1;
            }
        }
        "fischgrat" => {
            let a = mh;
            let (mut y, mut k) = (y0, 0);
            while y < y1 + a {
                let mut x = x0 - 2.0 * a;
                while x < x1 + 2.0 * a {
                    l.push(vec![(x, y), (x + a, y + a), (x + 2.0 * a, y)]);
                    x += 2.0 * a;
                }
                if k % 2 == 1 {
                    let mut x = x0 - a;
                    while x < x1 + 2.0 * a {
                        l.push(vec![(x, y), (x, y + a)]);
                        x += 2.0 * a;
                    }
                }
                y += a;
                k += 1;
            }
        }
        "feldstein" => {
            let mut rng = Rng(seed | 1);
            let (mut y, mut k) = (y0, 0);
            while y < y1 + mh {
                let mut x = x0 - ml + (k % 2) as f64 * ml / 2.0;
                while x < x1 + ml {
                    let cx = x + (rng.next() - 0.5) * 1.4;
                    let cy = y + (rng.next() - 0.5) * 1.0;
                    let rx = ml * (0.36 + rng.next() * 0.1);
                    let ry = mh * (0.36 + rng.next() * 0.1);
                    let pts = (0..9).map(|i| {
                        let th = i as f64 / 9.0 * 2.0 * PI;
                        let f = 0.85 + rng.next() * 0.3;
                        (cx + th.cos() * rx * f, cy + th.sin() * ry * f)
                    }).collect();
                    l.push(closed(pts));
                    x += ml;
                }
                y += mh;
                k += 1;
            }
        }
        _ => {
            let (mut y, mut k) = (y0 + mh, 0);
            while y < y1 + mh {
                l.push(vec![(x0, y), (x1, y)]);
                let mut x = x0 + if k % 2 == 1 { ml / 2.0 } else { 0.0 };
                while x < x1 {
                    if x > x0 + 1e-6 {
                        l.push(vec![(x, y - mh), (x, y)]);
                    }
                    x += ml;
                }
                y += mh;
                k += 1;
            }
        }
    }
    clip(l, area)
}

fn fries_shape(x0: f64, x1: f64, z0: f64, h: f64, p: f64, form: &str) -> MP {
    let (p, h) = (p.max(3.0), h.max(3.0));
    let zt = z0 + h;
    let band = (2.0f64).min(h * 0.3);
    let leg = (1.2f64).max(p * 0.22);
    let n = (((x1 - x0) / p).round() as i64).max(1);
    let pp = (x1 - x0) / n as f64;
    let holes = union_all((0..n).map(|i| poly(&arch_poly(x0 + pp * (i as f64 + 0.5), z0 - 1.0,
        pp - leg, zt - band, if form == "spitz" { "spitz" } else { "bogen" }))));
    rect(x0, z0, x1, zt).difference(&holes)
}

fn clock_lines(cx: f64, cy: f64, rr: f64) -> Vec<Vec<P2>> {
    let mut out = vec![(0..49).map(|i| {
        let a = 2.0 * PI * i as f64 / 48.0;
        (cx + rr * 0.82 * a.cos(), cy + rr * 0.82 * a.sin())
    }).collect::<Vec<P2>>()];
    for i in 0..12 {
        let a = 2.0 * PI * i as f64 / 12.0;
        out.push(vec![(cx + rr * 0.62 * a.cos(), cy + rr * 0.62 * a.sin()),
                      (cx + rr * 0.74 * a.cos(), cy + rr * 0.74 * a.sin())]);
    }
    for (ang, ln) in [((90.0f64 - 300.0).to_radians(), 0.42), ((90.0f64 - 60.0).to_radians(), 0.58)] {
        out.push(vec![(cx, cy), (cx + rr * ln * ang.cos(), cy + rr * ln * ang.sin())]);
    }
    out
}

// ------------------------------------------------------------ Wandkontext

#[derive(Clone)]
struct Ctx {
    wall: String,
    p: V3,
    right: V3,
    up: V3,
    n: V3,
    thickness: f64,
    face: MP,
    bounds: (f64, f64, f64, f64),
    ecke: bool,
}

fn unit(v: V3) -> V3 {
    let l = dot(v, v).sqrt();
    mul(v, 1.0 / l)
}
fn sub(a: V3, b: V3) -> V3 { [a[0] - b[0], a[1] - b[1], a[2] - b[2]] }

/// Rechts/oben auf einer Fläche mit Außennormale n (Blick von außen).
fn frame_up(n: V3) -> (V3, V3) {
    let mut up = [0.0, 0.0, 1.0];
    if dot(up, n).abs() > 0.9 {
        up = [0.0, 1.0, 0.0];
    }
    let up = unit(sub(up, mul(n, dot(up, n))));
    (cross(up, n), up)
}

fn quant(p: P2) -> (i64, i64) { ((p.0 * 1000.0).round() as i64, (p.1 * 1000.0).round() as i64) }

/// Kanten einer Ebene → geschlossene Züge → Fläche (gerade/ungerade).
fn loops_to_area(segs: Vec<(P2, P2)>) -> MP {
    let mut used = vec![false; segs.len()];
    let mut area = empty();
    for s in 0..segs.len() {
        if used[s] { continue; }
        used[s] = true;
        let start = segs[s].0;
        let mut pts = vec![segs[s].0, segs[s].1];
        let mut cur = segs[s].1;
        let mut ok = false;
        for _ in 0..segs.len() {
            if quant(cur) == quant(start) { ok = true; break; }
            let mut found = false;
            for (j, sg) in segs.iter().enumerate() {
                if used[j] { continue; }
                let nxt = if quant(sg.0) == quant(cur) { Some(sg.1) }
                          else if quant(sg.1) == quant(cur) { Some(sg.0) } else { None };
                if let Some(nx) = nxt {
                    used[j] = true;
                    pts.push(nx);
                    cur = nx;
                    found = true;
                    break;
                }
            }
            if !found { break; }
        }
        if ok && pts.len() >= 4 {
            pts.pop();
            let pg = poly(&pts);
            if pg.unsigned_area() > 1e-6 {
                area = if is_empty(&area) { pg } else { area.xor(&pg) };
            }
        }
    }
    area
}

fn bodies_bbox() -> Result<Vec<(String, Bx)>, PluginError> {
    let m = run("inspect.measure", json!({}))?;
    Ok(m["bodies"].as_array().into_iter().flatten().map(|b| {
        (b["name"].as_str().unwrap_or("").to_string(),
         Bx { lo: v3(&b["bbox"]["min"]), hi: v3(&b["bbox"]["max"]) })
    }).collect())
}

fn ctx_wand(raw: &Value) -> Result<Ctx, PluginError> {
    let pick = raw["wand"].as_array().and_then(|a| a.first())
        .ok_or_else(|| invalid("wand", "Wandfläche in SolidCraft anklicken"))?;
    let wall = pick["body"].as_str().or(pick["name"].as_str())
        .ok_or_else(|| invalid("wand", "Fläche einer Platte anklicken"))?.to_string();
    let click = v3(&pick["point"]);
    let faces = run("model.faces", json!({"body": wall}))?;
    // Normale von der größten ebenen Fläche (nicht von der Klickfläche)
    let big = faces["faces"].as_array().into_iter().flatten()
        .filter(|f| f["plane_normal"].is_array())
        .max_by(|a, b| a["area"].as_f64().unwrap_or(0.0).total_cmp(&b["area"].as_f64().unwrap_or(0.0)))
        .ok_or_else(|| invalid("wand", format!("{wall} ist keine ebene Platte")))?;
    let mut n = unit(v3(&big["plane_normal"]));
    let edges = run("model.edges", json!({"body": wall}))?;
    let ev: Vec<(V3, V3, V3, f64)> = edges["edges"].as_array().into_iter().flatten()
        .map(|e| (v3(&e["start"]), v3(&e["end"]), v3(&e["mid"]), e["length"].as_f64().unwrap_or(0.0)))
        .collect();
    let ds: Vec<f64> = ev.iter().flat_map(|e| [dot(e.0, n), dot(e.1, n)]).collect();
    let (mut dmin, mut dmax) = (ds.iter().cloned().fold(f64::MAX, f64::min),
                                ds.iter().cloned().fold(f64::MIN, f64::max));
    let pc = dot(click, n);
    if (pc - dmin).abs() < (pc - dmax).abs() {
        n = mul(n, -1.0);
        (dmin, dmax) = (-dmax, -dmin);
    }
    let thickness = dmax - dmin;
    let p = add(click, mul(n, dmax - dot(click, n)));
    let (right, up) = frame_up(n);
    // Umriss von der Rückseite (dort keine Gravurrillen)
    let loc = |q: V3| { let v = sub(q, p); (dot(v, right), dot(v, up)) };
    let mut segs = vec![];
    for (s, e, m, len) in &ev {
        if (dot(*s, n) - dmin).abs() > 1e-3 || (dot(*e, n) - dmin).abs() > 1e-3 { continue; }
        let chord = dot(sub(*e, *s), sub(*e, *s)).sqrt();
        if *len > chord + 1e-3 && chord > 1e-6 {
            segs.push((loc(*s), loc(*m)));
            segs.push((loc(*m), loc(*e)));
        } else if chord > 1e-6 {
            segs.push((loc(*s), loc(*e)));
        }
    }
    let face = loops_to_area(segs);
    if is_empty(&face) {
        return Err(invalid("wand", format!("Umriss von {wall} nicht lesbar")));
    }
    let bounds = bounds(&face);
    Ok(Ctx { wall, p, right, up, n, thickness, face, bounds, ecke: false })
}

/// Die vier Außenwände eines Kastens („<Name> Front/Rueckwand/Seite links/Seite rechts“).
fn kasten_walls(ctx: &Ctx, all: &[(String, Bx)]) -> Option<Vec<Ctx>> {
    const SUF: [&str; 4] = ["Front", "Rueckwand", "Seite links", "Seite rechts"];
    let prefix = SUF.iter().find_map(|s| ctx.wall.strip_suffix(&format!(" {s}")))?;
    let get = |s: &str| all.iter().find(|(n, _)| *n == format!("{prefix} {s}")).map(|(_, b)| *b);
    let bx: Vec<Bx> = SUF.iter().map(|s| get(s)).collect::<Option<_>>()?;
    let lo = [0, 1, 2].map(|i| bx.iter().map(|b| b.lo[i]).fold(f64::MAX, f64::min));
    let hi = [0, 1, 2].map(|i| bx.iter().map(|b| b.hi[i]).fold(f64::MIN, f64::max));
    let (bb, tt, hh) = (hi[0] - lo[0], hi[1] - lo[1], hi[2] - lo[2]);
    let o = lo;
    let walls = [("Front", [0.0, -1.0, 0.0], [1.0, 0.0, 0.0], o, bb),
                 ("Rueckwand", [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], add(o, [bb, tt, 0.0]), bb),
                 ("Seite links", [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], add(o, [0.0, tt, 0.0]), tt),
                 ("Seite rechts", [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], add(o, [bb, 0.0, 0.0]), tt)];
    Some(walls.iter().zip(&bx).map(|((nm, n, rgt, po, l), b)| Ctx {
        wall: format!("{prefix} {nm}"), p: *po, right: *rgt, up: [0.0, 0.0, 1.0], n: *n,
        thickness: b.ext(b.thin_axis()), face: rect(0.0, 0.0, *l, hh),
        bounds: (0.0, 0.0, *l, hh), ecke: *nm == "Front" || *nm == "Rueckwand",
    }).collect())
}

fn walls_for(ctx: &Ctx, rundum: bool) -> Result<Vec<Ctx>, PluginError> {
    if rundum {
        if let Some(w) = kasten_walls(ctx, &bodies_bbox()?) {
            return Ok(w);
        }
    }
    Ok(vec![ctx.clone()])
}

/// Belegte Fläche auf der Wand: Durchbrüche der Wand und Körper davor
/// (Rahmen, Blenden, Uhr, Pfeiler, Türblatt) als Rechtecke. Ersetzt die
/// Elementliste der Palette, die es im Plugin nicht gibt.
fn occupied(c: &Ctx, all: &[(String, Bx)], skip_prefix: &str) -> MP {
    let mut parts = vec![];
    for pg in &c.face.0 {
        for h in pg.interiors() {
            parts.push(buf(&MP::new(vec![Polygon::new(h.clone(), vec![])]), 0.3));
        }
    }
    let dn = dot(c.p, c.n);
    let face_area = c.face.unsigned_area();
    for (name, b) in all {
        if name == &c.wall || name.starts_with(skip_prefix) { continue; }
        let corners: Vec<V3> = (0..8).map(|k| [if k & 1 == 0 { b.lo[0] } else { b.hi[0] },
            if k & 2 == 0 { b.lo[1] } else { b.hi[1] }, if k & 4 == 0 { b.lo[2] } else { b.hi[2] }])
            .collect();
        let d: Vec<f64> = corners.iter().map(|q| dot(*q, c.n) - dn).collect();
        let (d0, d1) = (d.iter().cloned().fold(f64::MAX, f64::min),
                        d.iter().cloned().fold(f64::MIN, f64::max));
        if d1 < -c.thickness - 0.05 || d0 > 0.05 + 1e-9 && d0 > 60.0 || d1 - d0 > 60.0 { continue; }
        if d1 <= -c.thickness + 0.05 { continue; }
        let xs: Vec<f64> = corners.iter().map(|q| dot(sub(*q, c.p), c.right)).collect();
        let ys: Vec<f64> = corners.iter().map(|q| dot(sub(*q, c.p), c.up)).collect();
        let g = rect(xs.iter().cloned().fold(f64::MAX, f64::min), ys.iter().cloned().fold(f64::MAX, f64::min),
                     xs.iter().cloned().fold(f64::MIN, f64::max), ys.iter().cloned().fold(f64::MIN, f64::max));
        if g.unsigned_area() > 0.5 * face_area { continue; }
        parts.push(buf(&g, 0.3));
    }
    union_all(parts)
}

// ------------------------------------------------------------ Befehle

struct W {
    rillen: bool,
    created: Vec<String>,
}

fn next_name(base: &str) -> Result<String, PluginError> {
    let names: Vec<String> = bodies_bbox()?.into_iter().map(|(n, _)| n).collect();
    let mut i = 1;
    loop {
        let cand = format!("{base} {i}");
        if !names.iter().any(|n| n == &cand || n.starts_with(&format!("{cand} "))) {
            return Ok(cand);
        }
        i += 1;
    }
}

fn pts_json(l: &[P2]) -> Value {
    let mut out: Vec<(f64, f64)> = vec![];
    for &(x, y) in l {
        let q = ((x * 1e4).round() / 1e4, (y * 1e4).round() / 1e4);
        if out.last().is_none_or(|l| (l.0 - q.0).abs() > 2e-4 || (l.1 - q.1).abs() > 2e-4) {
            out.push(q);
        }
    }
    Value::Array(out.into_iter().map(|(x, y)| json!([x, y])).collect())
}

impl W {
    fn sketch(&self, c: &Ctx, name: &str, polys: &[(Vec<P2>, Vec<Vec<P2>>)], lines: &[Vec<P2>],
              offset: f64) -> Result<(), PluginError> {
        let o = add(c.p, mul(c.n, offset));
        run("sketch.create", json!({"plane": {"origin": o.map(|x| (x * 1e6).round() / 1e6),
            "x_dir": c.right, "y_dir": c.up}, "name": name}))?;
        let n_paths = polys.iter().map(|(_, h)| 1 + h.len()).sum::<usize>() + lines.len();
        if n_paths <= 235 {
            for (outer, holes) in polys {
                for lp in std::iter::once(outer).chain(holes.iter()) {
                    let pts = pts_json(&closed(lp.clone()));
                    if pts.as_array().map_or(0, |a| a.len()) >= 4 {
                        run("sketch.line", json!({"points": pts}))?;
                    }
                }
            }
            for ln in lines {
                let pts = pts_json(ln);
                if pts.as_array().map_or(0, |a| a.len()) >= 2 {
                    run("sketch.line", json!({"points": pts}))?;
                }
            }
        } else {
            // Viele Linien (dichte Muster): alles in einem Aufruf als SVG, sonst
            // sprengt es das Limit von 256 Host-Aufrufen je Lauf. Braucht die
            // Befehlsgruppe "file" (nur laser-muster). SVG: px bei 96 dpi, y nach unten.
            let mut d = String::new();
            let mut add_path = |l: &[P2], close: bool| {
                let a = pts_json(l).as_array().cloned().unwrap_or_default();
                if a.len() < if close { 3 } else { 2 } {
                    return;
                }
                for (k, q) in a.iter().enumerate() {
                    let (x, y) = (q[0].as_f64().unwrap_or(0.0), q[1].as_f64().unwrap_or(0.0));
                    d.push_str(&format!("{}{} {} ", if k == 0 { "M" } else { "L" }, x, -y));
                }
                if close {
                    d.push_str("Z ");
                }
            };
            for (outer, holes) in polys {
                for lp in std::iter::once(outer).chain(holes.iter()) {
                    add_path(lp, true);
                }
            }
            for ln in lines {
                add_path(ln, false);
            }
            let svg = format!("<svg xmlns='http://www.w3.org/2000/svg'><path d='{}' fill='none' \
                               stroke='black'/></svg>", d.trim());
            run("sketch.insert_svg", json!({"text": svg, "scale": 96.0 / 25.4}))?;
        }
        run("sketch.finish", json!({}))?;
        Ok(())
    }

    /// Fläche als aufgesetzte Platte(n) vor der Wand; Splitter fallen weg.
    fn plate_on(&mut self, c: &Ctx, name: &str, geom: &MP, lagen: f64, staerke: f64, offset: f64,
                inward: bool) -> Result<Option<String>, PluginError> {
        let g = buf(&buf(geom, -0.4), 0.4);
        let polys: Vec<_> = polys_of(&g).into_iter().filter(|(o, h)| {
            MP::new(vec![Polygon::new(ring(o), h.iter().map(|x| ring(x)).collect())]).unsigned_area() >= 1.0
        }).collect();
        if polys.is_empty() {
            return Ok(None);
        }
        self.sketch(c, &format!("{name} Skizze"), &polys, &[], offset)?;
        let rep = run("solid.extrude", json!({"distance": r(staerke * lagen), "operation": "new",
            "direction": if inward { "negative" } else { "positive" },
            "body_name": name, "name": name}))?;
        let body = rep["created_bodies"][0].as_str().unwrap_or(name).to_string();
        self.created.push(body.clone());
        Ok(Some(body))
    }

    fn groove(&mut self, c: &Ctx, name: &str, lines: Vec<Vec<P2>>, target: &str, offset: f64,
              tiefe: f64) -> Result<usize, PluginError> {
        let lines: Vec<_> = lines.into_iter().filter(|l| l.len() >= 2).collect();
        if lines.is_empty() {
            return Ok(0);
        }
        self.sketch(c, &format!("{name} Skizze"), &[], &lines, offset)?;
        if self.rillen {
            run("solid.extrude", json!({"thin": true, "thickness": GROOVE_WIDTH,
                "distance": r(tiefe), "direction": "negative", "operation": "cut",
                "targets": [target], "name": format!("{name} Gravur")}))?;
        }
        Ok(lines.len())
    }

    fn cut_through(&mut self, c: &Ctx, name: &str, geom: &MP) -> Result<(), PluginError> {
        let polys = polys_of(geom);
        if polys.is_empty() {
            return Ok(());
        }
        self.sketch(c, &format!("{name} Skizze"), &polys, &[], 0.0)?;
        run("solid.extrude", json!({"distance": r(c.thickness + 1.0), "direction": "negative",
            "operation": "cut", "targets": [c.wall], "name": name}))?;
        Ok(())
    }

    // -- Öffnungen

    fn opening(p: &Pm, y0: Option<f64>) -> MP {
        let y0 = y0.unwrap_or(p.f("y") - p.f("hoehe") / 2.0);
        let form = p.s("form");
        let h = if form == "rund" { p.f("breite") } else { p.f("hoehe") };
        poly(&arch_poly(p.f("x"), y0, p.f("breite"), y0 + h, &form))
    }

    fn fenster(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let name = next_name("Fenster")?;
        let opening = Self::opening(p, None);
        if p.b("oeffnung") {
            self.cut_through(c, &format!("{name} Öffnung"), &opening)?;
        }
        let (rr, sp) = (p.f("rahmen"), p.f("sprosse"));
        let mut outer = if rr > 0.0 { buf(&opening, rr) } else { opening.clone() };
        if p.b("sims") {
            let (x0, y0, x1, _) = bounds(&outer);
            outer = outer.union(&rect(x0 - 2.5, y0 - 1.5, x1 + 2.5, y0 + 0.5));
        }
        let (x0, y0, x1, y1) = bounds(&opening);
        let (nv, nh) = (p.i("sprossen_v").max(0), p.i("sprossen_h").max(0));
        let mut bars = vec![];
        for i in 1..=nv {
            let x = x0 + (x1 - x0) * i as f64 / (nv + 1) as f64;
            bars.push(rect(x - sp / 2.0, y0 - 1.0, x + sp / 2.0, y1 + 1.0));
        }
        for j in 1..=nh {
            let y = y0 + (y1 - y0) * j as f64 / (nh + 1) as f64;
            bars.push(rect(x0 - 1.0, y - sp / 2.0, x1 + 1.0, y + sp / 2.0));
        }
        let panes = if bars.is_empty() { opening.clone() } else { opening.difference(&union_all(bars)) };
        let frame = outer.difference(&panes);
        if !is_empty(&frame) && frame.unsigned_area() > 0.01 {
            self.plate_on(c, &format!("{name} Rahmen"), &frame, p.f("lagen"), p.f("staerke"),
                          0.0, false)?;
        }
        Ok(format!("{} {}×{} auf {}", p.s("form"), p.f("breite"), p.f("hoehe"), c.wall))
    }

    fn door(c: &Ctx, p: &Pm) -> (MP, f64) {
        let mut y0 = c.bounds.1;
        if c.wall.ends_with("Front") || c.wall.ends_with("Rueckwand") || c.wall.contains("Seite") {
            y0 += c.thickness; // Schwelle auf dem Boden (Kasten/Haus)
        }
        let form = if p.s("form") == "rund" { "bogen".to_string() } else { p.s("form") };
        (Self::opening(&p.with("form", json!(form)), Some(y0)), y0)
    }

    fn tuer(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let name = next_name(if p.b("blatt") { "Tür" } else { "Tor" })?;
        let (opening, y0) = Self::door(c, p);
        let (x0, _, x1, _) = bounds(&opening);
        let cut = opening.union(&rect(x0, c.bounds.1 - 1.0, x1, y0 + 1.0));
        self.cut_through(c, &format!("{name} Öffnung"), &cut)?;
        let rr = p.f("rahmen");
        let above = rect(-1e4, y0, 1e4, 1e4);
        if rr > 0.0 {
            let frame = buf(&opening, rr).difference(&opening).intersection(&above);
            self.plate_on(c, &format!("{name} Rahmen"), &frame, p.f("lagen"), p.f("staerke"),
                          0.0, false)?;
        }
        if p.b("blatt") {
            let leaf = buf(&opening, 1.5).intersection(&above);
            let body = self.plate_on(c, &format!("{name} Blatt"), &leaf, 1.0, p.f("staerke"),
                                     -c.thickness, true)?;
            if let (Some(body), true) = (body, p.b("bretter")) {
                let lb = buf(&opening, 1.5);
                let (bx0, by0, bx1, by1) = bounds(&lb);
                let mut lines = vec![];
                let mut x = bx0 + p.f("brett");
                while x < bx1 {
                    lines.push(vec![(x, by0 - 1.0), (x, by1 + 1.0)]);
                    x += p.f("brett").max(0.5);
                }
                let lines = clip(lines, &lb);
                self.groove(c, &format!("{name} Bretter"), lines, &body, -c.thickness, GROOVE_DEPTH)?;
            }
        }
        Ok(format!("{} {}×{} auf {}", p.s("form"), p.f("breite"), p.f("hoehe"), c.wall))
    }

    fn blende(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let name = next_name("Blende")?;
        let n = p.i("anzahl").max(1);
        let niches: Vec<MP> = (0..n).map(|i| Self::opening(&p.with("x",
            json!(p.f("x") + (i as f64 - (n - 1) as f64 / 2.0) * p.f("abstand"))), None)).collect();
        let plate = union_all(niches.iter().map(|q| buf(q, p.f("rand"))))
            .difference(&union_all(niches.clone()));
        self.plate_on(c, &name, &plate, p.f("lagen"), p.f("staerke"), 0.0, false)?;
        Ok(format!("{n}× {} {}×{} auf {}", p.s("form"), p.f("breite"), p.f("hoehe"), c.wall))
    }

    // -- Muster

    fn muster(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let name = next_name("Muster")?;
        let mut area = c.face.clone();
        let feld = p.s("bereich") == "feld";
        if feld {
            let h2 = p.f("hoehe") / 2.0;
            let fld = poly(&arch_poly(p.f("x"), p.f("y") - h2, p.f("breite"), p.f("y") + h2,
                                      &p.s("form")));
            area = area.intersection(&fld);
        }
        let seed = name.bytes().fold(1469598103934665603u64, |h, b| (h ^ b as u64).wrapping_mul(1099511628211));
        let mut lines = pattern(&p.s("muster"), &area, p.f("stein_h"), p.f("stein_l"), seed);
        if p.b("rand") && feld {
            lines.extend(boundary_lines(&area));
        }
        if lines.is_empty() {
            return Err(invalid("muster", "Muster ergibt keine Linien (Putz oder leere Fläche)"));
        }
        let k = self.groove(c, &name, lines, &c.wall.clone(), 0.0, p.f("tiefe"))?;
        Ok(format!("{} auf {}, {k} Linien", p.s("muster"), c.wall))
    }

    // -- Schmuck

    fn uhr(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let name = next_name("Uhr")?;
        let rr = p.f("durchmesser") / 2.0;
        let disk = poly(&arch_poly(p.f("x"), p.f("y") - rr, 2.0 * rr, p.f("y") + rr, "rund"));
        if let Some(body) = self.plate_on(c, &name, &disk, p.f("lagen"), p.f("staerke"), 0.0, false)? {
            let lines = clock_lines(p.f("x"), p.f("y"), rr);
            self.groove(c, &format!("{name} Zifferblatt"), lines, &body,
                        p.f("staerke") * p.f("lagen"), GROOVE_DEPTH)?;
        }
        Ok(format!("Ø{} auf {}", p.f("durchmesser"), c.wall))
    }

    /// Strebepfeiler: Profilplatten quer zur Wand, abgetreppt.
    fn pfeiler(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let name = next_name("Pfeiler")?;
        let t = p.f("staerke");
        let n = ((p.f("breite") / t).round() as i64).max(1);
        let (d, h) = (p.f("tiefe"), p.f("hoehe"));
        let prof = vec![(0.0, 0.0), (d, 0.0), (d, h * 0.45), (d * 0.6, h * 0.45 + d * 0.4),
                        (d * 0.6, h * 0.8), (0.0, h)];
        let y0 = c.bounds.1;
        for i in 0..n {
            let o = add(add(c.p, mul(c.right, p.f("x") - n as f64 * t / 2.0 + i as f64 * t)),
                        mul(c.up, y0));
            let c2 = Ctx { p: o, right: c.n, up: c.up, n: mul(c.right, -1.0), ..c.clone() };
            let nm = format!("{name} Lage {}", i + 1);
            self.sketch(&c2, &format!("{nm} Skizze"), &[(prof.clone(), vec![])], &[], 0.0)?;
            let rep = run("solid.extrude", json!({"distance": r(t), "direction": "negative",
                "operation": "new", "body_name": nm, "name": nm}))?;
            self.created.push(rep["created_bodies"][0].as_str().unwrap_or(&nm).to_string());
        }
        Ok(format!("{n} Lagen, {d} tief, {h} hoch an {}", c.wall))
    }

    // -- Bänder

    fn band_geom(c: &Ctx, p: &Pm) -> MP {
        let (mut x0, y0, mut x1, y1) = c.bounds;
        let d = p.f("staerke") * p.f("lagen");
        if c.ecke {
            x0 -= d;
            x1 += d;
        }
        let h = p.f("hoehe");
        match p.s("art").as_str() {
            "sockel" => rect(x0, y0, x1, y0 + h),
            "trauf" => rect(x0, y1 - h, x1, y1),
            "fries" => fries_shape(x0, x1, y0 + p.f("z"), h, p.f("bogen"), &p.s("form")),
            _ => rect(x0, y0 + p.f("z"), x1, y0 + p.f("z") + h),
        }
    }

    fn band(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let base = match p.s("art").as_str() {
            "sockel" => "Sockel", "trauf" => "Traufgesims", "fries" => "Bogenfries", _ => "Gesims",
        };
        let name = next_name(base)?;
        let walls = walls_for(c, p.b("rundum"))?;
        let all = bodies_bbox()?;
        for w in &walls {
            let nm = if walls.len() > 1 {
                format!("{name} {}", w.wall.rsplit(' ').next().unwrap_or(""))
            } else { name.clone() };
            let g = Self::band_geom(w, p).difference(&occupied(w, &all, &name));
            self.plate_on(w, &nm, &g, p.f("lagen"), p.f("staerke"), 0.0, false)?;
        }
        let wo = if walls.len() > 1 { "rundum".to_string() } else { format!("auf {}", c.wall) };
        Ok(format!("{} {} hoch {wo}", p.s("art"), p.f("hoehe")))
    }

    fn eckquader(&mut self, c: &Ctx, p: &Pm) -> Result<String, PluginError> {
        let name = next_name("Eckquader")?;
        let walls = walls_for(c, true)?;
        let all = bodies_bbox()?;
        let d = p.f("staerke") * p.f("lagen");
        let mut n_ok = 0;
        for w in &walls {
            let (x0, y0, x1, y1) = w.bounds;
            let mut rects = vec![];
            let (mut k, mut y) = (0, y0 + p.f("fuge"));
            while y + p.f("hoehe") <= y1 - p.f("fuge") + 1e-6 {
                let long_row = (k % 2 == 0) == w.ecke;
                let l = if long_row { p.f("lang") } else { p.f("kurz") };
                let ext = if w.ecke { d } else { 0.0 };
                rects.push(rect(x0 - ext, y, x0 + l, y + p.f("hoehe")));
                rects.push(rect(x1 - l, y, x1 + ext, y + p.f("hoehe")));
                y += p.f("hoehe") + p.f("fuge");
                k += 1;
            }
            if rects.is_empty() { continue; }
            let nm = if walls.len() > 1 {
                format!("{name} {}", w.wall.rsplit(' ').next().unwrap_or(""))
            } else { name.clone() };
            let g = union_all(rects).difference(&occupied(w, &all, "Eckquader"));
            if self.plate_on(w, &nm, &g, p.f("lagen"), p.f("staerke"), 0.0, false)?.is_some() {
                n_ok += 1;
            }
        }
        if n_ok == 0 {
            return Err(invalid("wand", "Wand zu niedrig für Eckquader"));
        }
        Ok(format!("{}er Quader, {} Wände", p.f("hoehe"), walls.len()))
    }
}
