"""Ein Satz je Node für die Hover-Karte in der Palette (die App ist deutsch;
englische Namen und Texte stehen in scripts/gen_node_docs.py)."""

import os

PREVIEWS = os.path.join(os.path.dirname(__file__), "previews")

DE = {
    # Parameter
    "Zahl": "Regler mit einstellbarem Minimum, Maximum und Nachkommastellen.",
    "Geometrie holen": "Übernimmt die Auswahl aus SolidCraft oder Serpentine3D. "
                       "Eine Kopie steht im Graph; „verknüpft“ holt sie neu, "
                       "wenn sich das CAD-Modell ändert.",
    "Folge": "Zahlenfolge: start, start+schritt, … (anzahl Werte).",
    "Bereich": "Teilt [von, bis] in gleich große Schritte (teile+1 Werte).",
    "Punkt": "Punkt aus x, y, z.",
    "Anzeige": "Zeigt Werte und den Datenbaum an.",
    # Mathe
    "Rechnen": "Plus, minus, mal, geteilt, hoch, min, max, Rest.",
    "Funktion": "Eigene Formel mit x y z a b, dazu sin, cos, pi, sqrt …",
    # Listen
    "Listen-Element": "Holt das Element an Stelle index (läuft im Kreis).",
    "Listen-Länge": "Anzahl der Elemente je Zweig.",
    "Umkehren": "Dreht die Reihenfolge der Liste um.",
    "Liste versetzen": "Verschiebt die Liste um n Stellen, wahlweise im Kreis.",
    "Teilen": "Zerlegt die Liste in Stücke; jedes Stück wird ein Zweig.",
    # Baum
    "Aufpfropfen": "Jedes Element bekommt einen eigenen Zweig (Graft).",
    "Glätten": "Alle Zweige zu einem zusammenlegen (Flatten).",
    "Vereinfachen": "Entfernt den gemeinsamen Anfang der Zweigpfade.",
    "Matrix tauschen": "Tauscht Zweige und Elemente (Flip Matrix).",
    "Zweig wählen": "Holt einen einzelnen Zweig per Index.",
    "Zusammenführen": "Legt zwei Bäume Zweig für Zweig zusammen.",
    # Kurven
    "Linie": "Gerade Linie von a nach b.",
    "Polylinie": "Linienzug durch Punkte, offen oder geschlossen.",
    "Kurve durch Punkte": "Glatte Kurve durch alle Punkte.",
    "Kreis": "Kreis um mitte mit radius.",
    "Rechteck": "Rechteck ab ecke mit Breite und Höhe.",
    "Polygon": "Regelmäßiges n-Eck.",
    "Kurve teilen": "Setzt gleichmäßig verteilte Punkte auf eine Kurve.",
    "Kurve versetzen": "Parallele Kurve im Abstand; negativ = nach innen.",
    "Text": "Schrift als Umrisskurven.",
    # Körper
    "Extrudieren": "Zieht ein Profil in Z hoch, wahlweise geschlossen als Körper.",
    "Loft": "Körper durch eine Reihe von Profilen.",
    "Drehkörper": "Dreht ein Profil um eine Achse.",
    "Box": "Quader ab ecke.",
    "Zylinder": "Zylinder auf basis.",
    "Kugel": "Kugel um mitte.",
    "Boolean": "Differenz, Vereinigung oder Schnitt; b darf eine Liste sein.",
    "Schale": "Höhlt einen Körper aus, wahlweise oben offen.",
    "Abrunden": "Rundet alle Kanten ab.",
    "Sweep": "Führt ein Profil an einem Pfad entlang.",
    "Rohr": "Rohr um eine Kurve.",
    # Transformieren
    "Verschieben": "Verschiebt Geometrie um x, y, z.",
    "Drehen": "Dreht um die X-, Y- oder Z-Achse.",
    "Skalieren": "Vergrößert oder verkleinert um einen Faktor.",
    "Spiegeln": "Spiegelt an einer Ebene (Punkt + Normale).",
    "Kreisförmig anordnen": "Kopien im Kreis um eine Mitte.",
    # Muster
    "Zufall": "Zufallszahlen zwischen min und max, mit seed wiederholbar.",
    "Zufallspunkte": "Zufällige Punkte in einem Rechteck, mit seed wiederholbar.",
    "Voronoi": "Voronoi-Zellen um Punkte, auf ein Rechteck beschnitten.",
    # Export
    "Export": "Schreibt STL, 3MF oder STEP — nur solange „schreiben“ an ist.",
    # Laser
    "Fingerzinken": "Gezahnte Kante zwischen zwei Punkten.",
    "Zinken-Box": "Box aus sechs (oder fünf) Platten mit Fingerzinken: "
                  "flach für den Laser und zusammengebaut in 3D.",
    "Living Hinge": "Biegemuster zum Lasern: Schnittlänge, Steg, Abstand.",
    "Kerf-Ausgleich": "Außenkonturen wachsen, Löcher schrumpfen um die halbe "
                      "Schnittbreite — Teile kommen maßhaltig aus dem Laser.",
    "Verschachteln": "Packt Teile platzsparend auf Platten; je Platte ein Zweig.",
    "SVG-Export (Laser)": "Maßgenaues SVG: rot = schneiden, blau = gravieren.",
    "Schlitze": "Steckschlitze für Steckbausätze.",
    "Konturschnitt": "Schnitte durch einen Körper entlang einer Achse, "
                     "flach ausgelegt zum Lasern.",
    "Waffel": "Körper → sich kreuzende Rippen mit Halbschlitzen, flach "
              "ausgelegt.",
    # 3D-Druck
    "Druck-Check": "Überhang in %, dünnste Wand, dicht? Überhänge rot.",
    "Auf Bett legen": "Größte ebene Fläche nach unten, mittig, z = 0.",
    "Toleranz-Paar": "Stift und Bohrung mit Spiel — zum Passung-Testen.",
    "Gitter-Füllung": "Waben- oder Würfelgitter innen, außen eine Haut.",
    "Gyroid": "Gyroid-Fläche in Quader oder Zylinder (als Netz).",
    "Gewinde": "Metrisches Bolzengewinde oder Bohrwerkzeug mit Spiel.",
    "Prägen": "Erhabene oder vertiefte Schrift auf der Oberseite.",
    "Mehrfarb-Teilen": "Schneidet einen Körper in Höhen auf — ein Teil je Farbe.",
    # Polyeder
    "Pyramide, vierseitig": "Pyramide mit quadratischer Grundfläche.",
    "Pyramide, dreiseitig": "Pyramide mit dreieckiger Grundfläche.",
    "Bipyramide": "Zwei Pyramiden Boden an Boden.",
    "Antiprisma": "Zwei gedrehte n-Ecke, verbunden durch Dreiecke.",
    "Tetraeder": "4 Dreiecke.",
    "Hexaeder": "Würfel, 6 Quadrate.",
    "Oktaeder": "8 Dreiecke.",
    "Dodekaeder": "12 Fünfecke.",
    "Ikosaeder": "20 Dreiecke.",
    "Tetraederstumpf": "Tetraeder mit abgeschnittenen Ecken.",
    "Würfelstumpf": "Würfel mit abgeschnittenen Ecken.",
    "Oktaederstumpf": "Oktaeder mit abgeschnittenen Ecken.",
    "Dodekaederstumpf": "Dodekaeder mit abgeschnittenen Ecken.",
    "Ikosaederstumpf": "Der Fußball: 12 Fünfecke, 20 Sechsecke.",
    "Kuboktaeder": "8 Dreiecke, 6 Quadrate.",
    "Ikosidodekaeder": "20 Dreiecke, 12 Fünfecke.",
    "Rhombenkuboktaeder": "8 Dreiecke, 18 Quadrate.",
    "Großes Rhombenkuboktaeder": "Quadrate, Sechsecke und Achtecke.",
    "Rhombenikosidodekaeder": "Dreiecke, Quadrate und Fünfecke.",
    "Großes Rhombenikosidodekaeder": "Quadrate, Sechsecke und Zehnecke.",
    "Abgeschrägter Würfel": "Würfel mit verdrehten Quadraten und vielen "
                            "Dreiecken.",
    "Abgeschrägtes Dodekaeder": "Dodekaeder mit verdrehten Fünfecken und "
                                "vielen Dreiecken.",
}


