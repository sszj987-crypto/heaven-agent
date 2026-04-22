# VoiceFromHeaven — 最小化架构设计文档 v1

## 项目概述

为失去挚爱之人提供跨越生死对话的 AI Agent。通过**灵魂档案系统**构建逝者完整的数字人格，驱动真实感对话。

**项目名**: VoiceFromHeaven

---

## 核心设计原则

1. **最小化优先**: 只实现最核心的架构，后续可扩展
2. **模块边界清晰**: 每个模块职责单一，通过接口通信
3. **配置驱动**: 所有模块配置通过 JSON 文件管理
4. **可测试性**: 每个模块可独立测试

---

## 系统架构图

```
┌─────────────────────────────────────────────────────────────┐
│                    前端层 (Frontend)                         │
│         对话窗口 + 系统设置(LLM Provider/API Key)            │
└─────────────────────────┬───────────────────────────────────┘
                          │ HTTP/SSE
┌─────────────────────────▼───────────────────────────────────┐
│                   Agent-Core (AgentLoop)                    │
│  ┌────────────────────────────────────────────────────────┐ │
│  │              Pipeline Architecture                      │ │
│  │  Input → Preprocess → LLM → Postprocess → Output        │ │
│  │                                                        │ │
│  │  可扩展模块插槽 (Extensible Module Slots)               │ │
│  └────────────────────────────────────────────────────────┘ │
└─────────────────────────┬───────────────────────────────────┘
              ┌───────────┼───────────┐
              ▼           ▼           ▼
        ┌──────────┐ ┌──────────┐ ┌──────────┐
        │   LLM    │ │   Soul   │ │  Voice   │
        │  Module  │ │  Module  │ │  Module  │
        └──────────┘ └──────────┘ └──────────┘
              │           │           │
              ▼           ▼           ▼
        ┌──────────────────────────────────────────┐
        │            Config Module                  │
        │      (统一管理所有模块的 JSON 配置)        │
        └──────────────────────────────────────────┘
```

---

## 目录结构

```
voicefromheaven/
├── src/
│   ├── main.py                      # 应用入口
│   │
│   ├── config/                      # 配置模块
│   │   ├── __init__.py
│   │   ├── settings.py             # 配置类（统一管理）
│   │   └── loader.py               # JSON 配置加载器
│   │
│   ├── llm/                         # LLM 模块
│   │   ├── __init__.py
│   │   ├── base.py                  # 抽象基类
│   │   ├── manager.py               # LLM 管理器（工厂模式）
│   │   └── providers/               # 多 Provider 实现
│   │       ├── __init__.py
│   │       ├── openai.py
│   │       ├── anthropic.py
│   │       ├── gemini.py
│   │       └── ollama.py
│   │
│   ├── soul/                        # Soul 模块
│   │   ├── __init__.py
│   │   ├── profile.py               # 灵魂档案模型
│   │   ├── loader.py                # 从 md 文件加载维度
│   │   └── prompt_builder.py        # 将多维度 md 编译为 System Prompt
│   │
│   ├── agent/                       # Agent-Core 模块
│   │   ├── __init__.py
│   │   ├── loop.py                 # AgentLoop（主循环）
│   │   ├── pipeline.py             # Pipeline 架构
│   │   └── modules/                # 可扩展模块
│   │       ├── __init__.py
│   │       ├── preprocess.py
│   │       ├── postprocess.py
│   │       └── emotion_detector.py
│   │
│   ├── voice/                       # Voice 模块
│   │   ├── __init__.py
│   │   ├── tts.py                  # 语音合成（Fish Speech）
│   │   └── config.py               # 语音配置
│   │
│   └── api/                        # API 路由（可选）
│       ├── __init__.py
│       └── routes.py
│
├── config/                          # 配置文件目录
│   ├── llm.json                     # LLM 提供商配置
│   ├── voice.json                   # 语音模块配置
│   ├── app.json                     # 应用全局配置
│   ├── circumstances.md             # 当前场景描述
│   └── souls/                        # 灵魂档案数据（每个灵魂一个目录）
│       └── demo/                     # 示例灵魂
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
├── tests/
│   ├── test_config.py
│   ├── test_llm/
│   │   ├── __init__.py
│   │   ├── test_manager.py
│   │   └── test_providers/
│   │       ├── __init__.py
│   │       └── test_openai.py
│   ├── test_soul/
│   │   ├── __init__.py
│   │   ├── test_profile.py
│   │   ├── test_loader.py
│   │   └── test_prompt_builder.py
│   ├── test_agent/
│   │   ├── __init__.py
│   │   ├── test_loop.py
│   │   ├── test_pipeline.py
│   │   └── test_modules/
│   │       ├── __init__.py
│   │       ├── test_preprocess.py
│   │       └── test_emotion_detector.py
│   └── test_voice/
│       ├── __init__.py
│       └── test_tts.py
│
├── pyproject.toml
├── requirements.txt
└── README.md
```

---

## 模块详细设计

### 1. Config 模块

