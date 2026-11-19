//! Kategorie Baukörper (laser_haus.py, laser_extra.py Rundturm, laser_bauten.py).
//! Portiert 1:1 aus der Python-Palette; Lage per Zahlenfeld x/y/z, Bezug
//! (Gebäude, Wand) per Pick. Jeder Lauf legt neu an.

use crate::craft::plugin::types::PluginError;
use crate::{add, box_plate, cross, dot, invalid, mul, num, r, run, v3, Bx, V3};
use serde_json::{json, Value};
use std::f64::consts::PI;

type Res<T> = Result<T, PluginError>;

/// None = Eintrag gehört nicht zu diesem Modul.
pub fn execute(entry: &str, p: &Value) -> Option<Result<Value, PluginError>> {
    // Voreinstellungen wie im Katalog der Palette (fehlende Felder werden ergänzt)
    let (preset, label): (Value, &str) = match entry {
        "haus" => (json!({"dach": "sattel"}), "Haus"),
        "walmhaus" => (json!({"dach": "walm", "neigung": 40}), "Walmhaus"),
        "anbau" => (json!({"dach": "pult", "neigung": 25, "breite": 40}), "Anbau"),
        "burghaus" => (json!({"dach": "flach", "zinnen": true}), "Burghaus"),
        "turm" => (json!({"dach": "zinnen"}), "Turm"),
        "zeltturm" => (json!({"dach": "zelt"}), "Zeltdachturm"),
        "rundturm" => (json!({"dach": "zinnen"}), "Rundturm"),
        "kegelturm" => (json!({"dach": "kegel"}), "Kegelturm"),
        _ => (json!({}), ""),
    };
    let mut q = p.clone();
    if let (Some(m), Some(pr)) = (q.as_object_mut(), preset.as_object()) {
        for (k, v) in pr { m.entry(k.clone()).or_insert(v.clone()); }
        m.insert("_label".into(), json!(label));
    }
    let p = &q;
    let r = match entry {
        "haus" | "walmhaus" | "anbau" | "burghaus" => haus(p),
        "turm" | "zeltturm" => turm(p),
        "rundturm" | "kegelturm" => rundturm(p),
        "ecktuerme" => ecktuerme(p),
        "podest" => podest(p),
        "apsis" => apsis(p),
        "pagode" => pagode(p),
        "muehle" => muehle(p),
        "leuchtturm" => leuchtturm(p),
        "steinbruecke" => steinbruecke(p),
        "fachwerk" => fachwerkbruecke(p),
        _ => return None,
    };
    Some(r)
}

// ------------------------------------------------------------ Vektoren

fn sub(a: V3, b: V3) -> V3 { [a[0] - b[0], a[1] - b[1], a[2] - b[2]] }
fn norm(a: V3) -> f64 { dot(a, a).sqrt() }
fn unit(a: V3) -> V3 { mul(a, 1.0 / norm(a)) }
fn f6(a: V3) -> [f64; 3] { a.map(|x| (x * 1e6).round() / 1e6) }
fn r4(x: f64) -> f64 { (x * 1e4).round() / 1e4 }
const Z: V3 = [0.0, 0.0, 1.0];

fn boolp(p: &Value, k: &str, d: bool) -> bool { p[k].as_bool().unwrap_or(d) }
fn strp<'a>(p: &'a Value, k: &str, d: &'a str) -> &'a str { p[k].as_str().unwrap_or(d) }
fn origin(p: &Value) -> V3 { [num(p, "x", 0.0), num(p, "y", 0.0), num(p, "z", 0.0)] }
fn lagen(h: f64, t: f64) -> f64 { ((h / t).round()).max(1.0) * t }

// ------------------------------------------------------------ Namen

fn body_names() -> Res<Vec<String>> {
    let d = run("document.inspect", json!({"bodies": "names"}))?;
    Ok(d["bodies"].as_array().into_iter().flatten()
        .filter_map(|b| b["name"].as_str().or(b.as_str()).map(String::from)).collect())
}

/// „Haus“, „Haus 2“, „Haus 3“ … — der erste Name, mit dem noch kein Körper beginnt.
fn new_name(typ: &str) -> Res<String> {
    let names = body_names()?;
    let mut n = 1;
    loop {
        let cand = if n == 1 { typ.to_string() } else { format!("{typ} {n}") };
        let pre = format!("{cand} ");
        if !names.iter().any(|b| b.starts_with(&pre) || *b == cand) {
            return Ok(cand);
        }
        n += 1;
    }
}

// ------------------------------------------------------------ Bausteine

struct Out {
    bodies: Vec<String>,
}
impl Out {
    fn new() -> Self { Out { bodies: vec![] } }
    fn push(&mut self, n: String) { self.bodies.push(n) }
    fn done(self, info: String) -> Res<Value> {
        Ok(json!({"koerper": self.bodies, "info": info}))
    }
}

fn created(rep: &Value, name: &str) -> String {
    rep["created_bodies"][0].as_str().unwrap_or(name).to_string()
}

/// Ebenes Polygon (Weltpunkte) als Platte; wächst entlang n_out (oder nach innen).
fn plate3d(name: &str, pts: &[V3], n_out: V3, t: f64, inward: bool, holes: &[Vec<V3>])
    -> Res<String> {
    let n = unit(n_out);
    let x = unit(sub(pts[1], pts[0]));
    let y = cross(n, x);
    let o = pts[0];
    let loc = |q: V3| { let d = sub(q, o); [r4(dot(d, x)), r4(dot(d, y))] };
    run("sketch.create", json!({"plane": {"origin": f6(o), "x_dir": f6(x), "y_dir": f6(y)},
                                "name": format!("{name} Skizze")}))?;
    let mut loops: Vec<&[V3]> = vec![pts];
    for h in holes { loops.push(h); }
    for lp in loops {
        let mut q: Vec<[f64; 2]> = lp.iter().map(|&p| loc(p)).collect();
        q.push(q[0]);
        run("sketch.line", json!({"points": q}))?;
    }
    run("sketch.finish", json!({}))?;
    let rep = run("solid.extrude", json!({"distance": r4(t), "operation": "new",
        "direction": if inward { "negative" } else { "positive" },
        "body_name": name, "name": name}))?;
    Ok(created(&rep, name))
}

/// Grundrissfläche senkrecht von oben aus Körpern schneiden.
fn cut_plan(name: &str, poly: &[[f64; 2]], z_top: f64, depth: f64, targets: &[String]) -> Res<()> {
    run("sketch.create", json!({"plane": {"origin": [0, 0, r4(z_top)], "x_dir": [1, 0, 0],
                                "y_dir": [0, 1, 0]}, "name": format!("{name} Skizze")}))?;
    let mut q: Vec<[f64; 2]> = poly.iter().map(|p| [r4(p[0]), r4(p[1])]).collect();
    q.push(q[0]);
    run("sketch.line", json!({"points": q}))?;
    run("sketch.finish", json!({}))?;
    run("solid.extrude", json!({"distance": r4(depth), "direction": "negative",
        "operation": "cut", "targets": targets, "name": name}))?;
    Ok(())
}

/// Rechteck in Wandkoordinaten (x längs, z hoch) durch eine Wand schneiden.
fn plate_cut(a: V3, x: V3, rect: (f64, f64, f64, f64), t: f64, target: &str, nm: &str) -> Res<()> {
    let (x0, z0, x1, z1) = rect;
    let o = add(add(a, mul(x, x0)), mul(Z, z0));
    run("sketch.create", json!({"plane": {"origin": f6(o), "x_dir": f6(x), "y_dir": [0, 0, 1]},
                                "name": format!("{nm} Skizze")}))?;
    run("sketch.rectangle.two_point", json!({"p0": [0, 0], "p1": [r4(x1 - x0), r4(z1 - z0)]}))?;
    run("sketch.finish", json!({}))?;
    run("solid.extrude", json!({"distance": r4(t * 3.0), "direction": "symmetric",
        "operation": "cut", "targets": [target], "name": nm}))?;
    Ok(())
}

