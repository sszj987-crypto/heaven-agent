# TODO

## Windows 平台支持

当前项目仅在 macOS 上运行，MLX 生态（mlx-audio-plus、mlx-whisper）仅支持 Apple Silicon，Windows 上不可用。

**已知问题**：
- `scripts/start.sh` / `scripts/stop.sh` 是 bash 脚本，Windows 无法直接执行
- MLX 生态仅支持 Apple Silicon，Windows 上不可用
- TTS 的 `tts.py`（MLX CosyVoice3）在 Windows 上无法运行
- ASR 的 `asr.py`（mlx-whisper）在 Windows 上无法运行
- 部分依赖（soundfile、scipy）在 Windows 上有额外系统依赖

**范围**：
- TTS：Windows 上自动使用 official 后端（CosyVoice-300M PyTorch CPU）
- ASR：Windows 上自动使用 faster-whisper（CTranslate2 CPU）
- 平台自适应：`create_asr_service()` 工厂函数 + `tts_backend` 平台感知默认值
- 启动脚本：PowerShell `.ps1` 或 `.bat`
- 路径处理：统一 pathlib.Path（项目已大量使用，需检查遗漏）
- Windows 环境配置文档

**预估难点**：
- CosyVoice PyTorch（official）在 Windows 上的依赖链（torchaudio、modelscope）
- faster-whisper 依赖 CTranslate2，Windows 兼容性需验证
- ffmpeg 需单独安装并加入 PATH
