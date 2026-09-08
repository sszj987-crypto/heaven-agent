import asyncio
import time
from types import SimpleNamespace

from fastapi.testclient import TestClient

from src.agent.context import PipelineContext
from src.config.loader import LLMConfig, VoiceProviderConfig
from src.data.layout import SoulDataLayout
from src.main import create_app
from src.memory.candidates import CandidateStore
from src.services.candidates import CandidateService
from src.services.data_management import DataManagementService
from src.services.imports import ImportReviewService
from src.services.jobs import JobManager
from src.services.onboarding import OnboardingStore
from src.services.status import SystemStatusService
from src.soul.loader import SoulLoader


def test_empty_profile_to_reviewed_voice_chat_journey(tmp_path):
    container = JourneyContainer(tmp_path)
    app = create_app(lambda _root, _settings: container)

    with TestClient(app) as client:
        initial = client.get("/system/status").json()
        assert initial["initialization"] == "degraded"

        assert client.put(
            "/soul/basic_info",
            json={"content": "姓名: 演示奶奶\n"},
        ).status_code == 200
        assert client.post("/system/onboarding/steps/profile").status_code == 200

        accepted = client.post(
            "/soul/imports",
            files={"file": ("chat.txt", "她很重视家人", "text/plain")},
        )
        job_id = accepted.json()["job_id"]
        for _ in range(50):
            job = client.get(f"/jobs/{job_id}").json()
            if job["status"] == "completed":
                break
            time.sleep(0.01)
        assert job["status"] == "completed"

        candidates = client.get("/memory/candidates").json()
        assert len(candidates) == 1
        approved = client.post(
            f"/memory/candidates/{candidates[0]['id']}/approve",
            json={},
        )
        assert approved.status_code == 200
        assert client.post(
            "/system/onboarding/steps/import_review"
        ).status_code == 200

        voice = client.post(
            "/settings/voice/upload",
            files={"audio": ("voice.wav", b"RIFFdemo", "audio/wav")},
        )
        assert voice.status_code == 200
        assert client.post("/system/onboarding/steps/voice").status_code == 200
        assert client.get("/settings/voice/status").json()["has_reference"] is True

        completed = client.post("/system/onboarding/complete")
        assert completed.status_code == 200
        assert completed.json()["onboarding"]["completed"] is True

        reply = client.post("/chat", json={"message": "你好"})
        assert reply.status_code == 200
        assert reply.json()["response_text"] == "旅程完成"


class JourneyContainer:
    def __init__(self, root):
        self.root = root
        self.soul_lock = asyncio.Lock()
        self.layout = SoulDataLayout(root / "data", "default")
        self.layout.initialize()
        self.settings = SimpleNamespace(
            soul_id="default",
            llm=LLMConfig(
                base_url="https://api.test/v1",
                api_key="test-key",
                model="test-model",
            ),
            tts=VoiceProviderConfig(),
        )
        self.soul_loader = SoulLoader(self.layout.profile_dir)
        self.candidates = CandidateStore(self.layout.candidates_path)
        self.candidate_service = CandidateService(
            self.candidates,
            self.soul_loader,
            lambda: None,
        )
        self.import_reviews = ImportReviewService(self.candidates)
        self.jobs = JobManager()
        self.onboarding = OnboardingStore(self.layout.onboarding_path)
        self.voice = JourneyVoice()
        self.voice_installed = True
        self.memory_store = None
        self.agent_loop = JourneyAgent()
        self.distiller = JourneyDistiller()
        self.data_management = DataManagementService(self.layout)
        self.status_service = SystemStatusService(
            soul_id="default",
            loader=self.soul_loader,
            candidates=self.candidates,
            jobs=self.jobs,
            onboarding=self.onboarding,
            voice=self.voice,
            voice_installed=True,
            ffmpeg_available=False,
        )

    async def save_voice_reference(self, audio, _filename, _content_type):
        self.voice.save_reference_audio(audio)
        return None

    async def close(self):
        await self.jobs.shutdown()


class JourneyVoice:
    def __init__(self):
        self.has_reference = False

    def save_reference_audio(self, _audio):
        self.has_reference = True


class JourneyAgent:
    messages = []

    def invalidate_soul_cache(self):
        return None

    async def run_once(self, message):
        context = PipelineContext(user_message=message)
        context.response = "旅程完成"
        context.instruct_text = "温和地说"
        return context


class JourneyDistiller:
    async def distill(self, _text, chat_name="", *, apply_changes=True):
        assert apply_changes is False
        return SimpleNamespace(
            changes=["relationships"],
            profile={"relationships": "- 她很重视家人"},
            summary="发现一条关系候选",
            skill_card=None,
        )
