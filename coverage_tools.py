from coverage import CoverageData
from collections import defaultdict
import sys
import os
from typing import List, Dict

def load_coverage_matrix(data_file=".coverage"):
    data = CoverageData(basename=data_file)
    data.read()

    test_to_lines = defaultdict(set)

    for filename in data.measured_files():
        contexts_by_lineno = data.contexts_by_lineno(filename)

        for lineno, contexts in contexts_by_lineno.items():
            for ctx in contexts:
                if ctx and ctx.startswith("test"):
                    test_to_lines[ctx].add((filename, lineno))

    return test_to_lines


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
