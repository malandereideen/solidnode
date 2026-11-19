//! Laser-Palette als SolidCraft-Plugin: Kasten und Fingerzinken.
//! Portiert aus src/solidnode/laser.py (cmds_kasten, _zinken_cmds), aber nur
//! für achsparallele Platten — dafür ohne OCP, nur über Bounding-Boxen.

wit_bindgen::generate!({ path: "wit", world: "command-plugin" });

use craft::plugin::commands;
use craft::plugin::types::{FieldFailure, PluginError};
use exports::craft::plugin::entry::Guest;
use serde_json::{Value, json};

mod baukoerper;
mod dach;
mod wand;

struct Plugin;

type V3 = [f64; 3];

#[derive(Clone, Copy)]
struct Bx {
    lo: V3,
    hi: V3,
}

impl Bx {
    fn ext(&self, i: usize) -> f64 {
        self.hi[i] - self.lo[i]
    }
    fn thin_axis(&self) -> usize {
        (0..3).min_by(|&a, &b| self.ext(a).total_cmp(&self.ext(b))).unwrap()
    }
    fn common(&self, o: &Bx) -> Option<Bx> {
        let mut c = Bx { lo: [0.0; 3], hi: [0.0; 3] };
        for i in 0..3 {
            c.lo[i] = self.lo[i].max(o.lo[i]);
            c.hi[i] = self.hi[i].min(o.hi[i]);
            if c.hi[i] - c.lo[i] < 1e-4 {
                return None;
            }
        }
        Some(c)
    }
}

fn e(i: usize) -> V3 {
    let mut v = [0.0; 3];
    v[i] = 1.0;
    v
}

fn r(x: f64) -> f64 {
    (x * 1e5).round() / 1e5
}

fn run(cmd: &str, args: Value) -> Result<Value, PluginError> {
    let out = commands::run(cmd, &args.to_string())?;
    Ok(serde_json::from_str(&out).unwrap_or(Value::Null))
}

fn sketch_rects(origin: V3, x: V3, y: V3, rects: &[(f64, f64, f64, f64)], name: &str)
    -> Result<(), PluginError> {
    run("sketch.create", json!({"plane": {"origin": origin.map(r), "x_dir": x, "y_dir": y},
                                "name": name}))?;
    for &(x0, y0, x1, y1) in rects {
        run("sketch.rectangle.two_point", json!({"p0": [r(x0), r(y0)], "p1": [r(x1), r(y1)]}))?;
    }
    run("sketch.finish", json!({}))?;
    Ok(())
}

/// Eine Platte als Skizze + Extrusion; gibt den echten Körpernamen zurück.
fn box_plate(name: &str, lo: V3, hi: V3) -> Result<String, PluginError> {
    sketch_rects([0.0, 0.0, lo[2]], e(0), e(1), &[(lo[0], lo[1], hi[0], hi[1])],
                 &format!("Skizze {name}"))?;
    let rep = run("solid.extrude", json!({"distance": r(hi[2] - lo[2]), "operation": "new",
                                          "body_name": name, "name": name}))?;
    Ok(rep["created_bodies"][0].as_str().unwrap_or(name).to_string())
}

fn odd_count(len: f64, target: f64) -> usize {
    let n = ((len / target).round() as usize).max(3);
    if n % 2 == 1 { n } else { n + 1 }
}

