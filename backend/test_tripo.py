"""Self-check for the Tripo plugin: a fake Tripo API, no network, no credits."""

from __future__ import annotations

import io
import json
import urllib.error
from pathlib import Path
from typing import Any

import pytest

try:
    from . import nodes, tools, tripo as t
    from . import register
except ImportError:  # run as a plain file
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
    from backend import nodes, register, tools, tripo as t

ROOT = Path(__file__).resolve().parents[1]
PNG = b"\x89PNG\r\n\x1a\n" + b"\0" * 32
GLB = b"glTF\x02\0\0\0" + b"\0" * 32
FBX = b"Kaydara FBX Binary  \0" + b"\0" * 32
WEBP = b"RIFF\0\0\0\0WEBPVP8 " + b"\0" * 32


class _Resp(io.BytesIO):
    def __enter__(self):
        return self

    def __exit__(self, *exc):
        return False


class FakeTripo:
    """Routes urllib requests like openapi.tripo3d.ai/v3 + its CDN would."""

    def __init__(self) -> None:
        self.created: list[tuple[str, dict[str, Any]]] = []
        self.tasks: dict[str, dict[str, Any]] = {}
        self.cdn_headers: list[dict[str, str]] = []
        self.fail_next: list[tuple[int, dict[str, Any]]] = []
        self.uploads = 0

    def _envelope(self, data: Any) -> _Resp:
        return _Resp(json.dumps({"code": 0, "status": "success", "data": data}).encode())

    def output_for(self, kind: str, tid: str, payload: dict[str, Any]) -> dict[str, Any]:
        cdn = f"https://cdn.example/{tid}"
        if kind == "rig_check":
            return {"riggable": True, "rig_type": "quadruped"}
        if kind in ("text_to_image", "image_to_image"):
            return {"generated_image_url": f"{cdn}/image.png?sig=1"}
        if kind in ("image_to_multiview", "edit_multiview"):
            return {v + "_view_url": f"{cdn}/{v}.png" for v in t.VIEWS}
        if kind == "smart_uv":
            return {"model_url": f"{cdn}/model.glb", "uv_render_url": f"{cdn}/uv.png"}
        if kind in ("rig", "retarget") and payload.get("out_format") == "fbx":
            return {"model_url": f"{cdn}/rigged.fbx?sig=2"}
        return {"model_url": f"{cdn}/model.glb?sig=1", "rendered_image_url": f"{cdn}/preview.webp"}

    def __call__(self, req, timeout):  # noqa: ANN001 — urllib.request.Request
        url = req.full_url
        if url.startswith("https://cdn.example/"):
            self.cdn_headers.append(dict(req.header_items()))
            path = url.split("?")[0]
            body = GLB if path.endswith(".glb") else FBX if path.endswith(".fbx") else WEBP if path.endswith(".webp") else PNG
            return _Resp(body)
        assert req.get_header("Authorization") == "Bearer tsk_test"
        if self.fail_next:
            code, body = self.fail_next.pop(0)
            raise urllib.error.HTTPError(url, code, "fail", {}, io.BytesIO(json.dumps(body).encode()))
        path = url.removeprefix(t.BASE_URL)
        if path == "/account/balance":
            return self._envelope({"balance": 1234.5, "frozen": 20})
        if path.startswith("/account/usage"):
            return self._envelope([{"task_id": "task_1", "type": "text_to_model", "credits_consumed": 20.0}])
        if path == "/files":
            self.uploads += 1
            assert req.get_header("Content-type").startswith("multipart/form-data; boundary=")
            return self._envelope({"file_token": f"file_{self.uploads}"})
        if path.startswith("/tasks/"):
            tid = path.rsplit("/", 1)[-1]
            return self._envelope(self.tasks[tid])
        kind = next(k for k, p in t.ENDPOINTS.items() if p == path)
        payload = json.loads(req.data.decode())
        tid = f"task_{len(self.created) + 1}"
        self.created.append((kind, payload))
        self.tasks[tid] = {"task_id": tid, "type": kind, "status": "success", "progress": 100, "input": payload,
                           "output": self.output_for(kind, tid, payload), "credits_consumed": 20.0}
        return self._envelope({"task_id": tid, "type": kind, "status": "queued"})


