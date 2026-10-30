"""Tripo AI API (v3) — HTTP client, request builders, task parsing and downloads.

Calls https://openapi.tripo3d.ai/v3 with a Bearer key from the app's encrypted
credentials (secret key ``tripo_api_key``). Stdlib only (urllib), so the module
also runs outside the app for the self-check.
"""

from __future__ import annotations

import base64
import binascii
import json
import logging
import re
import shutil
import tempfile
import time
import urllib.error
import urllib.parse
import urllib.request
import uuid
import zipfile
from pathlib import Path
from typing import Any

log = logging.getLogger("uefn.plugin.tripo")

PLUGIN_ID = "tripo"
SECRET_KEY = "tripo_api_key"
BASE_URL = "https://openapi.tripo3d.ai/v3"
CONSOLE_URL = "https://developers.tripo3d.ai"
USER_AGENT = "UEFN-Ducky-Tripo/1.0"
DEFAULT_TIMEOUT = 60

# 3D generation versions (``model`` is required on V3). P series = clean low-poly.
MODEL_VERSIONS = ("v3.1-20260211", "v3.0-20250812", "v2.5-20250123", "P1-20260311", "P2-20260801")
DEFAULT_MODEL = "v3.1-20260211"
TEXTURE_QUALITIES = ("fast", "standard", "detailed", "extreme")
TEXTURE_VERSIONS = ("v3.5-20260815", "v3.0-20250812", "v2.5-20250123")
FAST_TEXTURE_VERSION = "v3.5-20260815"
IMAGE_MODELS = (
    "seedream_v4", "seedream_v5", "banana", "banana2", "banana_pro",
    "chat_image_2", "chat_image_2.5_flare", "chat_image_2.5_sunburst", "chat_image_1.5",
)
DEFAULT_IMAGE_MODEL = "seedream_v4"
IMAGE_TEMPLATES = ("t_pose", "character_completion", "3d_enhance", "variants", "figure", "asset_extraction")
RIG_VERSIONS = ("v1.0-20240301", "v2.5-20260210", "v3.0-20260909")
RIG_TYPES = ("biped", "quadruped", "hexapod", "octopod", "avian", "serpentine", "aquatic", "others")
RIG_SPECS = ("tripo", "mixamo", "actorcore", "unity", "unreal", "vrm")
# Specs only the v3.0 rig makes.
V3_RIG_SPECS = frozenset({"actorcore", "unity", "unreal", "vrm"})
STYLES = ("lego", "voxel", "voronoi", "minecraft", "keyring", "fridge_magnet", "keycap")
CONVERT_FORMATS = ("GLTF", "FBX", "USDZ", "OBJ", "STL", "3MF")
TEXTURE_FORMATS = ("JPEG", "PNG", "WEBP", "BMP", "DPX", "HDR", "OPEN_EXR", "TARGA", "TIFF")
FBX_PRESETS = ("blender", "3dsmax", "mixamo", "bake_scale")
RETOPO_VERSIONS = ("v3.0", "v2.0", "v1.0")
SEGMENT_VERSIONS = ("v1.0-20250506", "v2.0-20260430")
VIEWS = ("front", "left", "back", "right")

# kind → POST path under BASE_URL.
ENDPOINTS: dict[str, str] = {
    "text_to_model": "/generation/text-to-model",
    "image_to_model": "/generation/image-to-model",
    "multiview_to_model": "/generation/multiview-to-model",
    "text_to_image": "/generation/text-to-image",
    "image_to_image": "/generation/image-to-image",
    "image_to_multiview": "/generation/image-to-multiview",
    "edit_multiview": "/generation/edit-multiview",
    "image_to_splat": "/generation/image-to-splat",
    "texture": "/models/texture",
    "convert": "/models/convert",
    "stylize": "/models/stylize",
    "rig_check": "/animations/rig-check",
    "rig": "/animations/rig",
    "retarget": "/animations/retarget",
    "segment": "/mesh/segment",
    "complete": "/mesh/complete",
    "decimate": "/mesh/decimate",
    "smart_uv": "/mesh/uv",
}

# Animation presets (retarget). v2.5/v3.0 rigs: these for every rig type.
ANIMATIONS_V25 = (
    "preset:idle", "preset:walk", "preset:run", "preset:dive", "preset:climb", "preset:jump",
    "preset:slash", "preset:shoot", "preset:hurt", "preset:fall", "preset:turn",
    "preset:quadruped:walk", "preset:hexapod:walk", "preset:octopod:walk",
    "preset:serpentine:march", "preset:aquatic:march",
)
_V1_NAMES = (
    "afraid agree angry_01 angry_02 angry_03 basketball_shot bow box_01 box_02 box_03 cast_a_spell "
    "cheer chop clap climb complain_01 complain_02 cross_body_crunch crossover_dribble cry dance_01 "
    "dance_02 dance_03 dance_04 dance_05 dance_06 defeat_02 defeat_03 depressed dig dive dribble fall "
    "fire flee_01 flee_02 flip fold_arms football_catch football_save football_pass freaky frightened "
    "front_kick_01 front_kick_02 frustrated_01 frustrated_02 golf greet_01 greet_02 greet_03 greet_04 "
    "heart_pose hit_to_body_01 hit_to_body_02 hit_to_head hit_to_side hit_to_stomach hug hurt idle "
    "jump_down jump jump_rope_01 jump_rope_02 laugh_01 laugh_02 lift_heavy look_around make_a_call_01 "
    "make_a_call_02 pitch_baseball play_mobile_game play_video_game press-up run_upstairs run scared_01 "
    "scared_02 scratch shoot shovel sing_01 sing_02 sing_03 sing_04 sit slash sob standing_relax surf "
    "swagger swim turn victory_celebration volleyball wait walk warm_up wave_goodbye_01 wave_goodbye_02"
)
# v1.0 rig (biped only): a big humanoid library.
ANIMATIONS_V1 = tuple(f"preset:biped:{name}" for name in _V1_NAMES.split())
# Rig type → the walk-style preset of the v2.5 set.
_CREATURE_WALK = {
    "quadruped": "preset:quadruped:walk",
    "hexapod": "preset:hexapod:walk",
    "octopod": "preset:octopod:walk",
    "serpentine": "preset:serpentine:march",
    "aquatic": "preset:aquatic:march",
}