/// Profil (r, z) um die senkrechte Achse durch c drehen.
fn revolve(nm: &str, c: V3, prof: &[[f64; 2]]) -> Res<String> {
    run("sketch.create", json!({"plane": {"origin": f6([c[0], c[1], 0.0]), "x_dir": [1, 0, 0],
                                "y_dir": [0, 0, 1]}, "name": format!("{nm} Skizze")}))?;
    let mut q: Vec<[f64; 2]> = prof.iter().map(|p| [r4(p[0]), r4(p[1])]).collect();
    q.push(q[0]);
    run("sketch.line", json!({"points": q}))?;
    run("sketch.finish", json!({}))?;
    let rep = run("solid.revolve", json!({"axis": {"origin": f6([c[0], c[1], 0.0]), "dir": [0, 0, 1]},
        "operation": "new", "body_name": nm, "name": nm}))?;
    Ok(created(&rep, nm))
}

fn solid(nm: &str, cmd: &str, radius: f64, height: f64, base: V3) -> Res<String> {
    let rep = run(cmd, json!({"radius": r4(radius), "height": r4(height), "base": f6(base),
        "operation": "new", "body_name": nm, "name": nm}))?;
    Ok(created(&rep, nm))
}

fn disk(nm: &str, c: V3, rad: f64, z: f64, t: f64) -> Res<String> {
    run("sketch.create", json!({"plane": {"origin": [0, 0, r4(z)], "x_dir": [1, 0, 0],
                                "y_dir": [0, 1, 0]}, "name": format!("{nm} Skizze")}))?;
    run("sketch.circle.center", json!({"center": [r4(c[0]), r4(c[1])], "radius": r4(rad)}))?;
    run("sketch.finish", json!({}))?;
    let rep = run("solid.extrude", json!({"distance": r4(t), "operation": "new",
        "body_name": nm, "name": nm}))?;
    Ok(created(&rep, nm))
}

/// Aussparungen der Zinnen an einer Mauerkrone (Rechtecke x0, z0, x1, z1).
fn zinnen_cuts(x0: f64, x1: f64, top: f64, hp: f64, breite: f64) -> Vec<(f64, f64, f64, f64)> {
    let zb = if breite > 0.0 { breite } else { hp.max(4.0) };
    let mut n = (((x1 - x0) / zb).round() as usize).max(3);
    if n % 2 == 0 { n += 1; }
    let w = (x1 - x0) / n as f64;
    (1..n).step_by(2).map(|i| (x0 + i as f64 * w, top - hp, x0 + (i + 1) as f64 * w, top + 1.0))
        .collect()
}

fn poly_ang(n: usize) -> Vec<f64> {
    (0..n).map(|i| 2.0 * PI * (i as f64 + 0.5) / n as f64).collect()
}

/// Vieleckwände (außen Radius R), stumpf gestoßen; hole(L, h) → Fenster.
fn ring_walls(out: &mut Out, name: &str, c: V3, n: usize, rr: f64, z0: f64, h: f64, t: f64,
              hole: Option<&dyn Fn(f64, f64) -> Option<(f64, f64, f64, f64)>>, prefix: &str)
    -> Res<()> {
    let v: Vec<V3> = poly_ang(n).iter()
        .map(|q| [c[0] + rr * q.cos(), c[1] + rr * q.sin(), z0]).collect();
    let trim = t / (2.0 * PI / n as f64).sin();
    for i in 0..n {
        let (a0, b) = (v[i], v[(i + 1) % n]);
        let mid = sub(mul(add(a0, b), 0.5), [c[0], c[1], z0]);
        let n_out = unit([mid[0], mid[1], 0.0]);
        let x = unit(sub(b, a0));
        let a = add(a0, mul(x, trim));
        let pts = [a, b, add(b, mul(Z, h)), add(a, mul(Z, h))];
        let mut holes = vec![];
        if let Some(hf) = hole {
            let l = norm(sub(b, a));
            if let Some((x0, h0, x1, h1)) = hf(l, h) {
                let w = |xx: f64, zz: f64| add(add(a, mul(x, xx)), mul(Z, zz));
                holes.push(vec![w(x0, h0), w(x1, h0), w(x1, h1), w(x0, h1)]);
            }
        }
        out.push(plate3d(&format!("{name} {prefix} {}", i + 1), &pts, n_out, t, true, &holes)?);
    }
    Ok(())
}

/// Zeltdach aus n Dreiecken; gibt die Spitze zurück.
fn zelt(out: &mut Out, name: &str, c: V3, n: usize, rr: f64, z_eave: f64, a: f64, ov: f64,
        t: f64, prefix: &str) -> Res<V3> {
    let ro = rr + ov / (PI / n as f64).cos();
    let ze = z_eave - ov * a.tan();
    let apex = [c[0], c[1], z_eave + rr * (PI / n as f64).cos() * a.tan()];
    let vo: Vec<V3> = poly_ang(n).iter()
        .map(|q| [c[0] + ro * q.cos(), c[1] + ro * q.sin(), ze]).collect();
    for i in 0..n {
        let (p0, p1) = (vo[i], vo[(i + 1) % n]);
        let mid = sub(mul(add(p0, p1), 0.5), [c[0], c[1], ze]);
        let nh = unit([mid[0], mid[1], 0.0]);
        let n_out = add(mul(nh, a.sin()), [0.0, 0.0, a.cos()]);
        out.push(plate3d(&format!("{name} {prefix} {}", i + 1), &[p0, p1, apex], n_out, t, false, &[])?);
    }
    Ok(apex)
}

/// Walm-/Zeltdach über dem Rechteck o…o+(B,T), Traufe auf H; gibt Firsthöhe zurück.
fn walm_plates(out: &mut Out, name: &str, o: V3, b: f64, tt: f64, h: f64, a: f64, ov: f64,
               t: f64, prefix: &str) -> Res<f64> {
    let (ta, s, c) = (a.tan(), a.sin(), a.cos());
    let ze = h - ov * ta;
    let pp = |x: f64, y: f64, z: f64| [o[0] + x, o[1] + y, o[2] + z];
    let e = [pp(-ov, -ov, ze), pp(b + ov, -ov, ze), pp(b + ov, tt + ov, ze), pp(-ov, tt + ov, ze)];
    let (zr, faces): (f64, Vec<(&str, Vec<V3>, V3)>) = if b >= tt {
        let zr = h + tt / 2.0 * ta;
        let rr = [pp(tt / 2.0, tt / 2.0, zr), pp(b - tt / 2.0, tt / 2.0, zr)];
        (zr, vec![("vorn", vec![e[0], e[1], rr[1], rr[0]], [0.0, -s, c]),
                  ("hinten", vec![e[2], e[3], rr[0], rr[1]], [0.0, s, c]),
                  ("rechts", vec![e[1], e[2], rr[1]], [s, 0.0, c]),
                  ("links", vec![e[3], e[0], rr[0]], [-s, 0.0, c])])
    } else {
        let zr = h + b / 2.0 * ta;
        let rr = [pp(b / 2.0, b / 2.0, zr), pp(b / 2.0, tt - b / 2.0, zr)];
        (zr, vec![("vorn", vec![e[0], e[1], rr[0]], [0.0, -s, c]),
                  ("hinten", vec![e[2], e[3], rr[1]], [0.0, s, c]),
                  ("rechts", vec![e[1], e[2], rr[1], rr[0]], [s, 0.0, c]),
                  ("links", vec![e[3], e[0], rr[0], rr[1]], [-s, 0.0, c])])
    };
    for (nm, pts, n) in faces {
        let mut clean = vec![pts[0]];
        for &q in &pts[1..] {
            if norm(sub(q, *clean.last().unwrap())) > 1e-6 { clean.push(q); }
        }
        if clean.len() >= 3 && norm(sub(*clean.last().unwrap(), clean[0])) < 1e-6 { clean.pop(); }
        if clean.len() < 3 { continue; }
        out.push(plate3d(&format!("{name} {prefix} {nm}"), &clean, n, t, false, &[])?);
    }
    Ok(zr)
}

