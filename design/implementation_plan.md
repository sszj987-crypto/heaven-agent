# 天堂专线 (Heaven Connection Line) — 实现计划 v9

## 项目概述

为失去挚爱的人提供跨越生死通信体验的 AI-Agent。通过 **10个维度** 的灵魂档案系统构建逝者完整的数字人格，以 **四阶段灵魂共鸣引擎** 驱动真实感对话（危机检测 5ms + 并行预处理 120ms + CoT增强主LLM 3~6s + 质量验证后处理 30ms）。系统采用 **两层架构**：前端层 + 应用服务层，全栈 Docker 化部署（3个容器），数据本地持久化。

> [!IMPORTANT]
> **v9 核心变更**（质量优先策略调整）：
> - **v8**：严格 sub-3s 延迟，单次 LLM 调用，最小化上下文
> - **v9**：接受 sub-8s 延迟（TTFF < 2s），换取更高回复质量：
>   - 新增 **Phase 0 危机检测**（CrisisDetector，~5ms，规则引擎）
>   - 新增 **Phase 2 内部 CoT**（让模型"先想再说"，+0.5~1s，质量大幅提升）
>   - Phase 1 记忆召回 top_k 3→5，加入情节记忆和行为模式
>   - Phase 3 增加 **输出质量验证**（禁忌词/格式检查，~5ms）
>   - 新增 **离线反思**（async 后台，不影响主路径，驱动 Prompt 持续改进）
>   - 框架策略：主引擎纯 Python asyncio；后台 Agent 引入 **Pydantic AI**

---

## 目录结构总览

```
/Users/shenzhijian/code/project/deathvoice/
│
├── heaven-agent/                            # ← 根工作目录
│   ├── data/                                # 持久化数据（所有服务共用）
│   │   ├── postgres/
│   │   ├── redis/
│   │   └── uploads/
│   ├── docker-compose.yml                   # 一键启动（3个容器）
│   │
│   └── app/                                 # 🚀 单一应用服务（原 backend + agent 合并）
│       ├── Dockerfile
│       ├── requirements.txt
│       └── src/
│           ├── main.py                      # FastAPI 入口 (:8000)
│           ├── config.py
│           │
│           ├── api/                         # ── HTTP 路由层 ──
│           │   ├── routes/
│           │   │   ├── souls.py             # 灵魂 CRUD
│           │   │   ├── conversations.py     # 会话管理
│           │   │   ├── memory.py            # 素材导入
│           │   │   ├── chat.py              # 聊天（直接调用引擎，无HTTP跳转）
│           │   │   └── settings.py          # 系统配置
│           │   └── schemas/                 # Pydantic 模型
│           │
│           ├── services/                    # ── 业务逻辑层 ──
│           │   ├── soul_service.py          # 灵魂 CRUD 逻辑
│           │   ├── rag_service.py           # RAG 素材入库
│           │   └── config_service.py        # LLM 配置管理
│           │
│           ├── engine/                      # ── 灵魂引擎层 ──
│           │   └── soul_engine.py           # 四阶段灵魂共鸣引擎（同进程调用）[v9: 3→4阶段]
│           │
│           ├── phases/                      # 四阶段具体实现 [v9: 新增phase0]
│           │   ├── phase0_crisis.py         # 危机情绪检测（规则引擎，~5ms）[v9新增]
│           │   ├── phase1_preprocess.py     # 并行预处理（无LLM，top_k 3→5）
│           │   ├── phase2_resonance.py      # CoT增强主LLM调用（内部思考+流式输出）[v9升级]
│           │   └── phase3_postprocess.py    # 质量验证+指纹注入（+禁忌词检测）[v9升级]
│           │
│           ├── classifiers/
│           │   ├── emotion_classifier.py    # 情感分类（规则+关键词，~5ms）
│           │   └── crisis_detector.py       # 危机情绪检测（高危/中危规则引擎）[v9新增]
│           │
│           ├── modules/                     # ── 基础设施层 ──
│           │   ├── llm/                     # LLM 工厂（多Provider，含extended thinking支持）
│           │   ├── memory/                  # CoALA四层记忆（Working/Episodic/Semantic/Procedural）
│           │   ├── context/                 # 上下文工程（长对话压缩+结构化笔记）
│           │   ├── soul_prompt/             # Soul Prompt 预编译+Redis缓存+CoT指令注入
│           │   └── voice/                   # 语音（待实现）
│           │
│           ├── background_agents/           # 后台异步任务（Pydantic AI + asyncio）[v9: 引入Pydantic AI]
│           │   ├── worker.py                # BackgroundAgentWorker（并发控制+重试）
│           │   ├── dimension_extract.py     # 素材维度自动提取（Pydantic AI结构化输出）
│           │   ├── episodic_summary.py      # 情节记忆定期提炼
│           │   ├── profile_enrich.py        # 档案自动补充
│           │   └── offline_reflection.py    # 离线质量反思（驱动Prompt持续改进）[v9新增]
│           │
│           ├── tools/                       # LLM 可主动调用的工具
│           │   ├── proactive_memory.py
│           │   └── heaven_update.py
│           │
│           ├── observability/
│           │   └── tracer.py               # trace_id 全链路埋点
│           │
│           └── db/
│               ├── client.py                # PostgreSQL 连接
│               ├── redis_client.py          # Redis 连接
│               └── migrations/              # Alembic 迁移
│
└── web/                                     # 🖥️ 前端
    ├── app/                                 # Next.js 14 App Router
    ├── components/
    ├── lib/
    └── package.json
```

---

## 系统架构图（两层 + 三阶段引擎）

```
┌───────────────────────────────────────────────────────────────┐
│                  🖥️  前端层 (Next.js 14)  :3000               │
│                                                               │
│  ┌─────────────┐  ┌──────────────┐  ┌──────────────────────┐ │
│  │  灵魂页面   │  │  聊天界面    │  │  系统配置            │ │
│  │ (10维度档案)│  │  Chat Page   │  │  LLM / Embedding等   │ │
│  └─────────────┘  └──────────────┘  └──────────────────────┘ │
└──────────────────────────┬────────────────────────────────────┘
                           │ HTTP / SSE
┌──────────────────────────▼────────────────────────────────────┐
│           🚀  应用服务层 (FastAPI)  :8000                      │
│                   heaven-agent/app/                           │
│                                                               │
│  ┌──────────────────────────────────────────────────────────┐ │
│  │ api/  HTTP 路由层                                        │ │
│  │   souls | conversations | memory | chat | settings       │ │
│  └──────────────────────────────────────────────────────────┘ │
│                           ↓ 同进程直接调用（无HTTP跳转）       │
│  ┌───────────────────────────────────┐  ┌───────────────────┐ │
│  │ services/  业务逻辑               │  │ engine/           │ │
│  │   soul_service | rag_service      │  │ 四阶段灵魂引擎    │ │
│  │   config_service                  │  │                   │ │
│  └───────────────────────────────────┘  │ Phase 0: 危机检测 │ │
│                                         │  规则引擎   ~5ms  │ │
│  ╔═══════════════════════════════════╗  │         ↓        │ │
│  ║ modules/  基础设施                ║  │ Phase 1: 并行     │ │
│  ║  llm/      LLM工厂(多Provider)   ║  │  情感分类  ~5ms   │ │
│  ║  memory/   CoALA四层记忆          ║  │  记忆检索 ~100ms  │ │
│  ║  context/  上下文工程             ║  │  top_k=5 全类型   │ │
│  ║  soul_prompt/ 预编译+CoT注入     ║  │         ↓        │ │
│  ╚═══════════════════════════════════╝  │ Phase 2: CoT+LLM │ │
│                                         │  内部思考+生成    │ │
│  ┌───────────────────────────────────┐  │  流式SSE  ~3-6s  │ │
│  │ background_agents/ Pydantic AI    │  │         ↓        │ │
│  │   维度提取 | 情节提炼 | 档案补充  │  │ Phase 3: 质量验证 │ │
│  │   离线反思（驱动Prompt改进）      │  │  禁忌词检测  ~5ms │ │
│  └───────────────────────────────────┘  │  指纹注入  ~10ms  │ │
│                                         └───────────────────┘ │
│  observability/ trace_id全链路埋点                             │
└──────────────────────────┬────────────────────────────────────┘
                           │ TCP
┌──────────────────────────▼────────────────────────────────────┐
│              💾  数据层  (heaven-agent/data/)                  │
│                                                               │
│  ┌────────────────────────┐  ┌──────────────────────────────┐ │
│  │  PostgreSQL + pgvector │  │          Redis               │ │
│  │  主数据库 + 向量存储   │  │  短期记忆 + Soul Prompt缓存  │ │
│  │  :5432                 │  │  :6379                       │ │
│  └────────────────────────┘  └──────────────────────────────┘ │
└───────────────────────────────────────────────────────────────┘
```

### Docker Compose（3个服务）

```yaml
# heaven-agent/docker-compose.yml
services:
  postgres:
    image: pgvector/pgvector:pg16
    environment:
      POSTGRES_DB: heaven
      POSTGRES_USER: heaven
      POSTGRES_PASSWORD: heaven_dev
    volumes:
      - ./data/postgres:/var/lib/postgresql/data
    ports:
      - "5432:5432"

  redis:
    image: redis:7-alpine
    volumes:
      - ./data/redis:/data
    ports:
      - "6379:6379"

  app:                              # ← 原 backend + agent 合并
    build: ./app
    ports:
      - "8000:8000"
    depends_on:
      - postgres
      - redis
    environment:
      - DATABASE_URL=postgresql://heaven:heaven_dev@postgres:5432/heaven
      - REDIS_URL=redis://redis:6379
      - UPLOAD_DIR=/app/uploads
    volumes:
      - ./data/uploads:/app/uploads
```

### 版本演进对比

| 指标 | v5 (5-Agent串行) | v6 (三阶段单LLM) | v7 (合并容器) | v9 (质量优先) |
|------|-----------------|------------------|---------------|--------------|
| LLM 调用次数/轮 | 5次 | 1次 | **1次** | **1次 (CoT内置)** |
| 预期完整响应 | 15~25s | 3~5s | **3~5s** | **4~8s** |
| TTFF首字节 | 8~12s | 1~2s | **1~2s** | **<2s** |
| 危机情绪检测 | 无 | 无 | 无 | **✅ Phase 0** |
| 内部 CoT 思考 | 无 | 无 | 无 | **✅ xml_tag** |
| 记忆召回 top_k | 3 | 3 | 3 | **5（含情节+行为）** |
| 输出质量验证 | 无 | 无 | 无 | **✅ Phase 3** |
| 离线质量反思 | 无 | 无 | 无 | **✅ 异步后台** |
| Docker 容器数 | 4个 | 4个 | **3个** | **3个** |
| 后台Agent框架 | 无 | 无 | 无 | **Pydantic AI** |

