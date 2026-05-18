# VoiceFromHeaven — 最小化架构设计文档 v2

## 项目概述

为失去挚爱之人提供跨越生死对话的 AI Agent。通过**灵魂档案系统**构建逝者完整的数字人格，驱动真实感对话。

**项目名**: VoiceFromHeaven

**愿景**: 让思念有回响。

---

## 核心设计决策

| 决策项 | 选择 |
|--------|------|
| 交互方式 | 语音输入 + 语音输出，前端降级支持文字 |
| 前端技术栈 | React / Next.js |
| LLM 接口 | 仅支持 OpenAI 兼容接口（base_url + api_key + model 配置） |
| ASR | Fish Speech 本地 STT（最低延迟） |
| TTS | Fish Speech 本地 TTS（支持情绪标签） |
| 部署模式 | 先本地服务 + 远端 LLM API，逐步演进到全本地 |
| 实现顺序 | 自顶向下：Agent → LLM → Soul → Voice → Config |
| 语音交互 | 按住说话（Push-to-Talk） |

---

## 系统架构图

```
┌──────────────────────────────────────────────────────────┐
│                 Next.js 前端 (:3000)                       │
│                                                          │
│  /              首页（项目介绍、愿景）                    │
│  /souls         灵魂列表（选择/创建）                     │
│  /souls/[id]    灵魂档案（维度子页面）                    │
│  /chat/[id]     对话界面（语音/文字双模）                 │
│  /settings      系统配置（base_url/api_key/model）        │
└─────────────────────────┬────────────────────────────────┘
                          │ HTTP / SSE
┌─────────────────────────▼────────────────────────────────┐
│                FastAPI 后端 (:8000)                        │
│                                                          │
│  POST /chat/{soul_id}/stream    SSE 流式对话（音频出入）  │
│  GET/PUT /settings              系统配置 CRUD             │
│  GET /souls                     灵魂列表                  │
│  GET/PUT /souls/{id}/dimensions  维度 md 编辑             │
│                                                          │
│  ┌────────────────────────────────────────────────────┐  │
│  │              AgentLoop.run()                        │  │
│  │                                                    │  │
│  │  ASR (Fish Speech STT)                             │  │
│  │    → Pipeline:                                     │  │
│  │      [Preprocess 链]                               │  │
│  │        ├─ soul_context   加载 Soul → System Prompt │  │
│  │        ├─ circumstances  场景上下文注入              │  │
│  │        ├─ emotion_detect 规则引擎情绪检测            │  │
│  │      → LLM (OpenAI 兼容 API，流式生成)              │  │
│  │      → [Postprocess 链]                             │  │
│  │        ├─ quality_check  禁忌词/破设定检测           │  │
│  │        ├─ emotion_inject TTS 情绪标签注入            │  │
│  │    → TTS (Fish Speech TTS)                         │  │
│  └────────────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────────────┘
```

---

## 目录结构

