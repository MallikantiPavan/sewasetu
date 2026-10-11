"""Citizen-facing MCP server for the Sewa Setu portal."""

import os

import jwt
import requests
from mcp.server.fastmcp import Context, FastMCP

from db import get_cursor


mcp = FastMCP("Sewa Setu Citizen Assistant")

APPLICATION_COLUMNS = (
    "application_no, applicant_name, mobile, dob, village, block, "
    "bank_account, ifsc, status, submitted_at, decided_at"
)


def _iso(value):
    return value.isoformat() if value is not None else None


def _application(row):
    if row is None:
        return None
    values = dict(zip(
        ("application_no", "applicant_name", "mobile", "dob", "village", "block",
         "bank_account", "ifsc", "status", "submitted_at", "decided_at"),
        row,
    ))
    values["dob"] = _iso(values["dob"])
    values["submitted_at"] = _iso(values["submitted_at"])
    values["decided_at"] = _iso(values["decided_at"])
    # Bank details are not needed to answer status questions.
    values.pop("bank_account", None)
    values.pop("ifsc", None)
    return values


def _citizen_mobile(ctx: Context):
    """Validate the portal JWT and return its citizen subject."""
    request = ctx.request_context.request
    header = request.headers.get("authorization", "")
    if not header.lower().startswith("bearer "):
        raise ValueError("A citizen access token is required.")

    token = header[7:].strip()
    issuer = os.getenv("OAUTH_ISSUER", "http://localhost:8000").rstrip("/")
    audience = os.getenv("MCP_AUDIENCE", "http://localhost:8101")
    response = requests.get(issuer + "/.well-known/jwks.json", timeout=5)
    response.raise_for_status()
    keys = response.json().get("keys", [])
    header_data = jwt.get_unverified_header(token)
    jwk = next((key for key in keys if key.get("kid") == header_data.get("kid")), None)
    if jwk is None:
        raise ValueError("The access token is not valid for this service.")

    try:
        claims = jwt.decode(
            token,
            jwt.algorithms.RSAAlgorithm.from_jwk(jwk),
            algorithms=["RS256"],
            audience=audience,
            issuer=issuer,
        )
    except jwt.PyJWTError as exc:
        raise ValueError("The citizen access token is invalid or expired.") from exc

    subject = claims.get("sub", "")
    scope = claims.get("scope")
    if claims.get("role") != "citizen" or scope != "citizen" or not subject.startswith("citizen:"):
        raise ValueError("This endpoint accepts citizen authorization only.")
    return subject.split(":", 1)[1]


@mcp.tool()
def get_application_status(ctx: Context) -> dict:
    """Return the authenticated citizen's current pension applications."""
    mobile = _citizen_mobile(ctx)
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT " + APPLICATION_COLUMNS +
            " FROM applications WHERE mobile = %s ORDER BY submitted_at DESC",
            (mobile,),
        )
        applications = [_application(row) for row in cursor.fetchall()]
    return {"applications": applications}


@mcp.tool()
def get_application_details(ctx: Context, application_no: str) -> dict:
    """Return one application only when it belongs to the authenticated citizen."""
    mobile = _citizen_mobile(ctx)
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT " + APPLICATION_COLUMNS +
            " FROM applications WHERE application_no = %s AND mobile = %s",
            (application_no, mobile),
        )
        application = _application(cursor.fetchone())
    if application is None:
        raise ValueError("Application not found.")
    return {"application": application}


@mcp.tool()
def get_required_documents() -> dict:
    """List documents required by the pension portal."""
    return {
        "documents": [
            {
                "name": "Age proof",
                "description": "A JPG, PNG, or PDF document proving the applicant is at least 60.",
                "maximum_size_mb": 5,
            }
        ],
        "other_information": ["Applicant details", "Address and village", "Bank account and IFSC"],
    }


@mcp.tool()
def withdraw_application(ctx: Context, application_no: str, reason: str = "") -> dict:
    """Withdraw the authenticated citizen's pending application."""
    mobile = _citizen_mobile(ctx)
    with get_cursor(commit=True) as cursor:
        cursor.execute(
            "UPDATE applications SET status = 'WITHDRAWN', decided_at = NOW(), "
            "decided_by = 'APPLICANT' WHERE application_no = %s AND mobile = %s "
            "AND status = 'PENDING' RETURNING id, application_no",
            (application_no, mobile),
        )
        row = cursor.fetchone()
        if row is None:
            raise ValueError("Only your pending application can be withdrawn.")
        note = "applicant:%s" % mobile
        if reason.strip():
            note += " - " + reason.strip()[:450]
        cursor.execute(
            "INSERT INTO audit_log (application_id, action, actor, note, at) "
            "VALUES (%s, 'WITHDRAW', %s, %s, NOW())",
            (row[0], note, "citizen:%s" % mobile),
        )
    return {"application_no": row[1], "status": "WITHDRAWN"}


if __name__ == "__main__":
    mcp.settings.host = os.getenv("MCP_HOST", "0.0.0.0")
    mcp.settings.port = int(os.getenv("MCP_PORT", "8101"))
    mcp.run(transport="streamable-http")

