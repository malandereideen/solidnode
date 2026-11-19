//! Kategorie Dach: Gaube, Zwerchgiebel, Dachreiter, Turmhelm, Schornstein, Vordach.
//! Portiert aus laser_extra.py (gaube, vordach), laser_bauten.py (zwerch, dachreiter,
//! helm) und laser_haus.py (kamin). Das Plugin hat keine Elementliste wie SolidNode:
//! Haus und Turm werden aus ihren Körpern (Namen + Bounding-Boxen) zurückgerechnet.

use crate::craft::plugin::types::PluginError;
use crate::{Bx, V3, add, cross, dot, invalid, mul, num, r, run, v3};
use serde_json::{Value, json};
use std::f64::consts::PI;

type R<T> = Result<T, PluginError>;

/// None = Eintrag gehört nicht zu diesem Modul.
pub fn execute(entry: &str, p: &Value) -> Option<Result<Value, PluginError>> {
    Some(match entry {
        "gaube" => giebelgaube(p, false),
        "zwerch" => giebelgaube(p, true),
        "dachreiter" => dachreiter(p),
        "helm" => helm(p),
        "kamin" => kamin(p),
        "vordach" => vordach(p),
        _ => return None,
    })
}

// ------------------------------------------------------------------ Helfer

fn sub(a: V3, b: V3) -> V3 { [a[0] - b[0], a[1] - b[1], a[2] - b[2]] }
fn norm(a: V3) -> f64 { dot(a, a).sqrt() }
fn unit(a: V3) -> V3 { mul(a, 1.0 / norm(a)) }
fn f6(v: V3) -> [f64; 3] { v.map(|x| (x * 1e6).round() / 1e6) }
fn r4(x: f64) -> f64 { (x * 1e4).round() / 1e4 }
fn flag(p: &Value, k: &str, d: bool) -> bool { p[k].as_bool().unwrap_or(d) }

/// Ebenes Weltpolygon als Platte, wächst entlang n_out (oder nach innen).
/// Gibt den echten Körpernamen zurück.
fn plate3d(name: &str, pts: &[V3], n_out: V3, t: f64, inward: bool, holes: &[Vec<V3>])
    -> R<String> {
    let n = unit(n_out);
    let x = unit(sub(pts[1], pts[0]));
    let y = cross(n, x);
    let o = pts[0];
    let loc = |q: V3| { let d = sub(q, o); json!([r4(dot(d, x)), r4(dot(d, y))]) };
    run("sketch.create", json!({"plane": {"origin": f6(o), "x_dir": f6(x), "y_dir": f6(y)},
                                "name": format!("{name} Skizze")}))?;
    for lp in std::iter::once(pts).chain(holes.iter().map(|h| h.as_slice())) {
        let mut q: Vec<Value> = lp.iter().map(|&p| loc(p)).collect();
        q.push(q[0].clone());
        run("sketch.line", json!({"points": q}))?;
    }
    run("sketch.finish", json!({}))?;
    let rep = run("solid.extrude", json!({"distance": r4(t), "operation": "new",
        "direction": if inward { "negative" } else { "positive" },
        "body_name": name, "name": name}))?;
    Ok(rep["created_bodies"][0].as_str().unwrap_or(name).to_string())
}

/// Grundrissfläche senkrecht von oben aus Körpern schneiden.
fn cut_plan(nm: &str, poly: &[[f64; 2]], z_top: f64, depth: f64, targets: &[String]) -> R<()> {
    run("sketch.create", json!({"plane": {"origin": [0, 0, r(z_top)], "x_dir": [1, 0, 0],
                                          "y_dir": [0, 1, 0]}, "name": format!("{nm} Skizze")}))?;
    let mut q: Vec<Value> = poly.iter().map(|p| json!([r4(p[0]), r4(p[1])])).collect();
    q.push(q[0].clone());
    run("sketch.line", json!({"points": q}))?;
    run("sketch.finish", json!({}))?;
    run("solid.extrude", json!({"distance": r(depth), "direction": "negative",
                                "operation": "cut", "targets": targets, "name": nm}))?;
    Ok(())
}

