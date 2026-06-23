# TODO

## 容器化部署

当前部署方式为 `scripts/start.sh` 脚本直接在宿主机启动 uvicorn + next dev，存在以下问题：

- 依赖宿主机 Python/Node 环境，环境差异易导致启动失败
- 无进程隔离和资源限制
- 无健康检查和自动重启机制
- macOS / Linux 之间脚本不可通用

**目标**：编写 Dockerfile 和 docker-compose.yml，实现一键 `docker compose up` 启动全部服务。

**范围**：
- 后端容器（FastAPI + uvicorn，端口 8326）
- 前端容器（Next.js，端口 3326）
- 模型依赖处理（CosyVoice3 MLX 需 Apple Silicon GPU，可先用 official 后端在 CPU 上跑通；mlx-whisper 同理，可降级为 faster-whisper）
- 卷挂载：`config/`（含 soul 档案、LLM 配置、voice 参考音频、memory_db 持久化）
- `.env` 统一环境变量管理
- 非 macOS 环境下 TTS 自动切换为 official 后端，ASR 降级为 faster-whisper

**预估难点**：
- CosyVoice3 MLX 模型仅支持 Apple Silicon，需做跨平台兼容
- 前端 dev 模式 vs 生产构建的选择
- 模型文件体积大（数 GB），不适合打入镜像，需卷挂载或模型下载脚本

---

## Windows 平台支持

当前项目仅在 macOS 上运行，多处存在平台假设。

**已知问题**：
- `scripts/start.sh` / `scripts/stop.sh` 是 bash 脚本，Windows 无法直接执行
- 多处路径使用 Unix 风格斜杠
- MLX 生态（`mlx-audio-plus`、`mlx-whisper`）仅支持 Apple Silicon，Windows 上不可用
- TTS 的 `tts.py`（MLX CosyVoice3）在 Windows 上无法运行
- ASR 的 `asr.py`（mlx-whisper）在 Windows 上无法运行
- 部分依赖（如 `soundfile`、`scipy`）在 Windows 上有额外的系统依赖

**范围**：
- 提供 Windows 启动脚本（`.ps1` 或 `.bat`）
- TTS 在 Windows 上自动使用 `official` 后端（CosyVoice PyTorch）
- ASR 在 Windows 上降级为 `faster-whisper` 或 `whisper`（openai-whisper）
- 路径处理统一使用 `pathlib.Path`（项目已大量使用，需检查遗漏）
- Windows 下跳过 MLX 相关导入
- 编写 Windows 环境配置文档

**预估难点**：
- CosyVoice PyTorch（official）在 Windows 上的依赖链较长（torchaudio、modelscope 等）
- `faster-whisper` 需要 CTranslate2，Windows 兼容性需验证
- 部分音频处理（ffmpeg）需单独安装并加入 PATH

---

## 建议顺序

1. 先做容器化部署 —— 容器天然解决跨平台问题，Windows 用户可通过 Docker 运行
2. 再做 Windows 原生支持 —— 作为容器的补充，满足不想装 Docker 的用户