# Credit estimates (1 credit = $0.01) from developers.tripo3d.ai/en/pricing. Tripo shows
# the real cost on the finished task (credits_consumed).
_MODEL_BASE = {"text_to_model": (10, 20), "image_to_model": (20, 30), "multiview_to_model": (20, 30)}
TEXTURE_CREDITS = {"fast": 10, "standard": 10, "detailed": 20, "extreme": 30}
RETOPO_CREDITS = {"v3.0": (35, 40), "v2.0": (30, 30), "v1.0": (10, 10)}
RIG_CREDITS = 25
RETARGET_CREDITS = 10
CONVERT_CREDITS = (5, 10)  # basic, advanced
SMART_UV_CREDITS = 20
SEGMENT_CREDITS = 40
COMPLETE_CREDITS = {"ai_completion": 50, "quick_cap": 30}
MULTIVIEW_CREDITS = 10
EDIT_VIEW_CREDITS = 5
STYLIZE_CREDITS = 20  # not on the price list: an estimate
SPLAT_CREDITS = 30  # not on the price list: an estimate
# (≤1K, 2K, 4K)
_IMAGE_PRICE: dict[str, tuple[int, int, int]] = {
    "seedream_v4": (5, 5, 5), "seedream_v5": (5, 5, 5), "banana": (5, 5, 5),
    "banana2": (10, 10, 15), "banana_pro": (15, 15, 20),
    "chat_image_1": (5, 5, 5), "chat_image_1.5": (10, 10, 10), "chat_image_2": (10, 10, 15),
    "chat_image_2.5_flare": (10, 10, 15), "chat_image_2.5_sunburst": (10, 10, 15),
}
_GPT_QUALITY_PRICE = {"high": (20, 25, 40), "xhigh": (25, 30, 45), "max": (30, 50, 50)}

_RETRY_HTTP = frozenset({429, 500, 502, 503, 504})
_RETRY_CODES = frozenset({1000, 1001, 1007, 2000})
_IMAGE_EXTS = {".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".webp": "image/webp",
               ".bmp": "image/bmp", ".tif": "image/tiff", ".tiff": "image/tiff"}
_MODEL_EXTS = {".glb": "model/gltf-binary", ".gltf": "model/gltf+json", ".fbx": "application/octet-stream",
               ".obj": "text/plain", ".stl": "model/stl", ".3mf": "model/3mf", ".usdz": "model/vnd.usdz+zip"}
_IMAGE_MAX = 20 * 1024 * 1024
_MODEL_MAX = 150 * 1024 * 1024
_KNOWN_EXTS = (*_MODEL_EXTS, *_IMAGE_EXTS, ".zip", ".ply", ".spz", ".splat", ".mp4", ".usdc")
_TOKEN_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:-]{5,200}$")


class TripoError(Exception):
    def __init__(self, message: str, *, status: int | None = None, code: int | None = None, detail: Any = None):
        super().__init__(message)
        self.status = status
        self.code = code
        self.detail = detail


def _api_key() -> str:
    try:
        from backend.agent.secrets import load_keys
    except ImportError:
        return ""
    # Read the file, not the process cache: tools run outside Settings, so a key saved there
    # after this process cached its keys would stay invisible until restart.
    return (load_keys(use_cache=False).get(SECRET_KEY) or "").strip()


def plugin_prefs() -> dict[str, Any]:
    """Defaults the person picked in Settings → Tripo (plain prefs, not secrets)."""
    try:
        from frontend.ui_web.plugin_host_api import prefs_plugin_get

        prefs = prefs_plugin_get(PLUGIN_ID) or {}
    except Exception:  # noqa: BLE001 — prefs are best-effort
        prefs = {}
    return prefs if isinstance(prefs, dict) else {}


def pref(key: str, default: str, allowed: tuple[str, ...] = ()) -> str:
    value = str(plugin_prefs().get(key) or "").strip()
    if not value or (allowed and value not in allowed):
        return default
    return value


