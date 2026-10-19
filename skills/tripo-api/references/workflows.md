---
description: "The Tripo workflow nodes (Text/Image/Multi-view to 3D, pictures, Texture, Retopology, Smart UV, Segment, Complete Parts, Convert, Stylize, Rig Check, Auto Rig, Animate, Balance), their pins, chaining and the ready-made templates"
metadata:
  label: "Workflow nodes"
---

# Tripo workflow nodes

All in the **Tripo** group. Value nodes: they run when something needs their output. Paid nodes run only with **Spend credits** on in their details (leave it off when you build a workflow for someone and tell them which switch to turn on). Outputs carry their Tripo task, so wiring one Tripo node into the next chains on the task instead of uploading the file.

| Node | In | Out |
|---|---|---|
| `tripo.text_to_3d` Text to 3D | prompt, negative, polycount | mesh, preview, files, task_id |
| `tripo.image_to_3d` Image to 3D | image, polycount | mesh, preview, files, task_id |
| `tripo.multiview_to_3d` Multi-view to 3D | views (from Image to Multi-view) or front/left/back/right | mesh, preview, files, task_id |
| `tripo.image_to_splat` Image to Splat | image | splat, files, task_id |
| `tripo.text_to_image` Text to Image | prompt | image, files, task_id |
| `tripo.edit_image` Edit Image | image, prompt, refs | image, files, task_id |
| `tripo.image_to_multiview` Image to Multi-view | image | views, front, left, back, right |
| `tripo.edit_multiview` Edit Multi-view | views, front_edit…right_edit | views, front, left, back, right |
| `tripo.texture` Texture Model | mesh, prompt, image, style_image | mesh, preview, files |
| `tripo.retopology` Retopology | mesh, polycount | mesh, preview, files |
| `tripo.smart_uv` Smart UV | mesh | mesh, uv, files |
| `tripo.segment` Segment Parts | mesh, ref_image | mesh, preview, files |
| `tripo.complete_parts` Complete Parts | mesh (from Segment), parts | mesh, preview, files |
| `tripo.convert` Convert | mesh, polycount | mesh, preview, files |
| `tripo.stylize` Stylize | mesh | mesh, preview, files |
| `tripo.rig_check` Rig Check (free) | mesh | riggable, rig_type, info |
| `tripo.rig` Auto Rig | mesh | mesh (rigged), preview, files, rig_type |
| `tripo.animate` Animate | mesh (from Auto Rig), animations | mesh (first), meshes (all), files |
| `tripo.balance` Balance (free) | — | balance, frozen |

Details worth knowing: Text/Image/Multi-view to 3D have Model (v3.1 … P2), Texture (PBR / color / none), Texture quality, HD geometry, Max polygons, Quads, Smart low-poly, Separate parts, Real-world size. Auto Rig: Skeleton (Auto runs the free rig check), Bone names (Unreal = UE mannequin), File (FBX/GLB), Rig engine. Animate: comma-separated names, up to 10, one model per animation.

Any mesh works as input to Texture, Retopology, Smart UV, Segment, Convert and Rig (a local GLB/FBX/OBJ is uploaded); Stylize, Animate and Complete Parts need a Tripo node's output. Tripo meshes also feed the built-in nodes (Set Mesh Origin, Mesh BBox Fit, Send to UEFN, Open in Blender).

## Built-in nodes on Tripo

On apps that list plugin backends, the built-in Text to 3D (Tripo, Tripo P1), Image to 3D, Multi-view to 3D, (Re)Texture Mesh, Optimize Mesh (retopology), UV Unfold (smart UV), Convert 3D Model, Rig Humanoid Mesh (any creature, skeleton picked by the free rig check), Animate Rigged Mesh (names like idle, walk, run) and Edit Image nodes offer Tripo in their Backend dropdown. Their outputs chain into the Tripo nodes and back on the Tripo task.

## Templates (New workflow → "Tripo: …")

- Prompt to 3D model in UEFN · Picture to 3D model in UEFN
- Prompt → rigged, animated character → UEFN (Text to 3D → Auto Rig (auto) → Animate idle/walk/run → Send to UEFN)
- Prompt → concept → 4 views → 3D model
- Make any model game-ready (Retopology 8k + smart UV → origin → UEFN)
- Repaint a model · Prompt → LEGO-style model

Building one with tools: `create_workflow_from_template`, or `save_workflow` with nodes of these types and data wires (`kind: "data"`, `source_pin`/`target_pin` as above).
