"""Give every test subprocess the import roots of the test process."""
import os
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
os.environ["PYTHONPATH"] = os.pathsep.join(str(ROOT / name) for name in ("shared", "server", "six", "."))