@pytest.fixture
def fake(monkeypatch, tmp_path):
    server = FakeTripo()
    monkeypatch.setattr(t, "_urlopen", server)
    monkeypatch.setattr(t.time, "sleep", lambda _s: None)
    monkeypatch.setattr(t, "plugin_prefs", lambda: {})
    monkeypatch.setitem(tools._DOWNLOADS, "root", tmp_path / "downloads")
    (tmp_path / "downloads").mkdir()
    monkeypatch.setitem(nodes._STATE, "client", lambda: t.TripoClient(api_key="tsk_test"))
    return server


class FakeApi:
    def __init__(self, tmp: Path) -> None:
        self.tools: dict[str, Any] = {}
        self.nodes: dict[str, Any] = {}
        self.tmp = tmp

    def tool(self, name: str, intent: str = ""):
        def deco(fn):
            self.tools[name] = fn
            return fn
        return deco

    def register_secret_test(self, key, fn):
        self.secret_test = (key, fn)

    def register_automation_node(self, node_type, handler):
        self.nodes[node_type] = handler

    def local_dir(self, name=""):
        return str(self.tmp / name)

    def media_url(self, path):
        return ""

    def log(self, message):
        pass


@pytest.fixture
def api(fake, tmp_path, monkeypatch):
    fapi = FakeApi(tmp_path)
    monkeypatch.setattr(tools.t, "_api_key", lambda: "tsk_test")
    register(fapi)
    return fapi


# --------------------------------------------------------------------------- builders


def test_model_options_rules() -> None:
    opts = t.model_options(model_version="v3.1-20260211")
    assert opts == {"model": "v3.1-20260211", "texture": True, "pbr": True}
    assert t.model_options(model_version="v3.0-20250812", texture="none")["texture"] is False
    fast = t.model_options(model_version="v3.0-20250812", texture_quality="fast")
    assert fast["texture_version"] == t.FAST_TEXTURE_VERSION
    with pytest.raises(ValueError, match="v3.0 or newer"):
        t.model_options(model_version="v2.5-20250123", quad=True)
    with pytest.raises(ValueError, match="P series"):
        t.model_options(model_version="P1-20260311", smart_low_poly=True)
    assert t.model_options(model_version="P2-20260801", quad=True)["quad"] is True
    with pytest.raises(ValueError, match="untextured"):
        t.model_options(model_version="v3.1-20260211", generate_parts=True)
    parts = t.model_options(model_version="v3.1-20260211", generate_parts=True, texture="none")
    assert parts["generate_parts"] is True
    with pytest.raises(ValueError):
        t.model_options(model_version="v9")


def test_credit_estimates() -> None:
    assert t.estimate_model_credits("text_to_model", {"texture": False, "pbr": False}) == 10
    assert t.estimate_model_credits("image_to_model", {"texture": True, "pbr": True}) == 30
    hd = {"texture": True, "pbr": True, "texture_quality": "detailed", "geometry_quality": "detailed", "quad": True}
    assert t.estimate_model_credits("text_to_model", hd) == 20 + 10 + 20 + 5
    assert t.estimate_image_credits("seedream_v4") == 5
    assert t.estimate_image_credits("banana2", "4K") == 15
    assert t.estimate_image_credits("chat_image_2.5_flare", "1024x1024", "max") == 30
    assert t.convert_is_advanced({"format": "FBX"}) is False
    assert t.convert_is_advanced({"format": "FBX", "pivot_to_center_bottom": True}) is True


