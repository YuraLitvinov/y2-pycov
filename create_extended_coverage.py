"""Create extended coverage data with per-test contexts for the parent project.

This script runs the parent project's test suite under coverage with dynamic_context
enabled (per-test context tracking). The generated .coverage data file is isolated
to y2-pycov/ and consumed by coverage_report.py to emit per-test attribution reports.

The coverage configuration includes dynamic_context = test_function, which is REQUIRED
to populate per-test contexts. Without it, contexts remain empty.

Usage:
    python y2-pycov/create_extended_coverage.py

This runs:
  1. Generates/uses a coverage config with dynamic_context = test_function
  2. Runs pytest on tests/ and knowledge_tool/knowledge_tool/tests/ with coverage
  3. Writes .coverage data file to y2-pycov/.coverage (isolated, not /workspace/.coverage)
  4. Runs coverage_report.py on the generated data file to emit the report
"""

from __future__ import annotations

import os
import subprocess
import sys
import tempfile
from pathlib import Path


def get_script_dir() -> Path:
    """Get the absolute path to the y2-pycov/ directory (where this script lives)."""
    return Path(os.path.dirname(os.path.abspath(__file__)))


def get_project_root() -> Path:
    """Get the absolute path to the parent project root."""
    return get_script_dir().parent


def create_coverage_config(config_dir: Path) -> Path:
    """Create a coverage config file with dynamic_context = test_function.

    The dynamic_context setting is REQUIRED to enable per-test context tracking.
    Returns the path to the created config file.
    """
    config_path = config_dir / ".coveragerc"
    config_content = """\
[run]
dynamic_context = test_function

[report]
precision = 2
"""
    config_path.write_text(config_content)
    return config_path


def run_coverage_and_tests(
    project_root: Path,
    script_dir: Path,
    coverage_config: Path,
) -> bool:
    """Run pytest under coverage with the given config.

    Returns True if successful, False otherwise.
    """
    # Path to isolated .coverage data file (inside y2-pycov/)
    data_file = script_dir / ".coverage"

    # Run coverage over both test roots: tests/ and knowledge_tool/knowledge_tool/tests/
    cmd = [
        sys.executable,
        "-m",
        "coverage",
        "run",
        f"--rcfile={coverage_config}",
        f"--data-file={data_file}",
        "--source=knowledge_tool",
        "-m",
        "pytest",
        "tests/",
        "knowledge_tool/knowledge_tool/tests/",
    ]

    # Change to project root for pytest to find tests
    print(f"Running coverage and pytest from {project_root}...")
    print(f"Command: {' '.join(cmd)}")
    print(f"Coverage data file: {data_file}")
    print()

    result = subprocess.run(cmd, cwd=project_root)
    return result.returncode == 0


def run_coverage_report(script_dir: Path) -> bool:
    """Run coverage_report.py to emit the per-test attribution report.

    Returns True if successful, False otherwise.
    """
    data_file = script_dir / ".coverage"

    # Run coverage_report.py with --compact to show the report
    cmd = [
        sys.executable,
        str(script_dir / "coverage_report.py"),
        f"--data-file={data_file}",
        "--compact",
    ]

    print()
    print("Running coverage report...")
    print(f"Command: {' '.join(cmd)}")
    print()

    result = subprocess.run(cmd)
    return result.returncode == 0


def main() -> int:
    """Main entry point."""
    project_root = get_project_root()
    script_dir = get_script_dir()

    # Create coverage config in a temp directory to avoid polluting the project
    with tempfile.TemporaryDirectory() as tmpdir:
        tmpdir_path = Path(tmpdir)
        coverage_config = create_coverage_config(tmpdir_path)

        # Run coverage and pytest
        if not run_coverage_and_tests(project_root, script_dir, coverage_config):
            print("Error: pytest failed", file=sys.stderr)
            return 1

    # Run coverage report
    if not run_coverage_report(script_dir):
        print("Error: coverage report failed", file=sys.stderr)
        return 1

    print()
    print(f"✓ Coverage data written to {script_dir / '.coverage'}")
    print(f"✓ Report generated successfully")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