/// Fingerzinken zwischen zwei Platten A und B. None, wenn sie keinen Stoß bilden.
fn zinken(mut na: String, mut a: Bx, mut nb: String, mut b: Bx, finger: f64, tag: &str)
    -> Result<Option<usize>, PluginError> {
    let Some(c) = a.common(&b) else { return Ok(None) };
    let (mut ia, mut ib) = (a.thin_axis(), b.thin_axis());
    if ia == ib {
        return Ok(None);
    }
    // Wer behält die Enden? Boden/Deckel (z) vor Front/Rück (y) vor Seiten (x).
    if ib > ia {
        std::mem::swap(&mut na, &mut nb);
        std::mem::swap(&mut a, &mut b);
        std::mem::swap(&mut ia, &mut ib);
    }
    let _ = (a, b);
    let k = 3 - ia - ib;
    let (s0, l) = (c.lo[k], c.ext(k));
    let n = odd_count(l, finger);
    let seg: Vec<(f64, f64)> =
        (0..n).map(|j| (s0 + j as f64 * l / n as f64, s0 + (j + 1) as f64 * l / n as f64)).collect();
    let mut o = [0.0; 3];
    o[ia] = (c.lo[ia] + c.hi[ia]) / 2.0;
    o[ib] = (c.lo[ib] + c.hi[ib]) / 2.0;
    let (ha, hb) = (c.ext(ia) / 2.0, c.ext(ib) / 2.0);
    let ra: Vec<_> = seg.iter().enumerate().filter(|(j, _)| j % 2 == 1)
        .map(|(_, &(x0, x1))| (x0, -hb, x1, hb)).collect();
    let rb: Vec<_> = seg.iter().enumerate().filter(|(j, _)| j % 2 == 0)
        .map(|(_, &(x0, x1))| (x0, -ha, x1, ha)).collect();
    let nm = format!("Zinken {tag} {na}");
    sketch_rects(o, e(k), e(ib), &ra, &nm)?;
    run("solid.extrude", json!({"distance": r(c.ext(ia) + 0.02), "direction": "symmetric",
                                "operation": "cut", "targets": [na], "name": nm}))?;
    let nm = format!("Zinken {tag} {nb}");
    sketch_rects(o, e(k), e(ia), &rb, &nm)?;
    run("solid.extrude", json!({"distance": r(c.ext(ib) + 0.02), "direction": "symmetric",
                                "operation": "cut", "targets": [nb], "name": nm}))?;
    Ok(Some(n))
}

fn bboxes(names: &[String]) -> Result<Vec<(String, Bx)>, PluginError> {
    let m = run("inspect.measure", json!({}))?;
    let mut out = vec![];
    for n in names {
        let b = m["bodies"].as_array().into_iter().flatten()
            .find(|b| b["name"].as_str() == Some(n))
            .ok_or_else(|| invalid("bodies", format!("Körper `{n}` nicht gefunden")))?;
        let v = |k: &str| -> V3 {
            let a = &b["bbox"][k];
            [0, 1, 2].map(|i| a[i].as_f64().unwrap_or(0.0))
        };
        out.push((n.clone(), Bx { lo: v("min"), hi: v("max") }));
    }
    Ok(out)
}

fn zinken_alle(names: &[String], finger: f64, tag: &str) -> Result<usize, PluginError> {
    let bx = bboxes(names)?;
    let mut stoesse = 0;
    for i in 0..bx.len() {
        for j in i + 1..bx.len() {
            let t = format!("{tag}.{}", stoesse + 1);
            if zinken(bx[i].0.clone(), bx[i].1, bx[j].0.clone(), bx[j].1, finger, &t)?.is_some() {
                stoesse += 1;
            }
        }
    }
    Ok(stoesse)
}

fn v3(v: &Value) -> V3 {
    [0, 1, 2].map(|i| v[i].as_f64().unwrap_or(0.0))
}
fn v2(v: &Value) -> [f64; 2] {
    [v[0].as_f64().unwrap_or(0.0), v[1].as_f64().unwrap_or(0.0)]
}
fn add(a: V3, b: V3) -> V3 { [a[0] + b[0], a[1] + b[1], a[2] + b[2]] }
fn mul(a: V3, s: f64) -> V3 { a.map(|x| x * s) }
fn dot(a: V3, b: V3) -> f64 { a[0] * b[0] + a[1] * b[1] + a[2] * b[2] }
fn cross(a: V3, b: V3) -> V3 {
    [a[1] * b[2] - a[2] * b[1], a[2] * b[0] - a[0] * b[2], a[0] * b[1] - a[1] * b[0]]
}