/// Kreuz als stehende Platte auf der Spitze.
fn kreuz(out: &mut Out, name: &str, apex: V3, h: f64, t: f64, a: Option<f64>) -> Res<()> {
    let apex = match a { Some(a) => add(apex, [0.0, 0.0, t / a.cos()]), None => apex };
    let b = (h * 0.12).max(1.2);
    let arm = h * 0.6;
    let (y0, y1) = (h * 0.58, h * 0.58 + b);
    let (bb, aa) = (b / 2.0, arm / 2.0);
    let ring = [(-bb, 0.0), (bb, 0.0), (bb, y0), (aa, y0), (aa, y1), (bb, y1), (bb, h),
                (-bb, h), (-bb, y1), (-aa, y1), (-aa, y0), (-bb, y0)];
    let o = sub(apex, [0.0, t / 2.0, 0.0]);
    let pts: Vec<V3> = ring.iter().map(|&(x, z)| add(o, [x, 0.0, z])).collect();
    out.push(plate3d(&format!("{name} Kreuz"), &pts, [0.0, 1.0, 0.0], t, false, &[])?);
    Ok(())
}

/// Umriss Rundbogen (Unterkante y0, Scheitel top) wie laser_geom.arch_poly „bogen“:
/// Punkte von rechts unten über den Bogen nach links unten.
fn arch_bogen(cx: f64, y0: f64, w: f64, top: f64) -> Vec<[f64; 2]> {
    let (rr, h) = (w / 2.0, top - y0);
    let rise = if h >= rr { rr } else { h * 0.6 };
    let ys = top - rise;
    (0..33).map(|i| { let th = PI * i as f64 / 32.0; [cx + rr * th.cos(), ys + rise * th.sin()] })
        .collect()
}

// ------------------------------------------------------------ Bezug per Pick

fn measure_all() -> Res<Vec<(String, Bx)>> {
    let m = run("inspect.measure", json!({}))?;
    Ok(m["bodies"].as_array().into_iter().flatten().map(|b| {
        (b["name"].as_str().unwrap_or("").to_string(),
         Bx { lo: v3(&b["bbox"]["min"]), hi: v3(&b["bbox"]["max"]) })
    }).collect())
}

fn pick_names(p: &Value, k: &str) -> Vec<String> {
    p[k].as_array().into_iter().flatten()
        .filter_map(|x| x.as_str().or(x["name"].as_str()).or(x["body"].as_str()))
        .map(String::from).collect()
}

const TEILE: [&str; 6] = ["Boden", "Front", "Rueckwand", "Seite links", "Seite rechts", "Deckel"];

/// Gebäude (Kasten/Haus) aus einem angeklickten Körper: Präfix vor dem Teilnamen,
/// dann alle Körper mit diesem Präfix. Liefert (Ursprung, B, T, Wandoberkante, Schrägdach?).
struct Host { o: V3, b: f64, t: f64, top: f64, schraeg: bool, name: String }

fn host(p: &Value, k: &str) -> Res<Option<Host>> {
    let picks = pick_names(p, k);
    let Some(first) = picks.first() else { return Ok(None) };
    let all = measure_all()?;
    let prefix = TEILE.iter().chain(["Dach"].iter())
        .find_map(|t| first.find(&format!(" {t}")).map(|i| first[..i].to_string()))
        .unwrap_or_else(|| first.clone());
    let pre = format!("{prefix} ");
    let mine: Vec<&(String, Bx)> = all.iter()
        .filter(|(n, _)| n.starts_with(&pre) || picks.contains(n)).collect();
    let walls: Vec<&Bx> = mine.iter()
        .filter(|(n, _)| ["Front", "Rueckwand", "Seite links", "Seite rechts"].iter()
            .any(|t| n.ends_with(t)))
        .map(|(_, b)| b).collect();
    let use_: Vec<&Bx> = if walls.is_empty() { mine.iter().map(|(_, b)| b).collect() } else { walls };
    if use_.is_empty() { return Ok(None); }
    let mut lo = [f64::MAX; 3];
    let mut hi = [f64::MIN; 3];
    for b in &use_ { for i in 0..3 { lo[i] = lo[i].min(b.lo[i]); hi[i] = hi[i].max(b.hi[i]); } }
    let front_top = mine.iter().find(|(n, _)| n.ends_with("Front")).map(|(_, b)| b.hi[2]);
    let schraeg = mine.iter().any(|(n, b)| n.contains(" Dach") && b.thin_axis() != 2);
    Ok(Some(Host { o: lo, b: hi[0] - lo[0], t: hi[1] - lo[1], top: front_top.unwrap_or(hi[2]),
                   schraeg, name: prefix }))
}

fn frame_up(n: V3) -> (V3, V3) {
    let mut up = Z;
    if dot(up, n).abs() > 0.9 { up = [0.0, 1.0, 0.0]; }
    let up = unit(sub(up, mul(n, dot(up, n))));
    (cross(up, n), up)
}

/// Wand-Kontext aus einem Flächen-Pick (achsparallele Platte): Ursprung auf der
/// Außenfläche am Klickpunkt, right/up/n, Umriss-Grenzen in Wandkoordinaten.
struct Wall { p: V3, right: V3, up: V3, n: V3, bounds: [f64; 4], name: String }

fn wall_ctx(p: &Value, k: &str) -> Res<Wall> {
    let Some(f) = p[k].as_array().and_then(|a| a.first()) else {
        return Err(invalid(k, "Wandfläche anklicken"));
    };
    let body = f["body"].as_str().or(f["name"].as_str()).unwrap_or("").to_string();
    let pt = v3(&f["point"]);
    let all = measure_all()?;
    let Some((_, bx)) = all.iter().find(|(n, _)| *n == body) else {
        return Err(invalid(k, format!("Körper `{body}` nicht gefunden")));
    };
    let ax = bx.thin_axis();
    let mut n = crate::e(ax);
    let (dmin, dmax) = (bx.lo[ax], bx.hi[ax]);
    let mut outer = dmax;
    if (pt[ax] - dmin).abs() < (pt[ax] - dmax).abs() { n = mul(n, -1.0); outer = dmin; }
    let mut pp = pt;
    pp[ax] = outer;
    let (right, up) = frame_up(n);
    let mut b = [f64::MAX, f64::MAX, f64::MIN, f64::MIN];
    for i in 0..8 {
        let c = [if i & 1 == 0 { bx.lo[0] } else { bx.hi[0] },
                 if i & 2 == 0 { bx.lo[1] } else { bx.hi[1] },
                 if i & 4 == 0 { bx.lo[2] } else { bx.hi[2] }];
        let d = sub(c, pp);
        let (x, y) = (dot(d, right), dot(d, up));
        b = [b[0].min(x), b[1].min(y), b[2].max(x), b[3].max(y)];
    }
    Ok(Wall { p: pp, right, up, n, bounds: b, name: body })
}

// ------------------------------------------------------------ Haus

