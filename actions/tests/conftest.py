"""Load the standalone action scripts for testing.

The scripts are hyphenated, non-package files (e.g. ``specs-diff.py``) run
directly by the composite actions, so they can't be imported by name. Each
fixture loads one by path via importlib and hands back the module object.
"""

import importlib.util
from pathlib import Path

import pytest

ACTIONS_DIR = Path(__file__).resolve().parent.parent


def _load(rel_path: str, mod_name: str):
    path = ACTIONS_DIR / rel_path
    spec = importlib.util.spec_from_file_location(mod_name, path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


@pytest.fixture
def specs_diff():
    return _load("specs-delta/specs-diff.py", "specs_diff")


@pytest.fixture
def sorry_diff():
    return _load("sorry-delta/sorry-diff.py", "sorry_diff")


@pytest.fixture
def probe_to_manifest():
    return _load("sorry-audit-probe/probe-to-manifest.py", "probe_to_manifest")