/// Living Hinge: Schlitzmuster um eine Biegelinie (oder im Rechteck mehrerer Linien),
/// durch die Platte unter der Skizze geschnitten. Portiert aus laser.py cmds_hinge.
fn hinge(p: &Value) -> Result<Value, PluginError> {
    let sel: Vec<&Value> = p["linie"].as_array().into_iter().flatten().collect();
    let Some(first) = sel.first() else {
        return Err(invalid("linie", "Biegelinie (Skizzenlinie) auswählen"));
    };
    let sk = run("sketch.inspect", json!({"sketch": first["sketch"]}))?;
    let ids: Vec<&str> = sel.iter().filter(|s| s["sketch"] == first["sketch"])
        .filter_map(|s| s["id"].as_str()).collect();
    let lines: Vec<[[f64; 2]; 2]> = sk["curves"].as_array().into_iter().flatten()
        .filter(|c| c["type"] == "line" && ids.contains(&c["id"].as_str().unwrap_or("")))
        .map(|c| [v2(&c["start_at"]), v2(&c["end_at"])]).collect();
    if lines.is_empty() {
        return Err(invalid("linie", "nur gerade Skizzenlinien"));
    }
    let pl = &sk["world_plane"];
    let (o, xd, yd) = (v3(&pl["origin"]), v3(&pl["x_dir"]), v3(&pl["y_dir"]));
    let n = cross(xd, yd);
    let at = |q: [f64; 2]| add(o, add(mul(xd, q[0]), mul(yd, q[1])));

    // Platte unter der Skizze: dünne Achse parallel zur Normalen, Punkt liegt drin.
    let probe = at(lines[0][0]);
    let m = run("inspect.measure", json!({}))?;
    let mut plate = None;
    for b in m["bodies"].as_array().into_iter().flatten() {
        let bx = Bx { lo: v3(&b["bbox"]["min"]), hi: v3(&b["bbox"]["max"]) };
        let ax = bx.thin_axis();
        if n[ax].abs() < 0.999 { continue; }
        let inside = (0..3).all(|i| probe[i] >= bx.lo[i] - 1e-3 && probe[i] <= bx.hi[i] + 1e-3);
        if inside {
            plate = Some((b["name"].as_str().unwrap_or("").to_string(), bx.ext(ax)));
            break;
        }
    }
    let Some((plate, thickness)) = plate else {
        return Err(invalid("linie", "keine Platte unter der Skizze gefunden"));
    };

    let (radius, winkel) = (num(p, "radius", 15.0), num(p, "winkel", 90.0));
    let (schnitt, steg, abstand, schlitz) = (num(p, "schnitt", 15.0), num(p, "steg", 3.0),
                                              num(p, "abstand", 1.5), num(p, "schlitz", 0.5));
    let (u, length, width, corner);
    if lines.len() == 1 {
        let [p0, p1] = lines[0];
        let d = [p1[0] - p0[0], p1[1] - p0[1]];
        let l = (d[0] * d[0] + d[1] * d[1]).sqrt();
        u = [d[0] / l, d[1] / l];
        length = l;
        width = radius * winkel.to_radians();
        corner = [p0[0] + u[1] * width / 2.0, p0[1] - u[0] * width / 2.0];
    } else {
        let pts: Vec<[f64; 2]> = lines.iter().flat_map(|l| l.iter().copied()).collect();
        let lo = [pts.iter().map(|q| q[0]).fold(f64::MAX, f64::min),
                  pts.iter().map(|q| q[1]).fold(f64::MAX, f64::min)];
        let hi = [pts.iter().map(|q| q[0]).fold(f64::MIN, f64::max),
                  pts.iter().map(|q| q[1]).fold(f64::MIN, f64::max)];
        if hi[0] - lo[0] >= hi[1] - lo[1] {
            u = [1.0, 0.0]; length = hi[0] - lo[0]; width = hi[1] - lo[1]; corner = lo;
        } else {
            u = [0.0, 1.0]; length = hi[1] - lo[1]; width = hi[0] - lo[0]; corner = [hi[0], lo[1]];
        }
    }
    let v = [-u[1], u[0]];
    let mut wo = at(corner);
    let ux = add(mul(xd, u[0]), mul(yd, u[1]));
    let mut vy = add(mul(xd, v[0]), mul(yd, v[1]));
    if dot(cross(ux, vy), n) < 0.0 {
        wo = add(wo, mul(vy, width));
        vy = mul(vy, -1.0);
    }
    let pitch = schnitt + steg;
    let rows = ((width / abstand).floor() as usize).max(2);
    let gap = (width - (rows - 1) as f64 * abstand) / 2.0;
    let mut rects = vec![];
    for row in 0..rows {
        let y = gap + row as f64 * abstand;
        let mut x = -(if row % 2 == 1 { 0.0 } else { pitch / 2.0 }) - pitch;
        while x < length {
            let (x0, x1) = (x.max(-2.0 * steg), (x + schnitt).min(length + 2.0 * steg));
            if x1 - x0 > steg {
                rects.push((x0, y - schlitz / 2.0, x1, y + schlitz / 2.0));
            }
            x += pitch;
        }
    }
    let name = "Living Hinge";
    sketch_rects(wo, ux, vy, &rects, &format!("{name} Skizze"))?;
    run("solid.extrude", json!({"distance": r(thickness * 2.0 + 2.0), "direction": "symmetric",
                                "operation": "cut", "targets": [plate], "name": name}))?;
    Ok(json!({"platte": plate, "zone": [r(width), r(length)], "schlitze": rects.len()}))
}

