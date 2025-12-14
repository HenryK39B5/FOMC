from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
import json
from pathlib import Path
from typing import Any, Dict, Optional

from fomc.config.paths import MEETING_RUNS_DIR


def _utc_now() -> str:
    return datetime.utcnow().isoformat(timespec="seconds") + "Z"


@dataclass(frozen=True)
class MeetingRun:
    meeting_id: str
    run_dir: Path
    manifest_path: Path


def get_run_dir(meeting_id: str) -> Path:
    MEETING_RUNS_DIR.mkdir(parents=True, exist_ok=True)
    return MEETING_RUNS_DIR / meeting_id


def ensure_meeting_run(meeting_id: str) -> MeetingRun:
    run_dir = get_run_dir(meeting_id)
    run_dir.mkdir(parents=True, exist_ok=True)
    manifest_path = run_dir / "manifest.json"
    if not manifest_path.exists():
        payload: Dict[str, Any] = {
            "meeting_id": meeting_id,
            "created_at": _utc_now(),
            "updated_at": _utc_now(),
            "context": {},
            "artifacts": {},
        }
        manifest_path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    return MeetingRun(meeting_id=meeting_id, run_dir=run_dir, manifest_path=manifest_path)


def load_manifest(run: MeetingRun) -> Dict[str, Any]:
    return json.loads(run.manifest_path.read_text(encoding="utf-8"))


def save_manifest(run: MeetingRun, manifest: Dict[str, Any]) -> None:
    manifest["updated_at"] = _utc_now()
    run.manifest_path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def set_context(run: MeetingRun, context: Dict[str, Any]) -> Dict[str, Any]:
    manifest = load_manifest(run)
    manifest["context"] = context or {}
    save_manifest(run, manifest)
    return manifest


def artifact_path(run: MeetingRun, name: str, *, ext: str = "md") -> Path:
    safe = "".join(ch for ch in (name or "").strip().lower() if ch.isalnum() or ch in ("-", "_"))
    if not safe:
        raise ValueError("Invalid artifact name")
    return run.run_dir / f"{safe}.{ext}"


def read_artifact_text(run: MeetingRun, name: str) -> Optional[str]:
    path = artifact_path(run, name, ext="md")
    if not path.exists():
        return None
    return path.read_text(encoding="utf-8")

def read_artifact_json(run: MeetingRun, name: str) -> Optional[Dict[str, Any]]:
    path = artifact_path(run, name, ext="json")
    if not path.exists():
        return None
    return json.loads(path.read_text(encoding="utf-8"))


def write_artifact_text(
    run: MeetingRun,
    name: str,
    text: str,
    *,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    path = artifact_path(run, name, ext="md")
    path.write_text(text or "", encoding="utf-8")

    manifest = load_manifest(run)
    artifacts = manifest.setdefault("artifacts", {})
    artifacts[name] = {
        "path": str(path.relative_to(MEETING_RUNS_DIR.parent)),
        "updated_at": _utc_now(),
        "bytes": path.stat().st_size,
        "meta": meta or {},
    }
    save_manifest(run, manifest)
    return artifacts[name]


def write_artifact_json(
    run: MeetingRun,
    name: str,
    payload: Dict[str, Any],
    *,
    meta: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    path = artifact_path(run, name, ext="json")
    path.write_text(json.dumps(payload or {}, ensure_ascii=False, indent=2), encoding="utf-8")

    manifest = load_manifest(run)
    artifacts = manifest.setdefault("artifacts", {})
    artifacts[name] = {
        "path": str(path.relative_to(MEETING_RUNS_DIR.parent)),
        "updated_at": _utc_now(),
        "bytes": path.stat().st_size,
        "meta": meta or {},
    }
    save_manifest(run, manifest)
    return artifacts[name]