**职责**: 统一管理所有模块的 JSON 配置

```python
# config/settings.py
@dataclass
class AppConfig:
    llm: LLMConfig
    voice: VoiceConfig
    souls_path: Path

@dataclass
class LLMConfig:
    provider: str              # openai | anthropic | gemini | ollama
    api_key: str
    model: str
    base_url: str | None = None

@dataclass
class VoiceConfig:
    provider: str             # fish_speech | ...
    model_path: str
    speaker: str

# config/loader.py
class ConfigLoader:
    def load(config_path: Path) -> AppConfig
    def reload() -> AppConfig   # 热重载配置

# config/settings.py
class Settings:
    _instance: Settings | None = None

    def get() -> AppConfig
    def update(partial: dict)   # 更新部分配置

# 用法
config = Settings.get().llm
```

**配置示例**:
```json
// config/llm.json
{
  "provider": "openai",
  "api_key": "sk-...",
  "model": "gpt-4o",
  "base_url": null
}

// config/voice.json
{
  "provider": "fish_speech",
  "model_path": "./models/fish-speech",
  "speaker": "demo_speaker"
}
```

---

### 2. LLM 模块

**职责**: 封装底层 LLM，提供统一接口，支持多 Provider

```python
# llm/base.py
class LLMClient(ABC):
    @abstractmethod
    async def chat(messages: list[ChatMessage]) -> str: ...

    @abstractmethod
    async def stream(messages: list[ChatMessage]) -> AsyncGenerator[str]: ...

# llm/manager.py
class LLMManager:
    def get_client(config: LLMConfig) -> LLMClient

    async def test_connection(config: LLMConfig) -> bool

# llm/providers/openai.py
class OpenAIClient(LLMClient):
    def __init__(self, config: LLMConfig)
    async def chat(messages) -> str
    async def stream(messages) -> AsyncGenerator[str]
```

**支持的 Provider**:
| Provider | 说明 |
|----------|------|
| `openai` | OpenAI API (GPT-4o, GPT-4o-mini) |
| `anthropic` | Anthropic Claude |
| `gemini` | Google Gemini |
| `ollama` | 本地模型 (无需 API Key) |

---

### 3. Soul 模块

**职责**: 通过多维度构建完整的数字人格，每个维度一个 md 文件

```python
# soul/profile.py
@dataclass
class SoulProfile:
    soul_id: str
    dimensions: dict[str, str]  # dimension_name -> md_content

# soul/loader.py
class SoulLoader:
    def load(soul_id: str) -> SoulProfile

    def load_dimension(soul_id: str, dimension: str) -> str

    def save_dimension(soul_id: str, dimension: str, content: str)

# soul/prompt_builder.py
class SoulPromptBuilder:
    def build(profile: SoulProfile) -> str
    # 将 10 个维度的 md 内容编译成 System Prompt
```

**维度定义** (10个维度):

| 维度 | 文件名 | 说明 |
|------|--------|------|
| basic_info | basic_info.md | 姓名/性别/年龄/籍贯/职业/生卒 |
| personality | personality.md | 性格标签/MBTI/情绪表达方式 |
| life_experiences | life_experiences.md | 人生经历时间线 |
| relationships | relationships.md | 社会关系图 |
| hobbies | hobbies.md | 爱好与熟练度 |
| special_habits | special_habits.md | 特殊习惯 |
| values_beliefs | values_beliefs.md | 价值观与世界观 |
| emotional_anchors | emotional_anchors.md | 情感锚点 |
| linguistic_fingerprint | linguistic_fingerprint.md | 语言指纹 |
| knowledge_domain | knowledge_domain.md | 知识与专业边界 |

**Soul 档案目录结构**:
```
config/souls/{soul_id}/
├── basic_info.md            # 姓名/性别/年龄/籍贯/职业/生卒
├── personality.md          # 性格标签/MBTI/情绪表达方式
├── life_experiences.md     # 人生经历时间线
├── relationships.md        # 社会关系图
├── hobbies.md              # 爱好与熟练度
├── special_habits.md       # 特殊习惯
├── values_beliefs.md       # 价值观与世界观
├── emotional_anchors.md     # 情感锚点
├── linguistic_fingerprint.md  # 语言指纹
└── knowledge_domain.md     # 知识与专业边界
```

**MD 文件格式规范**:

所有 md 文件统一采用以下格式：

```markdown
# 维度中文名称

## identity
字段: 值
字段: 值

## description
维度描述文本，可以包含多行内容。
```

例如 `basic_info.md`:
```markdown
# 基本信息

## identity
name: 王奶奶
gender: female
age: 75
birthplace: 浙江杭州
occupation: 退休教师
birth_year: 1948
death_year: 2023

## description
王奶奶是一位慈祥的退休小学教师，在杭州生活了大半辈子。
喜欢给孩子们讲故事，擅长做红烧肉。
```

