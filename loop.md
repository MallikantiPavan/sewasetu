# Loom Video Script

**Total time: ~3 minutes. Screen + Cam mode. Face in corner, screen main focus.**

---

## Step 1: Before You Record (Run These)

### Command 1: Start the full stack
```bash
cd /home/pavan/Desktop/AI_4_Bharat/sewasetu-ai-handout
ADMIN_PASSWORD=dev-password docker compose up -d
```
**Why:** Starts 6 containers — portal, database, citizen MCP, officer MCP, SMS gateway, and scheduler. The MCP servers on ports 8101 and 8102 are what you built.

### Command 2: Open the eval dashboard
Open in browser: `http://localhost:8000/eval-dashboard`
**Why:** This shows the endpoint checks and test results as a web page. You will screen-share this during the video.

### Command 3: Get tokens and run the full test
```bash
./get_tokens.sh dev-password 9876500000
```
**Why:** This registers an OAuth client, gives you two URLs to get citizen and officer tokens (enter mobile + OTP for citizen, admin + password for officer), then runs the full end-to-end test automatically. Keep the terminal output visible — you will show it in the video.

---

## Step 2: Record the Video

### 0:00 - 0:15 | Introduction

**Say:**
> "I built two MCP servers that let any AI assistant help a citizen apply for the old age pension and help a block officer decide applications. The portal and database remain the system of record. Built on open standards — MCP and OAuth 2.1."

**Show:** Your face, then switch to screen.

---

### 0:15 - 0:50 | Citizen MCP Server

**Say:**
> "This is the citizen-facing MCP server on port 8101. It exposes 7 tools that an AI assistant can call: get_form_guidance explains the form steps, get_required_documents lists what is needed, submit_application validates and submits, get_application_status tracks applications, get_application_details shows one application, withdraw_application lets a citizen withdraw, and get_connected_applications shows which apps are connected."

> "The citizen's identity comes from the OAuth token — never from a tool argument. The AI cannot act for a different citizen. The validation rules are shared with the portal through a common module, so the assistant cannot get anyone a pension the counter would not. Bank details are stripped from status responses."

**Show:** Scroll through the terminal output showing the citizen endpoint checks:
```
"endpoint": "citizen",
"checks": [
  {"name": "initialize", "passed": true},
  {"name": "tool isolation", "passed": true, "actual": [7 tools...]},
  {"name": "protected tool call", "passed": true}
]
```

---

### 0:50 - 1:20 | Officer MCP Server

**Say:**
> "This is the officer-facing MCP server on port 8102. Separate endpoint, separate OAuth scope — a citizen token cannot see officer tools. It exposes 5 tools: search_applications shows the pending queue scoped to allowed blocks, get_application shows one case with its audit history, approve_application and reject_application record decisions, and get_audit_history shows the full trail."

> "Only pending applications can be decided. A rejection requires a reason. Every decision writes to the audit log with the officer's identity."

**Show:** Scroll through the terminal output showing the officer endpoint checks:
```
"endpoint": "officer",
"checks": [
  {"name": "initialize", "passed": true},
  {"name": "tool isolation", "passed": true, "actual": [5 tools...]},
  {"name": "protected tool call", "passed": true}
]
```

---

### 1:20 - 1:50 | End-to-End Proof

**Say:**
> "The eval runner proves the full workflow. A citizen submits an application through the MCP server. The database shows it as PENDING. The officer searches the queue, finds it, and approves it. The database confirms APPROVED. The citizen checks status and sees APPROVED."

**Show:** The workflow section of the terminal output:
```
"workflow": {
  "checks": [
    {"name": "citizen submission", "passed": true},
    {"name": "database shows PENDING", "passed": true, "detail": "status=PENDING"},
    {"name": "officer sees submitted application", "passed": true},
    {"name": "officer approval", "passed": true},
    {"name": "database shows APPROVED", "passed": true, "detail": "status=APPROVED, decided_by=admin"},
    {"name": "citizen sees approved status", "passed": true}
  ],
  "passed": true
}
```

**Then show:** The eval dashboard at `http://localhost:8000/eval-dashboard` — it shows the same results as a web page.

---

### 1:50 - 2:30 | Personas and Evals

**Say:**
> "I invented three personas to test the system. Savitri Devi, 67, checking her pension status — she needs clear, simple answers and must not see anyone else's data. Ramohans Yadav, 72, applying for the first time — he needs help with technology and must upload age proof and bank details. Ramesh Kumar, the block officer — he needs a focused queue and accountable decisions."

> "The evals use real HTTP transport, not mocks. They verify the final state in the database directly. The dashboard shows all personas, scenarios, and results."

**Show:** The eval dashboard personas table and scenarios table.

---

### 2:30 - 3:00 | Design Decisions and Lesson

**Say:**
> "Three decisions mattered most. First, identity comes from the OAuth token — tool arguments cannot override who you are. Second, the portal stays the system of record — MCP servers write to the same database, so applications are visible in both places. Third, separate least-privilege endpoints — citizen and officer tools are isolated, and the assistant only works for a subset of blocks."

> "With more time, I would build a Gemini bridge so more AI assistants can plug in. But the MCP standard is open — any client can connect today."

**Show:** Your face. End the recording.

---

## Quick Reference

| What | Why |
|------|-----|
| `ADMIN_PASSWORD=dev-password docker compose up -d` | Starts all 6 containers |
| `./get_tokens.sh dev-password 9876500000` | Gets OAuth tokens + runs full test |
| `http://localhost:8000/eval-dashboard` | Web page showing test results |
| Terminal output from runner | Shows the actual MCP checks passing |

## Before You Hit Record

- [ ] Stack is running (`docker compose ps` shows 6 containers)
- [ ] Eval dashboard is open in a browser tab
- [ ] Terminal with eval runner output is visible
- [ ] No passwords or tokens visible on screen
- [ ] Loom is set to "Screen + Cam" mode
