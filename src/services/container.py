from __future__ import annotations

import asyncio
import importlib.util
import shutil
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from ..agent.loop import AgentLoop
from ..agent.pipeline import Pipeline
from ..config.settings import Settings
from ..data.layout import SoulDataLayout
from ..llm.manager import LLMManager
from ..memory.candidates import CandidateStore
from ..soul.distiller import SoulDistiller
from ..soul.loader import SoulLoader
from ..voice.service import DisabledVoiceService
from ..voice.minimax import MiniMaxTTSService
from .candidates import CandidateService
from .data_management import DataManagementService
from .imports import ImportReviewService
from .jobs import JobManager
from .onboarding import OnboardingStore
from .status import SystemStatusService
from .voice_installation import VoiceInstallationService


@dataclass
class ApplicationContainer:
    root: Path
    settings: Settings
    layout: SoulDataLayout
    llm: Any
    soul_loader: SoulLoader
    memory_store: Any
    voice: Any
    voice_installed: bool
    agent_loop: AgentLoop
    distiller: SoulDistiller
    candidates: CandidateStore
    candidate_service: CandidateService
    import_reviews: ImportReviewService
    jobs: JobManager
    onboarding: OnboardingStore
    status_service: SystemStatusService
    data_management: DataManagementService
    voice_installation: VoiceInstallationService
    _retired_llms: list[Any] = field(default_factory=list, repr=False)
    _retired_voices: list[Any] = field(default_factory=list, repr=False)
    soul_lock: asyncio.Lock = field(default_factory=asyncio.Lock, repr=False)

    @classmethod
    def create(cls, root: Path, settings: Settings) -> "ApplicationContainer":
        root = Path(root)
        layout = SoulDataLayout(settings.data_root, settings.soul_id)
        layout.initialize()
        legacy_soul = settings.soul_path
        if not legacy_soul.exists():
            legacy_soul = root / "config" / "souls" / "demo"
        if not layout.migration_marker_path.exists():
            layout.migrate_legacy(
                legacy_soul=legacy_soul,
                legacy_conversation=settings.data_dir / "conversation.json",
                legacy_voice=settings.data_dir / "voice",
                legacy_memory_db=settings.data_dir / "memory_db",
                legacy_daily=root / "memory" / "daily",
            )

        llm = LLMManager.get_client(settings.llm)
        soul_loader = SoulLoader(layout.profile_dir)
        candidates = CandidateStore(layout.candidates_path)
        jobs = JobManager()
        onboarding = OnboardingStore(layout.onboarding_path)

        memory_store = None
        try:
            from ..memory.store import MemoryStore
            memory_store = MemoryStore(layout.memory_db_dir)
        except (ImportError, RuntimeError) as exc:
            from ..config.logger import get_logger
            get_logger("container").warning("记忆索引不可用，降级为无检索模式: %s", exc)

        voice_installed, _ = voice_dependencies_available(sys.platform, root)
        voice = _create_selected_voice(settings, layout.voice_dir, root, settings.soul_id)
        pipeline = Pipeline()
        agent_loop = AgentLoop(
            history_path=str(layout.conversation_path),
            llm=llm,
            pipeline=pipeline,
            max_conversation_turns=settings.max_conversation_turns,
            max_regenerate=settings.max_regenerate,
        )
        pipeline.init_deps(
            agent_loop._messages,
            llm_client=llm,
            soul_loader=soul_loader,
            memory_store=memory_store,
            candidate_store=candidates,
            memory_root=layout.daily_dir,
            job_manager=jobs,
        )
        distiller = SoulDistiller(llm, soul_loader, max_retries=settings.distill_max_retries)
        candidate_service = CandidateService(
            candidates, soul_loader, agent_loop.invalidate_soul_cache
        )
        import_reviews = ImportReviewService(candidates)
        status_service = SystemStatusService(
            soul_id=settings.soul_id,
            loader=soul_loader,
            candidates=candidates,
            jobs=jobs,
            onboarding=onboarding,
            voice=voice,
            voice_installed=voice_installed,
            ffmpeg_available=bool(shutil.which("ffmpeg")),
            tts=settings.tts,
        )
        data_management = DataManagementService(layout)
        voice_installation = VoiceInstallationService(
            root=root,
            data_root=layout.data_root,
            jobs=jobs,
            voice_installed=voice_installed,
        )
        return cls(
            root=root,
            settings=settings,
            layout=layout,
            llm=llm,
            soul_loader=soul_loader,
            memory_store=memory_store,
            voice=voice,
            voice_installed=voice_installed,
            agent_loop=agent_loop,
            distiller=distiller,
            candidates=candidates,
            candidate_service=candidate_service,
            import_reviews=import_reviews,
            jobs=jobs,
            onboarding=onboarding,
            status_service=status_service,
            data_management=data_management,
            voice_installation=voice_installation,
        )

    async def replace_llm(self, replacement: Any | None = None) -> None:
        replacement = replacement or LLMManager.get_client(self.settings.llm)
        previous = self.llm
        self.llm = replacement
        self.agent_loop.update_llm_client(replacement)
        self.distiller._llm = replacement
        if previous is not replacement:
            # A concurrent request may still be using the old pool. Keep it
            # alive until lifespan shutdown instead of closing it mid-request.
            self._retired_llms.append(previous)

    async def replace_voice(self, replacement: Any | None = None) -> None:
        replacement = replacement or _create_selected_voice(
            self.settings, self.layout.voice_dir, self.root, self.settings.soul_id
        )
        previous = self.voice
        self.voice = replacement
        self.status_service.replace_voice(replacement)
        self.status_service.update_tts(self.settings.tts)
        if previous is not replacement:
            # A chat request can still be synthesizing through the old service.
            # Its remote client stays open until lifespan shutdown.
            self._retired_voices.append(previous)

    async def save_voice_reference(
        self, audio: bytes, filename: str, content_type: str
    ) -> bytes | None:
        voice = self.voice
        retry_cleanup = getattr(voice, "retry_cleanup", None)
        if callable(retry_cleanup):
            await retry_cleanup()
        create_reference = getattr(voice, "create_reference", None)
        if callable(create_reference):
            return await create_reference(audio, filename, content_type)
        await asyncio.to_thread(voice.save_reference_audio, audio)
        return None

    async def reset_demo(self) -> Path:
        """Reset the active Soul after all other Soul mutations have finished."""
        async with self.soul_lock:
            async with self.agent_loop._turn_lock:
                # Conversation extraction and other tracked background work may
                # still reference the pre-reset Soul. Cancel it before replacing
                # canonical data so stale results cannot reappear afterwards.
                await self.jobs.shutdown()
                backup = self.data_management.reset_demo(
                    self.root / "config" / "souls" / "demo",
                    self.memory_store,
                )
                self.agent_loop.delete_history()
                self.agent_loop.invalidate_soul_cache()
                return backup

    async def close(self) -> None:
        await self.jobs.shutdown()
        clients = [self.llm, *self._retired_llms]
        seen: set[int] = set()
        for client in clients:
            if id(client) in seen:
                continue
            seen.add(id(client))
            await client.aclose()
        voices = [
            *([self.voice] if hasattr(self, "voice") else []),
            *getattr(self, "_retired_voices", []),
        ]
        for voice in voices:
            if id(voice) in seen:
                continue
            seen.add(id(voice))
            close = getattr(voice, "aclose", None)
            if callable(close):
                await close()


