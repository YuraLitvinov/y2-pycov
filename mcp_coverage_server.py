# Coverage analysis tool for identifying test coverage statistics
import logging
import os
from typing import Dict, Any, List, Optional, cast

from pydantic import BaseModel
from llama_index.core.tools import FunctionTool
from llama_index.core.tools.tool_spec.base import BaseToolSpec
from coverage_tools import discover_tests_ranked, cov_lines_by_test, extended_cov_lines_raw_structure

logger = logging.getLogger(__name__)


# Pydantic Models for Type-Safe Serialization

class TestCoverageInfo(BaseModel):
    """Coverage information for a single test."""
    test: str
    lines: int


class CoveredLines(BaseModel):
    """Lines covered by a test, grouped by file."""
    files: Dict[str, List[int]]


class DiscoverTestsResponse(BaseModel):
    """Response from discover_tests tool."""
    tests: List[TestCoverageInfo]
    status: str  # "success" or "error"
    total_tests: int
    message: Optional[str] = None


class GetCoveredLinesResponse(BaseModel):
    """Response from cov_lines_by_test tool."""
    test: str
    files: Dict[str, List[int]]  # {"file_path": [line_numbers]}
    status: str  # "success" or "error"
    total_lines: int
    message: Optional[str] = None


class ExtendedCoveredLinesResponse(BaseModel):
    """Response from extended_cov_lines tool - coverage context information."""
    filepath: str
    status: str  # "success" or "error"
    context_map: Dict[str, str]  # {ctx_001: test_name, ctx_002: test_name, ...}
    contexts_by_line: Dict[str, List[str]]  # {line_number: [ctx_001, ctx_002, ...]}
    message: Optional[str] = None