def auth_header(api_key: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {api_key}", "Accept": "application/json", "User-Agent": USER_AGENT}


def _detail_message(detail: Any) -> tuple[str, int | None]:
    if isinstance(detail, dict):
        msg = str(detail.get("message") or detail.get("error") or "").strip()
        hint = str(detail.get("suggestion") or "").strip()
        code = detail.get("code")
        try:
            code = int(code) if code is not None else None
        except (TypeError, ValueError):
            code = None
        return (f"{msg} ({hint})" if hint and hint not in msg else msg)[:400], code
    return str(detail or "")[:400], None


def error_message(status: int | None, detail: Any) -> str:
    """A person-readable line for a failed Tripo call."""
    msg, code = _detail_message(detail)
    if status == 401:
        return "Tripo rejected the API key (401). Paste a key from developers.tripo3d.ai in Settings → Tripo and press Test."
    if code == 2010 or (status == 403 and "credit" in msg.lower()):
        return "Tripo: not enough credits (2010). Top up at developers.tripo3d.ai → Billing."
    if code == 2008:
        return "Tripo refused the content (2008, content policy). Change the prompt or picture."
    if status == 429 or code in (1007, 2000):
        return "Tripo is rate limiting (too many jobs at once). Wait a moment and retry."
    head = f"Tripo error {status}" if status else "Tripo error"
    if code is not None:
        head += f" (code {code})"
    return head + (f": {msg}" if msg else "")


def task_error(raw: dict[str, Any]) -> str:
    code = raw.get("error_code")
    msg = str(raw.get("error_message") or "").strip()
    status = str(raw.get("status") or "").lower()
    if code in (2008, "2008") or status == "banned":
        return "Tripo refused the content (content policy). Change the prompt or picture; no credits were spent."
    if code in (2018, "2018") or status == "expired":
        return "The Tripo job timed out (model too complex or the queue was full); no credits were spent. Try again or simplify."
    if status == "cancelled":
        return "The Tripo job was cancelled; no credits were spent."
    if msg or code:
        return f"{msg or 'Tripo job failed'}" + (f" (code {code})" if code else "")
    return "The Tripo job failed; no credits were spent."


# --------------------------------------------------------------------------- inputs


def is_url(value: str) -> bool:
    return value.startswith(("http://", "https://"))


def looks_like_path(value: str) -> bool:
    """A local path, not a task id / file token / URL."""
    if is_url(value):
        return False
    if "\\" in value or "/" in value or (len(value) > 2 and value[1] == ":"):
        return True
    return value.lower().endswith(_KNOWN_EXTS)


def mime_for(path: Path) -> str:
    ext = path.suffix.lower()
    return _IMAGE_EXTS.get(ext) or _MODEL_EXTS.get(ext) or "application/octet-stream"


def multipart_body(field: str, filename: str, data: bytes, mime: str) -> tuple[bytes, str]:
    boundary = "----tripo" + uuid.uuid4().hex
    safe_name = filename.replace('"', "_").replace("\r", "").replace("\n", "")
    head = (
        f"--{boundary}\r\n"
        f'Content-Disposition: form-data; name="{field}"; filename="{safe_name}"\r\n'
        f"Content-Type: {mime}\r\n\r\n"
    ).encode("utf-8")
    return head + data + f"\r\n--{boundary}--\r\n".encode("utf-8"), f"multipart/form-data; boundary={boundary}"


def data_uri_to_file(uri: str) -> Path:
    """An inline data: URI (agents pass pictures this way) → a temp file to upload."""
    head, _, payload = uri.partition(",")
    if ";base64" not in head:
        raise TripoError("Only base64 data: URIs can be uploaded to Tripo.")
    mime = head[5:].split(";", 1)[0].lower()
    ext = next((e for e, m in {**_IMAGE_EXTS, **_MODEL_EXTS}.items() if m == mime), ".png")
    try:
        raw = base64.b64decode(payload, validate=False)
    except (binascii.Error, ValueError) as exc:
        raise TripoError(f"Bad data: URI: {exc}") from exc
    folder = Path(tempfile.gettempdir()) / "uefn-ducky-tripo"
    folder.mkdir(parents=True, exist_ok=True)
    dest = folder / f"inline-{uuid.uuid4().hex[:12]}{ext}"
    dest.write_bytes(raw)
    return dest


# --------------------------------------------------------------------------- client


def _urlopen(req: urllib.request.Request, timeout: float):  # tests replace this
    return urllib.request.urlopen(req, timeout=timeout)


class TripoClient:
    def __init__(self, api_key: str | None = None, *, base_url: str = BASE_URL, timeout: int = DEFAULT_TIMEOUT):
        key = (api_key if api_key is not None else _api_key()).strip()
        if not key:
            raise TripoError("Tripo API key not set. Paste it in Settings → Tripo (developers.tripo3d.ai → API Keys).")
        self.api_key = key
        self.base_url = base_url.rstrip("/")
        self.timeout = timeout

    # ---- transport

    def _send(self, req: urllib.request.Request, *, retries: int = 3) -> Any:
        delay = 1.0
        for attempt in range(retries + 1):
            try:
                with _urlopen(req, self.timeout) as resp:
                    body = resp.read().decode("utf-8", "replace")
            except urllib.error.HTTPError as exc:
                raw = ""
                try:
                    raw = exc.read().decode("utf-8", "replace")
                except Exception:  # noqa: BLE001
                    pass
                try:
                    detail: Any = json.loads(raw) if raw else {}
                except ValueError:
                    detail = raw
                _msg, code = _detail_message(detail)
                if attempt < retries and (exc.code in _RETRY_HTTP or code in _RETRY_CODES):
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TripoError(error_message(exc.code, detail), status=exc.code, code=code, detail=detail) from exc
            except urllib.error.URLError as exc:
                if attempt < retries:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TripoError(f"Can't reach Tripo: {exc.reason}") from exc
            try:
                envelope = json.loads(body) if body.strip() else {}
            except ValueError as exc:
                raise TripoError(f"Tripo sent something that isn't JSON: {body[:200]}") from exc
            if not isinstance(envelope, dict):
                return envelope
            code = envelope.get("code")
            if code not in (0, None, "0"):
                try:
                    num = int(code)
                except (TypeError, ValueError):
                    num = None
                if attempt < retries and num in _RETRY_CODES:
                    time.sleep(delay)
                    delay *= 2
                    continue
                raise TripoError(error_message(None, envelope), code=num, detail=envelope)
            return envelope.get("data", envelope)
        raise TripoError("Tripo did not answer after several tries.")

    def request(self, method: str, path: str, body: dict[str, Any] | None = None, *, retries: int = 3) -> Any:
        headers = auth_header(self.api_key)
        data = None
        if body is not None:
            data = json.dumps(body).encode("utf-8")
            headers["Content-Type"] = "application/json"
        req = urllib.request.Request(f"{self.base_url}{path}", data=data, headers=headers, method=method)
        return self._send(req, retries=retries)

    # ---- account

    def balance(self) -> dict[str, Any]:
        data = self.request("GET", "/account/balance")
        data = data if isinstance(data, dict) else {}
        return {"balance": _num(data.get("balance")), "frozen": _num(data.get("frozen"))}

    def usage(self, limit: int = 20, offset: int = 0) -> list[dict[str, Any]]:
        q = urllib.parse.urlencode({"limit": max(1, min(int(limit or 20), 200)), "offset": max(0, int(offset or 0))})
        data = self.request("GET", f"/account/usage?{q}")
        if isinstance(data, dict):
            data = data.get("items") or data.get("list") or data.get("rows") or []
        return [row for row in data if isinstance(row, dict)] if isinstance(data, list) else []

    # ---- files

    def upload(self, path: str | Path) -> str:
        p = Path(path).expanduser()
        if not p.is_file():
            raise TripoError(f"File not found: {p}")
        size = p.stat().st_size
        limit = _IMAGE_MAX if p.suffix.lower() in _IMAGE_EXTS else _MODEL_MAX
        if size > limit:
            raise TripoError(f"{p.name} is {size // (1024 * 1024)} MB; Tripo takes up to {limit // (1024 * 1024)} MB for this kind of file.")
        body, ctype = multipart_body("file", p.name, p.read_bytes(), mime_for(p))
        headers = {**auth_header(self.api_key), "Content-Type": ctype}
        req = urllib.request.Request(f"{self.base_url}/files", data=body, headers=headers, method="POST")
        data = self._send(req, retries=4)  # uploads are limited to ~10 a minute
        token = (data or {}).get("file_token") if isinstance(data, dict) else None
        if not token:
            raise TripoError(f"Tripo upload sent no file_token: {data}")
        return str(token)

    def resolve(self, value: str, what: str = "input") -> str:
        """A path, data: URI, URL, task id or file token → what Tripo's ``input`` takes."""
        s = str(value or "").strip().strip('"')
        if not s:
            raise TripoError(f"{what} is required")
        if s.startswith("data:"):
            return self.upload(data_uri_to_file(s))
        if is_url(s):
            return s
        if Path(s).expanduser().is_file():
            return self.upload(s)
        if looks_like_path(s):
            raise TripoError(f"{what}: file not found: {s}")
        if not _TOKEN_RE.match(s):
            raise TripoError(f"{what}: {s!r} is not a file, link, Tripo task id or file token")
        return s

    # ---- tasks

    def create(self, kind: str, payload: dict[str, Any]) -> str:
        path = ENDPOINTS.get(kind)
        if not path:
            raise TripoError(f"Unknown Tripo task kind {kind!r}")
        data = self.request("POST", path, payload)
        task_id = data.get("task_id") if isinstance(data, dict) else None
        if not task_id:
            raise TripoError(f"Tripo sent no task id: {data}")
        return str(task_id)

    def task(self, task_id: str) -> dict[str, Any]:
        tid = urllib.parse.quote(str(task_id or "").strip(), safe="")
        if not tid:
            raise TripoError("task_id is required")
        data = self.request("GET", f"/tasks/{tid}")
        return parse_task(data if isinstance(data, dict) else {})

    def tasks(self, task_ids: list[str]) -> dict[str, Any]:
        ids = [str(t).strip() for t in task_ids if str(t).strip()][:100]
        if not ids:
            raise TripoError("task_ids is required")
        data = self.request("POST", "/tasks/list", {"task_ids": ids})
        data = data if isinstance(data, dict) else {}
        rows = data.get("tasks") if isinstance(data.get("tasks"), dict) else {}
        return {"tasks": {tid: parse_task(row) for tid, row in rows.items() if isinstance(row, dict)},
                "missed": list(data.get("missed") or [])}

    def wait(self, task_id: str, *, interval: float = 3, timeout: float = 1800) -> dict[str, Any]:
        deadline = time.monotonic() + max(10.0, float(timeout))
        while True:
            parsed = self.task(task_id)
            if parsed["finished"] or parsed["failed"]:
                return parsed
            if time.monotonic() >= deadline:
                raise TripoError(f"Tripo task {task_id} was still {parsed['status']} after {int(timeout)} s; check it later with tripo_status.")
            time.sleep(max(1.0, float(interval)))

    def run(self, kind: str, payload: dict[str, Any], output_dir: str | Path, *, timeout: float = 1800) -> dict[str, Any]:
        """Create, wait, download. Raises TripoError when the job fails."""
        task_id = self.create(kind, payload)
        parsed = self.wait(task_id, timeout=timeout)
        if parsed["failed"]:
            raise TripoError(parsed["failure_reason"] or "Tripo job failed", detail=parsed)
        parsed["downloaded"] = download_results(parsed, Path(output_dir) / task_id)
        parsed["output_dir"] = str(Path(output_dir) / task_id)
        return parsed


def _num(value: Any) -> float:
    try:
        return round(float(value), 2)
    except (TypeError, ValueError):
        return 0.0


# --------------------------------------------------------------------------- task parsing

_DONE = "success"
_RUNNING = frozenset({"queued", "running", "pending", "processing", ""})


def collect_urls(output: Any, prefix: str = "") -> list[dict[str, str]]:
    """Every downloadable link in a task's ``output`` (model, preview, views, UV render…)."""
    found: list[dict[str, str]] = []
    if isinstance(output, dict):
        for key, value in output.items():
            name = f"{prefix}{key}"
            if isinstance(value, str) and is_url(value.strip()):
                found.append({"key": name, "url": value.strip()})
            elif isinstance(value, (dict, list)):
                found.extend(collect_urls(value, f"{name}."))
    elif isinstance(output, list):
        for n, value in enumerate(output):
            if isinstance(value, str) and is_url(value.strip()):
                found.append({"key": f"{prefix}{n}", "url": value.strip()})
            elif isinstance(value, (dict, list)):
                found.extend(collect_urls(value, f"{prefix}{n}."))
    rank = {"model_url": 0, "generated_image_url": 1}
    return sorted(found, key=lambda row: (rank.get(row["key"].rsplit(".", 1)[-1], 5), row["key"]))


def parse_task(raw: dict[str, Any]) -> dict[str, Any]:
    status = str(raw.get("status") or "").strip().lower()
    output = raw.get("output") if isinstance(raw.get("output"), dict) else {}
    finished = status == _DONE
    failed = not finished and status not in _RUNNING
    links = collect_urls(output)
    model_url = output.get("model_url") or output.get("pbr_model") or output.get("model") or ""
    preview = output.get("rendered_image_url") or output.get("rendered_image") or ""
    out: dict[str, Any] = {
        "task_id": raw.get("task_id"),
        "type": raw.get("type"),
        "status": status or "unknown",
        "progress": raw.get("progress", 0),
        "finished": finished,
        "failed": failed,
        "failure_reason": task_error(raw) if failed else None,
        "error_code": raw.get("error_code"),
        "model_url": model_url if isinstance(model_url, str) else "",
        "preview_url": preview if isinstance(preview, str) else "",
        "image_url": output.get("generated_image_url") or "",
        "results": links,
        "output": output,
        "input": raw.get("input") if isinstance(raw.get("input"), dict) else {},
        "credits_consumed": raw.get("credits_consumed", raw.get("consumed_credit")),
        "created_at": raw.get("created_at"),
        "completed_at": raw.get("completed_at"),
    }
    if "riggable" in output:
        out["riggable"] = bool(output.get("riggable"))
        out["rig_type"] = str(output.get("rig_type") or output.get("topology") or "")
    return out


# --------------------------------------------------------------------------- downloads


def sniff_ext(head: bytes) -> str:
    if head[:4] == b"glTF":
        return ".glb"
    if head.startswith(b"Kaydara FBX Binary"):
        return ".fbx"
    if head[:8] == b"\x89PNG\r\n\x1a\n":
        return ".png"
    if head[:3] == b"\xff\xd8\xff":
        return ".jpg"
    if head[:4] == b"RIFF" and head[8:12] == b"WEBP":
        return ".webp"
    if head[:4] == b"PK\x03\x04":
        return ".zip"
    if head[:4] == b"ply\n" or head[:5] == b"ply\r\n":
        return ".ply"
    if head.lstrip()[:1] == b"{":
        return ".gltf"
    return ""


def url_ext(url: str) -> str:
    suffix = Path(urllib.parse.urlparse(url).path).suffix.lower()
    return suffix if suffix in _KNOWN_EXTS else ""


def _file_stem(key: str) -> str:
    last = key.rsplit(".", 1)[-1]
    base = re.sub(r"_url$", "", last) or "file"
    return {"model": "model", "rendered_image": "preview", "generated_image": "image",
            "uv_render": "uv", "front_view": "front", "left_view": "left", "back_view": "back",
            "right_view": "right"}.get(base, re.sub(r"[^A-Za-z0-9_-]+", "_", base)[:60] or "file")


def _fetch(url: str, timeout: float = 300) -> bytes:
    # Signed CDN links: never send the API key to them.
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT}, method="GET")
    delay = 1.0
    for attempt in range(4):
        try:
            with _urlopen(req, timeout) as resp:
                return resp.read()
        except urllib.error.HTTPError as exc:
            if attempt < 3 and exc.code in _RETRY_HTTP:
                time.sleep(delay)
                delay *= 2
                continue
            raise TripoError(f"Download failed (HTTP {exc.code}); links last ~24 h — run tripo_status again for fresh ones.") from exc
        except urllib.error.URLError as exc:
            if attempt < 3:
                time.sleep(delay)
                delay *= 2
                continue
            raise TripoError(f"Download failed: {exc.reason}") from exc
    raise TripoError("Download failed")


