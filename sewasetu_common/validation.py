"""Shared scheme validation for Sewa Setu.

Both the Flask portal and the MCP servers import from this module so that
no channel admits an application another channel would refuse.
"""

import os
import re
from datetime import datetime
from zoneinfo import ZoneInfo

IST = ZoneInfo("Asia/Kolkata")


def now_ist():
    return datetime.now(IST).replace(tzinfo=None)


def _getenv_int(key, default):
    try:
        return int(os.environ.get(key, default))
    except (TypeError, ValueError):
        return default


# Scheme rules — single source of truth.
MIN_AGE = _getenv_int("MIN_AGE", 60)
SLA_DAYS = _getenv_int("SLA_DAYS", 15)
SCHEME_DEADLINE = datetime.strptime(
    os.environ.get("SCHEME_DEADLINE", "2026-10-31 23:59"), "%Y-%m-%d %H:%M"
)
ALL_BLOCKS = ["Sonari", "Rajapara", "Dhemaji Pathar", "Borgaon", "Namti", "Khelua"]

# Statuses that count as "active" (one per mobile at a time).
ACTIVE_STATUSES = ("PENDING", "APPROVED", "DEEMED_APPROVED")

# Document rules.
MAX_DOCUMENT_BYTES = 5 * 1024 * 1024
ALLOWED_DOCUMENT_EXTENSIONS = ("pdf", "jpg", "jpeg", "png")


def sanitize(value, maxlen=100):
    if value is None:
        return ""
    return value.strip()[:maxlen]


def parse_dob(raw):
    try:
        return datetime.strptime((raw or "").strip(), "%d/%m/%Y").date()
    except (ValueError, AttributeError):
        return None


def age_on(dob, on=None):
    if on is None:
        on = now_ist().date()
    return on.year - dob.year - ((on.month, on.day) < (dob.month, dob.day))


def allowed_blocks():
    """Blocks this channel may accept (subset of ALL_BLOCKS)."""
    raw = os.environ.get("MCP_ALLOWED_BLOCKS", "")
    if raw:
        return tuple(b.strip() for b in raw.split(",") if b.strip())
    return tuple(ALL_BLOCKS)


def validate_application(data, doc_path, blocks=None):
    """Validate a complete application. Returns (errors, cleaned).

    `errors` is a list of plain-language problems (empty when valid);
    `cleaned` holds the normalised values ready for insertion.
    """
    if blocks is None:
        blocks = ALL_BLOCKS
    errors = []
    cleaned = {
        "applicant_name": sanitize(data.get("applicant_name")),
        "village": (data.get("village") or "").strip(),
        "block": (data.get("block") or "").strip(),
        "gender": data.get("gender") or "",
        "marital_status": data.get("marital_status") or "",
        "husband_name": (data.get("husband_name") or "").strip(),
        "husband_employer": "",
        "bank_account": re.sub(r"[\s-]", "", data.get("bank_account") or ""),
        "ifsc": re.sub(r"[\s-]", "", (data.get("ifsc") or "")).upper(),
        "doc_path": doc_path or "",
        "dob": None,
    }
    for label, key in (("full name", "applicant_name"), ("village", "village"),
                       ("block", "block"), ("bank account", "bank_account")):
        if not cleaned[key]:
            errors.append("%s is required" % label)
    if cleaned["block"] and cleaned["block"] not in blocks:
        errors.append("block must be one of: " + ", ".join(blocks))
    if cleaned["bank_account"] and not re.fullmatch(r"\d{9,18}", cleaned["bank_account"]):
        errors.append("bank account number must be 9 to 18 digits")
    if cleaned["ifsc"] and not re.fullmatch(r"[A-Z]{4}0[A-Z0-9]{6}", cleaned["ifsc"]):
        errors.append("IFSC must be 11 characters, e.g. SBIN0003077")
    dob = parse_dob(data.get("dob"))
    if dob is None:
        errors.append("date of birth must be given as DD/MM/YYYY")
    else:
        cleaned["dob"] = dob
        if age_on(dob) < MIN_AGE:
            errors.append("applicant must be %d years of age or above" % MIN_AGE)
    if not cleaned["doc_path"]:
        errors.append("age proof document is required")
    if now_ist() > SCHEME_DEADLINE:
        errors.append("the application window has closed")
    return errors, cleaned


def hash_password(p):
    import hashlib
    return hashlib.sha256(p.encode("utf-8")).hexdigest()