def test_image_options_rules() -> None:
    assert t.image_options(model="banana2", aspect_ratio="16:9")["aspect_ratio"] == "16:9"
    with pytest.raises(ValueError, match="banana"):
        t.image_options(model="seedream_v4", aspect_ratio="16:9")
    with pytest.raises(ValueError, match="chat_image"):
        t.image_options(model="banana", quality="high")
    clear = t.image_options(model="chat_image_2.5_sunburst", background="transparent", output_format="jpeg")
    assert clear["output_format"] == "png"


def test_animation_ids_and_rig_versions() -> None:
    assert t.animation_id("walk") == "preset:biped:walk"
    assert t.animation_id("greet") == "preset:biped:greet_01"
    assert t.animation_id("Walk", "v2.5-20260210") == "preset:walk"
    assert t.animation_id("walk", "v2.5-20260210", "quadruped") == "preset:quadruped:walk"
    with pytest.raises(ValueError):
        t.animation_id("dance_01", "v2.5-20260210")
    assert t.rig_version_for("biped", "tripo") == "v1.0-20240301"
    assert t.rig_version_for("quadruped", "tripo") == "v2.5-20260210"
    assert t.rig_version_for("biped", "unreal") == "v3.0-20260909"
    with pytest.raises(ValueError):
        t.rig_version_for("biped", "unreal", "v1.0-20240301")


def test_animation_aliases() -> None:
    assert t.animation_id("bite", "v2.5-20260210", "quadruped") == "preset:slash"
    assert t.animation_id("Attack", "v2.5-20260210", "biped") == "preset:slash"
    assert t.animation_id("walk", "v2.5-20260210", "quadruped") == "preset:quadruped:walk"


def test_parse_task_and_links() -> None:
    ok = t.parse_task({"task_id": "x", "status": "success",
                       "output": {"rendered_image_url": "https://c/p.webp", "model_url": "https://c/m.glb",
                                  "views": {"front_view_url": "https://c/f.png"}}})
    assert ok["finished"] and not ok["failed"]
    assert [r["key"] for r in ok["results"]][0] == "model_url"
    assert any(r["key"] == "views.front_view_url" for r in ok["results"])
    banned = t.parse_task({"status": "failed", "error_code": 2008})
    assert banned["failed"] and "content policy" in banned["failure_reason"]
    assert t.parse_task({"status": "running"})["failed"] is False
    assert t.parse_task({"status": "weird"})["failed"] is True
    rig = t.parse_task({"status": "success", "output": {"riggable": True, "rig_type": "avian"}})
    assert rig["riggable"] is True and rig["rig_type"] == "avian"


def test_file_helpers(tmp_path) -> None:
    assert t.sniff_ext(GLB) == ".glb" and t.sniff_ext(FBX) == ".fbx" and t.sniff_ext(PNG) == ".png"
    assert t.sniff_ext(WEBP) == ".webp" and t.sniff_ext(b"PK\x03\x04") == ".zip"
    assert t.url_ext("https://c/a/model.fbx?sig=1") == ".fbx" and t.url_ext("https://c/a/blob") == ""
    assert t.looks_like_path(r"C:\x\a.png") and t.looks_like_path("a.glb") and not t.looks_like_path("task_abc123")
    body, ctype = t.multipart_body("file", 'a"b.png', b"DATA", "image/png")
    assert b'filename="a_b.png"' in body and b"DATA" in body and ctype.startswith("multipart/form-data")
    assert "CREDIT GATE" in (t.credit_gate(False, 20, "x") or "") and t.credit_gate(True, 20, "x") is None
    assert t.credit_gate(False, 0, "free") is None
    zpath = tmp_path / "m.zip"
    import zipfile

    with zipfile.ZipFile(zpath, "w") as zf:
        zf.writestr("model.obj", "o x")
        zf.writestr("../evil.txt", "no")
    out = t.safe_extract(zpath, tmp_path / "m")
    assert [Path(p).name for p in out] == ["model.obj"]
    assert not (tmp_path / "evil.txt").exists()


