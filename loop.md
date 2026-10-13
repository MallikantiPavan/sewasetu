# Loom Video Guide

Target length: 2 minutes 30 seconds to 3 minutes. Show your face briefly at the beginning, then share the screen. Do not show passwords, access tokens, refresh tokens, OTPs, database credentials, or private user data.

## Before Recording

Start the local stack:

```bash
ADMIN_PASSWORD=dev-password docker compose up -d
```

Confirm the services:

```bash
docker compose ps
```

Open these pages or terminals before recording:

- Portal: `http://localhost:8000/`
- Evaluation dashboard: `http://localhost:8000/eval-dashboard`
- Citizen MCP endpoint: `http://localhost:8101/mcp`
- Officer MCP endpoint: `http://localhost:8102/mcp`

Run the evaluator before recording and keep the result ready:

```bash
EVAL_RUN_WORKFLOW=1 python evals/runner.py
```

Use a fresh test citizen identity for the submission workflow. Never record real citizen information.

## Three-Minute Script

### 0:00-0:20 - Introduction

Say:

> I built an agent-accessible old-age pension workflow for Sewa Setu using two separate MCP servers. Citizens can get guidance, submit an application, track it, and withdraw a pending application. Officers can search the queue, inspect applications, approve or reject them, and view the audit history. The existing portal and PostgreSQL database remain the system of record.

Show your face briefly, then switch to the shared screen.

### 0:20-0:55 - Citizen Experience

Show the citizen MCP tool list or the evaluation output. Explain:

- `get_form_guidance` explains each form step.
- `get_required_documents` gives the current age-proof requirement.
- `submit_application` validates age, bank account, IFSC, document type and size, deadline, duplicate applications, and allowed blocks.
- The citizen identity comes from the OAuth token, not from a tool argument.
- Bank details and document paths are not exposed in normal status responses.

Show the portal or dashboard only with test data.

### 0:55-1:25 - Officer Experience

Show the officer tool list or officer MCP endpoint. Explain:

- Officers have a separate endpoint and cannot see citizen tools.
- `search_applications` shows the queue within the configured block scope.
- `get_application` shows safe application metadata and audit history.
- `approve_application` and `reject_application` only work for pending applications.
- Rejection requires a reason.
- Every decision records the officer actor and decision in `audit_log`.

### 1:25-1:55 - End-to-End Proof

Show the evaluator result and point to these checks:

```text
citizen submission: true
officer sees submitted application: true
officer approval: true
citizen sees approved status: true
```

Say:

> This proves the citizen submission, officer review, approval, audit-backed mutation, and citizen follow-up use the same portal database.

Then show `/eval-dashboard` and point out the citizen and officer endpoint checks.

### 1:55-2:30 - Personas and Evals

Explain the test personas:

- Savitri Devi: an older citizen who needs short, clear guidance and confirmation at each step.
- Ramesh Kumar: a block officer who needs a focused pending queue and accountable decisions.

Explain the evaluation approach:

- Use real Streamable HTTP MCP transport.
- Check tool isolation between citizen and officer endpoints.
- Test validation and authorization boundaries.
- Verify the final status in the portal database.
- Redact credentials, tokens, and private documents from results.

### 2:30-3:00 - Design Decisions and Learning

Mention these three decisions:

1. **Identity from OAuth:** tool arguments cannot override the authenticated citizen or officer identity.
2. **Portal as system of record:** MCP writes to the existing applications and audit tables so web and agent-created applications are visible in both places.
3. **Separate least-privilege endpoints:** citizen and officer tools are exposed through different MCP servers with separate audiences and block scope.

Close with:

> The most important lesson was that an AI assistant needs structured guidance and strict validation, not just database access. With more time, I would import the portal's validation and creation helpers directly instead of mirroring those rules in the MCP service, and I would expand the conversational evaluations with more real client transcripts.

## Recording Checklist

- [ ] Face shown briefly at the beginning.
- [ ] Total duration is no more than three minutes.
- [ ] Citizen MCP endpoint shown.
- [ ] Officer MCP endpoint shown.
- [ ] Citizen submission demonstrated or evaluator result shown.
- [ ] Officer approval demonstrated or evaluator result shown.
- [ ] `/eval-dashboard` shown.
- [ ] Personas and evaluation method explained.
- [ ] Three design decisions explained.
- [ ] One lesson or future improvement explained.
- [ ] No passwords, OTPs, access tokens, refresh tokens, or database credentials visible.
