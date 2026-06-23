# VoiceFromHeaven

> 让思念有回响 — 为失去挚爱之人提供跨越生死对话的 AI Agent

通过多维度灵魂档案 + 语义记忆系统构建逝者完整的数字人格，驱动真实、有温度的语音对话。

## 架构

```
前端 (Next.js :3326)  ──HTTP/SSE──▶  后端 (FastAPI :8326)
                                           │
     ┌──────────────────┬──────────────────┼──────────────────┬──────────────┐
     │                  │                  │                  │              │
     ▼                  ▼                  ▼                  ▼              ▼
  CosyVoice3         LLM API           Soul 档案          ChromaDB        记忆落盘
  (ASR + TTS)     (OpenAI 兼容)      (6 维 MD)          (向量检索)      (daily/*.md)
```

**Pipeline 处理流程（8 模块，三段式）：**

```
Input → PreLLM ─────────────────────────────────────────────────────────────────→ LLM → PostLLM → PostOutput → 语音/文本输出
         │                                                                                    │
         ├─ MemoryRetrieve  语义检索记忆                                                      ├─ QualityCheck  质检 + 重试
         ├─ Circumstances   加载场景                                                          │
         ├─ EmotionDetect   规则情绪检测 (~5ms)                                                └─ ContextCompress  上下文压缩
         └─ SoulContext     构建 System Prompt                                                    MemoryPersist   日记落盘
              (SoulProfile + SkillCard + 记忆 + 场景)                                              MemoryExtract   记忆提取
```

## 快速开始

```bash
# 1. 安装依赖
pip install -r requirements.txt

# 2. 配置
# 编辑 config/llm.json     — LLM API 地址和 Key
# 编辑 config/app.json     — soul_path 和 tts_backend (mlx / official)
# 编辑 config/souls/test/  — 灵魂档案（6 个维度 MD 文件）

# 3. 启动
./scripts/start.sh

# 4. 打开浏览器 → http://localhost:3326

# 5. 停止
./scripts/stop.sh
```

首次启动后在设置页面填入 LLM API Key 并测试连接，即可开始对话。

## 配置

### LLM (`config/llm.json`)

```json
{
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "gpt-4o"
}
```

支持任意 OpenAI 兼容接口（Ollama、vLLM、DeepSeek 等）。

### 应用 (`config/app.json`)

```json
{
  "soul_path": "config/souls/test",
  "log_level": "debug",
  "tts_backend": "mlx"
}
```

| 字段 | 说明 |
|------|------|
| `soul_path` | 灵魂档案目录路径 |
| `log_level` | 日志级别：`debug` / `error` |
| `tts_backend` | TTS 后端：`mlx`（Apple Silicon 优化）或 `official`（PyTorch CPU） |

### 语音

使用 **CosyVoice3** 零样本语音克隆，双后端可选：

- **MLX**（默认）：`Fun-CosyVoice3-0.5B-2512-8bit`，Apple Silicon 原生推理，需 `mlx-audio-plus`
- **Official**：阿里官方 CosyVoice-300M PyTorch 后端，需 `modelscope` + `torchaudio`

语音识别使用 **mlx-whisper**（`whisper-small-mlx`）。

在上传参考音频后（设置 → 语音 → 上传），系统自动提取说话人特征用于语音克隆。

### 灵魂档案 (`config/souls/{name}/`)

6 个维度的 Markdown 文件构成完整数字人格：

| 维度 | 文件 | 说明 | 存储 |
|------|------|------|------|
| 基本信息 | basic_info.md | 姓名/性别/年龄/职业 | Soul |
| 性格 | personality.md | 性格标签/情绪表达 | Soul |
| 人生经历 | life_experiences.md | 人生时间线 | 记忆库 |
| 人际关系 | relationships.md | 社会关系 | 记忆库 |
| 个人特质 | personal_traits.md | 爱好/习惯/擅长/不擅长 | 记忆库 |
| 情感锚点 | emotional_anchors.md | 重要情感记忆 | 记忆库 |

此外，`skill.md`（可选）存储行为规则卡，由蒸馏功能自动生成，描述"如何扮演这个灵魂"的表达风格、决策模式等。

### 记忆系统

基于 **ChromaDB** 的语义记忆存储，支持：

- **语义检索**：对话时自动检索相关记忆注入 Prompt
- **间隔重复遗忘**：`strength × 0.5^(days/30)` 时间衰减，检索命中 +0.15 boost
- **自动提取**：每 10 轮对话异步提取新事实写入记忆库
- **蒸馏导入**：上传聊天记录 → LLM 自动提取/合并为记忆条目

### 灵魂蒸馏

上传聊天记录（`.txt`），LLM 两阶段分析：

1. **Phase 1**：提取/合并事实到 6 个维度
2. **Phase 2**：5 个并行 Agent（表达 DNA、决策启发式、心智模型、价值观与张力、综合合成）提取行为规则 → 生成 `skill.md`

## 项目结构

