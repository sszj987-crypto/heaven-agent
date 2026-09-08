from src.services.status import SystemStatusService


class Loader:
    def load_dimension(self, dimension):
        return "姓名: 王奶奶" if dimension == "basic_info" else ""

    def load(self):
        return type("Profile", (), {"name": "王奶奶"})()


class Candidates:
    def __init__(self, count):
        self.count = count

    def list(self, _status):
        return [object()] * self.count


class Jobs:
    def list_active(self):
        return []


class Voice:
    has_reference = False


class Onboarding:
    completed = True


def test_text_ready_onboarding_can_complete_without_optional_voice():
    service = SystemStatusService(
        soul_id="default",
        loader=Loader(),
        candidates=Candidates(0),
        jobs=Jobs(),
        onboarding=Onboarding(),
        voice=Voice(),
        voice_installed=False,
        ffmpeg_available=False,
    )

    status = service.get()

    assert status.capabilities.text_chat is True
    assert status.capabilities.voice_installed is False
    assert status.capabilities.tts_instruction is False
    assert status.onboarding.completed is True
    assert status.soul_name == "王奶奶"


def test_pending_candidates_keep_review_step_incomplete():
    service = SystemStatusService(
        soul_id="default",
        loader=Loader(),
        candidates=Candidates(2),
        jobs=Jobs(),
        onboarding=type("Onboarding", (), {"completed": False})(),
        voice=Voice(),
        voice_installed=True,
        ffmpeg_available=True,
    )

    status = service.get()

    assert status.pending_candidates == 2
    assert status.onboarding.import_review_ready is False
    assert status.onboarding.completed is False


def test_demo_profile_does_not_skip_first_run_steps_without_explicit_markers():
    service = SystemStatusService(
        soul_id="default",
        loader=Loader(),
        candidates=Candidates(0),
        jobs=Jobs(),
        onboarding=type(
            "Onboarding",
            (),
            {
                "completed": False,
                "profile_completed": False,
                "import_review_completed": False,
            },
        )(),
        voice=Voice(),
        voice_installed=False,
        ffmpeg_available=False,
    )

    status = service.get()

    assert status.onboarding.profile_ready is False
    assert status.onboarding.import_review_ready is False
    assert status.initialization == "degraded"


def test_cloud_voice_without_credentials_is_not_advertised_as_ready():
    voice = type("Voice", (), {"has_reference": True})()
    tts = type(
        "TTS",
        (), {"provider": "minimax", "minimax": type("MiniMax", (), {"api_key": ""})()},
    )()
    service = SystemStatusService(
        soul_id="default",
        loader=Loader(),
        candidates=Candidates(0),
        jobs=Jobs(),
        onboarding=Onboarding(),
        voice=voice,
        voice_installed=False,
        ffmpeg_available=False,
        tts=tts,
    )

    status = service.get()

    assert status.capabilities.voice_ready is False
    assert status.onboarding.voice_ready is False


def test_status_service_uses_replaced_voice():
    service = SystemStatusService(
        soul_id="default",
        loader=Loader(),
        candidates=Candidates(0),
        jobs=Jobs(),
        onboarding=Onboarding(),
        voice=Voice(),
        voice_installed=False,
        ffmpeg_available=False,
    )

    service.replace_voice(type("Voice", (), {"has_reference": True})())

    assert service.get().capabilities.voice_ready is True


def test_status_service_uses_replaced_tts_configuration():
    voice = type("Voice", (), {"has_reference": True})()
    missing_key = type(
        "TTS",
        (), {"provider": "minimax", "minimax": type("MiniMax", (), {"api_key": ""})()},
    )()
    configured = type(
        "TTS",
        (), {"provider": "minimax", "minimax": type("MiniMax", (), {"api_key": "key"})()},
    )()
    service = SystemStatusService(
        soul_id="default",
        loader=Loader(),
        candidates=Candidates(0),
        jobs=Jobs(),
        onboarding=Onboarding(),
        voice=voice,
        voice_installed=False,
        ffmpeg_available=False,
        tts=missing_key,
    )

    service.update_tts(configured)

    assert service.get().capabilities.voice_ready is True
