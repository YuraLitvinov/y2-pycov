"""Run a host project's tests under coverage with per-test contexts.

Host-agnostic: test roots come from CLI args; coverage scope from an external
config (--rcfile, default <project root>/.coveragerc). Writes an isolated
.coverage and emits the per-test report via coverage_report.py.

    python y2-pycov/create_extended_coverage.py [test_roots...] \
        [--rcfile PATH] [--data-file PATH]
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from pathlib import Path


def get_script_dir() -> Path:
    """Absolute path to the y2-pycov/ directory (where this script lives)."""
    return Path(os.path.dirname(os.path.abspath(__file__)))


def get_project_root() -> Path:
    """Absolute path to the host project root."""
    return get_script_dir().parent


def resolve_coverage_config(project_root: Path) -> Path:
    """Locate the external <project root>/.coveragerc (coverage scope lives there)."""
    config_path = project_root / ".coveragerc"
    if not config_path.exists():
        raise FileNotFoundError(
            f"Coverage config not found at {config_path}; create it or pass --rcfile."
        )
    return config_path


def run_coverage_and_tests(
    project_root: Path,
    data_file: Path,
    coverage_config: Path,
    test_paths: list[str],
) -> bool:
    """Run pytest under coverage over ``test_paths`` (empty = host pytest config decides)."""
    # No --source override: source scope comes from the --rcfile config.
    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--rcfile={coverage_config}",
        f"--data-file={data_file}",
        "-m",
        "pytest",
        *test_paths,
    ]

    print(f"Running: {' '.join(cmd)} (cwd={project_root})")
    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode == 0


def run_coverage_report(script_dir: Path, data_file: Path) -> bool:
    """Emit the per-test attribution report via coverage_report.py."""
    cmd = [
        sys.executable,
        str(script_dir / "coverage_report.py"),
        f"--data-file={data_file}",
        "--compact",
    ]
    print(f"Running: {' '.join(cmd)}")
    result = subprocess.run(cmd)
    return result.returncode == 0


def _parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(prog="create_extended_coverage")
    parser.add_argument("test_paths", nargs="*", default=[],
                        help="Test roots to run (default: host pytest config decides).")
    parser.add_argument("--rcfile", default=None,
                        help="Coverage config (default: <project root>/.coveragerc).")
    parser.add_argument("--data-file", default=None,
                        help="Coverage data file to write (default: y2-pycov/.coverage).")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = _parse_args(argv)
    project_root = get_project_root()
    script_dir = get_script_dir()

    coverage_config = (
        Path(args.rcfile).resolve() if args.rcfile else resolve_coverage_config(project_root)
    )
    if not coverage_config.exists():
        raise FileNotFoundError(f"Coverage config not found at {coverage_config}.")

    data_file = Path(args.data_file).resolve() if args.data_file else (script_dir / ".coverage")

    if not run_coverage_and_tests(project_root, data_file, coverage_config, args.test_paths):
        print("Error: pytest failed", file=sys.stderr)
        return 1
    if not run_coverage_report(script_dir, data_file):
        print("Error: coverage report failed", file=sys.stderr)
        return 1

    print(f"✓ Coverage data written to {data_file}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
