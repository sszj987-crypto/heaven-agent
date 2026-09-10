#!/usr/bin/env python3
"""Create a double-clickable macOS .app bundle for Heaven Agent.

Run from the repository root with the project virtual environment activated:
    .venv/bin/python -m pip install -e '.[desktop]'
    .venv/bin/python scripts/build_macos_app.py
"""

from __future__ import annotations

import platform
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
FRONTEND = ROOT / "frontend"
OUT = FRONTEND / "out"
APP_NAME = "Heaven Agent"


def run(command: list[str], *, cwd: Path = ROOT) -> None:
    print("+", " ".join(command))
    subprocess.run(command, cwd=cwd, check=True)


def main() -> None:
    if platform.system() != "Darwin":
        raise SystemExit("macOS 应用只能在 macOS 上构建")
    try:
        import PyInstaller  # noqa: F401
    except ImportError as exc:
        raise SystemExit("请先运行: .venv/bin/python -m pip install -e '.[desktop]'") from exc

    run(["npm", "run", "build"], cwd=FRONTEND)
    if not (OUT / "index.html").is_file():
        raise SystemExit("前端静态构建失败：未生成 frontend/out/index.html")

    dist = ROOT / "dist"
    build = ROOT / "build" / "macos-app"
    shutil.rmtree(build, ignore_errors=True)
    run([
        sys.executable, "-m", "PyInstaller",
        "--noconfirm", "--clean", "--windowed",
        "--name", APP_NAME,
        "--distpath", str(dist),
        "--workpath", str(build),
        "--specpath", str(build),
        "--add-data", f"{ROOT / 'config'}:config",
        "--add-data", f"{OUT}:frontend",
        "--collect-all", "chromadb",
        "--collect-all", "sentence_transformers",
        "--collect-all", "tokenizers",
        str(ROOT / "src" / "desktop.py"),
    ])
    print(f"\n完成：{dist / (APP_NAME + '.app')}")
    print("首次打开时，用户数据会保存在 ~/Library/Application Support/Heaven Agent/")


if __name__ == "__main__":
    main()
