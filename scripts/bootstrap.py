#!/usr/bin/env python3
"""Cross-platform first-run setup for Heaven Agent.

This file intentionally uses only the Python standard library so it can run
before the project environment exists.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import platform
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


ROOT = Path(__file__).resolve().parent.parent
VENV = ROOT / ".venv"
STATE_FILE = VENV / ".heaven-bootstrap.json"
SUPPORTED_MIN = (3, 11)
SUPPORTED_MAX = (3, 13)
COSYVOICE_REPO = "https://github.com/FunAudioLLM/CosyVoice.git"
COSYVOICE_COMMIT = "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc"
MLX_AUDIO_PACKAGE = "mlx-audio-plus==0.1.8"
MLX_MODEL_DIR = "Fun-CosyVoice3-0.5B-2512-8bit"


class BootstrapError(RuntimeError):
    """Raised when the local machine cannot satisfy setup requirements."""


def _write_install_status(
    path: Path | None,
    state: str,
    stage: str,
    message: str,
) -> None:
    if path is None:
        return
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = {
        "state": state,
        "stage": stage,
        "message": message,
        "restart_required": state == "restart_required",
    }
    fd, temporary = tempfile.mkstemp(prefix=".voice-install-", dir=path.parent)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def ensure_supported_python(version: tuple[int, int]) -> None:
    if not (SUPPORTED_MIN <= version <= SUPPORTED_MAX):
        raise BootstrapError(
            f"需要 Python 3.11–3.13，当前为 {version[0]}.{version[1]}。"
        )


def voice_extra_for(system: str, machine: str) -> str:
    if system == "Darwin" and machine.lower() in {"arm64", "aarch64"}:
        return "voice-macos"
    return "voice-cross-platform"


def voice_source_commands(system: str, machine: str, deps_dir: Path) -> list[list[str]]:
    """Return reproducible source setup commands for the selected voice backend."""
    if voice_extra_for(system, machine) == "voice-macos":
        return []
    target = deps_dir / "CosyVoice"
    return [
        ["git", "clone", "--recursive", COSYVOICE_REPO, str(target)],
        ["git", "-C", str(target), "checkout", COSYVOICE_COMMIT],
        ["git", "-C", str(target), "submodule", "update", "--init", "--recursive"],
    ]


def voice_install_commands(
    system: str, machine: str, venv_python: Path
) -> list[list[str]]:
    """Return special installs that must bypass broken upstream metadata."""
    if voice_extra_for(system, machine) != "voice-macos":
        return []
    return [[
        str(venv_python),
        "-m",
        "pip",
        "install",
        "--disable-pip-version-check",
        "--progress-bar",
        "off",
        "--no-deps",
        MLX_AUDIO_PACKAGE,
    ]]


def voice_model_ready(system: str, root: Path) -> bool:
    """Return whether the platform's eagerly managed voice model is complete."""
    if voice_extra_for(system, platform.machine()) != "voice-macos":
        return True
    return (Path(root) / "deps" / MLX_MODEL_DIR / "model.safetensors").is_file()


def voice_model_commands(
    system: str,
    machine: str,
    venv_python: Path,
    root: Path,
) -> list[list[str]]:
    if voice_extra_for(system, machine) != "voice-macos" or voice_model_ready(
        system, root
    ):
        return []
    return [[
        str(venv_python),
        str(Path(root) / "scripts" / "download_voice_model.py"),
        str(Path(root) / "deps" / MLX_MODEL_DIR),
    ]]


def voice_completion(dry_run: bool) -> tuple[str, str, str]:
    if dry_run:
        return "dry_run", "dry-run", "检查完成；dry-run 未修改环境"
    return "restart_required", "complete", "语音组件已安装，请重启 Heaven Agent 生效"


def _version_of(executable: str) -> tuple[int, int] | None:
    try:
        result = subprocess.run(
            [executable, "-c", "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')"],
            check=True,
            capture_output=True,
            text=True,
        )
        major, minor = result.stdout.strip().split(".")
        return int(major), int(minor)
    except (OSError, ValueError, subprocess.CalledProcessError):
        return None


def find_supported_python() -> str:
    candidates = [sys.executable, "python3.13", "python3.12", "python3.11", "python"]
    seen: set[str] = set()
    for candidate in candidates:
        resolved = shutil.which(candidate) if not Path(candidate).is_absolute() else candidate
        if not resolved or resolved in seen:
            continue
        seen.add(resolved)
        version = _version_of(resolved)
        if version and SUPPORTED_MIN <= version <= SUPPORTED_MAX:
            return resolved
    raise BootstrapError(
        "未找到 Python 3.11–3.13。请先安装受支持版本后重新运行启动脚本。"
    )


def _digest(paths: list[Path], voice: bool) -> str:
    digest = hashlib.sha256()
    digest.update(f"voice={voice}".encode())
    for path in paths:
        digest.update(path.name.encode())
        digest.update(path.read_bytes())
    return digest.hexdigest()