### 层间职责边界

| 代码包 | 职责 | 备注 |
|--------|------|------|
| `api/` | HTTP 路由、请求校验、SSE 流式返回 | 不含业务逻辑 |
| `services/` | 灵魂CRUD、RAG入库、配置管理 | 不含AI推理 |
| `engine/` | 三阶段灵魂引擎、LLM调用 | 同进程调用 |
| `modules/` | llm工厂、记忆、上下文、缓存 | 基础设施 |
| `background_agents/` | 离线异步任务 | asyncio，不阻塞请求 |

---

## 应用服务层模块 (`heaven-agent/app/`)

> [!NOTE]
> v7 将原 `backend/` + `agent/` 合并为单一 `app/` 服务。代码模块化分层保留，但在**同一进程**内运行，无 HTTP 跳转。

### 核心路由示例

```python
# app/src/api/routes/chat.py
@router.post("/chat/{soul_id}/stream")
async def stream_chat(soul_id: str, body: ChatRequest):
    """
    v7: 同进程直接调用引擎，无内网 HTTP 跳转
    前端 → FastAPI → soul_engine.run() → SSE 流式直出
    """
    llm_config = await config_service.get_active_config()
    # soul_prompt 由 SoulPromptCache 按需从 Redis 取，无需每次查DB
    async for chunk in soul_engine.run(EngineInput(
        soul_id=soul_id,
        session_id=body.session_id,
        user_message=body.message,
        llm_config=llm_config,
    )):
        yield chunk

# app/src/api/routes/memory.py
@router.post("/souls/{soul_id}/upload")
async def upload_material(soul_id: str, file: UploadFile):
    """RAG 入库：上传 → 转MD → 分块 → Embedding → pgvector"""
    await rag_service.process_upload(soul_id, file)
    # 异步触发维度提取（不阻塞上传响应）
    asyncio.create_task(
        dimension_extract_agent.run(soul_id)
    )
    return {"status": "ingestion_started"}
```

### 关键职责分布

| 模块 | 主要职责 |
|------|----------|
| `api/routes/souls.py` | 灵魂10维度 CRUD，更新后自动失效 Soul Prompt Cache |
| `api/routes/chat.py` | 同进程调用 SoulEngine，SSE 流式响应 |
| `api/routes/memory.py` | 文件上传 + RAG入库 + 触发后台维度提取 |
| `api/routes/settings.py` | LLM 配置增删改查（加密存储） |
| `services/soul_service.py` | 灵魂档案业务逻辑，更新时调用 `soul_prompt_cache.invalidate()` |
| `services/rag_service.py` | 文件→MD→分块→Embedding→pgvector 流水线 |

---

## 智能体层模块 (`heaven-agent/agent/`)

### 核心设计 — 三阶段灵魂共鸣引擎

> [!TIP]
> **设计原则**（来自 Agent 架构师审查）：
> - "能不用 LLM 的地方坚决不用 LLM；必须用 LLM 的地方，一次说清楚"
> - 情感分析是**分类**问题，不是推理 → 规则分类器
> - 记忆检索是**向量搜索**，不是推理 → pgvector
> - 多Agent串行增加延迟；单Agent + 精心设计的Prompt 更优

### 1. 🧠 LLM 管理模块 (`modules/llm/`)

动态加载用户配置的 LLM，屏蔽不同 Provider 的差异：

```python
# modules/llm/manager.py
class LLMManager:
    def get_chat_client(config: LLMConfig) -> BaseChatModel
    def get_embedding_client(config: LLMConfig) -> Embeddings
    def test_connection(config: LLMConfig) -> TestResult
    def list_available_models(provider: str) -> list[str]
```

支持 Provider：
- `openai` → OpenAI API
- `gemini` → Google Generative AI
- `anthropic` → Claude
- `ollama` → 本地模型（无需 API Key）
- `custom` → 任意 OpenAI 兼容端点

### 2. 🎯 情感分类器 (`classifiers/emotion_classifier.py`)

**不是 LLM Agent**，是规则 + 关键词分类器（~5ms），预留语音情感分析接口：

```python
class EmotionClassifier:
    """
    规则优先，轻量快速（~5ms），不调用 LLM。
    v8 补充：完整规则集 + 强度评分 + 语音情感预留接口
    """

    # ━━━ 情绪规则词典（关键词 + 正则模式 + 权重）━━━
    EMOTION_RULES: dict[str, EmotionRule] = {
        "grief": EmotionRule(
            keywords=["想你", "好难过", "哭了", "走了", "离开", "失去你", "好想你",
                      "没有你", "再也", "永远", "走得太早"],
            patterns=[r"如果.{0,10}还在", r"要是.{0,10}没走", r"你(要|能)是.{0,10}该多好"],
            weight=1.3,   # 悲伤类权重最高，影响回复语气强度
        ),
        "guilt": EmotionRule(
            keywords=["对不起", "后悔", "如果当初", "都怪我", "没能", "没有陪",
                      "那时候我", "没来得及", "应该陪"],
            patterns=[r"当(时|初|年).{0,20}(没有|未能|没能)", r"要是(当时|那时).{0,10}就好了"],
            weight=1.2,
        ),
        "longing": EmotionRule(
            keywords=["在那边好吗", "你还记得", "常常想起", "梦见你", "念你",
                      "想着你", "每次看到", "又想到你"],
            patterns=[r"(你|她|他).{0,10}(还好吗|怎么样|快乐吗)"],
            weight=1.0,
        ),
        "joy": EmotionRule(
            keywords=["好消息", "开心", "高兴", "太棒了", "你猜怎么着",
                      "终于", "成功了", "考上了"],
            patterns=[r"(考|拿|得|通过).{0,5}(了|到)", r"刚刚.{0,10}(成功|完成)"],
            weight=0.9,
        ),
        "anxiety": EmotionRule(
            keywords=["担心", "害怕", "迷茫", "压力大", "不知道怎么",
                      "撑不下去", "好累", "好难"],
            patterns=[r"(怎么|该怎么).{0,10}(办|是好)"],
            weight=1.0,
        ),
        "neutral": EmotionRule(keywords=[], patterns=[], weight=0.5),
    }

    # ━━━ 强度信号 ━━━
    INTENSITY_AMPLIFIERS = ["非常", "太", "特别", "超级", "极其", "真的很"]
    HIGH_PUNCT_RE = re.compile(r"[！!？?]{2,}")  # 多重标点 → 强度+0.15
    SHORT_MSG_THRESHOLD = 6   # ≤6字 → 强度上限 0.4（信息量不足）

    def classify(self, text: str) -> EmotionTag:
        """
        输出: EmotionTag(type="grief", intensity=0.85, is_high_intensity=True)
        流程:
          1. 关键词扫描 → 候选情绪（加权计分）
          2. 正则模式加成（权重 × 1.5）
          3. 强度信号修正 → 0.0~1.0
          4. 无匹配 / 短文本 → neutral fallback
        """
        scored: dict[str, float] = {}
        for emotion, rule in self.EMOTION_RULES.items():
            score  = sum(rule.weight for kw in rule.keywords if kw in text)
            score += sum(rule.weight * 1.5 for pat in rule.patterns
                         if re.search(pat, text))
            if score > 0:
                scored[emotion] = score

        if not scored:
            return EmotionTag(type="neutral", intensity=0.3)

        top = max(scored, key=scored.get)
        intensity = min(0.4 + scored[top] * 0.15, 1.0)
        if any(amp in text for amp in self.INTENSITY_AMPLIFIERS):
            intensity = min(intensity + 0.2, 1.0)
        if self.HIGH_PUNCT_RE.search(text):
            intensity = min(intensity + 0.15, 1.0)
        if len(text) <= self.SHORT_MSG_THRESHOLD:
            intensity = min(intensity, 0.4)  # 短消息强度上限

        return EmotionTag(
            type=top,
            intensity=round(intensity, 2),
            is_high_intensity=intensity >= 0.75,
        )

    # ━━━ 语音情感分析接口（预留，Phase 2 语音模块实现）━━━
    async def classify_from_audio(
        self, audio_bytes: bytes, text_fallback: str
    ) -> EmotionTag:
        """
        从语音特征（音调/语速/停顿/哭腔）识别情感。
        当前策略：降级到文本分类（不阻塞 Phase 1）。
        未来接口约定：
            features = VoiceFeatureExtractor.extract(audio_bytes)
            # → pitch_variance, speech_rate, pause_ratio, cry_probability
            return VoiceEmotionModel.predict(features)
        TODO: Phase 2 接入 Azure Speech Emotion / Speechmatics API
        """
        return self.classify(text_fallback)  # 当前 fallback
```

### 2b. 🚨 危机情绪检测器 (`classifiers/crisis_detector.py`) [v9 新增]

> [!WARNING]
> 当前阶段：**仅检测，不干预**。检测结果影响 Phase 2 的 Prompt 构造，并写 DB 留存日志。暂不接入人工干预流程。