def safe_extract(zip_path: Path, folder: Path) -> list[str]:
    """Unzip (OBJ + textures) without letting a name escape the folder."""
    out: list[str] = []
    folder.mkdir(parents=True, exist_ok=True)
    root = folder.resolve()
    with zipfile.ZipFile(zip_path) as zf:
        for info in zf.infolist():
            if info.is_dir():
                continue
            target = (folder / info.filename).resolve()
            if root not in target.parents:
                continue
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(info) as src, open(target, "wb") as dst:
                shutil.copyfileobj(src, dst)
            out.append(str(target))
    return out


def download_results(parsed: dict[str, Any], output_dir: str | Path) -> list[str]:
    """Save every output file of a finished task; the main model first."""
    folder = Path(output_dir)
    folder.mkdir(parents=True, exist_ok=True)
    paths: list[str] = []
    seen: set[str] = set()
    for item in parsed.get("results") or []:
        url = item["url"]
        if url in seen:
            continue
        seen.add(url)
        data = _fetch(url)
        ext = url_ext(url) or sniff_ext(data[:64]) or ".bin"
        stem = _file_stem(item["key"])
        dest = folder / f"{stem}{ext}"
        n = 1
        while dest.exists() and str(dest) in paths:
            dest = folder / f"{stem}_{n}{ext}"
            n += 1
        dest.write_bytes(data)
        if ext == ".zip":
            unpacked = safe_extract(dest, folder / stem)
            if unpacked:
                dest.unlink(missing_ok=True)
                paths.extend(unpacked)
                continue
        paths.append(str(dest))
    return paths


