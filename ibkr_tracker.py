import requests
import csv
import time
import json
import os
from io import StringIO
from datetime import datetime
import gspread
from google.oauth2.service_account import Credentials

# ── CONFIG ──────────────────────────────────────────────────────────────────
IBKR_TOKEN    = os.environ.get("IBKR_TOKEN")
IBKR_QUERY_ID = os.environ.get("IBKR_QUERY_ID")
SHEET_ID       = os.environ.get("GOOGLE_SHEET_ID")
SERVICE_ACCOUNT_JSON = os.environ.get("GOOGLE_SERVICE_ACCOUNT_JSON")

SEND_URL = f"https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.SendRequest?t={IBKR_TOKEN}&q={IBKR_QUERY_ID}&v=3"
GET_URL  = f"https://gdcdyn.interactivebrokers.com/Universal/servlet/FlexStatementService.GetStatement?t={IBKR_TOKEN}&q={IBKR_QUERY_ID}&v=3"

# ── STEP 1: FETCH IBKR DATA ──────────────────────────────────────────────────
def fetch_ibkr_csv():
    print("Step 1: Sending request to IBKR Flex...")
    resp = requests.get(SEND_URL, timeout=30)
    
    # Parse XML response
    text = resp.text
    if "<Status>Fail</Status>" in text:
        error_code = text.split("<ErrorCode>")[1].split("</ErrorCode>")[0]
        error_msg  = text.split("<ErrorMessage>")[1].split("</ErrorMessage>")[0]
        raise Exception(f"IBKR Error {error_code}: {error_msg}")
    
    ref_code = text.split("<ReferenceCode>")[1].split("</ReferenceCode>")[0]
    print(f"Reference code: {ref_code}. Waiting 15 seconds...")
    time.sleep(15)
    
    print("Step 2: Fetching statement...")
    get_resp = requests.get(f"{GET_URL}&referenceCode={ref_code}", timeout=60)
    csv_text = get_resp.text
    
    if csv_text.strip().startswith("<"):
        if "<Status>Fail</Status>" in csv_text:
            error_code = csv_text.split("<ErrorCode>")[1].split("</ErrorCode>")[0]
            error_msg  = csv_text.split("<ErrorMessage>")[1].split("</ErrorMessage>")[0]
            raise Exception(f"IBKR GetStatement Error {error_code}: {error_msg}")
        raise Exception("IBKR returned XML instead of CSV")
    
    print("CSV data received successfully.")
    return csv_text

# ── STEP 2: PARSE CSV ────────────────────────────────────────────────────────
def parse_ibkr_csv(csv_text):
    reader = csv.reader(StringIO(csv_text))
    rows = list(reader)
    
    nav_data       = {}
    open_positions = []
    realized_pnl   = {}
    trades         = []

    for row in rows:
        if len(row) < 3:
            continue

        # Change in NAV
        if row[0] == "Change in NAV" and row[1] == "Data":
            nav_data[row[2]] = row[3]

        # Open Positions
        if (row[0] == "Open Positions" and row[1] == "Data"
                and row[2] == "Summary" and row[3] == "Stocks"):
            try:
                open_positions.append({
                    "symbol":       row[5],
                    "qty":          float(row[6]),
                    "cost_price":   float(row[8]),
                    "cost_basis":   float(row[9]),
                    "close_price":  float(row[10]),
                    "market_value": float(row[11]),
                    "unrealized":   float(row[12]),
                })
            except (IndexError, ValueError):
                pass

        # Realized PnL
        if (row[0] == "Realized & Unrealized Performance Summary"
                and row[1] == "Data" and row[3] == "Stocks"
                and row[2] not in ("Total", "Header")):
            try:
                symbol = row[4]
                realized = float(row[11]) if row[11] else 0
                if symbol and symbol != "Total":
                    realized_pnl[symbol] = realized
            except (IndexError, ValueError):
                pass

        # Trades
        if (row[0] == "Trades" and row[1] == "Data"
                and row[2] == "Order" and row[3] == "Stocks"):
            try:
                trades.append({
                    "symbol":   row[5],
                    "date":     row[6],
                    "qty":      float(row[7]),
                    "price":    float(row[8]),
                    "proceeds": float(row[10]),
                    "comm":     float(row[11]),
                })
            except (IndexError, ValueError):
                pass

    return nav_data, open_positions, realized_pnl, trades

