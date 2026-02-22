"""
MT4 Multi-Account Monitor - Central Server
Deploy free on: Render.com or Railway.app
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime
import json
import os

app = Flask(__name__)
CORS(app)

# In-memory store: { "account_id": { ...data... } }
accounts = {}

# Optional: simple API key protection
API_KEY = os.environ.get("API_KEY", "mt4monitor2024")

# ─────────────────────────────────────────────
# POST /report  ← EA sends data here
# ─────────────────────────────────────────────
@app.route("/report", methods=["POST"])
def receive_report():
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    data = request.get_json(silent=True)
    if not data:
        return jsonify({"error": "invalid json"}), 400

    account_id = str(data.get("account_id", "unknown"))
    data["last_update"] = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    accounts[account_id] = data

    return jsonify({"status": "ok", "account_id": account_id}), 200


# ─────────────────────────────────────────────
# GET /accounts  ← Dashboard reads from here
# ─────────────────────────────────────────────
@app.route("/accounts", methods=["GET"])
def get_accounts():
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    return jsonify({
        "count":    len(accounts),
        "accounts": list(accounts.values())
    }), 200


# ─────────────────────────────────────────────
# GET /health  ← check server is alive
# ─────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":   "online",
        "accounts": len(accounts),
        "time":     datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S UTC")
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"MT4 Monitor Server running on port {port}")
    app.run(host="0.0.0.0", port=port)
