"""Dependency-light MCP surface evaluator.

This runner uses the real Streamable HTTP transport. Protected tool checks are
reported as skipped unless the matching access token is supplied via the
environment; tokens are never written to result files.
"""

import json
import os
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
RESULTS = EVALS / "results"


def _post(url, payload, session_id=None, token=None):
    headers = {
        "Content-Type": "application/json",
        "Accept": "application/json, text/event-stream",
    }
    if session_id:
        headers["MCP-Session-ID"] = session_id
    if token:
        headers["Authorization"] = "Bearer " + token
    request = urllib.request.Request(
        url, data=json.dumps(payload).encode(), headers=headers, method="POST"
    )
    with urllib.request.urlopen(request, timeout=15) as response:
        body = response.read().decode()
        session = response.headers.get("mcp-session-id")
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:]), session
    raise RuntimeError("MCP response did not contain an SSE data event")


def initialize(url):
    payload = {
        "jsonrpc": "2.0", "id": 1, "method": "initialize",
        "params": {
            "protocolVersion": "2025-03-26", "capabilities": {},
            "clientInfo": {"name": "sewasetu-evaluator", "version": "1.0"},
        },
    }
    result, session = _post(url, payload)
    if "error" in result or not session:
        raise RuntimeError(result.get("error", "MCP initialization failed"))
    return session


def tool_list(url, session):
    result, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session,
    )
    return [tool["name"] for tool in result.get("result", {}).get("tools", [])]


def tool_call(url, session, name, arguments=None, token=None):
    result, _ = _post(
        url,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": name, "arguments": arguments or {}}},
        session,
        token,
    )
    return result


def evaluate_endpoint(name, url, expected_tools, token=None):
    checks = []
    try:
        session = initialize(url)
        checks.append({"name": "initialize", "passed": True})
        tools = tool_list(url, session)
        isolated = set(tools) == set(expected_tools)
        checks.append({"name": "tool isolation", "passed": isolated, "actual": tools})
        if name == "citizen" and "get_required_documents" in tools:
            response = tool_call(url, session, "get_required_documents")
            passed = "result" in response and "error" not in response
            checks.append({"name": "public tool call", "passed": passed})
        protected_token = token or os.getenv(name.upper() + "_MCP_TOKEN")
        if protected_token:
            response = tool_call(url, session, expected_tools[0], {}, protected_token)
            checks.append({"name": "protected tool call", "passed": "error" not in response})
        else:
            checks.append({"name": "protected tool call", "passed": None, "skipped": True})
    except Exception as exc:
        checks.append({"name": "endpoint reachable", "passed": False, "failure": str(exc)})
    return {"endpoint": name, "checks": checks, "passed": all(c["passed"] is not False for c in checks)}


def main():
    citizen_url = os.getenv("CITIZEN_MCP_URL", "http://127.0.0.1:8101/mcp")
    officer_url = os.getenv("OFFICER_MCP_URL", "http://127.0.0.1:8102/mcp")
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": [
            evaluate_endpoint("citizen", citizen_url, [
                "get_application_status", "get_application_details",
                "get_required_documents", "get_form_guidance",
                "get_connected_applications", "withdraw_application",
            ]),
            evaluate_endpoint("officer", officer_url, [
                "search_applications", "get_application", "approve_application",
                "reject_application", "get_audit_history",
            ]),
        ],
    }
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    return 0 if all(item["passed"] for item in result["endpoints"]) else 1


if __name__ == "__main__":
    sys.exit(main())
