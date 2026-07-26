"""Make the tool's stdlib-only modules importable from the tests.

The tool is a set of standalone scripts (not an installed package), so put its
directory on sys.path rather than requiring an install step.
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
