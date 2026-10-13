import unittest
from datetime import date, datetime
from unittest.mock import Mock, patch

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parents[1] / "assistant"))

import citizen_server  # pyright: ignore[reportMissingImports]
import officer_server  # pyright: ignore[reportMissingImports]


class CursorContext:
    def __init__(self, rows):
        self.rows = rows
        self.executed = []

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc_value, traceback):
        return False

    def execute(self, query, parameters=()):
        self.executed.append((query, parameters))

    def fetchall(self):
        return self.rows

    def fetchone(self):
        return self.rows[0] if self.rows else None


class McpServerTests(unittest.TestCase):
    def test_citizen_application_redacts_bank_details(self):
        row = (
            "APP-1", "Asha", "9999999999", date(1960, 1, 1), "Rampur", "East",
            "123456789", "IFSC0001", "PENDING", datetime(2026, 1, 1), None,
        )
        result = citizen_server._application(row)
        self.assertNotIn("bank_account", result)
        self.assertNotIn("ifsc", result)
        self.assertEqual(result["application_no"], "APP-1")

    def test_officer_application_only_exposes_document_presence(self):
        row = (
            1, "APP-1", "Asha", "9999999999", date(1960, 1, 1), "Rampur", "East",
            "PENDING", datetime(2026, 1, 1), None, None, "/uploads/secret.pdf",
        )
        result = officer_server._application(row)
        self.assertTrue(result["document_uploaded"])
        self.assertNotIn("doc_path", result)
        self.assertEqual(result["id"], 1)

    def test_connected_applications_never_returns_token_hash(self):
        context = Mock()
        cursor = CursorContext([("Portal helper", "client-1", datetime(2026, 1, 1), datetime(2026, 2, 1))])
        with patch.object(citizen_server, "_citizen_mobile", return_value="9999999999"), \
             patch.object(citizen_server, "get_cursor", return_value=cursor):
            result = citizen_server.get_connected_applications(context)
        self.assertEqual(result["connections"][0]["client_id"], "client-1")
        self.assertNotIn("token_hash", result["connections"][0])
        self.assertIn("citizen:9999999999", cursor.executed[0][1])

    def test_officer_date_validation(self):
        self.assertEqual(officer_server._parse_date("2026-01-31", "date_from"), date(2026, 1, 31))
        with self.assertRaises(ValueError):
            officer_server._parse_date("31-01-2026", "date_from")

    def test_rejection_requires_reason(self):
        context = Mock()
        with patch.object(officer_server, "_officer", return_value="block-officer"):
            with self.assertRaisesRegex(ValueError, "rejection reason"):
                officer_server._decide(context, "APP-1", "REJECTED", " ")

    def test_submission_rejects_underage_and_unsupported_block_before_database(self):
        context = Mock()
        with patch.object(citizen_server, "_citizen_mobile", return_value="9999999999"), \
             patch.object(citizen_server, "get_cursor") as get_cursor:
            with self.assertRaises(ValueError) as raised:
                citizen_server.submit_application(
                    context, "Asha", "01/01/1970", "Rampur", "Rajapara",
                    "123456789", "SBIN0003077", "proof.pdf", "cGRm",
                )
        self.assertIn("60 years", str(raised.exception))
        self.assertIn("block is not supported", str(raised.exception))
        get_cursor.assert_not_called()


if __name__ == "__main__":
    unittest.main()
