# Heaven Agent

Heaven Agent 是一个本地优先的 AI 人物模拟与纪念对话应用。它使用六维 Markdown 档案、可审阅的记忆候选、可重建的向量索引，以及按需安装的 ASR/TTS。产品会明确标识 AI 模拟；模型生成的回复不会被自动固化为人物事实。

## 系统要求

- Python 3.11–3.13（不支持 3.14）
- Node.js 22+ 与 npm
- macOS Apple Silicon 或 Windows 10/11
- `ffmpeg`：文字模式不需要；语音模式强烈建议安装
- 一个 OpenAI 兼容的 LLM 接口

## 一条命令启动

macOS / Linux shell：

```bash
./scripts/start.sh
```

Windows：

```powershell
scripts\start.bat
```

启动脚本会检查 Python/Node，创建或修复 `.venv`，从 `pyproject.toml` 安装核心依赖并执行 `npm ci`。打开 <http://localhost:3326>，按四步引导完成“人物信息 → 导入确认 → 声音 → 对话”。首次建档会使用脱敏 demo 模板，不要求仓库中存在个人资料。

如果只想准备环境：

```bash
python3 scripts/bootstrap.py
```

核心安装完成后文字对话即可使用。语音依赖和模型不会被核心安装强制下载。

## 按需安装语音

进入“档案 → 语音音色”，当前状态为“语音组件未安装”时点击“安装语音组件”。安装在后台进行，完成后按页面提示重启 Heaven Agent；文字对话在安装期间仍可使用。模型下载支持断点续传。

也可以使用命令行安装：

```bash
python3 scripts/bootstrap.py --voice
```

- macOS Apple Silicon：MLX ASR/TTS
- 其他平台：faster-whisper + 固定提交版本的 CosyVoice PyTorch 后端
- Apple Silicon 模型会在安装时下载并校验；其他平台模型在首次使用时按需下载。安装前请预留磁盘空间

安装命令只输出当前阶段，不再持续打印 pip 解析过程。未安装、未配置或加载失败时，系统状态会显示语音降级，文字对话仍然可用。

### 本地语音故障排查与日志

通过 `scripts/start.sh` 启动时，后端日志在 `log/backend.log`，前端日志在 `log/frontend.log`。手动运行 uvicorn 时，后端日志输出到启动它的终端。

```bash
tail -f log/backend.log
```

在“设置 → 日志等级”选择 Debug，可以查看模型加载、参考音频读取、合成耗时和音频大小；默认 Error 等级仍会记录生成失败的完整异常堆栈。复现后可切回 Error。

- **点击播放失败**：浏览器开发者工具的 Network 中检查 `POST /chat/audio` 的状态和错误消息，再对照同一时刻的后端日志。`POST /chat/voice` 对应语音输入识别。
- **`No module named 'einops'` 或缺少语音依赖**：运行 `python3 scripts/bootstrap.py --voice --skip-node` 修复语音环境，然后重启服务。MLX 语音包使用 `--no-deps` 安装，其推理所需依赖由本项目安装清单显式补齐。
- **模型加载或合成报错**：查看堆栈最底部的原因；首次加载模型较慢，“测试连接”只检查服务可用状态，实际点击播放才能验证完整合成链路。

## 本地与 MiniMax 云端音色

设置页的“语音合成”可选择 `local` 或 `minimax`。`local` 使用本机按需安装的语音组件和模型；`minimax` 使用 MiniMax 云端音色，不需要安装本地语音包或下载本地模型。选择一种服务只影响语音：对话文字会照常返回。

### 配置 MiniMax

MiniMax 的 Key 独立于 LLM Key，不能互用。在 MiniMax 开放平台的“账户管理 → 接口密钥”创建按量付费 API Key，再在设置页选择 MiniMax、填入 Key 和模型名并保存。读取设置不会返回 Key；保存时不填写 Key 会保留原值，显式清空才会删除它。

