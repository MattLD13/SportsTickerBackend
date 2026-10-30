"""Enroll physical-device credential hashes without transferring secrets through GitHub."""
from __future__ import annotations
import argparse
import hashlib
import json
import os
from pathlib import Path
import re
import shlex
import subprocess
import sys
import time
import serial

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from ticker.six.platform.device_credentials import load_device_token


def mini_digest(port: str, identity: str) -> str:
    directory = Path(os.environ.get("LOCALAPPDATA", Path.home())) / "SportsTicker/device-credentials"
    filename = hashlib.sha256(identity.encode()).hexdigest() + ".token"
    token = load_device_token(directory / filename)
    with serial.Serial(port, 115200, timeout=0.1, write_timeout=2) as connection:
        deadline = time.monotonic() + 60
        incoming = bytearray()
        validated = False
        while time.monotonic() < deadline and not validated:
            connection.write(b"STATS\n")
            sample_until = time.monotonic() + .5
            while time.monotonic() < sample_until:
                incoming.extend(connection.read(min(4096, connection.in_waiting or 1)))
                while b"\n" in incoming:
                    raw, _, incoming = incoming.partition(b"\n")
                    marker = raw.find(b"MINI_STATS:")
                    if marker >= 0:
                        stats = json.loads(raw[marker + 11:])
                        validated = stats["display"]["update"]["boot_validated"]
        if not validated:
            raise RuntimeError("The Mini has not confirmed a healthy boot")
        connection.write(("AUTHSET:" + token + "\n").encode("ascii"))
        incoming = bytearray()
        deadline = time.monotonic() + 20
        while time.monotonic() < deadline:
            incoming.extend(connection.read(min(4096, connection.in_waiting or 1)))
            while b"\n" in incoming:
                raw, _, incoming = incoming.partition(b"\n")
                if b"MINI_AUTH:STORED" in raw:
                    return hashlib.sha256(token.encode()).hexdigest()
                if b"MINI_AUTH:REJECTED" in raw or b"MINI_AUTH:BUSY" in raw:
                    raise RuntimeError("The Mini rejected the credential operation")
    raise TimeoutError("The Mini did not confirm durable credential storage")


def pi_digest(host: str, identity: Path, token_path: str) -> str:
    script = "import hashlib;from pathlib import Path;print(hashlib.sha256(Path(" + repr(token_path) + ").read_text().strip().encode()).hexdigest())"
    command = "sudo python3 -c " + shlex.quote(script)
    result = subprocess.run(["ssh", "-i", str(identity), "-o", "IdentitiesOnly=yes", host, command],
                            check=True, text=True, capture_output=True)
    digest = result.stdout.strip()
    if not re.fullmatch(r"[0-9a-f]{64}", digest):
        raise RuntimeError("The Pi did not return a credential hash")
    return digest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--ticker-id", required=True)
    target = parser.add_mutually_exclusive_group(required=True)
    target.add_argument("--mini-port")
    target.add_argument("--pi-host")
    parser.add_argument("--identity", type=Path)
    parser.add_argument("--pi-token-path", default="/home/mld/ticker/device_token")
    args = parser.parse_args()
    if args.pi_host and not args.identity:
        parser.error("Pi enrollment requires an SSH identity path")
    digest = mini_digest(args.mini_port, args.ticker_id) if args.mini_port else pi_digest(args.pi_host, args.identity, args.pi_token_path)
    result = subprocess.run(["gh", "workflow", "run", "device-credentials.yml", "-f", "ticker_id=" + args.ticker_id,
                             "-f", "token_sha256=" + digest], check=True, text=True, capture_output=True)
    print(json.dumps({"ticker_id": args.ticker_id, "enrollment_run": result.stdout.strip()}))


if __name__ == "__main__":
    main()
