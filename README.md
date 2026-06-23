# VoiceFromHeaven

> 让思念有回响 — 为失去挚爱之人提供跨越生死对话的 AI Agent

通过多维度灵魂档案系统构建逝者完整的数字人格，驱动真实、有温度的语音对话。

## 架构

```
前端 (Next.js :3326)  ──HTTP/SSE──▶  后端 (FastAPI :8326)
                                       │
     ┌─────────────────────────────────┼──────────────────────┐
     │                                 │                      │
     ▼                                 ▼                      ▼
  Fish Speech                       LLM API               Soul 档案
  (ASR + TTS)                   (OpenAI 兼容)         (6 维 MD 文件)
```

**Pipeline 处理流程：**

```
Input → prellm (场景/情绪/Soul) → LLM → postllm (质检/情绪注入) → postoutput (压缩/落盘) → 语音输出
```

## 快速开始

```bash
# 1. 安装 Python 依赖
pip install -r requirements.txt

# 2. 配置
# 编辑 config/llm.json    — LLM API 地址和 Key
# 编辑 config/voice.json  — Fish Speech 地址
# 编辑 config/souls/demo/ — 灵魂档案（6 个维度 MD 文件）

# 3. 启动
./scripts/start.sh

# 4. 打开浏览器
# http://localhost:3326

# 5. 停止
./scripts/stop.sh
```

首次启动后，在设置页面填入 LLM API Key 并测试连接，即可开始对话。

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

### 语音 (`config/voice.json`)

```json
{
  "fish_speech_url": "http://localhost:8080"
}
```

使用 Fish Speech 提供 ASR（语音识别）和 TTS（语音合成）。

### 灵魂档案 (`config/souls/demo/`)

6 个维度的 Markdown 文件构成完整数字人格：

| 维度 | 文件 | 说明 | 存储 |
|------|------|------|------|
| 基本信息 | basic_info.md | 姓名/性别/年龄/职业 | Soul |
| 性格 | personality.md | 性格标签/情绪表达 | Soul |
| 人生经历 | life_experiences.md | 人生时间线 | 记忆库 |
| 人际关系 | relationships.md | 社会关系 | 记忆库 |
| 个人特质 | personal_traits.md | 爱好/习惯/擅长/不擅长 | 记忆库 |
| 情感锚点 | emotional_anchors.md | 重要情感记忆 | 记忆库 |

其中"记忆库"维度在对话中通过语义检索动态注入，支持间隔重复遗忘机制自然演化。

## 项目结构

```
voicefromheaven/
├── scripts/                        # 启停脚本
├── config/                         # 配置文件
│   ├── app.json                    # 应用配置
│   ├── llm.json                    # LLM 配置
│   ├── voice.json                  # 语音配置
│   ├── circumstances.md            # 当前场景描述
│   └── souls/demo/                 # 灵魂档案（6 MD）
├── src/
│   ├── main.py                     # FastAPI 入口
│   ├── config/                     # 配置模块（单例）
│   ├── llm/                        # LLM 客户端（OpenAI 兼容）
│   ├── soul/                       # 灵魂档案加载与 Prompt 构建
│   ├── agent/                      # Agent 核心
│   │   ├── loop.py                 # 主循环
│   │   ├── pipeline.py             # 三段式 Pipeline
│   │   ├── message.py              # 消息/上下文管理
│   │   └── modules/
│   │       ├── prellm/             # 场景 + 情绪检测 + Soul
│   │       ├── postllm/            # 质检 + TTS 参数注入
│   │       └── postoutput/         # 上下文压缩 + 记忆落盘
│   ├── voice/                      # ASR + TTS 服务
│   └── api/                        # API 路由（8 条）
├── frontend/                       # Next.js 前端
│   └── app/
│       ├── page.tsx                # 首页
│       ├── chat/page.tsx           # 对话（文字 + 按住说话）
│       ├── settings/page.tsx       # 系统设置
│       └── soul/page.tsx           # 灵魂档案编辑
├── tests/                          # 114 个测试用例
└── design/                         # 架构设计文档
```

## API

| Method | Path | 说明 |
|--------|------|------|
| POST | `/chat` | 文字对话 → 语音输出 |
| POST | `/chat/voice` | 语音对话 → 语音输出 |
| GET | `/soul` | 获取灵魂档案 |
| GET | `/soul/{dimension}` | 获取单个维度 |
| PUT | `/soul/{dimension}` | 更新维度 |
| GET | `/settings` | 获取配置 |
| PUT | `/settings` | 更新配置 |
| POST | `/settings/test-llm` | 测试 LLM 连接 |

## 技术栈

- **后端**: Python 3.11+ / FastAPI / httpx
- **前端**: Next.js 16 / TypeScript / Tailwind CSS
- **语音**: Fish Speech (ASR + TTS)
- **LLM**: OpenAI 兼容 API
- **测试**: pytest + pytest-asyncio
