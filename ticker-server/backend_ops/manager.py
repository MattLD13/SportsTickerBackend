"""Keep the installed backend deployment and recovery command entry point stable."""
import argparse
import json
from pathlib import Path

from .deployment import manager as deployment


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("operation", choices=("deploy", "guard", "status"))
    parser.add_argument("--home", type=Path, default=Path("/home/ubuntu"))
    parser.add_argument("--staging", type=Path)
    args = parser.parse_args()
    manager = deployment.Manager(args.home)
    if args.operation == "status":
        print(json.dumps(deployment.read(manager.state_path), indent=2))
        return
    with manager.locked(wait=args.operation == "deploy") as acquired:
        if not acquired:
            return
        if args.operation == "deploy":
            manager.deploy(args.staging)
        elif manager.state_path.exists():
            state = deployment.read(manager.state_path)
            previous_rollback = state.get("last_rollback")
            manager.guard(state)
            if previous_rollback != state.get("last_rollback"):
                from .diagnostics import bundle
                bundle(manager.home, manager.control / "latest-report.zip")


if __name__ == "__main__":
    main()