def prune_downloads(root: Path, *, keep: int = 80, max_age_days: float = 14) -> None:
    """Drop old task folders so downloads never pile up (newest ``keep`` stay)."""
    try:
        folders = sorted((p for p in root.iterdir() if p.is_dir()), key=lambda p: p.stat().st_mtime, reverse=True)
    except OSError:
        return
    cutoff = time.time() - max_age_days * 86400
    for n, folder in enumerate(folders):
        try:
            if n >= keep or folder.stat().st_mtime < cutoff:
                shutil.rmtree(folder, ignore_errors=True)
        except OSError:
            pass


MAIN_MESH_EXTS = (".glb", ".fbx", ".gltf", ".obj", ".usdz", ".stl", ".3mf")
MAIN_IMAGE_EXTS = (".png", ".jpg", ".jpeg", ".webp")


def main_file(paths: list[str], exts: tuple[str, ...]) -> str:
    for ext in exts:
        for path in paths:
            if path.lower().endswith(ext):
                return path
    return paths[0] if paths else ""


# --------------------------------------------------------------------------- request builders


def is_p_series(version: str) -> bool:
    return str(version or "").upper().startswith("P")


def texture_flags(mode: str) -> tuple[bool, bool]:
    """"pbr" (default) | "texture" | "none" → (texture, pbr)."""
    m = str(mode or "pbr").strip().lower()
    if m in ("none", "off", "false", "no", "untextured", "geometry"):
        return False, False
    if m in ("texture", "textured", "color", "basic"):
        return True, False
    return True, True


