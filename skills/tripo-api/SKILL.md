---
name: tripo-api
description: "Tripo AI via UEFN-Ducky MCP — text/image/multi-view to 3D, pictures, texture, retopology, smart UV, segment/complete parts, convert, LEGO/voxel stylize, auto-rig, animate, then import to Blender or UEFN. Tools tripo_* and Tripo workflow nodes; async jobs with a spend lock."
license: MIT
metadata:
  label: Tripo
  version: 1
  author: UEFN-Ducky
  copyright: Copyright 2026 Mindful Path Company, LLC
  allow_redistribute: true
  managed_by: uefn-ducky
  source_plugin_id: tripo
---

# Tripo — generate via MCP

You call **`tripo_*` tools** on the shared `uefn-ducky` MCP (Tripo API v3, the engine behind studio.tripo3d.ai). The key lives in **Settings → Tripo** (encrypted; Test shows the balance). Never curl the API, read a `.env`, or install Tripo's own SDK/MCP.

## Prerequisites

1. Plugin **tripo** installed + enabled (Settings → Store), tools opted in for this chat.
2. Tripo API key pasted + Tested (`tsk_…` from developers.tripo3d.ai).
3. Blender import: Blender + its MCP add-on on `localhost:9876`. UEFN import: UEFN open, listener online.

## HARD RULES — CREDITS (non-negotiable)

Paid `tripo_*` tools **refuse** unless `confirm_spend=true`. Free: balance, usage, status, tasks, download, upload, list_animations, rig_check, imports.

1. Call `tripo_balance` before proposing paid work.
2. Call **`ducky_ask_user`** with a yes/no question that names the job and the ~credit cost (1 credit = $0.01). Never ask only in chat text.
3. Only on Spend / a clear yes: call the same tool again with `confirm_spend=true`.
4. One yes covers the job(s) named in that question — never chain extra paid jobs without a new yes. Silence or Cancel = do not spend.

## Core pattern

Every job is async. Tools default to `wait=true`: they poll and download every output into the plugin's folder and return `task_id`, `status`, `downloaded`, `model_url`. With `wait=false` you get a `task_id`; then `tripo_status(task_id, poll=true)` and `tripo_download(task_id)`.

**Chain on task ids.** Any `source` / `image` argument takes a Tripo `task_id`, a local file path, an https link, a data: URI or a `file_token`. Passing the previous job's `task_id` skips re-uploading (rig and animate require it). Output links last ~24 h — download promptly.

## Tools

| Tool | When | ~Credits |
|------|------|---------|
| `tripo_text_to_3d` | Prompt → model. `model_version` v3.1 (best) / v3.0 / v2.5 / P1·P2 (clean low-poly); `texture` pbr\|texture\|none | 10 untextured, 20 textured, + add-ons |
| `tripo_image_to_3d` | One picture → model | 20 / 30 |
| `tripo_multiview_to_3d` | front + left/back/right, or a multiview `task_id` | 20 / 30 |
| `tripo_image_to_splat` | Picture → Gaussian splat (not a mesh) | estimate |
| `tripo_text_to_image` | Concept art / the picture for image→3D (seedream_v4/v5, banana, banana2, banana_pro, chat_image_2…) | 5–20 |
| `tripo_image_to_image` | Edit a picture by prompt or template (`t_pose`, `3d_enhance`, `variants`, `character_completion`, `figure`) | 5–20 |
| `tripo_image_to_multiview` / `tripo_edit_multiview` | 4 views from one picture / fix a view by prompt | 10 / 5 per view |
| `tripo_texture` | Repaint any model from a prompt, style picture or reference picture | 10–30 |
| `tripo_retopology` | Game-ready low-poly (500–20k tri, 500–10k quad), textures baked; v3.0 + `smart_uv` | 10–40 |
| `tripo_smart_uv` | Clean UVs (≤80k tris) + UV atlas picture | 20 |
| `tripo_segment` → `tripo_complete_parts` | Split into parts, then fill hidden sides | 40 → 30/50 |
| `tripo_convert` | FBX / GLTF / OBJ / USDZ / STL / 3MF, `fbx_preset`, pivot, scale, polycount | 5 / 10 |
| `tripo_stylize` | lego, voxel, minecraft, voronoi, keyring, fridge_magnet, keycap | estimate |
| `tripo_rig_check` | Free: riggable? which rig type | 0 |
| `tripo_rig` | Skeleton + skin. `rig_type` biped…aquatic\|others; `spec` tripo\|mixamo\|unreal\|unity\|actorcore\|vrm | 25 |
| `tripo_list_animations` / `tripo_animate` | Presets → up to 5 animations on a `tripo_rig` task | 10 each |
| `tripo_import_to_uefn` / `tripo_import_to_blender` | Land the file | 0 |
| `tripo_balance` / `tripo_usage` / `tripo_status` / `tripo_tasks` / `tripo_download` / `tripo_upload` | Account and jobs | 0 |

## Pipelines

### Prop → UEFN
1. `tripo_balance` → `ducky_ask_user` (~20–30 credits) → `tripo_text_to_3d` or `tripo_image_to_3d` with `confirm_spend=true`.
2. Optional game-ready: `tripo_retopology(source=<task_id>, face_limit=8000, smart_uv=true)`.
3. `tripo_import_to_uefn(<downloaded glb/fbx>, destination_path="Tripo/Props")` — or `get_project_info()` first for a `/Project/...` path.

### Character → rig → animate → UEFN
1. Concept: `tripo_text_to_image` (or `tripo_image_to_image(template="t_pose")`) → `tripo_image_to_3d(image=<image task_id>)`; or `tripo_text_to_3d` with "full body, A-pose".
2. `tripo_rig_check(source=<model task_id>)` (free) → `tripo_rig(source=<model task_id>, rig_type=<its rig_type>, out_format="fbx")`. For UE mannequin bone names use `spec="unreal"` (rig v3.0).
3. `tripo_animate(rig_task_id=<rig task_id>, animations="idle, walk, run", rig_version=<from rig result>, rig_type=<from rig result>)`.
4. `tripo_import_to_uefn(<fbx>)` for each; skeleton cleanup / retargeting → **animation** or **blender** skill.

### Better shape from every side
`tripo_text_to_image` → `tripo_image_to_multiview(image=<task_id>)` → optional `tripo_edit_multiview` → `tripo_multiview_to_3d(multiview_task_id=<task_id>)`.

## Workflows

The **Tripo** node group (see reference `workflows`) does all of this without an agent: wire Text to 3D → Auto Rig → Animate → Send to UEFN. Nodes only spend with **Spend credits** on in their details; when you build a workflow for someone, leave it off and tell them which switch to turn on. Templates: "Tripo: …" in the New workflow picker.

## Don'ts

- Don't spend without a fresh `ducky_ask_user` yes; don't invent approval.
- Don't invent task status — poll with `tripo_status`.
- Don't rig before checking: run `tripo_rig_check` (free) when unsure of the skeleton.
- Don't animate a file: `tripo_animate` needs the `tripo_rig` task id.
- Don't send P1 options it rejects (quad, smart_low_poly, generate_parts, HD geometry) — the tool explains version limits.
- Don't invent skeletal UEFN import — hand off to **animation** / **blender** skills.

## Reference files

Load with MCP `skill_read_subskill("tripo-api", "<id>")`.

- `api_reference` — versions, options, limits and prices
- `workflows` — every Tripo workflow node and the templates
- `animations` — animation presets per rig version
- `setup` — key, Test, defaults

## Verify

`tripo_status` for the job; after import `get_static_mesh_info` / `get_skeletal_mesh_info`.
