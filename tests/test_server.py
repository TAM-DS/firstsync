import asyncio
import inspect
import json
import re
from pathlib import Path

import pytest
from mcp.server.mcpserver.exceptions import ToolError

import firstsync.salesforce.base as base
from firstsync import audit, mcp_server
from firstsync.target import TARGET_SCHEMA


def _lines(path):
    return [json.loads(line) for line in path.read_text().splitlines()]


def test_server_exposes_exactly_the_expected_tools():
    listed = asyncio.run(mcp_server.server.list_tools())
    assert sorted(t.name for t in listed) == sorted(mcp_server.TOOL_NAMES)
    assert sorted(mcp_server.TOOL_NAMES) == [
        "dryrun_get_results",
        "dryrun_start",
        "mapping_propose",
        "migration_get_status",
        "rule_test",
        "sf_check_access",
        "sf_count_records",
        "sf_describe_object",
        "sf_sample_records",
        "target_get_schema",
    ]
    assert all(t.description for t in listed)


def test_tool_call_limit_stops_a_runaway_session(monkeypatch):
    monkeypatch.setattr(mcp_server, "_calls", 0)
    monkeypatch.setenv("FIRSTSYNC_MAX_TOOL_CALLS", "2")
    mcp_server.target_get_schema()
    mcp_server.target_get_schema()
    with pytest.raises(ToolError, match="limit of 2 tool calls"):
        mcp_server.target_get_schema()


def test_mapping_tools_are_logged_in_the_map_stage(_audit_to_tmp, tmp_path, monkeypatch):
    monkeypatch.setenv("FIRSTSYNC_STATE_DIR", str(tmp_path / "state"))
    mcp_server.rule_test("org_b", "Account.Name", [{"op": "trim"}])
    with pytest.raises(ToolError):
        mcp_server.mapping_propose("org_b", [])
    first, second = _lines(_audit_to_tmp)
    assert (first["tool"], first["stage"], first["ok"]) == ("rule_test", "map", True)
    assert (second["tool"], second["stage"], second["ok"]) == ("mapping_propose", "map", False)


def test_no_tool_accepts_a_credential():
    for tool in asyncio.run(mcp_server.server.list_tools()):
        for name in tool.input_schema.get("properties", {}):
            assert not re.search(r"token|secret|password|key", name, re.IGNORECASE)


def test_the_client_interface_has_no_write_method():
    methods = [
        name
        for name, _ in inspect.getmembers(base.SalesforceClient, inspect.isfunction)
        if not name.startswith("_")
    ]
    assert sorted(methods) == ["accessible_objects", "count", "describe", "sample"]


def test_each_call_is_logged_with_a_hash_of_its_output(_audit_to_tmp):
    result = mcp_server.sf_count_records("org_a")
    mcp_server.target_get_schema()
    first, second = _lines(_audit_to_tmp)
    assert first["tool"] == "sf_count_records"
    assert first["connection"] == "org_a"
    assert first["stage"] == "discover"
    assert first["ok"] is True
    assert first["output_sha256"] == audit.output_hash(result)
    assert second["tool"] == "target_get_schema"
    assert second["connection"] is None


def test_failed_calls_are_logged_too(_audit_to_tmp):
    with pytest.raises(ToolError, match="Not a valid Salesforce API name"):
        mcp_server.sf_describe_object("org_a", "Account; DROP")
    (entry,) = _lines(_audit_to_tmp)
    assert entry["ok"] is False
    assert entry["output_sha256"] is None
    assert "Not a valid Salesforce API name" in entry["error"]


def test_sql_schema_matches_the_python_schema():
    sql = (Path(mcp_server.__file__).parent / "target" / "schema.sql").read_text()
    for table, spec in TARGET_SCHEMA["tables"].items():
        match = re.search(rf"CREATE TABLE {table} \((.*?)\n\);", sql, re.DOTALL)
        assert match, table
        columns = set(re.findall(r"^\s{4}([a-z_]+)\s", match.group(1), re.MULTILINE))
        assert {f["name"] for f in spec["fields"]} <= columns
        for field in spec["fields"]:
            line = re.search(rf"^\s{{4}}{field['name']}\s+.*$", match.group(1), re.MULTILINE)
            assert ("NOT NULL" in line.group(0)) == field["required"], (table, field["name"])


def test_unknown_connection_and_unreadable_object_reach_claude_as_readable_errors():
    with pytest.raises(ToolError, match="No connection named"):
        mcp_server.sf_check_access("org_zz")
    with pytest.raises(ToolError, match="cannot read"):
        mcp_server.sf_describe_object("org_a", "Lead")
