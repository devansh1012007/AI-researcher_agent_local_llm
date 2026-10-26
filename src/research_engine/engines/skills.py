"""Engine pack skills/*.md loader with frontmatter parsing and character cap."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path

import yaml

MAX_SKILLS_CHARS = 4000
_FRONTMATTER_RE = re.compile(r"^---\s*\n(.*?)\n---\s*\n", re.DOTALL)


@dataclass(frozen=True)
class SkillDoc:
    name: str
    phase: str
    priority: int
    body: str


def load_pack_skills(pack_dir: Path) -> list[SkillDoc]:
    """Load and sort skills/*.md from an engine pack directory."""
    skills_dir = pack_dir / "skills"
    if not skills_dir.is_dir():
        return []
    docs: list[SkillDoc] = []
    for md_path in sorted(skills_dir.glob("*.md"), key=lambda p: p.name):
        raw = md_path.read_text(encoding="utf-8")
        phase = "all"
        priority = 50
        body = raw
        m = _FRONTMATTER_RE.match(raw)
        if m:
            try:
                meta = yaml.safe_load(m.group(1)) or {}
                if isinstance(meta, dict):
                    phase = str(meta.get("phase", "all")).strip().lower()
                    priority = int(meta.get("priority", 50))
            except Exception:
                pass
            body = raw[m.end():]
        docs.append(SkillDoc(name=md_path.stem, phase=phase, priority=priority, body=body.strip()))
    docs.sort(key=lambda d: (d.priority, d.name))
    return docs


def render_skills_guidance(skills: list[SkillDoc], phase: str | None = None,
                           max_chars: int = MAX_SKILLS_CHARS) -> str:
    """Render skills matching ``phase`` (or 'all') up to ``max_chars`` total."""
    if not skills:
        return ""
    selected = [
        s for s in skills
        if phase is None or s.phase in ("all", phase.lower())
    ]
    if not selected:
        return ""
    chunks: list[str] = []
    used = 0
    for s in selected:
        block = s.body.strip()
        if not block:
            continue
        sep = "\n\n" if chunks else ""
        remaining = max_chars - used - len(sep)
        if remaining <= 0:
            break
        if len(block) > remaining:
            chunks.append(block[:remaining])
            break
        chunks.append(block)
        used += len(sep) + len(block)
    return "\n\n".join(chunks)
