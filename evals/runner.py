"""Dependency-light MCP surface evaluator.

This runner speaks the real Streamable HTTP transport. It checks that each
endpoint refuses anonymous connections, that the two endpoints expose only their
own tools, and (when tokens are supplied via the environment) that a protected
tool call succeeds. An optional end-to-end workflow submits an application as a
citizen and approves it as an officer, then confirms the citizen sees the new
status by reading the database directly.

Tokens are read from the environment and never written to result files.
"""

import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
EVALS = ROOT / "evals"
RESULTS = EVALS / "results"

INITIALIZE = {
    "jsonrpc": "2.0", "id": 1, "method": "initialize",
    "params": {
        "protocolVersion": "2025-03-26", "capabilities": {},
        "clientInfo": {"name": "sewasetu-evaluator", "version": "1.0"},
    },
}


def _post(url, payload, session_id=None, token=None):
    """POST an MCP message. Returns (parsed_result_or_None, http_status, session_id)."""
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
    try:
        with urllib.request.urlopen(request, timeout=15) as response:
            status = response.status
            body = response.read().decode()
            session = response.headers.get("mcp-session-id")
    except urllib.error.HTTPError as exc:
        exc.read()
        return None, exc.code, exc.headers.get("mcp-session-id")
    for line in body.splitlines():
        if line.startswith("data: "):
            return json.loads(line[6:]), status, session
    return None, status, session


def initialize(url, token=None):
    """Run the MCP initialize handshake; returns the session id."""
    result, status, session = _post(url, INITIALIZE, token=token)
    if status != 200 or result is None or "error" in result or not session:
        raise RuntimeError("MCP initialization failed (HTTP %s)" % status)
    return session


def initialize_status(url, token=None):
    return _post(url, INITIALIZE, token=token)[1]


def tool_list(url, session, token=None):
    result, _status, _session = _post(
        url,
        {"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}},
        session,
        token,
    )
    return [tool["name"] for tool in (result or {}).get("result", {}).get("tools", [])]


def tool_call(url, session, name, arguments=None, token=None):
    result, _status, _session = _post(
        url,
        {"jsonrpc": "2.0", "id": 3, "method": "tools/call",
         "params": {"name": name, "arguments": arguments or {}}},
        session,
        token,
    )
    return result or {}


def _tool_value(response):
    """Extract FastMCP structured content without storing credentials."""
    result = response.get("result", {})
    if isinstance(result.get("structuredContent"), dict):
        return result["structuredContent"]
    for item in result.get("content", []):
        if item.get("type") == "text":
            try:
                return json.loads(item.get("text", "{}"))
            except ValueError:
                return {}
    return {}


def _tool_error(response):
    result = response.get("result", {})
    if response.get("error"):
        return response["error"].get("message", "MCP request failed")
    if result.get("isError"):
        messages = [
            item.get("text", "") for item in result.get("content", [])
            if item.get("type") == "text"
        ]
        return "; ".join(messages) or "MCP tool call failed"
    return None


def evaluate_endpoint(name, url, expected_tools, token=None):
    checks = []
    token = token or os.getenv(name.upper() + "_MCP_TOKEN")
    try:
        if not token:
            checks.append({
                "name": "requires authorization",
                "passed": initialize_status(url) == 401,
            })
            checks.append({"name": "tool isolation", "passed": None, "skipped": True})
            return {
                "endpoint": name,
                "checks": checks,
                "passed": all(c["passed"] is not False for c in checks),
            }

        session = initialize(url, token)
        checks.append({"name": "initialize", "passed": True})
        tools = tool_list(url, session, token)
        checks.append({
            "name": "tool isolation",
            "passed": set(tools) == set(expected_tools),
            "actual": tools,
        })
        response = tool_call(url, session, expected_tools[0], {}, token)
        failure = _tool_error(response)
        checks.append({
            "name": "protected tool call",
            "passed": failure is None,
            **({"failure": failure} if failure else {}),
        })
    except Exception as exc:
        checks.append({"name": "endpoint reachable", "passed": False, "failure": str(exc)})
    return {"endpoint": name, "checks": checks, "passed": all(c["passed"] is not False for c in checks)}


def _db_connection():
    """Direct database connection for post-workflow verification."""
    import psycopg2
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "db"),
        port=os.getenv("DB_PORT", "5432"),
        dbname=os.getenv("DB_NAME", "sewasetu"),
        user=os.getenv("DB_USER", "sewasetu"),
        password=os.getenv("DB_PASSWORD", "sewasetu123"),
    )


def _verify_db_state(application_no, expected_status):
    """Read the database directly to verify the application state."""
    try:
        conn = _db_connection()
        cur = conn.cursor()
        cur.execute(
            "SELECT status, decided_by FROM applications WHERE application_no = %s",
            (application_no,),
        )
        row = cur.fetchone()
        cur.close()
        conn.close()
        if row is None:
            return False, "application not found in database"
        if row[0] != expected_status:
            return False, "expected status %s, found %s" % (expected_status, row[0])
        return True, "status=%s, decided_by=%s" % (row[0], row[1])
    except Exception as exc:
        return False, "DB error: %s" % str(exc)