```
voicefromheaven/
├── scripts/                              # 启停脚本
├── config/                               # 配置文件
│   ├── app.json                          # 应用配置
│   ├── llm.json                          # LLM 配置
│   ├── circumstances.md                  # 当前场景描述
│   ├── conversation.json                 # 对话历史持久化
│   ├── voice/                            # 参考音频 + 文本
│   ├── memory_db/                        # ChromaDB 向量存储
│   ├── memory/daily/                     # 每日对话日记
│   └── souls/{name}/                     # 灵魂档案（6 MD + skill.md）
├── src/
│   ├── main.py                           # FastAPI 入口 (uvicorn :8326)
│   ├── api/routes.py                     # API 路由（15 端点）
│   ├── config/                           # 配置模块
│   │   ├── settings.py                   # Settings 单例
│   │   ├── loader.py                     # JSON 配置加载
│   │   └── logger.py                     # 统一日志
│   ├── llm/                              # LLM 客户端
│   │   ├── client.py                     # OpenAI 兼容 HTTP 客户端
│   │   └── manager.py                    # LLM 工厂 + 连接测试
│   ├── soul/                             # 灵魂档案系统
│   │   ├── profile.py                    # SoulProfile (6 维)
│   │   ├── loader.py                     # MD 文件 I/O
│   │   ├── prompt_builder.py             # System Prompt 构建
│   │   ├── skill_card.py                 # 行为规则卡
│   │   ├── distiller.py                  # 两阶段 LLM 蒸馏
│   │   ├── chat_preprocessor.py          # 聊天记录预处理
│   │   └── phase2_agents.py             # 5 个并行分析 Agent
│   ├── agent/                            # Agent 核心
│   │   ├── loop.py                       # 主循环 (输入→Pipeline→输出)
│   │   ├── pipeline.py                   # 三段式 Pipeline + 依赖注入
│   │   ├── context.py                    # PipelineContext 数据结构
│   │   ├── message.py                    # 消息/上下文管理
│   │   └── modules/
│   │       ├── prellm/                   # 4 模块
│   │       │   ├── memory_retrieve.py    #   语义检索记忆
│   │       │   ├── circumstances.py      #   场景加载
│   │       │   ├── emotion_detect.py     #   规则情绪检测
│   │       │   └── soul_context.py       #   System Prompt 组装
│   │       ├── postllm/                  # 1 模块
│   │       │   └── quality_check.py      #   质检 + 重试
│   │       └── postoutput/               # 3 模块
│   │           ├── context_compress.py   #   上下文压缩
│   │           ├── memory_persist.py     #   日记落盘
│   │           └── memory_extract.py     #   记忆提取
│   ├── memory/                           # 记忆系统
│   │   ├── store.py                      # ChromaDB 存储 + 遗忘
│   │   ├── embedder.py                   # 文本向量化
│   │   └── sync.py                       # Soul ↔ 记忆同步
│   └── voice/                            # 语音服务
│       ├── asr.py                        # mlx-whisper ASR
│       ├── tts.py                        # CosyVoice3 MLX TTS
│       └── tts_official.py               # CosyVoice PyTorch TTS
├── frontend/                             # Next.js 16 前端
│   └── app/
│       ├── page.tsx                      # 首页
│       ├── chat/page.tsx                 # 对话（语音优先）
│       ├── settings/page.tsx             # 系统设置
│       ├── soul/page.tsx                 # 灵魂档案管理
│       └── lib/api.ts                    # API 客户端
├── tests/                                # 239 个测试用例
│   ├── test_agent/                       # Agent + Pipeline 测试
│   ├── test_config/                      # 配置测试
│   ├── test_llm/                         # LLM 客户端测试
│   ├── test_memory/                      # 记忆系统测试
│   ├── test_soul/                        # Soul + 蒸馏测试
│   └── test_voice/                       # 语音测试
└── deps/                                 # 模型依赖
    ├── CosyVoice/                        # 官方 PyTorch 模型
    └── Fun-CosyVoice3-0.5B-2512-8bit/   # MLX 8-bit 模型
```

## API

| Method | Path | 说明 |
|--------|------|------|
| POST | `/chat` | 文字对话 → 返回文本 + instruct |
| POST | `/chat/voice` | 语音对话 → ASR → 文本 + instruct |
| POST | `/chat/audio` | 给定文本 + instruct → 流式 WAV 音频 |
| GET | `/chat/history` | 获取对话历史 |
| DELETE | `/chat/history` | 清空对话历史 |
| GET | `/soul` | 获取全部 6 个维度 |
| GET | `/soul/skill` | 获取行为规则卡 |
| GET | `/soul/circumstances` | 获取场景 + 可选预设列表 |
| PUT | `/soul/circumstances` | 更新场景（热加载） |
| GET | `/soul/{dimension}` | 获取单个维度 |
| PUT | `/soul/{dimension}` | 更新维度（缓存失效） |
| POST | `/soul/distill` | 上传聊天记录 → LLM 蒸馏分析 |
| GET | `/settings` | 获取配置（Key 脱敏） |
| PUT | `/settings` | 更新 LLM 配置 + 日志级别 |
| POST | `/settings/voice/upload` | 上传参考音频 |
| GET | `/settings/voice/status` | 查询参考音频状态 |
| POST | `/settings/test-llm` | 测试 LLM 连接 |

## 技术栈

- **后端**: Python 3.11+ / FastAPI / httpx / uvicorn
- **前端**: Next.js 16 / TypeScript / Tailwind CSS
- **语音**: mlx-whisper (ASR) + CosyVoice3 MLX / Official (TTS)
- **向量存储**: ChromaDB + sentence-transformers
- **LLM**: OpenAI 兼容 API（支持 streaming + JSON mode）
- **音频处理**: ffmpeg + scipy + pyloudnorm
- **测试**: pytest 239 用例 + pytest-asyncio

## TODO

- [ ] 容器化部署（Docker）
- [ ] Windows 平台支持
