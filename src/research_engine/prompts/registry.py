"""Versioned prompt template registry.

prompts/templates/<name>/<version>.txt with optional <version>.meta.yaml
(system prompt, role assignment). Prompts are externalized, never inlined.
Rendered copies are saved to the project workspace for audit.
"""
from __future__ import annotations

import functools
from pathlib import Path

import yaml

TEMPLATES_DIR = Path(__file__).parent / "templates"

# Decision: a missing templates directory is an incomplete INSTALLATION, not a
# missing prompt. The two failures need different fixes, so they get different
# messages.
# Why: the templates are package data; if they are absent, the wheel was built
# without them and every prompt render will fail. An actionable message beats a
# bare FileNotFoundError from iterdir().
_INSTALL_INCOMPLETE = (
    "prompt templates directory is missing at {path}. The installation is "
    "incomplete (package data was not installed). Reinstall with "
    "`pip install .` or use an editable install (`pip install -e .`)."
)


def _require_templates_dir() -> None:
    if not TEMPLATES_DIR.is_dir():
        raise FileNotFoundError(_INSTALL_INCOMPLETE.format(path=TEMPLATES_DIR))


class PromptSpec:
    def __init__(self, name: str, version: str, system: str, template: str):
        self.name = name
        self.version = version
        self.system = system
        self.template = template

    def render(self, **kwargs) -> str:
        out = self.template
        for k, v in kwargs.items():
            out = out.replace("{{" + k + "}}", str(v))
        # fail loudly only on OUR placeholders (lowercase snake_case) left unfilled;
        # braces inside untrusted document content must never crash the pipeline
        import re
        for m in re.finditer(r"\{\{\s*([a-z][a-z0-9_]*)\s*\}\}", out):
            if m.group(1) not in kwargs:
                raise ValueError(f"unknown/unfilled placeholder '{m.group(1)}' in prompt {self.name}")
        return out


@functools.lru_cache(maxsize=None)
def _load(name: str, version: str | None = None) -> PromptSpec:
    _require_templates_dir()
    base = TEMPLATES_DIR / name
    if not base.exists():
        raise FileNotFoundError(f"prompt template '{name}' not found")
    if version is None:
        versions = sorted(p.stem for p in base.glob("v*.txt"))
        if not versions:
            raise FileNotFoundError(f"no versions for prompt '{name}'")
        version = versions[-1].lstrip("v")  # latest
    txt_path = base / f"v{version}.txt"
    meta_path = base / f"v{version}.meta.yaml"
    meta = {}
    if meta_path.exists():
        meta = yaml.safe_load(meta_path.read_text()) or {}
    return PromptSpec(name=name, version=version,
                      system=meta.get("system", ""),
                      template=txt_path.read_text())


def get_prompt(name: str, version: str | None = None) -> PromptSpec:
    return _load(name, version)


def record_versions() -> dict[str, str]:
    _require_templates_dir()
    out = {}
    for d in TEMPLATES_DIR.iterdir():
        if d.is_dir():
            versions = sorted(p.stem for p in d.glob("v*.txt"))
            if versions:
                out[d.name] = versions[-1]
    return out