def evaluate_workflow(citizen_url, officer_url, citizen_token, officer_token):
    checks = []
    try:
        citizen_session = initialize(citizen_url, citizen_token)
        officer_session = initialize(officer_url, officer_token)
        document = "bG9jYWwgYWdlIHByb29m"  # test-only, non-identity placeholder
        submission = tool_call(
            citizen_url,
            citizen_session,
            "submit_application",
            {
                "applicant_name": "Evaluation Applicant",
                "dob": "01/01/1960",
                "village": "Rampur",
                "block": "Sonari",
                "bank_account": "123456789",
                "ifsc": "SBIN0003077",
                "age_proof_filename": "proof.pdf",
                "age_proof_base64": document,
            },
            citizen_token,
        )
        submission_data = _tool_value(submission)
        submission_error = _tool_error(submission)
        application_no = submission_data.get("application_no")
        submission_check = {
            "name": "citizen submission",
            "passed": bool(application_no) and submission_error is None,
        }
        if submission_error:
            submission_check["failure"] = submission_error
        checks.append(submission_check)
        if not application_no:
            return {"checks": checks, "passed": False}

        # Verify in database directly.
        db_ok, db_detail = _verify_db_state(application_no, "PENDING")
        checks.append({
            "name": "database shows PENDING",
            "passed": db_ok,
            **({"failure": db_detail} if not db_ok else {"detail": db_detail}),
        })

        search = tool_call(
            officer_url, officer_session, "search_applications",
            {"application_no": application_no, "status": "PENDING", "limit": 5},
            officer_token,
        )
        applications = _tool_value(search).get("applications", [])
        search_error = _tool_error(search)
        checks.append({
            "name": "officer sees submitted application",
            "passed": bool(applications) and search_error is None,
            **({"failure": search_error} if search_error else {}),
        })

        decision = tool_call(
            officer_url, officer_session, "approve_application",
            {"application_no": application_no, "decision_note": "Evaluation approval"},
            officer_token,
        )
        decision_error = _tool_error(decision)
        checks.append({
            "name": "officer approval",
            "passed": decision_error is None,
            **({"failure": decision_error} if decision_error else {}),
        })

        # Verify in database directly.
        db_ok, db_detail = _verify_db_state(application_no, "APPROVED")
        checks.append({
            "name": "database shows APPROVED",
            "passed": db_ok,
            **({"failure": db_detail} if not db_ok else {"detail": db_detail}),
        })

        status = tool_call(
            citizen_url, citizen_session, "get_application_status", {}, citizen_token
        )
        status_text = json.dumps(status)
        status_error = _tool_error(status)
        checks.append({
            "name": "citizen sees approved status",
            "passed": "APPROVED" in status_text and status_error is None,
            **({"failure": status_error} if status_error else {}),
        })
    except Exception as exc:
        checks.append({"name": "end-to-end workflow", "passed": False, "failure": str(exc)})
    return {"checks": checks, "passed": all(c["passed"] for c in checks)}


def _load_json(path):
    try:
        with open(path, encoding="utf-8") as f:
            return json.load(f)
    except (OSError, ValueError):
        return None


def main():
    citizen_url = os.getenv("CITIZEN_MCP_URL", "http://127.0.0.1:8101/mcp")
    officer_url = os.getenv("OFFICER_MCP_URL", "http://127.0.0.1:8102/mcp")
    citizen_token = os.getenv("CITIZEN_MCP_TOKEN")
    officer_token = os.getenv("OFFICER_MCP_TOKEN")
    result = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "endpoints": [
            evaluate_endpoint("citizen", citizen_url, [
                "get_application_status", "get_application_details",
                "get_required_documents", "get_form_guidance", "submit_application",
                "get_connected_applications", "withdraw_application",
            ], citizen_token),
            evaluate_endpoint("officer", officer_url, [
                "search_applications", "get_application", "approve_application",
                "reject_application", "get_audit_history",
            ], officer_token),
        ],
    }
    if os.getenv("EVAL_RUN_WORKFLOW") == "1" and citizen_token and officer_token:
        result["workflow"] = evaluate_workflow(
            citizen_url, officer_url, citizen_token, officer_token
        )
    RESULTS.mkdir(parents=True, exist_ok=True)
    (RESULTS / "latest.json").write_text(json.dumps(result, indent=2) + "\n")
    print(json.dumps(result, indent=2))
    passed = all(item["passed"] for item in result["endpoints"])
    if "workflow" in result:
        passed = passed and result["workflow"]["passed"]
    return 0 if passed else 1


if __name__ == "__main__":
    sys.exit(main())