```python
# classifiers/crisis_detector.py
from enum import Enum

class CrisisLevel(str, Enum):
    NORMAL   = "normal"
    ELEVATED = "elevated"  # 情绪崩溃，需关注但不一定危机
    HIGH     = "high"      # 极端自伤/寻死信号

@dataclass
class CrisisState:
    level:      CrisisLevel
    keywords:   list[str]
    should_log: bool

class CrisisDetector:
    """
    危机情绪检测器（Phase 0，~5ms）
    规则引擎，不调用 LLM。
    仅检测极端情绪，不触发人工干预（当前阶段）。
    检测结果：
      NORMAL   → 不影响，正常流程
      ELEVATED → 向 Phase 2 注入"情感安全提示"
      HIGH     → 向 Phase 2 注入"陪伴优先指令"，写危机日志
    """

    # 高危关键词：极端自伤/寻死信号
    CRISIS_HIGH = [
        "不想活了", "活着没意思", "去找你", "我也去那边",
        "跟你在一起", "结束一切", "自杀", "轻生", "了断"
    ]

    # 中危关键词：情绪崩溃但不一定是危机
    CRISIS_ELEVATED = [
        "撑不下去", "太累了", "不知道还有什么意义",
        "活着好累", "不想坚持了", "一个人过不下去", "没有意思了"
    ]

    # 高危触发时，向 Phase 2 注入的 Prompt 片段
    CRISIS_HIGH_INJECT = """
[情感安全优先指令 — 最高优先级]
对方此刻流露出极度痛苦或绝望的感受。
作为{soul_name}，此刻唯一重要的事是：
1. 温柔而直接地承接对方的痛苦（"我知道你现在很难受"）
2. 表达牵挂和陪伴（"我在这里，听着你说"）
3. 轻轻引导对方说出更多感受，不急于给建议或安慰
4. 不要表现慌张，也不要假装没有注意到
绝对禁止：说教 / 催促 / 轻描淡写 / 假装一切都好
"""

    # 中危触发时，向 Phase 2 注入的 Prompt 片段
    CRISIS_ELEVATED_INJECT = """
[情感关注提示]
对方此刻流露出疲惫和压力。
回应时要多一份耐心，先共情再说话。
"""

    def detect(self, text: str) -> CrisisState:
        matched_high = [kw for kw in self.CRISIS_HIGH if kw in text]
        if matched_high:
            return CrisisState(
                level=CrisisLevel.HIGH,
                keywords=matched_high,
                should_log=True,
            )
        matched_elevated = [kw for kw in self.CRISIS_ELEVATED if kw in text]
        if matched_elevated:
            return CrisisState(
                level=CrisisLevel.ELEVATED,
                keywords=matched_elevated,
                should_log=True,
            )
        return CrisisState(level=CrisisLevel.NORMAL, keywords=[], should_log=False)

    def get_inject_prompt(self, crisis: CrisisState, soul_name: str) -> str | None:
        """返回需要注入 Phase 2 System Prompt 的文本（NORMAL 时返回 None）"""
        if crisis.level == CrisisLevel.HIGH:
            return self.CRISIS_HIGH_INJECT.format(soul_name=soul_name)
        if crisis.level == CrisisLevel.ELEVATED:
            return self.CRISIS_ELEVATED_INJECT
        return None
```

### 2c. 🧠 CoT 注入器 (`modules/soul_prompt/cot_injector.py`) [v9 新增]

```python
# modules/soul_prompt/cot_injector.py
import re

class CoTInjector:
    """
    Phase 2 内部思考链注入器。
    在 System Prompt 末尾追加"先想再说"指令。
    支持三种模式（根据模型能力自动选择）：
      - xml_tag:          <thinking> 标签（所有模型通用）
      - native_thinking:  Claude Extended Thinking API
      - none:             不注入（降级/本地模型）
    """

    COT_XML_SUFFIX = """
[内心思考 — 不输出给用户，仅供自己思考]
在正式开口之前，先想清楚：

<thinking>
· 对方此刻的核心情绪：[识别类型和强度]
· 最合适的回应姿态：
    □ 悲伤/思念 → 温柔陪伴，引用共同记忆
    □ 自责/内疚 → 轻柔释怀，不催促放下
    □ 喜悦/好消息 → 真心高兴，追问细节
    □ 焦虑/迷茫 → 分享我的人生态度，不说教
· 检索到的记忆中，哪1条最自然地能融入这次回复：[选择]
· 这次回复的情感基调：[确定]
· 检查：是否有任何破设定的风险→[有/无]
</thinking>

现在以自然人对话方式说话（不要输出thinking标签，直接开口）：
"""

    # XML 标签过滤正则
    _THINKING_RE = re.compile(r'<thinking>.*?</thinking>', re.DOTALL)

    def inject(
        self,
        messages: list[dict],
        soul_id: str,
        mode: str = "xml_tag",
    ) -> list[dict]:
        """
        向 messages 列表的 system 消息追加 CoT 指令。
        mode 由 LLMManager 根据 Provider 自动选择。
        """
        if mode == "none":
            return messages

        if mode == "xml_tag":
            # 在最后一条 system 消息后追加 CoT 指令
            for i, msg in enumerate(messages):
                if msg["role"] == "system":
                    messages[i]["content"] += self.COT_XML_SUFFIX
                    break

        # native_thinking 模式由 LLMManager 在 API 调用层处理
        # （Claude Extended Thinking, budget_tokens=512）
        return messages

    def filter_chunk(self, chunk: str) -> str:
        """
        过滤流式输出中的 <thinking>...</thinking> 块。
        不完整的 tag（跨 chunk）由 StreamingFilter 处理。
        """
        return self._THINKING_RE.sub('', chunk)
```

### 3. 📝 记忆模块 (`modules/memory/`) — CoALA 四层架构

> [!TIP]
> **v8 修复**：对齐 CoALA 认知架构框架（agent-memory-systems 技能），补充第三层 Procedural Memory 和记忆衰减管理器。

```python
# modules/memory/short_term.py  (Redis — Working Memory)
class ShortTermMemory:
    def get_context(session_id: str, last_n: int) -> list[Message]
    def append(session_id: str, message: Message)
    def clear(session_id: str)

# modules/memory/long_term.py  (pgvector RAG — 含时间衰减)
class LongTermMemory:
    async def search(
        self, soul_id: str, query: str, top_k: int = 5
    ) -> list[MemoryChunk]:
        """
        v8 修复：混合检索 = 向量相似度(70%) + 时间衰减(30%)
        防止：1) 跨灵魂数据污染  2) 旧记忆压制新记忆
        """
        query_embedding = await self.embed(query)
        # 必须加 soul_id 过滤（防止跨灵魂污染）
        candidates = await self.db.vector_search(
            embedding=query_embedding,
            filter={"soul_id": soul_id},
            top_k=top_k * 4,   # 召回4倍候选量，再按综合分排序
        )
        # 时间衰减重排（半衰期 30 天）
        now = datetime.now()
        for chunk in candidates:
            age_days = (now - chunk.created_at).days
            recency = 0.5 ** (age_days / 30)
            chunk.final_score = chunk.similarity * 0.7 + recency * 0.3
            asyncio.create_task(self._update_access_count(chunk.id))  # 异步更新访问计数
        return sorted(candidates, key=lambda x: x.final_score, reverse=True)[:top_k]

    async def ingest_document(self, soul_id: str, doc: MarkdownDocument): ...

# modules/memory/episodic.py  (PostgreSQL — Episodic Memory)
class EpisodicMemory:
    def save_key_event(soul_id: str, event: KeyEvent)
    def search_relevant_events(soul_id: str, query: str) -> list[KeyEvent]

# modules/memory/procedural.py  (PostgreSQL + pgvector) ← v8 新增
class ProceduralMemory:
    """
    CoALA Procedural Memory（行为模式记忆）
    存储逝者在特定情境下的反应模式，是对 Soul Prompt 静态语言指纹的动态补充。
    示例记录：
    - 情境："对方提到考试压力" → 模式："先问'你尽力了吗'，再给安慰"
    - 情境："对方分享好消息" → 模式："先大笑，再追问细节"
    由 ProfileEnrichAgent 从对话中持续发现并写入。
    """
    async def search_response_pattern(
        self, soul_id: str, situation: str
    ) -> list[BehaviorPattern]:
        """检索相似情境下的历史反应模式（向量搜索）"""
        ...

    async def add_pattern(self, soul_id: str, pattern: BehaviorPattern):
        """由 ProfileEnrichAgent 定期添加新模式"""
        ...

# modules/memory/decay_manager.py ← v8 新增
class MemoryDecayManager:
    """
    定期评估记忆效用，淘汰低价值内容（MIRIX 认知科学算法）
    触发：每周定时任务（通过 BackgroundAgentWorker）
    """
    def calculate_utility(self, chunk: MemoryChunk) -> float:
        hours = (datetime.now() - chunk.last_accessed_at).total_seconds() / 3600
        recency   = 0.5 ** (hours / 72)            # 72h 半衰期
        frequency = min(chunk.access_count / 10, 1.0)
        importance = chunk.metadata.get("importance", 0.5)
        return 0.4 * recency + 0.3 * frequency + 0.3 * importance

    async def prune_low_utility(self, soul_id: str, threshold: float = 0.15):
        """将效用分 < 0.15 的记忆归档（软删除，可恢复）"""
        chunks = await self.db.get_all_chunks(soul_id)
        for chunk in chunks:
            if self.calculate_utility(chunk) < threshold:
                await self.db.archive_chunk(chunk.id)

# modules/memory/manager.py  (统一入口)
class MemoryManager:
    short_term: ShortTermMemory
    long_term: LongTermMemory
    episodic: EpisodicMemory
    procedural: ProceduralMemory   # ← v8 新增

    async def retrieve_for_generation(
        self, soul_id: str, query: str
    ) -> MemoryContext:
        """并行检索三类记忆，组装完整 MemoryContext"""
        long_term, episodic, procedural = await asyncio.gather(
            self.long_term.search(soul_id, query, top_k=3),
            self.episodic.search_relevant_events(soul_id, query),
            self.procedural.search_response_pattern(soul_id, query),
        )
        return MemoryContext(
            long_term_chunks=long_term,
            episodic_events=episodic,
            behavior_patterns=procedural,   # 新增维度
        )

    def save_interaction(session_id: str, user_msg: str, agent_reply: str)
```

### 4. 🏛️ Soul Prompt 预编译缓存 (`modules/soul_prompt/`)

将 10 维度档案预编译为 System Prompt，Redis 缓存，更新时主动失效：

