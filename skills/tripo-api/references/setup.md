---
description: "Set up Tripo in UEFN Ducky: install and enable the plugin, paste and test the API key, pick defaults, optional Blender and UEFN import"
metadata:
  label: "Setup"
---

# Tripo setup

1. Store → Install **Tripo** → Enable.
2. Settings → **Tripo** → paste the API key (`tsk_…` from https://developers.tripo3d.ai → API Keys) → **Test** (shows the credit balance).
3. Optional: **Defaults** — 3D model (v3.1 best quality; P1/P2 clean low-poly), texture quality, image model.
4. Opt in the `tripo_*` tools for the chat. Workflows show the **Tripo** node group.
5. Optional Blender: Blender Store plugin once (deploys the add-on), open Blender, Connect on port `9876`.
6. Optional UEFN: UEFN open with the Ducky listener online for `tripo_import_to_uefn` / Send to UEFN.

The key is stored encrypted as `tripo_api_key` on this device. Credits: 1 credit = $0.01, bought at developers.tripo3d.ai → Billing. Failed or cancelled jobs are refunded.
