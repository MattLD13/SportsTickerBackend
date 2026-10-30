"""Install one immutable Six release and atomically restart the controller.

Run it from the release folder: `PYTHONPATH=shared:six python3 -m ticker.six.updater`.
"""

from __future__ import annotations

import os
import argparse
import re
import json
import shutil
import subprocess
import sys
from pathlib import Path
import time
from typing import Any


PROJECT_DIR = Path(__file__).resolve().parents[3]
RELEASE_ROOT = Path(os.environ.get("TICKER_RELEASE_ROOT", "/opt/sports-ticker"))
RELEASES_DIR = RELEASE_ROOT / "releases"
CURRENT_LINK = Path(os.environ.get("TICKER_RELEASE_LINK", RELEASE_ROOT / "current"))
FRAME_HEALTH_PATH = Path(os.environ.get("TICKER_FRAME_HEALTH_PATH", "/run/sports-ticker/frame-health.json"))
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


def _revision(version: str) -> str:
    """Fetch the selected branch and return its immutable Git revision."""

    if not re.fullmatch(r"[0-9a-f]{40}", version):
        raise ValueError("Ticker Six updates require an immutable commit id")
    _git("fetch", "--quiet", "origin", "main")
    _git("merge-base", "--is-ancestor", version, "origin/main")
    return version


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
    names = ("six/ticker/six", "shared/ticker/shared", "shared/ticker/panel")
    packages = [release / name for name in names if (release / name).is_dir()]
    if not packages:
        raise FileNotFoundError(f"Release contains no runtime packages: {release}")
    subprocess.run([sys.executable, "-m", "compileall", "-q", *(str(path) for path in packages)], check=True)


def _current_release() -> Path | None:
    """Return the release currently selected by the atomic symlink."""
    try:
        return CURRENT_LINK.resolve(strict=True)
    except OSError:
        return None


def _service_is_healthy(release: Path, *, not_before: float, timeout_seconds: float = 90.0) -> bool:
    """Require an active service and a frame receipt from its current process and release."""
    from ticker.six.platform.frame_health import receipt_matches

    deadline = time.monotonic() + timeout_seconds
    while time.monotonic() < deadline:
        active = subprocess.run(["systemctl", "is-active", "--quiet", SERVICE_NAME], check=False)
        if active.returncode == 0:
            try:
                process = subprocess.check_output(["systemctl", "show", "--property=MainPID", "--value", SERVICE_NAME],
                                                  text=True, timeout=5)
                receipt = json.loads(FRAME_HEALTH_PATH.read_text(encoding="utf-8"))
                if receipt_matches(receipt, release, int(process.strip()), not_before):
                    return True
            except (OSError, ValueError, subprocess.SubprocessError):
                pass
        time.sleep(1)
    return False


def _install_requirements(release: Path, changed: tuple[str, ...]) -> None:
    """Install dependencies only when the selected release changes them."""

    if not any(path in {"requirements/base.txt", "pyproject.toml", "poetry.lock"} for path in changed):
        return
    requirements = release / "requirements/base.txt"
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

    source = release / "six/deploy/ticker-controller.service"
    if not source.is_file():
        raise FileNotFoundError(f"Release service file is missing: {source}")
    shutil.copy2(source, SERVICE_PATH)
    subprocess.run(["systemctl", "daemon-reload"], check=True)


def _cleanup_releases(active: Path, previous: Path | None = None) -> None:
    """Keep the active release and two rollback releases."""

    releases = sorted(
        (path for path in RELEASES_DIR.iterdir() if path.is_dir() and path != active),
        key=lambda path: path.stat().st_mtime,
        reverse=True,
    )
    retained = {previous} if previous in releases else set()
    for path in releases:
        if len(retained) >= 2:
            break
        retained.add(path)
    for release in releases:
        if release in retained:
            continue
        try:
            _git("worktree", "remove", "--force", str(release), capture=False)
        except subprocess.CalledProcessError:
            continue


def _install_checked_release(release: Path, previous: Path | None, *, timeout_seconds: float = 90.0) -> None:
    """Restore the prior immutable release if startup produces no valid display receipt."""
    _activate_release(release)
    try:
        _install_service(release)
        restart_started = time.time()
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
        if not _service_is_healthy(release, not_before=restart_started, timeout_seconds=timeout_seconds):
            raise RuntimeError(f"Release {release.name[:12]} failed its display health check")
    except Exception:
        if previous is not None and previous != release:
            _activate_release(previous)
            _install_service(previous)
            subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
        raise


