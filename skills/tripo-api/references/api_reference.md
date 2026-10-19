---
description: "Tripo API v3 through the tripo_* tools: model versions, texture and geometry options, version limits, image models, rig specs, retopology engines, input forms and credit prices"
metadata:
  label: "API reference"
---

# Tripo API v3 notes (via our tools)

Base `https://openapi.tripo3d.ai/v3`, Bearer `tsk_…`. Statuses: `queued` → `running` → `success` | `failed` | `cancelled`. Failed jobs carry `error_code` (2008 content policy, 2018 timeout, 2010 no credits) and are refunded.

## Inputs

`source` / `image` take: a Tripo `task_id` (cheapest — no upload), a local path (uploaded: pictures ≤20 MB, models ≤150 MB), an https link, a data: URI, or a `file_token` from `tripo_upload`.

## 3D generation (`tripo_text_to_3d`, `tripo_image_to_3d`, `tripo_multiview_to_3d`)

| model_version | Use |
|---|---|
| `v3.1-20260211` | best quality (default) |
| `v3.0-20250812` | stable, all advanced options |
| `v2.5-20250123` | balanced; no HD geometry / quad / smart low-poly / parts / auto size |
| `P1-20260311` | clean low-poly, face_limit 50–20,000; no quad, smart low-poly, parts, HD geometry |
| `P2-20260801` | P series with quads (preview), face_limit 48–50,000 (quad 48–25,000) |

- `texture`: `pbr` (base color, metallic, roughness, normal), `texture` (color only), `none` (geometry only, cheaper).
- `texture_quality`: `fast` (texture v3.5), `standard`, `detailed` (HD, +10), `extreme` (8K, +20).
- `geometry_quality="detailed"` (+20), `quad` (FBX, +5, default 10k faces), `smart_low_poly` (+10; 500–20k tri / 500–10k quad), `generate_parts` (+20; untextured only), `auto_size` (meters).
- `face_limit` caps: v3.1 1.5M (2M HD), v3.0 1M (2M HD), v2.5 500k, quad 150k. Game assets: 50k–100k; mobile 10k–50k.
- Multi-view: front required, ≥2 views; or a `tripo_image_to_multiview` / `tripo_edit_multiview` task id.

## Pictures

`tripo_text_to_image` models: `seedream_v4` (default, 5), `seedream_v5` (5), `banana` (5), `banana2` (10; 4K 15), `banana_pro` (15; 4K 20), `chat_image_2` / `chat_image_2.5_flare` / `chat_image_2.5_sunburst` (10; 4K 15; `quality` high/xhigh/max cost more). `aspect_ratio` only on banana models; `size` (2K, 4K, 2048x1152…) on the others. Templates: `t_pose`, `character_completion`, `3d_enhance`, `variants`, `figure`, `asset_extraction`. `tripo_image_to_image` defaults to `seedream_v5` and takes up to 4 (seedream) / 10 (banana) / 16 (chat_image) reference pictures.

## Processing

- **Texture**: prompt (`text_prompt` + optional `style_image`) or `reference_image`; quality fast/standard 10, HD 20, 8K 30; `part_names` from segmentation.
- **Convert**: `GLTF`, `FBX`, `USDZ`, `OBJ`, `STL`, `3MF`; `fbx_preset` blender/3dsmax/mixamo/bake_scale; options (pivot, scale, polycount, texture size/format, flatten bottom, quad) bill 10 instead of 5. OBJ arrives zipped with textures and is unpacked.
- **Retopology** (`mesh/decimate`): `v3.0` 35 tri / 40 quad (supports `smart_uv`), `v2.0` 30, `v1.0` 10 (needs face_limit). Textures baked on unless `bake=false`.
- **Smart UV** (`mesh/uv`): ≤80k equivalent triangles, 20 credits, returns a UV atlas picture.
- **Segment**: `v1.0-20250506` (by shape) or `v2.0-20260430` (named parts; granularity simple/balanced/detailed, optional ref image), 40. **Complete parts**: on a segment task; `ai_completion` 50, `quick_cap` 30.
- **Stylize**: lego, voxel, voronoi, minecraft, keyring, fridge_magnet, keycap (`block_size` optional).

## Rigging and animation

- `tripo_rig_check`: free; returns `riggable` and the fitting `rig_type`.
- `tripo_rig` (25): `rig_type` biped (default), quadruped, hexapod, octopod, avian, serpentine, aquatic, others. Rig engine: `v1.0-20240301` biped (100+ animations), `v2.5-20260210` creatures, `v3.0-20260909` for `others` and the `unreal`/`unity`/`actorcore`/`vrm` specs (picked automatically). `spec` only applies to bipeds. `out_format` fbx (default here) or glb.
- `tripo_animate` (10 each, ≤5 per job): needs the rig `task_id`; names → presets per rig engine (see `animations`).

## Credits

1 credit = $0.01. Estimates come from developers.tripo3d.ai/en/pricing; the finished job's `credits_consumed` is the real cost. Stylize and splat prices are not published — the tools use an estimate.