fn num(p: &Value, k: &str, d: f64) -> f64 {
    p[k].as_f64().unwrap_or(d)
}

impl Guest for Plugin {
    fn execute(entry: String, params: String) -> Result<String, PluginError> {
        let p: Value = serde_json::from_str(&params).map_err(|e| invalid("params", e))?;
        match entry.as_str() {
            "kasten" => {
                let (bb, tt, hh) = (num(&p, "breite", 120.0), num(&p, "tiefe", 80.0),
                                    num(&p, "hoehe", 60.0));
                let t = num(&p, "staerke", 3.0);
                if bb <= 2.0 * t || tt <= 2.0 * t || hh <= 2.0 * t {
                    return Err(invalid("staerke", "Kasten zu klein für diese Materialstärke"));
                }
                let mut teile = vec![
                    ("Boden", [0.0, 0.0, 0.0], [bb, tt, t]),
                    ("Front", [0.0, 0.0, 0.0], [bb, t, hh]),
                    ("Rueckwand", [0.0, tt - t, 0.0], [bb, tt, hh]),
                    ("Seite links", [0.0, 0.0, 0.0], [t, tt, hh]),
                    ("Seite rechts", [bb - t, 0.0, 0.0], [bb, tt, hh]),
                ];
                if p["deckel"].as_bool().unwrap_or(false) {
                    teile.push(("Deckel", [0.0, 0.0, hh - t], [bb, tt, hh]));
                }
                let mut namen = vec![];
                for (n, lo, hi) in &teile {
                    namen.push(box_plate(&format!("Kasten {n}"), *lo, *hi)?);
                }
                let stoesse = if p["zinken"].as_bool().unwrap_or(true) {
                    zinken_alle(&namen, num(&p, "zinke", 10.0), "K")?
                } else { 0 };
                Ok(json!({"platten": namen, "stoesse": stoesse}).to_string())
            }
            "hinge" => Ok(hinge(&p)?.to_string()),
            "zinken" => {
                let names: Vec<String> = p["platten"].as_array().into_iter().flatten()
                    .filter_map(|x| x.as_str().or(x["name"].as_str()).or(x["body"].as_str()))
                    .map(String::from).collect();
                if names.len() < 2 {
                    return Err(invalid("platten", "mindestens zwei Platten auswählen"));
                }
                let n = zinken_alle(&names, num(&p, "zinke", 10.0), "Z")?;
                if n == 0 {
                    return Err(PluginError::InvalidInput(FieldFailure { field: "platten".into(), reason: 
                        "Keine Stöße gefunden: Platten müssen sich überlappen und \
                         rechtwinklig stehen".into() }));
                }
                Ok(json!({"stoesse": n}).to_string())
            }
            e => baukoerper::execute(e, &p)
                .or_else(|| dach::execute(e, &p))
                .or_else(|| wand::execute(e, &p))
                .unwrap_or_else(|| Err(invalid("entry", format!("no entry `{e}`"))))
                .map(|v| v.to_string()),
        }
    }
}

fn invalid(field: &str, reason: impl ToString) -> PluginError {
    PluginError::InvalidInput(FieldFailure { field: field.into(), reason: reason.to_string() })
}

export!(Plugin);
