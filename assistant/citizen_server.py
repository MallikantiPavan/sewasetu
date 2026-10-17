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
from sewasetu_common.validation import (
    ACTIVE_STATUSES,
    ALLOWED_DOCUMENT_EXTENSIONS,
    MAX_DOCUMENT_BYTES,
    SCHEME_DEADLINE,
    age_on,
    allowed_blocks,
    hash_password,
    now_ist,
    validate_application,
)


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
        validate_token_resource=False,
    ),
)

APPLICATION_COLUMNS = (
    "application_no, applicant_name, mobile, dob, village, block, "
    "bank_account, ifsc, status, submitted_at, decided_at"
)
ALLOWED_BLOCKS = allowed_blocks()
UPLOAD_DIR = os.getenv("UPLOAD_DIR", "/var/sewasetu/uploads")
SMS_GATEWAY_URL = os.getenv("SMS_GATEWAY_URL", "http://smsgw:8025")


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


def _send_sms(mobile, text):
    """Send an SMS via the simulated gateway (best-effort)."""
    try:
        import requests
        requests.post(SMS_GATEWAY_URL + "/api/send",
                      json={"to": mobile, "text": text}, timeout=5)
    except Exception:
        pass


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
    """Validate and submit a pension application for the authenticated citizen.

    Uses the same validation rules as the portal (sewasetu_common.validation).
    """
    mobile = _citizen_mobile(ctx)

    # Decode and save the document first so validation can check the path.
    suffix = (age_proof_filename or "").lower().rsplit(".", 1)[-1]
    if suffix not in ALLOWED_DOCUMENT_EXTENSIONS:
        raise ValueError("age proof must be a JPG, PNG, or PDF")
    try:
        document = base64.b64decode(age_proof_base64, validate=True)
    except (ValueError, TypeError):
        document = b""
        raise ValueError("age proof content must be valid base64")
    if not document:
        raise ValueError("age proof document is required")
    if len(document) > MAX_DOCUMENT_BYTES:
        raise ValueError("age proof must be no larger than 5 MB")

    Path(UPLOAD_DIR).mkdir(parents=True, exist_ok=True)
    path = Path(UPLOAD_DIR) / ("%s_%s.%s" % (mobile, uuid.uuid4().hex, suffix))
    path.write_bytes(document)

    # Build the data dict for shared validation.
    data = {
        "applicant_name": applicant_name,
        "dob": dob,
        "village": village,
        "block": block,
        "bank_account": bank_account,
        "ifsc": ifsc,
        "gender": gender,
        "marital_status": marital_status,
        "husband_name": husband_name,
    }
    errors, cleaned = validate_application(data, str(path), blocks=ALLOWED_BLOCKS)
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
        application_no = "SSP%s%06d" % (now_ist().strftime("%y"), uuid.uuid4().int % 1000000)
        cursor.execute(
            "INSERT INTO applications "
            "(application_no, applicant_name, mobile, dob, gender, marital_status, "
            "husband_name, husband_employer, village, block, bank_account, ifsc, "
            "doc_path, status, submitted_at) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'PENDING',NOW()) "
            "RETURNING id",
            (application_no, cleaned["applicant_name"], mobile, cleaned["dob"],
             cleaned["gender"], cleaned["marital_status"], cleaned["husband_name"], "",
             cleaned["village"], cleaned["block"], cleaned["bank_account"], cleaned["ifsc"],
             str(path)),
        )
        application_id = cursor.fetchone()[0]
        cursor.execute(
            "INSERT INTO audit_log (application_id, action, actor, note, at) "
            "VALUES (%s, 'SUBMIT', %s, '', NOW())",
            (application_id, "applicant:%s" % mobile),
        )
        cursor.execute("SELECT count(*) FROM portal_users WHERE mobile = %s", (mobile,))
        if cursor.fetchone()[0] == 0:
            password_hash = hash_password(cleaned["dob"].strftime("%d%m%Y"))
            cursor.execute(
                "INSERT INTO portal_users (mobile, password_hash) VALUES (%s, %s)",
                (mobile, password_hash),
            )

    _send_sms(mobile, "Sewa Setu: application %s received. Track at the status portal "
                     "with mobile no. and password (DOB as DDMMYYYY)." % application_no)
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