# ── STEP 3: WRITE TO GOOGLE SHEETS ──────────────────────────────────────────
def write_to_sheets(nav_data, open_positions, realized_pnl, trades):
    print("Connecting to Google Sheets...")
    
    creds_dict = json.loads(SERVICE_ACCOUNT_JSON)
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive"
    ]
    creds = Credentials.from_service_account_info(creds_dict, scopes=scopes)
    gc    = gspread.authorize(creds)
    wb    = gc.open_by_key(SHEET_ID)
    
    updated_at = datetime.now().strftime("%d %b %Y %H:%M SGT")

    # ── TAB 1: PnL SUMMARY ──────────────────────────────────────────────────
    try:
        ws = wb.worksheet("PnL Summary")
        ws.clear()
    except:
        ws = wb.add_worksheet("PnL Summary", rows=200, cols=8)

    total_deposits   = float(nav_data.get("Deposits & Withdrawals", 0))
    dividends        = float(nav_data.get("Dividends", 0))
    commissions      = float(nav_data.get("Commissions", 0))
    ending_nav       = float(nav_data.get("Ending Value", 0))
    total_mval       = sum(p["market_value"] for p in open_positions)
    total_unrealized = sum(p["unrealized"]   for p in open_positions)
    total_realized   = sum(realized_pnl.values())
    cash_balance     = ending_nav - total_mval

    summary_data = [
        ["IBKR Portfolio PnL Summary", "", "", "", "", "", "", ""],
        [f"Last Updated: {updated_at}", "", "", "", "", "", "", ""],
        [""],
        ["ACCOUNT OVERVIEW", "USD"],
        ["Total Deposits",           round(total_deposits, 2)],
        ["Cash Balance",             round(cash_balance, 2)],
        ["Stock Portfolio Value",    round(total_mval, 2)],
        ["Total NAV",                round(ending_nav, 2)],
        ["Dividends Received",       round(dividends, 2)],
        ["Commissions Paid",         round(commissions, 2)],
        [""],
        ["PnL SUMMARY", "USD"],
        ["Total Realized P&L",       round(total_realized, 2)],
        ["Total Unrealized P&L",     round(total_unrealized, 2)],
        ["Net P&L (Realized + Unrealized)", round(total_realized + total_unrealized, 2)],
        ["Net P&L % on Deposits",   round((total_realized + total_unrealized) / total_deposits * 100, 2) if total_deposits else 0],
        [""],
        ["OPEN POSITIONS", "", "", "", "", "", "", ""],
        ["Symbol", "Qty", "Avg Cost (USD)", "Price Jul 31 (USD)", "Cost Basis (USD)", "Market Value (USD)", "Unrealized P&L (USD)", "Gain %"],
    ]

    for p in sorted(open_positions, key=lambda x: x["unrealized"], reverse=True):
        gain_pct = round((p["close_price"] - p["cost_price"]) / p["cost_price"] * 100, 2) if p["cost_price"] else 0
        summary_data.append([
            p["symbol"],
            round(p["qty"], 4),
            round(p["cost_price"], 2),
            round(p["close_price"], 2),
            round(p["cost_basis"], 2),
            round(p["market_value"], 2),
            round(p["unrealized"], 2),
            f"{gain_pct}%"
        ])

    # Totals row
    summary_data.append([
        "TOTAL", "",  "", "",
        round(sum(p["cost_basis"]   for p in open_positions), 2),
        round(total_mval, 2),
        round(total_unrealized, 2),
        ""
    ])

    ws.update("A1", summary_data)

    # ── TAB 2: REALIZED PnL ─────────────────────────────────────────────────
    try:
        ws2 = wb.worksheet("Realized PnL")
        ws2.clear()
    except:
        ws2 = wb.add_worksheet("Realized PnL", rows=100, cols=4)

    realized_data = [
        ["REALIZED P&L — CLOSED / PARTIAL POSITIONS", "", "", ""],
        [f"Last Updated: {updated_at}", "", "", ""],
        [""],
        ["Symbol", "Realized P&L (USD)", "Status", ""],
    ]
    for symbol, pnl in sorted(realized_pnl.items(), key=lambda x: x[1]):
        if pnl != 0:
            status = "Loss" if pnl < 0 else "Gain"
            realized_data.append([symbol, round(pnl, 2), status, ""])
    
    realized_data.append(["TOTAL", round(total_realized, 2), "", ""])
    ws2.update("A1", realized_data)

    # ── TAB 3: TRADE LOG ────────────────────────────────────────────────────
    try:
        ws3 = wb.worksheet("Trade Log")
        ws3.clear()
    except:
        ws3 = wb.add_worksheet("Trade Log", rows=500, cols=6)

    trade_data = [
        ["TRADE LOG", "", "", "", "", ""],
        [f"Last Updated: {updated_at}", "", "", "", "", ""],
        [""],
        ["Symbol", "Date", "Qty", "Price (USD)", "Proceeds (USD)", "Commission (USD)"],
    ]
    for t in trades:
        trade_data.append([
            t["symbol"],
            t["date"],
            round(t["qty"], 4),
            round(t["price"], 2),
            round(t["proceeds"], 2),
            round(t["comm"], 4),
        ])
    ws3.update("A1", trade_data)

    print(f"Google Sheets updated successfully at {updated_at}")
    print(f"NAV: ${ending_nav:.2f} | Unrealized: ${total_unrealized:.2f} | Realized: ${total_realized:.2f}")

# ── MAIN ─────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    print("=== IBKR Portfolio Tracker ===")
    csv_text = fetch_ibkr_csv()
    nav_data, open_positions, realized_pnl, trades = parse_ibkr_csv(csv_text)
    write_to_sheets(nav_data, open_positions, realized_pnl, trades)
    print("=== Done ===")
