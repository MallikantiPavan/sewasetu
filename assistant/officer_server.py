"""Officer-facing MCP server for the Sewa Setu portal."""

import os
from datetime import datetime

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP

import auth
from db import get_cursor


MCP_RESOURCE = (
	os.getenv("MCP_AUDIENCE", "http://localhost:8102").split(",")[0].strip().rstrip("/")
)

mcp = FastMCP(
	"Sewa Setu Officer Assistant",
	token_verifier=auth.PortalTokenVerifier(MCP_RESOURCE),
	auth=AuthSettings(
		issuer_url=auth.issuer(),
		resource_server_url=MCP_RESOURCE,
		required_scopes=["officer"],
		# The verifier checks the token's audience against the portal issuer and
		# this server's URL itself, so the transport need not re-check it.
		validate_token_resource=False,
	),
)

APPLICATION_COLUMNS = (
	"id, application_no, applicant_name, mobile, dob, village, block, "
	"status, submitted_at, decided_at, decided_by, doc_path"
)
ALLOWED_BLOCKS = tuple(
	block.strip() for block in os.getenv("MCP_ALLOWED_BLOCKS", "Sonari").split(",")
	if block.strip()
)


def _iso(value):
	return value.isoformat() if value is not None else None


def _application(row):
	if row is None:
		return None
	values = dict(zip(
		("id", "application_no", "applicant_name", "mobile", "dob", "village",
		 "block", "status", "submitted_at", "decided_at", "decided_by", "doc_path"),
		row,
	))
	values["dob"] = _iso(values["dob"])
	values["submitted_at"] = _iso(values["submitted_at"])
	values["decided_at"] = _iso(values["decided_at"])
	doc_path = values.pop("doc_path")
	values["document_uploaded"] = bool(doc_path)
	return values


def _officer(ctx: Context):
	"""Validate the officer access token and return the username."""
	claims = auth.authenticate(ctx.request_context.request, MCP_RESOURCE, "officer")
	return claims["sub"].split(":", 1)[1]


def _parse_date(value, field_name):
	if value is None or value == "":
		return None
	try:
		return datetime.strptime(value, "%Y-%m-%d").date()
	except ValueError as exc:
		raise ValueError("%s must use YYYY-MM-DD format." % field_name) from exc


@mcp.tool()
def search_applications(
	ctx: Context,
	status: str = "",
	village: str = "",
	application_no: str = "",
	applicant_name: str = "",
	date_from: str = "",
	date_to: str = "",
	limit: int = 25,
	offset: int = 0,
) -> dict:
	"""Search applications for authorized departmental work."""
	_officer(ctx)
	if limit < 1 or limit > 50:
		raise ValueError("limit must be between 1 and 50.")
	if offset < 0:
		raise ValueError("offset cannot be negative.")
	start_date = _parse_date(date_from, "date_from")
	end_date = _parse_date(date_to, "date_to")
	if start_date and end_date and start_date > end_date:
		raise ValueError("date_from cannot be after date_to.")

	conditions = []
	parameters = []
	conditions.append("block = ANY(%s)")
	parameters.append(list(ALLOWED_BLOCKS))
	if status.strip():
		conditions.append("status = %s")
		parameters.append(status.strip().upper())
	if village.strip():
		conditions.append("village ILIKE %s")
		parameters.append("%%%s%%" % village.strip())
	if application_no.strip():
		conditions.append("application_no = %s")
		parameters.append(application_no.strip())
	if applicant_name.strip():
		conditions.append("applicant_name ILIKE %s")
		parameters.append("%%%s%%" % applicant_name.strip())
	if start_date:
		conditions.append("submitted_at >= %s")
		parameters.append(start_date)
	if end_date:
		conditions.append("submitted_at < %s + INTERVAL '1 day'")
		parameters.append(end_date)

	query = "SELECT " + APPLICATION_COLUMNS + " FROM applications"
	if conditions:
		query += " WHERE " + " AND ".join(conditions)
	query += " ORDER BY submitted_at DESC LIMIT %s OFFSET %s"
	parameters.extend((limit, offset))

	with get_cursor() as cursor:
		cursor.execute(query, tuple(parameters))
		applications = [_application(row) for row in cursor.fetchall()]
	return {"applications": applications, "limit": limit, "offset": offset}


