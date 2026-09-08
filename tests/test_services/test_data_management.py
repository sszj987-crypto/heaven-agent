import io
import zipfile

from src.data.layout import SoulDataLayout
from src.memory.candidates import MemoryCandidate
from src.services.data_management import DataManagementService


def test_export_contains_current_soul_files_with_scoped_paths(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "soul_a")
    layout.initialize()
    (layout.profile_dir / "basic_info.md").write_text("姓名：小安", encoding="utf-8")
    layout.conversation_path.write_text("[]", encoding="utf-8")
    service = DataManagementService(layout)

    payload = service.export_zip()

    with zipfile.ZipFile(io.BytesIO(payload)) as archive:
        names = archive.namelist()
        assert "soul_a/profile/basic_info.md" in names
        assert "soul_a/conversation.json" in names
        assert all(".." not in name for name in names)


def test_diagnostics_does_not_include_file_contents_or_secrets(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "soul_a")
    layout.initialize()
    (layout.profile_dir / "basic_info.md").write_text("SECRET PERSON", encoding="utf-8")
    service = DataManagementService(layout)

    result = service.diagnostics(
        voice_installed=False,
        voice_ready=False,
        memory_ready=True,
        ffmpeg_available=False,
    )

    rendered = str(result)
    assert "SECRET PERSON" not in rendered
    assert result["soul_id"] == "soul_a"
    assert result["profile_files"] == 1


def test_archive_conversation_moves_index_and_candidate_provenance(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "default")
    layout.initialize()
    layout.conversation_path.write_text("[]", encoding="utf-8")
    memory_store = FakeMemoryStore()
    candidates = FakeCandidates()
    service = DataManagementService(layout)

    archived = service.archive_conversation(memory_store, candidates, "session-test")

    assert (archived / "conversation.json").exists()
    assert (archived / "memory-summaries.json").exists()
    assert (archived / "conversation-candidates.json").exists()
    assert memory_store.deleted == ["conversation"]
    assert candidates.extracted == ["conversation"]


def test_reset_demo_archives_user_data_before_restoring_template(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "default")
    layout.initialize()
    (layout.profile_dir / "basic_info.md").write_text("姓名: PRIVATE", encoding="utf-8")
    (layout.voice_dir / "reference_audio.wav").write_bytes(b"private voice")
    layout.conversation_path.write_text("private chat", encoding="utf-8")
    layout.candidates_path.write_text("[]", encoding="utf-8")
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "basic_info.md").write_text("姓名: 演示人物", encoding="utf-8")
    memory = FakeClearableMemory()

    backup = DataManagementService(layout).reset_demo(demo, memory, "reset-test")

    assert (backup / "profile" / "basic_info.md").read_text(encoding="utf-8") == "姓名: PRIVATE"
    assert (backup / "voice" / "reference_audio.wav").read_bytes() == b"private voice"
    assert (backup / "conversation.json").read_text(encoding="utf-8") == "private chat"
    assert (layout.profile_dir / "basic_info.md").read_text(encoding="utf-8") == "姓名: 演示人物"
    assert not layout.conversation_path.exists()
    assert not layout.candidates_path.exists()
    assert memory.cleared is True


def test_reset_demo_missing_template_leaves_user_data_untouched(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "default")
    layout.initialize()
    profile = layout.profile_dir / "basic_info.md"
    profile.write_text("姓名: PRIVATE", encoding="utf-8")

    import pytest
    with pytest.raises(FileNotFoundError):
        DataManagementService(layout).reset_demo(tmp_path / "missing", None, "reset-test")

    assert profile.read_text(encoding="utf-8") == "姓名: PRIVATE"


def test_reset_demo_rolls_back_active_data_when_index_clear_fails(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "default")
    layout.initialize()
    (layout.profile_dir / "basic_info.md").write_text("姓名: PRIVATE", encoding="utf-8")
    (layout.voice_dir / "reference_audio.wav").write_bytes(b"private voice")
    layout.conversation_path.write_text("private chat", encoding="utf-8")
    demo = tmp_path / "demo"
    demo.mkdir()
    (demo / "basic_info.md").write_text("姓名: 演示人物", encoding="utf-8")

    import pytest
    with pytest.raises(RuntimeError, match="index unavailable"):
        DataManagementService(layout).reset_demo(
            demo, FailingClearableMemory(), "reset-failure"
        )

    assert (layout.profile_dir / "basic_info.md").read_text(encoding="utf-8") == "姓名: PRIVATE"
    assert (layout.voice_dir / "reference_audio.wav").read_bytes() == b"private voice"
    assert layout.conversation_path.read_text(encoding="utf-8") == "private chat"


class FakeMemoryStore:
    def __init__(self):
        self.deleted = []

    def get_by_dimension(self, dimension):
        return [{"id": "mem-1", "document": "摘要", "metadata": {"dimension": dimension}}]

    def delete_by_dimension(self, dimension):
        self.deleted.append(dimension)
        return 1


class FakeCandidates:
    def __init__(self):
        self.extracted = []

    def extract_by_source_type(self, source_type):
        self.extracted.append(source_type)
        return [MemoryCandidate(
            id="candidate-1",
            dimension="relationships",
            content="事实",
            source_type=source_type,
            source_excerpt="原文",
            confidence=0.7,
            status="pending",
            conflict_with=None,
            created_at="now",
            resolved_at=None,
        )]


class FakeClearableMemory:
    def __init__(self):
        self.cleared = False

    def clear(self):
        self.cleared = True
        return 1


class FailingClearableMemory:
    def clear(self):
        raise RuntimeError("index unavailable")
