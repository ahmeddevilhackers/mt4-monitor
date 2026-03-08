"""
MT4 Multi-Account Monitor - Central Server v2.3
- Cent account support (USC/USc → divide by 100)
- Telegram alerts for dangerous margin levels
- Auto-cleanup: removes accounts with balance < MIN_BALANCE (default $5)
- Daily & cumulative profit tracking per account
Deploy free on: Render.com or Railway.app
"""

from flask import Flask, request, jsonify
from flask_cors import CORS
from datetime import datetime, timezone
import os
import urllib.request
import urllib.parse
import threading
import time

app = Flask(__name__)
CORS(app)

# In-memory store
accounts = {}

# ─────────────────────────────────────────────
# PROFIT TRACKING
# ─────────────────────────────────────────────
# daily_snapshots[account_id] = {
#   "date": "YYYY-MM-DD",          ← اليوم اللي اتاخد فيه الـ snapshot
#   "start_balance": float,        ← البالانس أول اليوم
# }
daily_snapshots = {}

# cumulative_profit[account_id] = float   ← الأرباح المتراكمة من أول يوم
cumulative_profit = {}

# previous_balance[account_id] = float    ← آخر بالانس اتسجل (لحساب الأرباح المحققة)
previous_balance = {}

def update_profit_tracking(account_id, balance):
    """Track daily and cumulative profit based on balance changes."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # ── Initialize if first time ──
    if account_id not in daily_snapshots:
        daily_snapshots[account_id] = {
            "date": today,
            "start_balance": balance
        }
        cumulative_profit[account_id] = 0.0
        previous_balance[account_id] = balance
        return

    # ── New day? Save yesterday's profit and reset snapshot ──
    if daily_snapshots[account_id]["date"] != today:
        yesterday_start = daily_snapshots[account_id]["start_balance"]
        yesterday_end   = previous_balance.get(account_id, balance)
        day_profit      = yesterday_end - yesterday_start
        cumulative_profit[account_id] = cumulative_profit.get(account_id, 0) + day_profit

        daily_snapshots[account_id] = {
            "date": today,
            "start_balance": balance
        }

    previous_balance[account_id] = balance

# Config
API_KEY        = os.environ.get("API_KEY",          "mt4monitor2024")
TELEGRAM_TOKEN = os.environ.get("TELEGRAM_TOKEN",   "")
TELEGRAM_CHAT  = os.environ.get("TELEGRAM_CHAT_ID", "")
DANGER_ML      = float(os.environ.get("DANGER_ML",  "150"))
WARN_ML        = float(os.environ.get("WARN_ML",    "250"))
MIN_BALANCE    = float(os.environ.get("MIN_BALANCE", "5.0"))

# Alert tracker
alerted = {}

# ─────────────────────────────────────────────
# CENT ACCOUNT CONVERTER
# ─────────────────────────────────────────────
CENT_CURRENCIES = {"USC", "USc", "usc", "cent", "CENT", "ZAc", "GBp"}

def normalize_account(data):
    currency = data.get("currency", "USD")
    if currency in CENT_CURRENCIES:
        data["is_cent"]     = True
        data["balance"]     = round(data.get("balance",    0) / 100, 2)
        data["equity"]      = round(data.get("equity",     0) / 100, 2)
        data["margin"]      = round(data.get("margin",     0) / 100, 2)
        data["free_margin"] = round(data.get("free_margin",0) / 100, 2)
        data["floating"]    = round(data.get("floating",   0) / 100, 2)
        for b in data.get("baskets", []):
            b["buy_profit"]  = round(b.get("buy_profit",  0) / 100, 2)
            b["sell_profit"] = round(b.get("sell_profit", 0) / 100, 2)
            b["net_profit"]  = round(b.get("net_profit",  0) / 100, 2)
        data["currency_display"] = "USD (¢)"
    else:
        data["is_cent"]          = False
        data["currency_display"] = currency
    return data

# ─────────────────────────────────────────────
# TELEGRAM
# ─────────────────────────────────────────────
def send_telegram(message):
    if not TELEGRAM_TOKEN or not TELEGRAM_CHAT:
        return
    try:
        url  = f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage"
        data = urllib.parse.urlencode({
            "chat_id":    TELEGRAM_CHAT,
            "text":       message,
            "parse_mode": "HTML"
        }).encode()
        urllib.request.urlopen(urllib.request.Request(url, data), timeout=5)
    except Exception as e:
        print(f"Telegram error: {e}")

# ─────────────────────────────────────────────
# BACKGROUND THREAD: alerts + cleanup
# ─────────────────────────────────────────────
def background_tasks():
    while True:
        time.sleep(60)

        for acc_id in list(accounts.keys()):
            acc = accounts.get(acc_id)
            if not acc:
                continue

            # ── AUTO CLEANUP: zero balance ────────────────
            balance = acc.get("balance", 0)
            if balance < MIN_BALANCE:
                print(f"Auto-removing low balance account: {acc_id} (balance={balance})")
                accounts.pop(acc_id, None)
                alerted.pop(acc_id, None)
                daily_snapshots.pop(acc_id, None)
                cumulative_profit.pop(acc_id, None)
                previous_balance.pop(acc_id, None)
                continue

            # ── MARGIN ALERTS ─────────────────────────────
            ml     = acc.get("margin_level", 0)
            bal    = acc.get("balance",  0)
            eq     = acc.get("equity",   0)
            broker = acc.get("broker",   "")
            cur    = acc.get("currency_display", "USD")

            if ml <= 0:
                continue

            if ml < DANGER_ML:
                if alerted.get(acc_id) != "danger":
                    alerted[acc_id] = "danger"
                    send_telegram(
                        f"🔴 <b>DANGER — {acc_id}</b>\n"
                        f"Broker: {broker}\n"
                        f"Margin Level: <b>{ml:.1f}%</b>\n"
                        f"Balance: {bal:.2f} {cur}\n"
                        f"Equity:  {eq:.2f} {cur}\n"
                        f"⚠️ Take action immediately!"
                    )
            elif ml < WARN_ML:
                if alerted.get(acc_id) != "warn":
                    alerted[acc_id] = "warn"
                    send_telegram(
                        f"🟡 <b>WARNING — {acc_id}</b>\n"
                        f"Broker: {broker}\n"
                        f"Margin Level: <b>{ml:.1f}%</b>\n"
                        f"Balance: {bal:.2f} {cur}\n"
                        f"Equity:  {eq:.2f} {cur}"
                    )
            else:
                if alerted.get(acc_id) in ("danger", "warn"):
                    alerted[acc_id] = "ok"
                    send_telegram(
                        f"✅ <b>RECOVERED — {acc_id}</b>\n"
                        f"Margin Level: <b>{ml:.1f}%</b>\n"
                        f"Account is now safe."
                    )

threading.Thread(target=background_tasks, daemon=True).start()

# ─────────────────────────────────────────────
# POST /report
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

    # ── Skip zero balance accounts ──────────────
    balance = data.get("balance", 0)
    if balance < MIN_BALANCE:
        return jsonify({"status": "skipped", "reason": f"balance {balance} below minimum {MIN_BALANCE}"}), 200

    data["last_update"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    data = normalize_account(data)

    # ── Track profit (use normalized balance for cent accounts) ──
    update_profit_tracking(account_id, data.get("balance", 0))

    # ── Inject profit data into account ──
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    snap  = daily_snapshots.get(account_id, {})
    start_bal   = snap.get("start_balance", data.get("balance", 0))
    daily_prof  = data.get("balance", 0) - start_bal
    cumul_prof  = cumulative_profit.get(account_id, 0) + daily_prof

    data["daily_profit"]      = round(daily_prof, 2)
    data["cumulative_profit"] = round(cumul_prof, 2)
    data["day_start_balance"] = round(start_bal, 2)

    accounts[account_id] = data

    return jsonify({"status": "ok", "account_id": account_id}), 200


# ─────────────────────────────────────────────
# GET /accounts
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
# DELETE /account/<id>  ← حذف يدوي
# ─────────────────────────────────────────────
@app.route("/account/<account_id>", methods=["DELETE"])
def delete_account(account_id):
    key = request.headers.get("X-API-Key", "")
    if key != API_KEY:
        return jsonify({"error": "unauthorized"}), 401

    if account_id in accounts:
        accounts.pop(account_id)
        alerted.pop(account_id, None)
        daily_snapshots.pop(account_id, None)
        cumulative_profit.pop(account_id, None)
        previous_balance.pop(account_id, None)
        return jsonify({"status": "deleted", "account_id": account_id}), 200
    return jsonify({"error": "not found"}), 404


# ─────────────────────────────────────────────
# GET /health
# ─────────────────────────────────────────────
@app.route("/health", methods=["GET"])
def health():
    return jsonify({
        "status":   "online",
        "accounts": len(accounts),
        "telegram": "configured" if TELEGRAM_TOKEN else "not set",
        "time":     datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    }), 200


if __name__ == "__main__":
    port = int(os.environ.get("PORT", 5000))
    print(f"MT4 Monitor Server v2.3 running on port {port}")
    app.run(host="0.0.0.0", port=port)
