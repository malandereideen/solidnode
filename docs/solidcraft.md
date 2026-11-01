# Working with SolidCraft

SolidNode drives a **running** SolidCraft through SolidCraft's own MCP interface — the same one AI agents use. Nothing is patched or injected.

## Connection

1. SolidCraft must be started with its control port: `--control 7878` (or click *SolidCraft starten* in SolidNode; on macOS that runs `open -n -a SolidCraft --args --control 7878`).
2. SolidNode starts `solidcraft-cli mcp --connect 127.0.0.1:7878 --allow-path ~/.solidnode/transfer` and keeps it open while the app runs.
3. Files are exchanged through `~/.solidnode/transfer`. SolidCraft only reads files from folders it was allowed (`--allow-path`), which is why everything goes through that one folder.

`solidcraft-cli` is looked up in this order: `$SOLIDNODE_SOLIDCRAFT_CLI`, your `PATH`, `/Applications/SolidCraft.app/Contents/MacOS/`, `~/Applications/…`, `C:\Program Files\SolidCraft\`. The port can be changed with `$SOLIDNODE_SOLIDCRAFT_PORT`.

## Sending geometry

| Geometry in the graph | Arrives in SolidCraft as |
|---|---|
| Solids, surfaces | STEP import (`file.insert_step`) — real B-rep bodies |
| Meshes (e.g. gyroid) | STL import (`file.insert_mesh`) — mesh bodies |
| Flat curves (laser parts, text) | SVG into a sketch on XY (`sketch.insert_svg`) — editable sketch curves in world coordinates |
| Points | left out |

- **An SolidCraft senden** puts everything into a component **Nodes Vorschau**. The next send deletes that component and creates it again, so it is always one undo step per send and never piles up.
- **live in SolidCraft** sends automatically 1 s after the last change.
- **Bake** creates a separate component **Nodes HH:MM:SS** that SolidNode never touches again.
- **Vorschau dort entfernen** deletes *Nodes Vorschau*.

What goes out is what the preview shows: the *ends* of the graph (nodes whose outputs aren't used further, plus selected nodes). Red warning geometry (print-check overhangs) is not sent.

## Picking geometry

**Geometrie holen** reads `inspect_design → selection`:

| Selected in SolidCraft | How SolidNode gets it |
|---|---|
| Body | `export` of that body as STEP, read back with OpenCASCADE |
| Face / edge | The body is exported, then the face/edge closest to the picked point is taken |
| Sketch line / arc / circle | Rebuilt from the sketch data (plane origin and axes, start/end/centre) |

The geometry is stored in the graph file (as B-rep text), so a graph opens even without SolidCraft. With **verknüpft** (linked) SolidNode polls the design's revision counter every 1.5 s and re-reads the references (body name, sketch id + curve id) when it changed.

## Limits

- Splines and other curve types in sketches aren't read yet (lines, arcs, circles are).
- After a body is renamed in SolidCraft, a linked pick can't find it any more — pick again.
- Sending is synchronous: big STEP files freeze the window for a moment.
- Snub polyhedra are built in one handedness only.

## Testing without touching your design

Every test in this repo uses `solidcraft-cli mcp --headless`, an invisible SolidCraft instance. You can do the same with the app:

```bash
solidnode --solidcraft-headless
```