```
voicefromheaven/
├── src/
│   ├── main.py                      # FastAPI 入口 (:8000)
│   │
│   ├── config/                      # 配置模块
│   │   ├── __init__.py
│   │   ├── settings.py             # Settings 单例，统一管理所有配置
│   │   └── loader.py               # JSON 配置加载器
│   │
│   ├── llm/                         # LLM 模块
│   │   ├── __init__.py
│   │   ├── client.py                # OpenAIClient: chat() + stream()
│   │   └── manager.py               # LLMManager: 工厂创建 + test_connection()
│   │
│   ├── soul/                        # Soul 模块
│   │   ├── __init__.py
│   │   ├── profile.py               # SoulProfile 数据类
│   │   ├── loader.py                # 从 config/souls/{id}/*.md 加载
│   │   └── prompt_builder.py        # 模板拼装 System Prompt
│   │
│   ├── agent/                       # Agent-Core 模块
│   │   ├── __init__.py
│   │   ├── loop.py                 # AgentLoop 主循环
│   │   ├── pipeline.py             # Pipeline: 可扩展模块链
│   │   └── modules/
│   │       ├── __init__.py
│   │       ├── base.py             # PipelineModule 抽象基类
│   │       ├── preprocess/         # 预处理模块链
│   │       │   ├── __init__.py
│   │       │   ├── soul_context.py    # 加载 Soul Profile → System Prompt
│   │       │   ├── circumstances.py   # 注入场景上下文
│   │       │   ├── emotion_detect.py  # 规则引擎情绪检测
│   │       │   └── history.py        # 对话历史管理（后期加）
│   │       └── postprocess/        # 后处理模块链
│   │           ├── __init__.py
│   │           ├── quality_check.py   # 禁忌词/破设定检测
│   │           ├── emotion_inject.py  # TTS 情绪标签注入
│   │           └── fingerprint.py    # 语言指纹注入（后期加）
│   │
│   ├── voice/                       # Voice 模块
│   │   ├── __init__.py
│   │   ├── asr.py                  # Fish Speech STT: audio → text
│   │   └── tts.py                  # Fish Speech TTS: text → audio
│   │
│   └── api/                        # API 路由
│       ├── __init__.py
│       └── routes.py               # chat, settings, souls 路由
│
├── config/                          # 配置文件目录
│   ├── llm.json                     # { base_url, api_key, model }
│   ├── voice.json                   # { fish_speech_url, speaker }
│   ├── app.json                     # { souls_path } 全局配置
│   ├── circumstances.md             # 当前场景描述
│   └── souls/                       # 灵魂档案数据
│       └── {soul_id}/               # 每个灵魂一个目录
│           ├── basic_info.md
│           ├── personality.md
│           ├── life_experiences.md
│           ├── relationships.md
│           ├── hobbies.md
│           ├── special_habits.md
│           ├── values_beliefs.md
│           ├── emotional_anchors.md
│           ├── linguistic_fingerprint.md
│           └── knowledge_domain.md
│
├── web/                             # Next.js 前端
│   ├── app/
│   │   ├── page.tsx                 # /         首页
│   │   ├── souls/page.tsx           # /souls    灵魂列表
│   │   ├── souls/[id]/page.tsx      # /souls/[id] 维度列表
│   │   ├── souls/[id]/[dim]/page.tsx # 维度编辑
│   │   ├── chat/[id]/page.tsx       # /chat     对话界面
│   │   └── settings/page.tsx        # /settings 系统配置
│   ├── components/
│   │   ├── ChatWindow.tsx           # 对话窗口
│   │   ├── VoiceButton.tsx          # 按住说话按钮
│   │   ├── MessageBubble.tsx        # 消息气泡
│   │   ├── SettingsPanel.tsx        # LLM 配置表单
│   │   └── SoulEditor.tsx           # 维度 md 编辑器
│   └── lib/
│       └── api.ts                   # 后端 API 调用封装
│
├── tests/                           # 测试与源码模块一一对应
│   ├── conftest.py
│   ├── test_config/
│   │   ├── test_loader.py
│   │   └── test_settings.py
│   ├── test_llm/
│   │   └── test_client.py
│   ├── test_soul/
│   │   ├── test_loader.py
│   │   └── test_prompt_builder.py
│   ├── test_agent/
│   │   ├── test_loop.py
│   │   ├── test_pipeline.py
│   │   └── test_modules/
│   │       ├── test_soul_context.py
│   │       ├── test_circumstances.py
│   │       ├── test_emotion_detect.py
│   │       ├── test_quality_check.py
│   │       └── test_emotion_inject.py
│   └── test_voice/
│       ├── test_asr.py
│       └── test_tts.py
│
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 模块详细设计

### 1. Config 模块

```python
# settings.py — 单例，统一管理所有配置
class Settings:
    _instance: Settings | None = None
    
    def get() -> AppConfig
    def update(partial: dict)   # 更新配置（会写回 JSON 文件）

# 数据类
@dataclass
class AppConfig:
    llm: LLMConfig
    voice: VoiceConfig
    souls_path: Path

@dataclass 
class LLMConfig:
    base_url: str              # OpenAI 兼容 endpoint
    api_key: str
    model: str                 # gpt-4o / claude-sonnet / 任意

@dataclass
class VoiceConfig:
    fish_speech_url: str       # Fish Speech 服务地址
    speaker: str               # 默认说话人
```

**配置文件示例**:
```json
// config/llm.json
{
  "base_url": "https://api.openai.com/v1",
  "api_key": "sk-...",
  "model": "gpt-4o"
}

// config/voice.json
{
  "fish_speech_url": "http://localhost:8080",
  "speaker": "demo_speaker"
}

// config/app.json
{
  "souls_path": "config/souls"
}
```

---

### 2. LLM 模块

**只支持 OpenAI 兼容接口**，不做 Provider 特殊适配。

```python
# client.py
class LLMClient:
    def __init__(self, base_url: str, api_key: str, model: str)
    async def chat(self, messages: list[dict]) -> str
    async def stream(self, messages: list[dict]) -> AsyncGenerator[str]

# manager.py
class LLMManager:
    def get_client(config: LLMConfig) -> LLMClient
    async def test_connection(config: LLMConfig) -> bool
```

---

### 3. Soul 模块

```python
# profile.py
@dataclass
class SoulProfile:
    soul_id: str
    dimensions: dict[str, str]  # dimension_name → md_content

# loader.py — 从 config/souls/{soul_id}/*.md 加载
class SoulLoader:
    def load(self, soul_id: str) -> SoulProfile
    def load_dimension(self, soul_id: str, dimension: str) -> str
    def save_dimension(self, soul_id: str, dimension: str, content: str)

# prompt_builder.py — 模板拼装，不用 LLM
class SoulPromptBuilder:
    def build(self, profile: SoulProfile, circumstances: str) -> str
