from pathlib import Path

from src.desktop import seed_runtime_files, user_data_root


def test_user_data_root_uses_macos_application_support(tmp_path):
    assert user_data_root(tmp_path) == (
        tmp_path / "Library" / "Application Support" / "Heaven Agent"
    )


def test_seed_runtime_files_preserves_existing_user_configuration(tmp_path):
    bundled = tmp_path / "bundle"
    (bundled / "config" / "souls" / "demo").mkdir(parents=True)
    (bundled / "config" / "app.json").write_text('{"soul_id":"demo"}', encoding="utf-8")
    (bundled / "config" / "souls" / "demo" / "basic_info.md").write_text("默认", encoding="utf-8")

    runtime = tmp_path / "runtime"
    seed_runtime_files(bundled, runtime)
    (runtime / "config" / "app.json").write_text('{"soul_id":"mine"}', encoding="utf-8")
    (bundled / "config" / "souls" / "demo" / "personality.md").write_text("新增", encoding="utf-8")

    seed_runtime_files(bundled, runtime)

    assert (runtime / "config" / "app.json").read_text(encoding="utf-8") == '{"soul_id":"mine"}'
    assert (runtime / "config" / "souls" / "demo" / "personality.md").read_text(encoding="utf-8") == "新增"
    assert (runtime / "data").is_dir()
    assert (runtime / "log").is_dir()
