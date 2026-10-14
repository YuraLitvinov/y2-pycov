from coverage import CoverageData
from collections import defaultdict
import sys
import os
from typing import Iterable, List, Dict, Mapping


def load_coverage_lines(data_files: Iterable[str]) -> set[tuple[str, int]]:
    """Load the union of source lines from one or more Coverage.py data files."""
    lines: set[tuple[str, int]] = set()
    paths = [os.fspath(path) for path in data_files]
    if not paths:
        raise ValueError("at least one coverage data file is required")
    for path in paths:
        if not os.path.isfile(path):
            raise FileNotFoundError(f"coverage data file not found: {path}")
        data = CoverageData(basename=path)
        data.read()
        for filename in data.measured_files():
            canonical = os.path.normcase(os.path.realpath(filename))
            lines.update((canonical, int(line)) for line in (data.lines(filename) or []))
    return lines


def analyze_named_coverage(
    test_data_files: Mapping[str, Iterable[str]], base_dir: str | None = None,
) -> dict:
    """Analyze independent Coverage.py files as named logical tests.

    Each mapping key is one test identity and its value contains one or more
    Coverage.py data files produced by that test (for example, multiprocessing
    shards). Files for one test are unioned in memory; data is never written to
    or merged into a shared database, and no context naming convention is used.

    The result includes per-test line counts, lines uniquely covered by each
    test, suite totals, and only non-zero pairwise overlaps. Source paths are
    canonicalized before comparison so shards created in different processes
    agree on line identity.
    """
    base = os.path.abspath(base_dir or os.getcwd())
    line_ids: dict[tuple[str, int], int] = {}
    sole_owner: dict[tuple[str, int], str] = {}
    covered_counts: dict[str, int] = {}
    test_masks: dict[str, bytearray] = {}

    for test_id, raw_paths in sorted(test_data_files.items()):
        if not isinstance(test_id, str) or not test_id:
            raise ValueError("test IDs must be non-empty strings")
        paths = [os.fspath(raw_paths)] if isinstance(raw_paths, (str, os.PathLike)) else [
            os.fspath(path) for path in raw_paths
        ]
        if not paths:
            raise ValueError(f"test {test_id!r} has no coverage data files")

        try:
            test_lines = load_coverage_lines(paths)
        except FileNotFoundError as exc:
            raise FileNotFoundError(f"coverage data for {test_id!r} not found: {exc}") from exc

        covered_counts[test_id] = len(test_lines)
        mask = bytearray()
        for line in test_lines:
            line_id = line_ids.get(line)
            if line_id is None:
                line_id = len(line_ids)
                line_ids[line] = line_id
                sole_owner[line] = test_id
            else:
                sole_owner.pop(line, None)
            byte_index = line_id >> 3
            if byte_index >= len(mask):
                mask.extend(b"\0" * (byte_index + 1 - len(mask)))
            mask[byte_index] |= 1 << (line_id & 7)
        test_masks[test_id] = mask

    # Store each logical test's covered lines as a compact bitset. Computing
    # intersections in C via Python's big-integer bit operations avoids walking
    # every pair of test IDs once for every commonly covered line. The old
    # line-to-test-list loop became prohibitively expensive for large suites.
    mask_size = (len(line_ids) + 7) // 8
    integer_masks = {
        test_id: int.from_bytes(mask.ljust(mask_size, b"\0"), byteorder="little")
        for test_id, mask in test_masks.items()
    }
    pair_counts: dict[tuple[str, str], int] = {}
    test_ids = sorted(test_data_files)
    for index, first in enumerate(test_ids):
        first_mask = integer_masks[first]
        for second in test_ids[index + 1:]:
            shared_count = (first_mask & integer_masks[second]).bit_count()
            if shared_count:
                pair_counts[(first, second)] = shared_count

    unique_by_test: dict[str, list[dict]] = defaultdict(list)
    for (filename, lineno), owner in sole_owner.items():
        unique_by_test[owner].append({
            "file": os.path.relpath(filename, base), "line": lineno,
        })
    tests = []
    suite_line_count = len(line_ids)
    for test_id in sorted(test_data_files):
        unique_lines = sorted(unique_by_test.get(test_id, []), key=lambda item: (item["file"], item["line"]))
        unique_count = len(unique_lines)
        tests.append({
            "test_id": test_id,
            "covered_source_line_count": covered_counts[test_id],
            "unique_source_line_count": unique_count,
            "unique_suite_coverage_share_percent": round(100 * unique_count / suite_line_count, 2)
            if suite_line_count else 0.0,
            "unique_source_lines": unique_lines,
        })
    return {
        "schema_version": 1,
        "test_count": len(tests),
        "suite_covered_source_line_count": suite_line_count,
        "zero_unique_tests": [
            row["test_id"] for row in tests if row["unique_source_line_count"] == 0
        ],
        "tests": tests,
        "overlaps": [
            {"test_a": first, "test_b": second, "shared_source_line_count": count}
            for (first, second), count in sorted(pair_counts.items())
        ],
    }


def load_coverage_matrix(data_file=".coverage", context_prefix="test"):
    """Map matching coverage contexts to their covered source lines.

    ``context_prefix`` defaults to ``test`` for existing test-coverage consumers.
    Callers can provide any prefix that matches their context naming scheme.
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


def export_coverage_context(data_file, context, output_file):
    """Write one context from a coverage database to an independent data file.

    This is context- and path-agnostic so callers can partition coverage for any
    test or workload without coupling the analysis library to a particular suite.
    Returns ``False`` when the requested context has no recorded coverage.
    """
    source = CoverageData(basename=data_file)
    source.read()
    if context not in source.measured_contexts():
        return False

    os.makedirs(os.path.dirname(os.path.abspath(output_file)), exist_ok=True)
    target = CoverageData(basename=output_file)
    source.set_query_contexts([context])
    for filename in source.measured_files():
        if source.has_arcs():
            arcs = source.arcs(filename) or []
            if arcs:
                target.set_context(context)
                target.add_arcs({filename: arcs})
        else:
            lines = source.lines(filename) or []
            if lines:
                target.set_context(context)
                target.add_lines({filename: lines})
    target.write()
    return True


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