**config/circumstances.md 场景描述格式**:
```markdown
# 当前场景

## context
- 用户身份: [与逝者的关系]
- 当前时间: [对话发生的时间]
- 用户情绪: [当前情绪状态]
- 对话目的: [为什么发起这次对话]

## description
详细描述这次对话的背景和情境。
```

---

### 4. Agent-Core 模块

**职责**: Agent 循环 + Pipeline 架构 + 可扩展模块

```python
# agent/loop.py
class AgentLoop:
    def __init__(
        self,
        llm_client: LLMClient,
        soul_loader: SoulLoader,
        config: AppConfig
    )

    async def run(
        soul_id: str,
        user_message: str,
        session_id: str
    ) -> AsyncGenerator[str]:
        # Pipeline: Input → Preprocess → LLM → Postprocess → Output
        ...

# agent/pipeline.py
class Pipeline:
    def __init__(self)
    def add_module(name: str, module: PipelineModule)
    async def execute(ctx: PipelineContext) -> PipelineContext

class PipelineContext:
    soul_id: str
    session_id: str
    user_message: str
    soul_profile: SoulProfile | None
    llm_messages: list[ChatMessage]
    response: str

# agent/modules/preprocess.py
class PreprocessModule(PipelineModule):
    async def process(ctx: PipelineContext) -> PipelineContext
    # 职责: 加载 Soul Profile, 组装 Prompt

# agent/modules/emotion_detector.py
class EmotionDetectorModule(PipelineModule):
    async def process(ctx: PipelineContext) -> PipelineContext
    # 职责: 检测用户情绪 (规则引擎, ~5ms)

# agent/modules/postprocess.py
class PostprocessModule(PipelineModule):
    async def process(ctx: PipelineContext) -> PipelineContext
    # 职责: 输出质量验证, 指纹注入
```

---

### 5. Voice 模块

**职责**: 语音合成 (使用 Fish Speech)

```python
# voice/tts.py
class TTSService:
    def __init__(self, config: VoiceConfig)

    async def speak(
        text: str,
        speaker: str | None = None
    ) -> AsyncGenerator[bytes]:
        # 流式合成音频
        ...

    async def speak_sync(text: str) -> bytes
    # 同步合成完整音频
```

---

### 6. 前端设计

**页面**:
- `/` - 首页
- `/chat/[soul_id]` - 聊天界面
- `/settings` - 系统设置 (LLM 配置, API Key)
- `/souls/[soul_id]` - 灵魂档案管理

**核心组件**:
```tsx
// components/ChatWindow.tsx
function ChatWindow({ soulId }) {
  const [messages, setMessages] = useState([])
  const [input, setInput] = useState('')

  const sendMessage = async () => {
    // 调用后端 API
  }

  return (
    <div className="chat-container">
      <div className="messages">
        {messages.map(m => (
          <div key={m.id} className={m.role}>
            {m.content}
          </div>
        ))}
      </div>
      <div className="input-area">
        <input
          value={input}
          onChange={e => setInput(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && sendMessage()}
        />
        <button onClick={sendMessage}>发送</button>
      </div>
    </div>
  )
}

// components/SettingsPanel.tsx
function SettingsPanel() {
  const [llmConfig, setLLMConfig] = useState({
    provider: 'openai',
    apiKey: '',
    model: 'gpt-4o'
  })

  return (
    <div className="settings">
      <h2>LLM 配置</h2>
      <select value={llmConfig.provider}>
        <option value="openai">OpenAI</option>
        <option value="anthropic">Anthropic</option>
        <option value="gemini">Google Gemini</option>
        <option value="ollama">Ollama (本地)</option>
      </select>
      <input
        type="password"
        placeholder="API Key"
        value={llmConfig.apiKey}
        onChange={e => setLLMConfig({...llmConfig, apiKey: e.target.value})}
      />
      <input
        placeholder="Model"
        value={llmConfig.model}
        onChange={e => setLLMConfig({...llmConfig, model: e.target.value})}
      />
    </div>
  )
}
```

---

## 实施计划

### Phase 1: 基础架构
- [ ] 项目初始化 (pyproject.toml, requirements.txt)
- [ ] Config 模块 (JSON 配置加载 + 测试 tests/test_config.py)
- [ ] LLM 模块 (Manager + OpenAI Provider + 测试 tests/test_llm/)
- [ ] Soul 模块 (Profile + Loader + PromptBuilder + 测试 tests/test_soul/)
- [ ] Agent-Core (Loop + Pipeline + 测试 tests/test_agent/)
- [ ] 前端基础 (ChatWindow + SettingsPanel)

### Phase 2: 语音模块
- [ ] TTS Service 接口定义 + 测试 tests/test_voice/

### Phase 3: 高级功能
- [ ] 其他 LLM Provider (Anthropic, Gemini, Ollama)
- [ ] Emotion Detector 模块
- [ ] 记忆模块 (短期 + 长期)

---

## 验证方式

1. **单元测试**: 每个模块独立测试
2. **集成测试**: 端到端对话流程
3. **手动验证**: 启动应用, 创建灵魂, 进行对话