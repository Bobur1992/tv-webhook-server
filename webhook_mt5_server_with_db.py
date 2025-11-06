#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
webhook_mt5_server_with_db.py
TradingView → Server (queue) → MT5 EA bridge
Supports optional MySQL and Google Sheets logging.
Ready for Render/VPS deployment.
"""

import os
import json
import threading
from datetime import datetime
from flask import Flask, request, jsonify
import logging

# Optional imports
try:
    import mysql.connector
except Exception:
    mysql = None

try:
    import gspread
    from google.oauth2.service_account import Credentials
except Exception:
    gspread = None

# Load .env if present
try:
    from dotenv import load_dotenv
    load_dotenv()
except Exception:
    pass

# -------------------------
# Config from environment
# -------------------------
SECRET = os.getenv("TV_SECRET", "my_super_secret_ABC123")

# MySQL
MYSQL_HOST = os.getenv("MYSQL_HOST", "localhost")
MYSQL_PORT = int(os.getenv("MYSQL_PORT", "3306"))
MYSQL_USER = os.getenv("MYSQL_USER", "root")
MYSQL_PASS = os.getenv("MYSQL_PASS", "")
MYSQL_DB   = os.getenv("MYSQL_DB", "trading")

# Google Sheets
GOOGLE_CREDS_JSON = os.getenv("GOOGLE_CREDENTIALS_JSON", None)  # path or JSON string
GSHEET_ID = os.getenv("GSHEET_ID", None)
GSHEET_WORKSHEET = os.getenv("GSHEET_WORKSHEET", "Sheet1")

# Behavior flags
WRITE_TO_SHEET = os.getenv("WRITE_TO_SHEET", "false").lower() == "true"
WRITE_TO_DB    = os.getenv("WRITE_TO_DB", "false").lower() == "true"

# Logging setup
logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s: %(message)s")
log = logging.getLogger("tv-webhook-server")

app = Flask(__name__)

# In-memory queue
order_queue = []
queue_lock = threading.Lock()

# -------------------------
# DB helpers
# -------------------------
def get_db_conn():
    if mysql is None:
        raise RuntimeError("mysql-connector-python not installed")
    return mysql.connector.connect(
        host=MYSQL_HOST,
        port=MYSQL_PORT,
        user=MYSQL_USER,
        password=MYSQL_PASS,
        database=MYSQL_DB,
        autocommit=True
    )

def ensure_db():
    if not WRITE_TO_DB:
        return
    if mysql is None:
        log.warning("MySQL not installed, WRITE_TO_DB disabled.")
        return
    try:
        conn = mysql.connector.connect(host=MYSQL_HOST, port=MYSQL_PORT, user=MYSQL_USER, password=MYSQL_PASS, autocommit=True)
        cur = conn.cursor()
        cur.execute(f"CREATE DATABASE IF NOT EXISTS `{MYSQL_DB}`")
        cur.close()
        conn.close()
        conn = get_db_conn()
        cur = conn.cursor()
        cur.execute("""
        CREATE TABLE IF NOT EXISTS trades (
          id VARCHAR(128) PRIMARY KEY,
          action VARCHAR(16),
          symbol VARCHAR(64),
          sl DOUBLE,
          tp DOUBLE,
          volume DOUBLE,
          message TEXT,
          status VARCHAR(32),
          created_at DATETIME,
          sent_to_ea_at DATETIME,
          executed_at DATETIME,
          extra JSON
        ) ENGINE=InnoDB DEFAULT CHARSET=utf8mb4;
        """)
        conn.commit()
        cur.close()
        conn.close()
        log.info("DB ensured")
    except Exception as e:
        log.exception("Failed to ensure DB: %s", e)

# -------------------------
# Google Sheets helpers
# -------------------------
gc = None
sheet = None
if WRITE_TO_SHEET:
    if gspread is None:
        log.warning("gspread not installed, WRITE_TO_SHEET disabled.")
        WRITE_TO_SHEET = False
    else:
        try:
            if GOOGLE_CREDS_JSON is None:
                raise ValueError("GOOGLE_CREDS_JSON not set")
            if os.path.exists(GOOGLE_CREDS_JSON):
                creds = Credentials.from_service_account_file(GOOGLE_CREDS_JSON, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            else:
                creds_dict = json.loads(GOOGLE_CREDS_JSON)
                creds = Credentials.from_service_account_info(creds_dict, scopes=["https://www.googleapis.com/auth/spreadsheets"])
            gc = gspread.Client(auth=creds)
            gc.session = gc.session
            sh = gc.open_by_key(GSHEET_ID)
            sheet = sh.worksheet(GSHEET_WORKSHEET)
            log.info("Connected to Google Sheet '%s' worksheet '%s'", GSHEET_ID, GSHEET_WORKSHEET)
        except Exception as e:
            log.exception("Google Sheets init failed: %s", e)
            WRITE_TO_SHEET = False

if WRITE_TO_DB:
    try:
        ensure_db()
    except Exception as e:
        log.exception("ensure_db failed: %s", e)

# -------------------------
# Queue helpers
# -------------------------
def add_order_to_queue(trade):
    with queue_lock:
        order_queue.append(trade)
    try:
        if WRITE_TO_DB:
            insert_trade_db(trade)
        if WRITE_TO_SHEET:
            append_sheet_row(trade, event="queued")
    except Exception as e:
        log.warning("Data persistence failed: %s", e)

def get_next_order():
    with queue_lock:
        return order_queue[0] if order_queue else None

def pop_order():
    with queue_lock:
        return order_queue.pop(0) if order_queue else None

def ack_order(order_id):
    with queue_lock:
        for i, o in enumerate(order_queue):
            if o.get("id") == order_id:
                order_queue.pop(i)
                return True
    return False

# -------------------------
# DB / Sheet operations
# -------------------------
def insert_trade_db(trade):
    if not WRITE_TO_DB:
        return
    conn = get_db_conn()
    cur = conn.cursor()
    sql = """
    INSERT INTO trades (id, action, symbol, sl, tp, volume, message, status, created_at, extra)
    VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)
    """
    now = datetime.utcnow()
    cur.execute(sql, (
        trade["id"],
        trade.get("action"),
        trade.get("symbol"),
        trade.get("sl"),
        trade.get("tp"),
        trade.get("volume", 0),
        trade.get("message", ""),
        "queued",
        now,
        json.dumps(trade.get("extra", {}))
    ))
    conn.commit()
    cur.close()
    conn.close()

def update_trade_status(trade_id, status_field):
    if not WRITE_TO_DB:
        return
    conn = get_db_conn()
    cur = conn.cursor()
    now = datetime.utcnow()
    cur.execute("UPDATE trades SET status=%s, executed_at=%s WHERE id=%s", (status_field, now, trade_id))
    conn.commit()
    cur.close()
    conn.close()

def append_sheet_row(trade, event="queued"):
    if not WRITE_TO_SHEET or sheet is None:
        return
    now_str = datetime.utcnow().strftime("%Y-%m-%d %H:%M:%S")
    row = [
        trade.get("id"),
        event,
        trade.get("action"),
        trade.get("symbol"),
        str(trade.get("volume", "")),
        str(trade.get("sl", "")),
        str(trade.get("tp", "")),
        trade.get("message", ""),
        now_str
    ]
    try:
        sheet.append_row(row, value_input_option="USER_ENTERED")
    except Exception as e:
        log.warning("append_row failed: %s", e)

# -------------------------
# Flask routes
# -------------------------
@app.route("/", methods=["GET"])
def index():
    return "✅ TV → MT5 webhook server is running", 200

@app.route("/webhook", methods=["POST"])
def webhook():
    try:
        data = request.get_json(force=True)
    except Exception:
        return jsonify({"status":"error","message":"invalid json"}), 400

    if data.get("secret") != SECRET:
        log.warning("Invalid secret received: %s", data.get("secret"))
        return jsonify({"status":"error","message":"unauthorized"}), 403

    trade = {
        "id": str(data.get("id", f"tv-{int(datetime.utcnow().timestamp())}")),
        "action": str(data.get("action", "")).upper(),
        "symbol": data.get("symbol"),
        "sl": float(data.get("sl")) if data.get("sl") else None,
        "tp": float(data.get("tp")) if data.get("tp") else None,
        "volume": float(data.get("volume", 0)),
        "message": data.get("message", ""),
        "extra": data.get("extra", {})
    }

    if not trade["action"] or not trade["symbol"]:
        return jsonify({"status":"error","message":"missing action or symbol"}), 400

    add_order_to_queue(trade)
    log.info("New signal queued: %s %s id=%s", trade["action"], trade["symbol"], trade["id"])
    return jsonify({"status":"ok","id":trade["id"]}), 200

@app.route("/pending", methods=["GET"])
def pending():
    if request.args.get("secret") != SECRET:
        return jsonify({"status":"unauthorized"}), 403

    order = get_next_order()
    if order:
        update_trade_status(order["id"], "sent_to_ea")
        append_sheet_row(order, event="sent_to_ea")
        log.info("Sent to EA id=%s", order["id"])
        return jsonify(order), 200
    else:
        return "", 204

@app.route("/pending/ack", methods=["GET"])
def ack():
    if request.args.get("secret") != SECRET:
        return jsonify({"status":"unauthorized"}), 403

    order_id = request.args.get("id")
    if not order_id:
        return jsonify({"status":"error","message":"id required"}), 400

    if ack_order(order_id):
        update_trade_status(order_id, "executed")
        append_sheet_row({"id": order_id}, event="executed")
        log.info("Order acked id=%s", order_id)
        return jsonify({"status":"ok"}), 200
    else:
        return jsonify({"status":"not found"}), 404

# -------------------------
# Run server
# -------------------------
if __name__ == "__main__":
    port = int(os.getenv("PORT", "10000"))
    app.run(host="0.0.0.0", port=port)