@mcp.tool()
def get_application(ctx: Context, application_no: str) -> dict:
	"""Return one application and its audit history."""
	_officer(ctx)
	if not application_no.strip():
		raise ValueError("application_no is required.")
	with get_cursor() as cursor:
		cursor.execute(
			"SELECT " + APPLICATION_COLUMNS +
			" FROM applications WHERE application_no = %s AND block = ANY(%s)",
			(application_no.strip(), list(ALLOWED_BLOCKS)),
		)
		application = _application(cursor.fetchone())
		if application is None:
			raise ValueError("Application not found.")
		cursor.execute(
			"SELECT at, action, actor, note FROM audit_log "
			"WHERE application_id = %s ORDER BY at ASC, id ASC",
			(application["id"],),
		)
		audit = [
			{"at": _iso(row[0]), "action": row[1], "actor": row[2], "note": row[3]}
			for row in cursor.fetchall()
		]
	application.pop("id", None)
	return {"application": application, "audit": audit}


def _decide(ctx, application_no, new_status, note):
	officer = _officer(ctx)
	if not application_no.strip():
		raise ValueError("application_no is required.")
	note = note.strip()
	if new_status == "REJECTED" and not note:
		raise ValueError("A rejection reason is required.")
	if len(note) > 450:
		raise ValueError("The decision note must be 450 characters or fewer.")

	actor = "admin:%s" % officer
	with get_cursor(commit=True) as cursor:
		cursor.execute(
			"UPDATE applications SET status = %s, decided_at = NOW(), decided_by = %s "
			"WHERE application_no = %s AND status = 'PENDING' "
			"AND block = ANY(%s) "
			"RETURNING id, application_no, status",
			(new_status, officer, application_no.strip(), list(ALLOWED_BLOCKS)),
		)
		row = cursor.fetchone()
		if row is None:
			raise ValueError("Only a pending application can be decided.")
		cursor.execute(
			"INSERT INTO audit_log (application_id, action, actor, note, at) "
			"VALUES (%s, %s, %s, %s, NOW())",
			(row[0], new_status, actor, note),
		)
	return {"application_no": row[1], "status": row[2]}


@mcp.tool()
def approve_application(ctx: Context, application_no: str, decision_note: str = "") -> dict:
	"""Approve an authenticated officer's pending application."""
	return _decide(ctx, application_no, "APPROVED", decision_note)


@mcp.tool()
def reject_application(ctx: Context, application_no: str, rejection_reason: str) -> dict:
	"""Reject an authenticated officer's pending application with a reason."""
	return _decide(ctx, application_no, "REJECTED", rejection_reason)


@mcp.tool()
def get_audit_history(ctx: Context, application_no: str) -> dict:
	"""Return chronological audit events for an application."""
	_officer(ctx)
	if not application_no.strip():
		raise ValueError("application_no is required.")
	with get_cursor() as cursor:
		cursor.execute(
			"SELECT a.at, a.action, a.actor, a.note FROM audit_log a "
			"JOIN applications p ON p.id = a.application_id "
			"WHERE p.application_no = %s AND p.block = ANY(%s) "
			"ORDER BY a.at ASC, a.id ASC",
			(application_no.strip(), list(ALLOWED_BLOCKS)),
		)
		audit = [
			{"at": _iso(row[0]), "action": row[1], "actor": row[2], "note": row[3]}
			for row in cursor.fetchall()
		]
	return {"application_no": application_no.strip(), "audit": audit}


if __name__ == "__main__":
	mcp.settings.host = os.getenv("MCP_HOST", "0.0.0.0")
	mcp.settings.port = int(os.getenv("MCP_PORT", "8102"))
	mcp.run(transport="streamable-http")