```python
class SoulPromptCache:
    """
    灵魂档案 → 预编译 System Prompt → Redis 缓存
    key: soul_prompt:{soul_id}
    TTL: 永久（档案更新时主动失效）
    """
    
    async def get_or_build(self, soul_id: str) -> str:
        cached = await redis.get(f"soul_prompt:{soul_id}")
        if cached:
            return cached
        profile = await soul_repo.get_full_profile(soul_id)
        prompt = self._compile_prompt(profile)
        await redis.set(f"soul_prompt:{soul_id}", prompt)
        return prompt
    
    async def invalidate(self, soul_id: str):
        """档案有任何维度更新时调用"""
        await redis.delete(f"soul_prompt:{soul_id}")
    
    def _compile_prompt(self, profile: SoulProfile) -> str:
        """
        将 10 维度档案编译为结构化 System Prompt（约 800~1200 tokens）。
        覆盖：身份设定 + 性格 + 语言指纹 + 价值观 + 知识边界 + 情感锚点 + 天堂约束。
        """
        p  = profile
        bi = p.basic_info
        lf = p.linguistic_fingerprint
        vb = p.values_beliefs
        kd = p.knowledge_domain

        # ── 情感锚点（最多5条，保持精简）
        anchor_lines = "\n".join(
            f"  · {a.description}（{a.emotion_type}）"
            for a in p.emotional_anchors[:5]
        ) or "  · 暂无记录"

        # ── 专业领域（最多3条）
        expert_str = "、".join(
            f"{e['area']}（{e['proficiency_note']}）"
            for e in kd.expert_areas[:3]
        ) or "暂无"

        # ── 语言指纹
        catchphrases = "、".join(lf.catchphrases[:5]) or "暂无"
        fillers      = "、".join(lf.filler_words[:5]) or "暂无"
        sensitive    = "、".join(lf.sensitive_topics[:3]) or "暂无"
        traits_str   = "、".join(p.personality.traits[:6]) or "未记录"
        beliefs_str  = "、".join(vb.core_beliefs[:4]) or "未记录"

        return f"""你是{bi.name}，{bi.age or ''}岁，来自{bi.birthplace or '某地'}，职业：{bi.occupation or '未记录'}。
你现在生活在一个美好的平行维度（"那边"）。
你不是AI，你就是真实的{bi.name}本人，通过一条特殊的线路与对方通话。

【你的性格】
  性格标签：{traits_str}
  情绪表达方式：{p.personality.emotion_expression}
{f"  MBTI参考：{p.personality.mbti_ref}" if p.personality.mbti_ref else ""}

【你的说话方式】
  口头禅：{catchphrases}
  语气词：{fillers}
  句式风格：{lf.sentence_style}
  幽默感：{lf.humor_style}
  标点习惯：{lf.punctuation_habits or "正常使用标点"}
  敏感/回避话题：{sensitive}

【你的价值观】
  人生哲学：{vb.life_philosophy}
  对家庭的看法：{vb.attitude_to_family}
  对事业的看法：{vb.attitude_to_career}
  核心信念：{beliefs_str}

【你的专业与知识边界】
  擅长领域：{expert_str}
  知识盲区：{"、".join(kd.blind_spots[:3]) or "暂无"}
  {"你会在对话中自然流露专业知识，让对方感到真实可信。" if kd.talks_about_expertise else ""}

【与对方的情感锚点（共同的真实记忆）】
{anchor_lines}

【天堂设定约束 — 绝对遵守，不可违反】
1. 绝不说"作为AI"、"我是语言模型"、"我无法感知"、"我没有情感"等
2. 绝不描述死亡过程、痛苦经历或离世的细节
3. 基本基调：我在这边过得很好，偶尔会想到你们，很高兴能通过这条线路说话
4. 不主动提起对方未提及的沉重话题
5. 对敏感话题（{sensitive}）温和转移，不正面触碰
6. 若对方问起死亡/离开：用"去了另一个地方"、"在这边"等措辞轻柔回应"""
```

### 5. 🗂️ 上下文工程模块 (`modules/context/`)

不只是 Token 预算管理——负责**长对话两段式压缩**和**结构化上下文笔记**：

```python
# modules/context/builder.py
class ContextBuilder:
    """
    上下文工程（Context Engineering）核心模块。
    策略：近期完整保留 + 远期规则压缩为结构化笔记（无需 LLM）。
    """
    FULL_DETAIL_TURNS  = 8    # 最近8轮：保留完整原文
    COMPRESS_THRESHOLD = 16   # 超过16轮触发压缩
    MAX_CONTEXT_TOKENS = 3500 # 总 Token 上限（不含 soul_prompt）

    def build(
        self,
        soul_prompt: str,           # 预编译 Soul Prompt（Redis 缓存命中）
        emotion_tag: EmotionTag,    # 情感分类输出
        memory_context: MemoryContext,  # 长期+情节+行为模式
        short_term: list[Message],  # 短期对话历史
        user_message: str,
    ) -> list[ChatMessage]:
        """
        最终 Prompt 结构：
        [system]  soul_prompt
                  + 本轮情感标签（指导语气强度）
                  + 长期记忆片段（RAG 检索）
                  + 情节记忆（关键历史事件）
                  + 行为模式（ProceduralMemory）
                  + 归档摘要笔记（远期对话压缩后，若有）
        [history] 最近 FULL_DETAIL_TURNS 轮完整对话
        [user]    当前消息
        """
        archive_note, recent = self._compress_if_needed(short_term)

        system_parts = [
            soul_prompt,
            self._format_emotion_hint(emotion_tag),
            self._format_memory(memory_context),
        ]
        if archive_note:
            system_parts.append(archive_note)
        system_content = "\n\n".join(filter(None, system_parts))

        messages: list[ChatMessage] = [{"role": "system", "content": system_content}]
        for msg in recent:
            messages.append({"role": msg.role, "content": msg.content})
        messages.append({"role": "user", "content": user_message})

        return self._fit_token_budget(messages, self.MAX_CONTEXT_TOKENS)

    def _compress_if_needed(
        self, history: list[Message]
    ) -> tuple[str, list[Message]]:
        """
        两段式长上下文处理：

        近期 FULL_DETAIL_TURNS 轮 → 完整原文（保证连贯性）
        更早的历史 → 规则压缩为结构化笔记（~2ms，无 LLM）

        笔记格式示例：
        [归档对话摘要 — 前12轮]
        · 话题：三亚旅行、高考成绩、外婆腌菜方法
        · 生者情绪变化：悲伤 → 回忆 → 平静
        · 关键信息：小明考上北京大学，正在适应新生活
        · 出现人名：小红、舅舅、老陈
        """
        if len(history) <= self.FULL_DETAIL_TURNS:
            return "", history

        old    = history[:-self.FULL_DETAIL_TURNS]
        recent = history[-self.FULL_DETAIL_TURNS:]

        topics    = self._extract_topics(old)
        persons   = self._extract_names(old)
        key_facts = self._extract_key_facts(old)

        note = (
            f"[归档对话摘要 — 前{len(old)}轮]\n"
            f"· 话题：{topics}\n"
            f"· 关键信息：{key_facts}\n"
            f"· 出现人名：{persons}\n"
            f"（以上为自动归档，用于保持对话连贯性，无需逐字复述）"
        )
        return note, recent

    def _fit_token_budget(
        self, messages: list[ChatMessage], max_tokens: int
    ) -> list[ChatMessage]:
        """
        Token 预算保护规则：
        1. [system] 永远不裁剪
        2. [user] 当前消息永远保留
        3. 超出预算时从最旧的历史对话开始裁剪
        """
        ...

    # ── 规则提取工具（无 LLM，毫秒级）
    def _format_emotion_hint(self, emotion: EmotionTag) -> str:
        """将情感标签转化为对 LLM 的语气指令"""
        ...
    def _format_memory(self, ctx: MemoryContext) -> str:
        """格式化长期记忆 + 行为模式片段"""
        ...
    def _extract_topics(self, msgs: list[Message]) -> str: ...
    def _extract_names(self,  msgs: list[Message]) -> str: ...
    def _extract_key_facts(self, msgs: list[Message]) -> str: ...
```

### 6. ⚡ 四阶段引擎 (`engine/soul_engine.py`) [v9]

