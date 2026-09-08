import platform
from pathlib import Path
import sys
import json

import pytest

from scripts.bootstrap import (
    BootstrapError,
    ensure_supported_python,
    _run,
    _write_install_status,
    voice_install_commands,
    voice_completion,
    voice_model_ready,
    voice_model_commands,
    voice_source_commands,
    voice_extra_for,
)


def test_python_314_is_rejected_with_supported_range():
    with pytest.raises(BootstrapError, match="3.11–3.13"):
        ensure_supported_python((3, 14))


def test_python_311_through_313_are_supported():
    for version in ((3, 11), (3, 12), (3, 13)):
        ensure_supported_python(version)


def test_apple_silicon_uses_macos_voice_extra():
    assert voice_extra_for("Darwin", "arm64") == "voice-macos"


def test_other_platforms_use_cross_platform_voice_extra():
    assert voice_extra_for("Windows", "AMD64") == "voice-cross-platform"
    assert voice_extra_for("Linux", "x86_64") == "voice-cross-platform"


def test_current_platform_selection_is_deterministic():
    expected = "voice-macos" if platform.system() == "Darwin" and platform.machine().lower() in {"arm64", "aarch64"} else "voice-cross-platform"
    assert voice_extra_for(platform.system(), platform.machine()) == expected


def test_cross_platform_voice_bootstrap_pins_cosyvoice_source(tmp_path):
    commands = voice_source_commands("Windows", "AMD64", tmp_path)

    assert commands[0][:3] == ["git", "clone", "--recursive"]
    assert commands[0][-1] == str(tmp_path / "CosyVoice")
    assert commands[1] == [
        "git", "-C", str(tmp_path / "CosyVoice"), "checkout",
        "074ca6dc9e80a2f424f1f74b48bdd7d3fea531cc",
    ]


def test_macos_voice_bootstrap_does_not_clone_official_backend(tmp_path):
    assert voice_source_commands("Darwin", "arm64", tmp_path) == []


def test_python_313_selects_binary_compatible_numpy_range():
    pyproject = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(
        encoding="utf-8"
    )
    assert "numpy>=2.1,<3.0; python_version >= '3.13'" in pyproject


def test_macos_installs_fork_without_broken_transitive_dependencies(tmp_path):
    commands = voice_install_commands("Darwin", "arm64", tmp_path / "python")

    assert any(
        "--no-deps" in command and "mlx-audio-plus==0.1.8" in command
        for command in commands
    )
    assert all("mlx-audio[all]" not in " ".join(command) for command in commands)


def test_cross_platform_does_not_install_mlx_audio_fork(tmp_path):
    commands = voice_install_commands("Windows", "AMD64", tmp_path / "python.exe")

    assert commands == []


def test_macos_model_requires_the_weight_file(tmp_path):
    assert voice_model_ready("Darwin", tmp_path) is False

    model = tmp_path / "deps" / "Fun-CosyVoice3-0.5B-2512-8bit"
    model.mkdir(parents=True)
    (model / "model.safetensors").write_bytes(b"weight")

    assert voice_model_ready("Darwin", tmp_path) is True


def test_cross_platform_model_is_managed_by_official_backend(tmp_path):
    assert voice_model_ready("Windows", tmp_path) is True


def test_macos_model_download_uses_project_script(tmp_path):
    command = voice_model_commands(
        "Darwin", "arm64", tmp_path / ".venv" / "bin" / "python", tmp_path
    )

    assert command == [[
        str(tmp_path / ".venv" / "bin" / "python"),
        str(tmp_path / "scripts" / "download_voice_model.py"),
        str(tmp_path / "deps" / "Fun-CosyVoice3-0.5B-2512-8bit"),
    ]]


def test_command_failure_reports_only_bounded_output_tail():
    command = [
        sys.executable,
        "-c",
        "import sys; print('EARLY' * 1000); print('FINAL_REASON', file=sys.stderr); raise SystemExit(7)",
    ]

    with pytest.raises(BootstrapError) as raised:
        _run(command)

    assert "FINAL_REASON" in str(raised.value)
    assert "EARLY" not in str(raised.value)


def test_install_status_is_replaced_atomically(tmp_path):
    status_file = tmp_path / "system" / "voice-installation.json"

    _write_install_status(status_file, "installing", "dependencies", "正在安装")
    _write_install_status(status_file, "restart_required", "complete", "请重启")

    assert json.loads(status_file.read_text(encoding="utf-8")) == {
        "state": "restart_required",
        "stage": "complete",
        "message": "请重启",
        "restart_required": True,
    }
    assert list(status_file.parent.glob(".voice-install-*")) == []


def test_voice_dry_run_does_not_claim_installation_completed():
    assert voice_completion(True) == (
        "dry_run", "dry-run", "检查完成；dry-run 未修改环境"
    )
    assert voice_completion(False) == (
        "restart_required", "complete", "语音组件已安装，请重启 Heaven Agent 生效"
    )