def model_options(
    *,
    model_version: str = "",
    texture: str = "pbr",
    texture_quality: str = "",
    geometry_quality: str = "",
    face_limit: int = 0,
    quad: bool = False,
    smart_low_poly: bool = False,
    generate_parts: bool = False,
    auto_size: bool = False,
    export_uv: bool = True,
    model_seed: int = 0,
    texture_seed: int = 0,
) -> dict[str, Any]:
    """Shared options of text / image / multiview → 3D, checked against Tripo's version rules."""
    version = (model_version or "").strip() or pref("default_model", DEFAULT_MODEL, MODEL_VERSIONS)
    if version not in MODEL_VERSIONS:
        raise ValueError(f"model_version must be one of {', '.join(MODEL_VERSIONS)}")
    tex, pbr = texture_flags(texture)
    p_series = is_p_series(version)
    v25 = version.startswith("v2.5")
    out: dict[str, Any] = {"model": version, "texture": tex, "pbr": pbr}
    if generate_parts:
        if tex or pbr:
            raise ValueError("generate_parts makes untextured parts: set texture to none (texture them afterwards with tripo_texture).")
        if quad or smart_low_poly:
            raise ValueError("generate_parts can't be combined with quad or smart_low_poly.")
    gated = {"geometry_quality": geometry_quality == "detailed", "auto_size": auto_size, "quad": quad,
             "smart_low_poly": smart_low_poly, "generate_parts": generate_parts}
    if v25:
        bad = [name for name, on in gated.items() if on]
        if bad:
            raise ValueError(f"{', '.join(bad)} need model v3.0 or newer (not {version}).")
    if p_series:
        bad = [name for name in ("geometry_quality", "smart_low_poly", "generate_parts") if gated[name]]
        if quad and not version.startswith("P2"):
            bad.append("quad")
        if bad:
            raise ValueError(f"{', '.join(bad)} don't apply to {version} (P series is already clean low-poly).")
    quality = (texture_quality or "").strip().lower() or pref("default_texture_quality", "standard", TEXTURE_QUALITIES)
    if quality not in TEXTURE_QUALITIES:
        raise ValueError(f"texture_quality must be one of {', '.join(TEXTURE_QUALITIES)}")
    if tex and quality != "standard":
        if v25 and quality != "fast":
            raise ValueError(f"texture_quality {quality} needs model v3.0 or newer.")
        out["texture_quality"] = quality
        if quality == "fast":
            out["texture_version"] = FAST_TEXTURE_VERSION
    if geometry_quality == "detailed":
        out["geometry_quality"] = "detailed"
    for name in ("auto_size", "quad", "smart_low_poly", "generate_parts"):
        if gated[name]:
            out[name] = True
    if int(face_limit or 0) > 0:
        out["face_limit"] = int(face_limit)
    if not export_uv:
        out["export_uv"] = False
    if int(model_seed or 0):
        out["model_seed"] = int(model_seed)
    if int(texture_seed or 0):
        out["texture_seed"] = int(texture_seed)
    return out


