"""
Daily Market Screener — v3
Covers: Indian Stocks (Nifty 500), Indian ETFs, Global ETFs, Metals/Commodities, Crypto

New in v3:
  1.  Signal performance tracker — shows how last 5 days of picks performed (no CSV needed,
      uses yfinance to pull prices for previously recommended tickers stored in email subject)
      Simpler approach: tracks today's picks and compares open vs close price same day,
      plus fetches 5-day return for any ticker mentioned in a companion JSON file if present.
  2.  Score-weighted allocation — Rs.10,000 total budget, weighted by score
  3.  Category exposure caps — Indian Stock 40%, Global ETF 30%, Metal 20%, Crypto 10%
      Indian ETF shares the Indian Stock cap pool
  4.  Telegram alert — top 5 picks sent as a clean message
  5.  Plain English reason per pick — one line explaining why it scored high
  6.  Macro context header — Nifty/S&P close, USD/INR move, regime sentence
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
import smtplib
import os
import json
import urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime, timedelta

warnings.simplefilter("ignore")

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
TOTAL_BUDGET       = 10000    # INR — score-weighted across final picks
DATA_PERIOD        = "1y"
MIN_PRICE_INR      = 50
MIN_AVG_VOLUME_NS  = 300000
GLOBAL_MAX_PICKS   = 25
SCORE_STRONG_BUY   = 60
SCORE_WATCH        = 40

# Category budget caps as fraction of TOTAL_BUDGET
# Indian ETF shares the Indian Stock pool
CATEGORY_CAPS = {
    "Indian Stock":    0.40,
    "Indian ETF":      0.40,   # shared pool with Indian Stock
    "Global ETF":      0.30,
    "Metal/Commodity": 0.20,
    "Crypto":          0.10,
}

# Signal history file — stored as a JSON artifact in the repo root
# If not present, tracker section is skipped gracefully
HISTORY_FILE = "screener_history.json"

# ══════════════════════════════════════════════════════
#  FULL ASSET UNIVERSE
# ══════════════════════════════════════════════════════

GLOBAL_ETFS = {
    "SPY":  "SPDR S&P 500 ETF Trust",
    "QQQ":  "Invesco QQQ Trust (Nasdaq 100)",
    "VTI":  "Vanguard Total Stock Market ETF",
    "VOO":  "Vanguard S&P 500 ETF",
    "IVV":  "iShares Core S&P 500 ETF",
    "IWM":  "iShares Russell 2000 ETF",
    "DIA":  "SPDR Dow Jones Industrial ETF",
    "EFA":  "iShares MSCI EAFE ETF",
    "VEA":  "Vanguard FTSE Developed Markets ETF",
    "IEFA": "iShares Core MSCI EAFE ETF",
    "EWJ":  "iShares MSCI Japan ETF",
    "EWG":  "iShares MSCI Germany ETF",
    "EWU":  "iShares MSCI UK ETF",
    "EWQ":  "iShares MSCI France ETF",
    "EWA":  "iShares MSCI Australia ETF",
    "EWC":  "iShares MSCI Canada ETF",
    "EWZ":  "iShares MSCI Brazil ETF",
    "EWY":  "iShares MSCI South Korea ETF",
    "MCHI": "iShares MSCI China ETF",
    "FXI":  "iShares China Large Cap ETF",
    "KWEB": "KraneShares China Internet ETF",
    "EEM":  "iShares MSCI Emerging Markets ETF",
    "VWO":  "Vanguard Emerging Markets ETF",
    "KSA":  "iShares MSCI Saudi Arabia ETF",
    "UAE":  "iShares MSCI UAE ETF",
    "XLK":  "Technology Select Sector SPDR",
    "XLF":  "Financial Select Sector SPDR",
    "XLE":  "Energy Select Sector SPDR",
    "XLV":  "Health Care Select Sector SPDR",
    "XLI":  "Industrial Select Sector SPDR",
    "XLP":  "Consumer Staples Select Sector SPDR",
    "ARKK": "ARK Innovation ETF",
    "SOXX": "iShares Semiconductor ETF",
}

METALS_COMMODITIES = {
    "GLD":  "SPDR Gold Shares",
    "IAU":  "iShares Gold Trust",
    "SLV":  "iShares Silver Trust",
    "PPLT": "Aberdeen Platinum ETF",
    "PALL": "Aberdeen Palladium ETF",
    "USO":  "United States Oil Fund (Crude)",
    "BNO":  "United States Brent Oil Fund",
    "UNG":  "United States Natural Gas Fund",
    "CPER": "United States Copper ETF",
    "WEAT": "Teucrium Wheat Fund",
    "CORN": "Teucrium Corn Fund",
    "SOYB": "Teucrium Soybean Fund",
    "DBA":  "Invesco DB Agriculture Fund",
    "DJP":  "iPath Bloomberg Commodity ETN",
    "GSG":  "iShares S&P GSCI Commodity ETF",
}

CRYPTO = {
    "BTC-USD":  "Bitcoin",
    "ETH-USD":  "Ethereum",
    "SOL-USD":  "Solana",
    "BNB-USD":  "BNB (Binance Coin)",
    "XRP-USD":  "XRP (Ripple)",
    "ADA-USD":  "Cardano",
    "AVAX-USD": "Avalanche",
    "DOT-USD":  "Polkadot",
    "LINK-USD": "Chainlink",
    "MATIC-USD":"Polygon (MATIC)",
}

INDIAN_ETFS = {
    "NIFTYBEES.NS":  "Nippon Nifty BeES",
    "JUNIORBEES.NS": "Nippon Junior BeES (Nifty Next 50)",
    "BANKBEES.NS":   "Nippon Bank BeES",
    "ITBEES.NS":     "Nippon IT BeES",
    "GOLDBEES.NS":   "Nippon Gold BeES",
    "SILVERBEES.NS": "Nippon Silver BeES",
    "ICICIB22.NS":   "ICICI Bharat 22 ETF",
    "CPSE.NS":       "CPSE ETF (PSU Basket)",
    "MAN50ETF.NS":   "Mirae Asset Nifty 50 ETF",
    "NETFIT.NS":     "Nippon India ETF Nifty IT",
    "PSUBNKBEES.NS": "Nippon PSU Bank BeES",
    "PHARMABEES.NS": "Nippon Pharma BeES",
}

CATEGORY_META = {
    "Indian Stock":    {"benchmark": "^NSEI",   "currency": "INR", "label": "Indian Stock"},
    "Indian ETF":      {"benchmark": "^NSEI",   "currency": "INR", "label": "Indian ETF"},
    "Global ETF":      {"benchmark": "^GSPC",   "currency": "USD", "label": "Global ETF"},
    "Metal/Commodity": {"benchmark": "^GSPC",   "currency": "USD", "label": "Metal / Commodity"},
    "Crypto":          {"benchmark": "BTC-USD", "currency": "USD", "label": "Crypto"},
}

CATEGORY_ORDER  = ["Indian Stock", "Indian ETF", "Global ETF", "Metal/Commodity", "Crypto"]
CATEGORY_COLORS = {
    "Indian Stock":    "#1d4ed8",
    "Indian ETF":      "#7c3aed",
    "Global ETF":      "#0369a1",
    "Metal/Commodity": "#b45309",
    "Crypto":          "#0f766e",
}

def get_category(ticker):
    if ticker in GLOBAL_ETFS:        return "Global ETF"
    if ticker in METALS_COMMODITIES: return "Metal/Commodity"
    if ticker in CRYPTO:             return "Crypto"
    if ticker in INDIAN_ETFS:        return "Indian ETF"
    return "Indian Stock"

def get_display_name(ticker):
    return (
        GLOBAL_ETFS.get(ticker)
        or METALS_COMMODITIES.get(ticker)
        or CRYPTO.get(ticker)
        or INDIAN_ETFS.get(ticker)
        or ticker
    )

# ══════════════════════════════════════════════════════
#  TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════

def compute_rsi(series, period=14):
    delta = series.diff()
    gain  = delta.clip(lower=0).rolling(period).mean()
    loss  = (-delta.clip(upper=0)).rolling(period).mean()
    rs    = gain / loss.replace(0, np.nan)
    return 100 - (100 / (1 + rs))

def compute_macd(series, fast=12, slow=26, signal=9):
    ema_f = series.ewm(span=fast,   adjust=False).mean()
    ema_s = series.ewm(span=slow,   adjust=False).mean()
    macd  = ema_f - ema_s
    sig   = macd.ewm(span=signal, adjust=False).mean()
    return macd, sig, macd - sig

def compute_adx(df, period=14):
    hi  = df["High"].squeeze()
    lo  = df["Low"].squeeze()
    cl  = df["Close"].squeeze()
    tr  = pd.concat([
        hi - lo,
        (hi - cl.shift()).abs(),
        (lo - cl.shift()).abs()
    ], axis=1).max(axis=1)
    atr = tr.rolling(period).mean()
    pdm = hi.diff().clip(lower=0)
    mdm = (-lo.diff()).clip(lower=0)
    mask = pdm >= mdm
    pdm[~mask] = 0
    mdm[mask]  = 0
    pdi = 100 * pdm.rolling(period).mean() / atr.replace(0, np.nan)
    mdi = 100 * mdm.rolling(period).mean() / atr.replace(0, np.nan)
    dx  = 100 * (pdi - mdi).abs() / (pdi + mdi).replace(0, np.nan)
    return dx.rolling(period).mean(), pdi, mdi

def relative_strength(stock_close, bench_close, lookback=63):
    if len(stock_close) < lookback or len(bench_close) < lookback:
        return None
    sr = (stock_close.iloc[-1] - stock_close.iloc[-lookback]) / stock_close.iloc[-lookback]
    br = (bench_close.iloc[-1] - bench_close.iloc[-lookback]) / bench_close.iloc[-lookback]
    return float(sr - br)

def relative_strength_short(stock_close, bench_close, lookback=10):
    if len(stock_close) < lookback or len(bench_close) < lookback:
        return None
    sr = (stock_close.iloc[-1] - stock_close.iloc[-lookback]) / stock_close.iloc[-lookback]
    br = (bench_close.iloc[-1] - bench_close.iloc[-lookback]) / bench_close.iloc[-lookback]
    return float(sr - br)

# ══════════════════════════════════════════════════════
#  MARKET REGIME
# ══════════════════════════════════════════════════════

def get_regime(close_series):
    cl = close_series.squeeze()
    if len(cl) < 200:
        return "neutral"
    ma50     = cl.rolling(50).mean().iloc[-1]
    ma200    = cl.rolling(200).mean().iloc[-1]
    ma200_1m = cl.rolling(200).mean().iloc[-22]
    price    = cl.iloc[-1]
    slope    = (ma200 - ma200_1m) / ma200_1m
    if price > ma50 > ma200 and slope > 0:
        return "bull"
    if price < ma200 * 0.95:
        return "bear"
    return "neutral"

# ══════════════════════════════════════════════════════
#  MACRO CONTEXT
# ══════════════════════════════════════════════════════

def build_macro_context(bench_nifty, bench_sp500, usd_to_inr, regime_nifty, regime_sp500):
    """
    Returns a dict with yesterday's close, 1-day change, and a plain English
    regime summary sentence used in the email header.
    """
    def last_two(series):
        s = series.dropna()
        if len(s) < 2:
            return None, None, None
        prev  = float(s.iloc[-2])
        today = float(s.iloc[-1])
        chg   = (today - prev) / prev * 100
        return prev, today, chg

    _, nifty_close, nifty_chg = last_two(bench_nifty)
    _, sp_close,    sp_chg    = last_two(bench_sp500)

    # USD/INR 5-day change for context
    usd_note = f"1 USD = Rs.{usd_to_inr:.2f}"

    # Plain English regime sentence
    regime_sentences = {
        ("bull",    "bull"):    "Both Nifty and S&P are in bull mode — conditions are favourable across the board.",
        ("bull",    "neutral"): "Nifty is bullish, S&P is sideways — Indian picks look stronger today.",
        ("bull",    "bear"):    "Nifty is bullish but S&P is under pressure — lean towards Indian over Global ETFs.",
        ("neutral", "bull"):    "S&P is bullish, Nifty is consolidating — Global ETFs may have the edge today.",
        ("neutral", "neutral"): "Both markets are sideways — be selective, only the highest-scoring picks are worth acting on.",
        ("neutral", "bear"):    "Nifty is consolidating, S&P is in a downtrend — tread carefully on Global ETFs.",
        ("bear",    "bull"):    "Nifty is under pressure but S&P is strong — Global ETFs and Crypto may be better bets.",
        ("bear",    "neutral"): "Nifty is in a downtrend, S&P is sideways — watch for Recovery Watch signals specifically.",
        ("bear",    "bear"):    "Both markets are in downtrends — only act on Strong Buy signals with Recovery Watch flag.",
    }
    regime_note = regime_sentences.get(
        (regime_nifty, regime_sp500),
        "Review regime carefully before acting on any signal today."
    )

    return {
        "nifty_close": round(nifty_close, 2) if nifty_close else "N/A",
        "nifty_chg":   round(nifty_chg, 2)   if nifty_chg   else 0,
        "sp_close":    round(sp_close, 2)     if sp_close    else "N/A",
        "sp_chg":      round(sp_chg, 2)       if sp_chg      else 0,
        "usd_note":    usd_note,
        "regime_note": regime_note,
    }

# ══════════════════════════════════════════════════════
#  SIGNAL HISTORY TRACKER
#  Reads screener_history.json if present in repo root.
#  Fetches 5-day return for each past ticker using yfinance.
#  No CSV commit needed — history file is optional.
# ══════════════════════════════════════════════════════

def load_signal_history():
    """Load past signals from JSON file if it exists."""
    if not os.path.exists(HISTORY_FILE):
        return []
    try:
        with open(HISTORY_FILE, "r") as f:
            data = json.load(f)
        # Keep only last 5 days of entries
        return data[-5:] if len(data) > 5 else data
    except Exception:
        return []

def save_signal_history(results, today_str):
    """Append today's picks to history file (max 5 entries kept)."""
    entry = {
        "date": today_str,
        "picks": [
            {
                "ticker":   r["ticker"],
                "name":     r["name"],
                "category": r["category"],
                "price":    r["price"],
                "tier":     r["tier"],
                "score":    r["score"],
            }
            for r in results
        ]
    }
    history = load_signal_history()
    history.append(entry)
    history = history[-5:]   # keep rolling 5 days only
    try:
        with open(HISTORY_FILE, "w") as f:
            json.dump(history, f, indent=2)
    except Exception as e:
        print(f"  [WARN] Could not save history: {e}")

