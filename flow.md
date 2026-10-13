# Sewa Setu Assistant Implementation Flow

This document is the working checklist for completing the assignment in this repository.

## 1. Understand the Assignment

Read these files first:

- `BRIEF.md`: assignment requirements and submission deliverables
- `README.md`: existing portal behavior and local startup instructions
- `app/app.py`: Flask routes, citizen flow, officer flow, and database operations
- `app/oauth.py`: OAuth discovery, authorization, token, and scope behavior
- `app/schema.sql`: database tables and relationships
- `docker-compose.yml`: services, networks, volumes, and environment variables

Core rule: the existing Sewa Setu portal remains the system of record. MCP servers must use the portal's database and authorization model instead of maintaining a competing application database.

## 2. Start the Existing Portal

Run from the repository root:

```bash
cd ~/Desktop/AI_4_Bharat/sewasetu-ai-handout
```

If Docker Hub reports an IPv6 or anonymous-token error, pull the base images first:

```bash
docker pull postgres:15
docker pull python:3.11-slim
```

Start the portal in the background:

```bash
ADMIN_PASSWORD=dev-password docker compose up -d
```

Check the containers:

```bash
docker compose ps
```

Check the portal:

```bash
curl -i http://localhost:8000/
```

Expected HTTP status: `200`.

Local URLs:

- Portal: `http://localhost:8000/`
- Applicant status: `http://localhost:8000/status`
- Department login: `http://localhost:8000/admin`
- Simulated SMS console: `http://localhost:8000/__gateway/`

View logs without stopping the services:

```bash
docker compose logs -f app
```

Stop the stack:

```bash
docker compose down
```

Only reset the database when deliberately starting over:

```bash
docker compose down -v
ADMIN_PASSWORD=dev-password docker compose up -d
```

## 3. Define the Target Architecture

Build two separately addressable MCP servers over streamable HTTP:

```text
Citizen client -> Citizen MCP endpoint -> portal database / portal APIs
Officer client -> Officer MCP endpoint -> portal database / portal APIs
```

The endpoints must be separate. A citizen client must not receive officer tools, and an officer client must not be able to act as an arbitrary citizen.

Recommended service layout:

```text
assistant/
  auth.py
  db.py
  citizen_server.py
  officer_server.py
  tools/
    citizen_tools.py
    officer_tools.py
  requirements.txt

evals/
  personas/
  scenarios/
  runner.py
  results/
```

Keep the MCP implementation separate from the existing Flask portal where possible. Reuse the portal's database schema and OAuth contract.

## 4. Inspect the Existing Database Contract

Before writing queries, inspect `app/schema.sql` and identify:

- Application table and primary key
- Applicant identity fields
- Mobile number fields
- Application status values
- Address and village fields
- Uploaded document fields
- Audit/history tables
- OAuth client, authorization, token, and connected-application tables

Then inspect the matching functions and routes in `app/app.py`. Prefer the same status names, validation rules, and transaction behavior already used by the portal.

Do not guess table or column names. Confirm them from `app/schema.sql`.

## 5. Implement Shared Database Access

Complete `assistant/db.py` with:

- PostgreSQL connection creation
- Environment-based connection settings
- Context-managed cursors/connections
- Parameterized SQL only
- Explicit commit for mutations
- Rollback on exceptions
- Read-only helpers for lookup operations

The Compose database is reachable from other containers as:

```text
host=db
port=5432
user=sewasetu
password=sewasetu123
database=sewasetu
```

Do not expose database credentials in the MCP response or in committed secrets.

## 6. Implement Authentication and Authorization

Complete `assistant/auth.py` using the existing OAuth behavior in `app/oauth.py`.

Every MCP request must:

1. Read the bearer token.
2. Validate the token signature using the portal's JWKS or the same verified key configuration.
3. Validate issuer and expiration.
4. Validate the expected audience/resource.
5. Validate the required scope.
6. Extract the subject and role.
7. Reject a token that does not belong to the endpoint's required role.

