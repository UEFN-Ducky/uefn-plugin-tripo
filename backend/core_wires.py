"""Run the Ducky core's own checks on the character bundle: python core_wires.py <ducky_app dir>.

Needs the app's source (its `backend` package), so test_tripo runs it in a subprocess when
DUCKY_APP_DIR points at it; exit code 1 and one line per problem otherwise."""

from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def problems(app_dir: str) -> list[str]:
    sys.path.insert(0, app_dir)
    from backend.automations import catalog, pins
    from backend.automations.bundles import clean_bundle

    manifest = json.loads((ROOT / "plugin.json").read_text(encoding="utf-8"))
    auto = manifest["contributes"]["automations"]
    row = next(t for t in auto["templates"] if t["id"] == "tripo-character")
    bundle = clean_bundle(row["bundle"])
    specs = dict(catalog.node_specs())
    for node in auto["nodes"]:
        specs.setdefault(node["id"], {**node, "type": node["id"]})
    sigs: dict[str, dict] = {}
    for wf in bundle["workflows"]:
        nodes = wf["graph"]["nodes"]
        start = next((n for n in nodes if n["type"] == "flow.input"), None)
        rets = [r for n in nodes if n["type"] == "flow.output" for r in n["config"]["outputs"]]
        sigs[wf["key"]] = {
            "inputs": [{"name": r["name"], "type": r.get("type", "any"), "default": ""} for r in (start["config"]["inputs"] if start else [])],
            "outputs": [r["name"] for r in rets],
            "output_types": {r["name"]: r.get("type", "any") for r in rets},
        }
    from backend.automations.expr import compile_expr, evaluate

    out: list[str] = []
    spec_nodes = {n["id"]: n for n in next(w for w in bundle["workflows"] if w["key"] == "spec")["graph"]["nodes"]}
    front = spec_nodes["fr"]["config"]["template"]
    for palette, gear in ((None, []), ("", None), ("red, black, grey", ["a backpack", "a lantern"])):
        text = front.replace("{{palette}}", evaluate(spec_nodes["pal"]["config"]["expression"], {"palette": palette}))
        text = text.replace("{{gear}}", evaluate(spec_nodes["gx"]["config"]["expression"], {"gear": gear}))
        for bad in ("Gear: [", "palette: .", "Gear: .", "None", "null", "{{"):
            if bad in text.replace("character.", "character. ", 1) and not (bad == "{{" and "{{name}}" in text):
                out.append(f"spec: front prompt for palette={palette!r} gear={gear!r} contains {bad!r}")
        if gear and "Gear: a backpack, a lantern." not in text or palette and "Color palette: red, black, grey." not in text:
            out.append(f"spec: front prompt lost its palette or gear: {text}")
    for wf in bundle["workflows"]:
        for node in wf["graph"]["nodes"]:
            if node["type"] in ("logic.expression", "logic.if"):
                try:
                    compile_expr(node["config"]["expression"])
                except ValueError as exc:
                    out.append(f"{wf['key']}: {node['id']}: {exc}")
        graph = json.loads(json.dumps(wf["graph"]))
        for node in graph["nodes"]:
            if node["type"] not in specs:
                out.append(f"{wf['key']}: unknown node type {node['type']}")
            if node["type"] == "workflow.call":
                node["config"]["workflow_id"] = node["config"]["workflow_id"].lstrip("@")
        out += [f"{wf['key']}: {p}" for p in pins.check_wires(graph, specs, sigs.get)]
    return out


if __name__ == "__main__":
    found = problems(sys.argv[1])
    print("\n".join(found) or "clean")
    sys.exit(1 if found else 0)
