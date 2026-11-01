# Node reference

Generated from the code by `scripts/gen_node_docs.py` — 87 nodes. Node and port names are German (as in the app); *list* means the input takes a whole branch at once.

## Parameter

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Zahl** | Number slider | — | `N` | Slider with editable min, max and decimals. |
| **Geometrie holen** | Pick geometry | — | `geometrie` | Take the selection from SolidCraft or Serpentine3D; a copy is stored in the graph, *linked* re-reads it when the CAD model changes. |
| **Folge** | Series | `start` number = 0<br>`schritt` number = 1<br>`anzahl` integer = 10 | `liste` | start, start+step, … (count values). |
| **Bereich** | Range | `von` number = 0<br>`bis` number = 1<br>`teile` integer = 10 | `liste` | Divide [from, to] into n equal steps (n+1 values). |
| **Punkt** | Point | `x` number = 0<br>`y` number = 0<br>`z` number = 0 | `punkt` | Point from x, y, z. |
| **Anzeige** | Panel | `wert` anything *(list)* | — | Shows values and the data tree. |

## Mathe

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Rechnen** | Math | `a` number = 0<br>`b` number = 1 | `ergebnis` | + − × ÷ ^ min max remainder. |
| **Funktion** | Expression | `x` number = 0<br>`y` number = 0<br>`z` number = 0<br>`a` number = 0<br>`b` number = 0 | `ergebnis` | Formula in x y z a b, with sin, cos, pi, sqrt … |

## Listen

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Listen-Element** | List item | `liste` anything *(list)*<br>`index` integer = 0 | `element` | Item at index (wraps around). |
| **Listen-Länge** | List length | `liste` anything *(list)* | `laenge` | Number of items per branch. |
| **Umkehren** | Reverse list | `liste` anything *(list)* | `liste` |  |
| **Liste versetzen** | Shift list | `liste` anything *(list)*<br>`um` integer = 1 | `liste` | Shift by n, optionally wrapping. |
| **Teilen** | Partition list | `liste` anything *(list)*<br>`groesse` integer = 2 | `teile` | Split into chunks; each chunk becomes a branch. |

## Baum

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Aufpfropfen** | Graft | `daten` anything *(list)* | `daten` | Every item into its own branch. |
| **Glätten** | Flatten | `daten` anything *(list)* | `daten` | All branches into one. |
| **Vereinfachen** | Simplify | `daten` anything *(list)* | `daten` | Remove the common path prefix. |
| **Matrix tauschen** | Flip matrix | `daten` anything *(list)* | `daten` | Swap branches and items. |
| **Zweig wählen** | Tree branch | `daten` anything *(list)*<br>`index` integer = 0 | `liste` | Pick a branch by index. |
| **Zusammenführen** | Merge | `a` anything *(list)*<br>`b` anything *(list)* | `daten` | Merge two trees branch by branch. |

## Kurven

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Linie** | Line | `a` point = 0 0 0<br>`b` point = 100 0 0 | `kurve` |  |
| **Polylinie** | Polyline | `punkte` point *(list)* | `kurve` | Through points; open or closed. |
| **Kurve durch Punkte** | Interpolated curve | `punkte` point *(list)* | `kurve` | Smooth curve through points. |
| **Kreis** | Circle | `mitte` point = 0 0 0<br>`radius` number = 50 | `kurve` |  |
| **Rechteck** | Rectangle | `ecke` point = 0 0 0<br>`breite` number = 100<br>`hoehe` number = 50 | `kurve` |  |
| **Polygon** | Polygon | `mitte` point = 0 0 0<br>`radius` number = 30<br>`seiten` integer = 6 | `kurve` | Regular n-gon. |
| **Kurve teilen** | Divide curve | `kurve` geometry<br>`anzahl` integer = 10 | `punkte` | Points along a curve. |
| **Kurve versetzen** | Offset curve | `kurve` geometry<br>`abstand` number = 2 | `kurve` | Planar offset; negative = inwards. |
| **Text** | Text | `hoehe` number = 10 | `kurven` | Text outlines as curves. |