def voice_dependencies_available(
    system: str,
    root: Path,
    *,
    find_spec=importlib.util.find_spec,
) -> tuple[bool, str]:
    if system == "darwin":
        required = ("mlx", "mlx_audio", "mlx_whisper", "soundfile", "scipy", "einops")
    else:
        required = (
            "faster_whisper",
            "torch",
            "torchaudio",
            "soundfile",
            "scipy",
            "onnxruntime",
            "modelscope",
            "hyperpyyaml",
            "zhconv",
        )
    missing = [name for name in required if find_spec(name) is None]
    if missing:
        return False, f"缺少可选语音依赖: {', '.join(missing)}"
    if system == "darwin" and not (
        Path(root)
        / "deps"
        / "Fun-CosyVoice3-0.5B-2512-8bit"
        / "model.safetensors"
    ).is_file():
        return False, "缺少语音模型，请运行 bootstrap --voice"
    if system != "darwin" and not (Path(root) / "deps" / "CosyVoice").is_dir():
        return False, "缺少固定版本 CosyVoice 源码，请运行 bootstrap --voice"
    return True, ""


def _create_local_voice(data_dir: Path, root: Path) -> tuple[Any, bool]:
    available, reason = voice_dependencies_available(sys.platform, root)
    if not available:
        return DisabledVoiceService(data_dir, reason), False
    try:
        if sys.platform == "darwin":
            from ..voice.tts import TTSService
            return TTSService(data_dir), True
        from ..voice.tts_official import OfficialTTSService
        return OfficialTTSService(data_dir), True
    except ImportError as exc:
        return DisabledVoiceService(data_dir, f"缺少可选语音依赖: {exc.name}"), False


def _create_selected_voice(
    settings: Settings, data_dir: Path, root: Path, soul_id: str
) -> Any:
    if settings.tts.provider == "minimax":
        return MiniMaxTTSService(data_dir, soul_id, settings.tts.minimax)
    return _create_local_voice(data_dir, root)[0]
