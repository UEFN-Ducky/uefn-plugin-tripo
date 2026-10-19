"""Tripo workflow nodes (contributes.automations.nodes in plugin.json).

Each node is a value node: it runs when something needs what it makes. Paid nodes keep
the spend lock: they only run with "Spend credits" on in their details. Files land in
the run's folder (a chat pipeline) or the plugin's downloads folder, and travel as file
refs that remember their Tripo task, so the next Tripo node (rig, animate, retopology,
convert…) chains on the task instead of uploading the file again.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Callable

from . import tripo as t
from .tools import download_root

PROVIDER = "Tripo"
_STATE: dict[str, Any] = {"api": None, "client": None}

Ctx = dict[str, Any]


# --------------------------------------------------------------------------- helpers


def _client() -> t.TripoClient:
    factory = _STATE.get("client")
    return factory() if callable(factory) else t.TripoClient()


def _cfg(ctx: Ctx) -> dict[str, Any]:
    return ctx.get("config") if isinstance(ctx.get("config"), dict) else {}


def _inputs(ctx: Ctx) -> dict[str, Any]:
    return ctx.get("inputs") if isinstance(ctx.get("inputs"), dict) else {}


def _text(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, (dict, list)):
        return json.dumps(value)
    return str(value).strip()


def _number(*values: Any) -> float:
    for raw in values:
        try:
            if raw not in (None, ""):
                return float(raw)
        except (TypeError, ValueError):
            continue
    return 0.0


def _first(value: Any) -> Any:
    return (value[0] if value else None) if isinstance(value, list) else value


def _path_of(value: Any) -> str:
    value = _first(value)
    if isinstance(value, dict):
        return str(value.get("path") or value.get("remote") or value.get("url") or "")
    return str(value or "").strip()


def _tripo_ref(value: Any, stage: str = "") -> dict[str, Any] | None:
    """The wired file ref when a Tripo node made it (and, if asked, at that stage)."""
    ref = _first(value)
    if isinstance(ref, dict) and ref.get("plugin_id") == t.PLUGIN_ID and ref.get("task_id"):
        if not stage or ref.get("stage") == stage:
            return ref
    return None


def _source(client: t.TripoClient, value: Any, what: str) -> str:
    """A Tripo task id when a Tripo node made the file, else the file uploaded / its link."""
    ref = _tripo_ref(value)
    if ref is not None:
        return str(ref["task_id"])
    path = _path_of(value)
    if not path:
        raise ValueError(f"Nothing in {what}: wire one in.")
    if not t.is_url(path) and not Path(path).is_file():
        raise ValueError(f"{what} {Path(path).name} isn't on this PC any more.")
    return client.resolve(path, what)


def _spend(cfg: dict[str, Any], credits: int, label: str) -> dict[str, Any] | None:
    if credits > 0 and cfg.get("spend") is not True:
        return {"ok": False, "error": f"Tripo {label} costs about {credits} credits a run (1 credit = $0.01). "
                                      "Turn on Spend credits in this node's details to let it run."}
    return None


def _folder(ctx: Ctx) -> Path:
    art = str(ctx.get("artifact_dir") or "").strip()
    return Path(art) / "tripo" if art else download_root(_STATE.get("api"))


def _kind(path: str) -> str:
    ext = Path(path).suffix.lower()
    if ext in t.MAIN_IMAGE_EXTS or ext in (".bmp", ".tif", ".tiff"):
        return "image"
    if ext in t.MAIN_MESH_EXTS or ext == ".ply":
        return "mesh"
    return "file"


def _link(path: str) -> str:
    api = _STATE.get("api")
    try:
        return str(api.media_url(path)) if api is not None and hasattr(api, "media_url") else ""
    except Exception:  # noqa: BLE001 — a link is only for the editor's preview
        return ""


def file_ref(path: str, parsed: dict[str, Any], *, kind: str = "", stage: str = "", **extra: Any) -> dict[str, Any]:
    ref: dict[str, Any] = {"kind": kind or _kind(path), "path": path, "name": Path(path).name,
                           "provider": PROVIDER, "plugin_id": t.PLUGIN_ID, "task_id": str(parsed.get("task_id") or "")}
    if stage:
        ref["stage"] = stage
    remote = parsed.get("model_url") if ref["kind"] == "mesh" else parsed.get("image_url") or parsed.get("preview_url")
    if isinstance(remote, str) and remote.startswith("https://"):
        ref["remote"] = remote
    ref.update({k: v for k, v in extra.items() if v not in (None, "")})
    url = _link(path)
    if url:
        ref["url"] = url
    return ref


def _run(ctx: Ctx, client: t.TripoClient, kind: str, payload: dict[str, Any]) -> dict[str, Any]:
    parsed = client.run(kind, payload, _folder(ctx))
    if not str(ctx.get("artifact_dir") or "").strip():
        t.prune_downloads(download_root(_STATE.get("api")))
    return parsed


def _files(parsed: dict[str, Any]) -> list[dict[str, Any]]:
    return [file_ref(p, parsed) for p in parsed.get("downloaded") or []]


def _mesh_out(parsed: dict[str, Any], stage: str, **extra: Any) -> dict[str, Any]:
    paths = list(parsed.get("downloaded") or [])
    main = t.main_file([p for p in paths if _kind(p) == "mesh"], t.MAIN_MESH_EXTS)
    if not main:
        return {"ok": False, "error": "Tripo finished but sent no model back."}
    preview = t.main_file([p for p in paths if _kind(p) == "image"], t.MAIN_IMAGE_EXTS)
    out: dict[str, Any] = {
        "ok": True,
        "mesh": file_ref(main, parsed, kind="mesh", stage=stage, **extra),
        "files": _files(parsed),
        "task_id": str(parsed.get("task_id") or ""),
        "credits": parsed.get("credits_consumed"),
    }
    if preview:
        out["preview"] = file_ref(preview, parsed, kind="image")
    return out


def _image_out(parsed: dict[str, Any], stage: str = "image") -> dict[str, Any]:
    paths = list(parsed.get("downloaded") or [])
    main = t.main_file([p for p in paths if _kind(p) == "image"], t.MAIN_IMAGE_EXTS)
    if not main:
        return {"ok": False, "error": "Tripo finished but sent no picture back."}
    return {"ok": True, "image": file_ref(main, parsed, kind="image", stage=stage), "files": _files(parsed),
            "task_id": str(parsed.get("task_id") or ""), "credits": parsed.get("credits_consumed")}


def _views_out(parsed: dict[str, Any]) -> dict[str, Any]:
    by_view: dict[str, dict[str, Any]] = {}
    for path in parsed.get("downloaded") or []:
        stem = Path(path).stem.lower()
        for view in t.VIEWS:
            if stem.startswith(view) and view not in by_view and _kind(path) == "image":
                by_view[view] = file_ref(path, parsed, kind="image", stage="multiview", view=view)
    if not by_view:
        return {"ok": False, "error": "Tripo finished but sent no views back."}
    views = [by_view[v] for v in t.VIEWS if v in by_view]
    return {"ok": True, "views": views, **by_view, "files": _files(parsed), "task_id": str(parsed.get("task_id") or "")}


def _guard(fn: Callable[[Ctx], dict[str, Any]]) -> Callable[[Ctx], dict[str, Any]]:
    def handler(ctx: Ctx) -> dict[str, Any]:
        try:
            return fn(ctx if isinstance(ctx, dict) else {})
        except t.TripoError as exc:
            return {"ok": False, "error": str(exc)}
        except (ValueError, OSError) as exc:
            return {"ok": False, "error": str(exc)}
    handler.__name__ = fn.__name__
    handler.__doc__ = fn.__doc__
    return handler


def _model_opts(cfg: dict[str, Any], inp: dict[str, Any]) -> dict[str, Any]:
    return t.model_options(
        model_version=str(cfg.get("model") or ""),
        texture=str(cfg.get("texture") or "pbr"),
        texture_quality=str(cfg.get("texture_quality") or ""),
        geometry_quality="detailed" if cfg.get("hd_geometry") is True else "",
        face_limit=int(_number(inp.get("polycount"), cfg.get("face_limit"))),
        quad=cfg.get("quad") is True,
        smart_low_poly=cfg.get("smart_low_poly") is True,
        generate_parts=cfg.get("generate_parts") is True,
        auto_size=cfg.get("auto_size") is True,
    )


# --------------------------------------------------------------------------- 3D generation


@_guard
def text_to_3d(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    prompt = _text(inp.get("prompt"))
    if not prompt:
        return {"ok": False, "error": "Nothing in Prompt: wire text in or type it in the details."}
    opts = _model_opts(cfg, inp)
    blocked = _spend(cfg, t.estimate_model_credits("text_to_model", opts), "Text to 3D")
    if blocked:
        return blocked
    payload = {**opts, "prompt": prompt[:1024]}
    negative = _text(inp.get("negative"))
    if negative:
        payload["negative_prompt"] = negative[:255]
    client = _client()
    return _mesh_out(_run(ctx, client, "text_to_model", payload), "model", model_version=opts["model"])


@_guard
def image_to_3d(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    opts = _model_opts(cfg, inp)
    blocked = _spend(cfg, t.estimate_model_credits("image_to_model", opts), "Image to 3D")
    if blocked:
        return blocked
    client = _client()
    payload = {**opts, "input": _source(client, inp.get("image"), "Image")}
    if cfg.get("orientation") == "align_image":
        payload["orientation"] = "align_image"
    if cfg.get("texture_alignment") == "geometry":
        payload["texture_alignment"] = "geometry"
    if cfg.get("image_autofix") is True:
        payload["enable_image_autofix"] = True
    return _mesh_out(_run(ctx, client, "image_to_model", payload), "model", model_version=opts["model"])


@_guard
def multiview_to_3d(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    opts = _model_opts(cfg, inp)
    blocked = _spend(cfg, t.estimate_model_credits("multiview_to_model", opts), "Multi-view to 3D")
    if blocked:
        return blocked
    client = _client()
    views = inp.get("views") if isinstance(inp.get("views"), list) else [inp.get("views")] if inp.get("views") else []
    made = next((r for r in [*views, *(inp.get(v) for v in t.VIEWS)] if _tripo_ref(r, "multiview")), None)
    if made is not None:
        inputs: list[dict[str, str]] = [{"task_id": str(_tripo_ref(made)["task_id"])}]
    else:
        picked = {v: inp.get(v) for v in t.VIEWS if _path_of(inp.get(v))}
        for view, ref in zip(t.VIEWS, views, strict=False):  # Views in front, left, back, right order
            if _path_of(ref):
                picked.setdefault(view, ref)
        if "front" not in picked:
            return {"ok": False, "error": "Multi-view needs a front picture (wire Front, or Views in front, left, back, right order)."}
        if len(picked) < 2:
            return {"ok": False, "error": "Multi-view needs at least 2 pictures of the same thing (front plus a side or back)."}
        inputs = [{view: _source(client, picked[view], f"{view.title()} view")} for view in t.VIEWS if view in picked]
    return _mesh_out(_run(ctx, client, "multiview_to_model", {**opts, "inputs": inputs}), "model", model_version=opts["model"])


@_guard
def image_to_splat(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    blocked = _spend(cfg, t.SPLAT_CREDITS, "Image to Splat")
    if blocked:
        return blocked
    client = _client()
    parsed = _run(ctx, client, "image_to_splat", {"input": _source(client, inp.get("image"), "Image")})
    paths = list(parsed.get("downloaded") or [])
    if not paths:
        return {"ok": False, "error": "Tripo finished but sent no splat back."}
    main = next((p for p in paths if Path(p).suffix.lower() in (".ply", ".spz", ".splat")), paths[0])
    return {"ok": True, "splat": file_ref(main, parsed, stage="splat"), "files": _files(parsed), "task_id": parsed.get("task_id")}


# --------------------------------------------------------------------------- images


def _image_opts(cfg: dict[str, Any], default_model: str = "") -> dict[str, Any]:
    return t.image_options(model=str(cfg.get("model") or default_model), size=str(cfg.get("size") or ""),
                           aspect_ratio=str(cfg.get("aspect_ratio") or ""), quality=str(cfg.get("quality") or ""),
                           background=str(cfg.get("background") or ""), template=str(cfg.get("template") or ""))


@_guard
def text_to_image(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    prompt = _text(inp.get("prompt"))
    if not prompt:
        return {"ok": False, "error": "Nothing in Prompt: wire text in or type it in the details."}
    opts = _image_opts(cfg)
    blocked = _spend(cfg, t.estimate_image_credits(opts["model"], opts.get("size", ""), opts.get("quality", "")), "Text to Image")
    if blocked:
        return blocked
    return _image_out(_run(ctx, _client(), "text_to_image", {**opts, "prompt": prompt[:1800]}))


@_guard
def edit_image(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    prompt = _text(inp.get("prompt"))
    if not prompt and not cfg.get("template"):
        return {"ok": False, "error": "Nothing in Prompt: say what to change, or pick a template in the details."}
    opts = _image_opts(cfg, "seedream_v5")
    if opts["model"] == "seedream_v4":
        opts["model"] = "seedream_v5"
    blocked = _spend(cfg, t.estimate_image_credits(opts["model"], opts.get("size", ""), opts.get("quality", "")), "Edit Image")
    if blocked:
        return blocked
    client = _client()
    payload: dict[str, Any] = {**opts, "input": _source(client, inp.get("image"), "Image")}
    refs = inp.get("refs") if isinstance(inp.get("refs"), list) else [inp.get("refs")] if inp.get("refs") else []
    if refs:
        payload["inputs"] = [payload["input"], *[_source(client, r, "Reference") for r in refs[:15]]]
    if prompt:
        payload["prompt"] = prompt[:1800]
    return _image_out(_run(ctx, client, "image_to_image", payload))


@_guard
def image_to_multiview(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    blocked = _spend(cfg, t.MULTIVIEW_CREDITS, "Image to Multi-view")
    if blocked:
        return blocked
    client = _client()
    return _views_out(_run(ctx, client, "image_to_multiview", {"input": _source(client, inp.get("image"), "Image")}))


@_guard
def edit_multiview(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    views = inp.get("views") if isinstance(inp.get("views"), list) else [inp.get("views")]
    made = next((r for r in views if _tripo_ref(r, "multiview")), None)
    if made is None:
        return {"ok": False, "error": "Edit Multi-view needs the views straight from a Tripo Image to Multi-view node."}
    edits = [{"view": v, "prompt": _text(inp.get(f"{v}_edit"))[:1024]} for v in t.VIEWS if _text(inp.get(f"{v}_edit"))]
    if not edits:
        return {"ok": False, "error": "Say what to change on at least one view (Front change, Left change…)."}
    blocked = _spend(cfg, t.EDIT_VIEW_CREDITS * len(edits), "Edit Multi-view")
    if blocked:
        return blocked
    payload = {"input": str(_tripo_ref(made)["task_id"]), "prompts": edits}
    return _views_out(_run(ctx, _client(), "edit_multiview", payload))


# --------------------------------------------------------------------------- model processing


@_guard
def texture(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    quality = str(cfg.get("texture_quality") or "standard")
    if quality not in t.TEXTURE_QUALITIES:
        quality = "standard"
    blocked = _spend(cfg, t.TEXTURE_CREDITS[quality], "Texture")
    if blocked:
        return blocked
    client = _client()
    payload: dict[str, Any] = {"input": _source(client, inp.get("mesh"), "3D model"), "pbr": cfg.get("no_pbr") is not True}
    if quality != "standard":
        payload["texture_quality"] = quality
    if quality == "fast":
        payload["model"] = t.FAST_TEXTURE_VERSION
    prompt_obj: dict[str, Any] = {}
    if _path_of(inp.get("image")):
        prompt_obj["image"] = _source(client, inp.get("image"), "Reference picture")
    elif _text(inp.get("prompt")):
        prompt_obj["text"] = _text(inp.get("prompt"))[:1024]
        if _path_of(inp.get("style_image")):
            prompt_obj["style_image"] = _source(client, inp.get("style_image"), "Style picture")
    if prompt_obj:
        payload["texture_prompt"] = prompt_obj
    if cfg.get("texture_alignment") == "geometry":
        payload["texture_alignment"] = "geometry"
    return _mesh_out(_run(ctx, client, "texture", payload), "model")


@_guard
def convert(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    fmt = str(cfg.get("format") or "FBX").upper()
    fmt = "GLTF" if fmt in ("GLB", "GLTF") else fmt
    if fmt not in t.CONVERT_FORMATS:
        return {"ok": False, "error": f"Format must be one of {', '.join(t.CONVERT_FORMATS)}."}
    opts: dict[str, Any] = {"format": fmt}
    if cfg.get("fbx_preset"):
        opts["fbx_preset"] = str(cfg["fbx_preset"])
    face_limit = int(_number(inp.get("polycount"), cfg.get("face_limit")))
    if face_limit > 0:
        opts["face_limit"] = face_limit
    for key, name in (("quad", "quad"), ("pivot_bottom", "pivot_to_center_bottom"), ("flatten_bottom", "flatten_bottom"),
                      ("in_place", "animate_in_place")):
        if cfg.get(key) is True:
            opts[name] = True
    scale = _number(cfg.get("scale"))
    if scale and scale != 1:
        opts["scale_factor"] = scale
    size = int(_number(cfg.get("texture_size")))
    if size > 0:
        opts["texture_size"] = size
    blocked = _spend(cfg, t.CONVERT_CREDITS[1 if t.convert_is_advanced(opts) else 0], f"Convert to {fmt}")
    if blocked:
        return blocked
    client = _client()
    return _mesh_out(_run(ctx, client, "convert", {**opts, "input": _source(client, inp.get("mesh"), "3D model")}), "model")


@_guard
def stylize(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    style = str(cfg.get("style") or "lego")
    if style not in t.STYLES:
        return {"ok": False, "error": f"Style must be one of {', '.join(t.STYLES)}."}
    blocked = _spend(cfg, t.STYLIZE_CREDITS, f"Stylize ({style})")
    if blocked:
        return blocked
    client = _client()
    src = _source(client, inp.get("mesh"), "3D model")
    payload: dict[str, Any] = {"input": src, "style": style}
    if not (t.is_url(src) or src.startswith("file_")):
        payload["original_model_task_id"] = src
    block = int(_number(cfg.get("block_size")))
    if block > 0:
        payload["block_size"] = block
    return _mesh_out(_run(ctx, client, "stylize", payload), "model")


@_guard
def retopology(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    version = str(cfg.get("version") or "v3.0")
    if version not in t.RETOPO_VERSIONS:
        version = "v3.0"
    quad = cfg.get("quad") is True
    face_limit = int(_number(inp.get("polycount"), cfg.get("face_limit")))
    if version == "v1.0" and face_limit <= 0:
        return {"ok": False, "error": "Retopology v1.0 needs Target polygons."}
    smart_uv = cfg.get("smart_uv") is True and version == "v3.0"
    blocked = _spend(cfg, t.RETOPO_CREDITS[version][1 if quad else 0], f"Retopology {version}")
    if blocked:
        return blocked
    client = _client()
    payload: dict[str, Any] = {"input": _source(client, inp.get("mesh"), "3D model"), "model": version}
    if face_limit > 0:
        payload["face_limit"] = face_limit
    if quad:
        payload["quad"] = True
    if smart_uv:
        payload["smart_uv"] = True
    return _mesh_out(_run(ctx, client, "decimate", payload), "model")


@_guard
def smart_uv(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    blocked = _spend(cfg, t.SMART_UV_CREDITS, "Smart UV")
    if blocked:
        return blocked
    client = _client()
    payload = {"input": _source(client, inp.get("mesh"), "3D model"), "bake": cfg.get("no_bake") is not True}
    out = _mesh_out(_run(ctx, client, "smart_uv", payload), "model")
    if out.get("ok") and out.get("preview"):
        out["uv"] = out.pop("preview")
    return out


@_guard
def segment(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    version = str(cfg.get("version") or "v1.0-20250506")
    if version not in t.SEGMENT_VERSIONS:
        version = "v1.0-20250506"
    blocked = _spend(cfg, t.SEGMENT_CREDITS, "Segment Parts")
    if blocked:
        return blocked
    client = _client()
    payload: dict[str, Any] = {"input": _source(client, inp.get("mesh"), "3D model"), "model": version}
    if version.startswith("v2"):
        if cfg.get("granularity") in ("simple", "balanced", "detailed"):
            payload["segmentation_granularity"] = cfg["granularity"]
        if _path_of(inp.get("ref_image")):
            payload["ref_image"] = _source(client, inp.get("ref_image"), "Reference picture")
    return _mesh_out(_run(ctx, client, "segment", payload), "segment")


@_guard
def complete_parts(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    ref = _tripo_ref(inp.get("mesh"), "segment")
    if ref is None:
        return {"ok": False, "error": "Complete Parts needs the model straight from a Tripo Segment Parts node."}
    mode = "quick_cap" if cfg.get("mode") == "quick_cap" else "ai_completion"
    blocked = _spend(cfg, t.COMPLETE_CREDITS[mode], "Complete Parts")
    if blocked:
        return blocked
    payload: dict[str, Any] = {"input": str(ref["task_id"])}
    if mode == "quick_cap":
        payload["completion_mode"] = mode
    parts = t.split_names(inp.get("parts"), limit=200)
    if parts:
        payload["part_names"] = parts
    return _mesh_out(_run(ctx, _client(), "complete", payload), "model")


# --------------------------------------------------------------------------- rigging / animation


@_guard
def rig_check(ctx: Ctx) -> dict[str, Any]:
    inp = _inputs(ctx)
    client = _client()
    parsed = _run(ctx, client, "rig_check", {"input": _source(client, inp.get("mesh"), "3D model")})
    return {"ok": True, "riggable": bool(parsed.get("riggable")), "rig_type": str(parsed.get("rig_type") or ""),
            "info": {"task_id": parsed.get("task_id"), "riggable": parsed.get("riggable"), "rig_type": parsed.get("rig_type")}}


@_guard
def rig(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    blocked = _spend(cfg, t.RIG_CREDITS, "Auto Rig")
    if blocked:
        return blocked
    client = _client()
    source = _source(client, inp.get("mesh"), "3D model")
    kind = str(cfg.get("rig_type") or "auto")
    if kind == "auto":
        check = client.run("rig_check", {"input": source}, _folder(ctx))  # free
        if check.get("riggable") is False:
            return {"ok": False, "error": "Tripo says this model can't be rigged (check it is one whole character in a clear pose)."}
        kind = str(check.get("rig_type") or "biped")
    if kind not in t.RIG_TYPES:
        kind = "biped"
    spec = str(cfg.get("spec") or "tripo")
    if spec not in t.RIG_SPECS:
        spec = "tripo"
    version = t.rig_version_for(kind, spec, str(cfg.get("version") or "auto"))
    out_format = "glb" if cfg.get("out_format") == "glb" else "fbx"
    payload: dict[str, Any] = {"input": source, "model": version, "rig_type": kind, "out_format": out_format}
    if kind == "biped":
        payload["spec"] = spec
    out = _mesh_out(_run(ctx, client, "rig", payload), "rig", rig_version=version, rig_type=kind, spec=spec)
    if out.get("ok"):
        out["rig_type"] = kind
    return out


@_guard
def animate(ctx: Ctx) -> dict[str, Any]:
    cfg, inp = _cfg(ctx), _inputs(ctx)
    ref = _tripo_ref(inp.get("mesh"), "rig")
    if ref is None:
        return {"ok": False, "error": "Animate needs the model straight from a Tripo Auto Rig node."}
    names = t.split_names(inp.get("animations") or cfg.get("animations") or "idle", limit=10)
    version, kind = str(ref.get("rig_version") or "v1.0-20240301"), str(ref.get("rig_type") or "biped")
    ids = [t.animation_id(n, version, kind) for n in names]
    blocked = _spend(cfg, t.RETARGET_CREDITS * len(ids), f"Animate ({len(ids)} animation{'s' if len(ids) != 1 else ''})")
    if blocked:
        return blocked
    client = _client()
    out_format = "glb" if cfg.get("out_format") == "glb" else "fbx"
    meshes: list[dict[str, Any]] = []
    files: list[dict[str, Any]] = []
    for anim in ids:  # one job per animation: one model file each
        payload: dict[str, Any] = {"input": str(ref["task_id"]), "original_model_task_id": str(ref["task_id"]),
                                   "animation": anim, "out_format": out_format}
        if cfg.get("in_place") is True:
            payload["animate_in_place"] = True
        step = _mesh_out(_run(ctx, client, "retarget", payload), "animation", animation=anim,
                         rig_version=version, rig_type=kind)
        if not step.get("ok"):
            return step if not meshes else {**step, "error": f"{anim}: {step.get('error')}"}
        meshes.append(step["mesh"])
        files.extend(step["files"])
    return {"ok": True, "mesh": meshes[0], "meshes": meshes, "files": files, "animations": ids}


# --------------------------------------------------------------------------- account


@_guard
def balance(_ctx: Ctx) -> dict[str, Any]:
    bal = _client().balance()
    return {"ok": True, "balance": bal["balance"], "frozen": bal["frozen"]}


HANDLERS: dict[str, Callable[[Ctx], dict[str, Any]]] = {
    "tripo.text_to_3d": text_to_3d,
    "tripo.image_to_3d": image_to_3d,
    "tripo.multiview_to_3d": multiview_to_3d,
    "tripo.image_to_splat": image_to_splat,
    "tripo.text_to_image": text_to_image,
    "tripo.edit_image": edit_image,
    "tripo.image_to_multiview": image_to_multiview,
    "tripo.edit_multiview": edit_multiview,
    "tripo.texture": texture,
    "tripo.convert": convert,
    "tripo.stylize": stylize,
    "tripo.retopology": retopology,
    "tripo.smart_uv": smart_uv,
    "tripo.segment": segment,
    "tripo.complete_parts": complete_parts,
    "tripo.rig_check": rig_check,
    "tripo.rig": rig,
    "tripo.animate": animate,
    "tripo.balance": balance,
}


def register_nodes(api: Any) -> None:
    _STATE["api"] = api
    if not hasattr(api, "register_automation_node"):
        return
    for node_type, handler in HANDLERS.items():
        api.register_automation_node(node_type, handler)