def fetch_performance(history):
    """
    For each past signal entry, fetch current price and compute return.
    Returns list of dicts: {date, ticker, name, category, entry_price,
                            current_price, return_pct, tier}
    """
    if not history:
        return []

    all_tickers = list({pick["ticker"] for entry in history for pick in entry["picks"]})
    if not all_tickers:
        return []

    try:
        raw = yf.download(
            tickers=all_tickers,
            period="10d",
            interval="1d",
            group_by="ticker",
            threads=True,
            progress=False,
            auto_adjust=True,
        )
    except Exception:
        return []

    def get_latest_price(ticker):
        try:
            if len(all_tickers) == 1:
                s = raw["Close"].dropna()
            else:
                s = raw[ticker]["Close"].dropna()
            return float(s.iloc[-1]) if not s.empty else None
        except Exception:
            return None

    rows = []
    for entry in history:
        for pick in entry["picks"]:
            current = get_latest_price(pick["ticker"])
            if current is None:
                continue
            ret = (current - pick["price"]) / pick["price"] * 100
            rows.append({
                "date":          entry["date"],
                "ticker":        pick["ticker"],
                "name":          pick["name"],
                "category":      pick["category"],
                "entry_price":   pick["price"],
                "current_price": round(current, 4),
                "return_pct":    round(ret, 2),
                "tier":          pick["tier"],
            })
    return rows

