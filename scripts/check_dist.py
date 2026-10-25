#!/usr/bin/env python
"""Release gate: verify a BUILT distribution, not just the source tree.

Why this exists: an editable install (what development uses) points at the
source tree, so it hides packaging defects completely. `fastapi`/`uvicorn` were
undeclared and all 16 prompt templates were excluded from the wheel; the
editable install made both invisible, and the Docker image (`pip install .`)
was dead on arrival.

What it checks:
  1. every prompt template file in the source tree is present in the wheel
  2. the wheel's metadata declares the runtime dependencies the code imports
  3. the EXTRACTED wheel can load its prompts and import the API — i.e. the
     wheel is self-sufficient for package data

Requires a wheel builder on PATH: `uv` (preferred), `python -m build`, or
`pip`. Builders use build isolation, so the first run may need network to
fetch the build backend. Leaves a gitignored `build/` and `src/*.egg-info/`
behind, as any setuptools build does.

Usage:
    .venv/bin/python scripts/check_dist.py
Exit code is non-zero on the first failure.
"""
from __future__ import annotations

import glob
import os
import re
import shutil
import subprocess
import sys
import tempfile
import zipfile
from pathlib import Path

ROOT = Path(__file__).parents[1]
SRC = ROOT / "src"
TEMPLATES_DIR = SRC / "research_engine" / "prompts" / "templates"
REQUIRED_DISTS = ("fastapi", "uvicorn")


def fail(msg: str) -> None:
    print(f"FAIL: {msg}", file=sys.stderr)
    raise SystemExit(1)


def _has_module(name: str) -> bool:
    return subprocess.run([sys.executable, "-c", f"import {name}"],
                          capture_output=True).returncode == 0


def build_wheel(outdir: Path) -> Path:
    """Build a wheel with whichever builder is actually available."""
    # A stale build/ tree can mask a packaging defect: setuptools' bdist_wheel
    # copies from build/lib, so leftovers from a previous build would be
    # re-used. This guard is load-bearing, not decorative.
    stale_paths = [ROOT / "build", *SRC.glob("*.egg-info")]
    for stale in stale_paths:
        if stale.exists():
            shutil.rmtree(stale)

    builders: list[tuple[list[str], str]] = []
    if shutil.which("uv"):
        builders.append((["uv", "build", "--wheel", "--out-dir", str(outdir),
                          str(ROOT)], "uv build"))
    if _has_module("build"):
        builders.append(([sys.executable, "-m", "build", "--wheel", "--outdir",
                          str(outdir), str(ROOT)], "python -m build"))
    if _has_module("pip"):
        builders.append(([sys.executable, "-m", "pip", "wheel", "--no-deps",
                          "--no-build-isolation", "-w", str(outdir), str(ROOT)],
                         "pip wheel"))
    if not builders:
        fail("no wheel builder available: install `uv`, `build` or `pip`")

    cmd, label = builders[0]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        print(proc.stdout[-1500:])
        print(proc.stderr[-1500:], file=sys.stderr)
        fail(f"{label} failed with exit code {proc.returncode}")
    wheels = sorted(glob.glob(str(outdir / "*.whl")))
    if not wheels:
        fail(f"{label} produced no wheel")
    return Path(wheels[-1])


def check_templates_in_wheel(wheel: Path) -> set[str]:
    """Assert every template file is in the wheel; return the template names."""
    names = set(zipfile.ZipFile(wheel).namelist())
    expected = {
        str(p.relative_to(SRC)).replace(os.sep, "/")
        for p in TEMPLATES_DIR.rglob("*") if p.is_file()
    }
    missing = sorted(expected - names)
    if missing:
        fail(f"{len(missing)} template file(s) missing from the wheel: {missing}")
    template_names = {p.name for p in TEMPLATES_DIR.iterdir() if p.is_dir()}
    print(f"  OK  {len(expected)} template files ({len(template_names)} templates) in the wheel")
    return template_names


def check_metadata(wheel: Path) -> None:
    zf = zipfile.ZipFile(wheel)
    meta_names = [n for n in zf.namelist() if n.endswith(".dist-info/METADATA")]
    if not meta_names:
        fail("wheel has no METADATA")
    meta = zf.read(meta_names[0]).decode()
    requires = [line.split(":", 1)[1].strip() for line in meta.splitlines()
                if line.startswith("Requires-Dist:")]
    for dist in REQUIRED_DISTS:
        # Match the requirement NAME, not a prefix: `fastapi>=0.100.0` is a
        # match, `fastapi-extra` is not.
        names = {re.split(r"[<>=!~;\[ ]", r, maxsplit=1)[0].lower() for r in requires}
        if dist.lower() not in names:
            fail(f"{dist} is not declared in the wheel metadata ({requires})")
    print(f"  OK  metadata declares {', '.join(REQUIRED_DISTS)}")


def check_extracted_wheel(wheel: Path, template_names: set[str]) -> None:
    """Extract the wheel and use it as the import source.

    This is the part that proves the wheel is self-sufficient: the prompt
    registry must resolve its templates from the extracted package, and the API
    module must import.
    """
    with tempfile.TemporaryDirectory(dir=("/run/user/1235" if Path("/run/user/1235").is_dir() else None)) as tmp:
        site = Path(tmp) / "site-packages"
        site.mkdir()
        with zipfile.ZipFile(wheel) as zf:
            zf.extractall(site)
        probe = (
            "from research_engine.prompts.registry import get_prompt, record_versions;"
            "v = record_versions();"
            "s = get_prompt('synthesizer');"
            "assert s.template.strip() and s.system.strip(), 'synthesizer prompt is empty';"
            "import research_engine.api.app;"
            "import research_engine;"
            "print('TEMPLATES=' + ','.join(sorted(v)));"
            "print('MODULE=' + research_engine.__file__)"
        )
        env = dict(os.environ)
        env["PYTHONPATH"] = str(site)
        proc = subprocess.run([sys.executable, "-c", probe], capture_output=True,
                              text=True, env=env)
        if proc.returncode != 0:
            print(proc.stdout[-1500:])
            print(proc.stderr[-1500:], file=sys.stderr)
            fail("the extracted wheel could not load its prompts / API")
        found, module_path = "", ""
        for line in proc.stdout.splitlines():
            if line.startswith("TEMPLATES="):
                found = line.split("=", 1)[1]
            elif line.startswith("MODULE="):
                module_path = line.split("=", 1)[1]
        if set(found.split(",")) != template_names:
            fail(f"extracted wheel exposes templates {sorted(found.split(','))}, "
                 f"source tree has {sorted(template_names)}")
        if not module_path.startswith(str(site)):
            fail(f"probe imported {module_path!r}, not the extracted wheel at {site}")
        print(f"  OK  extracted wheel loads {len(template_names)} templates and the API module")


def main() -> int:
    print("check_dist: verifying the built distribution")
    with tempfile.TemporaryDirectory(dir=("/run/user/1235" if Path("/run/user/1235").is_dir() else None)) as tmp:
        wheel = build_wheel(Path(tmp))
        template_names = check_templates_in_wheel(wheel)
        check_metadata(wheel)
        check_extracted_wheel(wheel, template_names)
    print("check_dist: OK")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
