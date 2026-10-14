from coverage import CoverageData
from collections import defaultdict
from itertools import combinations
import sys
import os
from typing import List, Dict


def load_coverage_matrix(data_file=".coverage", context_prefix="test"):
    """Map matching coverage contexts to their covered source lines.

    ``context_prefix`` defaults to ``test`` for existing test-coverage consumers.
    Pass ``e2e:`` to analyze one isolated variant-probe context per probe.
    """
    data = CoverageData(basename=data_file)
    data.read()

    test_to_lines = defaultdict(set)

    for filename in data.measured_files():
        contexts_by_lineno = data.contexts_by_lineno(filename)

        for lineno, contexts in contexts_by_lineno.items():
            for ctx in contexts:
                if ctx and ctx.startswith(context_prefix):
                    test_to_lines[ctx].add((filename, lineno))

    return test_to_lines


def build_e2e_probe_overlap_report(data_file, run_manifest=None, base_dir=None):
    """Build source-line uniqueness and pairwise overlap for ``e2e:<probe>`` contexts.

    The manifest comes from ``run_variant_probes.py`` and distinguishes a complete
    unfiltered suite from filtered or interrupted runs. Coverage data alone cannot
    identify probes that were selected but never executed or had no measured lines.
    """
    base = os.path.abspath(base_dir or os.getcwd())
    matrix = load_coverage_matrix(data_file, context_prefix="e2e:")
    lines_by_probe = {
        context.removeprefix("e2e:"): set(lines)
        for context, lines in matrix.items()
    }

    manifest = run_manifest if isinstance(run_manifest, dict) else {}
    inventory = sorted(set(manifest.get("probe_inventory") or []))
    selected = sorted(set(manifest.get("selected_probe_ids") or []))
    statuses = manifest.get("probe_statuses") if isinstance(manifest.get("probe_statuses"), dict) else {}
    completed = sorted(
        probe for probe in selected if statuses.get(probe) in {"passed", "failed"}
    )
    skipped = sorted(probe for probe in selected if statuses.get(probe) == "skipped")
    not_run = sorted(set(selected) - set(statuses))
    covered_by_line = defaultdict(set)
    for probe, lines in lines_by_probe.items():
        for line in lines:
            covered_by_line[line].add(probe)

    probe_ids = sorted(set(inventory) | set(selected) | set(lines_by_probe))
    probes = []
    for probe in probe_ids:
        lines = lines_by_probe.get(probe, set())
        unique_lines = sorted(
            (os.path.relpath(path, base), lineno)
            for path, lineno in lines
            if covered_by_line[(path, lineno)] == {probe}
        )
        probes.append({
            "probe_id": probe,
            "status": statuses.get(probe, "not_run"),
            "covered_source_line_count": len(lines),
            "unique_source_line_count": len(unique_lines),
            "unique_source_lines": [
                {"file": path, "line": lineno} for path, lineno in unique_lines
            ],
        })

    overlap_pairs = []
    measured_probe_ids = sorted(lines_by_probe)
    for first, second in combinations(measured_probe_ids, 2):
        overlap_pairs.append({
            "probe_a": first,
            "probe_b": second,
            "shared_source_line_count": len(lines_by_probe[first] & lines_by_probe[second]),
        })

    filtered = manifest.get("filtered") is True
    run_complete = manifest.get("run_complete") is True
    missing_coverage = sorted(set(selected) - set(lines_by_probe))
    coverage_complete = not missing_coverage
    complete = run_complete and coverage_complete and not filtered
    return {
        "schema_version": 1,
        "scope": manifest.get("scope", "unknown"),
        "filtered": filtered,
        "complete": complete,
        "incomplete": not complete,
        "run_complete": run_complete,
        "coverage_complete": coverage_complete,
        "runner_exit_code": manifest.get("runner_exit_code"),
        "probe_inventory": {
            "available": inventory,
            "selected": selected,
            "completed": completed,
            "skipped": skipped,
            "not_run": not_run,
            "missing_coverage_context": missing_coverage,
        },
        "probes": probes,
        "overlaps": overlap_pairs,
    }


def rank_tests_by_line_count(test_to_lines):
    ranked = sorted(
        test_to_lines.items(),
        key=lambda item: len(item[1]),
        reverse=True
    )
    return ranked


def discover_tests_ranked(data_file: str = ".coverage") -> List[Dict[str, object]]:
    """
    Discover all tests and their line coverage counts, ranked by coverage.

    Args:
        data_file: Path to coverage data file (default: ".coverage")

    Returns:
        List of dicts: [{"test": "test_name", "lines": count}, ...]
    """
    test_to_lines = load_coverage_matrix(data_file)
    ranked = rank_tests_by_line_count(test_to_lines)

    return [
        {"test": test_name, "lines": len(lines)}
        for test_name, lines in ranked
    ]


def cov_lines_by_test(test_name: str, base_dir: str, data_file: str = ".coverage") -> List[Dict[str, object]]:
    """
    Get all lines covered by a specific test, relative to base_dir.

    Args:
        test_name: Full test name (e.g., "test_module::TestClass::test_method")
        base_dir: Base directory for relative paths
        data_file: Path to coverage data file (default: ".coverage")

    Returns:
        List of dicts: [{"file": "relative/path.py", "line": 42}, ...]
    """
    test_to_lines = load_coverage_matrix(data_file)

    if test_name not in test_to_lines:
        return []

    covered_lines = test_to_lines[test_name]
    result = []

    for filepath, lineno in covered_lines:
        relative_path = os.path.relpath(filepath, base_dir)
        result.append({"file": relative_path, "line": lineno})

    # Sort by file path, then line number
    result.sort(key=lambda x: (x["file"], x["line"]))

    return result

def extended_cov_lines_raw_structure(filepath: str, base_dir: str, data_file: str = ".coverage"):
    data = CoverageData(basename=data_file)
    data.read()

    if filepath not in data.measured_files():
        filepath = os.path.join(base_dir, filepath)

    return data.contexts_by_lineno(filepath)

def main():
    test_to_lines = load_coverage_matrix()
    if len(sys.argv) > 1:
        # expected full test name as argument. If do not know the name then run without arguments
        test_name = sys.argv[1]
        # get base dir
        base_dir = os.path.dirname(os.path.abspath(__file__))
        print(test_name)
        covered_files_lines = []
        for line in test_to_lines[test_name]:
            # print file path relative to base dir
            covered_files_lines.append((os.path.relpath(line[0], base_dir), line[1]))
        # sort by name
        covered_files_lines.sort(key=lambda x: x[0])
        for file, line in covered_files_lines:
            print(f"  {file}:{line}")
        return
    ranked = rank_tests_by_line_count(test_to_lines)

    print(f"{'Lines':>6}  Test")
    print("-" * 50)

    for test, lines in ranked:
        print(f"{len(lines):>6}  {test}")


if __name__ == "__main__":
    main()
