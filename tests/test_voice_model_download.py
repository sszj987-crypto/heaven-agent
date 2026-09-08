from scripts.download_voice_model import MODEL_REPO, MODEL_REVISION, download_model


def test_download_model_uses_pinned_revision_and_validates_weight(tmp_path):
    calls = []

    def fake_snapshot_download(**kwargs):
        calls.append(kwargs)
        (tmp_path / "model.safetensors").write_bytes(b"weights")

    download_model(tmp_path, snapshot_download=fake_snapshot_download)

    assert calls == [{
        "repo_id": MODEL_REPO,
        "revision": MODEL_REVISION,
        "local_dir": tmp_path,
    }]


def test_existing_weight_skips_download(tmp_path):
    (tmp_path / "model.safetensors").write_bytes(b"weights")
    called = []

    download_model(tmp_path, snapshot_download=lambda **kwargs: called.append(kwargs))

    assert called == []
