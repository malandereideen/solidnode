# How SolidNode works

```
 ┌──────────── SolidNode app (PySide6) ────────────┐
 │  preview: Serpentine3D viewport (empty scene)   │
 │  ───────────────────────────────────────────────│
 │  palette │ node canvas (NodeGraphQt)            │
 └──────────────┬──────────────────────────────────┘
                │ Router: own preview + one target
      ┌─────────┴──────────┐
 SolidCraftHost        SerpentineRemote
 solidcraft-cli mcp    TCP bridge (plugin inside Serpentine3D)
```

## Files

| File | Role |
|---|---|
| `src/solidnode/core.py` | Node base class, data trees, the panel (evaluation, preview, palette, compact node look), the general nodes, and the optional Serpentine3D plugin entry |
| `src/solidnode/fabrication.py` | Laser and 3D-print nodes |
| `src/solidnode/polyhedra.py` | Pyramids, Platonic and Archimedean solids (vertex sets → convex hull → sewn solid) |
| `src/solidnode/hosts.py` | Targets: SolidCraft over MCP, Serpentine3D in-process and over the bridge; shape transport; picking |
| `src/solidnode/app.py` | The stand-alone window, target selection and auto-detection |
| `src/solidnode/cli.py` | `solidnode`, `solidnode doctor`, `solidnode install-serpentine-plugin` |

## Evaluation

- Every wire carries a `Tree` (`{path: [values]}`).
- A change marks the node and everything downstream dirty; a 30 ms debounce then recomputes only those, in topological order.
- `SerpNode.compute` matches branches (longest wins) and items within a branch; inputs flagged as *list* get the whole branch. If `solve()` returns a list and there were several iterations, each iteration gets a sub-branch.
- Connected values are coerced to the input type (a float slider into an integer input). Missing inputs turn a node yellow, exceptions red.

## Preview

The preview is the result of the graph's ends: nodes whose outputs are unused or only go into *Anzeige*/*Export*/*Druck-Check* (`SINK`), plus selected nodes. Shapes are tessellated once per result and drawn as Serpentine3D's two-colour overlay — green for results, red for warnings (`WARN_OUTPUTS`).

## Targets

- **Auto** polls every 1.5 s: SolidCraft = TCP connect to the control port; Serpentine3D = the bridge answers `ping`. With both available, the one you had in front last wins (macOS only; elsewhere the first one).
- **SolidCraft** runs in the Qt main thread on purpose: a worker thread let Python's garbage collector free Qt objects off the GUI thread.
- **Serpentine3D bridge**: the plugin opens a localhost `QTcpServer`, writes its port to `~/.serpentine3d/nodes-bridge.json`, and accepts line-delimited JSON (`ping`, `preview`, `bake`, `fit`, `pick`, `fetch`, `rev`). Geometry travels as `.brep` / `.npz` files.

## Adding a node

```python
class MyNode(SerpNode):
    __identifier__ = "serp.Koerper"          # palette group
    NODE_NAME = "Mein Node"
    INPUTS = [("koerper", "geo", None, False),   # name, kind, default, list?
              ("wert", "num", 2, False)]
    OUTPUTS = ["form"]

    def solve(self, koerper, wert):
        return ...                            # one value per output
```

Add it to `NODE_CLASSES`, give it a symbol in `SYMBOLS`, then run `scripts/gen_node_docs.py` and add its English name there.
