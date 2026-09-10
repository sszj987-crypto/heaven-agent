"""macOS desktop entry point used by the PyInstaller application bundle."""

from __future__ import annotations

import shutil
import socket
import sys
import threading
import time
import webbrowser
from pathlib import Path

import uvicorn

from src.main import create_app

APP_NAME = "Heaven Agent"
HOST = "127.0.0.1"
PORT = 8326


def bundled_root() -> Path:
    """Return PyInstaller's Resources directory, or the source root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def user_data_root(home: Path | None = None) -> Path:
    """Keep mutable configuration out of a signed, read-only .app bundle."""
    return (home or Path.home()) / "Library" / "Application Support" / APP_NAME


def seed_runtime_files(source_root: Path, destination_root: Path) -> None:
    """Copy bundled defaults only once; never overwrite a person's local data."""
    source_config = source_root / "config"
    destination_config = destination_root / "config"
    if not source_config.is_dir():
        raise RuntimeError(f"找不到内置配置: {source_config}")

    destination_root.mkdir(parents=True, exist_ok=True)
    if not destination_config.exists():
        shutil.copytree(source_config, destination_config)
    else:
        # App updates may add new template files.  Existing user edits win.
        for source in source_config.rglob("*"):
            target = destination_config / source.relative_to(source_config)
            if source.is_dir():
                target.mkdir(parents=True, exist_ok=True)
            elif not target.exists():
                shutil.copy2(source, target)
    (destination_root / "data").mkdir(exist_ok=True)
    (destination_root / "log").mkdir(exist_ok=True)


def wait_for_port(host: str, port: int, timeout: float = 20) -> bool:
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        try:
            with socket.create_connection((host, port), timeout=0.2):
                return True
        except OSError:
            time.sleep(0.1)
    return False


def run() -> None:
    resources = bundled_root()
    runtime_root = user_data_root()
    seed_runtime_files(resources, runtime_root)

    app = create_app(project_root=runtime_root, static_dir=resources / "frontend")
    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=PORT, log_level="error", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="heaven-agent-api", daemon=True)
    thread.start()
    if not wait_for_port(HOST, PORT):
        raise RuntimeError("Heaven Agent 启动超时，请查看 ~/Library/Application Support/Heaven Agent/log")
    webbrowser.open_new("http://127.0.0.1:8326/")
    thread.join()


if __name__ == "__main__":
    run()
