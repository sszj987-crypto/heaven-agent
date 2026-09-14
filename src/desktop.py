"""macOS desktop entry point used by the PyInstaller application bundle."""

from __future__ import annotations

import shutil
import socket
import platform
import sys
import threading
import time
from pathlib import Path
from typing import Any

import uvicorn

from src.main import create_app

APP_NAME = "Heaven Agent"
HOST = "127.0.0.1"


def bundled_root() -> Path:
    """Return PyInstaller's Resources directory, or the source root in dev."""
    if getattr(sys, "frozen", False):
        return Path(sys._MEIPASS)  # type: ignore[attr-defined]
    return Path(__file__).resolve().parent.parent


def user_data_root(
    home: Path | None = None,
    *,
    system: str | None = None,
    local_app_data: str | None = None,
) -> Path:
    """Keep mutable configuration out of a signed desktop application bundle."""
    current_system = system or platform.system()
    if current_system == "Windows":
        if local_app_data:
            return Path(local_app_data) / APP_NAME
        return (home or Path.home()) / "AppData" / "Local" / APP_NAME
    if current_system == "Darwin":
        return (home or Path.home()) / "Library" / "Application Support" / APP_NAME
    return (home or Path.home()) / ".local" / "share" / APP_NAME


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


def find_available_port(host: str = HOST) -> int:
    """Choose an unused loopback port so a development server cannot collide."""
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as candidate:
        candidate.bind((host, 0))
        return int(candidate.getsockname()[1])


def show_native_window(
    webview_module: Any, url: str, *, system: str | None = None
) -> None:
    """Run the native WebView loop on the application's main thread."""
    webview_module.create_window(
        APP_NAME,
        url,
        width=1280,
        height=820,
        min_size=(960, 640),
        background_color="#1c1917",
    )
    start_options: dict[str, object] = {"private_mode": True}
    if (system or platform.system()) == "Windows":
        # Never silently fall back to the deprecated MSHTML / Internet Explorer engine.
        start_options["gui"] = "edgechromium"
    webview_module.start(**start_options)


def run() -> None:
    try:
        import webview
    except ImportError as exc:
        raise RuntimeError("缺少原生窗口组件，请重新构建 Heaven Agent.app") from exc

    resources = bundled_root()
    runtime_root = user_data_root()
    seed_runtime_files(resources, runtime_root)

    port = find_available_port()
    app = create_app(project_root=runtime_root, static_dir=resources / "frontend")
    server = uvicorn.Server(
        uvicorn.Config(app, host=HOST, port=port, log_level="error", access_log=False)
    )
    thread = threading.Thread(target=server.run, name="heaven-agent-api", daemon=True)
    thread.start()
    if not wait_for_port(HOST, port):
        raise RuntimeError(f"Heaven Agent 启动超时，请查看 {runtime_root / 'log'}")
    try:
        show_native_window(webview, f"http://{HOST}:{port}/")
    finally:
        server.should_exit = True
        thread.join(timeout=5)


if __name__ == "__main__":
    run()
