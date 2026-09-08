#!/usr/bin/env python3
"""Download the pinned Apple Silicon voice model with resume support."""

from __future__ import annotations

import argparse
import os
from pathlib import Path
from typing import Callable


MODEL_REPO = "mlx-community/Fun-CosyVoice3-0.5B-2512-8bit"
MODEL_REVISION = "177baf277ac75e04e810f7db7f0d9c0ce5a17854"
WEIGHT_FILE = "model.safetensors"


def download_model(
    target: Path,
    *,
    snapshot_download: Callable | None = None,
) -> Path:
    target = Path(target)
    weight = target / WEIGHT_FILE
    if weight.is_file():
        return weight
    target.mkdir(parents=True, exist_ok=True)
    os.environ.setdefault("HF_HUB_DISABLE_PROGRESS_BARS", "1")
    if snapshot_download is None:
        from huggingface_hub import snapshot_download as huggingface_download

        snapshot_download = huggingface_download
    snapshot_download(
        repo_id=MODEL_REPO,
        revision=MODEL_REVISION,
        local_dir=target,
    )
    if not weight.is_file():
        raise RuntimeError("模型下载结束，但缺少 model.safetensors")
    return weight


def main() -> int:
    parser = argparse.ArgumentParser(description="下载 Heaven Agent 固定版本语音模型")
    parser.add_argument("target", type=Path)
    args = parser.parse_args()
    download_model(args.target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
