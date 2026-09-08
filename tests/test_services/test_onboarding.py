from src.services.onboarding import OnboardingStore


def test_first_run_is_incomplete_until_explicitly_finished(tmp_path):
    store = OnboardingStore(tmp_path / "onboarding.json")

    assert store.completed is False

    store.complete()

    assert store.completed is True
    assert OnboardingStore(tmp_path / "onboarding.json").completed is True


def test_first_run_steps_require_explicit_markers(tmp_path):
    store = OnboardingStore(tmp_path / "onboarding.json")

    assert store.profile_completed is False
    assert store.import_review_completed is False
    assert store.voice_completed is False

    store.mark_step("profile")
    store.mark_step("import_review")

    reloaded = OnboardingStore(tmp_path / "onboarding.json")
    assert reloaded.profile_completed is True
    assert reloaded.import_review_completed is True
    assert reloaded.voice_completed is False


def test_legacy_completed_marker_implies_all_steps(tmp_path):
    path = tmp_path / "onboarding.json"
    path.write_text('{"completed": true}', encoding="utf-8")

    store = OnboardingStore(path)

    assert store.profile_completed is True
    assert store.import_review_completed is True
    assert store.voice_completed is True
