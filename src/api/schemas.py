from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field


SafetyState = Literal["normal", "supportive_redirect", "crisis"]


class APIModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ErrorBody(APIModel):
    code: str
    message: str
    retryable: bool = False
    request_id: str


class ChatRequest(APIModel):
    message: str = Field(min_length=1, max_length=10_000)


class AudioRequest(APIModel):
    text: str = Field(min_length=1, max_length=10_000)
    instruct_text: str = Field(default="用平静自然的语气说话。", max_length=500)


class MemoryReference(APIModel):
    id: str
    content: str
    dimension: str = ""
    source_type: str = "unknown"


class ChatTiming(APIModel):
    """Server-side timings for a completed chat request, in milliseconds."""

    first_response_ms: int | None = None
    total_response_ms: int = 0


class ChatResponse(APIModel):
    response_id: str = ""
    response_text: str
    instruct_text: str
    has_voice: bool
    transcript: str | None = None
    used_memories: list[MemoryReference] = Field(default_factory=list)
    safety_state: SafetyState = "normal"
    timing: ChatTiming = Field(default_factory=ChatTiming)


class ChatFeedbackUpdate(APIModel):
    user_message: str = Field(min_length=1, max_length=10_000)
    response_text: str = Field(min_length=1, max_length=10_000)
    rating: Literal["similar", "dissimilar"]
    reasons: list[Literal["fact", "style", "relationship", "response", "other"]] = Field(default_factory=list, max_length=5)
    suggestion: str = Field(default="", max_length=10_000)


class ChatFeedbackView(ChatFeedbackUpdate):
    response_id: str
    created_at: str
    updated_at: str


class ChatFeedbackStatsView(APIModel):
    total: int
    similar: int
    dissimilar: int
    similar_rate: float
    reasons: dict[str, int]


class CloudLLMSettingsView(APIModel):
    base_url: str
    model: str
    temperature: float | None = None
    api_key_configured: bool


class OllamaSettingsView(APIModel):
    base_url: str
    model: str
    temperature: float | None = None


class LLMSettingsView(APIModel):
    provider: Literal["cloud", "local"]
    cloud: CloudLLMSettingsView
    ollama: OllamaSettingsView


class MiniMaxSettingsView(APIModel):
    base_url: str
    model: str
    api_key_configured: bool


class OpenAICompatibleTTSSettingsView(APIModel):
    base_url: str
    model: str
    voice: str
    api_key_configured: bool


class TTSSettingsView(APIModel):
    provider: Literal["local", "minimax", "openai_compatible"]
    auto_play: bool = False
    audio_cache_size: int = Field(default=10, ge=0, le=100)
    minimax: MiniMaxSettingsView
    openai_compatible: OpenAICompatibleTTSSettingsView


class SettingsView(APIModel):
    llm: LLMSettingsView
    tts: TTSSettingsView
    log_level: Literal["debug", "error"]


class CloudLLMSettingsUpdate(APIModel):
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    api_key: str | None = None


class OllamaSettingsUpdate(APIModel):
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)


class LLMSettingsUpdate(APIModel):
    provider: Literal["cloud", "local"] | None = None
    cloud: CloudLLMSettingsUpdate | None = None
    ollama: OllamaSettingsUpdate | None = None
    # Compatibility for callers of the former single cloud configuration.
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    api_key: str | None = None