声音复刻还要求在 MiniMax “账户管理 → 账户信息 → 认证信息”完成个人实名认证或企业认证。官方说明与当前限制以 MiniMax 文档为准：[接口相关 FAQ](https://platform.minimaxi.com/docs/faq/about-apis)、[上传复刻音频](https://platform.minimaxi.com/docs/api-reference/voice-cloning-uploadcloneaudio)。请只上传自己拥有合法授权的声音样本，也不要把 API Key 交给他人或提交到 Git。

### 创建云端音色与隐私

在“档案 → 语音音色”上传参考声音即可创建或替换当前 Soul 的云端音色。MiniMax 接受 MP3、M4A、WAV；官方限制为 10 秒至 5 分钟、最多 20 MB。本应用建议使用清晰、单人说话的 10–30 秒样本，以保持原有录音引导的一致性。

上传即表示该音频会发送给 MiniMax 用于音色复刻。系统会在新音色启用前自动生成一次短句合成试听；该激活合成以及 MiniMax 的复刻/合成服务可能产生费用。该试听不会自动播放，需用户点击播放；聊天文字先显示，聊天语音也只会在用户点击后生成并播放。

创建成功后，原始上传文件会尽力从 MiniMax 删除；替换成功后，旧的远端克隆音色也会尽力删除。网络或服务端暂时不可用时，清理任务会保留并在后续安全操作中重试，重试范围限于当前活跃 Soul 的语音目录；这不会撤销已经验证并启用的新音色。当前激活所需的本地元数据、参考录音和试听文件仍保存在本机运行数据中。

演示重置会把云端音色元数据、参考录音和试听文件一起归档到可恢复备份，远端音色会保留。归档中的待清理任务不会再自动重试；重置本身不会删除远端音色。

云端配置写入被 Git 忽略的 `config/tts.json`；其中包含提供商、MiniMax 服务地址、模型和 API Key。每个 Soul 的云端音色元数据位于 `data/souls/{soul_id}/voice/cloud.json`，同一目录还会保存云端参考录音与激活试听。不要手工共享这些运行数据。

### MiniMax 故障排查

- **“测试连接”失败**：它只校验 MiniMax 凭据，不会合成音频。确认使用的是独立的按量付费 API Key、账户已具备相应权限，且服务地址和网络可用。
- **提示未配置或没有可用音色**：先保存 MiniMax Key，再上传合规样本并等待状态显示“音色已就绪”。MiniMax 模式不应安装本地语音组件作为前置条件。
- **401/403、额度或频率限制、超时**：检查 Key 与认证状态，或稍后重试/检查 MiniMax 账户额度。错误会直接显示；系统不会自动切回本地 TTS。
- **替换创建失败**：旧音色会保持可用，直到新音色完成激活试听。可在修正样本、凭据或额度问题后重试。

## 配置

首次启动后在设置页填写 Base URL、API Key 和模型名。`PUT /settings` 中省略 API Key 表示保持现值，传空字符串表示清除；读取设置永远不会返回真实 Key 或掩码占位符。

主要本地配置：

- `config/app.json`：当前 `soul_id`、数据根目录、兼容迁移来源与运行参数
- `config/llm.json`：本地 LLM 配置；不要提交真实 Key
- `config/souls/demo/`：可提交的脱敏首次运行模板

## 数据与隐私

每个档案有稳定的 `soul_id`，运行数据统一位于：

```text
data/souls/{soul_id}/
├── profile/           # 六维 Markdown 与 skill.md，人物事实真源
├── conversation.json # 当前对话历史
├── memory/
│   ├── daily/         # 对话日记
│   ├── index/         # ChromaDB，可由真源重建
│   └── candidates.json # 待确认事实
├── voice/             # 本地或云端参考声音；云端状态见 cloud.json
└── onboarding.json    # 首次引导状态
```

旧版 `config/souls/`、`config/voice/`、`config/memory_db/` 等数据首次迁移时会先备份、复制并校验，不会自动删除原文件。`data/` 默认不进入 Git。

人物事实只接受以下来源：导入资料、手工编辑、或用户人工确认的候选项。聊天中的用户陈述可形成候选；AI 自己的回复永远不是事实来源。导入任务只生成预览和候选，不直接覆盖档案。

## 开发与测试

Python 依赖以 `pyproject.toml` 为唯一真源：

```bash
./.venv/bin/python -m pip install -e '.[dev]'
./.venv/bin/python -m pytest -q
```

前端：

```bash
cd frontend
npm ci
npm test
npm run lint
npx tsc --noEmit
npm run build
```

环境诊断：

```bash
python3 scripts/bootstrap.py --dry-run
curl http://localhost:8326/system/status
```

## 关键 API

| 方法 | 路径 | 说明 |
|---|---|---|
| GET | `/system/status` | 初始化、当前 Soul、核心/语音能力和待处理任务 |
| GET/POST | `/system/voice-installation` | 查看当前安装状态或创建语音安装任务 |
| GET | `/system/diagnostics` | 返回不含私密正文的环境诊断 |
| GET | `/system/export` | 导出当前 Soul 的用户数据 |
| POST | `/system/demo-reset` | 备份当前数据后恢复脱敏演示档案 |
| POST | `/system/onboarding/steps/{step}` | 显式记录人物、导入确认或声音步骤 |
| POST | `/system/onboarding/complete` | 完成人物与导入确认后结束首次引导 |
| POST | `/chat` | 文字对话；返回记忆来源与安全状态 |
| POST | `/chat/voice` | ASR 后对话；返回真实转写 |
| POST | `/chat/audio` | 独立 TTS，失败不影响文字回复 |
| POST | `/soul/imports` | 创建导入预览任务，返回 `202 + job_id` |
| GET | `/jobs/{job_id}` | 查询后台任务进度与错误 |
| GET | `/memory/candidates` | 查看待确认事实与来源 |
| POST | `/memory/candidates/{id}/approve` | 编辑后确认写入 |
| POST | `/memory/candidates/{id}/reject` | 忽略候选 |
| GET/PUT | `/settings` | 读取或热更新配置 |
| POST | `/settings/test-tts` | 校验当前语音服务连接；MiniMax 不合成音频 |
| GET | `/settings/voice/status` | 当前提供商及其音色状态 |
| POST | `/settings/voice/upload` | 上传本地参考音频或创建 MiniMax 云端音色 |
| GET | `/settings/voice/preview` | 读取已激活 MiniMax 音色的本地试听 WAV |

错误统一为 `{code, message, retryable, request_id}`；日志默认记录请求 ID、阶段耗时和任务状态，不应记录完整私密内容。

## 故障排查

- **提示 Python 版本不支持**：安装 Python 3.11、3.12 或 3.13，然后重新运行启动脚本。损坏或失效的 `.venv` 会被自动修复。
- **找不到 Node/npm**：安装 Node.js 22+，确认 `node --version` 和 `npm --version` 可用。
- **文字可用、语音不可用**：在“档案 → 语音音色”点击安装，完成后重启；也可运行 `bootstrap.py --voice`。安装 `ffmpeg` 后再查看 `/system/status`。
- **语音安装失败**：直接点击“重试安装”即可继续未完成的模型下载。命令行安装失败时只显示末尾错误摘要，不会再因 `mlx-audio[all]` 依赖回溯反复刷屏。
- **声音可用但语气不变化**：查看 `/settings/voice/status` 的 `supports_instruction`。官方跨平台 CosyVoice 零样本后端只克隆音色，不支持逐轮语气指令；Apple Silicon 的 MLX 后端支持该能力。
- **LLM 401/404**：检查 API Key、Base URL 与模型名；保存设置后客户端会立即热更新。
- **记忆索引不可用**：系统会降级为无检索文字模式。修复 ChromaDB 依赖后重启即可，Markdown 档案不受影响。
- **直接运行 Turbopack build 报端口权限错误**：受限环境会禁止其内部端口；项目的 `npm run build` 已固定使用 webpack 生产构建。

## 升级

升级前备份 `data/` 与 `config/llm.json`，拉取代码后重新运行启动脚本。Bootstrap 会根据依赖指纹增量更新环境；数据迁移采用复制与校验策略。不要手工删除旧数据，确认新版本可读后再自行归档。

设置页的“恢复演示数据”会先把当前人物档案、声音、对话、候选事实和引导状态完整复制到 `data/backups/`，再恢复脱敏模板；任一步失败会回滚活动数据，不会修改 LLM 配置。该操作必须由用户显式确认。

## 安全边界

这是 AI 人物模拟，不是逝者本人、医疗服务或危机支持工具。高风险情绪场景会退出角色化强化，优先建议联系现实中可信任的人和当地专业/紧急支持。设计遵循自主性、安全、透明和问责原则。