def _install_boot_guard() -> None:
    """Keep the last working updater available after a power interruption."""
    unit = "\n".join((
        "[Unit]", "Description=Ticker Six update recovery", "After=network-online.target ticker-controller.service",
        "[Service]", "Type=oneshot", "Environment=TICKER_DATA_DIR=" + os.environ.get("TICKER_DATA_DIR", "/home/mld/ticker"),
        "Environment=TICKER_RELEASE_ROOT=" + str(RELEASE_ROOT), "Environment=TICKER_RELEASE_LINK=" + str(CURRENT_LINK),
        "WorkingDirectory=" + str(PROJECT_DIR), "Environment=PYTHONPATH=shared:six",
        "ExecStart=/usr/bin/python3 -m ticker.six.updater --recover", "TimeoutStartSec=180",
        "[Install]", "WantedBy=multi-user.target", "",
    ))
    Path("/etc/systemd/system/ticker-update-guard.service").write_text(unit, encoding="utf-8")
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    subprocess.run(["systemctl", "enable", "ticker-update-guard.service"], check=True)


def _recover_pending_boot(journal, client, ticker_id: str) -> int:
    receipt = journal.load()
    if receipt is None:
        return 0
    if receipt.get("phase") != "activating":
        if receipt.get("status") == "started":
            receipt.update(status="download_failed", reason="manifest", phase="finished")
            journal.save(receipt)
        journal.flush(client, ticker_id)
        return 0
    previous = Path(receipt["previous_release"]).resolve(strict=True)
    release = Path(receipt["target_release"]).resolve(strict=True)
    root = RELEASES_DIR.resolve(strict=True)
    if previous.parent != root or release.parent != root or previous == release:
        raise ValueError("Update recovery paths do not identify two managed releases")
    boot_time = time.time() - float(Path("/proc/uptime").read_text(encoding="ascii").split()[0])
    if _current_release() == release and _service_is_healthy(release, not_before=boot_time):
        receipt.update(status="installed", running_version=receipt["version"], reason="", phase="finished")
    else:
        _activate_release(previous)
        _install_service(previous)
        subprocess.run(["systemctl", "restart", SERVICE_NAME], check=True)
        receipt.update(status="rolled_back", running_version=previous.name, reason="boot_reset", phase="finished")
    journal.save(receipt)
    journal.flush(client, ticker_id)
    return 0


def main() -> int:
    """Install one assigned release and persist its verified boot result."""
    from ticker.six.platform.update_journal import UpdateJournal
    from ticker.six.platform.device_credentials import load_device_token
    from ticker.six.protocol import BackendClient
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--recover", action="store_true")
    parser.add_argument("--version")
    parser.add_argument("--command-id")
    parser.add_argument("--ticker-id")
    args = parser.parse_args()
    data = Path(os.environ.get("TICKER_DATA_DIR", "/home/mld/ticker"))
    journal = UpdateJournal(data)
    client = BackendClient(os.environ.get("TICKER_BACKEND_URL", "https://ticker.mattdicks.org"),
                           device_token=load_device_token(Path(os.environ.get("TICKER_DEVICE_TOKEN_FILE", data / "device_token"))))
    if args.recover:
        from ticker.six.composition import load_device_id
        try:
            return _recover_pending_boot(journal, client, load_device_id(data))
        finally:
            client.close()
    if not all((args.version, args.command_id, args.ticker_id)):
        parser.error("Update requires --version, --command-id, and --ticker-id")
    previous = _current_release()
    if previous is None:
        raise RuntimeError("The last known good release is missing")
    receipt = {"id": args.command_id, "version": args.version, "status": "started", "running_version": previous.name,
               "reason": "", "previous_release": str(previous), "target_release": "", "phase": "preparing"}
    journal.save(receipt)
    activated = False
    try:
        result = journal.flush(client, args.ticker_id)
        if result is not None and result.get("quarantined"):
            raise RuntimeError("The server quarantined this release")
        target = _revision(args.version)
        changed = _changed_files(target)
        release = _checkout_release(target)
        _validate_release(release)
        _install_requirements(release, changed)
        _install_boot_guard()
        confirmed = client.report_update(args.ticker_id, {key: receipt[key] for key in ("id", "version", "status", "running_version", "reason")})
        if not confirmed.get("accepted") or confirmed.get("quarantined"):
            raise RuntimeError("The server stopped this update before activation")
        receipt.update(target_release=str(release), phase="activating")
        journal.save(receipt)
        activated = True
        _install_checked_release(release, previous)
        receipt.update(status="installed", running_version=args.version, phase="finished")
        journal.save(receipt)
        _cleanup_releases(release, previous)
        print(f"[updater] Activated {target[:12]} after a successful display frame.")
        return 0
    except Exception as error:
        restored = activated and _current_release() == previous
        receipt.update(status="rolled_back" if restored else "download_failed",
                       reason="render_validation" if restored else "manifest", phase="finished")
        journal.save(receipt)
        print(f"[updater] Update failed: {error}", file=sys.stderr)
        return 1
    finally:
        try:
            journal.flush(client, args.ticker_id)
        except Exception:
            print("[updater] Saved the update result for a later server report.", file=sys.stderr)
        client.close()


if __name__ == "__main__":
    raise SystemExit(main())