fn haus(p: &Value) -> Res<Value> {
    let name = new_name(strp(p, "_label", "Haus"))?;
    let (bb, tt, hh, t) = (num(p, "breite", 100.0), num(p, "tiefe", 70.0),
                           num(p, "hoehe", 60.0), num(p, "staerke", 3.0));
    let a = num(p, "neigung", 45.0).to_radians();
    let ta = a.tan();
    let ov = num(p, "ueberstand", 5.0);
    let o = origin(p);
    let dach = strp(p, "dach", "sattel");
    let mut out = Out::new();
    let at = |x: f64, y: f64, z: f64| [o[0] + x, o[1] + y, o[2] + z];
    if dach == "walm" && bb < tt {
        return Err(invalid("breite", "Walmdach: Breite muss ≥ Tiefe sein"));
    }
    if boolp(p, "boden", true) {
        out.push(box_plate(&format!("{name} Boden"), o, at(bb, tt, t))?);
    }
    let zh = if dach == "flach" && boolp(p, "zinnen", false) { num(p, "zinnen_h", 8.0) } else { 0.0 };
    let hv = hh;
    let hr = if dach == "pult" { hh + (tt - t) * ta } else { hh };
    out.push(box_plate(&format!("{name} Front"), o, at(bb, t, hv + zh))?);
    out.push(box_plate(&format!("{name} Rueckwand"), at(0.0, tt - t, 0.0), at(bb, tt, hr + zh))?);
    for (side, x0, nx) in [("Seite links", 0.0, -1.0), ("Seite rechts", bb, 1.0)] {
        let pp = |y: f64, z: f64| at(x0, y, z);
        let poly = match dach {
            "sattel" => vec![pp(0.0, 0.0), pp(tt, 0.0), pp(tt, hh), pp(tt / 2.0, hh + tt / 2.0 * ta), pp(0.0, hh)],
            "pult" => vec![pp(0.0, 0.0), pp(tt, 0.0), pp(tt, hh + tt * ta), pp(0.0, hh)],
            _ => vec![pp(0.0, 0.0), pp(tt, 0.0), pp(tt, hh + zh), pp(0.0, hh + zh)],
        };
        out.push(plate3d(&format!("{name} {side}"), &poly, [nx, 0.0, 0.0], t, true, &[])?);
    }
    let ze = hh - ov * ta;
    let (r0, r1) = (o[0] - ov, o[0] + bb + ov);
    let (s, c) = (a.sin(), a.cos());
    match dach {
        "sattel" => {
            let zr = hh + tt / 2.0 * ta;
            out.push(plate3d(&format!("{name} Dach vorn"), &[
                [r0, o[1] - ov, o[2] + ze], [r1, o[1] - ov, o[2] + ze],
                [r1, o[1] + tt / 2.0, o[2] + zr], [r0, o[1] + tt / 2.0, o[2] + zr]],
                [0.0, -s, c], t, false, &[])?);
            out.push(plate3d(&format!("{name} Dach hinten"), &[
                [r1, o[1] + tt + ov, o[2] + ze], [r0, o[1] + tt + ov, o[2] + ze],
                [r0, o[1] + tt / 2.0, o[2] + zr], [r1, o[1] + tt / 2.0, o[2] + zr]],
                [0.0, s, c], t, false, &[])?);
        }
        "pult" => {
            let zb = hh + (tt + ov) * ta;
            out.push(plate3d(&format!("{name} Dach"), &[
                [r0, o[1] - ov, o[2] + ze], [r1, o[1] - ov, o[2] + ze],
                [r1, o[1] + tt + ov, o[2] + zb], [r0, o[1] + tt + ov, o[2] + zb]],
                [0.0, -s, c], t, false, &[])?);
        }
        "walm" => {
            let zr = hh + tt / 2.0 * ta;
            let e = [at(-ov, -ov, ze), at(bb + ov, -ov, ze), at(bb + ov, tt + ov, ze), at(-ov, tt + ov, ze)];
            let rr = [at(tt / 2.0, tt / 2.0, zr), at(bb - tt / 2.0, tt / 2.0, zr)];
            out.push(plate3d(&format!("{name} Dach vorn"), &[e[0], e[1], rr[1], rr[0]], [0.0, -s, c], t, false, &[])?);
            out.push(plate3d(&format!("{name} Dach hinten"), &[e[2], e[3], rr[0], rr[1]], [0.0, s, c], t, false, &[])?);
            out.push(plate3d(&format!("{name} Dach rechts"), &[e[1], e[2], rr[1]], [s, 0.0, c], t, false, &[])?);
            out.push(plate3d(&format!("{name} Dach links"), &[e[3], e[0], rr[0]], [-s, 0.0, c], t, false, &[])?);
        }
        _ => {
            out.push(box_plate(&format!("{name} Dach"), at(0.0, 0.0, hh - t), at(bb, tt, hh))?);
            if zh > 0.0 {
                // Kasten-Wände: (Name, Normale, right, Ursprung, Länge)
                let walls: [(&str, V3, V3, V3, f64); 4] = [
                    ("Front", [0.0, -1.0, 0.0], [1.0, 0.0, 0.0], o, bb),
                    ("Rueckwand", [0.0, 1.0, 0.0], [-1.0, 0.0, 0.0], at(bb, tt, 0.0), bb),
                    ("Seite links", [-1.0, 0.0, 0.0], [0.0, -1.0, 0.0], at(0.0, tt, 0.0), tt),
                    ("Seite rechts", [1.0, 0.0, 0.0], [0.0, 1.0, 0.0], at(bb, 0.0, 0.0), tt)];
                for (wn, _n, right, po, l) in walls {
                    let cuts = zinnen_cuts(0.0, l, hh + zh, zh, num(p, "zinnen_b", 8.0));
                    let rects: Vec<(f64, f64, f64, f64)> = cuts.clone();
                    let nm = format!("{name} {wn} Zinnen");
                    crate::sketch_rects(po, right, Z, &rects, &format!("{nm} Skizze"))?;
                    run("solid.extrude", json!({"distance": r(t + 1.0), "direction": "negative",
                        "operation": "cut", "targets": [format!("{name} {wn}")], "name": nm}))?;
                }
            }
        }
    }
    let mut info = format!("{bb}×{tt}×{hh}, {dach}dach");
    if zh > 0.0 { info += ", Zinnen"; }
    out.done(info)
}

// ------------------------------------------------------------ Vieleckturm

fn turm(p: &Value) -> Res<Value> {
    let name = new_name(strp(p, "_label", "Turm"))?;
    let n = num(p, "ecken", 8.0) as usize;
    let (d, hh, t) = (num(p, "durchmesser", 50.0), num(p, "hoehe", 90.0), num(p, "staerke", 3.0));
    let dach = strp(p, "dach", "zelt");
    let c = origin(p);
    let rr = d / 2.0;
    let ang = poly_ang(n);
    let v: Vec<V3> = ang.iter().map(|q| add(c, [rr * q.cos(), rr * q.sin(), 0.0])).collect();
    let zh = if dach == "zinnen" { num(p, "zinnen_h", 8.0) } else { 0.0 };
    let mut out = Out::new();
    let trim = t / (2.0 * PI / n as f64).sin();
    for i in 0..n {
        let (a0, b) = (v[i], v[(i + 1) % n]);
        let mid = sub(mul(add(a0, b), 0.5), c);
        let n_out = unit([mid[0], mid[1], 0.0]);
        let x = unit(sub(b, a0));
        let a = add(a0, mul(x, trim));
        let nm = format!("{name} Wand {}", i + 1);
        let ht = hh + zh;
        let nm = plate3d(&nm, &[a, b, add(b, [0.0, 0.0, ht]), add(a, [0.0, 0.0, ht])], n_out, t, true, &[])?;
        if zh > 0.0 {
            let l = norm(sub(b, a));
            for (k, rc) in zinnen_cuts(0.0, l, ht, zh, num(p, "zinnen_b", 6.0)).into_iter().enumerate() {
                plate_cut(a, x, rc, t, &nm, &format!("{nm} Zinne {}", k + 1))?;
            }
        }
        out.push(nm);
    }
    let ri = rr - t / (PI / n as f64).cos();
    let vi: Vec<V3> = ang.iter().map(|q| add(c, [ri * q.cos(), ri * q.sin(), 0.0])).collect();
    if boolp(p, "boden", true) {
        out.push(plate3d(&format!("{name} Boden"), &vi, Z, t, false, &[])?);
    }
    if dach == "zelt" {
        let a = num(p, "neigung", 60.0).to_radians();
        zelt(&mut out, &name, c, n, rr, c[2] + hh, a, num(p, "ueberstand", 3.0), t, "Dach")?;
    } else {
        let top: Vec<V3> = vi.iter().map(|&q| add(q, [0.0, 0.0, hh - t])).collect();
        out.push(plate3d(&format!("{name} Dach"), &top, Z, t, false, &[])?);
    }
    out.done(format!("{n}-Eck Ø{d}×{hh}, {dach}"))
}