def estimate_model_credits(kind: str, opts: dict[str, Any]) -> int:
    none, textured = _MODEL_BASE.get(kind, (20, 30))
    tex = bool(opts.get("texture") or opts.get("pbr"))
    credits = textured if tex else none
    quality = opts.get("texture_quality")
    if tex and quality == "detailed":
        credits += 10
    elif tex and quality == "extreme":
        credits += 20
    if opts.get("geometry_quality") == "detailed":
        credits += 20
    if opts.get("quad"):
        credits += 5
    if opts.get("smart_low_poly"):
        credits += 10
    if opts.get("generate_parts"):
        credits += 20
    return credits


def _size_tier(size: str, model: str) -> int:
    s = str(size or "").strip().lower()
    if not s or s == "auto":
        return 0 if model == "banana" else 1
    if s in ("0.5k", "1k"):
        return 0
    if s in ("2k", "3k"):
        return 1
    if s == "4k":
        return 2
    m = re.match(r"^(\d+)\s*x\s*(\d+)$", s)
    if m:
        edge = max(int(m.group(1)), int(m.group(2)))
        return 0 if edge <= 1536 else 1 if edge <= 2560 else 2
    return 1


def estimate_image_credits(model: str, size: str = "", quality: str = "") -> int:
    tier = _size_tier(size, model)
    q = str(quality or "").strip().lower()
    if model.startswith("chat_image_2") and q in _GPT_QUALITY_PRICE:
        if q != "high" and not model.startswith("chat_image_2.5"):
            q = "high"
        return _GPT_QUALITY_PRICE[q][tier]
    return _IMAGE_PRICE.get(model, (10, 10, 15))[tier]


def image_options(
    *,
    model: str = "",
    size: str = "",
    aspect_ratio: str = "",
    quality: str = "",
    background: str = "",
    output_format: str = "",
    template: str = "",
) -> dict[str, Any]:
    chosen = (model or "").strip() or pref("default_image_model", DEFAULT_IMAGE_MODEL, IMAGE_MODELS)
    if chosen not in IMAGE_MODELS:
        raise ValueError(f"image model must be one of {', '.join(IMAGE_MODELS)}")
    out: dict[str, Any] = {"model": chosen}
    if size.strip():
        out["size"] = size.strip()
    if aspect_ratio.strip():
        if not chosen.startswith("banana"):
            raise ValueError("aspect_ratio works only on banana models; use size (e.g. 2048x1152) for the others.")
        out["aspect_ratio"] = aspect_ratio.strip()
    if quality.strip():
        if not chosen.startswith("chat_image_2"):
            raise ValueError("quality works only on chat_image_2 / chat_image_2.5 models.")
        out["quality"] = quality.strip().lower()
    if background.strip() and chosen.startswith("chat_image_2.5"):
        out["background"] = background.strip().lower()
        if out["background"] == "transparent":
            out["output_format"] = "png"
    if output_format.strip() and "output_format" not in out:
        out["output_format"] = output_format.strip().lower()
    if template.strip():
        if template.strip() not in IMAGE_TEMPLATES:
            raise ValueError(f"template must be one of {', '.join(IMAGE_TEMPLATES)}")
        out["template"] = template.strip()
    return out


