"""Citizen-facing MCP server for the Sewa Setu portal."""

import os
import base64
import hashlib
import re
import uuid
from datetime import datetime
from pathlib import Path

from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import Context, FastMCP

import auth
from db import get_cursor


MCP_RESOURCE = (
    os.getenv("MCP_AUDIENCE", "http://localhost:8101").split(",")[0].strip().rstrip("/")
)

mcp = FastMCP(
    "Sewa Setu Citizen Assistant",
    token_verifier=auth.PortalTokenVerifier(MCP_RESOURCE),
    auth=AuthSettings(
        issuer_url=auth.issuer(),
        resource_server_url=MCP_RESOURCE,
        required_scopes=["citizen"],
        # The verifier checks the token's audience against the portal issuer and
        # this server's URL itself, so the transport need not re-check it.
        validate_token_resource=False,
    ),
)

APPLICATION_COLUMNS = (
    "application_no, applicant_name, mobile, dob, village, block, "
    "bank_account, ifsc, status, submitted_at, decided_at"
)
ALLOWED_BLOCKS = tuple(
    block.strip() for block in os.getenv("MCP_ALLOWED_BLOCKS", "Sonari").split(",")
    if block.strip()
)
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/sewasetu/uploads")
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
SCHEME_DEADLINE = datetime.strptime(
    os.getenv("SCHEME_DEADLINE", "2026-10-31 23:59"), "%Y-%m-%d %H:%M"
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
    """Return the authenticated citizen's mobile number from the access token."""
    claims = auth.authenticate(ctx.request_context.request, MCP_RESOURCE, "citizen")
    return claims["sub"].split(":", 1)[1]


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
def get_form_guidance() -> dict:
    """Explain how to complete the pension application form."""
    return {
        "steps": [
            {
                "step": 1,
                "title": "Personal details",
                "fields": ["Applicant name", "Date of birth", "Gender", "Marital status"],
                "guidance": "Enter the applicant's details exactly as shown on the age proof.",
            },
            {
                "step": 2,
                "title": "Address",
                "fields": ["Village", "Block"],
                "guidance": "Choose the correct village and block where the applicant lives.",
            },
            {
                "step": 3,
                "title": "Bank details",
                "fields": ["Bank account number", "IFSC code"],
                "guidance": "Enter an account belonging to the applicant and check every digit before continuing.",
            },
            {
                "step": 4,
                "title": "Age proof",
                "fields": ["Age-proof document"],
                "guidance": "Upload one clear JPG, PNG, or PDF file no larger than 5 MB.",
            },
            {
                "step": 5,
                "title": "Review and declaration",
                "fields": ["Application review", "Declaration"],
                "guidance": "Review all details, correct mistakes, and submit only after confirming the declaration.",
            },
        ],
        "validation_rules": [
            "The applicant must be at least 60 years old.",
            "All required personal, address, and bank fields must be completed.",
            "An age-proof document is required.",
            "A mobile number cannot have another active pending or approved application.",
            "The application must be for an allowed block: %s." % ", ".join(ALLOWED_BLOCKS),
        ],
        "safety_note": "Do not share OTPs, passwords, or full bank details in chat.",
    }


@mcp.tool()
def submit_application(
    ctx: Context,
    applicant_name: str,
    dob: str,
    village: str,
    block: str,
    bank_account: str,
    ifsc: str,
    age_proof_filename: str,
    age_proof_base64: str,
    gender: str = "",
    marital_status: str = "",
    husband_name: str = "",
) -> dict:
    """Validate and submit a pension application for the authenticated citizen."""
    mobile = _citizen_mobile(ctx)
    applicant_name = applicant_name.strip()[:100]
    village = village.strip()
    block = block.strip()
    bank_account = re.sub(r"[\s-]", "", bank_account or "")
    ifsc = re.sub(r"[\s-]", "", ifsc or "").upper()
    errors = []
    if not applicant_name:
        errors.append("full name is required")
    if not village:
        errors.append("village is required")
    if not block:
        errors.append("block is required")
    elif block not in ALLOWED_BLOCKS:
        errors.append("block is not supported by this assistant")
    if not re.fullmatch(r"\d{9,18}", bank_account):
        errors.append("bank account number must be 9 to 18 digits")
    if not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", ifsc):
        errors.append("IFSC must be 11 characters, e.g. SBIN0003077")
    try:
        birth_date = datetime.strptime(dob.strip(), "%d/%m/%Y").date()
    except (AttributeError, ValueError):
        birth_date = None
        errors.append("date of birth must use DD/MM/YYYY")
    if birth_date:
        today = datetime.now().date()
        age = today.year - birth_date.year - ((today.month, today.day) < (birth_date.month, birth_date.day))
        if age < 60:
            errors.append("applicant must be 60 years of age or above")
    if datetime.now() > SCHEME_DEADLINE:
        errors.append("the application window has closed")
    suffix = (age_proof_filename or "").lower().rsplit(".", 1)[-1]
    if suffix not in ("pdf", "jpg", "jpeg", "png"):
        errors.append("age proof must be a JPG, PNG, or PDF")
    try:
        document = base64.b64decode(age_proof_base64, validate=True)
    except (ValueError, TypeError):
        document = b""
        errors.append("age proof content must be valid base64")
    if not document:
        errors.append("age proof document is required")
    elif len(document) > MAX_DOCUMENT_BYTES:
        errors.append("age proof must be no larger than 5 MB")
    if errors:
        raise ValueError("; ".join(errors))

    with get_cursor(commit=True) as cursor:
        cursor.execute(
            "SELECT application_no, status FROM applications "
            "WHERE mobile = %s AND status IN ('PENDING', 'APPROVED', 'DEEMED_APPROVED') "
            "ORDER BY submitted_at DESC LIMIT 1",
            (mobile,),
        )
        existing = cursor.fetchone()
        if existing:
            raise ValueError("An active application already exists for this mobile number.")
        Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
        path = Path(UPLOAD_DIR) / ("%s_%s.%s" % (mobile, uuid.uuid4().hex, suffix))
        path.write_bytes(document)
        application_no = "SSP%s%06d" % (datetime.now().strftime("%y"), uuid.uuid4().int % 1000000)
        cursor.execute(
            "INSERT INTO applications "
            "(application_no, applicant_name, mobile, dob, gender, marital_status, "
            "husband_name, husband_employer, village, block, bank_account, ifsc, "
            "doc_path, status, submitted_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',NOW()) "
            "RETURNING id",
            (application_no, applicant_name, mobile, birth_date, gender, marital_status,
             husband_name.strip(), "", village, block, bank_account, ifsc, str(path)),
        )
        application_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO audit_log (application_id, action, actor, note, at) "
            "VALUES (%s, 'SUBMIT', %s, '', NOW())",
            (application_id, "applicant:%s" % mobile),
        )
        cursor.execute("SELECT count(*) FROM portal_users WHERE mobile = %s", (mobile,))
        if cursor.fetchone()[0] == 0:
            password_hash = hashlib.sha256(
                birth_date.strftime("%d%m%Y").encode("utf-8")
            ).hexdigest()
            cursor.execute(
                "INSERT INTO portal_users (mobile, password_hash) VALUES (%s, %s)",
                (mobile, password_hash),
            )
    return {"application_no": application_no, "status": "PENDING", "block": block}


@mcp.tool()
def get_connected_applications(ctx: Context) -> dict:
    """List active third-party applications connected to the citizen account."""
    mobile = _citizen_mobile(ctx)
    subject = "citizen:%s" % mobile
    with get_cursor() as cursor:
        cursor.execute(
            "SELECT client_name, client_id, created_at, expires_at "
            "FROM oauth_refresh_tokens "
            "WHERE subject = %s AND role = 'citizen' AND scope = 'citizen' "
            "AND revoked_at IS NULL AND expires_at > NOW() "
            "ORDER BY created_at DESC",
            (subject,),
        )
        connections = [
            {
                "client_name": row[0],
                "client_id": row[1],
                "created_at": _iso(row[2]),
                "expires_at": _iso(row[3]),
            }
            for row in cursor.fetchall()
        ]
    return {"connections": connections}


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