class CoverageTool(BaseToolSpec):
    """Tool for analyzing test coverage and discovering coverage-guided testing opportunities."""

    def __init__(self, base_dir: str = None, data_file: str = ".coverage"):
        """
        Initialize the coverage analysis tool.

        Args:
            base_dir: Base directory for relative paths (defaults to project root)
            data_file: Path to coverage data file (default: ".coverage")
        """
        self.base_dir = base_dir or os.path.dirname(os.path.abspath(__file__))
        self.data_file = data_file
        self.last_result: Dict[str, Any] = {}

    def execute(self, tool_name: str, args: dict) -> Dict[str, Any]:
        """
        Execute a coverage analysis operation.

        Args:
            tool_name: Name of the tool to execute
            args: Tool arguments

        Returns:
            Tool result dictionary (Pydantic models serialized to dict)
        """
        if tool_name == "discover_tests":
            result = self.discover_tests()
            return result.model_dump()
        elif tool_name == "cov_lines_by_test":
            result = self.cov_lines_by_test(
                full_test_name=args.get('full_test_name', '')
            )
            return result.model_dump()
        return {"status": "rejected", "message": f"Unknown tool: {tool_name}"}

    def discover_tests(self) -> DiscoverTestsResponse:
        """
        Discover all tests and their coverage statistics.

        Returns statistics for all tests ranked by line coverage count.

        Returns:
            DiscoverTestsResponse with tests and total_tests
        """
        logger.info("Discovering tests with coverage statistics")

        try:
            tests_ranked = discover_tests_ranked(self.data_file)

            if not tests_ranked:
                logger.warning("No test coverage data found")
                result = DiscoverTestsResponse(
                    tests=[],
                    status="success",
                    total_tests=0,
                    message="No coverage data available"
                )
                self.last_result = result.model_dump()
                return result

            # Convert dicts to TestCoverageInfo objects
            test_infos = [
                TestCoverageInfo(
                    test=cast(str, t.get("test", "")),
                    lines=cast(int, t.get("lines", 0))
                )
                for t in tests_ranked
            ]

            result = DiscoverTestsResponse(
                tests=test_infos,
                status="success",
                total_tests=len(test_infos),
                message=None
            )
            self.last_result = result.model_dump()
            return result

        except Exception as e:
            logger.error(f"Error discovering tests: {e}")
            result = DiscoverTestsResponse(
                tests=[],
                status="error",
                total_tests=0,
                message=f"Failed to discover tests: {str(e)}"
            )
            self.last_result = result.model_dump()
            return result

    def cov_lines_by_test(
        self,
        full_test_name: str
    ) -> GetCoveredLinesResponse:
        """
        Get all lines covered by a specific test.

        Expected format for full_test_name:
        - "test_module::TestClass::test_method"
        - Obtained from discover_tests results

        Args:
            full_test_name: Full test identifier from discover_tests

        Returns:
            GetCoveredLinesResponse with covered lines grouped by file
        """
        if not full_test_name:
            logger.error("full_test_name is required")
            result = GetCoveredLinesResponse(
                test="",
                files={},
                status="error",
                total_lines=0,
                message="full_test_name is required"
            )
            self.last_result = result.model_dump()
            return result

        logger.info(f"Getting coverage lines for test: {full_test_name}")

        try:
            covered_lines = cov_lines_by_test(
                test_name=full_test_name,
                base_dir=self.base_dir,
                data_file=self.data_file
            )

            if not covered_lines:
                logger.warning(f"No coverage data found for test: {full_test_name}")
                result = GetCoveredLinesResponse(
                    test=full_test_name,
                    files={},
                    status="success",
                    total_lines=0,
                    message=f"No coverage data for test '{full_test_name}'"
                )
                self.last_result = result.model_dump()
                return result

            # Group lines by file: {"file_path": [line_numbers]}
            files_dict: Dict[str, List[int]] = {}
            for line_info in covered_lines:
                file_path = cast(str, line_info.get("file", ""))
                line_num = cast(int, line_info.get("line", 0))
                if file_path not in files_dict:
                    files_dict[file_path] = []
                files_dict[file_path].append(line_num)

            # Sort line numbers in each file
            for file_path in files_dict:
                files_dict[file_path].sort()

            result = GetCoveredLinesResponse(
                test=full_test_name,
                files=files_dict,
                status="success",
                total_lines=len(covered_lines),
                message=None
            )
            self.last_result = result.model_dump()
            return result

        except Exception as e:
            logger.error(f"Error getting coverage lines for {full_test_name}: {e}")
            result = GetCoveredLinesResponse(
                test=full_test_name,
                files={},
                status="error",
                total_lines=0,
                message=f"Failed to get coverage lines: {str(e)}"
            )
            self.last_result = result.model_dump()
            return result

    @staticmethod
    def convert_raw_to_extended_cov_lines(raw_structure: Dict[str, List[str]]) -> tuple:
        """
        Convert raw coverage structure to context-compressed format.

        Compresses duplicate test references across lines by mapping each unique test
        to a context ID (ctx_001, ctx_002, etc.). Reduces payload size when many tests
        cover many lines.

        Args:
            raw_structure: {line_num: [test_name1, test_name2, ...]}

        Returns:
            (ctx_map, contexts_by_line) where:
            - ctx_map: {ctx_001: test_name1, ctx_002: test_name2, ...}
            - contexts_by_line: {line_num: [ctx_001, ctx_002, ...]}
        """
        used_ctx_idx = 0
        ctx_test_cache = {}
        ctx_map = {}
        cov_lines_ctx = {}
        for line, tests in raw_structure.items():
            cov_lines_ctx[line] = []
            for test in tests:
                if test not in ctx_test_cache:
                    used_ctx_idx += 1
                    ctx_id = f"ctx_{used_ctx_idx:03d}"
                    ctx_test_cache[test] = ctx_id
                    ctx_map[ctx_id] = test
                ctx_id = ctx_test_cache[test]
                cov_lines_ctx[line].append(ctx_id)
        return ctx_map, cov_lines_ctx

    def extended_cov_lines(
        self,
        filepath: str
    ) -> ExtendedCoveredLinesResponse:
        """
        Get extended coverage context for a specific file.

        Shows which tests cover each line in the file (test contexts), using compressed
        context ID format to reduce payload size for large coverage data.

        Args:
            filepath: Path to file (absolute or relative to base_dir)

        Returns:
            ExtendedCoveredLinesResponse with context map and compressed line-to-context mapping
        """
        if not filepath:
            logger.error("filepath is required")
            result = ExtendedCoveredLinesResponse(
                filepath="",
                status="error",
                context_map={},
                contexts_by_line={},
                message="filepath is required"
            )
            self.last_result = result.model_dump()
            return result

        logger.info(f"Getting extended coverage for file: {filepath}")

        try:
            # Get raw coverage data from coverage_tools: {line_number: [test_names]}
            raw_contexts_by_line = extended_cov_lines_raw_structure(
                filepath=filepath,
                base_dir=self.base_dir,
                data_file=self.data_file
            )

            # Convert raw data to string keys for convert_raw_to_extended_cov_lines
            raw_structure = {str(line): tests if isinstance(tests, list) else list(tests)
                           for line, tests in raw_contexts_by_line.items()}

            # Convert to context ID compressed format
            context_map, contexts_by_line = self.convert_raw_to_extended_cov_lines(raw_structure)

            logger.info(f"Found coverage contexts for {len(contexts_by_line)} lines "
                       f"({len(context_map)} unique test contexts)")

            result = ExtendedCoveredLinesResponse(
                filepath=filepath,
                status="success",
                context_map=context_map,
                contexts_by_line=contexts_by_line,
                message=None
            )
            self.last_result = result.model_dump()
            return result

        except Exception as e:
            logger.error(f"Error getting extended coverage for {filepath}: {e}")
            result = ExtendedCoveredLinesResponse(
                filepath=filepath,
                status="error",
                context_map={},
                contexts_by_line={},
                message=f"Failed to get extended coverage: {str(e)}"
            )
            self.last_result = result.model_dump()
            return result


