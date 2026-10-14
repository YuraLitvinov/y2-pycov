"""Tests for the consolidated coverage report — living where the report lives.

The token-efficient per-module JSON report is ``y2-pycov/coverage_report.py``,
built on y2-pycov's ``coverage_tools.py`` engine. These tests exercise it
directly (loaded by file path via ``importlib`` — the hyphenated ``y2-pycov``
directory is not importable by package name, and this loads the file WITHOUT any
``sys.path`` manipulation).

They synthesize a small ``.coverage`` data file (with test contexts) via the
public ``coverage`` API and assert the report is machine-readable, per-module and
filterable, and that it consumes y2-pycov's real ``coverage_tools`` logic. They
pull in no heavy dependency (no ``fastmcp``).

Run explicitly::

    python -m pytest y2-pycov/test_coverage_report.py
"""

import importlib.util
import inspect
import json
import os
import sys

from coverage import CoverageData


def _load_y2_pycov_module(filename, mod_name):
    here = os.path.dirname(os.path.abspath(__file__))
    module_path = os.path.join(here, filename)
    spec = importlib.util.spec_from_file_location(mod_name, module_path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[mod_name] = module
    spec.loader.exec_module(module)
    return module


_report_mod = _load_y2_pycov_module("coverage_report.py", "y2_pycov_coverage_report_test")
build_report = _report_mod.build_report
CoverageReport = _report_mod.CoverageReport


def _write_coverage_data(tmp_path):
    """Create a .coverage data file with arcs + contexts for two modules."""
    data_file = os.path.join(str(tmp_path), ".coverage")
    data = CoverageData(basename=data_file)

    mod_a = os.path.join(str(tmp_path), "pkg", "mod_a.py")
    mod_b = os.path.join(str(tmp_path), "pkg", "mod_b.py")

    # test_one covers lines in both modules; test_two covers only mod_a.
    data.set_context("test_one")
    data.add_lines({mod_a: [1, 2, 3], mod_b: [10]})
    data.set_context("test_two")
    data.add_lines({mod_a: [2, 3]})
    data.write()
    return data_file, mod_a, mod_b


def test_build_report_is_machine_readable_and_grouped_by_module(tmp_path):
    data_file, _mod_a, _mod_b = _write_coverage_data(tmp_path)

    report = build_report(data_file=data_file, base_dir=str(tmp_path))

    assert isinstance(report, CoverageReport)
    assert report.total_modules == 2
    files = {m.file for m in report.modules}
    assert files == {os.path.join("pkg", "mod_a.py"), os.path.join("pkg", "mod_b.py")}

    # Round-trips through JSON (token-efficient, not an HTML blob).
    payload = json.loads(report.to_json())
    assert payload["total_modules"] == 2
    assert isinstance(payload["modules"], list)


def test_report_carries_test_contexts_per_line(tmp_path):
    data_file, _mod_a, _mod_b = _write_coverage_data(tmp_path)

    report = build_report(data_file=data_file, base_dir=str(tmp_path))
    mod_a = next(m for m in report.modules if m.file.endswith("mod_a.py"))

    # Line 2 was hit by both tests; line 1 only by test_one.
    assert mod_a.tests_by_line[2] == ["test_one", "test_two"]
    assert mod_a.tests_by_line[1] == ["test_one"]


def test_module_filter_narrows_to_specific_module(tmp_path):
    data_file, _mod_a, _mod_b = _write_coverage_data(tmp_path)

    report = build_report(
        data_file=data_file,
        base_dir=str(tmp_path),
        module_filters=["mod_b"],
    )

    assert report.total_modules == 1
    assert report.modules[0].file.endswith("mod_b.py")


def test_compact_json_is_single_line(tmp_path):
    data_file, _mod_a, _mod_b = _write_coverage_data(tmp_path)

    report = build_report(data_file=data_file, base_dir=str(tmp_path))
    compact = report.to_json(indent=None)

    assert "\n" not in compact
    assert json.loads(compact)["total_modules"] == 2


def test_empty_coverage_yields_empty_report(tmp_path):
    data_file = os.path.join(str(tmp_path), ".coverage")
    CoverageData(basename=data_file).write()  # no data measured

    report = build_report(data_file=data_file, base_dir=str(tmp_path))
    assert report.total_modules == 0
    assert report.total_covered_lines == 0
    assert report.modules == []


# --- consolidation guarantee: the report consumes y2-pycov's real engine ---


def test_report_consumes_y2_pycov_coverage_tools():
    """The consolidated report is built on y2-pycov's coverage_tools engine."""
    tools = _report_mod.coverage_tools
    assert hasattr(tools, "extended_cov_lines_raw_structure")
    assert os.path.join("y2-pycov", "coverage_tools.py") in inspect.getfile(
        tools.extended_cov_lines_raw_structure
    )


def test_report_is_authored_in_y2_pycov():
    """build_report / CoverageReport are authored in the y2-pycov submodule file."""
    assert os.path.join("y2-pycov", "coverage_report.py") in inspect.getfile(build_report)
    assert os.path.join("y2-pycov", "coverage_report.py") in inspect.getfile(CoverageReport)


def _write_e2e_coverage_data(tmp_path):
    data_file = os.path.join(str(tmp_path), ".coverage-e2e")
    data = CoverageData(basename=data_file)
    mod_a = os.path.join(str(tmp_path), "pkg", "mod_a.py")
    mod_b = os.path.join(str(tmp_path), "pkg", "mod_b.py")

    data.set_context("e2e:probe_a")
    data.add_lines({mod_a: [1, 2], mod_b: [10]})
    data.set_context("e2e:probe_b")
    data.add_lines({mod_a: [2, 3]})
    data.set_context("e2e:probe_c")
    data.add_lines({mod_a: [4]})
    data.set_context("test_unit_context")
    data.add_lines({mod_a: [99]})
    data.write()
    return data_file


def test_e2e_overlap_report_counts_unique_lines_and_probe_pairs(tmp_path):
    data_file = _write_e2e_coverage_data(tmp_path)
    manifest = {
        "scope": "full_suite",
        "filtered": False,
        "run_complete": True,
        "runner_exit_code": 0,
        "probe_inventory": ["probe_a", "probe_b", "probe_c"],
        "selected_probe_ids": ["probe_a", "probe_b", "probe_c"],
        "probe_statuses": {
            "probe_a": "passed", "probe_b": "failed", "probe_c": "passed",
        },
    }

    report = _report_mod.coverage_tools.build_e2e_probe_overlap_report(
        data_file, run_manifest=manifest, base_dir=str(tmp_path),
    )

    assert report["complete"] is True
    assert report["probe_inventory"]["completed"] == ["probe_a", "probe_b", "probe_c"]
    probes = {item["probe_id"]: item for item in report["probes"]}
    assert probes["probe_a"]["covered_source_line_count"] == 3
    assert probes["probe_a"]["unique_source_line_count"] == 2
    assert probes["probe_a"]["unique_source_lines"] == [
        {"file": os.path.join("pkg", "mod_a.py"), "line": 1},
        {"file": os.path.join("pkg", "mod_b.py"), "line": 10},
    ]
    assert probes["probe_b"]["unique_source_line_count"] == 1
    pairs = {(item["probe_a"], item["probe_b"]): item["shared_source_line_count"]
             for item in report["overlaps"]}
    assert pairs[("probe_a", "probe_b")] == 1
    assert pairs[("probe_a", "probe_c")] == 0


def test_e2e_overlap_report_marks_filtered_or_skipped_coverage_incomplete(tmp_path):
    data_file = _write_e2e_coverage_data(tmp_path)
    report = _report_mod.coverage_tools.build_e2e_probe_overlap_report(
        data_file,
        run_manifest={
            "scope": "filtered",
            "filtered": True,
            "run_complete": False,
            "probe_inventory": ["probe_a", "probe_b", "probe_c", "probe_d"],
            "selected_probe_ids": ["probe_a", "probe_d"],
            "probe_statuses": {"probe_a": "passed", "probe_d": "skipped"},
        },
        base_dir=str(tmp_path),
    )

    assert report["incomplete"] is True
    assert report["filtered"] is True
    assert report["probe_inventory"]["skipped"] == ["probe_d"]
    assert report["probe_inventory"]["missing_coverage_context"] == ["probe_d"]
