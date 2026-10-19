"""Optional Blender MCP socket client for tripo_import_to_blender.

Talks to localhost:9876 when Blender + BlenderMCP addon are listening.
Does not require the Blender Store plugin — only the addon socket.
"""

from __future__ import annotations

import json
import logging
import socket
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

log = logging.getLogger("uefn.plugin.tripo.blender_import")

_IMPORT_OPS = {
    ".glb": "bpy.ops.import_scene.gltf",
    ".gltf": "bpy.ops.import_scene.gltf",
    ".fbx": "bpy.ops.import_scene.fbx",
    ".obj": "bpy.ops.wm.obj_import",
    ".stl": "bpy.ops.wm.stl_import",
}


def import_code(local_path: str) -> str:
    """bpy snippet that imports one GLB/GLTF/FBX/OBJ/STL file."""
    op = _IMPORT_OPS.get(Path(local_path).suffix.lower())
    if not op:
        raise ValueError(f"Blender import takes .glb/.gltf/.fbx/.obj/.stl, not {Path(local_path).suffix or '(none)'}")
    return f"import bpy\n{op}(filepath={local_path!r})\n'imported'\n"

DEFAULT_HOST = "localhost"
DEFAULT_PORT = 9876
SOCKET_TIMEOUT_S = 180.0


@dataclass
class BlenderConnection:
    host: str = DEFAULT_HOST
    port: int = DEFAULT_PORT
    sock: socket.socket | None = field(default=None, repr=False)

    def connect(self) -> bool:
        if self.sock is not None:
            return True
        try:
            self.sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            self.sock.connect((self.host, self.port))
            return True
        except OSError as exc:
            log.warning("connect %s:%s failed: %s", self.host, self.port, exc)
            self.sock = None
            return False

    def disconnect(self) -> None:
        if self.sock is None:
            return
        try:
            self.sock.close()
        except OSError:
            pass
        self.sock = None

    def receive_full_response(self, sock: socket.socket, buffer_size: int = 8192) -> bytes:
        chunks: list[bytes] = []
        sock.settimeout(SOCKET_TIMEOUT_S)
        while True:
            try:
                chunk = sock.recv(buffer_size)
            except socket.timeout as exc:
                if chunks:
                    break
                raise TimeoutError("Timeout waiting for Blender response") from exc
            if not chunk:
                if not chunks:
                    raise ConnectionError("Connection closed before receiving any data")
                break
            chunks.append(chunk)
            data = b"".join(chunks)
            try:
                json.loads(data.decode("utf-8"))
                return data
            except json.JSONDecodeError:
                continue
        if not chunks:
            raise ConnectionError("No data received")
        data = b"".join(chunks)
        json.loads(data.decode("utf-8"))
        return data

    def send_command(self, command_type: str, params: dict[str, Any] | None = None) -> dict[str, Any]:
        if self.sock is None and not self.connect():
            raise ConnectionError(
                f"Open Blender with BlenderMCP addon listening on {self.host}:{self.port}. "
                "Install/enable the Blender Store plugin once to deploy the addon, or enable "
                "Blender MCP manually — then Connect in the N-panel."
            )
        assert self.sock is not None
        command = {"type": command_type, "params": params or {}}
        try:
            self.sock.sendall(json.dumps(command).encode("utf-8"))
            self.sock.settimeout(SOCKET_TIMEOUT_S)
            response_data = self.receive_full_response(self.sock)
            response = json.loads(response_data.decode("utf-8"))
            if response.get("status") == "error":
                raise RuntimeError(response.get("message") or "Unknown error from Blender")
            result = response.get("result", {})
            return result if isinstance(result, dict) else {"result": result}
        except (ConnectionError, BrokenPipeError, ConnectionResetError, OSError) as exc:
            self.sock = None
            raise ConnectionError(f"Connection to Blender lost: {exc}") from exc
        except TimeoutError:
            self.sock = None
            raise


def execute_code(code: str) -> dict[str, Any]:
    """Run bpy code in the live Blender session (one-shot connection)."""
    conn = BlenderConnection()
    try:
        return conn.send_command("execute_code", {"code": code})
    finally:
        conn.disconnect()