## Körper

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Extrudieren** | Extrude | `profil` geometry<br>`hoehe` number = 50 | `form` | Profile along Z, optionally capped to a solid. |
| **Loft** | Loft | `profile` geometry *(list)* | `form` | Through a list of profiles. |
| **Drehkörper** | Revolve | `profil` geometry<br>`achspunkt` point = 0 0 0<br>`richtung` point = 0 0 1<br>`winkel` number = 360 | `form` |  |
| **Box** | Box | `ecke` point = 0 0 0<br>`x` number = 50<br>`y` number = 50<br>`z` number = 50 | `form` |  |
| **Zylinder** | Cylinder | `basis` point = 0 0 0<br>`radius` number = 20<br>`hoehe` number = 50 | `form` |  |
| **Kugel** | Sphere | `mitte` point = 0 0 0<br>`radius` number = 25 | `form` |  |
| **Boolean** | Boolean | `a` geometry<br>`b` geometry *(list)* | `form` | Difference, union or intersection; b is a list. |
| **Schale** | Shell | `koerper` geometry<br>`wand` number = 2 | `form` | Hollow out, optionally open at the top. |
| **Abrunden** | Fillet | `koerper` geometry<br>`radius` number = 2 | `form` | Round all edges. |
| **Sweep** | Sweep | `profil` geometry<br>`pfad` geometry | `form` | Profile along a path. |
| **Rohr** | Pipe | `pfad` geometry<br>`radius` number = 3 | `form` | Tube around a curve. |

## Pyramiden

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Pyramide, vierseitig** | Square pyramid | `mitte` point = 0 0 0<br>`durchmesser` number = 40<br>`hoehe` number = 30 | `form` |  |
| **Pyramide, dreiseitig** | Triangular pyramid | `mitte` point = 0 0 0<br>`durchmesser` number = 40<br>`hoehe` number = 30 | `form` |  |
| **Bipyramide** | Bipyramid | `mitte` point = 0 0 0<br>`durchmesser` number = 40<br>`hoehe` number = 40<br>`seiten` integer = 5 | `form` |  |
| **Antiprisma** | Antiprism | `mitte` point = 0 0 0<br>`durchmesser` number = 40<br>`seiten` integer = 6 | `form` | Uniform: all edges equal. |

## Platonische Körper

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Tetraeder** | Tetrahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Hexaeder** | Cube | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Oktaeder** | Octahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Dodekaeder** | Dodecahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Ikosaeder** | Icosahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |

## Abgestumpfte

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Tetraederstumpf** | Truncated tetrahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Würfelstumpf** | Truncated cube | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Oktaederstumpf** | Truncated octahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Dodekaederstumpf** | Truncated dodecahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Ikosaederstumpf** | Truncated icosahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` | The football. |

## Weitere archimedische

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Kuboktaeder** | Cuboctahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Ikosidodekaeder** | Icosidodecahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Rhombenkuboktaeder** | Rhombicuboctahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Großes Rhombenkuboktaeder** | Truncated cuboctahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Rhombenikosidodekaeder** | Rhombicosidodecahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Großes Rhombenikosidodekaeder** | Truncated icosidodecahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` |  |
| **Abgeschrägter Würfel** | Snub cube | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` | One handedness. |
| **Abgeschrägtes Dodekaeder** | Snub dodecahedron | `mitte` point = 0 0 0<br>`durchmesser` number = 40 | `form` | One handedness. |

## Transform

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Verschieben** | Move | `geometrie` geometry<br>`x` number = 0<br>`y` number = 0<br>`z` number = 10 | `geometrie` |  |
| **Drehen** | Rotate | `geometrie` geometry<br>`winkel` number = 45<br>`mitte` point = 0 0 0 | `geometrie` | About X, Y or Z. |
| **Skalieren** | Scale | `geometrie` geometry<br>`faktor` number = 1<br>`mitte` point = 0 0 0 | `geometrie` |  |
| **Spiegeln** | Mirror | `geometrie` geometry<br>`punkt` point = 0 0 0<br>`normale` point = 1 0 0 | `geometrie` |  |
| **Kreisförmig anordnen** | Polar array | `geometrie` geometry<br>`anzahl` integer = 6<br>`winkel` number = 360<br>`mitte` point = 0 0 0 | `kopien` |  |

## Muster

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Zufall** | Random numbers | `anzahl` integer = 10<br>`min` number = 0<br>`max` number = 1<br>`seed` integer = 1 | `zahlen` | Seeded. |
| **Zufallspunkte** | Random points | `ecke` point = 0 0 0<br>`breite` number = 100<br>`hoehe` number = 100<br>`anzahl` integer = 30<br>`seed` integer = 1 | `punkte` | In a rectangle, seeded. |
| **Voronoi** | Voronoi | `punkte` point *(list)*<br>`ecke` point = 0 0 0<br>`breite` number = 100<br>`hoehe` number = 100 | `zellen` | Cells clipped to a rectangle (no SciPy needed). |

## Laser

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Fingerzinken** | Finger joint edge | `a` point = 0 0 0<br>`b` point = 100 0 0<br>`staerke` number = 3<br>`zinke` number = 10 | `kante` | Toothed edge between two points. |
| **Zinken-Box** | Finger-jointed box | `breite` number = 100<br>`tiefe` number = 70<br>`hoehe` number = 50<br>`staerke` number = 3<br>`zinke` number = 10<br>`abstand` number = 5 | `flach`, `montiert` | Six (or five) panels, flat for the laser and assembled in 3D; exact joints. |
| **Living Hinge** | Living hinge | `ecke` point = 0 0 0<br>`breite` number = 60<br>`hoehe` number = 80<br>`schnitt` number = 18<br>`steg` number = 3<br>`abstand` number = 1.5 | `schnitte` | Bend pattern: cut length, bridge, spacing. |
| **Kerf-Ausgleich** | Kerf compensation | `teile` geometry *(list)*<br>`kerf` number = 0.1 | `konturen` | Outlines grow, holes shrink by half the kerf. |
| **Verschachteln** | Nesting | `teile` geometry *(list)*<br>`breite` number = 200<br>`hoehe` number = 200<br>`abstand` number = 3 | `platziert`, `platten`, `rest` | Pack parts onto sheets (shelf packing); one branch per sheet. |
| **SVG-Export (Laser)** | Laser SVG export | `schneiden` geometry *(list)*<br>`gravieren` geometry *(list)* | `datei` | mm-exact SVG: red = cut, blue = engrave. |
| **Schlitze** | Slots | `platte` geometry<br>`punkte` point *(list)*<br>`breite` number = 3<br>`tiefe` number = 20 | `platte` | Cross slots for slotted (waffle) assemblies. |
| **Konturschnitt** | Contour slices | `koerper` geometry<br>`anzahl` integer = 8<br>`abstand` number = 5 | `schnitte`, `flach` | Sections along an axis, laid out flat. |
| **Waffel** | Waffle | `koerper` geometry<br>`nx` integer = 4<br>`ny` integer = 4<br>`staerke` number = 3<br>`abstand` number = 5 | `montiert`, `flach` | Body → interlocking ribs with half-slots, laid out flat. |

## 3D-Druck

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Druck-Check** | Print check | `koerper` geometry<br>`winkel` number = 45<br>`wand` number = 1.0 | `ueberhang`, `flaechen`, `bericht` | Overhang %, thinnest wall, watertight; overhangs shown red. |
| **Auf Bett legen** | Place on bed | `koerper` geometry | `koerper` | Largest flat face down, centred, z = 0. |
| **Toleranz-Paar** | Clearance pair | `mitte` point = 0 0 0<br>`durchmesser` number = 8<br>`laenge` number = 20<br>`spiel` number = 0.2 | `stift`, `bohrung` | Pin and hole with clearance. |
| **Gitter-Füllung** | Lattice infill | `koerper` geometry<br>`zelle` number = 10<br>`steg` number = 1.5<br>`haut` number = 1.2 | `koerper` | Honeycomb or cubic lattice inside a skin. |
| **Gyroid** | Gyroid | `mitte` point = 0 0 0<br>`breite` number = 40<br>`tiefe` number = 40<br>`hoehe` number = 40<br>`zelle` number = 12<br>`wand` number = 1.2<br>`feinheit` integer = 10 | `netz` | Gyroid sheet in a box or cylinder (mesh). |
| **Gewinde** | Thread | `mitte` point = 0 0 0<br>`durchmesser` number = 10<br>`steigung` number = 1.5<br>`laenge` number = 12<br>`toleranz` number = 0.2 | `gewinde` | Metric-style bolt thread or hole tool with clearance. |
| **Prägen** | Emboss | `koerper` geometry<br>`hoehe` number = 8<br>`tiefe` number = 0.6 | `koerper` | Raised or engraved text on the top face. |
| **Mehrfarb-Teilen** | Multi-colour split | `koerper` geometry<br>`hoehen` number *(list)* | `teile` | Cut a body at heights into parts (one per tool/colour). |

## Ausgabe

| Node | English | Inputs | Outputs | Notes |
|---|---|---|---|---|
| **Export** | Export | `geometrie` geometry *(list)* | `datei` | STL, 3MF or STEP — writes only while *write* is ticked. |
