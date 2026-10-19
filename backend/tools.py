"""tripo_* MCP tools on the shared uefn-ducky server.

Every paid job refuses unless confirm_spend=true (after a ducky_ask_user yes). Jobs run
async on Tripo: wait=true polls until done and downloads every output file.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import tripo as t

INTENT = (
    r"\b(tripo|tripo3d|tripo\s*ai|text[- ]?to[- ]?3d|image[- ]?to[- ]?3d|multi[- ]?view|"
    r"retopo(?:logy)?|low[- ]?poly|rig(?:ging)?|animat(?:e|ion)s?|lego|voxel|minecraft|splat|"
    r"segment(?:ation)?|smart\s*uv|3d\s*model)\b"
)

_DOWNLOADS: dict[str, Path] = {}


def _dumps(obj: Any) -> str:
    return json.dumps(obj, indent=2, default=str)


def download_root(api: Any = None) -> Path:
    """Where finished jobs land: the plugin's own local folder (old jobs are pruned)."""
    if "root" not in _DOWNLOADS:
        root: Path | None = None
        if api is not None and hasattr(api, "local_dir"):
            try:
                root = Path(api.local_dir("downloads"))
            except Exception:  # noqa: BLE001 — older apps: temp folder
                root = None
        if root is None:
            import tempfile

            root = Path(tempfile.gettempdir()) / "uefn-ducky-tripo" / "downloads"
        root.mkdir(parents=True, exist_ok=True)
        _DOWNLOADS["root"] = root
    return _DOWNLOADS["root"]


def _summary(parsed: dict[str, Any]) -> dict[str, Any]:
    """The task without the raw output echo (keeps answers short)."""
    keep = ("task_id", "kind", "type", "status", "progress", "finished", "failed", "failure_reason", "error_code",
            "model_url", "preview_url", "image_url", "credits_consumed", "riggable", "rig_type", "rig_version",
            "animations", "downloaded", "output_dir", "created_at", "completed_at")
    out = {k: parsed[k] for k in keep if k in parsed and parsed[k] not in (None, "", [])}
    links = [row for row in parsed.get("results") or [] if row.get("url") not in (parsed.get("model_url"), parsed.get("preview_url"))]
    if links:
        out["other_files"] = links
    return out


def submit(
    client: t.TripoClient,
    kind: str,
    payload: dict[str, Any],
    *,
    wait: bool,
    output_dir: str = "",
    timeout: float = 1800,
    api: Any = None,
) -> dict[str, Any]:
    """Create a task; with wait, poll it and download its files."""
    task_id = client.create(kind, payload)
    out: dict[str, Any] = {"task_id": task_id, "kind": kind, "status": "queued"}
    if not wait:
        out["next"] = "tripo_status(task_id, poll=true) then tripo_download(task_id)"
        return out
    parsed = client.wait(task_id, timeout=timeout)
    out.update(parsed)
    if parsed["finished"]:
        dest = Path(output_dir.strip()) if output_dir.strip() else download_root(api) / task_id
        out["downloaded"] = t.download_results(parsed, dest)
        out["output_dir"] = str(dest)
        if not output_dir.strip():
            t.prune_downloads(download_root(api))
    return out


def _tool_result(fn: Callable[[], dict[str, Any] | str]) -> str:
    try:
        res = fn()
    except t.TripoError as exc:
        return f"Error: {exc}"
    except (ValueError, FileNotFoundError, OSError) as exc:
        return f"Error: {exc}"
    if isinstance(res, str):
        return res
    return _dumps(_summary(res) if "results" in res else res)


