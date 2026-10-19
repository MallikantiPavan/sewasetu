"""Simulated SMS Gateway for Render deployment.

Stores messages in memory and serves them via API so users can retrieve OTPs.
"""

import json
import os
import time
from flask import Flask, jsonify, request

app = Flask(__name__)

# In-memory message store
MESSAGES = []


@app.route("/api/messages")
def get_messages():
    """Get messages for a specific mobile number."""
    to = request.args.get("to", "")
    return jsonify([m for m in MESSAGES if m.get("to") == to])


@app.route("/api/send", methods=["POST"])
def send_message():
    """Store a message (called by the portal)."""
    data = request.json
    data["received_at"] = time.time()
    MESSAGES.append(data)
    return jsonify({"status": "queued", "id": len(MESSAGES) - 1})


@app.route("/api/all")
def get_all_messages():
    """Get all messages (for debugging)."""
    return jsonify(MESSAGES)


@app.route("/")
def index():
    return "SMS Gateway is running. Use /api/messages?to=<mobile> to retrieve OTPs."


@app.route("/healthz")
def health():
    return jsonify({"status": "ok"})


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8025))
    app.run(host="0.0.0.0", port=port)
