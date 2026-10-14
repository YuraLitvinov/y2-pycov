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


def test_export_coverage_context_supports_arbitrary_contexts_and_roots(tmp_path):
    source_file = os.path.join(str(tmp_path), "source.coverage")
    output_file = os.path.join(str(tmp_path), "probe-root", "coverage", ".coverage")
    source = CoverageData(basename=source_file)
    module = os.path.join(str(tmp_path), "app.py")
    source.set_context("job:alpha")
    source.add_lines({module: [1, 3]})
    source.set_context("job:beta")
    source.add_lines({module: [2]})
    source.write()

    exported = _report_mod.coverage_tools.export_coverage_context(
        source_file, "job:alpha", output_file,
    )

    assert exported is True
    assert os.path.isfile(output_file)
    contexts = _report_mod.coverage_tools.load_coverage_matrix(
        output_file, context_prefix="job:",
    )
    assert contexts == {"job:alpha": {(module, 1), (module, 3)}}
    assert _report_mod.coverage_tools.export_coverage_context(
        source_file, "missing:context", os.path.join(str(tmp_path), "missing", ".coverage"),
    ) is False


def test_analyze_named_coverage_unions_shards_without_contexts(tmp_path):
    def write_shard(name, lines):
        path = tmp_path / name
        data = CoverageData(basename=str(path))
        data.add_lines({str(source): values for source, values in lines.items()})
        data.write()
        return str(path)

    source_a = tmp_path / "pkg" / "module.py"
    source_b = tmp_path / "pkg" / "other.py"
    alpha_one = write_shard("alpha-one.coverage", {source_a: [1, 2]})
    alpha_two = write_shard("alpha-two.coverage", {source_a: [3], source_b: [10]})
    beta = write_shard("beta.coverage", {source_a: [2, 3]})
    gamma = write_shard("gamma.coverage", {source_a: [5]})

    result = _report_mod.coverage_tools.analyze_named_coverage(
        {"alpha": [alpha_one, alpha_two], "beta": [beta], "gamma": [gamma]},
        base_dir=str(tmp_path),
    )

    assert result["test_count"] == 3
    assert result["suite_covered_source_line_count"] == 5
    tests = {row["test_id"]: row for row in result["tests"]}
    assert tests["alpha"]["covered_source_line_count"] == 4
    assert tests["alpha"]["unique_source_line_count"] == 2
    assert tests["alpha"]["unique_source_lines"] == [
        {"file": "pkg/module.py", "line": 1},
        {"file": "pkg/other.py", "line": 10},
    ]
    assert tests["beta"]["unique_source_line_count"] == 0
    assert tests["gamma"]["unique_source_line_count"] == 1
    assert result["zero_unique_tests"] == ["beta"]
    assert result["overlaps"] == [
        {"test_a": "alpha", "test_b": "beta", "shared_source_line_count": 2},
    ]


def test_analyze_named_coverage_rejects_missing_shard(tmp_path):
    import pytest

    with pytest.raises(FileNotFoundError, match="coverage data for 'probe' not found"):
        _report_mod.coverage_tools.analyze_named_coverage(
            {"probe": [str(tmp_path / "missing.coverage")]},
        )


def test_analyze_named_coverage_bitset_overlap_across_byte_boundaries(tmp_path):
    source = tmp_path / "pkg" / "many_lines.py"

    def write_data(name, lines):
        path = tmp_path / name
        data = CoverageData(basename=str(path))
        data.add_lines({str(source): lines})
        data.write()
        return str(path)

    first = write_data("first.coverage", list(range(1, 521)))
    second = write_data("second.coverage", [1, 8, 9, 255, 256, 519, 520, 521])

    result = _report_mod.coverage_tools.analyze_named_coverage(
        {"first": [first], "second": [second]}, base_dir=str(tmp_path),
    )

    tests = {row["test_id"]: row for row in result["tests"]}
    assert result["suite_covered_source_line_count"] == 521
    assert tests["first"]["unique_source_line_count"] == 513
    assert tests["second"]["unique_source_line_count"] == 1
    assert result["overlaps"] == [
        {"test_a": "first", "test_b": "second", "shared_source_line_count": 7},
    ]
