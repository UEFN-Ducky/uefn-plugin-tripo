# Tripo

Open-source [UEFN-Ducky](https://github.com/UEFN-Ducky/UEFN-Ducky) Store plugin for the [Tripo AI](https://studio.tripo3d.ai) API (v3): generate and process 3D models, pictures, rigs and animations from agents and workflows, then land them in Blender or UEFN.

Desktop plugin id `tripo`. Install or update from **Settings → Store** in the app — do not install from a zip by hand.

## What it does

- **Agent tools** (`tripo_*` on the shared `uefn-ducky` MCP): text / image / multi-view to 3D, image to Gaussian splat, text to image, image edit, image to multi-view, edit multi-view, texture, convert, stylize (LEGO, voxel, Minecraft…), retopology, smart UV, segment and complete parts, rig check, auto rig, animate, plus balance, usage, status, batch status, download, upload and import to Blender / UEFN.
- **Workflow nodes** (the **Tripo** group in Workflows): Text to 3D, Image to 3D, Multi-view to 3D, Image to Splat, Text to Image, Edit Image, Image to Multi-view, Edit Multi-view, Texture Model, Retopology, Smart UV, Segment Parts, Complete Parts, Convert, Stylize, Rig Check, Auto Rig, Animate, Balance. Files carry their Tripo task, so a chain (Text to 3D → Auto Rig → Animate → Send to UEFN) never re-uploads.
- **Text to Image backends** for the built-in Text to Image node (Seedream, Banana, Chat Image).
- **Ready-made workflows**: prompt or picture to a model in UEFN, a rigged and animated character, concept → four views → model, game-ready retopology, repaint, LEGO-style.
- **Settings → Tripo**: API key with Test (shows the balance) and defaults for the 3D model, texture quality and image model.

Paid jobs never run on their own: tools refuse until `confirm_spend=true` (agents ask you first with a panel question), and nodes need **Spend credits** on. 1 credit = $0.01.

## Build

```bash
py scripts/build_zip.py
py scripts/release.py --publish --changelog "…"   # commit + push, zip, upload, publish to the Store
```

`build_zip.py` writes `deploy/tripo-<version>.ducky-plugin.zip` (scripts/, deploy/ and the self-check are not packed).

## Test

```bash
py -m pytest -q --import-mode=importlib backend/test_tripo.py
```

No network and no credits: the self-check fakes Tripo's API.

## Secrets

Never commit keys. The app stores `tripo_api_key` locally (encrypted), not in this package.

## License

MIT. Copyright (c) 2026 Mindful Path Company, LLC. See [LICENSE](LICENSE). Tripo is a trademark of its owners; this plugin is not affiliated with Tripo AI.