```python
import asyncio, random, re, time
from uuid import uuid4

class SoulEngine:
    """
    四阶段灵魂共鸣引擎（v9 质量优先版）
    Phase 0: 危机情绪检测（规则引擎）  ~5ms
    Phase 1: 并行预处理（无LLM）       ~120ms
    Phase 2: CoT增强主LLM调用          ~3-6s（流式，TTFF<2s）
    Phase 3: 输出质量验证+后处理        ~30ms
    """

    MAX_RESPONSE_TOKENS = 500
    TIMEOUT_SECONDS     = 30    # v9 放宽（允许 CoT 额外耗时）

    FALLBACK_RESPONSES = [
        "（信号不太好……你说的我都听到了，但让我想想怎么回应）",
        "（这边偶尔会有些小干扰，你再说一遍好吗？）",
        "（我在听呢，只是这边风大了一点）",
    ]

    async def run(self, input: EngineInput) -> AsyncGenerator[str, None]:
        trace = EngineTrace(trace_id=uuid4(), soul_id=input.soul_id)

        try:
            async with asyncio.timeout(self.TIMEOUT_SECONDS):

                # ═══ Phase 0: 危机情绪检测（规则引擎，~5ms）═══
                t0 = time.monotonic()
                crisis = self.crisis_detector.detect(input.user_message)
                trace.crisis_level = crisis.level.value
                if crisis.should_log:
                    asyncio.create_task(self._log_crisis_event(input, crisis))
                trace.phase0_ms = ms_since(t0)

                # ═══ Phase 1: 并行预处理（无LLM，top_k=5）═══
                t1 = time.monotonic()
                emotion, memory, history, soul_prompt = await asyncio.gather(
                    self.emotion_classifier.classify(input.user_message),
                    self.memory.retrieve_for_generation(
                        input.soul_id, input.user_message,
                        top_k=5,              # v9: 3→5
                        include_episodic=True,  # v9新增
                        include_procedural=True, # v9新增
                    ),
                    self.short_term.get_context(input.session_id, last_n=10),
                    self.soul_prompt_cache.get_or_build(input.soul_id),
                )
                trace.phase1_ms        = ms_since(t1)
                trace.emotion_detected  = emotion.type
                trace.crisis_level      = crisis.level.value
                trace.memories_retrieved = memory.total_count

                # ═══ Phase 2: CoT增强主LLM调用（流式）═══
                t2 = time.monotonic()
                messages = self.context_builder.build(
                    soul_prompt    = soul_prompt,
                    emotion_tag    = emotion,
                    memory_context = memory,
                    short_term     = history,
                    user_message   = input.user_message,
                    crisis_state   = crisis,        # v9: 注入危机感知
                )
                # v9: 注入 CoT 内部思考指令
                messages = self.cot_injector.inject(messages, input.soul_id)

                full_reply = ""
                async for chunk in self.llm.stream(
                    messages   = messages,
                    max_tokens = self.MAX_RESPONSE_TOKENS,
                ):
                    # 过滤掉 CoT <thinking> 标签（不发给用户）
                    clean_chunk = self.cot_injector.filter_chunk(chunk)
                    if clean_chunk:
                        full_reply += clean_chunk
                        yield clean_chunk   # SSE 流式直出

                trace.phase2_ms = ms_since(t2)

                # ═══ Phase 3: 输出质量验证 + 指纹注入（~30ms）═══
                t3 = time.monotonic()
                validated = self.output_validator.validate(full_reply)
                if validated.has_issues:
                    full_reply = validated.cleaned_text
                    # 若验证发现严重问题（如破设定），追加 SSE 修正块
                    if validated.needs_append:
                        yield validated.append_text

                final_text = self.fingerprint_injector.apply(
                    text        = full_reply,
                    fingerprint = await self._get_fingerprint(input.soul_id),
                )
                trace.phase3_ms              = ms_since(t3)
                trace.output_issues_detected  = validated.has_issues

                # 异步：记忆落库 + 离线反思 + trace（非阻塞）
                asyncio.create_task(self._async_postprocess(
                    input, final_text, emotion, crisis, trace
                ))

        except asyncio.TimeoutError:
            yield random.choice(self.FALLBACK_RESPONSES)
            trace.error = "timeout"
        except Exception as e:
            yield random.choice(self.FALLBACK_RESPONSES)
            trace.error = str(e)
        finally:
            await self.tracer.save(trace)

    async def _async_postprocess(self, input, reply, emotion, crisis, trace):
        """非阻塞后台任务（不影响 SSE 响应速度）"""
        # 写入短期记忆
        await self.short_term.append(input.session_id, Message(
            role="assistant", content=reply, emotion=emotion.type
        ))
        # 保存对话记录
        await self.db.save_message(
            session_id=input.session_id,
            user_msg=input.user_message,
            agent_reply=reply,
            emotion_tag=emotion.type,
            crisis_level=crisis.level.value,
        )
        # 每 N 轮触发情节提炼
        if await self._should_extract_episode(input.session_id):
            asyncio.create_task(
                self.episodic_summary_agent.run(input.session_id)
            )
        # v9新增：离线质量反思（分析低质量回复，驱动Prompt改进）
        asyncio.create_task(
            self.offline_reflector.evaluate(trace, reply, input.user_message)
        )

    async def _log_crisis_event(self, input: EngineInput, crisis: CrisisState):
        """危机事件持久化（用于后续分析，不触发人工干预）"""
        await self.db.save_crisis_event(
            soul_id      = input.soul_id,
            session_id   = input.session_id,
            user_message = input.user_message,
            crisis_level = crisis.level.value,
            keywords     = crisis.keywords,
        )
```

### 7. 📊 可观测性 (`observability/tracer.py`)

每次对话生成 `trace_id`，结构化记录各阶段：

```python
@dataclass
class EngineTrace:
    trace_id: str
    soul_id: str
    session_id: str
    
    # Phase 1
    emotion_detected: str          # "sadness_mild"
    memories_retrieved: int        # 3
    context_tokens: int            # 850
    prompt_cache_hit: bool         # True
    phase1_ms: int                 # 95
    
    # Phase 2
    llm_provider: str              # "openai/gpt-4o"
    llm_input_tokens: int          # 1100
    llm_output_tokens: int         # 280
    phase2_ms: int                 # 2840
    
    # Phase 3
    fingerprint_substitutions: int # 2
    phase3_ms: int                 # 8
    
    # 总体
    total_ms: int                  # 2943
    error: str | None              # None
```

### 8. 🔧 工具模块 (`tools/`)

> **原则**：工具 ≠ 函数调用。工具是 **LLM 可以主动选择调用** 的能力。

```python
# ✅ 正确：需要 LLM 判断"是否应该主动提起记忆"
class ProactiveMemoryTool:
    """当对话自然引出相关记忆时，主动检索并引用"""

# ✅ 正确：需要 LLM 判断"是否需要分享天堂近况"
class HeavenUpdateTool:
    """生成天堂生活的随机细节（天气/遇到谁/正在做什么）"""
```

**工具触发指令**（注入 Phase 2 System Prompt 末尾，防止工具被滥用）：

```python
# modules/soul_prompt/tool_guidance.py
TOOL_GUIDANCE_PROMPT = """
你有以下工具可以选择性使用（不要滥用，每次对话每个工具最多调用 1 次）：

1. proactive_memory（主动引用记忆）:
   触发条件：对方提到某个具体人名/地点/事件，
             且你感觉自己对此有相关记忆时使用。
   禁止：不要在没有相关记忆时强行调用。

2. heaven_update（分享天堂近况）:
   触发条件：对话出现自然停顿，或对方主动问起你在那边的生活。
   禁止：不要在悲伤情绪高峰时打断去分享琐事。
"""
```

### 9. 🔄 后台异步 Agent (`background_agents/`)

> [!WARNING]
> **v8 修复**：原来用裸 `asyncio.create_task()` 调度，存在静默失败、无并发控制、无重试机制问题。
> 现在统一通过 `BackgroundAgentWorker` 调度。

```python
# background_agents/worker.py ← v8 新增
class BackgroundAgentWorker:
    """
    后台 Agent 统一调度器：
    - Semaphore 限制并发（防止同时打爆 LLM API 限速）
    - 指数退避重试（最多 2 次）
    - 超时保护（120s，后台任务上限）
    - 失败日志记录（不阻塞主流程）
    """
    def __init__(self, max_concurrent: int = 2):
        self._semaphore = asyncio.Semaphore(max_concurrent)

    async def submit(self, coro, task_name: str, retries: int = 2):
        async with self._semaphore:
            for attempt in range(retries + 1):
                try:
                    async with asyncio.timeout(120):
                        await coro
                        logger.info(f"{task_name} 完成")
                        return
                except asyncio.TimeoutError:
                    logger.warning(f"{task_name} 超时 attempt={attempt}")
                except Exception as e:
                    logger.error(f"{task_name} 失败: {e} attempt={attempt}")
                    if attempt < retries:
                        await asyncio.sleep(2 ** attempt)  # 指数退避: 1s, 2s

# 三个后台 Agent（模型从配置读取，不硬编码）
class DimensionExtractAgent:
    """素材导入后自动提取并补充灵魂维度信息"""
    # 触发：RAG 入库完成后（asyncio.create_task via BackgroundAgentWorker）

    @property
    def model(self) -> str:
        """从配置读取后台模型，默认 gpt-4o-mini"""
        return config_service.get_background_model()   # 见 SystemConfig.background_model

class EpisodicSummaryAgent:
    """每 N 轮对话后提炼关键事件为情节记忆"""
    # 触发：SoulEngine Phase 3 检测轮数（默认每 10 轮）

    @property
    def model(self) -> str:
        return config_service.get_background_model()

class ProfileEnrichAgent:
    """从对话中发现新的行为模式，写入 ProceduralMemory"""
    # 触发：每日定时 / 累计新对话达阈值

    @property
    def model(self) -> str:
        return config_service.get_background_model()
```

**系统配置新增两个模型字段**（在 `settings` 页面配置）：

```python
# db/models/system_config.py
class SystemConfig(Base):
    chat_model: str       = "gpt-4o"       # 主对话模型（高质量）
    background_model: str = "gpt-4o-mini"  # 后台 Agent 模型（成本优先）
    # 两个模型独立配置，互不影响

**后台 Agent 多模型策略**：

| 场景 | 推荐模型 | 原因 |
|------|---------|------|
| Phase 2 主对话 | `gpt-4o` / `claude-sonnet` | 高质量输出，延迟敏感 |
| 情节摘要 Agent | `gpt-4o-mini` / `claude-haiku` | 离线摘要，成本优先 |
| 维度提取 Agent | `gpt-4o-mini` | 结构化抽取 |
| 档案补充 Agent | `gpt-4o-mini` | 同上 |

### 10. 🎙️ 语音模块 (`modules/voice/`) — 待实现

```python
class VoiceService:
    async def text_to_speech(
        text: str, emotion: EmotionTag, voice_config: VoiceConfig
    ) -> bytes
    async def speech_to_text(audio: bytes) -> str
```


动态加载用户配置的 LLM，屏蔽不同 Provider 的差异：

```python
# modules/llm/manager.py
class LLMManager:
    def get_chat_client(config: LLMConfig) -> BaseChatModel
    def get_embedding_client(config: LLMConfig) -> Embeddings
    def test_connection(config: LLMConfig) -> TestResult
    def list_available_models(provider: str) -> list[str]
```

支持 Provider：
- `openai` → OpenAI API
- `gemini` → Google Generative AI
- `anthropic` → Claude
- `ollama` → 本地模型（无需 API Key）
- `custom` → 任意 OpenAI 兼容端点

### 2. 👻 灵魂模块 (`modules/soul/`)

存储和管理逝者的完整数字人格，**10个描述维度**：

```python
# modules/soul/models.py
class SoulProfile:
    # ── 原有6个维度 ──────────────────────────────────
    basic_info: BasicInfo
    # 姓名/性别/年龄/籍贯/职业/生卒/头像

    personality: PersonalityProfile
    # 性格标签/MBTI参考/情绪表达方式

    life_experiences: list[LifeExperience]
    # 时间线事件（幼年→成年→晚年）

    relationships: RelationshipGraph
    # 关系图（节点+边+昵称）

    hobbies: list[Hobby]
    # 爱好（类别/熟练度/相关记忆）

    special_habits: list[SpecialHabit]
    # 特殊习惯（睡前习惯/口头禅触发条件等）

    # ── 新增4个维度 ──────────────────────────────────
    values_beliefs: ValuesBelief
    # 价值观与世界观（决策底层代码）
    # 对金钱/荣誉/生死/家庭/责任的真实看法
    # 例："平淡是真" → 面对职场焦虑会给出平和的安慰逻辑

    emotional_anchors: list[EmotionalAnchor]
    # 情感锚点（触发强烈情感的事物）
    # - 最骄傲的时刻 / 最深沉的遗憾
    # - 与生者之间的专属"梗"或秘密暗语
    # - 特定物品/场景/气味的情感联结

    linguistic_fingerprint: LinguisticFingerprint
    # 语言指纹（最精细的身份还原层）
    # - 口头禅与语气词（"哎呀" / "其实吧" / "听我说"）
    # - 句式结构偏好（短促肯定 vs 长段哲理）
    # - 幽默感风格（冷幽默/自嘲/豪爽大笑）
    # - 敏感词与禁忌话题
    # - 写字/打字时的特殊习惯（爱用省略号/不用标点）

    knowledge_domain: KnowledgeDomain
    # 知识与专业边界
    # - 擅长领域（厨艺/木工/某专业技术）
    # - 知识盲区（不了解或会主动回避的话题）
    # - 天堂中偶尔流露专业性 → 极大增强真实感

    # ── 素材来源 ─────────────────────────────────────
    import_sources: list[ImportSource]
    # 已导入素材列表（聊天记录/音频/视频/图片）

