"""Prove that each product folder holds only the code that its device needs."""
import ast
from pathlib import Path

import pytest

pytestmark = pytest.mark.critical

ROOT = Path(__file__).resolve().parents[3]
# Each package can import only the products in its set.
ALLOWED = {
    "shared/ticker/shared": {"ticker.shared"},
    "shared/ticker/panel": {"ticker.shared", "ticker.panel"},
    "server/ticker": {"ticker.shared", "ticker.panel", "ticker.server", "ticker.ops"},
    "six/ticker/six": {"ticker.shared", "ticker.panel", "ticker.six"},
}
# The panel draws frames. Device services and transports stay in the Six.
DEVICE = {"flask", "rgbmatrix", "dbus_next", "bleak", "subprocess", "websockets"}
NETWORK = {"requests", "socket", "urllib", "http"}
# The asset store downloads the images that the cards draw. Ticker Server and Ticker Six both need it.
DOWNLOADER = "shared/ticker/panel/assets/storage.py"


def _imports(path: Path) -> set[str]:
    names = set()
    for node in ast.walk(ast.parse(path.read_text(encoding="utf-8"))):
        if isinstance(node, ast.Import):
            names.update(alias.name for alias in node.names)
        elif isinstance(node, ast.ImportFrom) and not node.level and node.module:
            names.add(node.module)
    return names


def _product(name: str) -> str | None:
    parts = name.split(".")
    return ".".join(parts[:2]) if parts[0] == "ticker" and len(parts) > 1 else None


@pytest.mark.parametrize("package", sorted(ALLOWED))
def test_each_package_imports_only_its_allowed_products(package):
    wrong = sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in (ROOT / package).rglob("*.py")
        for name in _imports(path)
        if _product(name) and _product(name) not in ALLOWED[package]
    )
    assert not wrong


def test_the_panel_has_no_device_or_network_code():
    wrong = sorted(
        f"{path.relative_to(ROOT)}: {name}"
        for path in (ROOT / "shared/ticker/panel").rglob("*.py")
        for name in _imports(path)
        if name.split(".")[0] in DEVICE
        or (name.split(".")[0] in NETWORK and path.relative_to(ROOT).as_posix() != DOWNLOADER)
    )
    assert not wrong
