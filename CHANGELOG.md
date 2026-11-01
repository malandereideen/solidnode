# Changelog

## 0.1.2 — 2026-11-01

- Update check at start: if GitHub has a newer version, a toolbar button installs it (uv tool, pip, or `git pull` for a clone) and restarts with the open graph. Also `solidnode update`; `SOLIDNODE_NO_UPDATE_CHECK=1` turns it off.

## 0.1.1 — 2026-11-01

- Hover card in the palette: a rendered preview of what the node makes, a one-line description and its ports (`scripts/gen_node_previews.py`).

## 0.1.0 — 2026-11-01

First public version.

- Stand-alone app: live preview on top, node canvas below, compact icon palette with search.
- Targets: SolidCraft (send, live, bake, remove preview), Serpentine3D (live preview, bake, via plugin bridge), or preview only (bake to STEP/3MF/STL). Automatic detection of what is running.
- Pick geometry from SolidCraft (bodies, faces, edges, sketch lines/arcs/circles) or Serpentine3D, stored in the graph, optionally linked.
- Data trees: graft, flatten, simplify, flip matrix, branch, merge; list nodes.
- 87 nodes: parameters, math, lists, trees, curves, solids, transforms, patterns, laser cutting, 3D printing, polyhedra, export.
- Six examples, `solidnode doctor`, headless test suite.