def convert_is_advanced(opts: dict[str, Any]) -> bool:
    """Non-default convert options bill as "advanced" (10 credits instead of 5)."""
    return any(opts.get(k) for k in ("quad", "face_limit", "flatten_bottom", "pivot_to_center_bottom")) or \
        opts.get("texture_size") not in (None, 4096) or opts.get("texture_format") not in (None, "JPEG") or \
        opts.get("scale_factor") not in (None, 1, 1.0)


def rig_version_for(rig_type: str, spec: str, version: str = "") -> str:
    v = (version or "").strip()
    if v and v != "auto":
        if v not in RIG_VERSIONS:
            raise ValueError(f"rig version must be one of {', '.join(RIG_VERSIONS)}")
        if spec in V3_RIG_SPECS and v != "v3.0-20260909":
            raise ValueError(f"spec {spec} needs rig version v3.0-20260909.")
        return v
    if spec in V3_RIG_SPECS or rig_type == "others":
        return "v3.0-20260909"
    if rig_type and rig_type != "biped":
        return "v2.5-20260210"
    return "v1.0-20240301"


def rig_info(client: "TripoClient", rig_task_id: str, version: str = "", kind: str = "") -> tuple[str, str]:
    """The rig engine and skeleton of a rig job, read from its own request when not given."""
    if version and kind:
        return version, kind
    echo = client.task(rig_task_id).get("input") or {}
    version = version or str(echo.get("model") or echo.get("model_version") or "v1.0-20240301")
    kind = kind or str(echo.get("rig_type") or echo.get("topology") or "biped")
    return version, kind


ANIMATION_ALIASES = {"attack": "slash", "bite": "slash", "claw": "slash", "strike": "slash", "hit": "hurt",
                     "damage": "hurt", "stand": "idle", "sprint": "run", "leap": "jump", "fire": "shoot"}


def animation_id(name: str, rig_version: str = "", rig_type: str = "biped") -> str:
    """Friendly name ("walk", "dance_01") → the preset id this rig takes."""
    raw = str(name or "").strip().lower().replace(" ", "_")
    if not raw:
        raise ValueError("empty animation name")
    if not (rig_version or "v1.0").startswith("v1"):
        raw = ANIMATION_ALIASES.get(raw, raw)  # a spec says attack / bite; the v2.5 set has slash
    v1 = (rig_version or "v1.0").startswith("v1")
    if raw.startswith("preset:"):
        pool = ANIMATIONS_V1 if v1 else ANIMATIONS_V25
        if raw not in pool:
            raise ValueError(f"{raw} isn't an animation for this rig ({'v1.0 biped' if v1 else rig_version}).")
        return raw
    if v1:
        for candidate in (f"preset:biped:{raw}", f"preset:biped:{raw}_01"):
            if candidate in ANIMATIONS_V1:
                return candidate
        near = [a.split(":")[-1] for a in ANIMATIONS_V1 if raw.split("_")[0] in a][:8]
        raise ValueError(f"No v1.0 animation called {raw!r}." + (f" Close: {', '.join(near)}." if near else " See tripo_list_animations."))
    kind = (rig_type or "biped").lower()
    if kind in _CREATURE_WALK and raw in ("walk", "march", "move", kind):
        return _CREATURE_WALK[kind]
    if f"preset:{raw}" in ANIMATIONS_V25:
        return f"preset:{raw}"
    raise ValueError(f"No animation {raw!r} for a {kind} rig. Use: idle, walk, run, dive, climb, jump, slash, shoot, hurt, fall, turn.")


def split_names(raw: Any, limit: int = 10) -> list[str]:
    items = raw if isinstance(raw, list) else re.split(r"[,\n;]+", str(raw or ""))
    out: list[str] = []
    for item in items:
        name = str(item or "").strip()
        if name and name not in out:
            out.append(name)
    return out[:limit]


def credit_gate(confirm_spend: bool, credits: int, label: str) -> str | None:
    """Hard spend lock: a paid Tripo job runs only with confirm_spend=true after a yes."""
    if int(credits or 0) <= 0 or confirm_spend:
        return None
    return (
        f"Error: CREDIT GATE — Tripo {label} costs ~{credits} credits (1 credit = $0.01). "
        "1) Call tripo_balance. "
        "2) Call ducky_ask_user with a yes/no spend question that names the job and the ~credit cost — "
        "never ask only in chat text. "
        "3) Only if they approve: call again with confirm_spend=true. Do not invent approval."
    )


def format_balance_detail(balance: dict[str, Any]) -> str:
    bal = balance.get("balance")
    if bal is None:
        return "Connected"
    frozen = balance.get("frozen") or 0
    return f"Connected — {bal:g} credits" + (f" ({frozen:g} held by running jobs)" if frozen else "")


def test_api_key(api_key: str = "") -> dict[str, Any]:
    """Settings → Test: GET /account/balance with a draft or saved key."""
    key = (api_key or "").strip()
    if not key:
        return {"ok": False, "detail": "Paste a Tripo API key first"}
    try:
        return {"ok": True, "detail": format_balance_detail(TripoClient(api_key=key).balance())}
    except TripoError as exc:
        return {"ok": False, "detail": str(exc)}


test_api_key.__test__ = False  # Settings helper; pytest must not collect this