class MiniMaxSettingsUpdate(APIModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class OpenAICompatibleTTSSettingsUpdate(APIModel):
    base_url: str | None = None
    model: str | None = None
    voice: str | None = None
    api_key: str | None = None


class TTSSettingsUpdate(APIModel):
    provider: Literal["local", "minimax", "openai_compatible"] | None = None
    auto_play: bool | None = None
    audio_cache_size: int | None = Field(default=None, ge=0, le=100)
    minimax: MiniMaxSettingsUpdate | None = None
    openai_compatible: OpenAICompatibleTTSSettingsUpdate | None = None


class SettingsUpdate(APIModel):
    llm: LLMSettingsUpdate | None = None
    tts: TTSSettingsUpdate | None = None
    log_level: Literal["debug", "error"] | None = None


class CandidateResolution(APIModel):
    content: str | None = Field(default=None, max_length=10_000)


class MemoryCandidateView(APIModel):
    id: str
    dimension: str
    content: str
    source_type: str
    source_excerpt: str
    confidence: float
    source_speaker: str = ""
    status: Literal["pending", "approved", "rejected"]
    conflict_with: str | None = None
    created_at: str
    resolved_at: str | None = None


class JobView(APIModel):
    id: str
    kind: str
    status: Literal["pending", "running", "completed", "failed", "cancelled"]
    result: Any = None
    error: str | None = None
    created_at: str


class JobAccepted(APIModel):
    job_id: str


class VoiceInstallationView(APIModel):
    state: Literal[
        "not_installed",
        "installing",
        "restart_required",
        "installed",
        "failed",
    ]
    stage: str
    message: str
    restart_required: bool = False
    job_id: str | None = None


class SystemCapabilities(APIModel):
    text_chat: bool = True
    voice_installed: bool = False
    voice_ready: bool = False
    tts_instruction: bool = False
    ffmpeg: bool = False


class OnboardingStatus(APIModel):
    profile_ready: bool
    import_review_ready: bool
    voice_ready: bool
    completed: bool


class SystemStatus(APIModel):
    initialization: Literal["ready", "degraded"]
    soul_id: str
    soul_name: str
    capabilities: SystemCapabilities
    onboarding: OnboardingStatus
    pending_jobs: int
    pending_candidates: int


class DiagnosticsView(APIModel):
    soul_id: str
    python: str
    platform: str
    supported_python: bool
    profile_files: int
    voice_installed: bool
    voice_ready: bool
    memory_ready: bool
    ffmpeg: bool


class StatusView(APIModel):
    status: Literal["ok"] = "ok"


class RecoverableDeleteView(StatusView):
    recoverable: bool
    archive: str


class DemoResetView(StatusView):
    recoverable: bool
    backup: str


class ContentUpdate(APIModel):
    content: str = Field(max_length=100_000)


class DimensionView(APIModel):
    dimension: str
    content: str


class SoulView(APIModel):
    dimensions: dict[str, str]


class SceneOptionView(APIModel):
    key: str
    label: str
    description: str
    prompt: str


class CircumstancesView(APIModel):
    content: str
    scene: str
    scenes: list[SceneOptionView]


class SkillView(APIModel):
    skill_card: dict[str, str] | None


class DistillResultView(APIModel):
    changes: list[str]
    profile: dict[str, str]
    summary: str
    candidate_ids: list[str]
    candidate_count: int
    skill_card: dict[str, str] | None = None


class ImportSpeakerView(APIModel):
    name: str
    message_count: int
    matches_profile_name: bool = False


class ImportPreviewView(APIModel):
    speakers: list[ImportSpeakerView]


class MemoryEntryView(APIModel):
    id: str
    document: str
    metadata: dict[str, Any]


class VoiceStatusView(APIModel):
    has_reference: bool
    ready: bool
    supports_instruction: bool
    supports_voice_cloning: bool
    preview_available: bool = False
    provider: Literal["local", "minimax", "openai_compatible"]
    state: Literal[
        "not_installed", "not_configured", "no_voice", "creating", "ready", "failed"
    ]
    message: str


class LLMConnectionView(APIModel):
    connected: bool


class TTSConnectionView(APIModel):
    connected: bool


class VoiceUploadView(StatusView):
    preview_available: bool = False


class MemoryStatsView(APIModel):
    total: int
    by_dimension: dict[str, int]


class ChatHistoryView(APIModel):
    messages: list[dict[str, str]]
