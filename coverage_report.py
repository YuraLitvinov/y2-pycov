"""Token-efficient, machine-readable per-module coverage report.

This module is the canonical home for the project's token-efficient coverage
report. It is built *on top of* the real analysis logic in this same package
(:mod:`coverage_tools`) rather than re-deriving coverage facts independently —
there is ONE coverage base, and that base is y2-pycov.

It reads a ``.coverage`` data file (produced by the ``coverage`` package) and
emits a structured, per-module JSON report that can be filtered to specific
modules. A consumer can load it, keep only the module(s) it cares about, and
ignore the rest — far cheaper than parsing an HTML coverage blob.

Importability note
------------------
This package lives in the hyphenated ``y2-pycov`` git submodule directory, which
is NOT importable as a normal Python package (``import y2-pycov`` is a syntax
error) and ``coverage_tools`` uses bare imports that assume it is the top-level
module. To reuse :mod:`coverage_tools` from outside the submodule WITHOUT any
``sys.path`` manipulation, callers load this file via
``importlib.util.spec_from_file_location`` (see ``pycov/report.py``). Internally
this module loads its sibling ``coverage_tools`` the same way, so it works both
when imported by file path and when run as a script from inside the submodule.

CLI usage::

    # Full machine-readable JSON report over the default .coverage file
    python y2-pycov/coverage_report.py

    # Filter to one or more modules (substring match on file path)
    python y2-pycov/coverage_report.py --module knowledge_tool --module tasks.py

    # Compact single-line JSON (most token-efficient)
    python y2-pycov/coverage_report.py --compact
"""

from __future__ import annotations

import argparse
import importlib.util
import json
import os
import sys
from collections import defaultdict
from dataclasses import dataclass, field, asdict
from typing import Dict, List, Optional


def _load_coverage_tools():
    """Load the sibling ``coverage_tools`` module by file path.

    ``coverage_tools`` lives next to this file inside the hyphenated
    ``y2-pycov`` submodule directory, so it cannot be imported by package name
    without ``sys.path`` manipulation. ``spec_from_file_location`` loads the file
    directly and does NOT mutate ``sys.path`` — the clean mechanism mandated by
    the consolidation design (acceptance #4, option "b").
    """
    here = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(here, "coverage_tools.py")
    mod_name = "y2_pycov_coverage_tools"
    spec = importlib.util.spec_from_file_location(mod_name, module_path)
    if spec is None or spec.loader is None:  # pragma: no cover - defensive
        raise ImportError(f"Cannot load coverage_tools from {module_path!r}")
    module = importlib.util.module_from_spec(spec)
    # Register before exec so dataclass/typing machinery can resolve the module
    # by name (importlib-by-path requirement). This does NOT touch sys.path.
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


# y2-pycov's real coverage analysis engine — the single base this report builds on.
coverage_tools = _load_coverage_tools()


@dataclass
class ModuleCoverage:
    """Coverage facts for a single measured source file (a "module")."""

    file: str
    covered_lines: int
    # line number -> sorted list of test context names that hit it.
    # Contexts make the report filterable down to "which test covered this line".
    tests_by_line: Dict[int, List[str]] = field(default_factory=dict)


@dataclass
class CoverageReport:
    """Machine-readable coverage report, grouped by module.

    The shape is intentionally flat and JSON-friendly so a consumer can load it,
    filter to the module(s) it cares about, and ignore the rest — avoiding the
    cost of parsing an HTML coverage blob.
    """

    data_file: str
    base_dir: str
    total_modules: int
    total_covered_lines: int
    modules: List[ModuleCoverage] = field(default_factory=list)

    def to_dict(self) -> dict:
        """Return the report as a plain, JSON-serialisable dict."""
        return asdict(self)

    def to_json(self, indent: Optional[int] = 2) -> str:
        """Serialise the report to JSON (``indent=None`` for compact output)."""
        return json.dumps(self.to_dict(), indent=indent, sort_keys=True)


def _matches(path: str, module_filters: Optional[List[str]]) -> bool:
    if not module_filters:
        return True
    return any(flt in path for flt in module_filters)


def build_report(
    data_file: str = ".coverage",
    base_dir: Optional[str] = None,
    module_filters: Optional[List[str]] = None,
) -> CoverageReport:
    """Build a :class:`CoverageReport` from a coverage data file.

    The per-line test contexts come from y2-pycov's own
    :func:`coverage_tools.extended_cov_lines_raw_structure`, so this report
    consumes the submodule's real analysis logic rather than re-deriving it.

    Args:
        data_file: path to the ``.coverage`` data file.
        base_dir: directory that file paths are reported relative to. Defaults to
            the current working directory.
        module_filters: optional list of substrings; only files whose path
            contains one of them are included. ``None``/empty includes all.
    """
    base = base_dir or os.getcwd()

    # Reuse y2-pycov's matrix loader to enumerate measured files via its own API.
    data = coverage_tools.CoverageData(basename=data_file)
    data.read()

    modules: List[ModuleCoverage] = []
    total_covered = 0

    for filename in sorted(data.measured_files()):
        rel = os.path.relpath(filename, base)
        if not _matches(rel, module_filters) and not _matches(filename, module_filters):
            continue

        # Delegate the raw per-line context extraction to y2-pycov's engine.
        contexts_by_lineno = coverage_tools.extended_cov_lines_raw_structure(
            filename, base, data_file=data_file
        )

        tests_by_line: Dict[int, List[str]] = defaultdict(list)
        for lineno, contexts in contexts_by_lineno.items():
            # Keep only real test contexts; drop the empty "no context" marker.
            test_ctxs = sorted({ctx for ctx in contexts if ctx})
            if test_ctxs:
                tests_by_line[int(lineno)] = test_ctxs

        covered = len(contexts_by_lineno)
        total_covered += covered
        modules.append(
            ModuleCoverage(
                file=rel,
                covered_lines=covered,
                tests_by_line=dict(sorted(tests_by_line.items())),
            )
        )

    return CoverageReport(
        data_file=data_file,
        base_dir=base,
        total_modules=len(modules),
        total_covered_lines=total_covered,
        modules=modules,
    )


def _parse_args(argv: Optional[List[str]] = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        prog="coverage_report",
        description="Emit a token-efficient, per-module JSON coverage report.",
    )
    parser.add_argument(
        "--data-file",
        default=".coverage",
        help="Path to the coverage data file (default: .coverage).",
    )
    parser.add_argument(
        "--base-dir",
        default=None,
        help="Base directory for relative file paths (default: cwd).",
    )
    parser.add_argument(
        "--module",
        dest="modules",
        action="append",
        default=None,
        help="Filter to files whose path contains this substring. Repeatable.",
    )
    parser.add_argument(
        "--compact",
        action="store_true",
        help="Emit compact single-line JSON (most token-efficient).",
    )
    return parser.parse_args(argv)


def main(argv: Optional[List[str]] = None) -> int:
    """CLI entrypoint: print a per-module JSON coverage report to stdout."""
    args = _parse_args(argv)
    report = build_report(
        data_file=args.data_file,
        base_dir=args.base_dir,
        module_filters=args.modules,
    )
    print(report.to_json(indent=None if args.compact else 2))
    return 0


if __name__ == "__main__":  # pragma: no cover
    raise SystemExit(main())
