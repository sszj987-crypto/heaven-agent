from __future__ import annotations

import io
import json
import platform
import shutil
import sys
import tempfile
import zipfile
from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path

from ..data.layout import SoulDataLayout
from ..data.files import atomic_write_text


class DataManagementService:
    def __init__(self, layout: SoulDataLayout):
        self._layout = layout

    def export_zip(self) -> bytes:
        """Export user-owned Soul data; omit the rebuildable vector index and trash."""
        buffer = io.BytesIO()
        prefix = self._layout.soul_id
        with zipfile.ZipFile(buffer, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for path in sorted(self._layout.soul_dir.rglob("*")):
                if not path.is_file():
                    continue
                relative = path.relative_to(self._layout.soul_dir)
                if relative.parts[:2] == ("memory", "index") or ".trash" in relative.parts:
                    continue
                archive.write(path, f"{prefix}/{relative.as_posix()}")
        return buffer.getvalue()

    def archive_conversation(
        self,
        memory_store,
        candidate_store,
        archive_name: str | None = None,
    ):
        """Archive all session-derived artifacts, then remove them from active lookup."""
        destination = self._layout.archive_chat(archive_name)

        if memory_store is not None:
            summaries = memory_store.get_by_dimension("conversation")
            if summaries:
                atomic_write_text(
                    destination / "memory-summaries.json",
                    json.dumps(summaries, ensure_ascii=False, indent=2, default=str),
                )
                memory_store.delete_by_dimension("conversation")

        candidates = candidate_store.extract_by_source_type("conversation")
        if candidates:
            atomic_write_text(
                destination / "conversation-candidates.json",
                json.dumps(
                    [asdict(item) for item in candidates],
                    ensure_ascii=False,
                    indent=2,
                ),
            )
        return destination

    def reset_demo(
        self,
        demo_profile_dir: Path,
        memory_store,
        backup_name: str | None = None,
    ) -> Path:
        """Recoverably reset canonical Soul data to the sanitized demo template."""
        demo_profile_dir = Path(demo_profile_dir)
        if not demo_profile_dir.is_dir():
            raise FileNotFoundError(f"demo profile not found: {demo_profile_dir}")
        stamp = backup_name or datetime.now(timezone.utc).strftime("demo-reset-%Y%m%dT%H%M%SZ")
        if not stamp or any(
            char not in "abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789-_"
            for char in stamp
        ):
            raise ValueError("backup name contains unsupported characters")
        backup = self._layout.data_root / "backups" / stamp / self._layout.soul_id
        suffix = 1
        while backup.exists():
            backup = self._layout.data_root / "backups" / f"{stamp}-{suffix}" / self._layout.soul_id
            suffix += 1
        backup.mkdir(parents=True)

        artifacts = (
            (self._layout.profile_dir, backup / "profile"),
            (self._layout.voice_dir, backup / "voice"),
            (self._layout.daily_dir, backup / "memory" / "daily"),
            (self._layout.conversation_path, backup / "conversation.json"),
            (self._layout.candidates_path, backup / "memory" / "candidates.json"),
            (self._layout.feedback_path, backup / "feedback.json"),
            (self._layout.onboarding_path, backup / "onboarding.json"),
        )
        existed = {source: source.exists() for source, _ in artifacts}
        for source, destination in artifacts:
            if not existed[source]:
                continue
            destination.parent.mkdir(parents=True, exist_ok=True)
            if source.is_dir():
                shutil.copytree(source, destination)
            else:
                shutil.copy2(source, destination)

        with tempfile.TemporaryDirectory(
            prefix=".demo-reset-", dir=self._layout.data_root
        ) as temporary:
            staged_profile = Path(temporary) / "profile"
            shutil.copytree(demo_profile_dir, staged_profile)
            try:
                self._remove_active_artifacts(artifacts)
                self._layout.initialize()
                shutil.copytree(
                    staged_profile, self._layout.profile_dir, dirs_exist_ok=True
                )
                if memory_store is not None:
                    memory_store.clear()
            except Exception:
                self._remove_active_artifacts(artifacts)
                self._layout.initialize()
                for source, saved in artifacts:
                    if not existed[source]:
                        continue
                    source.parent.mkdir(parents=True, exist_ok=True)
                    if saved.is_dir():
                        shutil.copytree(saved, source, dirs_exist_ok=True)
                    else:
                        shutil.copy2(saved, source)
                raise
        return backup

    @staticmethod
    def _remove_active_artifacts(artifacts) -> None:
        for source, _ in artifacts:
            if source.is_dir():
                shutil.rmtree(source)
            elif source.exists():
                source.unlink()

    def diagnostics(
        self,
        *,
        voice_installed: bool,
        voice_ready: bool,
        memory_ready: bool,
        ffmpeg_available: bool,
    ) -> dict:
        """Return metadata-only diagnostics without secrets or private contents."""
        return {
            "soul_id": self._layout.soul_id,
            "python": platform.python_version(),
            "platform": platform.platform(),
            "supported_python": (3, 11) <= sys.version_info[:2] <= (3, 13),
            "profile_files": sum(1 for path in self._layout.profile_dir.glob("*.md") if path.is_file()),
            "voice_installed": voice_installed,
            "voice_ready": voice_ready,
            "memory_ready": memory_ready,
            "ffmpeg": ffmpeg_available,
        }
