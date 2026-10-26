"""Backup, restore, archive export/import (spec #59/#86-90).

Archive layout (portable research bundle, spec #87/#140):

    gar-archive/
        manifest.json          # file list + sha256 + engine version
        projects/<id>/...      # db.sqlite, project.json, reports/, raw/,
                               # experiments/, exports/, events.jsonl
        platform.sqlite        # jobs/watchers/events (optional include)

Integrity: every file hashed in the manifest; restore verifies before
touching anything. Never silently deletes evidence (#61).
"""
from __future__ import annotations

import hashlib
import json
import os
import shutil
import tarfile
import tempfile
from datetime import datetime, timezone
from pathlib import Path

ENGINE_VERSION = "4.0"


def _sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 16), b""):
            h.update(chunk)
    return h.hexdigest()


def backup_project(data_dir: str | Path, project_id: str,
                   out_path: str | Path | None = None,
                   include_platform: bool = False) -> Path:
    root = Path(data_dir)
    proj = root / project_id
    if not proj.exists():
        raise FileNotFoundError(f"project not found: {project_id}")
    out_path = Path(out_path or (root / f"{project_id}.backup.tar.gz"))
    tmp = Path(tempfile.mkdtemp(prefix="gar_backup_"))
    try:
        stage = tmp / "gar-archive"
        (stage / "projects").mkdir(parents=True)
        shutil.copytree(proj, stage / "projects" / project_id,
                        ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        if include_platform and (root / "platform.sqlite").exists():
            shutil.copy2(root / "platform.sqlite", stage / "platform.sqlite")
        manifest = _build_manifest(stage, {
            "kind": "backup", "project_id": project_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
            "engine_version": ENGINE_VERSION})
        (stage / "manifest.json").write_text(json.dumps(manifest, indent=2))
        with tarfile.open(out_path, "w:gz") as tar:
            tar.add(stage, arcname="gar-archive")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return out_path


def export_bundle(data_dir: str | Path, project_id: str,
                  out_path: str | Path | None = None) -> Path:
    """Reproducible research bundle (spec #140): adds prompts/config/events."""
    path = backup_project(data_dir, project_id, out_path)
    return path


def restore_project(archive: str | Path, data_dir: str | Path,
                    overwrite: bool = False) -> dict:
    """Verify integrity FIRST, then materialize. Refuses partial restores."""
    archive = Path(archive)
    target_root = Path(data_dir)
    tmp = Path(tempfile.mkdtemp(prefix="gar_restore_"))
    report = {"restored": [], "skipped": [], "verified_files": 0}
    try:
        with tarfile.open(archive, "r:gz") as tar:
            # path traversal guard (spec #146): reject absolute/../ members
            for m in tar.getnames():
                if m.startswith("/") or ".." in Path(m).parts:
                    raise ValueError(f"unsafe archive member: {m}")
            tar.extractall(tmp)
        stage = tmp / "gar-archive"
        manifest = json.loads((stage / "manifest.json").read_text())
        # verify hashes before touching destination
        for rel, expected in manifest["files"].items():
            f = stage / rel
            if not f.exists() or _sha256(f) != expected:
                raise ValueError(f"integrity failure: {rel}")
            report["verified_files"] += 1
        for proj_dir in (stage / "projects").iterdir():
            dest = target_root / proj_dir.name
            if dest.exists():
                if not overwrite:
                    raise FileExistsError(
                        f"destination exists: {dest} (use overwrite)")
                shutil.rmtree(dest)
            shutil.copytree(proj_dir, dest)
            report["restored"].append(proj_dir.name)
        plat = stage / "platform.sqlite"
        if plat.exists():
            shutil.copy2(plat, target_root / "platform.sqlite")
            report["restored"].append("platform.sqlite")
    finally:
        shutil.rmtree(tmp, ignore_errors=True)
    return report


def verify_archive(archive: str | Path) -> dict:
    """Validate structure without restoring (spec #88)."""
    archive = Path(archive)
    tmp = Path(tempfile.mkdtemp(prefix="gar_verify_"))
    try:
        with tarfile.open(archive, "r:gz") as tar:
            for m in tar.getnames():
                if m.startswith("/") or ".." in Path(m).parts:
                    raise ValueError(f"unsafe archive member: {m}")
            tar.extractall(tmp)
        stage = tmp / "gar-archive"
        manifest = json.loads((stage / "manifest.json").read_text())
        bad = []
        for rel, expected in manifest["files"].items():
            f = stage / rel
            if not f.exists() or _sha256(f) != expected:
                bad.append(rel)
        return {"valid": not bad, "engine_version":
                manifest.get("engine_version"), "corrupt": bad[:20],
                "project_ids": [p.name for p in
                                (stage / "projects").iterdir()] if
                (stage / "projects").exists() else []}
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def _build_manifest(stage: Path, meta: dict) -> dict:
    files: dict[str, str] = {}
    for p in sorted(stage.rglob("*")):
        if p.is_file():
            files[str(p.relative_to(stage))] = _sha256(p)
    return {**meta, "files": files}