/// Konvexes Polygon ∩ {a·x + b·y ≤ c} (Sutherland–Hodgman, eine Kante).
fn clip_half(poly: &[[f64; 2]], a: f64, b: f64, c: f64) -> Vec<[f64; 2]> {
    let f = |p: [f64; 2]| a * p[0] + b * p[1] - c;
    let mut out = vec![];
    for i in 0..poly.len() {
        let (p, q) = (poly[i], poly[(i + 1) % poly.len()]);
        let (fp, fq) = (f(p), f(q));
        if fp <= 0.0 { out.push(p); }
        if (fp < 0.0) != (fq < 0.0) && fp != fq {
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

/// Freier Namensstamm: „Gaube“, sonst „Gaube 2“, „Gaube 3“ … (Feature-Namen müssen eindeutig sein).
fn unique(base: &str) -> R<String> {
    let d = run("document.inspect", json!({"bodies": "names"}))?;
    let names: Vec<String> = d["timeline"].as_array().into_iter().flatten()
        .filter_map(|f| f["name"].as_str().map(String::from))
        .chain(d["bodies"].as_array().into_iter().flatten()
            .filter_map(|b| b["name"].as_str().or(b.as_str()).map(String::from)))
        .collect();
    let taken = |pre: &str| names.iter().any(|n| n == pre || n.starts_with(&format!("{pre} ")));
    if !taken(base) { return Ok(base.to_string()); }
    let mut k = 2;
    while taken(&format!("{base} {k}")) { k += 1; }
    Ok(format!("{base} {k}"))
}

fn measure() -> R<Vec<(String, Bx)>> {
    let m = run("inspect.measure", json!({}))?;
    Ok(m["bodies"].as_array().into_iter().flatten().map(|b| {
        (b["name"].as_str().unwrap_or("").to_string(),
         Bx { lo: v3(&b["bbox"]["min"]), hi: v3(&b["bbox"]["max"]) })
    }).collect())
}

/// Erster Pick: Körpername und (bei Flächen) der Klickpunkt.
fn pick(p: &Value, key: &str) -> R<(String, Option<V3>)> {
    let it = p[key].as_array().and_then(|a| a.first())
        .ok_or_else(|| invalid(key, "nichts angeklickt"))?;
    let name = it.as_str().or(it["body"].as_str()).or(it["name"].as_str())
        .ok_or_else(|| invalid(key, "Körper oder Fläche anklicken"))?;
    let pt = it.get("point").filter(|v| v.is_array()).map(v3);
    Ok((name.to_string(), pt))
}

/// Kreuz als stehende Platte auf der Spitze.
fn kreuz(name: &str, apex: V3, h: f64, t: f64, a: Option<f64>) -> R<String> {
    let apex = match a { Some(a) => add(apex, [0.0, 0.0, t / a.cos()]), None => apex };
    let b = (h * 0.12).max(1.2);
    let arm = h * 0.6;
    let (z0, z1) = (h * 0.58, h * 0.58 + b);
    let ring: Vec<[f64; 2]> = if arm > b + 1e-6 {
        vec![[-b / 2.0, 0.0], [b / 2.0, 0.0], [b / 2.0, z0], [arm / 2.0, z0], [arm / 2.0, z1],
             [b / 2.0, z1], [b / 2.0, h], [-b / 2.0, h], [-b / 2.0, z1], [-arm / 2.0, z1],
             [-arm / 2.0, z0], [-b / 2.0, z0]]
    } else {
        vec![[-b / 2.0, 0.0], [b / 2.0, 0.0], [b / 2.0, h], [-b / 2.0, h]]
    };
    let o = sub(apex, [0.0, t / 2.0, 0.0]);
    let pts: Vec<V3> = ring.iter().map(|q| add(o, [q[0], 0.0, q[1]])).collect();
    plate3d(&format!("{name} Kreuz"), &pts, [0.0, 1.0, 0.0], t, false, &[])
}

/// Zeltdach aus n Dreiecken (Unterseite durch die Wandoberkanten).
fn zelt(name: &str, c: V3, n: usize, rr: f64, z_eave: f64, a: f64, ov: f64, t: f64,
        prefix: &str) -> R<(Vec<String>, V3)> {
    let ang: Vec<f64> = (0..n).map(|i| 2.0 * PI * (i as f64 + 0.5) / n as f64).collect();
    let ro = rr + ov / (PI / n as f64).cos();
    let ze = z_eave - ov * a.tan();
    let apex = [c[0], c[1], z_eave + rr * (PI / n as f64).cos() * a.tan()];
    let vo: Vec<V3> = ang.iter().map(|q| [c[0] + ro * q.cos(), c[1] + ro * q.sin(), ze]).collect();
    let mut bodies = vec![];
    for i in 0..n {
        let (p0, p1) = (vo[i], vo[(i + 1) % n]);
        let mid = sub(mul(add(p0, p1), 0.5), [c[0], c[1], ze]);
        let nh = unit([mid[0], mid[1], 0.0]);
        let n_out = add(mul(nh, a.sin()), [0.0, 0.0, a.cos()]);
        bodies.push(plate3d(&format!("{name} {prefix} {}", i + 1), &[p0, p1, apex], n_out, t,
                            false, &[])?);
    }
    Ok((bodies, apex))
}

/// Walmdach über dem Rechteck o…o+(B,T) mit Traufe auf H.
fn walm_plates(name: &str, o: V3, b: f64, tt: f64, h: f64, a: f64, ov: f64, t: f64)
    -> R<(Vec<String>, f64)> {
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
    let mut bodies = vec![];
    for (nm, pts, n) in faces {
        let mut clean = vec![pts[0]];
        for &q in &pts[1..] {
            if norm(sub(q, *clean.last().unwrap())) > 1e-6 { clean.push(q); }
        }
        if clean.len() >= 3 && norm(sub(*clean.last().unwrap(), clean[0])) < 1e-6 { clean.pop(); }
        if clean.len() < 3 { continue; }
        bodies.push(plate3d(&format!("{name} Dach {nm}"), &clean, n, t, false, &[])?);
    }
    Ok((bodies, zr))
}

// ------------------------------------------------------------ Haus erkennen

#[derive(Clone, Copy, PartialEq)]
enum Dach { Sattel, Pult, Walm, Flach }

struct Haus {
    pre: String,
    o: V3,
    b: f64,
    tt: f64,
    h: f64,
    t: f64,
    a: f64,
    ta: f64,
    ov: f64,
    dach: Dach,
    roofs: Vec<String>,
}

const HAUS_TEILE: [&str; 10] = ["Dach vorn", "Dach hinten", "Dach links", "Dach rechts",
                                 "Seite links", "Seite rechts", "Rueckwand", "Front", "Boden", "Dach"];

fn haus_prefix(body: &str) -> Option<String> {
    HAUS_TEILE.iter().find_map(|s| body.strip_suffix(&format!(" {s}")).map(String::from))
}

/// Haus (laser_haus.cmds_haus) aus seinen Körpern zurückrechnen.
fn haus_from(body: &str) -> R<Haus> {
    let all = measure()?;
    let pre = haus_prefix(body).filter(|pre| all.iter().any(|(n, _)| n == &format!("{pre} Front")))
        .or_else(|| {
            // nichts Passendes angeklickt: zuletzt angelegtes Haus
            all.iter().rev().find_map(|(n, _)| n.strip_suffix(" Front").map(String::from))
                .filter(|pre| all.iter().any(|(n, _)| n == &format!("{pre} Seite links")))
        })
        .ok_or_else(|| invalid("haus", "Haus anklicken (Wand oder Dach eines Hauses)"))?;
    let get = |s: &str| all.iter().find(|(n, _)| n == &format!("{pre} {s}")).map(|x| x.1);
    let front = get("Front").ok_or_else(|| invalid("haus", "Haus ohne Front"))?;
    let seite = get("Seite links").ok_or_else(|| invalid("haus", "Haus ohne Seitenwand"))?;
    let o = front.lo;
    let (b, t, tt) = (front.ext(0), front.ext(1), seite.ext(1));
    let roofs: Vec<String> = all.iter().filter(|(n, _)| n.starts_with(&format!("{pre} Dach")))
        .map(|x| x.0.clone()).collect();
    let dach = if get("Dach links").is_some() { Dach::Walm }
        else if get("Dach vorn").is_some() { Dach::Sattel }
        else if let Some(d) = get("Dach") { if d.ext(2) < t + 1e-3 { Dach::Flach } else { Dach::Pult } }
        else { Dach::Flach };
    let mut h = front.hi[2] - o[2];
    let mut ov = 0.0;
    let ta;
    match dach {
        Dach::Sattel => {
            ta = (seite.hi[2] - o[2] - h) / (tt / 2.0);
            ov = (get("Dach vorn").unwrap().ext(0) - b) / 2.0;
        }
        Dach::Pult => {
            ta = (seite.hi[2] - o[2] - h) / tt;
            ov = (get("Dach").unwrap().ext(0) - b) / 2.0;
        }
        Dach::Walm => {
            let dv = get("Dach vorn").unwrap();
            ov = (dv.ext(0) - b) / 2.0;
            let zmax = dv.hi[2] - o[2];
            // zmax = H + T/2·tan a + t·cos a  → a per Bisektion
            let (mut lo, mut hi) = (1e-4, PI / 2.0 - 1e-4);
            for _ in 0..80 {
                let m = (lo + hi) / 2.0;
                if h + tt / 2.0 * m.tan() + t * m.cos() > zmax { hi = m; } else { lo = m; }
            }
            ta = ((lo + hi) / 2.0).tan();
        }
        Dach::Flach => {
            if let Some(d) = get("Dach") { h = d.hi[2] - o[2]; }
            ta = 0.0;
        }
    }
    Ok(Haus { pre, o, b, tt, h, t, a: ta.atan(), ta, ov, dach, roofs })
}

// --------------------------------------------------------------- Schornstein

fn kamin(p: &Value) -> R<Value> {
    let (body, _) = pick(p, "haus")?;
    let hs = haus_from(&body)?;
    let (o, tt, h, t, ta) = (hs.o, hs.tt, hs.h, hs.t, hs.ta);
    let top_roof = match hs.dach { Dach::Flach => h, Dach::Pult => h + tt * ta, _ => h + tt / 2.0 * ta };
    let (w, d) = (num(p, "breite", 10.0), num(p, "tiefe", 10.0));
    let (cx, cy) = (o[0] + num(p, "x", 20.0), o[1] + tt / 2.0 - num(p, "y", 10.0));
    let (z0, z1) = (o[2] + h - t, o[2] + top_roof + num(p, "hoehe", 10.0));
    let (x0, x1, y0, y1) = (cx - w / 2.0, cx + w / 2.0, cy - d / 2.0, cy + d / 2.0);
    let tk = num(p, "staerke", 3.0);
    let name = &unique("Schornstein")?;
    if !hs.roofs.is_empty() {
        cut_plan(&format!("{name} Loch"), &[[x0, y0], [x1, y0], [x1, y1], [x0, y1]],
                 z1 + 1.0, z1 - z0 + 2.0, &hs.roofs)?;
    }
    let parts = [("vorn", [x0, y0, z0], [x1, y0 + tk, z1]),
                 ("hinten", [x0, y1 - tk, z0], [x1, y1, z1]),
                 ("links", [x0, y0 + tk, z0], [x0 + tk, y1 - tk, z1]),
                 ("rechts", [x1 - tk, y0 + tk, z0], [x1, y1 - tk, z1])];
    let mut bodies = vec![];
    for (nm, lo, hi) in parts {
        bodies.push(crate::box_plate(&format!("{name} {nm}"), lo, hi)?);
    }
    Ok(json!({"haus": hs.pre, "koerper": bodies}))
}

// --------------------------------------------------- Gaube / Zwerchgiebel

fn giebelgaube(p: &Value, zwerch: bool) -> R<Value> {
    let (body, pt) = pick(p, "dachflaeche")?;
    let hs = haus_from(&body)?;
    let mut hinten = body.ends_with("Dach hinten") || body.ends_with("Rueckwand");
    if let Some(pt) = pt {
        if body.ends_with(" Dach") && hs.dach != Dach::Pult {
            hinten = pt[1] > hs.o[1] + hs.tt / 2.0;
        }
    }
    if hs.dach == Dach::Flach {
        return Err(invalid("dachflaeche", "Gaube braucht ein geneigtes Dach"));
    }
    if hs.dach == Dach::Pult && hinten {
        return Err(invalid("dachflaeche", "Pultdach hat nur vorn eine Dachfläche"));
    }
    let (o, b, tt, h, t, a, ta, ov) = (hs.o, hs.b, hs.tt, hs.h, hs.t, hs.a, hs.ta, hs.ov);
    let ca = a.cos();
    let half = if hs.dach == Dach::Pult { tt } else { tt / 2.0 };
    let wf = |x: f64, y: f64, z: f64| -> V3 {
        if hinten { add(o, [b - x, tt - y, z]) } else { add(o, [x, y, z]) }
    };
    let vf = |v: V3| -> V3 { if hinten { [-v[0], -v[1], v[2]] } else { v } };
    let name = &unique(if zwerch { "Zwerchgiebel" } else { "Gaube" })?;
    let w = num(p, "breite", if zwerch { 30.0 } else { 14.0 }).max(2.0 * t + 3.0);
    let u = num(p, "x", if zwerch { 50.0 } else { 30.0 });
    let (u0, u1, hw) = (u - w / 2.0, u + w / 2.0, w / 2.0);
    let ag = num(p, "neigung", 45.0).to_radians();
    let (sg, cg, tg) = (ag.sin(), ag.cos(), ag.tan());
    let top = |y: f64| h + y * ta + t / ca;
    let (dg, z0, zt, zc);
    if zwerch {
        dg = 0.0;
        z0 = h;
        zt = h + num(p, "kniestock", 12.0);
        zc = top(t) + 0.2;
    } else {
        dg = num(p, "tiefe", 8.0);
        z0 = top(dg + t) + 0.2;
        zc = z0;
        zt = z0 + num(p, "hoehe", 10.0);
    }
    let hg = zt - z0;
    let zg = zt + hw * tg;
    if (zg + t / cg - (h + t / ca)) / ta > half - 1.0 {
        return Err(invalid("breite", "Gaube reicht über den First (kleiner oder näher an die Traufe)"));
    }
    let mut bodies = vec![];
    if zwerch {
        let roof = format!("{} {}", hs.pre, if hs.dach == Dach::Pult { "Dach" }
                           else if hinten { "Dach hinten" } else { "Dach vorn" });
        let q = [wf(u0, -ov - 1.0, 0.0), wf(u1, -ov - 1.0, 0.0), wf(u1, t, 0.0), wf(u0, t, 0.0)];
        let (xs, ys): (Vec<f64>, Vec<f64>) = q.iter().map(|v| (v[0], v[1])).unzip();
        let mn = |v: &[f64]| v.iter().cloned().fold(f64::MAX, f64::min);
        let mx = |v: &[f64]| v.iter().cloned().fold(f64::MIN, f64::max);
        let zz = wf(0.0, 0.0, top(half) + 20.0)[2];
        cut_plan(&format!("{name} Dachausschnitt"),
                 &[[mn(&xs), mn(&ys)], [mx(&xs), mn(&ys)], [mx(&xs), mx(&ys)], [mn(&xs), mx(&ys)]],
                 zz, zz - wf(0.0, 0.0, h - 1.0)[2], &[roof])?;
    }
    // Front mit Fenster
    let front = [wf(u0, dg, z0), wf(u1, dg, z0), wf(u1, dg, zt), wf(u, dg, zg), wf(u0, dg, zt)];
    let mut holes = vec![];
    if flag(p, "fenster", true) {
        let fw = (w - 2.0 * t - 2.0).min(w * 0.55);
        let (fz0, fz1) = (z0 + hg * 0.15, z0 + hg * 0.85);
        if fw > 2.0 {
            holes.push(vec![wf(u - fw / 2.0, dg, fz0), wf(u + fw / 2.0, dg, fz0),
                            wf(u + fw / 2.0, dg, fz1), wf(u - fw / 2.0, dg, fz1)]);
        }
    }
    bodies.push(plate3d(&format!("{name} Front"), &front, vf([0.0, -1.0, 0.0]), t, true, &holes)?);
    // Wangen
    let d_end = (zt - 0.2 - h - t / ca) / ta;
    for (nm, xc, n_out) in [("Wange links", u0, [-1.0, 0.0, 0.0]), ("Wange rechts", u1, [1.0, 0.0, 0.0])] {
        let pts = [wf(xc, dg + t, zc), wf(xc, d_end, zt), wf(xc, dg + t, zt)];
        bodies.push(plate3d(&format!("{name} {nm}"), &pts, vf(n_out), t, true, &[])?);
    }
    // Dachplatten, hinten an der Hauptdachfläche abgeschnitten
    let (ovd, ovs) = (1.5, 1.5);
    let sp = hw / cg;
    let ds = dg - ovd;
    for (nm, ue, side) in [("Dach links", u0, 1.0), ("Dach rechts", u1, -1.0)] {
        let bx = [[0.0, -ovs], [400.0, -ovs], [400.0, sp], [0.0, sp]];
        let poly = clip_half(&bx, ta, -sg, zt - h - t / ca - 0.1 - ds * ta);
        if poly.len() < 3 || area(&poly) < 1.0 { continue; }
        let pts: Vec<V3> = poly.iter().map(|&[s, v]| wf(ue + side * v * cg, ds + s, zt + v * sg)).collect();
        bodies.push(plate3d(&format!("{name} {nm}"), &pts, vf([-side * sg, 0.0, cg]), t, false, &[])?);
    }
    Ok(json!({"haus": hs.pre, "seite": if hinten { "hinten" } else { "vorn" }, "koerper": bodies}))
}

// --------------------------------------------------------------- Dachreiter

fn dachreiter(p: &Value) -> R<Value> {
    let (body, _) = pick(p, "haus")?;
    let hs = haus_from(&body)?;
    if hs.dach != Dach::Sattel {
        return Err(invalid("haus", "Dachreiter braucht ein Haus mit Satteldach"));
    }
    let (o, tt, h, t, a, ta) = (hs.o, hs.tt, hs.h, hs.t, hs.a, hs.ta);
    let ca = a.cos();
    let top = |y: f64| h + y.min(tt - y) * ta + t / ca;
    let (w, d) = (num(p, "breite", 14.0), num(p, "tiefe", 14.0));
    let px = num(p, "x", 50.0);
    let (x0, x1) = (px - w / 2.0, px + w / 2.0);
    let (y0, y1) = (tt / 2.0 - d / 2.0, tt / 2.0 + d / 2.0);
    let tk = num(p, "staerke", 3.0);
    let zb = top(y0 + tk) + 0.2;
    let zt = top(tt / 2.0) + num(p, "hoehe", 14.0);
    let wf = |x: f64, y: f64, z: f64| add(o, [x, y, z]);
    let name = &unique("Dachreiter")?;
    let mut bodies = vec![];
    for (nm, yy, n_out) in [("vorn", y0, [0.0, -1.0, 0.0]), ("hinten", y1, [0.0, 1.0, 0.0])] {
        let pts = [wf(x0, yy, zb), wf(x1, yy, zb), wf(x1, yy, zt), wf(x0, yy, zt)];
        bodies.push(plate3d(&format!("{name} {nm}"), &pts, n_out, tk, true, &[])?);
    }
    for (nm, xx, n_out) in [("links", x0, [-1.0, 0.0, 0.0]), ("rechts", x1, [1.0, 0.0, 0.0])] {
        let (ya, yb) = (y0 + tk, y1 - tk);
        let pts = [wf(xx, ya, top(ya) + 0.2), wf(xx, tt / 2.0, top(tt / 2.0) + 0.2),
                   wf(xx, yb, top(yb) + 0.2), wf(xx, yb, zt), wf(xx, ya, zt)];
        bodies.push(plate3d(&format!("{name} {nm}"), &pts, n_out, tk, true, &[])?);
    }
    let an = num(p, "neigung", 70.0).to_radians();
    let (b2, zr) = walm_plates(name, add(o, [x0, y0, 0.0]), w, d, zt, an, num(p, "ueberstand", 1.5), tk)?;
    bodies.extend(b2);
    if flag(p, "kreuz", true) {
        bodies.push(kreuz(name, add(o, [px, tt / 2.0, zr]), num(p, "kreuz_h", 8.0), tk, Some(an))?);
    }
    Ok(json!({"haus": hs.pre, "koerper": bodies}))
}

// ----------------------------------------------------------------- Turmhelm

fn helm(p: &Value) -> R<Value> {
    let (body, _) = pick(p, "turm")?;
    let all = measure()?;
    // Turmname: „<pre> Wand N“, „<pre> Dach“, „<pre> Boden“, „<pre> Mantel“
    let strip = |n: &str| -> Option<String> {
        let mut it = n.rsplitn(2, ' ');
        let last = it.next()?;
        let rest = it.next()?;
        if last.chars().all(|c| c.is_ascii_digit()) {
            rest.strip_suffix(" Wand").map(String::from)
        } else {
            ["Dach", "Boden", "Mantel"].iter().find_map(|s| n.strip_suffix(&format!(" {s}")).map(String::from))
        }
    };
    let pre = strip(&body).ok_or_else(|| invalid("turm", "Turm anklicken (Wand, Mantel oder Dach)"))?;
    let walls: Vec<&Bx> = all.iter().filter(|(n, _)| {
        n.strip_prefix(&format!("{pre} Wand ")).is_some_and(|k| k.chars().all(|c| c.is_ascii_digit()))
    }).map(|x| &x.1).collect();
    let mantel = all.iter().find(|(n, _)| n == &format!("{pre} Mantel")).map(|x| x.1);
    if all.iter().any(|(n, _)| n == &format!("{pre} Dach 1") || n == &format!("{pre} Kegeldach")) {
        return Err(invalid("turm", "Der Turm hat schon ein Spitzdach — dort „flach“ oder „zinnen“ wählen"));
    }
    let (n, bb) = if !walls.is_empty() {
        let mut bb = *walls[0];
        for w in &walls { for i in 0..3 { bb.lo[i] = bb.lo[i].min(w.lo[i]); bb.hi[i] = bb.hi[i].max(w.hi[i]); } }
        (walls.len(), bb)
    } else if let Some(m) = mantel { (16, m) } else {
        return Err(invalid("turm", "kein Turm gefunden"));
    };
    let c = [(bb.lo[0] + bb.hi[0]) / 2.0, (bb.lo[1] + bb.hi[1]) / 2.0, bb.lo[2]];
    let rr = if walls.is_empty() { bb.ext(0) / 2.0 } else {
        let mc = (0..n).map(|i| (2.0 * PI * (i as f64 + 0.5) / n as f64).cos()).fold(f64::MIN, f64::max);
        (bb.hi[0] - c[0]) / mc
    };
    let zb = bb.hi[2];
    let t = num(p, "staerke", 3.0);
    let hh = num(p, "hoehe", 50.0);
    let a = (hh / (rr * (PI / n as f64).cos())).atan();
    let name = &unique("Turmhelm")?;
    let (mut bodies, apex) = zelt(name, c, n, rr, zb, a, num(p, "ueberstand", 2.0), t, "Helm")?;
    if flag(p, "kreuz", true) {
        bodies.push(kreuz(name, apex, num(p, "kreuz_h", 12.0), t, Some(a))?);
    }
    Ok(json!({"turm": pre, "ecken": n, "koerper": bodies}))
}

// ------------------------------------------------------------------ Vordach

fn vordach(p: &Value) -> R<Value> {
    let (wall, pt) = pick(p, "wand")?;
    let pt = pt.ok_or_else(|| invalid("wand", "Wandfläche anklicken"))?;
    let all = measure()?;
    let bx = all.iter().find(|(n, _)| n == &wall).map(|x| x.1)
        .ok_or_else(|| invalid("wand", format!("Körper `{wall}` nicht gefunden")))?;
    let ax = bx.thin_axis();
    if ax == 2 {
        return Err(invalid("wand", "senkrechte Wand anklicken"));
    }
    let mut nn = crate::e(ax);
    let mut pp = pt;
    if (pt[ax] - bx.lo[ax]).abs() < (pt[ax] - bx.hi[ax]).abs() {
        nn = mul(nn, -1.0);
        pp[ax] = bx.lo[ax];
    } else {
        pp[ax] = bx.hi[ax];
    }
    let up = [0.0, 0.0, 1.0];
    let right = cross(up, nn);
    let y0 = bx.lo[2] - pp[2];                      // Wandunterkante in Wandkoordinaten
    let t = num(p, "staerke", 3.0);
    let dv = num(p, "tiefe", 20.0);
    let nk = num(p, "neigung", 12.0).to_radians();
    let tk = nk.tan();
    let zv = y0 + num(p, "z", 30.0);
    let w = num(p, "breite", 40.0);
    let u0 = num(p, "x", 0.0) - w / 2.0;
    let ovv = 2.0;
    let lv = (dv + ovv) / nk.cos();
    let wp = |u: f64, d: f64, z: f64| add(pp, add(mul(right, u), add(mul(nn, d), mul(up, z))));
    let name = &unique("Vordach")?;
    let mut bodies = vec![];
    let down = sub(mul(nn, nk.cos()), mul(up, nk.sin()));
    let n2 = add(mul(nn, nk.sin()), mul(up, nk.cos()));
    let a0 = wp(u0, 0.0, zv);
    let pts = [a0, add(a0, mul(right, w)), add(add(a0, mul(right, w)), mul(down, lv)), add(a0, mul(down, lv))];
    bodies.push(plate3d(&format!("{name} Dach"), &pts, n2, t, false, &[])?);
    // Binder: Balken + Kopfband (Viertelkreis-Kehle) + Stütze, als ein Umriss
    let (bh, pw, rk) = (3.0, t.max(3.0), 4.0);
    let zr = |d: f64| zv - d * tk;
    let xp = dv - pw;
    let zc = zr(xp) - bh;
    let bottom = if flag(p, "stuetzen", true) { y0 } else { zc - rk - 2.0 };
    let mut prof: Vec<[f64; 2]> = vec![[0.0, zr(0.0) - 0.05], [dv, zr(dv) - 0.05], [dv, bottom],
                                        [xp, bottom], [xp, zc - rk]];
    let (cx, cz) = (xp - rk, zc - rk);
    for k in 1..=12 {
        let th = (k as f64 / 12.0) * PI / 2.0;
        prof.push([cx + rk * th.cos(), cz + rk * th.sin()]);
    }
    prof.push([xp - rk, zr(xp - rk) - bh]);
    prof.push([0.0, zr(0.0) - bh]);
    let nb = ((w / 30.0).round() as usize + 1).max(2);
    for j in 0..nb {
        let ub = u0 + t / 2.0 + 1.0 + (w - t - 2.0) * j as f64 / (nb - 1) as f64;
        let pts3: Vec<V3> = prof.iter().map(|&[d, z]| wp(ub - t / 2.0, d, z)).collect();
        bodies.push(plate3d(&format!("{name} Binder {}", j + 1), &pts3, right, t, false, &[])?);
    }
    // Volant: Zackenbrett vor der Dachkante
    if flag(p, "volant", true) {
        let d_end = dv + ovv + t * nk.sin() + 0.15;
        let ztop = zv - lv * nk.sin() + t * nk.cos();
        let hv = 5.0;
        let mut zz: Vec<[f64; 2]> = vec![[0.0, ztop]];
        let mut xx = 0.0;
        while xx <= w + 0.01 {
            zz.push([xx.min(w), ztop - hv + 1.6]);
            zz.push([(xx + 1.5).min(w), ztop - hv]);
            xx += 3.0;
        }
        zz.push([w, ztop - hv + 1.6]);
        zz.push([w, ztop]);
        let mut ring: Vec<[f64; 2]> = vec![];
        for q in zz {
            if ring.last().is_none_or(|l: &[f64; 2]| (l[0] - q[0]).abs() + (l[1] - q[1]).abs() > 1e-6) {
                ring.push(q);
            }
        }
        let pts3: Vec<V3> = ring.iter().map(|&[uu, z]| wp(u0 + uu, d_end, z)).collect();
        bodies.push(plate3d(&format!("{name} Volant"), &pts3, nn, t, false, &[])?);
    }
    Ok(json!({"wand": wall, "koerper": bodies}))
}