// ------------------------------------------------------------ Rundturm

fn rundturm(p: &Value) -> Res<Value> {
    let name = new_name(strp(p, "_label", "Rundturm"))?;
    let (rr, hh, t) = (num(p, "durchmesser", 44.0) / 2.0, num(p, "hoehe", 80.0), num(p, "staerke", 3.0));
    let c = origin(p);
    let dach = strp(p, "dach", "kegel");
    let zh = if dach == "zinnen" { num(p, "zinnen_h", 8.0) } else { 0.0 };
    let z0 = c[2];
    let mut out = Out::new();
    let mantel = format!("{name} Mantel");
    run("sketch.create", json!({"plane": {"origin": [0, 0, r4(z0)], "x_dir": [1, 0, 0], "y_dir": [0, 1, 0]},
                                "name": format!("{mantel} Skizze")}))?;
    run("sketch.circle.center", json!({"center": [r4(c[0]), r4(c[1])], "radius": r4(rr)}))?;
    run("sketch.circle.center", json!({"center": [r4(c[0]), r4(c[1])], "radius": r4(rr - t)}))?;
    run("sketch.finish", json!({}))?;
    let rep = run("solid.extrude", json!({"distance": r4(hh + zh), "operation": "new",
        "body_name": mantel, "name": mantel}))?;
    let mantel = created(&rep, &mantel);
    out.push(mantel.clone());
    if zh > 0.0 {
        let zb = num(p, "zinnen_b", 6.0);
        let mut n = ((2.0 * PI * rr / zb).round() as usize).max(3);
        if n % 2 == 1 { n += 1; }
        let dz = 2.0 * PI / n as f64;
        run("sketch.create", json!({"plane": {"origin": [0, 0, r4(z0 + hh + zh + 1.0)], "x_dir": [1, 0, 0],
            "y_dir": [0, 1, 0]}, "name": format!("{name} Zinnen Skizze")}))?;
        for k in (0..n).step_by(2) {
            let (a0, a1) = (k as f64 * dz, (k + 1) as f64 * dz);
            let (q0, q1) = (rr - t - 1.0, rr + 1.0);
            let mut q: Vec<[f64; 2]> = [(q0, a0), (q1, a0), (q1, a1), (q0, a1)].iter()
                .map(|&(rad, an)| [r4(c[0] + rad * f64::cos(an)), r4(c[1] + rad * f64::sin(an))]).collect();
            q.push(q[0]);
            run("sketch.line", json!({"points": q}))?;
        }
        run("sketch.finish", json!({}))?;
        run("solid.extrude", json!({"distance": r4(zh + 1.0), "direction": "negative",
            "operation": "cut", "targets": [mantel], "name": format!("{name} Zinnen")}))?;
    }
    if boolp(p, "boden", true) {
        out.push(disk(&format!("{name} Boden"), c, rr - t, z0, t)?);
    }
    match dach {
        "flach" | "zinnen" => out.push(disk(&format!("{name} Dach"), c, rr - t, z0 + hh - t, t)?),
        _ => {
            let a = num(p, "neigung", 60.0).to_radians();
            let ov = num(p, "ueberstand", 3.0);
            let ro = rr + ov;
            let ze = z0 + hh - ov * a.tan();
            let zap = z0 + hh + rr * a.tan();
            let dt = t / a.cos();
            out.push(revolve(&format!("{name} Kegeldach"), c,
                             &[[ro, ze], [0.001, zap], [0.001, zap + dt], [ro, ze + dt]])?);
        }
    }
    out.done(format!("Ø{}×{hh}, {dach}", 2.0 * rr))
}

// ------------------------------------------------------------ Ecktürmchen

fn ecktuerme(p: &Value) -> Res<Value> {
    let Some(h) = host(p, "gebaeude")? else {
        return Err(invalid("gebaeude", "Kasten oder Haus anklicken"));
    };
    let name = new_name("Ecktuerme")?;
    let t = num(p, "staerke", 3.0);
    let rr = num(p, "durchmesser", 14.0) / 2.0;
    let auf = strp(p, "auf", "krone");
    let dach = strp(p, "dach", "zinnen");
    let (z0, off) = if auf == "krone" {
        if h.schraeg {
            return Err(invalid("auf", "Auf der Krone nur bei Kasten oder Flachdach — sonst „Boden“ wählen"));
        }
        (h.top, 0.0)
    } else { (h.o[2], rr) };
    let hs = lagen(num(p, "hoehe", 24.0), t);
    let o = h.o;
    let ecken = [("vl", o[0] - off, o[1] - off), ("vr", o[0] + h.b + off, o[1] - off),
                 ("hr", o[0] + h.b + off, o[1] + h.t + off), ("hl", o[0] - off, o[1] + h.t + off)];
    let mut out = Out::new();
    for (tag, cx, cy) in ecken {
        let nm = format!("{name} {tag}");
        out.push(solid(&format!("{nm} Schaft"), "solid.cylinder", rr, hs, [cx, cy, z0])?);
        let top = z0 + hs;
        if dach == "zinnen" {
            let zh = lagen(num(p, "zinnen_h", 6.0), t);
            let krone = solid(&format!("{nm} Krone"), "solid.cylinder", rr, zh, [cx, cy, top])?;
            out.push(krone.clone());
            let mut k = ((2.0 * PI * rr / (rr * 0.8).max(3.0)).round() as usize).max(4);
            k += k % 2;
            for (jj, j) in (0..k).step_by(2).enumerate() {
                let (a0, a1) = (2.0 * PI * j as f64 / k as f64, 2.0 * PI * (j + 1) as f64 / k as f64);
                let poly: Vec<[f64; 2]> = [(rr * 0.45, a0), (rr + 1.0, a0), (rr + 1.0, a1), (rr * 0.45, a1)]
                    .iter().map(|&(q, an)| [cx + q * f64::cos(an), cy + q * f64::sin(an)]).collect();
                cut_plan(&format!("{nm} Zinne {}", jj + 1), &poly, top + zh + 1.0, zh / 2.0 + 1.0,
                         &[krone.clone()])?;
            }
        } else if dach == "kegel" {
            let hc = lagen((rr + 1.0) * num(p, "neigung", 60.0).to_radians().tan(), t);
            out.push(solid(&format!("{nm} Kegel"), "solid.cone", rr + 1.0, hc, [cx, cy, top])?);
        }
    }
    out.done(format!("4× Ø{}×{hs} ({auf}, {dach}) an {}", 2.0 * rr, h.name))
}

// ------------------------------------------------------------ Podest

