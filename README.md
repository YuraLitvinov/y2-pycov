# y2-pycov — coverage tooling

The single coverage base for the parent project. Two pieces:

## `coverage_tools.py` — the analysis engine
Context-aware coverage analysis built on the `coverage` package's `CoverageData`:
- `discover_tests_ranked(data_file)` — every test ranked by the number of lines it covers.
- `cov_lines_by_test(test_name, base_dir, data_file)` — the files/lines a single test covers (relative paths).
- `extended_cov_lines_raw_structure(filepath, base_dir, data_file)` — per-line test contexts for a file (`{lineno: [test_ctx, ...]}`).
- `load_coverage_matrix` / `rank_tests_by_line_count` — the underlying primitives.

## `coverage_report.py` — token-efficient per-module JSON report
Built **on top of** `coverage_tools.py` (it calls `extended_cov_lines_raw_structure`).
Emits a flat, machine-readable, per-module JSON report, filterable by module
substring — cheap to consume vs. an HTML coverage blob.

```bash
python y2-pycov/coverage_report.py                          # full JSON report
python y2-pycov/coverage_report.py --module tasks.py        # filter to module(s)
python y2-pycov/coverage_report.py --compact                # single-line JSON
```

`build_report(data_file, base_dir, module_filters)` is the programmatic API.

## `mcp_coverage_server.py` — optional MCP server
Wraps the engine as FastMCP tools (`discover_tests`, `cov_lines_by_test`,
`extended_cov_lines`). Requires the **optional** `fastmcp` dependency; the report
path above does NOT need it, and `test_mcp_coverage_server.py` is kept off the
parent project's pytest `testpaths` so the suite runs without `fastmcp`.

## Importability
This directory is hyphenated (`y2-pycov`), so it cannot be imported by package
name. External callers (and `coverage_report.py` loading its sibling
`coverage_tools.py`) load modules by file path via
`importlib.util.spec_from_file_location`. This loads the file directly and does
**not** mutate `sys.path` — no `sys.path` hacks anywhere.

## Coverage data
Uses the project `.coverage` data file.

---
## ⚠️ Upstream-push note
`coverage_report.py` (and this README note) were added **in-place** in this
submodule by the parent project's coverage-consolidation work. `y2-pycov` is a
**separate remote** (`https://github.com/YuraLitvinov/y2-pycov.git`). These
changes are NOT silently divergent — they must be **pushed upstream** to that
remote, then the parent project's submodule pointer bumped to the new commit.
Until then the submodule is ahead of its origin.