```

**Soul Prompt 缓存策略**:
- 首次加载 → 模板拼装 → 内存缓存
- Soul 维度更新 → 主动失效 → 下次请求重新拼装
- 不调用 LLM，零成本

---

### 4. Agent-Core 模块

```python
# loop.py
class AgentLoop:
    def __init__(self, llm: LLMClient, soul_loader: SoulLoader, voice: VoiceService)
    
    async def run(self, soul_id: str, audio: bytes) -> AsyncGenerator[bytes]:
        text = await self.voice.asr.transcribe(audio)     # ASR
        ctx = PipelineContext(soul_id=soul_id, user_message=text)
        ctx = await self.pipeline.execute(ctx)            # Pipeline
        async for audio_chunk in self.voice.tts.speak(ctx.response):
            yield audio_chunk                             # TTS output

# pipeline.py
class Pipeline:
    def add_preprocess(self, module: PipelineModule)
    def add_postprocess(self, module: PipelineModule)
    async def execute(self, ctx: PipelineContext) -> PipelineContext

class PipelineContext:
    soul_id: str
    user_message: str
    soul_profile: SoulProfile | None
    circumstances: str
    emotion: EmotionTag | None
    system_prompt: str | None
    llm_messages: list[dict]
    response: str
    tts_emotion_tags: list[str]
```

**Pipeline 执行流程**:

```
Input (text from ASR)
  → Preprocess 链:
      [soul_context]     加载 10 维度 → 构建 System Prompt
      [circumstances]    注入场景描述
      [emotion_detect]   规则引擎检测情绪
  → LLM (OpenAI 兼容 API，流式生成)
  → Postprocess 链:
      [quality_check]    禁忌词 + 破设定检测
      [emotion_inject]   决定 TTS 情绪标签（如 [gentle]）
  → Output (text + emotion tags) → TTS
```

---

### 5. Voice 模块

```python
# asr.py
class ASRService:
    def __init__(self, fish_speech_url: str)
    async def transcribe(self, audio: bytes) -> str

# tts.py
class TTSService:
    def __init__(self, fish_speech_url: str, speaker: str)
    async def speak(self, text: str, emotion: str = "neutral") -> AsyncGenerator[bytes]
    # emotion 参数 → Fish Speech 情绪标签

class VoiceService:
    def __init__(self, config: VoiceConfig)
    asr: ASRService
    tts: TTSService
```

---

### 6. 前端设计

**页面路由**:

| 路由 | 说明 |
|------|------|
| `/` | 首页 — 项目介绍、愿景文案、引导按钮 |
| `/souls` | 灵魂列表 — 选择/创建灵魂 |
| `/souls/[id]` | 灵魂档案 — 10个维度列表 |
| `/souls/[id]/[dim]` | 维度编辑 — Markdown 编辑器，保存刷新缓存 |
| `/chat/[id]` | 对话界面 — 语音/文字双模输入 |
| `/settings` | 系统配置 — base_url/api_key/model |

**对话交互**: 按住说话（Push-to-Talk），松开发送音频到后端，SSE 流式接收音频回复。语音失败自动降级为文字输入。

**SettingsPanel 配置项**:

| 字段 | 说明 |
|------|------|
| API Base URL | OpenAI 兼容端点地址 |
| API Key | 密钥 |
| Model | 模型名 |
| Fish Speech URL | 服务地址 |
| Speaker | 说话人 |

---

## MD 文件格式规范

所有维度 md 文件统一格式：

```markdown
# 维度中文名称

## identity
字段: 值
字段: 值

## description
维度描述文本，可以包含多行内容。
```

**circumstances.md 格式**:

```markdown
# 当前场景

## context
- user_role: [与逝者的关系]
- current_time: [对话发生的时间]
- user_emotion: [当前情绪状态]
- purpose: [为什么发起这次对话]

## description
详细描述这次对话的背景和情境。
```

---

## 错误处理

| 场景 | 处理 |
|------|------|
| 麦克风被拒 | 前端提示，降级为文字输入 |
| ASR 超时/异常 | 返回提示"语音识别失败，请再试一次" |
| LLM API 超时/限流/Key 无效 | SSE 中断，前端提示"连接中断，请检查配置" |
| TTS 异常 | 降级返回文字回复 |
| 无效 soul_id | 返回 404 |
| 配置缺失 | 启动时报错，明确提示缺失项 |

**不做**: 不重试 LLM、不降级 Provider、内部模块不传播错误。

---

## 测试策略

- 单元测试 Mock 所有外部依赖（LLM API、Fish Speech、文件 IO）
- 每个模块独立可测
- AgentLoop 做集成测试（Mock LLM + Mock Voice）
- 测试目录与源码模块一一对应

---

## 实施顺序

1. **Agent + LLM + Soul** — 核心对话链路（文字输入 → 文字输出）
2. **Voice** — 接入 Fish Speech ASR + TTS
3. **Config** — 统一配置管理
4. **Frontend** — Next.js 页面 + 组件
5. **联调** — 端到端语音对话

---

## 不做的（当前阶段）

- 多 Provider 适配（只支持 OpenAI 兼容接口）
- 记忆模块（短期/长期/情节）
- LLM 主动工具调用
- 数据持久化（PostgreSQL/Redis）
- Docker 部署
- 用户认证
