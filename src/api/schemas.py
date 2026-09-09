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


class ChatResponse(APIModel):
    response_text: str
    instruct_text: str
    has_voice: bool
    transcript: str | None = None
    used_memories: list[MemoryReference] = Field(default_factory=list)
    safety_state: SafetyState = "normal"


class LLMSettingsView(APIModel):
    base_url: str
    model: str
    temperature: float | None = None
    api_key_configured: bool


class MiniMaxSettingsView(APIModel):
    base_url: str
    model: str
    api_key_configured: bool


class TTSSettingsView(APIModel):
    provider: Literal["local", "minimax"]
    auto_play: bool = False
    audio_cache_size: int = Field(default=10, ge=0, le=100)
    minimax: MiniMaxSettingsView


class SettingsView(APIModel):
    llm: LLMSettingsView
    tts: TTSSettingsView
    log_level: Literal["debug", "error"]


class LLMSettingsUpdate(APIModel):
    base_url: str | None = None
    model: str | None = None
    temperature: float | None = Field(default=None, ge=0, le=2)
    api_key: str | None = None


class MiniMaxSettingsUpdate(APIModel):
    base_url: str | None = None
    model: str | None = None
    api_key: str | None = None


class TTSSettingsUpdate(APIModel):
    provider: Literal["local", "minimax"] | None = None
    auto_play: bool | None = None
    audio_cache_size: int | None = Field(default=None, ge=0, le=100)
    minimax: MiniMaxSettingsUpdate | None = None


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


class MemoryEntryView(APIModel):
    id: str
    document: str
    metadata: dict[str, Any]


class VoiceStatusView(APIModel):
    has_reference: bool
    supports_instruction: bool
    preview_available: bool = False
    provider: Literal["local", "minimax"]
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
