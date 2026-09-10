from ..api.schemas import OnboardingStatus, SystemCapabilities, SystemStatus


class SystemStatusService:
    def __init__(
        self,
        *,
        soul_id: str,
        loader,
        candidates,
        jobs,
        onboarding,
        voice,
        voice_installed: bool,
        ffmpeg_available: bool,
        tts=None,
    ):
        self._soul_id = soul_id
        self._loader = loader
        self._candidates = candidates
        self._jobs = jobs
        self._onboarding = onboarding
        self._voice = voice
        self._voice_installed = voice_installed
        self._ffmpeg_available = ffmpeg_available
        self._tts = tts

    def replace_voice(self, voice) -> None:
        self._voice = voice

    def update_tts(self, tts) -> None:
        self._tts = tts

    def get(self) -> SystemStatus:
        pending_candidates = len(self._candidates.list("pending"))
        has_profile = bool(self._loader.load_dimension("basic_info").strip())
        legacy_completed = bool(self._onboarding.completed)
        profile_step = bool(
            getattr(self._onboarding, "profile_completed", legacy_completed)
        )
        review_step = bool(
            getattr(self._onboarding, "import_review_completed", legacy_completed)
        )
        profile_ready = bool(profile_step and has_profile)
        review_ready = bool(
            review_step and pending_candidates == 0
        )
        voice_ready = self._voice_ready()
        return SystemStatus(
            initialization="ready" if profile_ready else "degraded",
            soul_id=self._soul_id,
            soul_name=self._loader.load().name if has_profile else "",
            capabilities=SystemCapabilities(
                text_chat=True,
                voice_installed=self._voice_installed,
                voice_ready=voice_ready,
                tts_instruction=bool(
                    getattr(self._voice, "supports_instruction", False)
                ),
                ffmpeg=self._ffmpeg_available,
            ),
            onboarding=OnboardingStatus(
                profile_ready=profile_ready,
                import_review_ready=review_ready,
                voice_ready=voice_ready,
                completed=self._onboarding.completed,
            ),
            pending_jobs=len(self._jobs.list_active()),
            pending_candidates=pending_candidates,
        )

    def _voice_ready(self) -> bool:
        if self._tts is not None and self._tts.provider == "minimax":
            if not self._tts.minimax.api_key:
                return False
        return bool(getattr(self._voice, "is_ready", self._voice.has_reference))