# ══════════════════════════════════════════════════════
#  SCORE-WEIGHTED ALLOCATION WITH CATEGORY CAPS
# ══════════════════════════════════════════════════════

def compute_allocations(results, usd_to_inr):
    """
    Allocates TOTAL_BUDGET across picks weighted by score,
    subject to per-category caps.
    Indian Stock and Indian ETF share the 40% pool.
    Returns dict: ticker -> INR allocation
    """
    # Category budget limits
    # Indian Stock + Indian ETF together capped at 40%
    cat_budgets = {
        "Indian Stock":    TOTAL_BUDGET * CATEGORY_CAPS["Indian Stock"],
        "Indian ETF":      TOTAL_BUDGET * CATEGORY_CAPS["Indian ETF"],
        "Global ETF":      TOTAL_BUDGET * CATEGORY_CAPS["Global ETF"],
        "Metal/Commodity": TOTAL_BUDGET * CATEGORY_CAPS["Metal/Commodity"],
        "Crypto":          TOTAL_BUDGET * CATEGORY_CAPS["Crypto"],
    }

    # Group by category
    by_cat = {}
    for r in results:
        by_cat.setdefault(r["category"], []).append(r)

    # Indian Stock + Indian ETF share a combined pool
    indian_combined = (
        by_cat.get("Indian Stock", []) + by_cat.get("Indian ETF", [])
    )
    indian_pool = TOTAL_BUDGET * 0.40

    allocations = {}

    def weighted_split(picks, pool):
        total_score = sum(p["score"] for p in picks)
        if total_score == 0:
            per = pool / len(picks)
            return {p["ticker"]: per for p in picks}
        return {p["ticker"]: pool * (p["score"] / total_score) for p in picks}

    # Indian combined pool
    if indian_combined:
        allocations.update(weighted_split(indian_combined, indian_pool))

    # Other categories
    for cat in ["Global ETF", "Metal/Commodity", "Crypto"]:
        picks = by_cat.get(cat, [])
        if picks:
            allocations.update(weighted_split(picks, cat_budgets[cat]))

    return allocations

# ══════════════════════════════════════════════════════
#  TREND DIRECTION
# ══════════════════════════════════════════════════════

def get_trend_direction(price, ma_vals):
    ma20  = ma_vals.get("MA20")
    ma50  = ma_vals.get("MA50")
    ma200 = ma_vals.get("MA200")
    if ma20 and ma50 and price > ma20 and ma20 > ma50:
        if ma200 and price > ma200:
            return ("Strong Uptrend", "#15803d", "↑↑")
        return ("Uptrend", "#16a34a", "↑")
    if ma20 and ma50 and price < ma20 and ma20 < ma50:
        if ma200 and price < ma200:
            return ("Strong Downtrend", "#dc2626", "↓↓")
        return ("Downtrend", "#ef4444", "↓")
    return ("Sideways", "#d97706", "→")

# ══════════════════════════════════════════════════════
#  PRICE TARGETS
# ══════════════════════════════════════════════════════

def get_price_targets(price, ma_vals, close_series):
    targets_above    = {k: v for k, v in ma_vals.items() if v and v > price}
    three_month_high = float(close_series.tail(63).max())
    fifty_two_w_high = float(close_series.tail(252).max())
    upside_3m        = (three_month_high - price) / price * 100
    upside_52w       = (fifty_two_w_high  - price) / price * 100

    if targets_above:
        nearest_label = min(targets_above, key=targets_above.get)
        nearest_val   = targets_above[nearest_label]
        upside_ma     = (nearest_val - price) / price * 100
        above_all_mas = False
    else:
        nearest_label = "52W High"
        nearest_val   = fifty_two_w_high
        upside_ma     = upside_52w
        above_all_mas = True

    return {
        "nearest_ma_label": nearest_label,
        "nearest_ma_val":   round(nearest_val, 4),
        "upside_pct_ma":    round(upside_ma, 1),
        "three_month_high": round(three_month_high, 4),
        "upside_pct_3m":    round(upside_3m, 1),
        "above_all_mas":    above_all_mas,
    }

# ══════════════════════════════════════════════════════
#  RECOVERY WATCH
# ══════════════════════════════════════════════════════

def is_recovery_watch(regime, rsi_val, price, ma_vals, close_series, bench_close):
    if regime not in ("bear", "neutral"):
        return False
    if not (35 <= rsi_val <= 52):
        return False
    ma200 = ma_vals.get("MA200")
    if ma200 and price < ma200 * 0.85:
        return False
    rs_short = relative_strength_short(close_series, bench_close, lookback=10)
    rs_long  = relative_strength(close_series, bench_close, lookback=63)
    if rs_short is None or rs_long is None:
        return False
    return rs_short > rs_long

# ══════════════════════════════════════════════════════
#  PLAIN ENGLISH REASON
# ══════════════════════════════════════════════════════

def build_reason(r):
    """
    Generates a one-line plain English explanation of why this asset scored high.
    Reads from the breakdown and key metrics to pick the top 2-3 driving factors.
    """
    parts = []
    bd    = r["breakdown"]

    # RS
    if bd["RS vs Benchmark"] >= 20:
        parts.append(f"beating its benchmark by {r['rs_pct']:+.1f}% over 3 months")
    elif bd["RS vs Benchmark"] >= 10:
        parts.append(f"modestly outperforming its benchmark ({r['rs_pct']:+.1f}%)")

    # Trend
    if r["trend_dir"] in ("Strong Uptrend", "Uptrend"):
        parts.append(f"in a clear {r['trend_dir'].lower()}")
    elif r["trend_dir"] == "Sideways":
        parts.append("consolidating sideways")

    # RSI
    if 45 <= r["rsi"] <= 65:
        parts.append(f"RSI healthy at {r['rsi']}")
    elif r["rsi"] < 40:
        parts.append(f"RSI oversold at {r['rsi']} — potential bounce zone")
    elif r["rsi"] > 65:
        parts.append(f"RSI elevated at {r['rsi']} — momentum strong but watch for pullback")

    # MACD
    if bd["MACD Momentum"] == 15:
        parts.append("MACD positive and rising")
    elif bd["MACD Momentum"] == 10:
        parts.append("MACD positive")

    # ADX
    if bd["ADX Strength"] == 10:
        parts.append(f"strong directional trend (ADX {r['adx']})")

    # Volume
    if isinstance(r["vol_ratio"], float) and r["vol_ratio"] >= 1.5:
        parts.append(f"volume {r['vol_ratio']}x above average")

    # Recovery
    if r["recovery"]:
        parts.append("showing early reversal signs in a beaten-down regime")

    if not parts:
        return "Multiple technical factors aligning — review score breakdown below."

    sentence = ", ".join(parts[:3])
    return sentence[0].upper() + sentence[1:] + "."

# ══════════════════════════════════════════════════════
#  SCORING ENGINE  (max 110)
# ══════════════════════════════════════════════════════

