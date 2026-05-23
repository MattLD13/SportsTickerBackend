#!/usr/bin/env python3
"""SportsTicker Test Runner & Repository Cleaner.

A clean developer CLI utility to run unit/integration tests and
recursively purge compiled Python files, caches, preview frames,
and logs to restore the workspace to a pristine state.

Usage:
  python tools/test_runner.py --run
  python tools/test_runner.py --clean
  python tools/test_runner.py --clean --dry-run
"""

import argparse
import glob
import os
import shutil
import subprocess
import sys
import time

CLEAN_GLOBS = [
    # Compiled byte code
    "**/__pycache__",
    "**/*.pyc",
    "**/*.pyo",
    "**/*.pyd",
    ".pytest_cache",
    ".coverage",
    "htmlcov",
    
    # Generated development cache files
    "game_cache.json",
    "stock_cache.json",
    "airport_name_cache.json",
    "airline_code_cache.json",
    "ticker.log",
    
    # Previews and rendering files
    "previews/temp/*",
    "previews/*/*.png",
    "live_render.png",
    "*.png",
]


def run_tests(coverage=False):
    """Execute the pytest suite using the project's virtual environment."""
    print("[START] Starting SportsTicker Testing Suite...")
    
    venv_pytest = os.path.join(".venv", "Scripts", "pytest.exe")
    if not os.path.exists(venv_pytest):
        venv_pytest = os.path.join(".venv", "Scripts", "pytest")
        if not os.path.exists(venv_pytest):
            venv_pytest = "pytest"
        
    cmd = [venv_pytest]
    if coverage:
        cmd.extend(["--cov=sports_ticker", "tests/"])
    else:
        cmd.extend(["tests/"])
        
    print(f"Executing: {' '.join(cmd)}")
    start = time.time()
    try:
        res = subprocess.run(cmd, check=False)
        duration = time.time() - start
        print("\n" + "=" * 50)
        if res.returncode == 0:
            print(f"[SUCCESS] All tests passed in {duration:.2f}s!")
        else:
            print(f"[FAILURE] Tests failed with exit code {res.returncode} in {duration:.2f}s!")
        return res.returncode
    except FileNotFoundError:
        print("[ERROR] pytest is not installed. Run 'pip install pytest' in your virtual environment.")
        return 1


def clean_repository(dry_run=False):
    """Recursively clean compiled python bytecode and generated cache/preview artifacts."""
    print("[CLEAN] Cleaning up developer debris and test artifacts...")
    if dry_run:
        print("[WARNING] DRY RUN MODE: No files will be deleted.\n")
        
    removed_bytes = 0
    removed_count = 0
    
    # 1. Standard globs cleaning
    root_dir = os.path.abspath(os.path.join(os.path.dirname(__file__), ".."))
    
    for pattern in CLEAN_GLOBS:
        full_pattern = os.path.join(root_dir, pattern)
        for filepath in glob.glob(full_pattern, recursive=True):
            # Avoid cleaning folders in virtual environment (.venv)
            if ".venv" in filepath or ".git" in filepath:
                continue
                
            is_dir = os.path.isdir(filepath)
            
            # Skip parent previews folders, only empty their children
            if filepath.endswith("previews") or filepath.endswith("previews/"):
                continue
                
            try:
                size = 0
                if not is_dir:
                    size = os.path.getsize(filepath)
                    if not dry_run:
                        os.remove(filepath)
                else:
                    # Sum folder size
                    for root, _, files in os.walk(filepath):
                        for f in files:
                            fp = os.path.join(root, f)
                            if os.path.exists(fp):
                                size += os.path.getsize(fp)
                    if not dry_run:
                        shutil.rmtree(filepath)
                        
                removed_bytes += size
                removed_count += 1
                action = "Would delete" if dry_run else "Deleted"
                item_type = "folder" if is_dir else "file"
                size_str = f" ({size} bytes)" if size > 0 else ""
                print(f"  [{action}] {item_type}: {os.path.relpath(filepath, root_dir)}{size_str}")
            except Exception as e:
                print(f"  [ERROR] Failed to clean {filepath}: {e}")

    # 2. Cleanup orphaned temp testing folders
    import tempfile
    temp_dir = tempfile.gettempdir()
    for folder in os.listdir(temp_dir):
        if folder.startswith("sportsticker_test_"):
            full_path = os.path.join(temp_dir, folder)
            try:
                if not dry_run:
                    shutil.rmtree(full_path)
                action = "Would delete" if dry_run else "Deleted"
                print(f"  [{action}] temp testing workspace: {folder}")
                removed_count += 1
            except Exception:
                pass

    print("\n" + "=" * 50)
    status = "Would clean" if dry_run else "Cleaned"
    mb_cleaned = removed_bytes / (1024 * 1024)
    print(f"[FINISHED] Cleanup Completed: {status} {removed_count} items ({mb_cleaned:.3f} MB freed).")


def main():
    parser = argparse.ArgumentParser(description="SportsTicker Developer CLI Helper.")
    group = parser.add_mutually_exclusive_group(required=True)
    group.add_argument("--run", action="store_true", help="Execute the pytest test suite.")
    group.add_argument("--clean", action="store_true", help="Recursively clean caches, previews, and pycache.")
    
    parser.add_argument("--cov", action="store_true", help="Compute test code coverage (used with --run).")
    parser.add_argument("--dry-run", action="store_true", help="Show files to be deleted without cleaning (used with --clean).")
    
    args = parser.parse_args()
    
    if args.run:
        sys.exit(run_tests(coverage=args.cov))
    elif args.clean:
        clean_repository(dry_run=args.dry_run)
        
    return 0


if __name__ == "__main__":
    main()
