"""Per-project filesystem workspace.

research_data/
    <project_id>/
        project.json
        db.sqlite
        reports/*.md
        raw/            original downloaded artifacts
        exports/        JSONL exports
        prompts/        rendered prompt copies for audit
"""
from __future__ import annotations

from pathlib import Path


class Workspace:
    def __init__(self, data_dir: str | Path, project_id: str):
        self.root = Path(data_dir) / project_id
        self.reports = self.root / "reports"
        self.raw = self.root / "raw"
        self.exports = self.root / "exports"
        self.prompts = self.root / "prompts"
        for d in (self.root, self.reports, self.raw, self.exports, self.prompts):
            d.mkdir(parents=True, exist_ok=True)

    @property
    def db_path(self) -> Path:
        return self.root / "db.sqlite"

    @property
    def project_json(self) -> Path:
        return self.root / "project.json"

    def raw_file_for(self, source_id: str, ext: str) -> Path:
        safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in source_id)
        return self.raw / f"{safe}.{ext}"

    def report_path(self, name: str) -> Path:
        return self.reports / name

    def export_jsonl(self, name: str, rows: list[dict]) -> Path:
        import json
        path = self.exports / f"{name}.jsonl"
        with path.open("w", encoding="utf-8") as f:
            for r in rows:
                f.write(json.dumps(r, default=str) + "\n")
        return path

    def save_prompt_audit(self, task_id: str, role: str, system: str, user: str, response: str) -> None:
        import json
        blob = {"task_id": task_id, "role": role, "system": system[:4000],
                "user": user[:20000], "response": response[:20000]}
        (self.prompts / f"{task_id}_{role}.json").write_text(json.dumps(blob, indent=1))
