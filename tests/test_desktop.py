from pathlib import Path

from src.desktop import find_available_port, seed_runtime_files, show_native_window, user_data_root


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


def test_desktop_chooses_an_available_local_port(monkeypatch):
    class CandidateSocket:
        def __enter__(self):
            return self

        def __exit__(self, *_args):
            return None

        def bind(self, address):
            self.address = address

        def getsockname(self):
            return ("127.0.0.1", 43123)

    candidate = CandidateSocket()
    monkeypatch.setattr("src.desktop.socket.socket", lambda *_args: candidate)

    assert find_available_port() == 43123
    assert candidate.address == ("127.0.0.1", 0)


def test_native_window_uses_the_local_app_url():
    class FakeWebview:
        def create_window(self, *args, **kwargs):
            self.window = (args, kwargs)

        def start(self, **kwargs):
            self.started = kwargs

    webview = FakeWebview()
    show_native_window(webview, "http://127.0.0.1:43123/")

    assert webview.window == (
        ("Heaven Agent", "http://127.0.0.1:43123/"),
        {"width": 1280, "height": 820, "min_size": (960, 640), "background_color": "#1c1917"},
    )
    assert webview.started == {"private_mode": True}