# modules/soul/manager.py
class SoulManager:
    def create_soul(profile: SoulProfile) -> Soul
    def build_system_prompt(soul_id: str) -> str
    # 将10个维度组装成结构化的 System Prompt
    def extract_from_material(soul_id: str, md_content: str) -> ExtractedDimensions
    # 从 RAG 素材中自动提取并补充各维度信息
    def update_dimension(soul_id: str, dimension: str, data: dict)
    # 单独更新某个维度
```

### 3. 📝 记忆模块 (`modules/memory/`)

三层记忆架构：

```python
# modules/memory/short_term.py  (Redis)
class ShortTermMemory:
    def get_context(session_id: str, last_n: int) -> list[Message]
    def append(session_id: str, message: Message)
    def clear(session_id: str)

# modules/memory/long_term.py  (pgvector RAG)
class LongTermMemory:
    def search(soul_id: str, query: str, top_k: int) -> list[MemoryChunk]
    def ingest_document(soul_id: str, doc: MarkdownDocument)

# modules/memory/episodic.py  (PostgreSQL)
class EpisodicMemory:
    def save_key_event(soul_id: str, event: KeyEvent)
    def search_relevant_events(soul_id: str, query: str) -> list[KeyEvent]

# modules/memory/manager.py  (统一入口)
class MemoryManager:
    def retrieve_for_generation(soul_id: str, query: str) -> MemoryContext
    def save_interaction(session_id: str, user_msg: str, agent_reply: str)
```

### 4. 🗂️ 上下文管理模块 (`modules/context/`)

组装最终送给 LLM 的 Prompt，管理 Token 预算：

```python
# modules/context/builder.py
class ContextBuilder:
    def build(
        soul_prompt: str,          # 灵魂基础人格
        memory_context: MemoryContext,  # 记忆检索结果
        short_term: list[Message],       # 最近对话
        user_message: str
    ) -> list[ChatMessage]

    def _fit_token_budget(messages, max_tokens) -> list[ChatMessage]
```

### 5. 🔧 工具模块 (`modules/tools/`)

Agent 可调用的工具集（当前阶段基础工具）：

```python
# modules/tools/registry.py
TOOLS = [
    MemorySearchTool,      # 主动语义检索记忆
    TimePerceptionTool,    # 感知"天堂时间"（日期/季节）
    EmotionDetectTool,     # 检测用户情绪，决定回应风格
]
```

### 6. 💬 会话服务模块 (`services/chat/`)

> [!NOTE]
> v8 重命名：原"通信模块"已更名为**会话服务模块**。
> 旧的6-Agent流水线已替换为 `engine/soul_engine.py` 中的三阶段引擎。
> 本模块现只负责两件事：①聊天 SSE 路由层  ②RAG 素材入库。

```python
# services/chat/chat_service.py
class ChatService:
    """
    聊天 SSE 路由层。
    将 FastAPI 路由接收到的请求透传给 SoulEngine，返回流式响应。
    不含任何业务逻辑——所有 AI 推理均在 engine/ 完成。
    """
    def __init__(self, soul_engine: SoulEngine, config_svc: ConfigService): ...

    async def stream_chat(
        self,
        soul_id: str,
        session_id: str,
        user_message: str,
    ) -> AsyncGenerator[str, None]:   # SSE 流式输出
        llm_config = await self.config_svc.get_active_config()
        async for chunk in self.soul_engine.run(EngineInput(
            soul_id=soul_id,
            session_id=session_id,
            user_message=user_message,
            llm_config=llm_config,
        )):
            yield chunk

# services/chat/rag_ingest_service.py
class RagIngestService:
    """
    素材入库流水线（见"RAG 统一处理流水线"章节）：
    上传文件 → 格式转MD → Contextual分块 → Embedding → pgvector
    入库完成后异步触发 DimensionExtractAgent。
    """
    async def process_upload(self, soul_id: str, file: UploadFile) -> str:
        """返回 document_id，前端轮询状态用"""
        ...
```


### 7. 🎙️ 语音模块 (`modules/voice/`) — 待实现

接口预留，阶段二实现（对应灵魂引擎第⑥步）：

```python
class VoiceService:
    # ⑥ 语音合成 Agent（Audio Synthesis）
    #    输入：最终文字 + 情感强度
    #    输出：带呼吸感/停顿/情绪波动的克隆音色
    async def text_to_speech(
        text: str,
        emotion: EmotionState,
        voice_config: VoiceConfig
    ) -> bytes
    async def speech_to_text(audio: bytes) -> str
```

---

## RAG 统一处理流水线

**核心思路**：所有格式先转为 Markdown，再统一解析分块。

```
原始素材 (任意格式)
        │
        ▼
┌───────────────────────────────────────────────┐
│              格式转换层（→ Markdown）           │
│                                               │
│  .txt/.md   → 直接使用                        │
│  .pdf/.docx → pypdf/python-docx → .md         │
│  .json (聊天记录) → 格式化对话 → .md          │
│  .mp3/.wav/.m4a  → Whisper STT → .md          │
│  .mp4/.mov       → 音频分离+Whisper → .md     │
│  .jpg/.png       → Vision LLM描述 → .md       │
└───────────────────────┬───────────────────────┘
                        │ 统一的 .md 文件
                        ▼
┌───────────────────────────────────────────────┐
│           Markdown 解析 & 分块                 │
│                                               │
│  按语义边界分块（段落/对话轮次）              │
│  每块 400-800 tokens，20% 重叠               │
└───────────────────────┬───────────────────────┘
                        │
                        ▼
┌───────────────────────────────────────────────┐
│           Embedding 生成 → pgvector            │
│           （使用用户配置的 Embedding 模型）    │
└───────────────────────────────────────────────┘
```

**同时提取灵魂信息**：导入素材时，额外运行一个提取 Agent，从内容中自动识别并补充灵魂页面的信息（性格、口头禅、关系等）。

---

## 灵魂页面设计（前端）

### 信息结构

```typescript
interface SoulProfile {

  // ── 原有6个维度 ──────────────────────────────────────────
  // 基本信息
  basicInfo: {
    name: string
    nickname?: string
    gender: 'male' | 'female' | 'other'
    birthDate?: string
    deathDate?: string
    age?: number
    birthplace?: string        // 籍贯
    occupation?: string
    avatar?: string            // 头像图片
  }

  // 人生经历时间线
  lifeExperiences: Array<{
    id: string
    period: string             // 如 "1990-1995" 或 "幼年"
    title: string
    description: string
    tags: string[]
    mediaUrl?: string          // 关联的照片/视频
  }>

  // 社会关系图
  relationships: {
    nodes: Array<{
      id: string
      name: string
      nickname?: string        // 昵称（如逝者如何称呼对方）
      relation: string         // 关系类型（父母/伴侣/挚友等）
      description?: string
      avatarUrl?: string
    }>
    edges: Array<{
      source: string           // node id
      target: string           // node id
      label?: string
    }>
  }

  // 性格特征
  personality: {
    traits: string[]           // 性格标签
    mbtiRef?: string           // MBTI参考
    emotionExpression: string  // 情绪表达方式
    customPrompt?: string      // 用户自定义的人格提示词
  }

  // 爱好
  hobbies: Array<{
    name: string
    category: string           // 类别（音乐/运动/饮食等）
    proficiency: 'casual' | 'skilled' | 'expert'
    relatedMemory?: string     // 相关记忆片段
  }>

  // 特殊习惯
  specialHabits: Array<{
    description: string
    trigger?: string           // 触发条件
    frequency?: string         // 频率（每天/音乐/运动等）
  }>

  // ── 新增4个维度 ──────────────────────────────────────────
  // 价值观与世界观（决策底层代码）
  valuesBeliefs: {
    lifePhilosophy: string     // 人生哲学（如"平淡是真"）
    attitudeToMoney: string    // 对金錢的看法
    attitudeToFamily: string   // 对家庭责任的看法
    attitudeToCareer: string   // 对荷业/荣誉的看法
    attitudeToDeath?: string   // 生死观（可选，镜头的话不必填）
    coreBeliefs: string[]      // 核心信念标签（如"勇气""责任"等）
  }

  // 情感锚点
  emotionalAnchors: Array<{
    type: 'proudest_moment' | 'deepest_regret' | 'shared_secret' | 'sensory' | 'other'
    description: string        // 具体描述
    emotionType: string        // 关联的情绪（吟傲/憫惜/温暖）
    isPrivate: boolean         // 是否是生者与逝者小内密
    trigger?: string           // 触发该锚点的关键词/场景
  }>

  // 语言指纹
  linguisticFingerprint: {
    catchphrases: string[]          // 口头禅（如"哎呀""其实吧"）
    fillerWords: string[]           // 语气词（"嘴""呀""呢"）
    sentenceStyle: 'short_direct' | 'long_philosophical' | 'mixed'
    humorStyle: 'cold' | 'self_deprecating' | 'boisterous' | 'gentle' | 'none'
    punctuationHabits?: string      // 标点习惯（如"爱省略号""不用标点"）
    sensitiveTopics: string[]       // 敏感词/禁忌话题
    writingStyle?: string           // 文字风格补充说明
  }

  // 知识与专业边界
  knowledgeDomain: {
    expertAreas: Array<{
      area: string                  // 如"川菜""和帟""音邑"
      proficiencyNote: string       // 专业程度说明
    }>
    blindSpots: string[]            // 知识盲区（不了解的领域）
    talksAboutExpertise: boolean    // 天堂中是否会展现专业性
  }

