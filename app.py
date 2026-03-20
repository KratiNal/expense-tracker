from flask import Flask, render_template, request, jsonify, send_file
import sqlite3
import csv
import io
from datetime import datetime, date
import os

app = Flask(__name__)
DB = "expenses.db"

# ── Categories & default budgets ──────────────────────────────────────────────
CATEGORIES = ["groceries", "food", "transport", "bills", "health", "shopping", "education", "other"]

DEFAULT_BUDGETS = {
    "groceries": 8000,
    "food":      4000,
    "transport": 3000,
    "bills":     5000,
    "health":    2000,
    "shopping":  3000,
    "education": 2000,
    "other":     2000,
}

# ── Database setup ────────────────────────────────────────────────────────────
def get_db():
    conn = sqlite3.connect(DB)
    conn.row_factory = sqlite3.Row
    return conn

def init_db():
    conn = get_db()
    conn.executescript("""
        CREATE TABLE IF NOT EXISTS expenses (
            id        INTEGER PRIMARY KEY AUTOINCREMENT,
            amount    REAL    NOT NULL,
            category  TEXT    NOT NULL,
            note      TEXT,
            logged_by TEXT,
            ts        TEXT    DEFAULT (datetime('now','localtime'))
        );
        CREATE TABLE IF NOT EXISTS budgets (
            category TEXT PRIMARY KEY,
            amount   REAL NOT NULL
        );
    """)
    # Seed default budgets if empty
    for cat, amt in DEFAULT_BUDGETS.items():
        conn.execute(
            "INSERT OR IGNORE INTO budgets (category, amount) VALUES (?, ?)",
            (cat, amt)
        )
    conn.commit()
    conn.close()

# ── Routes ────────────────────────────────────────────────────────────────────
@app.route("/")
def index():
    return render_template("index.html", categories=CATEGORIES)

@app.route("/api/expenses", methods=["GET"])
def get_expenses():
    conn = get_db()
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    rows = conn.execute(
        "SELECT * FROM expenses WHERE strftime('%Y-%m', ts) = ? ORDER BY ts DESC",
        (month,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/expenses", methods=["POST"])
def add_expense():
    data = request.json
    amount    = float(data["amount"])
    category  = data["category"]
    note      = data.get("note", "")
    logged_by = data.get("logged_by", "You")

    conn = get_db()
    conn.execute(
        "INSERT INTO expenses (amount, category, note, logged_by) VALUES (?, ?, ?, ?)",
        (amount, category, note, logged_by)
    )
    conn.commit()

    # Return updated spent for this category
    month = datetime.now().strftime("%Y-%m")
    spent = conn.execute(
        "SELECT COALESCE(SUM(amount), 0) as total FROM expenses "
        "WHERE category=? AND strftime('%Y-%m', ts)=?",
        (category, month)
    ).fetchone()["total"]

    budget = conn.execute(
        "SELECT amount FROM budgets WHERE category=?", (category,)
    ).fetchone()["amount"]

    conn.close()
    return jsonify({"success": True, "spent": spent, "budget": budget})

@app.route("/api/expenses/<int:expense_id>", methods=["DELETE"])
def delete_expense(expense_id):
    conn = get_db()
    conn.execute("DELETE FROM expenses WHERE id=?", (expense_id,))
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/summary")
def summary():
    conn = get_db()
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))

    spent_rows = conn.execute(
        "SELECT category, SUM(amount) as total FROM expenses "
        "WHERE strftime('%Y-%m', ts)=? GROUP BY category",
        (month,)
    ).fetchall()
    spent_map = {r["category"]: r["total"] for r in spent_rows}

    budgets = conn.execute("SELECT * FROM budgets").fetchall()
    budget_map = {r["category"]: r["amount"] for r in budgets}

    conn.close()

    result = []
    for cat in CATEGORIES:
        result.append({
            "category": cat,
            "spent":    round(spent_map.get(cat, 0), 2),
            "budget":   budget_map.get(cat, DEFAULT_BUDGETS.get(cat, 2000)),
        })
    return jsonify(result)

@app.route("/api/budgets", methods=["GET"])
def get_budgets():
    conn = get_db()
    rows = conn.execute("SELECT * FROM budgets").fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

@app.route("/api/budgets", methods=["POST"])
def update_budget():
    data = request.json
    conn = get_db()
    conn.execute(
        "INSERT OR REPLACE INTO budgets (category, amount) VALUES (?, ?)",
        (data["category"], float(data["amount"]))
    )
    conn.commit()
    conn.close()
    return jsonify({"success": True})

@app.route("/api/export")
def export_csv():
    month = request.args.get("month", datetime.now().strftime("%Y-%m"))
    conn = get_db()
    rows = conn.execute(
        "SELECT ts, amount, category, note, logged_by FROM expenses "
        "WHERE strftime('%Y-%m', ts)=? ORDER BY ts",
        (month,)
    ).fetchall()
    conn.close()

    output = io.StringIO()
    writer = csv.writer(output)
    writer.writerow(["Date", "Amount (INR)", "Category", "Note", "Logged By"])
    for r in rows:
        writer.writerow([r["ts"], r["amount"], r["category"], r["note"], r["logged_by"]])

    output.seek(0)
    return send_file(
        io.BytesIO(output.getvalue().encode()),
        mimetype="text/csv",
        as_attachment=True,
        download_name=f"expenses_{month}.csv"
    )

@app.route("/api/today")
def today_expenses():
    conn = get_db()
    today = date.today().isoformat()
    rows = conn.execute(
        "SELECT * FROM expenses WHERE date(ts)=? ORDER BY ts DESC", (today,)
    ).fetchall()
    conn.close()
    return jsonify([dict(r) for r in rows])

if __name__ == "__main__":
    init_db()
    app.run(host="0.0.0.0", port=int(os.environ.get("PORT", 5000)), debug=False)
    