Citizen identity is represented by a subject similar to:

```text
citizen:<mobile>
```

Officer identity is represented by a subject similar to:

```text
officer:<username>
```

Required isolation:

- Citizen endpoint accepts citizen authorization only.
- Officer endpoint accepts officer authorization only.
- Citizen tools always scope data to the authenticated citizen.
- Officer tools authorize each administrative mutation.
- Never trust a mobile number, username, or role supplied only in tool arguments.

Add tests for missing, malformed, expired, wrong-audience, wrong-scope, and wrong-role tokens.

## 7. Build the Citizen MCP Server

Complete `assistant/citizen_server.py` and citizen tools with a streamable HTTP transport.

Expose only citizen tools. Suggested tools:

### `get_application_status`

Input:

- No identity argument; derive identity from the token.

Behavior:

- Return the authenticated citizen's active application status.
- Include application number, scheme, submitted date, current status, and next action.
- Do not return another citizen's records.

### `get_application_details`

Input:

- Optional application number, but verify ownership from the token.

Behavior:

- Return only records owned by the authenticated citizen.
- Avoid exposing internal secrets or unrelated applicant data.

### `get_required_documents`

Behavior:

- Explain the documents needed for an old-age pension application.
- Reflect the portal's actual validation rules.

### `withdraw_application`

Input:

- Application number
- Optional withdrawal reason

Behavior:

- Allow withdrawal only for the authenticated citizen's eligible pending application.
- Use the portal's existing status and audit conventions.
- Return the resulting status.

### `get_connected_applications`

Behavior:

- Return OAuth applications connected to the authenticated citizen.
- Do not return refresh tokens or token secrets.

For every tool, return clear structured results and user-safe error messages. Do not return raw SQL errors, stack traces, access tokens, or database credentials.

## 8. Build the Officer MCP Server

Complete `assistant/officer_server.py` and officer tools with a separate streamable HTTP endpoint.

Expose only officer tools. Suggested tools:

### `search_applications`

Inputs may include:

- Status
- Village or location
- Application number
- Applicant name
- Date range
- Pagination limit and cursor

Behavior:

- Use parameterized queries.
- Apply a maximum page size.
- Return only fields needed for officer work.

### `get_application`

Input:

- Application number

Behavior:

- Return application details, uploaded-document metadata, and relevant audit history.
- Do not expose unnecessary authentication secrets.

### `approve_application`

Input:

- Application number
- Decision note

Behavior:

- Confirm the officer is authorized.
- Allow only valid pending transitions.
- Write the same audit information as the portal.
- Return the resulting status.

### `reject_application`

Input:

- Application number
- Rejection reason

Behavior:

- Require a meaningful reason.
- Allow only valid pending transitions.
- Write an audit record.
- Return the resulting status.

### `get_audit_history`

Input:

- Application number

Behavior:

- Return chronological audit events for that application.

Do not expose these tools from the citizen endpoint. Test endpoint discovery and tool lists separately.

## 9. Define the MCP Error and Safety Contract

All tools should handle these cases consistently:

- Missing authorization: `401`
- Invalid or expired authorization: `401`
- Valid token with insufficient role or scope: `403`
- Missing required input: validation error
- Application not found: not-found result
- Application owned by another citizen: do not disclose its existence
- Invalid state transition: conflict or validation error
- Database failure: generic service error and server-side log only

Mutations must be safe against retries. Where practical, use transaction checks so an approval or withdrawal cannot overwrite a newer status unexpectedly.

## 10. Add Automated Tests

Create focused tests before running evaluations.

Citizen tests:

- Citizen can read their own application.
- Citizen cannot read another citizen's application.
- Citizen can withdraw an eligible pending application.
- Citizen cannot withdraw an approved application.
- Citizen cannot call officer tools.

Officer tests:

- Officer can search applications.
- Officer can view application details.
- Officer can approve a pending application.
- Officer can reject a pending application.
- Officer cannot use citizen identity to access citizen-only behavior.

Security tests:

- Missing token rejected.
- Invalid token rejected.
- Expired token rejected.
- Wrong issuer rejected.
- Wrong audience rejected.
- Wrong scope rejected.
- Wrong role rejected.

Regression tests:

- Existing portal home page still returns `200`.
- Existing portal admin login still works.
- Existing database seed is unchanged.

## 11. Create Evaluation Personas

Create several specific personas in `evals/personas/`. Each persona must include:

- Stable identifier
- Name
- Age
- Mobile number or test identity
- Village
- Personal situation
- Speaking style
- Goal
- Constraints or likely misunderstanding
- Expected final database state

Example:

```yaml
id: savitri-devi-01
name: Savitri Devi
age: 67
village: Rampur
style: Speaks in short Hindi-English sentences and asks for confirmation.
goal: Apply for old-age pension and understand the required age-proof document.
expected:
  application_status: pending
  application_owner: citizen identity used by the test
  required_document_present: true
```

Create both citizen and officer scenarios. Include ordinary successful cases and cases that test authorization boundaries or invalid requests.

Use test identities that do not conflict with important existing seed records.

## 12. Implement the Evaluation Runner

Complete `evals/runner.py` so it can:

1. Load personas and scenarios.
2. Connect to the real MCP endpoint as a client.
3. Send a limited-turn conversation or scripted user interaction.
4. Record every assistant response and MCP tool call.
5. Query Postgres after the conversation.
6. Compare actual state with expected state.
7. Write machine-readable results under `evals/results/`.
8. Produce data for the dashboard.

The evaluation must use the real MCP transport and client behavior, not direct function calls only.

Each result should include:

```json
{
  "persona_id": "savitri-devi-01",
  "scenario": "submit-pension-application",
  "conversation": [],
  "tools_called": [],
  "database_checks": [],
  "passed": true,
  "failures": []
}
```

Never store passwords, refresh tokens, access tokens, or uploaded identity documents in evaluation output.

## 13. Build `/eval-dashboard`

Add an authenticated or deliberately read-only dashboard route at `/eval-dashboard`.

The page must show:

- Persona name and summary
- Scenario and goal
- Conversation transcript
- MCP tools called
- Database checks performed
- Expected versus actual result summary
- Pass/fail status
- Failure details when applicable
- Aggregate pass rate

The dashboard should be safe to expose publicly. Redact:

- Mobile numbers except where explicitly needed for a test label
- Passwords
- OAuth tokens
- Refresh tokens
- Database credentials
- Uploaded document contents

Store results in a format the deployed dashboard can read consistently.

## 14. Add Docker Services

Add the MCP services to `docker-compose.yml` after they work locally.

Recommended services:

```text
citizen-mcp
  build: ./assistant
  command: run citizen server
  expose or ports: 8101

officer-mcp
  build: ./assistant
  command: run officer server
  expose or ports: 8102
```

Configure each service with:

- Database host and credentials
- Portal public base URL
- OAuth issuer and JWKS URL
- Required endpoint audience
- Environment-specific settings

Use separate health checks or startup checks where possible. `depends_on` alone does not guarantee that Postgres is ready to accept connections.

## 15. Run the Full Local Verification

Build and start everything:

```bash
ADMIN_PASSWORD=dev-password docker compose up --build -d
```

Check all containers:

```bash
docker compose ps
```

Check portal:

```bash
curl -fsS -o /dev/null -w 'portal=%{http_code}\n' http://localhost:8000/
```

Check each MCP endpoint using a real MCP client or the repository's client test:

```bash
# Replace these URLs with the implemented endpoints.
# Do not treat a plain HTTP 200 response as proof that MCP works;
# verify initialize, tool discovery, authorization, and a real tool call.
```

Run tests:

```bash
pytest -q
```