def register_tools(api: Any) -> None:
    def client() -> t.TripoClient:
        return t.TripoClient()

    def run(kind: str, payload: dict[str, Any], wait: bool, output_dir: str) -> dict[str, Any]:
        return submit(client(), kind, payload, wait=wait, output_dir=output_dir, api=api)

    if hasattr(api, "register_secret_test"):
        api.register_secret_test(t.SECRET_KEY, t.test_api_key)

    # ------------------------------------------------------------------ account / tasks (free)

    @api.tool(name="tripo_balance", intent=INTENT)
    def tripo_balance() -> str:
        """Tripo credits left: balance (spendable) and frozen (held by running jobs). 1 credit = $0.01."""
        return _tool_result(lambda: client().balance())

    @api.tool(name="tripo_usage", intent=INTENT)
    def tripo_usage(limit: int = 20, offset: int = 0) -> str:
        """Recent Tripo jobs and what each cost (task_id, type, status, credits_consumed, created_at), newest first."""
        return _tool_result(lambda: {"usage": client().usage(limit=limit, offset=offset)})

    @api.tool(name="tripo_status", intent=INTENT)
    def tripo_status(task_id: str, poll: bool = False, timeout_sec: int = 1800) -> str:
        """Status of a Tripo job (queued, running, success, failed) with its model/picture links. poll=true waits until it ends."""
        def go() -> dict[str, Any]:
            c = client()
            return c.wait(task_id, timeout=timeout_sec) if poll else c.task(task_id)
        return _tool_result(go)

    @api.tool(name="tripo_tasks", intent=INTENT)
    def tripo_tasks(task_ids: str) -> str:
        """Status of up to 100 Tripo jobs at once. task_ids: comma/newline-separated or a JSON array."""
        def go() -> dict[str, Any]:
            raw = task_ids.strip()
            ids = json.loads(raw) if raw.startswith("[") else t.split_names(raw, limit=100)
            res = client().tasks([str(i) for i in ids])
            return {"tasks": {k: _summary(v) for k, v in res["tasks"].items()}, "missed": res["missed"]}
        return _tool_result(go)

    @api.tool(name="tripo_download", intent=INTENT)
    def tripo_download(task_id: str, output_dir: str = "") -> str:
        """Download every file of a finished Tripo job (model, preview, views, textures) to output_dir or the plugin's folder."""
        def go() -> dict[str, Any]:
            parsed = client().task(task_id)
            if not parsed["finished"]:
                return {"error": f"Task is {parsed['status']}, not success", **_summary(parsed)}
            dest = Path(output_dir.strip()) if output_dir.strip() else download_root(api) / task_id
            parsed["downloaded"] = t.download_results(parsed, dest)
            parsed["output_dir"] = str(dest)
            return parsed
        return _tool_result(go)

    @api.tool(name="tripo_upload", intent=INTENT)
    def tripo_upload(path: str) -> str:
        """Upload a local picture (png/jpg/webp ≤20 MB) or model (glb/fbx/obj/stl ≤150 MB) to Tripo; returns a file_token any tool takes. Free."""
        return _tool_result(lambda: {"file_token": client().upload(path), "path": path})

    @api.tool(name="tripo_list_animations", intent=INTENT)
    def tripo_list_animations(query: str = "", rig_version: str = "v1.0-20240301") -> str:
        """Animation presets for tripo_animate: the big humanoid library (rig v1.0) or the creature set (rig v2.5/v3.0). Free."""
        pool = t.ANIMATIONS_V1 if rig_version.startswith("v1") else t.ANIMATIONS_V25
        q = query.strip().lower()
        hits = [a for a in pool if not q or q in a]
        return _dumps({"rig_version": rig_version, "count": len(hits), "animations": hits,
                       "note": "Pass short names (walk, dance_01) or these ids to tripo_animate; ≤5 per job, ~10 credits each."})

    # ------------------------------------------------------------------ 3D generation

    @api.tool(name="tripo_text_to_3d", intent=INTENT)
    def tripo_text_to_3d(
        prompt: str,
        model_version: str = "",
        negative_prompt: str = "",
        texture: str = "pbr",
        texture_quality: str = "",
        geometry_quality: str = "",
        face_limit: int = 0,
        quad: bool = False,
        smart_low_poly: bool = False,
        generate_parts: bool = False,
        auto_size: bool = False,
        model_seed: int = 0,
        texture_seed: int = 0,
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Tripo text→3D model (GLB; FBX when quad). texture: pbr|texture|none. model_version: v3.1 (best), v3.0, v2.5, P1/P2 (clean low-poly). ~20 credits textured."""
        def go() -> dict[str, Any] | str:
            if not prompt.strip():
                return "Error: prompt is required"
            opts = t.model_options(model_version=model_version, texture=texture, texture_quality=texture_quality,
                                   geometry_quality=geometry_quality, face_limit=face_limit, quad=quad,
                                   smart_low_poly=smart_low_poly, generate_parts=generate_parts, auto_size=auto_size,
                                   model_seed=model_seed, texture_seed=texture_seed)
            blocked = t.credit_gate(confirm_spend, t.estimate_model_credits("text_to_model", opts), "text to 3D")
            if blocked:
                return blocked
            payload = {**opts, "prompt": prompt.strip()[:1024]}
            if negative_prompt.strip():
                payload["negative_prompt"] = negative_prompt.strip()[:255]
            return run("text_to_model", payload, wait, output_dir)
        return _tool_result(go)

    @api.tool(name="tripo_image_to_3d", intent=INTENT)
    def tripo_image_to_3d(
        image: str,
        model_version: str = "",
        texture: str = "pbr",
        texture_quality: str = "",
        geometry_quality: str = "",
        face_limit: int = 0,
        quad: bool = False,
        smart_low_poly: bool = False,
        generate_parts: bool = False,
        auto_size: bool = False,
        orientation: str = "",
        texture_alignment: str = "",
        image_autofix: bool = False,
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Tripo image→3D model from one picture: local path, https link, data: URI, or a tripo_text_to_image task_id. ~30 credits textured."""
        def go() -> dict[str, Any] | str:
            opts = t.model_options(model_version=model_version, texture=texture, texture_quality=texture_quality,
                                   geometry_quality=geometry_quality, face_limit=face_limit, quad=quad,
                                   smart_low_poly=smart_low_poly, generate_parts=generate_parts, auto_size=auto_size)
            blocked = t.credit_gate(confirm_spend, t.estimate_model_credits("image_to_model", opts), "image to 3D")
            if blocked:
                return blocked
            c = client()
            payload = {**opts, "input": c.resolve(image, "image")}
            if orientation.strip():
                payload["orientation"] = orientation.strip()
            if texture_alignment.strip():
                payload["texture_alignment"] = texture_alignment.strip()
            if image_autofix:
                payload["enable_image_autofix"] = True
            return submit(c, "image_to_model", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_multiview_to_3d", intent=INTENT)
    def tripo_multiview_to_3d(
        front: str = "",
        left: str = "",
        back: str = "",
        right: str = "",
        images: str = "",
        multiview_task_id: str = "",
        model_version: str = "",
        texture: str = "pbr",
        texture_quality: str = "",
        face_limit: int = 0,
        quad: bool = False,
        smart_low_poly: bool = False,
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Tripo multi-view→3D: front (required) plus left/back/right pictures (or images = a JSON list in that order), or a tripo_image_to_multiview / tripo_edit_multiview task_id. ~30 credits."""
        def go() -> dict[str, Any] | str:
            opts = t.model_options(model_version=model_version, texture=texture, texture_quality=texture_quality,
                                   face_limit=face_limit, quad=quad, smart_low_poly=smart_low_poly)
            blocked = t.credit_gate(confirm_spend, t.estimate_model_credits("multiview_to_model", opts), "multi-view to 3D")
            if blocked:
                return blocked
            c = client()
            if multiview_task_id.strip():
                inputs: list[dict[str, str]] = [{"task_id": multiview_task_id.strip()}]
            else:
                views = {"front": front, "left": left, "back": back, "right": right}
                listed = json.loads(images) if images.strip().startswith("[") else t.split_names(images, limit=4)
                for view, src in zip(t.VIEWS, listed, strict=False):
                    if str(src or "").strip() and not views[view].strip():
                        views[view] = str(src)
                if not views["front"].strip():
                    return "Error: front view is required (or pass multiview_task_id)"
                inputs = [{view: c.resolve(src, f"{view} view")} for view, src in views.items() if src.strip()]
                if len(inputs) < 2:
                    return "Error: need at least 2 views (front plus one of left/back/right)"
            return submit(c, "multiview_to_model", {**opts, "inputs": inputs}, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_image_to_splat", intent=INTENT)
    def tripo_image_to_splat(image: str, confirm_spend: bool = False, wait: bool = True, output_dir: str = "") -> str:
        """Tripo image→Gaussian splat (a point-cloud style 3D capture, not a mesh) from one picture. Cost is an estimate."""
        def go() -> dict[str, Any] | str:
            blocked = t.credit_gate(confirm_spend, t.SPLAT_CREDITS, "image to splat")
            if blocked:
                return blocked
            c = client()
            return submit(c, "image_to_splat", {"input": c.resolve(image, "image")}, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    # ------------------------------------------------------------------ images

    @api.tool(name="tripo_text_to_image", intent=INTENT)
    def tripo_text_to_image(
        prompt: str,
        model: str = "",
        size: str = "",
        aspect_ratio: str = "",
        quality: str = "",
        background: str = "",
        output_format: str = "",
        template: str = "",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Tripo text→image (concept art or the picture for tripo_image_to_3d). model: seedream_v4/v5, banana, banana2, banana_pro, chat_image_2, chat_image_2.5_flare/sunburst. ~5-20 credits."""
        def go() -> dict[str, Any] | str:
            if not prompt.strip():
                return "Error: prompt is required"
            opts = t.image_options(model=model, size=size, aspect_ratio=aspect_ratio, quality=quality,
                                   background=background, output_format=output_format, template=template)
            credits = t.estimate_image_credits(opts["model"], size, quality)
            blocked = t.credit_gate(confirm_spend, credits, f"text to image ({opts['model']})")
            if blocked:
                return blocked
            return run("text_to_image", {**opts, "prompt": prompt.strip()[:1800]}, wait, output_dir)
        return _tool_result(go)

    @api.tool(name="tripo_image_to_image", intent=INTENT)
    def tripo_image_to_image(
        image: str,
        prompt: str = "",
        reference_images: str = "",
        model: str = "",
        template: str = "",
        size: str = "",
        aspect_ratio: str = "",
        quality: str = "",
        output_format: str = "",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Tripo image edit: change a picture by prompt, or a template (t_pose, character_completion, 3d_enhance, variants, figure). reference_images: more pictures (image[2]…)."""
        def go() -> dict[str, Any] | str:
            if not prompt.strip() and not template.strip():
                return "Error: prompt or template is required"
            opts = t.image_options(model=model or "seedream_v5", size=size, aspect_ratio=aspect_ratio, quality=quality,
                                   output_format=output_format, template=template)
            if opts["model"] == "seedream_v4":
                opts["model"] = "seedream_v5"  # v4 is text-to-image only
            blocked = t.credit_gate(confirm_spend, t.estimate_image_credits(opts["model"], size, quality), f"image edit ({opts['model']})")
            if blocked:
                return blocked
            c = client()
            payload = {**opts, "input": c.resolve(image, "image")}
            refs = t.split_names(reference_images, limit=15)
            if refs:
                payload["inputs"] = [payload["input"], *[c.resolve(r, "reference image") for r in refs]]
            if prompt.strip():
                payload["prompt"] = prompt.strip()[:1800]
            return submit(c, "image_to_image", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_image_to_multiview", intent=INTENT)
    def tripo_image_to_multiview(image: str, confirm_spend: bool = False, wait: bool = True, output_dir: str = "") -> str:
        """Tripo: front, left, back and right views from one picture (feed the task_id to tripo_multiview_to_3d). ~10 credits."""
        def go() -> dict[str, Any] | str:
            blocked = t.credit_gate(confirm_spend, t.MULTIVIEW_CREDITS, "image to multiview")
            if blocked:
                return blocked
            c = client()
            return submit(c, "image_to_multiview", {"input": c.resolve(image, "image")}, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_edit_multiview", intent=INTENT)
    def tripo_edit_multiview(
        multiview_task_id: str,
        front: str = "",
        left: str = "",
        back: str = "",
        right: str = "",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Tripo: edit views of a tripo_image_to_multiview job by prompt, per view (front/left/back/right). ~5 credits per edited view."""
        def go() -> dict[str, Any] | str:
            edits = [{"view": v, "prompt": p.strip()[:1024]} for v, p in (("front", front), ("left", left), ("back", back), ("right", right)) if p.strip()]
            if not edits:
                return "Error: give a prompt for at least one view"
            blocked = t.credit_gate(confirm_spend, t.EDIT_VIEW_CREDITS * len(edits), "edit multiview")
            if blocked:
                return blocked
            c = client()
            payload = {"input": c.resolve(multiview_task_id, "multiview_task_id"), "prompts": edits}
            return submit(c, "edit_multiview", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    # ------------------------------------------------------------------ model processing

    @api.tool(name="tripo_texture", intent=INTENT)
    def tripo_texture(
        source: str,
        text_prompt: str = "",
        style_image: str = "",
        reference_image: str = "",
        texture_quality: str = "standard",
        pbr: bool = True,
        texture_alignment: str = "",
        texture_version: str = "",
        part_names: str = "",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """(Re)texture a model: source = Tripo task_id, local glb/fbx/obj/stl, https link or file token. Prompt and/or a reference picture. ~10-30 credits."""
        def go() -> dict[str, Any] | str:
            quality = texture_quality.strip().lower() or "standard"
            if quality not in t.TEXTURE_QUALITIES:
                return f"Error: texture_quality must be one of {', '.join(t.TEXTURE_QUALITIES)}"
            blocked = t.credit_gate(confirm_spend, t.TEXTURE_CREDITS[quality], "texture")
            if blocked:
                return blocked
            c = client()
            payload: dict[str, Any] = {"input": c.resolve(source, "source"), "pbr": bool(pbr)}
            if quality != "standard":
                payload["texture_quality"] = quality
            version = texture_version.strip() or (t.FAST_TEXTURE_VERSION if quality == "fast" else "")
            if version:
                payload["model"] = version
            prompt_obj: dict[str, Any] = {}
            if reference_image.strip() or (style_image.strip() and not text_prompt.strip()):
                # A style picture with no prompt: paint from the picture itself.
                prompt_obj["image"] = c.resolve(reference_image or style_image, "reference_image")
            elif text_prompt.strip():
                prompt_obj["text"] = text_prompt.strip()[:1024]
                if style_image.strip():
                    prompt_obj["style_image"] = c.resolve(style_image, "style_image")
            if prompt_obj:
                payload["texture_prompt"] = prompt_obj
            if texture_alignment.strip():
                payload["texture_alignment"] = texture_alignment.strip()
            parts = t.split_names(part_names, limit=200)
            if parts:
                payload["part_names"] = parts
            return submit(c, "texture", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_convert", intent=INTENT)
    def tripo_convert(
        source: str,
        format: str = "FBX",
        fbx_preset: str = "",
        face_limit: int = 0,
        quad: bool = False,
        pivot_to_center_bottom: bool = False,
        scale_factor: float = 1.0,
        texture_size: int = 0,
        texture_format: str = "",
        flatten_bottom: bool = False,
        animate_in_place: bool = False,
        export_orientation: str = "",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Convert a model to FBX, GLTF, OBJ, USDZ, STL or 3MF (fbx_preset blender|3dsmax|mixamo|bake_scale; pivot, scale, polycount). 5 credits, 10 with options."""
        def go() -> dict[str, Any] | str:
            fmt = format.strip().upper() or "FBX"
            fmt = "GLTF" if fmt in ("GLB", "GLTF") else fmt
            if fmt not in t.CONVERT_FORMATS:
                return f"Error: format must be one of {', '.join(t.CONVERT_FORMATS)}"
            opts: dict[str, Any] = {"format": fmt}
            if fbx_preset.strip():
                opts["fbx_preset"] = fbx_preset.strip()
            if int(face_limit or 0) > 0:
                opts["face_limit"] = int(face_limit)
            for name, on in (("quad", quad), ("pivot_to_center_bottom", pivot_to_center_bottom),
                             ("flatten_bottom", flatten_bottom), ("animate_in_place", animate_in_place)):
                if on:
                    opts[name] = True
            if float(scale_factor or 1) != 1.0:
                opts["scale_factor"] = float(scale_factor)
            if int(texture_size or 0) > 0:
                opts["texture_size"] = int(texture_size)
            if texture_format.strip():
                opts["texture_format"] = texture_format.strip().upper()
            if export_orientation.strip():
                opts["export_orientation"] = export_orientation.strip()
            credits = t.CONVERT_CREDITS[1 if t.convert_is_advanced(opts) else 0]
            blocked = t.credit_gate(confirm_spend, credits, f"convert to {fmt}")
            if blocked:
                return blocked
            c = client()
            return submit(c, "convert", {**opts, "input": c.resolve(source, "source")}, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_stylize", intent=INTENT)
    def tripo_stylize(source: str, style: str = "lego", block_size: int = 0, confirm_spend: bool = False, wait: bool = True, output_dir: str = "") -> str:
        """Restyle a Tripo model as lego, voxel, voronoi, minecraft, keyring, fridge_magnet or keycap (source = its task_id). Cost is an estimate."""
        def go() -> dict[str, Any] | str:
            st = style.strip().lower()
            if st not in t.STYLES:
                return f"Error: style must be one of {', '.join(t.STYLES)}"
            blocked = t.credit_gate(confirm_spend, t.STYLIZE_CREDITS, f"stylize ({st})")
            if blocked:
                return blocked
            c = client()
            src = c.resolve(source, "source")
            payload: dict[str, Any] = {"input": src, "style": st}
            if not (t.is_url(src) or src.startswith("file_")):
                payload["original_model_task_id"] = src  # the V2 field name this endpoint documents
            if int(block_size or 0) > 0:
                payload["block_size"] = int(block_size)
            return submit(c, "stylize", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_retopology", intent=INTENT)
    def tripo_retopology(
        source: str,
        version: str = "v3.0",
        face_limit: int = 0,
        quad: bool = False,
        smart_uv: bool = False,
        bake: bool = True,
        part_names: str = "",
        topology: str = "",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Retopology / low-poly: clean game-ready topology at face_limit (500-20000 tri, 500-10000 quad; topology quad|triangle), textures baked on; v3.0 can add smart UVs. 10-40 credits."""
        quad = quad or topology.strip().lower() == "quad"

        def go() -> dict[str, Any] | str:
            v = version.strip() or "v3.0"
            if v not in t.RETOPO_VERSIONS:
                return f"Error: version must be one of {', '.join(t.RETOPO_VERSIONS)}"
            if v == "v1.0" and int(face_limit or 0) <= 0:
                return "Error: retopology v1.0 needs face_limit"
            if smart_uv and v != "v3.0":
                return "Error: smart_uv needs version v3.0"
            credits = t.RETOPO_CREDITS[v][1 if quad else 0]
            blocked = t.credit_gate(confirm_spend, credits, f"retopology {v}")
            if blocked:
                return blocked
            c = client()
            payload: dict[str, Any] = {"input": c.resolve(source, "source"), "model": v}
            if int(face_limit or 0) > 0:
                payload["face_limit"] = int(face_limit)
            if quad:
                payload["quad"] = True
            if smart_uv:
                payload["smart_uv"] = True
            if v != "v1.0":
                payload["bake"] = bool(bake)
                parts = t.split_names(part_names, limit=200)
                if parts:
                    payload["part_names"] = parts
            return submit(c, "decimate", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_smart_uv", intent=INTENT)
    def tripo_smart_uv(source: str, bake: bool = True, confirm_spend: bool = False, wait: bool = True, output_dir: str = "") -> str:
        """Smart UV unwrap (≤80k triangles) with textures re-baked onto the new UVs; also returns a UV atlas picture. ~20 credits."""
        def go() -> dict[str, Any] | str:
            blocked = t.credit_gate(confirm_spend, t.SMART_UV_CREDITS, "smart UV")
            if blocked:
                return blocked
            c = client()
            return submit(c, "smart_uv", {"input": c.resolve(source, "source"), "bake": bool(bake)}, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_segment", intent=INTENT)
    def tripo_segment(
        source: str,
        version: str = "v1.0-20250506",
        granularity: str = "",
        split_by_connectivity: bool = True,
        ref_image: str = "",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Split a model into named parts (v2.0 adds semantic labels, granularity simple|balanced|detailed). Feed the task_id to tripo_complete_parts. ~40 credits."""
        def go() -> dict[str, Any] | str:
            v = version.strip() or "v1.0-20250506"
            if v not in t.SEGMENT_VERSIONS:
                return f"Error: version must be one of {', '.join(t.SEGMENT_VERSIONS)}"
            blocked = t.credit_gate(confirm_spend, t.SEGMENT_CREDITS, "segmentation")
            if blocked:
                return blocked
            c = client()
            payload: dict[str, Any] = {"input": c.resolve(source, "source"), "model": v}
            if v.startswith("v2"):
                if granularity.strip():
                    payload["segmentation_granularity"] = granularity.strip()
                if not split_by_connectivity:
                    payload["split_by_connectivity"] = False
                if ref_image.strip():
                    payload["ref_image"] = c.resolve(ref_image, "ref_image")
            return submit(c, "segment", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    @api.tool(name="tripo_complete_parts", intent=INTENT)
    def tripo_complete_parts(
        segment_task_id: str,
        part_names: str = "",
        mode: str = "ai_completion",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Fill the hidden/open sides of segmented parts (tripo_segment task_id): ai_completion (~50) or quick_cap hole fill (~30 credits)."""
        def go() -> dict[str, Any] | str:
            m = mode.strip() or "ai_completion"
            if m not in t.COMPLETE_CREDITS:
                return "Error: mode must be ai_completion or quick_cap"
            blocked = t.credit_gate(confirm_spend, t.COMPLETE_CREDITS[m], f"part completion ({m})")
            if blocked:
                return blocked
            c = client()
            payload: dict[str, Any] = {"input": c.resolve(segment_task_id, "segment_task_id")}
            if m != "ai_completion":
                payload["completion_mode"] = m
            parts = t.split_names(part_names, limit=200)
            if parts:
                payload["part_names"] = parts
            return submit(c, "complete", payload, wait=wait, output_dir=output_dir, api=api)
        return _tool_result(go)

    # ------------------------------------------------------------------ rigging / animation

    @api.tool(name="tripo_rig_check", intent=INTENT)
    def tripo_rig_check(source: str) -> str:
        """Free: can this model be rigged, and which rig type fits (biped, quadruped, hexapod, octopod, avian, serpentine, aquatic)."""
        def go() -> dict[str, Any]:
            c = client()
            return submit(c, "rig_check", {"input": c.resolve(source, "source")}, wait=True, output_dir="", api=api)
        return _tool_result(go)

    @api.tool(name="tripo_rig", intent=INTENT)
    def tripo_rig(
        source: str,
        rig_type: str = "biped",
        spec: str = "tripo",
        out_format: str = "fbx",
        rig_version: str = "auto",
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Auto-rig a model (skeleton + skin). rig_type auto (free rig check picks it)|biped…aquatic|others; spec tripo|mixamo|unreal|unity|actorcore|vrm (unreal = UE mannequin bones). ~25 credits."""
        def go() -> dict[str, Any] | str:
            kind = rig_type.strip().lower() or "biped"
            if kind not in (*t.RIG_TYPES, "auto"):
                return f"Error: rig_type must be auto or one of {', '.join(t.RIG_TYPES)}"
            sp = spec.strip().lower() or "tripo"
            if sp not in t.RIG_SPECS:
                return f"Error: spec must be one of {', '.join(t.RIG_SPECS)}"
            t.rig_version_for("biped" if kind == "auto" else kind, sp, rig_version)  # a bad version/spec pair fails before any spend
            blocked = t.credit_gate(confirm_spend, t.RIG_CREDITS, "auto rig")
            if blocked:
                return blocked
            c = client()
            src = c.resolve(source, "source")
            if kind == "auto":  # free
                check = c.wait(c.create("rig_check", {"input": src}))
                if check.get("riggable") is False:
                    return "Error: Tripo says this model can't be rigged (one whole character or creature in a clear pose rigs best)."
                kind = str(check.get("rig_type") or "biped")
                kind = kind if kind in t.RIG_TYPES else "biped"
            version = t.rig_version_for(kind, sp, rig_version)
            payload: dict[str, Any] = {"input": src, "model": version, "rig_type": kind,
                                       "out_format": "glb" if out_format.strip().lower() == "glb" else "fbx"}
            if kind == "biped":
                payload["spec"] = sp
            res = submit(c, "rig", payload, wait=wait, output_dir=output_dir, api=api)
            res["rig_version"] = version
            res["rig_type"] = kind
            return res
        return _tool_result(go)

    @api.tool(name="tripo_animate", intent=INTENT)
    def tripo_animate(
        rig_task_id: str,
        animations: str = "idle",
        rig_version: str = "",
        rig_type: str = "",
        out_format: str = "fbx",
        animate_in_place: bool = False,
        export_with_geometry: bool = True,
        confirm_spend: bool = False,
        wait: bool = True,
        output_dir: str = "",
    ) -> str:
        """Animate a tripo_rig result: animations = up to 5 names (walk, run, idle, jump, dance_01…) or preset ids from tripo_list_animations. ~10 credits each."""
        def go() -> dict[str, Any] | str:
            names = t.split_names(animations, limit=5)
            if not names:
                return "Error: name at least one animation"
            c = client()
            version, kind = t.rig_info(c, rig_task_id.strip(), rig_version.strip(), rig_type.strip())  # free lookup
            ids = [t.animation_id(n, version, kind) for n in names]
            blocked = t.credit_gate(confirm_spend, t.RETARGET_CREDITS * len(ids), f"{len(ids)} animation(s)")
            if blocked:
                return blocked
            payload: dict[str, Any] = {"input": rig_task_id.strip(), "original_model_task_id": rig_task_id.strip(),
                                       "out_format": "glb" if out_format.strip().lower() == "glb" else "fbx"}
            if len(ids) == 1:
                payload["animation"] = ids[0]
            else:
                payload["animations"] = ids
            if animate_in_place:
                payload["animate_in_place"] = True
            if not export_with_geometry:
                payload["export_with_geometry"] = False
            res = submit(c, "retarget", payload, wait=wait, output_dir=output_dir, api=api)
            res["animations"] = ids
            return res
        return _tool_result(go)

    # ------------------------------------------------------------------ landing

    def _local(url_or_path: str) -> str:
        src = url_or_path.strip()
        if t.is_url(src):
            data = t._fetch(src)
            ext = t.url_ext(src) or t.sniff_ext(data[:64]) or ".glb"
            dest = download_root(api) / "imports" / (Path(src.split("?")[0]).stem[:60] + ext)
            dest.parent.mkdir(parents=True, exist_ok=True)
            dest.write_bytes(data)
            return str(dest)
        path = Path(src).expanduser()
        if not path.is_file():
            raise t.TripoError(f"file not found: {src}")
        return str(path.resolve())

    @api.tool(name="tripo_import_to_blender", intent=INTENT)
    def tripo_import_to_blender(url_or_path: str) -> str:
        """Import a Tripo GLB/GLTF/FBX/OBJ (file or link) into the open Blender (Blender MCP add-on on port 9876)."""
        def go() -> dict[str, Any]:
            from .blender_import import execute_code, import_code

            local = _local(url_or_path)
            return {"ok": True, "path": local, "blender": execute_code(import_code(local))}
        try:
            return _tool_result(go)
        except (ConnectionError, RuntimeError, TimeoutError) as exc:
            return f"Error importing to Blender: {exc}"

    @api.tool(name="tripo_import_to_uefn", intent=INTENT)
    def tripo_import_to_uefn(url_or_path: str, destination_path: str = "", replace_existing: bool = True) -> str:
        """Import a Tripo model (file or link; FBX for rigged/animated) into the open UEFN project's Content Browser (default folder Tripo)."""
        def go() -> dict[str, Any]:
            local = _local(url_or_path)
            dest = destination_path.strip() or "Tripo"
            result = api.listener("import_asset", {"source_file": local, "destination_path": dest, "replace_existing": bool(replace_existing)})
            return {"ok": True, "path": local, "destination_path": dest, "uefn": result}
        try:
            return _tool_result(go)
        except Exception as exc:  # noqa: BLE001 — the listener being offline is this tool's answer
            return f"Error importing to UEFN: {exc}. Is UEFN open with the Ducky listener online?"

    api.log("tripo tools registered")
