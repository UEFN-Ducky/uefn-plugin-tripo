"""Tripo — Store desktop plugin: Tripo AI API tools on the shared uefn-ducky MCP + workflow nodes."""

from __future__ import annotations

from . import nodes, tools

PLUGIN_ID = "tripo"


def register(api) -> None:
    tools.download_root(api)
    tools.register_tools(api)
    nodes.register_nodes(api)
    api.log("tripo workflow nodes registered")