def preview_file(cls):
    """Pfad des Vorschaubilds eines Nodes (ASCII-Name), oder None."""
    name = cls.__name__
    for a, b in (("ä", "ae"), ("ö", "oe"), ("ü", "ue"), ("ß", "ss")):
        name = name.replace(a, b)
    path = os.path.join(PREVIEWS, name + ".png")
    return path if os.path.exists(path) else None


def card(cls, group):
    """Hover-Karte als Rich-Text: Bild, Name, ein Satz, Ein-/Ausgänge."""
    import html
    parts = []
    img = preview_file(cls)
    if img:
        parts.append(f'<img src="{img}" width="160" height="110"><br>')
    parts.append(f"<b>{html.escape(cls.NODE_NAME)}</b> "
                 f"<span style='color:#888'>· {html.escape(group)}</span>")
    text = DE.get(cls.NODE_NAME, "")
    if text:
        parts.append(f"<br>{html.escape(text)}")
    ins = ", ".join(n for n, *_ in getattr(cls, "INPUTS", []))
    outs = ", ".join(getattr(cls, "OUTPUTS", []))
    ports = " · ".join(p for p in (f"Ein: {ins}" if ins else "",
                                   f"Aus: {outs}" if outs else "") if p)
    if ports:
        parts.append(f"<br><span style='color:#888'>{html.escape(ports)}"
                     "</span>")
    return f"<div style='max-width:220px'>{''.join(parts)}</div>"