def test_api_key_empty() -> None:
    res = t.test_api_key("")
    assert res["ok"] is False and "Paste" in res["detail"]


# --------------------------------------------------------------------------- client


def test_client_flow(fake, tmp_path) -> None:
    c = t.TripoClient(api_key="tsk_test")
    assert c.balance() == {"balance": 1234.5, "frozen": 20.0}
    assert c.usage(5)[0]["task_id"] == "task_1"
    img = tmp_path / "pic.png"
    img.write_bytes(PNG)
    assert c.resolve(str(img)) == "file_1"
    assert c.resolve("task_abc123") == "task_abc123"
    assert c.resolve("https://x.example/a.png") == "https://x.example/a.png"
    with pytest.raises(t.TripoError, match="not found"):
        c.resolve(str(tmp_path / "missing.glb"))
    done = c.run("text_to_model", {"prompt": "x", "model": t.DEFAULT_MODEL}, tmp_path / "out")
    names = sorted(Path(p).name for p in done["downloaded"])
    assert names == ["model.glb", "preview.webp"]
    assert all("Authorization" not in h for h in fake.cdn_headers)  # the key never goes to the CDN


def test_client_errors_and_retry(fake) -> None:
    c = t.TripoClient(api_key="tsk_test")
    fake.fail_next = [(429, {"code": 1007, "message": "slow down"})]
    assert c.balance()["balance"] == 1234.5  # retried after the 429
    fake.fail_next = [(401, {"code": 2, "message": "bad key"})]
    with pytest.raises(t.TripoError, match="rejected the API key"):
        c.balance()
    fake.fail_next = [(403, {"code": 2010, "message": "insufficient credit"})]
    with pytest.raises(t.TripoError, match="not enough credits"):
        c.balance()
    with pytest.raises(t.TripoError, match="API key not set"):
        t.TripoClient(api_key="")


# --------------------------------------------------------------------------- tools


def test_tools_gate_and_run(api, fake) -> None:
    blocked = api.tools["tripo_text_to_3d"](prompt="a duck")
    assert blocked.startswith("Error: CREDIT GATE") and "~20 credits" in blocked
    assert not fake.created
    res = json.loads(api.tools["tripo_text_to_3d"](prompt="a duck", confirm_spend=True))
    assert res["finished"] and res["downloaded"]
    kind, payload = fake.created[0]
    assert kind == "text_to_model" and payload["model"] == t.DEFAULT_MODEL and payload["prompt"] == "a duck"
    rig = json.loads(api.tools["tripo_rig"](source=res["task_id"], confirm_spend=True))
    assert rig["rig_version"] == "v1.0-20240301" and fake.created[-1][1]["spec"] == "tripo"
    anim = json.loads(api.tools["tripo_animate"](rig_task_id=rig["task_id"], animations="walk, run", confirm_spend=True))
    assert fake.created[-1][1]["animations"] == ["preset:biped:walk", "preset:biped:run"]
    assert anim["animations"] == ["preset:biped:walk", "preset:biped:run"]
    assert json.loads(api.tools["tripo_balance"]())["balance"] == 1234.5
    check = json.loads(api.tools["tripo_rig_check"](source="task_1"))
    assert check["riggable"] is True and check["rig_type"] == "quadruped"
    nowait = json.loads(api.tools["tripo_convert"](source="task_1", format="glb", confirm_spend=True, wait=False))
    assert nowait["status"] == "queued" and fake.created[-1][1]["format"] == "GLTF"
    assert "P series" in api.tools["tripo_text_to_3d"](prompt="x", model_version="P1-20260311", smart_low_poly=True)


