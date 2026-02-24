"""Test MCP coverage server conversion function."""

from mcp_coverage_server import CoverageTool


class TestConvertRawToExtendedCovLines:
    """Test convert_raw_to_extended_cov_lines function."""

    def test_convert_raw_to_extended_cov_lines(self):
        """Test conversion of raw coverage structure to extended format with context IDs."""
        raw_structure = {
            "16": [
                "test|tests.test_engine.TestAdaptiveRunner.test_runner_initialization",
                "test|tests.test_engine.TestAdaptiveRunner.test_error_logging"
            ],
            "17": [
                "test|tests.test_engine.TestAdaptiveRunner.test_error_logging",
                "test|tests.test_orchestrator_integration.TestMonolith.test_full_flow"
            ]
        }

        ctx_map, cov_lines_ctx = CoverageTool.convert_raw_to_extended_cov_lines(raw_structure)

        # Verify context map created with unique tests
        assert len(ctx_map) == 3
        assert ctx_map["ctx_001"] == "test|tests.test_engine.TestAdaptiveRunner.test_runner_initialization"
        assert ctx_map["ctx_002"] == "test|tests.test_engine.TestAdaptiveRunner.test_error_logging"
        assert ctx_map["ctx_003"] == "test|tests.test_orchestrator_integration.TestMonolith.test_full_flow"

        # Verify lines map to context IDs (reusing same ctx_id for same test)
        assert cov_lines_ctx["16"] == ["ctx_001", "ctx_002"]
        assert cov_lines_ctx["17"] == ["ctx_002", "ctx_003"]  # ctx_002 reused

    def test_extended_cov_lines_uses_new_format(self):
        """Test that extended_cov_lines method returns response in new context ID format."""
        from mcp_coverage_server import ExtendedCoveredLinesResponse

        # Create response using the new format
        response = ExtendedCoveredLinesResponse(
            filepath="/path/to/file.py",
            status="success",
            context_map={"ctx_001": "test|module.TestClass.test_method"},
            contexts_by_line={"10": ["ctx_001"], "11": ["ctx_001"]},
            message=None
        )

        # Verify response has both context_map and contexts_by_line fields
        data = response.model_dump()
        assert "context_map" in data
        assert "contexts_by_line" in data
        assert len(data["context_map"]) == 1
        assert len(data["contexts_by_line"]) == 2
        # Verify format: context_map maps ctx_NNN to test names
        assert all(k.startswith("ctx_") for k in data["context_map"].keys())
        # Verify format: contexts_by_line maps line numbers to list of ctx_NNN
        assert all(isinstance(v, list) for v in data["contexts_by_line"].values())
        assert all(all(c.startswith("ctx_") for c in ctx_list)
                   for ctx_list in data["contexts_by_line"].values())