def _venv_python() -> Path:
    return VENV / ("Scripts/python.exe" if platform.system() == "Windows" else "bin/python")


def _run(command: list[str], *, cwd: Path = ROOT, dry_run: bool = False) -> None:
    print("+", " ".join(command))
    if dry_run:
        return
    result = subprocess.run(
        command,
        cwd=cwd,
        capture_output=True,
        text=True,
    )
    if result.returncode:
        detail = (result.stderr.strip() or result.stdout.strip())[-2_000:]
        raise BootstrapError(
            f"命令执行失败（退出码 {result.returncode}）：{detail or '没有错误输出'}"
        )


def bootstrap(
    *,
    voice: bool = False,
    skip_node: bool = False,
    dry_run: bool = False,
    status_file: Path | None = None,
) -> Path:
    def report(state: str, stage: str, message: str) -> None:
        print(f"[{stage}] {message}")
        if not dry_run:
            _write_install_status(status_file, state, stage, message)

    report("installing", "environment", "正在检查本地环境")
    python = find_supported_python()
    ensure_supported_python(_version_of(python) or (0, 0))

    inputs = [ROOT / "pyproject.toml"]
    if not skip_node:
        inputs.append(ROOT / "frontend" / "package-lock.json")
    fingerprint = _digest(inputs, voice)

    current_state: dict[str, str] = {}
    if STATE_FILE.exists():
        try:
            current_state = json.loads(STATE_FILE.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            current_state = {}

    venv_python = _venv_python()
    venv_version = _version_of(str(venv_python)) if venv_python.exists() else None
    venv_ok = bool(venv_version and SUPPORTED_MIN <= venv_version <= SUPPORTED_MAX)
    if not venv_ok:
        _run([python, "-m", "venv", "--clear", str(VENV)], dry_run=dry_run)

    install_python = str(venv_python)
    extra = voice_extra_for(platform.system(), platform.machine()) if voice else None
    package = f".[{extra}]" if extra else "."

    if not venv_ok or current_state.get("fingerprint") != fingerprint:
        report("installing", "dependencies", "正在安装运行依赖")
        _run([install_python, "-m", "pip", "install", "--upgrade", "pip"], dry_run=dry_run)
        _run([install_python, "-m", "pip", "install", "-e", package], dry_run=dry_run)

        if voice:
            for command in voice_install_commands(
                platform.system(), platform.machine(), venv_python
            ):
                _run(command, dry_run=dry_run)

        if not skip_node:
            npm = shutil.which("npm")
            if not npm:
                raise BootstrapError("未找到 Node.js/npm，请安装 Node.js 22+。")
            _run([npm, "ci"], cwd=ROOT / "frontend", dry_run=dry_run)

        if voice:
            report("installing", "source", "正在准备语音后端")
            source_commands = voice_source_commands(
                platform.system(), platform.machine(), ROOT / "deps"
            )
            target = ROOT / "deps" / "CosyVoice"
            if source_commands and not target.exists():
                if not shutil.which("git"):
                    raise BootstrapError("安装跨平台语音后端需要 Git。")
                for command in source_commands:
                    _run(command, dry_run=dry_run)

    if voice:
        model_commands = voice_model_commands(
            platform.system(), platform.machine(), venv_python, ROOT
        )
        if model_commands:
            report("installing", "model", "正在下载语音模型，可断点续传")
            for command in model_commands:
                _run(command, dry_run=dry_run)
        if not dry_run and not voice_model_ready(platform.system(), ROOT):
            raise BootstrapError("语音模型校验失败，请重试安装")

    if not dry_run and (not venv_ok or current_state.get("fingerprint") != fingerprint):
        STATE_FILE.write_text(
            json.dumps({"fingerprint": fingerprint, "voice": voice}, indent=2),
            encoding="utf-8",
        )

    ffmpeg = shutil.which("ffmpeg")
    if voice and not ffmpeg:
        print("警告：未找到 ffmpeg；常见音频格式转换将使用兼容性较低的 Python 降级路径。")

    if voice:
        report(*voice_completion(dry_run))
    else:
        print("核心环境已就绪。")
    return venv_python


def main() -> int:
    parser = argparse.ArgumentParser(description="安装 Heaven Agent 本地运行环境")
    parser.add_argument("--voice", action="store_true", help="安装当前平台的可选语音依赖")
    parser.add_argument("--skip-node", action="store_true", help="跳过前端 npm 依赖安装")
    parser.add_argument("--dry-run", action="store_true", help="只显示操作，不修改环境")
    parser.add_argument("--status-file", type=Path, help="将安装阶段写入 JSON 状态文件")
    args = parser.parse_args()
    try:
        bootstrap(
            voice=args.voice,
            skip_node=args.skip_node,
            dry_run=args.dry_run,
            status_file=args.status_file,
        )
        return 0
    except (BootstrapError, subprocess.CalledProcessError) as exc:
        _write_install_status(
            args.status_file,
            "failed",
            "failed",
            f"安装失败：{str(exc)[-2_000:]}",
        )
        print(f"安装失败：{exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
