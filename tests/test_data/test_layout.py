from pathlib import Path

from src.data.layout import SoulDataLayout


def test_initialize_creates_scoped_soul_directories(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "default")

    layout.initialize()

    assert layout.profile_dir.is_dir()
    assert layout.voice_dir.is_dir()
    assert layout.daily_dir.is_dir()
    assert layout.memory_db_dir.is_dir()
    assert layout.conversation_path.parent == layout.soul_dir


def test_migration_copies_and_backs_up_without_deleting_legacy_data(tmp_path):
    legacy_soul = tmp_path / "config" / "souls" / "person"
    legacy_soul.mkdir(parents=True)
    (legacy_soul / "basic_info.md").write_text("姓名: 测试人物", encoding="utf-8")
    legacy_conversation = tmp_path / "config" / "conversation.json"
    legacy_conversation.write_text("[]", encoding="utf-8")

    layout = SoulDataLayout(tmp_path / "data", "default")
    result = layout.migrate_legacy(
        legacy_soul=legacy_soul,
        legacy_conversation=legacy_conversation,
        backup_name="test-backup",
    )

    assert (layout.profile_dir / "basic_info.md").read_text(encoding="utf-8") == "姓名: 测试人物"
    assert layout.conversation_path.read_text(encoding="utf-8") == "[]"
    assert (legacy_soul / "basic_info.md").exists()
    assert legacy_conversation.exists()
    assert (result.backup_dir / "soul" / "basic_info.md").exists()
    assert (result.backup_dir / "conversation.json").exists()
    assert layout.migration_marker_path.exists()


def test_migration_marker_is_written_only_after_verified_copy(tmp_path, monkeypatch):
    legacy_soul = tmp_path / "legacy"
    legacy_soul.mkdir()
    (legacy_soul / "basic_info.md").write_text("姓名: 测试", encoding="utf-8")
    layout = SoulDataLayout(tmp_path / "data", "default")

    monkeypatch.setattr(
        "src.data.layout._copy_file_atomic",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("copy interrupted")),
    )

    import pytest
    with pytest.raises(OSError, match="interrupted"):
        layout.migrate_legacy(legacy_soul=legacy_soul, backup_name="failed")

    assert not layout.migration_marker_path.exists()


def test_existing_scoped_profile_is_not_overwritten_by_migration(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "default")
    layout.initialize()
    (layout.profile_dir / "basic_info.md").write_text("姓名: 新档案", encoding="utf-8")
    legacy_soul = tmp_path / "legacy"
    legacy_soul.mkdir()
    (legacy_soul / "basic_info.md").write_text("姓名: 旧档案", encoding="utf-8")

    layout.migrate_legacy(legacy_soul=legacy_soul, backup_name="backup")

    assert (layout.profile_dir / "basic_info.md").read_text(encoding="utf-8") == "姓名: 新档案"


def test_archive_chat_moves_history_and_daily_files_to_recoverable_trash(tmp_path):
    layout = SoulDataLayout(tmp_path / "data", "default")
    layout.initialize()
    layout.conversation_path.write_text('[{"role":"user"}]', encoding="utf-8")
    (layout.daily_dir / "2026-08-24.md").write_text("private diary", encoding="utf-8")

    archived = layout.archive_chat("test-session")

    assert not layout.conversation_path.exists()
    assert not (layout.daily_dir / "2026-08-24.md").exists()
    assert (archived / "conversation.json").exists()
    assert (archived / "daily" / "2026-08-24.md").exists()
    assert layout.daily_dir.is_dir()