fn podest(p: &Value) -> Res<Value> {
    let name = new_name("Podest")?;
    let t = num(p, "staerke", 3.0);
    let hp = lagen(num(p, "hoehe", 9.0), t);
    let (bb, tt, o) = match host(p, "gebaeude")? {
        Some(h) => (h.b, h.t, h.o),
        None => (num(p, "breite", 80.0), num(p, "tiefe", 60.0), [num(p, "x", 0.0), num(p, "y", 0.0), hp]),
    };
    let rd = num(p, "rand", 8.0);
    let lo = add(o, [-rd, -rd, -hp]);
    let hi = add(o, [bb + rd, tt + rd, 0.0]);
    let mut out = Out::new();
    out.push(box_plate(&format!("{name} Block"), lo, hi)?);
    if boolp(p, "treppe", true) {
        let n = (hp / t).round() as usize;
        let (sw, tr) = (num(p, "treppe_breite", 24.0), num(p, "stufe", 4.0));
        let x0 = o[0] + bb / 2.0 - sw / 2.0;
        let (yf, zb) = (lo[1], lo[2]);
        let mut prof = vec![(yf, zb), (yf - n as f64 * tr, zb)];
        for k in 0..n {
            prof.push((yf - (n - k) as f64 * tr, zb + (k + 1) as f64 * t));
            if k < n - 1 { prof.push((yf - (n - k - 1) as f64 * tr, zb + (k + 1) as f64 * t)); }
        }
        prof.push((yf, zb + n as f64 * t));
        let pts: Vec<V3> = prof.iter().map(|&(y, z)| [x0, y, z]).collect();
        out.push(plate3d(&format!("{name} Treppe"), &pts, [1.0, 0.0, 0.0], sw, false, &[])?);
    }
    out.done(format!("{hp} hoch, Rand {rd}"))
}

// ------------------------------------------------------------ Apsis

fn apsis(p: &Value) -> Res<Value> {
    let w = wall_ctx(p, "wand")?;
    let name = new_name("Apsis")?;
    let (t, n) = (num(p, "staerke", 3.0), num(p, "segmente", 5.0) as usize);
    let rad = num(p, "breite", 40.0) / 2.0;
    let y0 = w.bounds[1];
    let hh = num(p, "hoehe", 40.0);
    let mut a = num(p, "neigung", 45.0).to_radians();
    let (rr_, uu, nn) = (w.right, w.up, w.n);
    let c = add(add(w.p, mul(rr_, num(p, "x", 0.0))), mul(uu, y0));
    let phis: Vec<f64> = (0..=n).map(|k| PI * k as f64 / n as f64).collect();
    let v: Vec<V3> = phis.iter().map(|&f| add(add(c, mul(rr_, rad * f.cos())), mul(nn, rad * f.sin()))).collect();
    let trim = t / (PI / n as f64).sin();
    let mut out = Out::new();
    for k in 0..n {
        let (mut a0, mut b0) = (v[k], v[k + 1]);
        let fm = (phis[k] + phis[k + 1]) / 2.0;
        let n_out = add(mul(rr_, fm.cos()), mul(nn, fm.sin()));
        let x = unit(sub(b0, a0));
        if k > 0 {
            a0 = add(a0, mul(x, trim));
        } else {
            a0 = add(a0, mul(x, t * dot(n_out, nn) / dot(x, nn)));
        }
        if k == n - 1 {
            b0 = sub(b0, mul(x, t * dot(n_out, nn) / -dot(x, nn)));
        }
        let pts = [a0, b0, add(b0, mul(uu, hh)), add(a0, mul(uu, hh))];
        out.push(plate3d(&format!("{name} Wand {}", k + 1), &pts, n_out, t, true, &[])?);
    }
    let ov = num(p, "ueberstand", 3.0);
    let ap = rad * (PI / (2.0 * n as f64)).cos();
    let top_max = w.bounds[3] - 8.0 - y0;
    let mut info_a = String::new();
    if hh + ap * a.tan() > top_max {
        if top_max - hh < 2.0 {
            return Err(invalid("hoehe", "Apsis zu hoch für diese Wand"));
        }
        a = ((top_max - hh) / ap).atan();
        info_a = format!(", Neigung auf {:.0}° begrenzt", a.to_degrees());
    }
    let ro = rad + ov / (PI / (2.0 * n as f64)).cos();
    let ze = hh - ov * a.tan();
    let apex = add(c, mul(uu, hh + ap * a.tan()));
    let e: Vec<V3> = phis.iter().map(|&f| add(add(add(c, mul(rr_, ro * f.cos())), mul(nn, ro * f.sin())), mul(uu, ze))).collect();
    for k in 0..n {
        let (e0, e1) = (e[k], e[k + 1]);
        let mut q = unit(cross(sub(e1, e0), sub(apex, e0)));
        if dot(q, uu) < 0.0 { q = mul(q, -1.0); }
        out.push(plate3d(&format!("{name} Dach {}", k + 1), &[e0, e1, apex], q, t, false, &[])?);
    }
    out.done(format!("Ø{}, {n} Segmente, {hh} hoch an {}{info_a}", 2.0 * rad, w.name))
}

// ------------------------------------------------------------ Windmühle

