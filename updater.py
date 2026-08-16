#!/usr/bin/env python3
"""Install one immutable Pi release and atomically restart the controller."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path
import time
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parent
RELEASE_ROOT = Path(os.environ.get("TICKER_RELEASE_ROOT", "/opt/sports-ticker"))
RELEASES_DIR = RELEASE_ROOT / "releases"
CURRENT_LINK = Path(os.environ.get("TICKER_RELEASE_LINK", RELEASE_ROOT / "current"))
SERVICE_NAME = "ticker-controller"
SERVICE_PATH = Path("/etc/systemd/system/ticker-controller.service")


def _repository_owner() -> Any:
    """Return the user that owns the source repository."""

    import pwd

    return pwd.getpwuid(PROJECT_DIR.stat().st_uid)


def _git(*args: str, capture: bool = True) -> subprocess.CompletedProcess[str]:
    """Run Git as the repository owner without changing the source checkout."""

    command = ["git", "-C", str(PROJECT_DIR), *args]
    if os.geteuid() == 0:
        owner = _repository_owner().pw_name
        command = ["sudo", "-u", owner, *command]
    return subprocess.run(command, check=True, capture_output=capture, text=True)


def _prepare_release_directory() -> None:
    """Create a release directory writable by the repository owner."""

    RELEASES_DIR.mkdir(parents=True, exist_ok=True)
    if os.geteuid() == 0:
        owner = _repository_owner()
        os.chown(RELEASE_ROOT, owner.pw_uid, owner.pw_gid)
        os.chown(RELEASES_DIR, owner.pw_uid, owner.pw_gid)


def _revision() -> str:
    """Fetch the selected branch and return its immutable Git revision."""

    _git("fetch", "--quiet", "origin", "main")
    return _git("rev-parse", "origin/main").stdout.strip()


def _changed_files(target: str) -> tuple[str, ...]:
    """Return files changed between this running release and the target release."""

    result = _git("diff", "--name-only", "HEAD", target)
    return tuple(line.strip() for line in result.stdout.splitlines() if line.strip())


def _checkout_release(revision: str) -> Path:
    """Create one detached worktree for the selected immutable revision."""

    _prepare_release_directory()
    release = RELEASES_DIR / revision
    if release.is_dir():
        return release
    _git("worktree", "add", "--detach", str(release), revision, capture=False)
    return release


def _validate_release(release: Path) -> None:
    """Compile the release packages before activation so syntax errors never become active code."""
    packages = [path for path in (release / "ticker_core", release / "sports_ticker") if path.is_dir()]
    if not packages:
        raise FileNotFoundError(f"Release contains no runtime packages: {release}")
    subprocess.run([sys.executable, "-m", "compileall", "-q", *(str(path) for path in packages)], check=True)


def _current_release() -> Path | None:
    """Return the release currently selected by the atomic symlink."""
    try:
        return CURRENT_LINK.resolve(strict=True)
    except OSError:
        return None


def _service_is_healthy(timeout_seconds: float = 30.0) -> bool:
    """Wait for systemd to report the controller active after one release restart."""
    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        result = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE_NAME], check=False)
        if result.returncode == 0:
            return True
        time.sleep(1)
    return False


def _install_requirements(release: Path, changed: tuple[str, ...]) -> None:
    """Install dependencies only when the selected release changes them."""

    if not any(path in {"requirements.txt", "pyproject.toml", "poetry.lock"} for path in changed):
        return
    requirements = release / "requirements.txt"
    if not requirements.is_file():
        return
    command = [sys.executable, "-m", "pip", "install", "-r", str(requirements), "--quiet"]
    try:
        subprocess.run([*command, "--break-system-packages"], check=True)
    except subprocess.CalledProcessError:
        subprocess.run(command, check=True)


def _activate_release(release: Path) -> None:
    """Atomically make one complete release the next controller working directory."""

    CURRENT_LINK.parent.mkdir(parents=True, exist_ok=True)
    temporary = CURRENT_LINK.with_name(f".{CURRENT_LINK.name}.{release.name}.next")
    temporary.unlink(missing_ok=True)
    temporary.symlink_to(release, target_is_directory=True)
    os.replace(temporary, CURRENT_LINK)


def _install_service(release: Path) -> None:
    """Install the release-aware unit before restarting the controller."""

    source = release / "ticker-controller.service"
    if not source.is_file():
        raise FileNotFoundError(f"Release service file is missing: {source}")
    shutil.copy2(source, SERVICE_PATH)
    subprocess.run(["systemctl", "daemon-reload"], check=True)


def _cleanup_releases(active: Path) -> None:
    """Keep the active release and two rollback releases."""

    releases = sorted(
        (path for path in RELEASES_DIR.iterdir() if path.is_dir() and path != active),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    for release in releases[2:]:
        try:
            _git("worktree", "remove", "--force", str(release), capture=False)
        except subprocess.CalledProcessError:
            continue


def main() -> int:
    """Install one clean Git worktree and restart the controller."""

    try:
        target = _revision()
        changed = _changed_files(target)
        previous = _current_release()
        release = _checkout_release(target)
        _validate_release(release)
        _install_requirements(release, changed)
        _activate_release(release)
        _install_service(release)
        _cleanup_releases(release)
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
        if not _service_is_healthy():
            if previous is not None and previous != release:
                _activate_release(previous)
                _install_service(previous)
                subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
            raise RuntimeError(f"Release {target[:12]} failed its startup health check")
        print(f"[updater] Activated {target[:12]}.")
        return 0
    except Exception as error:
        print(f"[updater] Update failed: {error}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
