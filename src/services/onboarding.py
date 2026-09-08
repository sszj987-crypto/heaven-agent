import json
import os
import tempfile
from pathlib import Path


class OnboardingStore:
    _STEP_FIELDS = {
        "profile": "profile_completed",
        "import_review": "import_review_completed",
        "voice": "voice_completed",
    }

    def __init__(self, path: Path):
        self._path = Path(path)

    @property
    def completed(self) -> bool:
        return bool(self._load().get("completed"))

    @property
    def profile_completed(self) -> bool:
        return self._step_completed("profile_completed")

    @property
    def import_review_completed(self) -> bool:
        return self._step_completed("import_review_completed")

    @property
    def voice_completed(self) -> bool:
        return self._step_completed("voice_completed")

    def mark_step(self, step: str) -> None:
        try:
            field = self._STEP_FIELDS[step]
        except KeyError as exc:
            raise ValueError(f"unknown onboarding step: {step}") from exc
        state = self._load()
        state[field] = True
        self._save(state)

    def complete(self) -> None:
        state = self._load()
        state["completed"] = True
        self._save(state)

    def _step_completed(self, field: str) -> bool:
        state = self._load()
        return bool(state.get("completed") or state.get(field))

    def _load(self) -> dict:
        if not self._path.exists():
            return {}
        try:
            state = json.loads(self._path.read_text(encoding="utf-8"))
            return state if isinstance(state, dict) else {}
        except (OSError, json.JSONDecodeError):
            return {}

    def _save(self, state: dict) -> None:
        self._path.parent.mkdir(parents=True, exist_ok=True)
        fd, temporary = tempfile.mkstemp(prefix=".onboarding-", dir=self._path.parent)
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as handle:
                json.dump(state, handle)
                handle.flush()
                os.fsync(handle.fileno())
            os.replace(temporary, self._path)
        finally:
            if os.path.exists(temporary):
                os.unlink(temporary)