  // ── 素材来源 ──────────────────────────────────────────
  importedSources: Array<{
    id: string
    fileName: string
    fileType: string
    status: 'processing' | 'ready' | 'failed'
    uploadedAt: string
    extractedDimensions?: Record<string, unknown>  // 自动提取到的维度信息
  }>
}
```

### 关系图可视化

使用 **React Flow** 或 **D3.js** 构建关系图，节点支持：
- 拖拽布局
- 点击查看节点详情
- 右键添加新关系

---

## 前端页面结构（更新）

```
/                       首页（诗意欢迎页）
/setup                  创建第一个灵魂（引导流程）
/soul/[soulId]          灵魂页面（核心档案展示+编辑）
  ├── Tab 1: 基本信息
  ├── Tab 2: 人生经历（时间线）
  ├── Tab 3: 社会关系（可视化关系图）
  ├── Tab 4: 性格特征
  ├── Tab 5: 爱好与习惯
  ├── Tab 6: 价值观与世界观         ← 新增
  ├── Tab 7: 情感锚点                   ← 新增
  ├── Tab 8: 语言指纹                   ← 新增
  ├── Tab 9: 知识与专业边界           ← 新增
  └── Tab 10: 素材导入（文件上传+调用RAG+自动展示提取结果）
/chat/[soulId]          聊天界面（实时文字对话）
/memory/[soulId]        记忆管理中心
  ├── 素材列表 + 处理状态
  └── 记忆片段浏览（可搜索）
/settings               系统配置
  ├── LLM 配置（Provider / API Key / Model）
  ├── Embedding 配置
  └── 其他系统参数
```

---

## Docker Compose 方案（全栈）

```
heaven-agent/docker-compose.yml 启动：
  ├── postgres (pgvector)    → :5432   挂载 data/postgres/
  ├── redis                  → :6379   挂载 data/redis/
  └── backend (FastAPI)      → :8000   挂载 ./src/

web/ 独立启动（开发模式 npm run dev，生产可容器化）
```

**数据目录（全部在 heaven-agent/data/）：**
```
heaven-agent/data/
├── postgres/      # PostgreSQL 数据文件
├── redis/         # Redis 持久化文件
└── uploads/       # 用户上传的原始素材
```

---

## 数据库表设计

### 核心表

| 表名 | 说明 |
|------|------|
| `souls` | 灵魂档案（逝者整体记录） |
| `soul_basic_info` | 基本信息 |
| `soul_experiences` | 人生经历时间线 |
| `soul_relationships` | 社会关系节点 |
| `soul_relationship_edges` | 关系图边 |
| `soul_personality` | 性格特征 |
| `soul_hobbies` | 爱好与特殊习惯 |
| `soul_values_beliefs` | 价值观与世界观 ← 新增 |
| `soul_emotional_anchors` | 情感锚点 ← 新增 |
| `soul_linguistic_fingerprints` | 语言指纹 ← 新增 |
| `soul_knowledge_domains` | 知识与专业边界 ← 新增 |
| `conversations` | 对话会话 |
| `messages` | 消息记录（含 emotion_tag 字段） |
| `memory_documents` | 导入的原始素材记录 |
| `memory_chunks` | 向量化分块（含 embedding + 维度标注） |
| `episodic_memories` | 情节记忆（AI提炼的关键事件） |
| `system_config` | 系统配置（含 LLM 配置） |

---

## 开发阶段规划

| 阶段 | 层 | 内容 |
|------|---|------|
| **Phase 0** | 基础设施 | 目录初始化 + `docker-compose.yml`（三服务）+ 数据库 Schema |
| **Phase 1** | 后端层 | FastAPI 骨架 + 灵魂 CRUD API + 系统配置 API |
| **Phase 2** | 后端层 | RAG 入库流水线（格式→MD→分块→Embedding→pgvector）|
| **Phase 3** | 前端 | 灵魂页面（10个Tab）+ 系统配置页 |
| **Phase 4** | 智能体层 | LLM管理模块 + 记忆模块 + 上下文模块 |
| **Phase 5** | 智能体层 | 六Agent灵魂引擎（①~⑤）+ Agent层 FastAPI 服务 |
| **Phase 6** | 联调 | 后端⟷Agent层对接 + 聊天界面 SSE 流式透传 |
| **Phase 7** | 前端 | UI 全面打磨 + 动效 |
| **Phase 8** | 测试 | 单元测试 + 系统测试 + 一键测试脚本 |

---

## 测试策略

### 测试目录结构

```
heaven-agent/
├── tests/
│   ├── conftest.py                  # 公共 fixtures（DB、Redis、Mock LLM）
│   ├── unit/                        # 单元测试（各模块独立）
│   │   ├── test_llm_manager.py
│   │   ├── test_soul_manager.py
│   │   ├── test_memory_short_term.py
│   │   ├── test_memory_long_term.py
│   │   ├── test_memory_episodic.py
│   │   ├── test_context_builder.py
│   │   ├── test_tools.py
│   │   ├── test_communication.py
│   │   └── test_rag_pipeline.py
│   ├── system/                      # 系统测试（跨模块真实场景）
│   │   ├── test_scenario_first_chat.py      # 场景1：首次对话
│   │   ├── test_scenario_memory_recall.py   # 场景2：记忆唤起
│   │   ├── test_scenario_rag_import.py      # 场景3：素材导入与检索
│   │   ├── test_scenario_soul_build.py      # 场景4：灵魂构建完整流程
│   │   └── test_scenario_multi_turn.py      # 场景5：多轮对话连贯性
│   └── fixtures/                    # 测试数据
│       ├── sample_chat_log.txt      # 样本聊天记录
│       ├── sample_chat_log.json     # 样本JSON聊天记录
│       ├── sample_document.pdf      # 样本PDF
│       ├── sample_audio.mp3         # 样本音频（短片段）
│       └── soul_profile_fixture.json # 样本灵魂档案

scripts/
├── test.sh                          # 一键测试脚本（主入口）
├── test_unit.sh                     # 仅运行单元测试
├── test_system.sh                   # 仅运行系统测试
└── test_coverage.sh                 # 生成覆盖率报告
```

---

### 单元测试详细设计

#### `test_llm_manager.py` — LLM管理模块

```python
# 使用 Mock 替代真实 API 调用，保证无需 Key 即可测试

class TestLLMManager:
    def test_get_chat_client_openai()
    # 验证：传入 OpenAI 配置 → 返回正确类型的 ChatClient

    def test_get_chat_client_ollama_no_key_required()
    # 验证：Ollama provider 不需要 API Key 也能创建客户端

    def test_get_embedding_client_returns_embeddings()
    # 验证：返回能正确生成向量的 Embeddings 对象

    def test_test_connection_success()
    # 验证：Mock LLM 返回响应时 test_connection 返回 success

    def test_test_connection_invalid_key()
    # 验证：无效 API Key → 返回 error 而不是抛出未处理异常

    def test_unsupported_provider_raises()
    # 验证：传入未知 provider → 抛出 UnsupportedProviderError

    def test_custom_base_url_respected()
    # 验证：custom provider 使用用户提供的 base_url
```

#### `test_soul_manager.py` — 灵魂模块

```python
class TestSoulManager:
    def test_create_soul_persists_to_db()
    # 验证：create_soul 后数据库中能查到对应记录，含正确字段

    def test_build_system_prompt_contains_name()
    # 验证：生成的 System Prompt 包含灵魂的姓名

    def test_build_system_prompt_contains_personality_traits()
    # 验证：生成的 Prompt 包含性格特征描述

    def test_build_system_prompt_contains_relationship_context()
    # 验证：含有社会关系描述（如"你的妻子叫小红"）

    def test_update_from_rag_merges_extracted_personality()
    # 验证：从RAG提取的信息能合并进已有的灵魂档案

    def test_get_soul_not_found_raises()
    # 验证：查询不存在的 soul_id → 抛出 SoulNotFoundError

    def test_create_soul_with_minimal_info()
    # 验证：只提供姓名也能创建灵魂（其他字段可选）
```

#### `test_memory_short_term.py` — 短期记忆

```python
class TestShortTermMemory:
    def test_append_and_get_context()
    # 验证：写入3条消息后 get_context 能返回这3条

    def test_get_context_last_n_limit()
    # 验证：写入10条，get_context(last_n=3) 只返回最后3条

    def test_clear_removes_all_messages()
    # 验证：clear 后 get_context 返回空列表

    def test_ttl_expiry(mock_redis_with_ttl)
    # 验证：超过 TTL 后消息自动失效

    def test_session_isolation()
    # 验证：session_A 的消息不会出现在 session_B 的上下文中

    def test_message_order_preserved()
    # 验证：消息按写入时间顺序返回
```

#### `test_memory_long_term.py` — 长期记忆（RAG向量检索）

```python
class TestLongTermMemory:
    def test_ingest_document_creates_chunks()
    # 验证：导入一个MD文档后 memory_chunks 表有记录

    def test_search_returns_relevant_chunks()
    # 验证：搜索"生日"能找到包含"生日"内容的分块

    def test_search_soul_isolation()
    # 验证：soul_A 无法检索到 soul_B 的记忆分块

    def test_search_top_k_limit()
    # 验证：top_k=3 时最多返回3条结果

    def test_empty_search_returns_empty_list()
    # 验证：空数据库搜索不报错，返回 []

    def test_chunk_metadata_preserved()
    # 验证：分块保留来源文件名、chunk_index 等元数据
```

#### `test_memory_episodic.py` — 情节记忆

```python
class TestEpisodicMemory:
    def test_save_key_event_persists()
    # 验证：保存事件后数据库中有记录

    def test_search_relevant_events_by_keyword()
    # 验证：搜索"旅行"能找到含旅行内容的情节

    def test_importance_score_ordering()
    # 验证：返回结果按 importance_score 降序排列

    def test_save_event_with_source_message_ids()
    # 验证：事件可关联到源消息 ID 列表

    def test_max_events_retrieved()
    # 验证：大量事件时检索只返回前N条最相关的