def test_tools_for_the_builtin_nodes(api, fake, tmp_path) -> None:
    # Rig "auto": the free rig check picks the skeleton (quadruped here) and so the engine.
    rig = json.loads(api.tools["tripo_rig"](source="task_abc123", rig_type="auto", confirm_spend=True))
    assert [k for k, _ in fake.created] == ["rig_check", "rig"] and rig["rig_type"] == "quadruped"
    assert fake.created[-1][1]["model"] == "v2.5-20260210" and "spec" not in fake.created[-1][1]
    # Animate with no engine given reads it from the rig job's own request.
    json.loads(api.tools["tripo_animate"](rig_task_id=rig["task_id"], animations="walk", confirm_spend=True))
    assert fake.created[-1][1]["animation"] == "preset:quadruped:walk"
    # Multi-view from a list (front, left, …) as the built-in node sends it.
    views = []
    for name in ("front", "left"):
        (tmp_path / f"{name}.png").write_bytes(PNG)
        views.append(str(tmp_path / f"{name}.png"))
    json.loads(api.tools["tripo_multiview_to_3d"](images=json.dumps(views), confirm_spend=True))
    assert [list(v) for v in fake.created[-1][1]["inputs"]] == [["front"], ["left"]]
    # Quads from the Optimize node's Topology, and a style picture alone paints from that picture.
    json.loads(api.tools["tripo_retopology"](source="task_abc123", topology="quad", confirm_spend=True))
    assert fake.created[-1][1]["quad"] is True
    json.loads(api.tools["tripo_texture"](source="task_abc123", style_image=views[0], confirm_spend=True))
    assert fake.created[-1][1]["texture_prompt"] == {"image": f"file_{fake.uploads}"}


# --------------------------------------------------------------------------- nodes


def _ctx(inputs: dict[str, Any], **config: Any) -> dict[str, Any]:
    return {"config": config, "inputs": inputs, "payload": {}, "artifact_dir": ""}


def test_nodes_gate_and_chain(api, fake) -> None:
    gated = nodes.text_to_3d(_ctx({"prompt": "a chest"}))
    assert gated["ok"] is False and "Spend credits" in gated["error"] and not fake.created
    made = nodes.text_to_3d(_ctx({"prompt": "a chest", "polycount": 9000}, spend=True, model="v3.0-20250812", quad=True))
    assert made["ok"] and made["mesh"]["kind"] == "mesh" and made["mesh"]["task_id"] == "task_1"
    assert made["mesh"]["stage"] == "model" and made["mesh"]["remote"].startswith("https://")
    assert fake.created[0][1]["face_limit"] == 9000 and fake.created[0][1]["quad"] is True
    rigged = nodes.rig(_ctx({"mesh": made["mesh"]}, spend=True, rig_type="auto"))
    assert rigged["ok"] and rigged["rig_type"] == "quadruped"
    assert [k for k, _ in fake.created[1:]] == ["rig_check", "rig"]
    assert fake.created[2][1]["input"] == "task_1" and fake.created[2][1]["model"] == "v2.5-20260210"
    assert rigged["mesh"]["stage"] == "rig" and rigged["mesh"]["path"].endswith(".fbx")
    anims = nodes.animate(_ctx({"mesh": rigged["mesh"], "animations": "walk"}, spend=True))
    assert anims["ok"] and len(anims["meshes"]) == 1
    assert fake.created[-1][1]["animation"] == "preset:quadruped:walk"
    wrong = nodes.animate(_ctx({"mesh": made["mesh"]}, spend=True))
    assert wrong["ok"] is False and "Auto Rig" in wrong["error"]