fn muehle(p: &Value) -> Res<Value> {
    let name = new_name("Muehle")?;
    let (t, n) = (num(p, "staerke", 3.0), num(p, "ecken", 8.0) as usize);
    let c = origin(p);
    let (rr, hh) = (num(p, "durchmesser", 50.0) / 2.0, num(p, "hoehe", 70.0));
    let mut out = Out::new();
    ring_walls(&mut out, &name, c, n, rr, c[2], hh, t, None, "Wand")?;
    let ri = rr - t / (PI / n as f64).cos();
    let vi: Vec<V3> = poly_ang(n).iter().map(|q| add(c, [ri * q.cos(), ri * q.sin(), 0.0])).collect();
    out.push(plate3d(&format!("{name} Boden"), &vi, Z, t, false, &[])?);
    let top: Vec<V3> = vi.iter().map(|&q| add(q, [0.0, 0.0, hh - t])).collect();
    out.push(plate3d(&format!("{name} Decke"), &top, Z, t, false, &[])?);
    // Haube: massive Kuppel
    let rh = rr + 2.0;
    let hhb = lagen(num(p, "haube_h", 18.0), t);
    let mut prof = vec![[0.001, c[2] + hh]];
    for i in 0..23 {
        let th = (PI / 2.0) * i as f64 / 23.0;
        prof.push([rh * th.cos(), c[2] + hh + hhb * th.sin()]);
    }
    prof.push([0.001, c[2] + hh + hhb]);
    out.push(revolve(&format!("{name} Haube"), c, &prof)?);
    // Flügel: eine stehende Platte vor der Haube — Nabe + 4 Arme verschmolzen, Felder ausgeschnitten
    let l = num(p, "fluegel", 60.0);
    let bw = l * 0.2;
    let zc = c[2] + hh + hhb * 0.5;
    let yf = c[1] - rh * (0.5f64).asin().cos() - 0.5;
    let fl = format!("{name} Fluegel");
    let to3 = |q: [f64; 2]| [c[0] + q[0], yf, zc + q[1]];
    let plane = json!({"origin": f6([c[0], yf, zc]), "x_dir": [1, 0, 0], "y_dir": [0, 0, 1]});
    // Ebene x=(1,0,0), y=(0,0,1) → Normale (0,-1,0): positive Extrusion nach vorn (−y)
    run("sketch.create", json!({"plane": plane, "name": format!("{fl} Nabe Skizze")}))?;
    run("sketch.circle.center", json!({"center": [0, 0], "radius": 5}))?;
    run("sketch.finish", json!({}))?;
    let rep = run("solid.extrude", json!({"distance": r4(t), "operation": "new", "body_name": fl, "name": format!("{fl} Nabe")}))?;
    let fl = created(&rep, &fl);
    let _ = to3;
    let mut holes: Vec<Vec<[f64; 2]>> = vec![];
    for k in 0..4 {
        let an = PI / 4.0 + k as f64 * PI / 2.0;
        let d = [an.cos(), an.sin()];
        let nr = [-d[1], d[0]];
        let pt = |s: f64, w: f64| [d[0] * s + nr[0] * w, d[1] * s + nr[1] * w];
        let frame = vec![pt(4.0, -bw / 2.0), pt(l, -bw / 2.0), pt(l, bw / 2.0), pt(4.0, bw / 2.0)];
        run("sketch.create", json!({"plane": plane, "name": format!("{fl} Arm {} Skizze", k + 1)}))?;
        let mut q: Vec<[f64; 2]> = frame.iter().map(|p| [r4(p[0]), r4(p[1])]).collect();
        q.push(q[0]);
        run("sketch.line", json!({"points": q}))?;
        run("sketch.finish", json!({}))?;
        run("solid.extrude", json!({"distance": r4(t), "operation": "join", "targets": [fl],
                                    "name": format!("{fl} Arm {}", k + 1)}))?;
        let m = 1.2;
        let cells = (((l - 8.0) / (bw * 0.9)).floor() as usize).max(2);
        for j in 0..cells {
            let s0 = 8.0 + j as f64 * (l - 10.0) / cells as f64 + m / 2.0;
            let s1 = 8.0 + (j + 1) as f64 * (l - 10.0) / cells as f64 - m / 2.0;
            for side in [-1.0, 1.0] {
                let (w0, w1) = (side * m / 2.0, side * (bw / 2.0 - m));
                let (lo, hi) = (w0.min(w1), w0.max(w1));
                holes.push(vec![pt(s0, lo), pt(s1, lo), pt(s1, hi), pt(s0, hi)]);
            }
        }
    }
    run("sketch.create", json!({"plane": plane, "name": format!("{fl} Felder Skizze")}))?;
    for h in &holes {
        let mut q: Vec<[f64; 2]> = h.iter().map(|p| [r4(p[0]), r4(p[1])]).collect();
        q.push(q[0]);
        run("sketch.line", json!({"points": q}))?;
    }
    run("sketch.finish", json!({}))?;
    run("solid.extrude", json!({"distance": r4(t * 3.0), "direction": "symmetric", "operation": "cut",
                                "targets": [fl], "name": format!("{fl} Felder")}))?;
    out.push(fl);
    out.done(format!("{n}-Eck Ø{}×{hh}, Flügel {l}", 2.0 * rr))
}

// ------------------------------------------------------------ Leuchtturm

fn leuchtturm(p: &Value) -> Res<Value> {
    let name = new_name("Leuchtturm")?;
    let (t, n) = (num(p, "staerke", 3.0), num(p, "ecken", 8.0) as usize);
    let c = origin(p);
    let (rr, hh) = (num(p, "durchmesser", 40.0) / 2.0, num(p, "hoehe", 90.0));
    let mut out = Out::new();
    ring_walls(&mut out, &name, c, n, rr, c[2], hh, t, None, "Wand")?;
    let rg = rr + num(p, "umgang", 6.0);
    let gal: Vec<V3> = (0..48).map(|i| {
        let an = 2.0 * PI * i as f64 / 48.0;
        add(c, [rg * an.cos(), rg * an.sin(), hh])
    }).collect();
    out.push(plate3d(&format!("{name} Galerie"), &gal, Z, t, false, &[])?);
    let zg = c[2] + hh + t;
    let ng = (n * 2).max(8);
    let fenster_g = |l: f64, h: f64| if l > 4.0 { Some((1.2, 1.2, l - 1.2, h - 1.2)) } else { None };
    ring_walls(&mut out, &name, c, ng, rg - 0.3, zg, 5.0, t, Some(&fenster_g), "Gelaender")?;
    let rl = num(p, "laterne_d", 24.0) / 2.0;
    let lh = num(p, "laterne_h", 14.0);
    let fenster_l = |l: f64, h: f64| if l > 4.0 { Some((1.2, 1.5, l - 1.2, h - 1.5)) } else { None };
    ring_walls(&mut out, &name, c, n, rl, zg, lh, t, Some(&fenster_l), "Laterne")?;
    zelt(&mut out, &name, c, n, rl, zg + lh, 55f64.to_radians(), 1.5, t, "Kappe")?;
    out.done(format!("{n}-Eck Ø{}×{hh}, Galerie, Laterne", 2.0 * rr))
}

// ------------------------------------------------------------ Steinbrücke

fn steinbruecke(p: &Value) -> Res<Value> {
    let name = new_name("Steinbruecke")?;
    let (l, w, h) = (num(p, "laenge", 120.0), num(p, "breite", 36.0), num(p, "hoehe", 32.0));
    let n = num(p, "boegen", 2.0) as usize;
    let t = num(p, "staerke", 3.0);
    let br = num(p, "bruestung", 6.0);
    let sb = l / (n as f64 + 0.3 * (n as f64 + 1.0));
    let pw = 0.3 * sb;
    let ks = (h - t - 3.0 - sb / 2.0).max(0.0);
    let xs: Vec<f64> = (0..n).map(|i| pw + sb / 2.0 + i as f64 * (sb + pw)).collect();
    let o = origin(p);
    // Seitenwand: Rechteck 0…L × 0…h+Brüstung, Bögen von unten ausgespart
    let mut outline: Vec<[f64; 2]> = vec![[0.0, 0.0]];
    for &x in &xs {
        let arch = arch_bogen(x, -1.0, sb, ks + sb / 2.0); // rechts → links über den Bogen
        let (xl, xr) = (x - sb / 2.0, x + sb / 2.0);
        outline.push([xl, 0.0]);
        outline.push([xl, arch[32][1]]);
        for q in arch.iter().rev().skip(1).take(31) { outline.push(*q); }
        outline.push([xr, arch[0][1]]);
        outline.push([xr, 0.0]);
    }
    outline.push([l, 0.0]);
    outline.push([l, h + br]);
    outline.push([0.0, h + br]);
    let mut out = Out::new();
    for (nm, yy, ny) in [("Wand vorn", 0.0, -1.0), ("Wand hinten", w, 1.0)] {
        let pts: Vec<V3> = outline.iter().map(|q| add(o, [q[0], yy, q[1]])).collect();
        out.push(plate3d(&format!("{name} {nm}"), &pts, [0.0, ny, 0.0], t, true, &[])?);
    }
    out.push(box_plate(&format!("{name} Fahrbahn"), add(o, [0.0, t, h - t]), add(o, [l, w - t, h]))?);
    for (i, &x) in xs.iter().enumerate() {
        let (ro, ri) = (sb / 2.0, sb / 2.0 - t);
        let mut prof = vec![];
        for k in 0..33 { let a = PI * k as f64 / 32.0; prof.push((x + ro * a.cos(), ks + ro * a.sin())); }
        for k in 0..33 { let a = PI - PI * k as f64 / 32.0; prof.push((x + ri * a.cos(), ks + ri * a.sin())); }
        let pts: Vec<V3> = prof.iter().map(|&(xx, zz)| add(o, [xx, t, zz])).collect();
        out.push(plate3d(&format!("{name} Gewoelbe {}", i + 1), &pts, [0.0, 1.0, 0.0], w - 2.0 * t, false, &[])?);
    }
    out.done(format!("{l}×{w}, {n} Bögen"))
}

// ------------------------------------------------------------ Fachwerkbrücke

