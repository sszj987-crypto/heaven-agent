#!/usr/bin/env python3
r"""Build the double-clickable Windows native-window executable.

Run this script on Windows, from a virtual environment with the desktop extra:
    .venv\Scripts\python.exe -m pip install -e ".[desktop]"
    .venv\Scripts\python.exe scripts\build_windows_exe.py
"""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
OUT = FRONTEND / "out"
APP_NAME = "Heaven Agent"


def run(
    command: list[str], *, cwd: Path = ROOT, env: dict[str, str] | None = None
) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, env=env, check=True)


def main() -> None:
    if platform.system() != "Windows":
        raise SystemExit("Windows .exe 只能在 Windows 上构建")
    try:
        import PyInstaller  # noqa: F401
        import webview  # noqa: F401
    except ImportError as exc:
        raise SystemExit('请先运行: .venv\\Scripts\\python.exe -m pip install -e ".[desktop]"') from exc

    frontend_env = os.environ | {"NEXT_PUBLIC_API_URL": ""}
    run(["npm", "run", "build"], cwd=FRONTEND, env=frontend_env)
    if not (OUT / "index.html").is_file():
        raise SystemExit("前端静态构建失败：未生成 frontend/out/index.html")

    dist = ROOT / "dist" / "windows"
    build = ROOT / "build" / "windows-exe"
    shutil.rmtree(build, ignore_errors=True)
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME,
        "--distpath", str(dist),
        "--workpath", str(build),
        "--specpath", str(build),
        "--add-data", f"{ROOT / 'config'};config",
        "--add-data", f"{OUT};frontend",
        "--collect-all", "chromadb",
        "--collect-all", "sentence_transformers",
        "--collect-all", "tokenizers",
        "--collect-all", "webview",
        "--collect-all", "pythonnet",
        str(ROOT / "src" / "desktop.py"),
    ])
    print(f"\n完成：{dist / APP_NAME / (APP_NAME + '.exe')}")
    print("用户数据会保存在 %LOCALAPPDATA%\\Heaven Agent\\")
    print("目标电脑需要 Microsoft Edge WebView2 Runtime；Windows 10/11 通常已预装。")


if __name__ == "__main__":
    main()