def test_nodes_local_files_and_views(api, fake, tmp_path) -> None:
    local = tmp_path / "prop.glb"
    local.write_bytes(GLB)
    ref = {"kind": "mesh", "path": str(local), "name": "prop.glb"}
    low = nodes.retopology(_ctx({"mesh": ref, "polycount": 5000}, spend=True, smart_uv=True))
    assert low["ok"] and fake.uploads == 1
    assert fake.created[-1][1] == {"input": "file_1", "model": "v3.0", "face_limit": 5000, "smart_uv": True}
    pic = tmp_path / "front.png"
    pic.write_bytes(PNG)
    views = nodes.image_to_multiview(_ctx({"image": {"kind": "image", "path": str(pic)}}, spend=True))
    assert views["ok"] and [v["view"] for v in views["views"]] == list(t.VIEWS)
    model = nodes.multiview_to_3d(_ctx({"views": views["views"]}, spend=True))
    assert model["ok"] and fake.created[-1][1]["inputs"] == [{"task_id": views["task_id"]}]
    uv = nodes.smart_uv(_ctx({"mesh": low["mesh"]}, spend=True))
    assert uv["ok"] and uv["uv"]["kind"] == "image"
    missing = nodes.texture(_ctx({"mesh": {"kind": "mesh", "path": str(tmp_path / "gone.glb")}}, spend=True))
    assert missing["ok"] is False and "isn't on this PC" in missing["error"]
    assert nodes.balance(_ctx({}))["balance"] == 1234.5


# --------------------------------------------------------------------------- manifest


def test_manifest_matches_code(api) -> None:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    contrib = manifest["contributes"]
    declared = {row["id"] for row in contrib["automations"]["nodes"]}
    assert declared == set(nodes.HANDLERS) == set(api.nodes)
    for row in contrib["automations"]["image_generators"]:
        assert row["tool"] in api.tools and row["args"]["model"] in t.IMAGE_MODELS
    import inspect

    builtin_pins = {"mesh.generate": {"prompt"}, "mesh.from_image": {"image", "prompt"}, "mesh.multi_view": {"images"},
                    "mesh.retexture": {"mesh", "prompt", "style_image"}, "mesh.remesh": {"mesh", "polycount"},
                    "mesh.uv_unwrap": {"mesh"}, "mesh.convert": {"mesh"}, "mesh.rig": {"mesh", "height"},
                    "mesh.animate": {"mesh", "actions"}, "image.edit": {"image", "prompt"}}
    for row in contrib["automations"]["media_backends"]:
        params = set(inspect.signature(api.tools[row["tool"]]).parameters)
        assert set(row["pins"]) <= builtin_pins[row["node"]], row["id"]
        for arg in [*row["pins"].values(), *row.get("task_args", {}).values(), *row.get("cfg", {}).values(),
                    *row.get("args", {}), *(f["id"] for f in row.get("config_fields", []))]:
            assert arg in params, (row["id"], arg)
    for name in contrib["agent.tools"]["plan_tools"]:
        assert name in api.tools
    builtin = {"input.text", "input.image", "input.mesh", "mesh.set_origin", "uefn.import", "util.preview"}
    for tmpl in contrib["automations"]["templates"]:
        assert tmpl["requires_plugins"] == ["tripo"]
        if "bundle" in tmpl:
            continue  # test_character_bundle
        ids = {n["id"] for n in tmpl["graph"]["nodes"]}
        for node in tmpl["graph"]["nodes"]:
            assert node["type"] in builtin or node["type"] in declared, node["type"]
        for edge in tmpl["graph"]["edges"]:
            assert edge["source"] in ids and edge["target"] in ids and edge["kind"] == "data"
    assert api.secret_test[0] == manifest["secret_keys"][0] == t.SECRET_KEY
    for path in (ROOT / "skills" / "tripo-api").rglob("*.md"):
        assert path.read_text(encoding="utf-8").startswith("---\n"), path


# Core node types the character bundle uses, with the pins its wires may name (the core catalog is the source).
_CORE_PINS: dict[str, tuple[set[str], set[str]]] = {
    "llm.vision": ({"image", "prompt"}, {"text"}), "image.generate": ({"prompt"}, {"image"}),
    "image.edit": ({"image", "prompt"}, {"image"}), "image.remove_bg": ({"image"}, {"image"}),
    "uefn.import": ({"file", "folder"}, {"asset", "assets"}), "uefn.open_project": ({"project"}, set()),
    "flow.choose": ({"images", "message"}, {"choice", "note"}), "flow.repeat": ({"until"}, {"attempt", "passed"}),
    "notify.message": ({"message"}, {"sent"}), "input.text": (set(), {"text"}), "list.make": (set(), {"list"}),
    "logic.if": (set(), {"result"}), "logic.expression": (set(), {"result"}), "text.template": (set(), {"text"}),
    "tool.call": (set(), {"result", "text"}), "pipeline.finish": (set(), set()),
    "mesh.rig": ({"mesh", "height", "body"}, {"mesh", "files"}), "mesh.animate": ({"mesh", "actions"}, {"mesh", "meshes", "files"}),
}