def score_asset(ticker, df, bench_close, category, regime):
    try:
        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(dtype=float)

        if len(close) < 60:
            return None

        price = float(close.iloc[-1])
        if np.isnan(price) or price <= 0:
            return None

        if category == "Indian Stock" and not volume.empty:
            avg_vol = float(volume.tail(20).mean())
            if price < MIN_PRICE_INR or avg_vol < MIN_AVG_VOLUME_NS:
                return None

        rs = relative_strength(close, bench_close, lookback=63)
        if rs is None or rs < -0.15:
            return None
        rs_score = min(30, max(0, (rs + 0.05) * 150))

        trend_score = 0
        ma_vals = {}
        for window, pts in [(20, 10), (50, 10), (200, 5)]:
            if len(close) >= window:
                ma = float(close.rolling(window).mean().iloc[-1])
                ma_vals[f"MA{window}"] = round(ma, 4)
                if price > ma:
                    trend_score += pts

        if "MA200" in ma_vals and price < ma_vals["MA200"] * 0.85:
            return None

        rsi_s   = compute_rsi(close)
        rsi_val = float(rsi_s.iloc[-1])
        if np.isnan(rsi_val):
            return None
        if rsi_val > 75:              rsi_score = 0
        elif rsi_val < 30:            rsi_score = 5
        elif 45 <= rsi_val <= 65:     rsi_score = 20
        elif 30 <= rsi_val < 45:      rsi_score = 12
        else:                         rsi_score = 8

        _, _, hist = compute_macd(close)
        hist_now  = float(hist.iloc[-1])
        hist_prev = float(hist.iloc[-2]) if len(hist) > 1 else hist_now
        macd_score = (10 if hist_now > 0 else 0) + (5 if hist_now > hist_prev else 0)

        adx_val = None
        adx_score = 0
        try:
            adx_s, pdi_s, mdi_s = compute_adx(df)
            adx_val = float(adx_s.iloc[-1])
            pdi_val = float(pdi_s.iloc[-1])
            mdi_val = float(mdi_s.iloc[-1])
            if adx_val > 25 and pdi_val > mdi_val:   adx_score = 10
            elif adx_val > 20 and pdi_val > mdi_val: adx_score = 6
        except Exception:
            pass

        vol_score = 0
        vol_ratio = None
        if not volume.empty and len(volume) >= 20:
            avg_vol   = float(volume.tail(20).mean())
            vol_ratio = float(volume.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
            vol_score = min(10, max(0, (vol_ratio - 0.8) * 12))

        period_high = float(close.tail(63).max())
        dip_pct     = (period_high - price) / period_high * 100

        rm          = {"bull": 1.0, "neutral": 0.9, "bear": 0.75}[regime]
        raw_score   = rs_score + trend_score + rsi_score + macd_score + adx_score + vol_score
        final_score = round(raw_score * rm, 1)

        if final_score >= SCORE_STRONG_BUY:   tier = "Strong Buy"
        elif final_score >= SCORE_WATCH:      tier = "Watch"
        else:                                 return None

        trend_dir, trend_color, trend_arrow = get_trend_direction(price, ma_vals)
        targets  = get_price_targets(price, ma_vals, close)
        recovery = is_recovery_watch(regime, rsi_val, price, ma_vals, close, bench_close)

        result = {
            "ticker":      ticker,
            "name":        get_display_name(ticker),
            "category":    category,
            "price":       round(price, 4),
            "tier":        tier,
            "score":       final_score,
            "raw_score":   round(raw_score, 1),
            "regime":      regime,
            "dip":         round(dip_pct, 2),
            "rs_pct":      round(rs * 100, 2),
            "rsi":         round(rsi_val, 1),
            "macd_hist":   round(hist_now, 6),
            "adx":         round(adx_val, 1) if adx_val is not None else "n/a",
            "vol_ratio":   round(vol_ratio, 2) if vol_ratio is not None else "n/a",
            "ma_vals":     ma_vals,
            "trend_dir":   trend_dir,
            "trend_color": trend_color,
            "trend_arrow": trend_arrow,
            "targets":     targets,
            "recovery":    recovery,
            "allocation":  0,   # filled in later
            "reason":      "",  # filled in later
            "breakdown": {
                "RS vs Benchmark": round(rs_score, 1),
                "Trend (DMA)":     trend_score,
                "RSI Quality":     rsi_score,
                "MACD Momentum":   macd_score,
                "ADX Strength":    adx_score,
                "Volume":          round(vol_score, 1),
            }
        }
        result["reason"] = build_reason(result)
        return result

    except Exception:
        return None

# ══════════════════════════════════════════════════════
#  HTML COMPONENTS
# ══════════════════════════════════════════════════════

TIER_BADGE = {
    "Strong Buy": ("background:#dcfce7;color:#15803d;border:1px solid #86efac", "STRONG BUY"),
    "Watch":      ("background:#fef9c3;color:#a16207;border:1px solid #fde047", "WATCH"),
}

REGIME_STYLE = {
    "bull":    ("background:#f0fdf4;border-left:4px solid #16a34a", "Bull Market",          "#15803d"),
    "neutral": ("background:#fffbeb;border-left:4px solid #f59e0b", "Neutral / Sideways",   "#a16207"),
    "bear":    ("background:#fef2f2;border-left:4px solid #dc2626", "Bear Market - Caution","#dc2626"),
}

def format_buy_amount(allocation_inr, price, currency, usd_to_inr):
    if currency == "INR":
        units = allocation_inr / price if price > 0 else 0
        return f"Rs.{int(allocation_inr):,}", f"approx {units:.1f} shares @ Rs.{price:.2f}"
    else:
        price_inr = price * usd_to_inr
        units = allocation_inr / price_inr if price_inr > 0 else 0
        return f"Rs.{int(allocation_inr):,}", f"approx {units:.4f} units @ ${price:.2f} (1 USD = Rs.{usd_to_inr:.2f})"

def ma_trend_label(price, ma_vals):
    parts = []
    for k in ["MA20", "MA50", "MA200"]:
        if k in ma_vals:
            above = price > ma_vals[k]
            color = "#16a34a" if above else "#dc2626"
            parts.append(f"<span style='color:{color};font-weight:600'>{k}: {'above' if above else 'below'}</span>")
    return " &nbsp;|&nbsp; ".join(parts)

# ══════════════════════════════════════════════════════
#  MACRO CONTEXT BLOCK (HTML)
# ══════════════════════════════════════════════════════

def build_macro_html(macro):
    nifty_color = "#15803d" if macro["nifty_chg"] >= 0 else "#dc2626"
    sp_color    = "#15803d" if macro["sp_chg"] >= 0    else "#dc2626"
    nifty_arrow = "▲" if macro["nifty_chg"] >= 0 else "▼"
    sp_arrow    = "▲" if macro["sp_chg"] >= 0    else "▼"

    return f"""
<div style='background:#1e3a5f;border-radius:10px;padding:18px 20px;margin-bottom:16px'>
  <div style='font-size:12px;font-weight:700;color:#93c5fd;text-transform:uppercase;
              letter-spacing:0.06em;margin-bottom:12px'>Market Snapshot — Yesterday's Close</div>
  <table cellpadding='0' cellspacing='0' width='100%'>
    <tr>
      <td style='padding-right:28px'>
        <div style='font-size:11px;color:#93c5fd;margin-bottom:2px'>Nifty 50</div>
        <div style='font-size:20px;font-weight:900;color:#fff'>{macro["nifty_close"]:,}</div>
        <div style='font-size:13px;font-weight:700;color:{nifty_color}'>{nifty_arrow} {abs(macro["nifty_chg"])}%</div>
      </td>
      <td style='padding-right:28px;border-left:1px solid #2d5a8e;padding-left:28px'>
        <div style='font-size:11px;color:#93c5fd;margin-bottom:2px'>S&amp;P 500</div>
        <div style='font-size:20px;font-weight:900;color:#fff'>{macro["sp_close"]:,}</div>
        <div style='font-size:13px;font-weight:700;color:{sp_color}'>{sp_arrow} {abs(macro["sp_chg"])}%</div>
      </td>
      <td style='border-left:1px solid #2d5a8e;padding-left:28px'>
        <div style='font-size:11px;color:#93c5fd;margin-bottom:2px'>USD / INR</div>
        <div style='font-size:16px;font-weight:800;color:#fff'>{macro["usd_note"]}</div>
      </td>
    </tr>
  </table>
  <div style='margin-top:14px;padding-top:12px;border-top:1px solid #2d5a8e;
              font-size:13px;color:#bfdbfe;line-height:1.6'>
    💡 {macro["regime_note"]}
  </div>
</div>"""

# ══════════════════════════════════════════════════════
#  PERFORMANCE TRACKER (HTML)
# ══════════════════════════════════════════════════════

def build_performance_html(perf_rows):
    if not perf_rows:
        return ""

    rows_html = ""
    for p in perf_rows:
        ret_color = "#15803d" if p["return_pct"] >= 0 else "#dc2626"
        ret_arrow = "▲" if p["return_pct"] >= 0 else "▼"
        cat_color = CATEGORY_COLORS.get(p["category"], "#374151")
        rows_html += f"""
        <tr style='border-bottom:1px solid #f1f5f9'>
          <td style='padding:7px 10px;font-size:11px;color:#9ca3af'>{p["date"]}</td>
          <td style='padding:7px 10px'>
            <span style='font-size:12px;font-weight:700;color:#111'>{p["ticker"]}</span>
            <span style='font-size:10px;color:{cat_color};font-weight:600;
                margin-left:4px;background:#f1f5f9;padding:1px 5px;border-radius:4px'>
              {p["category"]}
            </span>
          </td>
          <td style='padding:7px 10px;font-size:12px;color:#374151'>
            {p["entry_price"]:,.4f}
          </td>
          <td style='padding:7px 10px;font-size:12px;color:#374151'>
            {p["current_price"]:,.4f}
          </td>
          <td style='padding:7px 10px;font-size:13px;font-weight:800;color:{ret_color}'>
            {ret_arrow} {abs(p["return_pct"])}%
          </td>
        </tr>"""

    return f"""
<div style='margin-bottom:24px'>
  <div style='font-size:15px;font-weight:800;color:#374151;
              margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #e5e7eb'>
    📈 HOW LAST PICKS PERFORMED
  </div>
  <div style='font-size:12px;color:#6b7280;margin-bottom:10px'>
    Entry price = price on recommendation day. Current = today's price. Up to 5 days shown.
  </div>
  <table width='100%' cellpadding='0' cellspacing='0'
         style='border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;border-collapse:collapse'>
    <thead>
      <tr style='background:#f8fafc'>
        <th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Date</th>
        <th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Asset</th>
        <th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Entry Price</th>
        <th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Now</th>
        <th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Return</th>
      </tr>
    </thead>
    <tbody>{rows_html}</tbody>
  </table>
</div>"""

# ══════════════════════════════════════════════════════
#  SUMMARY TABLE
# ══════════════════════════════════════════════════════

def build_summary_table(results):
    rows_by_cat = {cat: [] for cat in CATEGORY_ORDER}
    for r in results:
        if r["category"] in rows_by_cat:
            rows_by_cat[r["category"]].append(r)

    rank_map = {r["ticker"]: i + 1 for i, r in enumerate(results)}
    sections = ""

    for cat in CATEGORY_ORDER:
        items = rows_by_cat[cat]
        if not items:
            continue
        cat_color = CATEGORY_COLORS.get(cat, "#374151")
        rows = ""
        for r in items:
            meta      = CATEGORY_META[r["category"]]
            price_str = f"${r['price']:.2f}" if meta["currency"] == "USD" else f"Rs.{r['price']:.2f}"
            alloc_str = f"Rs.{int(r['allocation']):,}"
            tier_color = "#15803d" if r["tier"] == "Strong Buy" else "#a16207"
            tier_bg    = "#dcfce7" if r["tier"] == "Strong Buy" else "#fef9c3"
            rec = ("<span style='background:#ede9fe;color:#7c3aed;border:1px solid #c4b5fd;"
                   "font-size:10px;font-weight:700;padding:1px 5px;border-radius:10px;margin-left:4px'>🔄</span>"
                   if r["recovery"] else "")
            t = r["targets"]
            ma_label = "52W High" if t.get("above_all_mas") else t["nearest_ma_label"]
            rows += f"""
              <tr style='border-bottom:1px solid #f1f5f9'>
                <td style='padding:8px 10px;font-size:13px;font-weight:700;color:#374151'>{rank_map[r["ticker"]]}</td>
                <td style='padding:8px 10px'>
                  <div style='font-size:13px;font-weight:800;color:#111'>{r["ticker"]}</div>
                  <div style='font-size:11px;color:#9ca3af'>{r["name"][:32]}{"..." if len(r["name"])>32 else ""}</div>
                </td>
                <td style='padding:8px 10px;font-size:12px;color:#374151'>{price_str}</td>
                <td style='padding:8px 10px;text-align:center'>
                  <span style='background:{tier_bg};color:{tier_color};border-radius:10px;
                      font-size:11px;font-weight:700;padding:2px 8px'>{r["tier"]}</span>{rec}
                </td>
                <td style='padding:8px 10px;text-align:center'>
                  <span style='font-size:15px;font-weight:900;color:{r["trend_color"]}'>{r["trend_arrow"]}</span>
                  <div style='font-size:10px;color:{r["trend_color"]};font-weight:600'>{r["trend_dir"]}</div>
                </td>
                <td style='padding:8px 10px;text-align:right'>
                  <span style='font-size:15px;font-weight:900;color:#1d4ed8'>{r["score"]}</span>
                  <span style='font-size:10px;color:#94a3b8'>/110</span>
                </td>
                <td style='padding:8px 10px;font-size:12px;color:#15803d;font-weight:700;white-space:nowrap'>
                  +{t["upside_pct_ma"]}% → {ma_label}
                </td>
                <td style='padding:8px 10px;font-size:12px;color:#0369a1;font-weight:600;white-space:nowrap'>
                  +{t["upside_pct_3m"]}% → 3M High
                </td>
                <td style='padding:8px 10px;font-size:13px;font-weight:800;color:#1d4ed8;white-space:nowrap'>
                  {alloc_str}
                </td>
              </tr>"""

        sections += f"""
        <table width='100%' cellpadding='0' cellspacing='0'
               style='border:1px solid #e5e7eb;border-radius:8px;margin-bottom:16px;
                      overflow:hidden;border-collapse:collapse'>
          <thead>
            <tr style='background:{cat_color}'>
              <td colspan='9' style='color:#fff;font-size:12px;font-weight:800;
                  text-transform:uppercase;letter-spacing:0.06em;padding:8px 14px'>
                {cat} — {len(items)} pick{"s" if len(items)!=1 else ""}
              </td>
            </tr>
            <tr style='background:#f8fafc'>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>#</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Asset</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Price</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:center'>Signal</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:center'>Trend</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:right'>Score</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>MA Target</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>3M High</th>
              <th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>Allocate</th>
            </tr>
          </thead>
          <tbody>{rows}</tbody>
        </table>"""

    return sections

# ══════════════════════════════════════════════════════
#  ASSET CARD
# ══════════════════════════════════════════════════════

def build_asset_card(global_rank, r, usd_to_inr):
    meta                   = CATEGORY_META[r["category"]]
    tier_style, tier_label = TIER_BADGE[r["tier"]]
    buy_str, fx_note       = format_buy_amount(r["allocation"], r["price"], meta["currency"], usd_to_inr)
    price_str              = f"${r['price']:.4f}" if meta["currency"] == "USD" else f"Rs.{r['price']:.2f}"
    rs_color               = "#16a34a" if r["rs_pct"] >= 0 else "#dc2626"
    cat_color              = CATEGORY_COLORS.get(r["category"], "#374151")
    t                      = r["targets"]
    regime_color           = {"bull":"#15803d","neutral":"#a16207","bear":"#dc2626"}[r["regime"]]

    recovery_banner = ""
    if r["recovery"]:
        recovery_banner = """
        <div style='background:#ede9fe;border:1px solid #c4b5fd;border-radius:8px;
                    padding:10px 16px;margin:12px 0;display:flex;align-items:flex-start'>
          <span style='font-size:20px;margin-right:10px;line-height:1.2'>🔄</span>
          <div>
            <div style='font-size:12px;font-weight:800;color:#7c3aed;text-transform:uppercase;
                        letter-spacing:0.05em'>Recovery Watch</div>
            <div style='font-size:12px;color:#6d28d9;margin-top:3px;line-height:1.5'>
              Bear/neutral regime but showing early reversal — RSI stabilising (35–52),
              short-term momentum recovering faster than 3-month trend, price within 15%
              of MA200. Potential value entry. Confirm before acting.
            </div>
          </div>
        </div>"""

    max_scores = {"RS vs Benchmark":30,"Trend (DMA)":25,"RSI Quality":20,"MACD Momentum":15,"ADX Strength":10,"Volume":10}
    breakdown_rows = "".join(
        f"<tr><td style='padding:3px 12px 3px 0;color:#6b7280;font-size:12px;white-space:nowrap'>{k}</td>"
        f"<td style='padding:3px 4px'><div style='height:10px;"
        f"width:{min(int(v * 220 / max_scores.get(k, 30)), 220)}px;"
        f"background:#3b82f6;border-radius:4px;display:inline-block;vertical-align:middle'></div></td>"
        f"<td style='padding:3px 0 3px 8px;font-size:12px;font-weight:700;color:#1d4ed8'>"
        f"{v} / {max_scores.get(k,'?')}</td></tr>"
        for k, v in r["breakdown"].items()
    )

    above_all_note = (
        "<div style='font-size:11px;color:#15803d;background:#dcfce7;border-radius:4px;"
        "padding:4px 8px;margin-bottom:10px;display:inline-block'>"
        "✓ Price is above all MAs — stock is in full strength</div>"
        if t.get("above_all_mas") else ""
    )

    return f"""
<div style='border:1px solid #e5e7eb;border-left:4px solid {cat_color};border-radius:12px;
            padding:20px;margin-bottom:20px;background:#fff;
            font-family:-apple-system,BlinkMacSystemFont,sans-serif'>

  <table width='100%' cellpadding='0' cellspacing='0'>
    <tr>
      <td valign='top'>
        <div style='font-size:11px;color:{cat_color};font-weight:700;text-transform:uppercase;
                    letter-spacing:0.05em'>#{global_rank} &nbsp;·&nbsp; {meta["label"]}</div>
        <div style='font-size:18px;font-weight:800;color:#111;margin:4px 0 2px'>{r["name"]}</div>
        <div style='font-size:13px;color:#9ca3af'>{r["ticker"]} &nbsp;|&nbsp; Price: {price_str}</div>
      </td>
      <td valign='top' align='right' style='white-space:nowrap;padding-left:12px'>
        <div style='display:inline-block;padding:4px 14px;border-radius:20px;
                    font-size:12px;font-weight:800;{tier_style}'>{tier_label}</div>
        <div style='margin-top:6px'>
          <span style='font-size:18px;font-weight:900;color:{r["trend_color"]}'>{r["trend_arrow"]}</span>
          <span style='font-size:13px;font-weight:700;color:{r["trend_color"]};margin-left:4px'>{r["trend_dir"]}</span>
        </div>
        <div style='font-size:26px;font-weight:900;color:#1d4ed8;margin-top:4px'>{buy_str}</div>
        <div style='font-size:11px;color:#9ca3af;margin-top:2px'>{fx_note}</div>
      </td>
    </tr>
  </table>

  <!-- PLAIN ENGLISH REASON -->
  <div style='background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px;
              padding:10px 14px;margin:12px 0;font-size:13px;color:#374151;line-height:1.6'>
    <strong style='color:#a16207'>Why this pick:</strong> {r["reason"]}
  </div>

  {recovery_banner}

  <!-- METRICS ROW -->
  <div style='margin:14px 0 4px;overflow-x:auto'>
    <table cellpadding='0' cellspacing='6' style='white-space:nowrap'>
      <tr>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'>
          <div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Score</div>
          <div style='font-size:18px;font-weight:900;color:#1d4ed8'>{r["score"]}<span style='font-size:10px;color:#94a3b8'>/110</span></div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'>
          <div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Raw Score</div>
          <div style='font-size:16px;font-weight:800;color:#374151'>{r["raw_score"]}<span style='font-size:10px;color:#94a3b8'>/110</span></div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'>
          <div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>RS vs Benchmark</div>
          <div style='font-size:16px;font-weight:800;color:{rs_color}'>{r["rs_pct"]:+.2f}%</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'>
          <div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>RSI (14)</div>
          <div style='font-size:16px;font-weight:800;color:#374151'>{r["rsi"]}</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'>
          <div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>ADX</div>
          <div style='font-size:16px;font-weight:800;color:#374151'>{r["adx"]}</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'>
          <div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Vol Ratio</div>
          <div style='font-size:16px;font-weight:800;color:#374151'>{r["vol_ratio"]}x</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'>
          <div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Regime</div>
          <div style='font-size:14px;font-weight:800;color:{regime_color}'>{r["regime"].title()}</div>
        </td>
      </tr>
    </table>
  </div>

  <!-- PRICE TARGETS -->
  <div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;
              padding:14px 16px;margin:14px 0'>
    <div style='font-size:11px;color:#15803d;font-weight:700;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:8px'>Price Targets &amp; Exit Levels</div>
    {above_all_note}
    <table cellpadding='0' cellspacing='0'>
      <tr>
        <td style='padding-right:24px'>
          <div style='font-size:11px;color:#6b7280;margin-bottom:2px'>{"52-Week High" if t.get("above_all_mas") else "Nearest MA Resistance"}</div>
          <div style='font-size:18px;font-weight:800;color:#15803d'>+{t["upside_pct_ma"]}%</div>
          <div style='font-size:11px;color:#374151'>{t["nearest_ma_label"]} @ {t["nearest_ma_val"]:,.4f}</div>
        </td>
        <td style='padding:0 24px;border-left:1px solid #bbf7d0'>
          <div style='font-size:11px;color:#6b7280;margin-bottom:2px'>3-Month High Recovery</div>
          <div style='font-size:18px;font-weight:800;color:#0369a1'>+{t["upside_pct_3m"]}%</div>
          <div style='font-size:11px;color:#374151'>Target: {t["three_month_high"]:,.4f}</div>
        </td>
        <td style='padding-left:24px;border-left:1px solid #bbf7d0'>
          <div style='font-size:11px;color:#6b7280;margin-bottom:2px'>Current Dip</div>
          <div style='font-size:18px;font-weight:800;color:#d97706'>-{r["dip"]}%</div>
          <div style='font-size:11px;color:#374151'>from 3M high</div>
        </td>
      </tr>
    </table>
  </div>

  <!-- MA POSITIONS -->
  <div style='font-size:12px;padding:8px 12px;background:#f8fafc;border-radius:6px;margin-bottom:14px'>
    {ma_trend_label(r["price"], r["ma_vals"])}
  </div>

  <!-- SCORE BREAKDOWN -->
  <div style='border-top:1px solid #f1f5f9;padding-top:12px'>
    <div style='font-size:11px;color:#9ca3af;font-weight:700;text-transform:uppercase;
                letter-spacing:0.05em;margin-bottom:8px'>Score Breakdown</div>
    <table cellpadding='0' cellspacing='0'>{breakdown_rows}</table>
  </div>

</div>"""

# ══════════════════════════════════════════════════════
#  EMAIL BUILDER
# ══════════════════════════════════════════════════════

def build_email(results, regime_nifty, regime_sp500, usd_to_inr, date_str, macro, perf_html):
    strong  = [r for r in results if r["tier"] == "Strong Buy"]
    watch   = [r for r in results if r["tier"] == "Watch"]
    n_total = len(results)
    total_deployed = sum(r["allocation"] for r in results)
    recovery_count = sum(1 for r in results if r["recovery"])

    rn_style, rn_label, rn_color = REGIME_STYLE[regime_nifty]
    rs_style, rs_label, rs_color = REGIME_STYLE[regime_sp500]

    summary = build_summary_table(results)

    strong_cards = "".join(
        build_asset_card(i + 1, r, usd_to_inr)
        for i, r in enumerate(results) if r["tier"] == "Strong Buy"
    ) or "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Strong Buy signals today.</p>"

    watch_start  = len(strong) + 1
    watch_cards  = "".join(
        build_asset_card(watch_start + i, r, usd_to_inr)
        for i, r in enumerate(results) if r["tier"] == "Watch"
    ) or "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Watch signals today.</p>"

    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head>
<body style='margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'>
<div style='max-width:760px;margin:0 auto;padding:24px 16px'>

  <!-- HEADER -->
  <div style='background:#1d4ed8;border-radius:14px 14px 0 0;padding:28px 28px 24px'>
    <div style='font-size:24px;font-weight:900;color:#fff'>Daily Market Screener</div>
    <div style='font-size:13px;color:#bfdbfe;margin-top:4px'>
      {date_str} &nbsp;|&nbsp; Budget: Rs.{TOTAL_BUDGET:,} &nbsp;|&nbsp; Deployed: Rs.{int(total_deployed):,}
    </div>
    <table cellpadding='0' cellspacing='0' style='margin-top:20px'>
      <tr>
        <td style='padding-right:24px'>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Strong Buy</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>{len(strong)}</div>
        </td>
        <td style='padding-right:24px'>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Watch</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>{len(watch)}</div>
        </td>
        <td style='padding-right:24px'>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Recovery 🔄</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>{recovery_count}</div>
        </td>
        <td>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Total Picks</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>{n_total}</div>
        </td>
      </tr>
    </table>
  </div>

  <!-- MACRO CONTEXT -->
  {build_macro_html(macro)}

  <!-- REGIME BANNERS -->
  <table width='100%' cellpadding='6' cellspacing='0' style='margin:0 0 16px'>
    <tr>
      <td width='50%'>
        <div style='{rn_style};padding:12px 16px;border-radius:8px'>
          <div style='font-size:11px;color:{rn_color};font-weight:700;text-transform:uppercase;letter-spacing:0.05em'>Nifty 50 Regime</div>
          <div style='font-size:15px;font-weight:800;color:{rn_color};margin-top:2px'>{rn_label}</div>
        </div>
      </td>
      <td width='50%'>
        <div style='{rs_style};padding:12px 16px;border-radius:8px'>
          <div style='font-size:11px;color:{rs_color};font-weight:700;text-transform:uppercase;letter-spacing:0.05em'>S&amp;P 500 Regime</div>
          <div style='font-size:15px;font-weight:800;color:{rs_color};margin-top:2px'>{rs_label}</div>
        </div>
      </td>
    </tr>
  </table>

  <!-- PERFORMANCE TRACKER -->
  {perf_html}

  <!-- SUMMARY TABLE -->
  <div style='font-size:15px;font-weight:800;color:#1d4ed8;margin:8px 0 8px;
              padding-bottom:8px;border-bottom:2px solid #bfdbfe'>
    AT A GLANCE — TOP {n_total} PICKS TODAY
  </div>
  <div style='font-size:12px;color:#6b7280;margin-bottom:16px;line-height:1.6'>
    Ranked #1 to #{n_total} by regime-adjusted score. Allocation is score-weighted within each category cap.
  </div>
  {summary}

  <!-- STRONG BUY -->
  <div style='font-size:15px;font-weight:800;color:#15803d;margin:32px 0 14px;
              padding-bottom:8px;border-bottom:2px solid #bbf7d0'>
    STRONG BUY SIGNALS ({len(strong)})
  </div>
  {strong_cards}

  <!-- WATCH LIST -->
  <div style='font-size:15px;font-weight:800;color:#a16207;margin:28px 0 14px;
              padding-bottom:8px;border-bottom:2px solid #fde68a'>
    WATCH LIST ({len(watch)})
  </div>
  {watch_cards}

  <!-- FOOTER -->
  <div style='margin-top:32px;padding:16px;background:#fff;border-radius:10px;
              font-size:11px;color:#9ca3af;border:1px solid #e5e7eb;line-height:1.8'>
    <strong style='color:#6b7280'>Scoring (max 110):</strong>
    RS vs Benchmark (30) + Trend/DMA (25) + RSI Quality (20) + MACD Momentum (15) + ADX (10) + Volume (10).
    Regime multiplier: Bull ×1.0 · Neutral ×0.9 · Bear ×0.75. Top 25 globally by final score.
    <br>
    <strong style='color:#6b7280'>Allocation:</strong>
    Score-weighted within category caps — Indian 40%, Global ETF 30%, Metals 20%, Crypto 10%.
    <br>
    <strong style='color:#6b7280'>Targets:</strong>
    MA Resistance = nearest MA above price. 3M High = 3-month peak. 52W High used when price is above all MAs.
    <br>
    <strong style='color:#6b7280'>Recovery Watch 🔄:</strong>
    Bear/neutral stocks with RSI 35–52, improving short-term RS, within 15% of MA200.
    <br>
    <strong style='color:#6b7280'>Disclaimer:</strong> Not financial advice. Do your own research.
  </div>

</div></body></html>"""

    return html

# ══════════════════════════════════════════════════════
#  TELEGRAM ALERT
# ══════════════════════════════════════════════════════

def send_telegram(results, regime_nifty, regime_sp500, macro, date_str):
    """
    Sends top 5 picks as a clean Telegram message.
    Requires TELEGRAM_BOT_TOKEN and TELEGRAM_CHAT_ID as GitHub secrets.
    """
    token   = os.environ.get("TELEGRAM_BOT_TOKEN", "")
    chat_id = os.environ.get("TELEGRAM_CHAT_ID", "")

    if not token or not chat_id:
        print("  [INFO] Telegram secrets not set — skipping Telegram alert.")
        return

    top5 = results[:5]
    nifty_arrow = "▲" if macro["nifty_chg"] >= 0 else "▼"
    sp_arrow    = "▲" if macro["sp_chg"] >= 0    else "▼"

    lines = [
        f"📊 *Daily Screener — {date_str}*",
        f"",
        f"Nifty: {macro['nifty_close']:,} {nifty_arrow}{abs(macro['nifty_chg'])}%  |  S&P: {macro['sp_close']:,} {sp_arrow}{abs(macro['sp_chg'])}%",
        f"Regime: Nifty={regime_nifty.title()}  S&P={regime_sp500.title()}",
        f"",
        f"💡 _{macro['regime_note']}_",
        f"",
        f"*🏆 TOP 5 PICKS*",
    ]

    for i, r in enumerate(top5, 1):
        meta      = CATEGORY_META[r["category"]]
        price_str = f"${r['price']:.2f}" if meta["currency"] == "USD" else f"Rs.{r['price']:.2f}"
        alloc_str = f"Rs.{int(r['allocation']):,}"
        rec_tag   = " 🔄" if r["recovery"] else ""
        tier_icon = "🟢" if r["tier"] == "Strong Buy" else "🟡"
        lines.append(
            f"{i}. {tier_icon} *{r['ticker']}* ({r['category']}){rec_tag}\n"
            f"   {price_str}  |  Score: {r['score']}/110  |  Allocate: {alloc_str}\n"
            f"   {r['trend_arrow']} {r['trend_dir']}  |  Target: +{r['targets']['upside_pct_ma']}%\n"
            f"   _{r['reason']}_"
        )

    lines += ["", f"Full report in your email 📧"]
    message = "\n".join(lines)

    try:
        url     = f"https://api.telegram.org/bot{token}/sendMessage"
        payload = json.dumps({
            "chat_id":    chat_id,
            "text":       message,
            "parse_mode": "Markdown",
        }).encode("utf-8")
        req = urllib.request.Request(
            url,
            data=payload,
            headers={"Content-Type": "application/json"},
            method="POST"
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            if resp.status == 200:
                print("  Telegram alert sent.")
            else:
                print(f"  [WARN] Telegram returned status {resp.status}")
    except Exception as e:
        print(f"  [WARN] Telegram alert failed: {e}")

# ══════════════════════════════════════════════════════
#  SEND EMAIL
# ══════════════════════════════════════════════════════

def send_email(subject, html_body):
    email    = os.environ["EMAIL_ADDRESS"]
    password = os.environ["EMAIL_PASSWORD"]
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = email
    msg["To"]      = email
    msg.attach(MIMEText(html_body, "html"))
    try:
        with smtplib.SMTP("smtp.gmail.com", 587) as s:
            s.starttls()
            s.login(email, password)
            s.send_message(msg)
        print("  Email sent successfully.")
    except Exception as e:
        print(f"  Email error: {e}")

# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════

def main():
    today     = datetime.now().strftime("%d %b %Y")
    today_key = datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*55}")
    print(f"  Daily Screener v3 — {today}")
    print(f"{'='*55}\n")

    # Load signal history before this run
    history  = load_signal_history()
    print(f"  Signal history entries found: {len(history)}")

    # Build Nifty 500 universe
    nse_stocks = []
    try:
        url    = "https://archives.nseindia.com/content/indices/ind_nifty500list.csv"
        df_nse = pd.read_csv(url)
        nse_stocks = [s.strip() + ".NS" for s in df_nse["Symbol"].dropna().tolist()]
        print(f"  Nifty 500 loaded: {len(nse_stocks)} stocks")
    except Exception as e:
        print(f"  [WARN] Nifty 500 fetch failed ({e}). Using fallback.")
        fallback = [
            "RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR",
            "SBIN","BHARTIARTL","ITC","KOTAKBANK","LT","AXISBANK",
            "ASIANPAINT","MARUTI","TITAN","SUNPHARMA","BAJFINANCE","WIPRO","HCLTECH",
            "ADANIENT","ADANIPORTS","BAJAJFINSV","BRITANNIA","CIPLA","COALINDIA",
            "DIVISLAB","DRREDDY","EICHERMOT","GRASIM","HEROMOTOCO","HINDALCO",
            "INDUSINDBK","JSWSTEEL","M&M","NESTLEIND","NTPC","ONGC","POWERGRID",
            "SBILIFE","SHREECEM","TATAMOTORS","TATACONSUM","TATASTEEL","TECHM",
            "ULTRACEMCO","UPL","VEDL"
        ]
        nse_stocks = [s + ".NS" for s in fallback]

    all_tickers = (
        nse_stocks
        + list(INDIAN_ETFS.keys())
        + list(GLOBAL_ETFS.keys())
        + list(METALS_COMMODITIES.keys())
        + list(CRYPTO.keys())
    )

    extra   = ["^NSEI", "^GSPC", "BTC-USD", "USDINR=X"]
    dl_list = list(dict.fromkeys(all_tickers + extra))

    print(f"  Total tickers: {len(dl_list)}  |  Downloading 1-year data...\n")

    raw = yf.download(
        tickers=dl_list,
        period=DATA_PERIOD,
        interval="1d",
        group_by="ticker",
        threads=True,
        progress=True,
        auto_adjust=True,
    )

    try:
        usd_to_inr = float(raw["USDINR=X"]["Close"].dropna().iloc[-1])
    except Exception:
        usd_to_inr = 84.0
    print(f"\n  USD/INR rate: {usd_to_inr:.2f}")

    def get_close(t):
        try:
            s = raw[t]["Close"].dropna()
            return s.squeeze() if not s.empty else pd.Series(dtype=float)
        except Exception:
            return pd.Series(dtype=float)

    bench_nifty = get_close("^NSEI")
    bench_sp500 = get_close("^GSPC")
    bench_btc   = get_close("BTC-USD")

    benchmarks = {
        "Indian Stock":    bench_nifty,
        "Indian ETF":      bench_nifty,
        "Global ETF":      bench_sp500,
        "Metal/Commodity": bench_sp500,
        "Crypto":          bench_btc,
    }

    regime_nifty = get_regime(bench_nifty) if not bench_nifty.empty else "neutral"
    regime_sp500 = get_regime(bench_sp500) if not bench_sp500.empty else "neutral"
    print(f"  Nifty regime:   {regime_nifty.upper()}")
    print(f"  S&P 500 regime: {regime_sp500.upper()}\n")

    # Macro context
    macro = build_macro_context(bench_nifty, bench_sp500, usd_to_inr, regime_nifty, regime_sp500)

    # Performance tracker
    print("  Fetching performance for past signals...")
    perf_rows = fetch_performance(history)
    perf_html = build_performance_html(perf_rows)
    print(f"  Past signal rows: {len(perf_rows)}")

    try:
        tickers_in_raw = set(raw.columns.get_level_values(0))
    except Exception:
        tickers_in_raw = set()

    all_results = []

    for ticker in all_tickers:
        if ticker not in tickers_in_raw:
            continue
        try:
            df = raw[ticker].dropna(how="all")
            if df.empty or len(df) < 60:
                continue

            cat   = get_category(ticker)
            bench = benchmarks.get(cat, pd.Series(dtype=float))
            if bench.empty:
                continue

            common = df.index.intersection(bench.index)
            if len(common) < 60:
                continue

            df_a   = df.loc[common].copy()
            b_a    = bench.loc[common].copy()
            regime = regime_nifty if cat in ("Indian Stock","Indian ETF") else (
                     "neutral" if cat == "Crypto" else regime_sp500)

            result = score_asset(ticker, df_a, b_a, cat, regime)
            if result is not None:
                all_results.append(result)
        except Exception:
            continue

    # Global top 25 by final score
    all_results.sort(key=lambda x: -x["score"])
    results = all_results[:GLOBAL_MAX_PICKS]

    # Strong Buy first, then Watch — both score-ordered
    results.sort(key=lambda x: (0 if x["tier"] == "Strong Buy" else 1, -x["score"]))

    # Compute score-weighted allocations with category caps
    allocations = compute_allocations(results, usd_to_inr)
    for r in results:
        r["allocation"] = round(allocations.get(r["ticker"], 0), 2)

    strong = [r for r in results if r["tier"] == "Strong Buy"]
    watch  = [r for r in results if r["tier"] == "Watch"]
    recovery_count = sum(1 for r in results if r["recovery"])

    print(f"  Total qualified: {len(all_results)}  |  Showing top {len(results)}")
    print(f"  Strong Buy: {len(strong)}  |  Watch: {len(watch)}  |  Recovery: {recovery_count}\n")

    for r in results:
        meta      = CATEGORY_META[r["category"]]
        price_str = f"${r['price']:.2f}" if meta["currency"] == "USD" else f"Rs.{r['price']:.2f}"
        print(f"  [{r['tier']:11s}] {r['ticker']:18s} Score={r['score']:5.1f}  "
              f"Alloc=Rs.{int(r['allocation']):,}  {r['trend_arrow']} {r['trend_dir']:<18s}  {price_str}")

    # Save today's picks to history
    save_signal_history(results, today_key)

    # Build and send email
    html = build_email(results, regime_nifty, regime_sp500, usd_to_inr, today, macro, perf_html)
    subject = (
        f"[Screener {today}] "
        f"{len(strong)} Strong Buy | {len(watch)} Watch | "
        f"{recovery_count} Recovery 🔄 | "
        f"Nifty={regime_nifty.title()} | S&P={regime_sp500.title()}"
    )
    send_email(subject, html)

    # Send Telegram alert
    send_telegram(results, regime_nifty, regime_sp500, macro, today)

    total_deployed = sum(r["allocation"] for r in results)
    print(f"\n  Done. Total deployed: Rs.{int(total_deployed):,} of Rs.{TOTAL_BUDGET:,}")


if __name__ == "__main__":
    main()