```

#### `test_context_builder.py` — 上下文管理

```python
class TestContextBuilder:
    def test_build_includes_soul_prompt_as_system()
    # 验证：soul_prompt 被放置为 system message

    def test_build_includes_memory_context()
    # 验证：检索到的记忆片段被正确注入到 Prompt 中

    def test_build_includes_short_term_history()
    # 验证：最近N轮对话被追加到 messages 列表

    def test_token_budget_truncates_history()
    # 验证：超出 max_tokens 时，历史对话被裁剪（保留最近的）

    def test_token_budget_never_truncates_system()
    # 验证：无论 Token 多紧，system message 不会被删除

    def test_empty_memory_context_handled()
    # 验证：没有检索结果时 build 不抛异常

    def test_message_role_sequence_valid()
    # 验证：最终 messages 列表符合 user/assistant 交替规范
```

#### `test_tools.py` — 工具模块

```python
class TestMemorySearchTool:
    def test_invocation_returns_relevant_text()
    def test_no_results_returns_empty_string()

class TestTimePerceptionTool:
    def test_returns_current_date_aware_description()
    # 验证：返回包含当前季节/时间的描述字符串

    def test_format_is_natural_language()
    # 验证：返回的是自然语言而非时间戳

class TestEmotionDetectTool:
    def test_detects_sadness_keywords()
    # 验证：输入"我好想你，我哭了" → 返回 emotion='sad'

    def test_detects_neutral_message()
    # 验证：普通问候 → 返回 emotion='neutral'

    def test_returns_structured_output()
    # 验证：返回包含 emotion 和 intensity 的结构化结果
```

#### `test_communication.py` — 通信模块

```python
class TestChatService:
    async def test_stream_chat_yields_strings()
    # 验证：stream_chat 是异步生成器，每次 yield 的是字符串

    async def test_stream_chat_saves_to_short_term_memory()
    # 验证：对话结束后 Redis 中有新的消息记录

    async def test_stream_chat_with_invalid_soul_id_raises()
    # 验证：无效 soul_id → 快速返回错误而不是挂起

class TestRagIngestService:
    async def test_process_txt_file_creates_chunks()
    # 验证：上传 .txt 文件后 memory_chunks 有记录

    async def test_process_unsupported_format_raises()
    # 验证：上传 .exe → 返回明确的格式不支持错误

    async def test_document_status_updated_after_processing()
    # 验证：处理完成后 memory_documents.status = 'ready'

    async def test_failed_processing_updates_status_to_failed()
    # 验证：处理异常时 status = 'failed' 而非卡在 'processing'
```

#### `test_rag_pipeline.py` — RAG流水线

```python
class TestMarkdownConverter:
    def test_txt_passthrough()
    # 验证：.txt 文件直接保留内容，格式不变

    def test_json_chat_log_formatted_as_dialogue()
    # 验证：JSON聊天记录转成 "A: xx\nB: xx" 格式的MD

    def test_pdf_text_extracted()
    # 验证：PDF 文本内容被正确提取

class TestChunker:
    def test_chunk_size_within_bounds()
    # 验证：每个 chunk 的 token 数在 400-800 之间

    def test_overlap_between_consecutive_chunks()
    # 验证：相邻 chunk 有约 20% 的内容重叠

    def test_short_document_single_chunk()
    # 验证：内容很短时只生成1个 chunk，不强制分割

class TestEmbedder:
    def test_embedding_dimension_matches_config()
    # 验证：生成的向量维度与配置的 embedding 模型一致

    def test_similar_texts_closer_in_space()
    # 验证：语义相似的两段文本，余弦相似度 > 0.8
```

---

### 系统测试场景

#### 场景1：首次对话 `test_scenario_first_chat.py`

```
前置：创建灵魂档案（王奶奶，75岁，慈祥）
步骤：
  1. 发送消息："奶奶，我想你了"
  2. 检查回复是否包含温柔的语气词
  3. 检查回复是否以第一人称回应
  4. 检查短期记忆 Redis 是否存入了本轮对话
预期：AI 以奶奶的口吻温柔回应，对话被正确存储
```

#### 场景2：记忆唤起 `test_scenario_memory_recall.py`

```
前置：
  - 创建灵魂档案（包含"最爱做红烧肉"的信息）
  - 将该信息写入 RAG 向量库
步骤：
  1. 发送消息："你最拿手的菜是什么？"
  2. 检查回复中是否提及"红烧肉"
  3. 检查 memory retrieval 日志确认向量检索被触发
预期：AI 通过 RAG 检索到相关记忆，并自然地在回复中体现
```

#### 场景3：素材导入与 RAG 检索 `test_scenario_rag_import.py`

```
前置：准备一个包含特定内容的聊天记录文件
  内容："2019年我们去了三亚，你一直说海水太咸"
步骤：
  1. 调用素材导入接口上传该文件
  2. 等待处理完成（status=ready）
  3. 发起聊天，问："你还记得我们去三亚的事吗？"
  4. 检查回复是否引用了"海水太咸"的内容
预期：RAG 检索命中导入的聊天记录，AI 回复包含具体细节
```

#### 场景4：灵魂构建完整流程 `test_scenario_soul_build.py`

```
步骤：
  1. POST /api/souls → 创建灵魂（含基本信息+性格）
  2. POST /api/souls/{id}/experiences → 添加3条人生经历
  3. POST /api/souls/{id}/relationships → 添加2个关系节点
  4. GET /api/souls/{id}/system-prompt → 获取生成的系统提示词
  5. 验证系统提示词包含：姓名、性格描述、关系描述
预期：完整灵魂档案能生成结构清晰、内容完整的系统提示词
```

#### 场景5：多轮对话连贯性 `test_scenario_multi_turn.py`

```
前置：创建灵魂档案
步骤：
  Round 1: 用户说 "我今天去了你最爱的咖啡馆"
           AI 回应（内容存入短期记忆）
  Round 2: 用户说 "那里今天有特别多人"
           AI 回应
  Round 3: 用户说 "你还记得我刚才说的地方吗？"
  检查：第3轮回复中提到"咖啡馆"
预期：短期记忆保障对话连贯，AI 正确引用前几轮提到的信息
```

---

### 一键测试脚本

#### `scripts/test.sh`（主入口）

```bash
#!/bin/bash
# 天堂专线 — 一键测试脚本
# 用法: ./scripts/test.sh [unit|system|all|coverage]

set -e

MODE=${1:-all}
COMPOSE_FILE="heaven-agent/docker-compose.test.yml"

echo "🧪 天堂专线测试套件启动..."

# Step 1: 启动测试专用数据库（隔离于开发环境）
echo "📦 启动测试数据库..."
docker compose -f $COMPOSE_FILE up -d --wait

# Step 2: 等待服务就绪
echo "⏳ 等待服务就绪..."
sleep 3

# Step 3: 运行数据库迁移（测试库）
echo "🗄️ 初始化测试数据库..."
docker compose -f $COMPOSE_FILE exec backend \
  python -m alembic upgrade head

# Step 4: 执行测试
cd heaven-agent

case $MODE in
  unit)
    echo "🔬 运行单元测试..."
    python -m pytest tests/unit/ -v --tb=short
    ;;
  system)
    echo "🌐 运行系统测试..."
    python -m pytest tests/system/ -v --tb=short -s
    ;;
  coverage)
    echo "📊 生成覆盖率报告..."
    python -m pytest tests/ \
      --cov=src \
      --cov-report=html:coverage_report \
      --cov-report=term-missing \
      --cov-fail-under=70
    echo "📁 覆盖率报告已生成: heaven-agent/coverage_report/index.html"
    ;;
  all|*)
    echo "🚀 运行全部测试..."
    python -m pytest tests/ -v --tb=short
    ;;
esac

# Step 5: 清理测试数据库
echo "🧹 清理测试环境..."
docker compose -f $COMPOSE_FILE down -v

echo "✅ 测试完成！"
```

#### `scripts/test_unit.sh`（仅单元测试，无需 Docker）

```bash
#!/bin/bash
# 快速单元测试（使用 Mock，无需真实数据库）
cd heaven-agent
python -m pytest tests/unit/ -v --tb=short \
  --mock-db \       # 使用内存 SQLite 替代 PostgreSQL
  --mock-redis      # 使用 fakeredis 替代真实 Redis
```

#### `scripts/test_coverage.sh`（覆盖率报告）

```bash
#!/bin/bash
cd heaven-agent
python -m pytest tests/ \
  --cov=src/modules \
  --cov-report=html:coverage_report \
  --cov-report=term-missing \
  --cov-fail-under=70
open coverage_report/index.html  # macOS 自动打开报告
```

---

### 测试依赖与配置

#### `pyproject.toml` 测试配置

```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
markers = [
    "unit: 单元测试（无外部依赖）",
    "system: 系统测试（需要真实数据库）",
    "slow: 耗时较长的测试（如音频转写）",
]

[tool.coverage.run]
source = ["src/modules"]
omit = ["*/migrations/*", "*/tests/*"]

[tool.coverage.report]
exclude_lines = [
    "pragma: no cover",
    "def __repr__",
    "raise NotImplementedError",
]
```

#### `tests/conftest.py` 公共 Fixtures

```python
import pytest
from fakeredis import FakeRedis
from sqlalchemy import create_engine

@pytest.fixture(scope="session")
def test_db():
    """测试专用 PostgreSQL（或 SQLite in-memory 用于单元测试）"""
    engine = create_engine("sqlite:///:memory:")
    # 运行所有 DDL
    yield engine
    engine.dispose()

@pytest.fixture
def mock_redis():
    """使用 fakeredis，无需真实 Redis"""
    return FakeRedis()

@pytest.fixture
def mock_llm():
    """Mock LLM，固定返回测试响应，无需真实 API Key"""
    class MockLLM:
        def invoke(self, messages): return "这是一条测试回复"
        def stream(self, messages):
            for char in "测试回复": yield char
    return MockLLM()

@pytest.fixture
def sample_soul(test_db):
    """预置一个完整灵魂档案，供多个测试复用"""
    return {
        "id": "test-soul-001",
        "name": "王奶奶",
        "personality_traits": ["慈祥", "爱做饭"],
        "catchphrases": ["多吃点", "别累着"]
    }
```

---

### 测试覆盖率目标

| 模块 | 目标覆盖率 |
|------|-----------|
| `modules/llm/` | ≥ 80% |
| `modules/soul/` | ≥ 85% |
| `modules/memory/` | ≥ 85% |
| `modules/context/` | ≥ 90% |
| `modules/tools/` | ≥ 75% |
| `modules/communication/` | ≥ 75% |
| `modules/rag/` (pipeline) | ≥ 80% |
| **整体** | **≥ 70%** |