_MORE_CORE_TYPES = {"flow.input", "flow.output", "llm.extract", "flow.foreach", "workflow.call", "start.chat", "mesh.multi_view",
                    "mesh.from_image", "mesh.remesh", "mesh.fit_box", "mesh.set_origin", "mesh.render", "mesh.info"}


def _pins_of(node: dict[str, Any]) -> tuple[set[str], set[str]] | None:
    if node["type"] in _MORE_CORE_TYPES - {"flow.input", "flow.output", "llm.extract"}:
        return None  # wires there are checked by the core (test_character_bundle_in_core)
    cfg = node.get("config") or {}
    names = {str(n) for n in cfg.get("names") or []}
    if node["type"] == "flow.input":
        return set(), {r["name"] for r in cfg["inputs"]}
    if node["type"] == "flow.output":
        return {r["name"] for r in cfg["outputs"]}, set()
    if node["type"] == "llm.extract":
        return {"text"}, names | {"data"}
    ins, outs = _CORE_PINS[node["type"]]
    return (ins | names, outs) if node["type"] in ("text.template", "logic.expression", "list.make") else (ins, outs)


def test_character_bundle() -> None:
    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    row = next(t_ for t_ in manifest["contributes"]["automations"]["templates"] if t_["id"] == "tripo-character")
    bundle = row["bundle"]
    keys = [w["key"] for w in bundle["workflows"]]
    assert len(keys) == len(set(keys)) and set(keys) == {"character", "spec", "sheet", "make3d", "rig", "gear", "ship"}
    declared = {r["id"] for r in manifest["contributes"]["automations"]["nodes"]}
    for wf in bundle["workflows"]:
        nodes = {n["id"]: n for n in wf["graph"]["nodes"]}
        for node in nodes.values():
            assert node["type"] in _CORE_PINS or node["type"] in _MORE_CORE_TYPES or node["type"] in declared, (wf["key"], node["type"])
            if node["type"] == "workflow.call":
                assert node["config"]["workflow_id"].lstrip("@") in keys
        fed: set[tuple[str, str]] = set()
        for edge in wf["graph"]["edges"]:
            assert edge["source"] in nodes and edge["target"] in nodes, (wf["key"], edge)
            if edge["kind"] == "data":
                src, dst = _pins_of(nodes[edge["source"]]), _pins_of(nodes[edge["target"]])
                assert src is None or edge["source_pin"] in src[1], (wf["key"], edge)
                assert dst is None or edge["target_pin"] in dst[0], (wf["key"], edge)
                assert (edge["target"], edge["target_pin"]) not in fed, (wf["key"], "two wires into one pin", edge)
                fed.add((edge["target"], edge["target_pin"]))
            else:
                assert edge["kind"] in ("main", "each", "done", "true", "false")


def test_character_bundle_in_core() -> None:
    """The core's own bundle, wire-type and expression checks (needs the app's source: DUCKY_APP_DIR)."""
    import os
    import subprocess
    import sys

    app_dir = os.environ.get("DUCKY_APP_DIR", "")
    if not app_dir or not Path(app_dir, "backend", "automations", "pins.py").is_file():
        pytest.skip("DUCKY_APP_DIR is not set to the Ducky app's source")
    done = subprocess.run([sys.executable, str(ROOT / "backend" / "core_wires.py"), app_dir], capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout + done.stderr
