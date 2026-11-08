"""requirements-eval.txt holds exactly the engine adapters' REQUIREMENTS, as
exact pins that can be installed together on every platform."""

import re
from pathlib import Path

import pytest
from packaging.requirements import Requirement
from packaging.utils import canonicalize_name

from ocr_eval.engines import discover

REQUIREMENTS_EVAL = Path(__file__).resolve().parents[1] / "requirements-eval.txt"
# the groups the file documents but doesn't install (commented-out pins)
COMMENTED_PIN = re.compile(r"^#\s*([A-Za-z0-9][A-Za-z0-9_.\[\],-]*==\S+)\s*$")
# the project's Python
PYTHON = {"python_version": "3.13", "python_full_version": "3.13.0"}
ENVIRONMENTS = {
    "windows": {"sys_platform": "win32", "platform_machine": "AMD64", **PYTHON},
    "linux": {"sys_platform": "linux", "platform_machine": "x86_64", **PYTHON},
    "macos-arm64": {"sys_platform": "darwin", "platform_machine": "arm64", **PYTHON},
}


def _key(requirement: Requirement) -> tuple:
    return canonicalize_name(requirement.name), tuple(sorted(requirement.extras))


def _pins() -> tuple[list[Requirement], list[Requirement]]:
    """(installed, commented-out) requirements of the file."""
    installed, commented = [], []
    for line in REQUIREMENTS_EVAL.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("-r "):
            continue
        if line.startswith("#"):
            match = COMMENTED_PIN.match(line)
            if match:
                commented.append(Requirement(match.group(1)))
            continue
        installed.append(Requirement(line))
    return installed, commented


def test_every_pin_is_exact():
    installed, commented = _pins()
    assert installed and commented
    for requirement in installed + commented:
        [spec] = list(requirement.specifier)
        assert spec.operator == "==", requirement


def test_the_file_matches_the_adapters_requirements():
    installed, commented = _pins()
    pinned = {}
    for requirement in installed + commented:
        pinned.setdefault(_key(requirement), set()).add(str(requirement.specifier))
    adapters = set()
    for engine in discover().engines.values():
        for spec in engine.requirements:
            requirement = Requirement(spec)
            adapters.add(_key(requirement))
            assert str(requirement.specifier) in pinned.get(_key(requirement), ()), (
                f"{engine.name}: {spec} is not in requirements-eval.txt"
            )
    # nothing in the file that no adapter asks for
    assert set(pinned) <= adapters, set(pinned) - adapters


@pytest.mark.parametrize("environment", sorted(ENVIRONMENTS))
def test_one_version_of_each_package_per_platform(environment):
    installed, _ = _pins()
    seen = {}
    for requirement in installed:
        if requirement.marker and not requirement.marker.evaluate(
            ENVIRONMENTS[environment]
        ):
            continue
        name = canonicalize_name(requirement.name)
        version = str(requirement.specifier)
        assert seen.setdefault(name, version) == version, (environment, name)
    # PP-OCR and OnnxTR need onnxruntime on every platform
    assert "onnxruntime" in seen
