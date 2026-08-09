import requests
import csv
import time
import json
import os
from io import StringIO
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ── CONFIG ───────────────────────────────────────────────────────────────────
IBKR_TOKEN           = os.environ.get("IBKR_TOKEN")
IBKR_QUERY_ID        = os.environ.get("IBKR_QUERY_ID")
SHEET_ID             = os.environ.get("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

SEND_URL = (
    f"https://gdcdyn.interactivebrokers.com/Universal/servlet/"
    f"FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={IBKR_QUERY_ID}&v=3"
)

# ── STEP 1: FETCH CSV FROM IBKR ──────────────────────────────────────────────
def fetch_ibkr_csv():
    text = None
    for attempt in range(5):
        print(f"Step 1: SendRequest attempt {attempt + 1}/5...")
        resp = requests.get(SEND_URL, timeout=30)
        text = resp.text

        if "<Status>Success</Status>" in text:
            print("Step 1 success.")
            break

        if "<Status>Fail</Status>" in text:
            ec = text.split("<ErrorCode>")[1].split("</ErrorCode>")[0]
            em = text.split("<ErrorMessage>")[1].split("</ErrorMessage>")[0]
            print(f"Attempt {attempt+1} failed — {ec}: {em}")
            if ec == "1001" and attempt < 4:
                wait = 30 * (attempt + 1)
                print(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise Exception(f"IBKR SendRequest Error {ec}: {em}")

    if not text or "<Status>Success</Status>" not in text:
        raise Exception("Step 1 failed after 5 attempts")

    ref_code = text.split("<ReferenceCode>")[1].split("</ReferenceCode>")[0]
    print(f"Reference code: {ref_code}. Waiting 20s...")
    time.sleep(20)

    # Build GetStatement URL — IBKR documented format
    # Only token and reference code needed, no query ID
    get_url = (
        f"https://gdcdyn.interactivebrokers.com/Universal/servlet/"
        f"FlexStatementService.GetStatement"
        f"?t={IBKR_TOKEN}&q={ref_code}&v=3"
    )
    print(f"GetStatement URL constructed (token masked): ...GetStatement?t=***&q={ref_code}&v=3")

    for attempt in range(3):
        print(f"Step 2: GetStatement attempt {attempt+1}/3...")
        get_resp = requests.get(get_url, timeout=60)
        csv_text = get_resp.text

        if not csv_text.strip().startswith("<"):
            print("CSV received successfully.")
            return csv_text

        if "<Status>Fail</Status>" in csv_text:
            ec = csv_text.split("<ErrorCode>")[1].split("</ErrorCode>")[0]
            em = csv_text.split("<ErrorMessage>")[1].split("</ErrorMessage>")[0]
            print(f"Attempt {attempt+1} failed — {ec}: {em}")
            print(f"Full response: {csv_text[:300]}")
            if attempt < 2:
                wait = 20 * (attempt + 2)
                print(f"Retrying in {wait}s...")
                time.sleep(wait)
            else:
                raise Exception(f"IBKR GetStatement Error {ec}: {em}")

    raise Exception("Step 2 failed after 3 attempts")


# ── STEP 2: PARSE NEW FLEX FORMAT ────────────────────────────────────────────
def parse_ibkr_csv(csv_text):
    reader = csv.reader(StringIO(csv_text))
    rows   = list(reader)

    nav_data       = {}
    open_positions = []
    realized_pnl   = {}

    for row in rows:
        if len(row) < 3:
            continue
        kind    = row[0]
        section = row[1]

        # Change in NAV
        if kind == "DATA" and section == "CNAV":
            try:
                nav_data["Deposits & Withdrawals"] = float(row[15]) if row[15] else 0
                nav_data["Dividends"]              = float(row[25]) if row[25] else 0
                nav_data["WithholdingTax"]         = float(row[26]) if row[26] else 0
                nav_data["Commissions"]            = float(row[42]) if row[42] else 0
                nav_data["SalesTax"]               = float(row[50]) if row[50] else 0
                nav_data["Ending Value"]           = float(row[57]) if row[57] else 0
            except (IndexError, ValueError):
                pass

        # Open Positions
        if kind == "DATA" and section == "POST":
            try:
                if row[7] == "CASH" or row[39] != "SUMMARY":
                    continue
                open_positions.append({
                    "symbol":       row[9],
                    "qty":          float(row[30]),
                    "cost_price":   float(row[34]),
                    "cost_basis":   float(row[35]),
                    "close_price":  float(row[31]),
                    "market_value": float(row[32]),
                    "unrealized":   float(row[37]),
                })
            except (IndexError, ValueError):
                pass

        # Realized PnL
        if kind == "DATA" and section == "FIFO":
            try:
                if row[5] == "CASH" or row[9] in ("", "Total (All Assets)"):
                    continue
                pnl = float(row[32]) if row[32] else 0
                if pnl != 0:
                    realized_pnl[row[9]] = pnl
            except (IndexError, ValueError):
                pass

    return nav_data, open_positions, realized_pnl


# ── STEP 3: WRITE TO GOOGLE SHEETS ───────────────────────────────────────────
def write_to_sheets(nav_data, open_positions, realized_pnl):
    print("Connecting to Google Sheets...")

    creds_dict = json.loads(SERVICE_ACCOUNT_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive",
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc    = gspread.authorize(creds)
    wb    = gc.open_by_key(SHEET_ID)

    updated_at       = datetime.now().strftime("%d %b %Y %H:%M SGT")
    total_deposits   = float(nav_data.get("Deposits & Withdrawals", 0))
    dividends        = float(nav_data.get("Dividends", 0))
    commissions      = float(nav_data.get("Commissions", 0))
    ending_nav       = float(nav_data.get("Ending Value", 0))
    total_mval       = sum(p["market_value"] for p in open_positions)
    total_unrealized = sum(p["unrealized"]   for p in open_positions)
    total_realized   = sum(realized_pnl.values())
    cash_balance     = ending_nav - total_mval
    net_pnl          = total_realized + total_unrealized
    net_pnl_pct      = round(net_pnl / total_deposits * 100, 2) if total_deposits else 0

    # TAB 1: PnL Summary
    try:
        ws = wb.worksheet("PnL Summary")
        ws.clear()
    except Exception:
        ws = wb.add_worksheet("PnL Summary", rows=200, cols=8)

    summary_data = [
        ["IBKR Portfolio PnL Summary", "", "", "", "", "", "", ""],
        [f"Last Updated: {updated_at}", "", "", "", "", "", "", ""],
        [""],
        ["ACCOUNT OVERVIEW", "USD"],
        ["Total Deposits",         round(total_deposits, 2)],
        ["Cash Balance",           round(cash_balance, 2)],
        ["Stock Portfolio Value",  round(total_mval, 2)],
        ["Total NAV",              round(ending_nav, 2)],
        ["Dividends Received",     round(dividends, 2)],
        ["Commissions Paid",       round(commissions, 2)],
        [""],
        ["PnL SUMMARY", "USD"],
        ["Total Realized P&L",     round(total_realized, 2)],
        ["Total Unrealized P&L",   round(total_unrealized, 2)],
        ["Net P&L",                round(net_pnl, 2)],
        ["Net P&L % on Deposits",  f"{net_pnl_pct}%"],
        [""],
        ["OPEN POSITIONS", "", "", "", "", "", "", ""],
        ["Symbol", "Qty", "Avg Cost (USD)", "Current Price (USD)",
         "Cost Basis (USD)", "Market Value (USD)", "Unrealized P&L (USD)", "Gain %"],
    ]

    for p in sorted(open_positions, key=lambda x: x["unrealized"], reverse=True):
        gain_pct = (
            round((p["close_price"] - p["cost_price"]) / p["cost_price"] * 100, 2)
            if p["cost_price"] else 0
        )
        summary_data.append([
            p["symbol"],
            round(p["qty"], 4),
            round(p["cost_price"], 2),
            round(p["close_price"], 2),
            round(p["cost_basis"], 2),
            round(p["market_value"], 2),
            round(p["unrealized"], 2),
            f"{gain_pct}%",
        ])

    summary_data.append([
        "TOTAL", "", "", "",
        round(sum(p["cost_basis"] for p in open_positions), 2),
        round(total_mval, 2),
        round(total_unrealized, 2),
        "",
    ])
    ws.update("A1", summary_data)

    # TAB 2: Realized PnL
    try:
        ws2 = wb.worksheet("Realized PnL")
        ws2.clear()
    except Exception:
        ws2 = wb.add_worksheet("Realized PnL", rows=100, cols=3)

    realized_data = [
        ["REALIZED P&L — CLOSED / PARTIAL POSITIONS", "", ""],
        [f"Last Updated: {updated_at}", "", ""],
        [""],
        ["Symbol", "Realized P&L (USD)", "Status"],
    ]
    for symbol, pnl in sorted(realized_pnl.items(), key=lambda x: x[1]):
        realized_data.append([symbol, round(pnl, 2), "Loss" if pnl < 0 else "Gain"])
    realized_data.append(["TOTAL", round(total_realized, 2), ""])
    ws2.update("A1", realized_data)

    print(f"Sheets updated at {updated_at}")
    print(f"NAV: ${ending_nav:.2f} | Portfolio: ${total_mval:.2f} | "
          f"Unrealized: ${total_unrealized:.2f} | Realized: ${total_realized:.2f}")


# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== IBKR Portfolio Tracker ===")
    csv_text = fetch_ibkr_csv()
    nav_data, open_positions, realized_pnl = parse_ibkr_csv(csv_text)
    write_to_sheets(nav_data, open_positions, realized_pnl)
    print("=== Done ===")