# Create FastMCP server at module level
from fastmcp import FastMCP

server = FastMCP("coverage-tool", "Coverage analysis tool")
coverage_tool = CoverageTool()


@server.tool(name="discover_tests", description="Discover all tests with coverage statistics")
def discover_tests() -> dict:
    """Discover all tests and their coverage statistics."""
    result = coverage_tool.discover_tests()
    return result.model_dump()


@server.tool(name="cov_lines_by_test", description="Get lines covered by a specific test")
def get_test_lines(full_test_name: str) -> dict:
    """Get all lines covered by a specific test, grouped by file."""
    result = coverage_tool.cov_lines_by_test(full_test_name)
    return result.model_dump()


@server.tool(name="extended_cov_lines", description="Get extended coverage context for a file")
def get_extended_cov_lines(filepath: str) -> dict:
    """Get which tests cover each line in a file (coverage contexts)."""
    result = coverage_tool.extended_cov_lines(filepath)
    return result.model_dump()


def main():
    """Start MCP server with configurable transport."""
    import argparse

    # Configure logging to stderr
    logging.basicConfig(
        level=logging.INFO,
        format='[%(asctime)s] %(levelname)s: %(message)s',
        datefmt='%Y-%m-%d %H:%M:%S'
    )

    parser = argparse.ArgumentParser(description="MCP Coverage Tool Server")
    parser.add_argument(
        "--transport",
        choices=["stdio", "http", "sse"],
        default="stdio",
        help="Transport protocol (default: stdio)"
    )
    parser.add_argument("--host", default="127.0.0.1", help="Host for HTTP/SSE")
    parser.add_argument("--port", type=int, default=8000, help="Port for HTTP/SSE")
    parser.add_argument("--data-file", default=".coverage", help="Coverage data file")
    parser.add_argument("--base-dir", help="Base directory for coverage analysis")

    args = parser.parse_args()

    # Update coverage tool configuration
    if args.data_file:
        coverage_tool.data_file = args.data_file
    if args.base_dir:
        coverage_tool.base_dir = args.base_dir

    # Start server with specified transport
    logger.info(f"Starting MCP server with {args.transport} transport")
    logger.info(f"Coverage file: {coverage_tool.data_file}")
    logger.info(f"Base directory: {coverage_tool.base_dir}")
    if args.transport != "stdio":
        logger.info(f"Listening on {args.host}:{args.port}")

    if args.transport == "stdio":
        server.run(transport="stdio", show_banner=False)
    elif args.transport == "http":
        server.run(transport="http", host=args.host, port=args.port, show_banner=False)
    elif args.transport == "sse":
        server.run(transport="sse", host=args.host, port=args.port, show_banner=False)


if __name__ == "__main__":
    main()