/// Konvexes Polygon an der Halbebene a·x + b·y + c ≥ 0 beschneiden.
fn clip(poly: &[[f64; 2]], a: f64, b: f64, c: f64) -> Vec<[f64; 2]> {
    let f = |p: [f64; 2]| a * p[0] + b * p[1] + c;
    let mut out = vec![];
    for i in 0..poly.len() {
        let (p, q) = (poly[i], poly[(i + 1) % poly.len()]);
        let (fp, fq) = (f(p), f(q));
        if fp >= 0.0 { out.push(p); }
        if (fp >= 0.0) != (fq >= 0.0) {
            let s = fp / (fp - fq);
            out.push([p[0] + (q[0] - p[0]) * s, p[1] + (q[1] - p[1]) * s]);
        }
    }
    out
}

fn area(poly: &[[f64; 2]]) -> f64 {
    let mut s = 0.0;
    for i in 0..poly.len() {
        let (p, q) = (poly[i], poly[(i + 1) % poly.len()]);
        s += p[0] * q[1] - q[0] * p[1];
    }
    s.abs() / 2.0
}

fn fachwerkbruecke(p: &Value) -> Res<Value> {
    let name = new_name("Fachwerkbruecke")?;
    let (l, w, ht) = (num(p, "laenge", 120.0), num(p, "breite", 36.0), num(p, "hoehe", 26.0));
    let n = num(p, "felder", 6.0) as usize;
    let (sw, t) = (num(p, "stab", 3.0), num(p, "staerke", 3.0));
    let o = origin(p);
    let pw = l / n as f64;
    // Löcher: je Feld das Innenrechteck, an der Diagonale (Stabbreite) in zwei Dreiecke geteilt
    let mut holes: Vec<Vec<[f64; 2]>> = vec![];
    for i in 0..n {
        let (x0, x1) = (i as f64 * pw, (i + 1) as f64 * pw);
        let xl = if i == 0 { sw } else { x0 + sw / 2.0 };
        let xr = if i == n - 1 { l - sw } else { x1 - sw / 2.0 };
        if xr - xl < 0.5 { continue; }
        let rect = [[xl, sw], [xr, sw], [xr, ht - sw], [xl, ht - sw]];
        let (pa, pb) = if i % 2 == 0 { ([x0, 0.0], [x1, ht]) } else { ([x0, ht], [x1, 0.0]) };
        let (dx, dy) = (pb[0] - pa[0], pb[1] - pa[1]);
        let len = (dx * dx + dy * dy).sqrt();
        let (a, b) = (-dy / len, dx / len);
        let c = -(a * pa[0] + b * pa[1]);
        for sgn in [1.0, -1.0] {
            let h = clip(&rect, sgn * a, sgn * b, sgn * c - sw / 2.0);
            if h.len() >= 3 && area(&h) > 0.5 { holes.push(h); }
        }
    }
    let mut out = Out::new();
    for (nm, yy, ny) in [("Traeger vorn", 0.0, -1.0), ("Traeger hinten", w, 1.0)] {
        let to3 = |q: &[f64; 2]| add(o, [q[0], yy, t + q[1]]);
        let outer = [to3(&[0.0, 0.0]), to3(&[l, 0.0]), to3(&[l, ht]), to3(&[0.0, ht])];
        let hs: Vec<Vec<V3>> = holes.iter().map(|h| h.iter().map(to3).collect()).collect();
        out.push(plate3d(&format!("{name} {nm}"), &outer, [0.0, ny, 0.0], t, true, &hs)?);
    }
    out.push(box_plate(&format!("{name} Fahrbahn"), o, add(o, [l, w, t]))?);
    let ha = lagen(num(p, "auflage", 6.0), t);
    for (nm, x0) in [("Auflager links", 0.0), ("Auflager rechts", l - 6.0)] {
        out.push(box_plate(&format!("{name} {nm}"), add(o, [x0, 0.0, -ha]), add(o, [x0 + 6.0, w, 0.0]))?);
    }
    out.done(format!("{l}×{w}, {n} Felder"))
}

// ------------------------------------------------------------ Pagode

fn pagode(p: &Value) -> Res<Value> {
    let name = new_name("Pagode")?;
    let (n, t) = (num(p, "stockwerke", 3.0) as usize, num(p, "staerke", 3.0));
    let a = num(p, "neigung", 30.0).to_radians();
    let (ta, s, c_) = (a.tan(), a.sin(), a.cos());
    let (b0, t0) = (num(p, "breite", 60.0), num(p, "tiefe", 60.0));
    let shr = num(p, "schrumpf", 0.75);
    let cx = num(p, "x", 0.0) + b0 / 2.0;
    let cy = num(p, "y", 0.0) + t0 / 2.0;
    let mut z = num(p, "z", 0.0);
    let dims: Vec<(f64, f64)> = (0..n).map(|k| (b0 * shr.powi(k as i32), t0 * shr.powi(k as i32))).collect();
    let mut out = Out::new();
    for (k, &(bb, tt)) in dims.iter().enumerate() {
        let hgt = num(p, "geschoss", 26.0) * 0.85f64.powi(k as i32);
        let o = [cx - bb / 2.0, cy - tt / 2.0, z];
        let tag = format!("{name} G{}", k + 1);
        if k == 0 {
            out.push(box_plate(&format!("{tag} Boden"), add(o, [t, t, 0.0]), add(o, [bb - t, tt - t, t]))?);
        }
        for (nm, lo, hi) in [("vorn", o, add(o, [bb, t, hgt])),
                             ("hinten", add(o, [0.0, tt - t, 0.0]), add(o, [bb, tt, hgt])),
                             ("links", add(o, [0.0, t, 0.0]), add(o, [t, tt - t, hgt])),
                             ("rechts", add(o, [bb - t, t, 0.0]), add(o, [bb, tt - t, hgt]))] {
            out.push(box_plate(&format!("{tag} {nm}"), lo, hi)?);
        }
        let ov = num(p, "ueberstand", 8.0) * 0.85f64.powi(k as i32);
        let hh = hgt;
        if k < n - 1 {
            let (bn, tn) = dims[k + 1];
            let d = ((bb - bn) / 2.0).min((tt - tn) / 2.0) - 1.0;
            let zt = hh + d * ta;
            let ze = hh - ov * ta;
            let pp = |x: f64, y: f64, zz: f64| add(o, [x, y, zz]);
            let e = [pp(-ov, -ov, ze), pp(bb + ov, -ov, ze), pp(bb + ov, tt + ov, ze), pp(-ov, tt + ov, ze)];
            let i_ = [pp(d, d, zt), pp(bb - d, d, zt), pp(bb - d, tt - d, zt), pp(d, tt - d, zt)];
            for (nm, pts, nn) in [("vorn", [e[0], e[1], i_[1], i_[0]], [0.0, -s, c_]),
                                  ("rechts", [e[1], e[2], i_[2], i_[1]], [s, 0.0, c_]),
                                  ("hinten", [e[2], e[3], i_[3], i_[2]], [0.0, s, c_]),
                                  ("links", [e[3], e[0], i_[0], i_[3]], [-s, 0.0, c_])] {
                out.push(plate3d(&format!("{tag} Dach {nm}"), &pts, nn, t, false, &[])?);
            }
            out.push(box_plate(&format!("{tag} Kragplatte"), add(o, [d, d, zt]), add(o, [bb - d, tt - d, zt + t]))?);
            z = z + zt + t;
        } else {
            let zr = walm_plates(&mut out, &tag, o, bb, tt, hh, a, ov, t, "Dach")?;
            if boolp(p, "spitze", true) {
                kreuz(&mut out, &tag, [cx, cy, z + zr], (bb * 0.3).max(6.0), t, Some(a))?;
            }
        }
    }
    out.done(format!("{n} Geschosse, {b0}×{t0}"))
}