Run evaluations:

```bash
python evals/runner.py
```

Open:

```text
http://localhost:8000/eval-dashboard
```

Review service logs:

```bash
docker compose logs --tail=200 citizen-mcp
docker compose logs --tail=200 officer-mcp
docker compose logs --tail=200 app
```

## 16. Deploy

For deployment, set the actual public URL. The portal README notes that this URL is embedded in sign-in tokens and discovery documents.

Example:

```bash
PUBLIC_BASE_URL=https://your-domain.example \
ADMIN_PASSWORD='use-a-strong-password' \
docker compose up --build -d
```

Before sharing the deployment:

- Put the portal behind HTTPS.
- Confirm OAuth discovery uses the public HTTPS URL.
- Confirm JWKS is reachable.
- Confirm citizen and officer MCP endpoints are reachable.
- Confirm the officer account works.
- Confirm the dashboard is reachable.
- Confirm logs do not contain secrets.
- Confirm the deployment survives a restart.

## 17. Final Acceptance Checklist

### Portal

- [ ] Portal loads at the deployment URL.
- [ ] Applicant status page works.
- [ ] Admin login works.
- [ ] SMS gateway works for local testing.
- [ ] Database remains the source of truth.

### Citizen MCP

- [ ] Separate streamable HTTP endpoint exists.
- [ ] Citizen tools are visible.
- [ ] Officer tools are not visible.
- [ ] Citizen identity comes from the verified token.
- [ ] Cross-citizen data access is blocked.
- [ ] Mutations use portal-compatible validation and audit behavior.

### Officer MCP

- [ ] Separate streamable HTTP endpoint exists.
- [ ] Officer tools are visible.
- [ ] Citizen-only tools are not exposed.
- [ ] Officer authorization is verified.
- [ ] Search, view, approve, reject, and audit operations work.
- [ ] Invalid transitions are rejected.

### Evaluations

- [ ] Personas are specific and realistic.
- [ ] Scenarios use a real MCP client.
- [ ] Conversations are recorded.
- [ ] Tool calls are recorded.
- [ ] Database state is checked after each scenario.
- [ ] Results are shown on `/eval-dashboard`.
- [ ] Failures are visible and explainable.

### Submission

- [ ] Portal URL prepared.
- [ ] Citizen MCP endpoint prepared.
- [ ] Officer MCP endpoint prepared.
- [ ] Officer login prepared.
- [ ] `/eval-dashboard` URL prepared.
- [ ] Private GitHub repository named `sewasetu-assistant` created.
- [ ] `harshnisar` invited to the repository.
- [ ] Full Git history preserved.
- [ ] ZIP created including `.git`.
- [ ] Three-minute Loom recorded with face and screen.
- [ ] One-page design note written.

## 18. Suggested Work Order

Complete the work in this order:

1. Run and verify the existing portal.
2. Inspect `app/schema.sql`, `app/app.py`, and `app/oauth.py`.
3. Complete shared database and authentication helpers.
4. Complete citizen MCP tools and endpoint.
5. Test citizen authorization boundaries.
6. Complete officer MCP tools and endpoint.
7. Test officer mutations and audit behavior.
8. Add automated security and regression tests.
9. Create personas and scenarios.
10. Implement the real MCP evaluation runner.
11. Add `/eval-dashboard`.
12. Add MCP services to Docker Compose.
13. Run the complete local verification.
14. Deploy and run evaluations again.
15. Prepare the repository, ZIP, Loom, design note, and submission URLs.

## Important Rules

- Do not edit or replace `seed/seed.sql` unless the assignment explicitly requires it.
- Do not commit secrets.
- Do not return tokens or passwords from tools.
- Do not let tool arguments override authenticated identity.
- Do not expose officer tools on the citizen endpoint.
- Do not claim an evaluation passed without checking the database afterward.
- Do not consider the project complete until the deployed `/eval-dashboard` works.
