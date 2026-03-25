"""
Daily Market Screener
Covers: Indian Stocks (Nifty 500), Indian ETFs, Global ETFs, Metals/Commodities, Crypto
Sends a rich HTML email every weekday at 11:00 AM IST with full score breakdown.
GitHub Secrets required: EMAIL_ADDRESS, EMAIL_PASSWORD
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings
import smtplib
import os
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

warnings.simplefilter("ignore")

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
PORTFOLIO_SIZE    = 100000   # INR — split equally across final picks
DATA_PERIOD       = "1y"     # 1 year needed for 200 DMA
MIN_PRICE_INR     = 50
MIN_AVG_VOLUME_NS = 300000   # Indian stocks liquidity filter
MAX_PER_CATEGORY  = 6        # max picks per category
SCORE_STRONG_BUY  = 60       # minimum score for Strong Buy
SCORE_WATCH       = 40       # minimum score for Watch

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
    hist  = macd - sig
    return macd, sig, hist

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
    adx = dx.rolling(period).mean()
    return adx, pdi, mdi

def relative_strength(stock_close, bench_close, lookback=63):
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
#  SCORING ENGINE
#  Max score = 110
#  RS vs benchmark    0-30
#  Trend (20/50/200)  0-25
#  RSI quality        0-20
#  MACD momentum      0-15
#  ADX strength       0-10
#  Volume confirm     0-10
# ══════════════════════════════════════════════════════

def score_asset(ticker, df, bench_close, category, regime):
    try:
        close  = df["Close"].squeeze()
        volume = df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(dtype=float)
        high   = df["High"].squeeze()
        low    = df["Low"].squeeze()

        if len(close) < 60:
            return None

        price = float(close.iloc[-1])
        if np.isnan(price) or price <= 0:
            return None

        # Liquidity filter for Indian stocks only
        if category == "Indian Stock" and not volume.empty:
            avg_vol = float(volume.tail(20).mean())
            if price < MIN_PRICE_INR or avg_vol < MIN_AVG_VOLUME_NS:
                return None

        # Relative Strength
        rs = relative_strength(close, bench_close, lookback=63)
        if rs is None:
            return None
        if rs < -0.15:
            return None
        rs_score = min(30, max(0, (rs + 0.05) * 150))

        # Multi-timeframe Trend
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

        # RSI
        rsi_s   = compute_rsi(close)
        rsi_val = float(rsi_s.iloc[-1])
        if np.isnan(rsi_val):
            return None
        if rsi_val > 75:
            rsi_score = 0
        elif rsi_val < 30:
            rsi_score = 5
        elif 45 <= rsi_val <= 65:
            rsi_score = 20
        elif 30 <= rsi_val < 45:
            rsi_score = 12
        else:
            rsi_score = 8

        # MACD
        _, _, hist = compute_macd(close)
        hist_now  = float(hist.iloc[-1])
        hist_prev = float(hist.iloc[-2]) if len(hist) > 1 else hist_now
        macd_score = 0
        if hist_now > 0:          macd_score += 10
        if hist_now > hist_prev:  macd_score += 5

        # ADX
        adx_val   = None
        adx_score = 0
        try:
            adx_s, pdi_s, mdi_s = compute_adx(df)
            adx_val = float(adx_s.iloc[-1])
            pdi_val = float(pdi_s.iloc[-1])
            mdi_val = float(mdi_s.iloc[-1])
            if adx_val > 25 and pdi_val > mdi_val:    adx_score = 10
            elif adx_val > 20 and pdi_val > mdi_val:  adx_score = 6
        except Exception:
            pass

        # Volume
        vol_score = 0
        vol_ratio = None
        if not volume.empty and len(volume) >= 20:
            avg_vol   = float(volume.tail(20).mean())
            vol_ratio = float(volume.iloc[-1]) / avg_vol if avg_vol > 0 else 1.0
            vol_score = min(10, max(0, (vol_ratio - 0.8) * 12))

        # Dip from 3-month high
        period_high = float(close.tail(63).max())
        dip_pct     = (period_high - price) / period_high * 100

        # Regime adjustment
        rm = {"bull": 1.0, "neutral": 0.9, "bear": 0.75}[regime]
        raw_score   = rs_score + trend_score + rsi_score + macd_score + adx_score + vol_score
        final_score = round(raw_score * rm, 1)

        if final_score >= SCORE_STRONG_BUY:
            tier = "Strong Buy"
        elif final_score >= SCORE_WATCH:
            tier = "Watch"
        else:
            return None

        return {
            "ticker":   ticker,
            "name":     get_display_name(ticker),
            "category": category,
            "price":    round(price, 4),
            "tier":     tier,
            "score":    final_score,
            "dip":      round(dip_pct, 2),
            "rs_pct":   round(rs * 100, 2),
            "rsi":      round(rsi_val, 1),
            "macd_hist":round(hist_now, 6),
            "adx":      round(adx_val, 1) if adx_val is not None else "n/a",
            "vol_ratio":round(vol_ratio, 2) if vol_ratio is not None else "n/a",
            "ma_vals":  ma_vals,
            "breakdown": {
                "RS vs Benchmark": round(rs_score, 1),
                "Trend (DMA)":     trend_score,
                "RSI Quality":     rsi_score,
                "MACD Momentum":   macd_score,
                "ADX Strength":    adx_score,
                "Volume":          round(vol_score, 1),
            }
        }

    except Exception:
        return None

# ══════════════════════════════════════════════════════
#  HTML EMAIL BUILDER
# ══════════════════════════════════════════════════════

TIER_BADGE = {
    "Strong Buy": ("background:#dcfce7;color:#15803d;border:1px solid #86efac", "STRONG BUY"),
    "Watch":      ("background:#fef9c3;color:#a16207;border:1px solid #fde047", "WATCH"),
}

REGIME_STYLE = {
    "bull":    ("background:#f0fdf4;border-left:4px solid #16a34a", "Bull Market",         "#15803d"),
    "neutral": ("background:#fffbeb;border-left:4px solid #f59e0b", "Neutral / Sideways",  "#a16207"),
    "bear":    ("background:#fef2f2;border-left:4px solid #dc2626", "Bear Market - Caution","#dc2626"),
}

def format_buy_amount(price, currency, usd_to_inr, per_asset_inr):
    if currency == "INR":
        return f"Rs.{int(per_asset_inr):,}", ""
    else:
        price_inr = price * usd_to_inr
        units = per_asset_inr / price_inr
        return f"Rs.{int(per_asset_inr):,}", f"approx {units:.4f} units @ ${price:.2f} (1 USD = Rs.{usd_to_inr:.2f})"

def ma_trend_label(price, ma_vals):
    parts = []
    for k in ["MA20", "MA50", "MA200"]:
        if k in ma_vals:
            arrow = "above" if price > ma_vals[k] else "below"
            color = "#16a34a" if price > ma_vals[k] else "#dc2626"
            parts.append(f"<span style='color:{color};font-weight:600'>{k}: {arrow}</span>")
    return " &nbsp;|&nbsp; ".join(parts)

def build_asset_card(n, r, usd_to_inr, per_asset_inr):
    meta                = CATEGORY_META[r["category"]]
    tier_style, tier_label = TIER_BADGE[r["tier"]]
    buy_str, fx_note    = format_buy_amount(r["price"], meta["currency"], usd_to_inr, per_asset_inr)
    trend_html          = ma_trend_label(r["price"], r["ma_vals"])
    price_str           = f"${r['price']:.4f}" if meta["currency"] == "USD" else f"Rs.{r['price']:.2f}"
    rs_color            = "#16a34a" if r["rs_pct"] >= 0 else "#dc2626"

    breakdown_rows = "".join(
        f"<tr>"
        f"<td style='padding:3px 12px 3px 0;color:#6b7280;font-size:12px;white-space:nowrap'>{k}</td>"
        f"<td style='padding:3px 4px'>"
        f"<div style='height:10px;width:{min(int(v * 2), 220)}px;background:#3b82f6;border-radius:4px;display:inline-block;vertical-align:middle'></div>"
        f"</td>"
        f"<td style='padding:3px 0 3px 8px;font-size:12px;font-weight:700;color:#1d4ed8'>{v} / max</td>"
        f"</tr>"
        for k, v in r["breakdown"].items()
    )

    max_scores = {
        "RS vs Benchmark": 30,
        "Trend (DMA)":     25,
        "RSI Quality":     20,
        "MACD Momentum":   15,
        "ADX Strength":    10,
        "Volume":          10,
    }
    breakdown_rows = "".join(
        f"<tr>"
        f"<td style='padding:3px 12px 3px 0;color:#6b7280;font-size:12px;white-space:nowrap'>{k}</td>"
        f"<td style='padding:3px 4px'>"
        f"<div style='height:10px;width:{min(int(v * 220 / max_scores.get(k, 30)), 220)}px;"
        f"background:#3b82f6;border-radius:4px;display:inline-block;vertical-align:middle'></div>"
        f"</td>"
        f"<td style='padding:3px 0 3px 8px;font-size:12px;font-weight:700;color:#1d4ed8'>"
        f"{v} / {max_scores.get(k, '?')}</td>"
        f"</tr>"
        for k, v in r["breakdown"].items()
    )

    return f"""
<div style='border:1px solid #e5e7eb;border-radius:12px;padding:20px;margin-bottom:20px;
            background:#ffffff;font-family:-apple-system,BlinkMacSystemFont,sans-serif'>

  <table width='100%' cellpadding='0' cellspacing='0'>
    <tr>
      <td valign='top'>
        <div style='font-size:12px;color:#6b7280;font-weight:600;text-transform:uppercase;
                    letter-spacing:0.05em'>{n}. {meta["label"]}</div>
        <div style='font-size:18px;font-weight:800;color:#111;margin:4px 0 2px'>{r["name"]}</div>
        <div style='font-size:13px;color:#9ca3af'>{r["ticker"]} &nbsp;|&nbsp; Price: {price_str}</div>
      </td>
      <td valign='top' align='right' style='white-space:nowrap'>
        <div style='display:inline-block;padding:4px 14px;border-radius:20px;
                    font-size:12px;font-weight:800;{tier_style}'>{tier_label}</div>
        <div style='font-size:26px;font-weight:900;color:#1d4ed8;margin-top:6px'>{buy_str}</div>
        {"<div style='font-size:11px;color:#9ca3af;margin-top:2px'>" + fx_note + "</div>" if fx_note else ""}
      </td>
    </tr>
  </table>

  <div style='margin:16px 0 12px'>
    <table cellpadding='0' cellspacing='8'>
      <tr>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 14px;text-align:center'>
          <div style='font-size:11px;color:#94a3b8;margin-bottom:2px'>Total Score</div>
          <div style='font-size:20px;font-weight:900;color:#1d4ed8'>{r["score"]}<span style='font-size:11px;color:#94a3b8'>/110</span></div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 14px;text-align:center'>
          <div style='font-size:11px;color:#94a3b8;margin-bottom:2px'>Dip from 3M High</div>
          <div style='font-size:18px;font-weight:800;color:#d97706'>{r["dip"]}%</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 14px;text-align:center'>
          <div style='font-size:11px;color:#94a3b8;margin-bottom:2px'>RS vs Benchmark</div>
          <div style='font-size:18px;font-weight:800;color:{rs_color}'>{r["rs_pct"]:+.2f}%</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 14px;text-align:center'>
          <div style='font-size:11px;color:#94a3b8;margin-bottom:2px'>RSI (14)</div>
          <div style='font-size:18px;font-weight:800;color:#374151'>{r["rsi"]}</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 14px;text-align:center'>
          <div style='font-size:11px;color:#94a3b8;margin-bottom:2px'>ADX</div>
          <div style='font-size:18px;font-weight:800;color:#374151'>{r["adx"]}</div>
        </td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 14px;text-align:center'>
          <div style='font-size:11px;color:#94a3b8;margin-bottom:2px'>Volume Ratio</div>
          <div style='font-size:18px;font-weight:800;color:#374151'>{r["vol_ratio"]}x</div>
        </td>
      </tr>
    </table>
  </div>

  <div style='font-size:12px;margin-bottom:14px;padding:8px 12px;
              background:#f8fafc;border-radius:6px'>{trend_html}</div>

  <div style='border-top:1px solid #f1f5f9;padding-top:12px'>
    <div style='font-size:11px;color:#9ca3af;font-weight:700;
                text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px'>Score Breakdown</div>
    <table cellpadding='0' cellspacing='0'>{breakdown_rows}</table>
  </div>

</div>
"""

def build_email(results, regime_nifty, regime_sp500, usd_to_inr, date_str):
    strong  = [r for r in results if r["tier"] == "Strong Buy"]
    watch   = [r for r in results if r["tier"] == "Watch"]
    n_total = len(results)
    per_asset = PORTFOLIO_SIZE / n_total if n_total > 0 else PORTFOLIO_SIZE / 10

    rn_style, rn_label, rn_color = REGIME_STYLE[regime_nifty]
    rs_style, rs_label, rs_color = REGIME_STYLE[regime_sp500]

    strong_cards = "".join(
        build_asset_card(i + 1, r, usd_to_inr, per_asset) for i, r in enumerate(strong)
    ) if strong else "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Strong Buy signals today.</p>"

    watch_cards = "".join(
        build_asset_card(len(strong) + i + 1, r, usd_to_inr, per_asset) for i, r in enumerate(watch)
    ) if watch else "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Watch signals today.</p>"

    html = f"""<!DOCTYPE html>
<html><head><meta charset='utf-8'>
<meta name='viewport' content='width=device-width,initial-scale=1'>
</head>
<body style='margin:0;padding:0;background:#f1f5f9;
             font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'>
<div style='max-width:700px;margin:0 auto;padding:24px 16px'>

  <!-- HEADER -->
  <div style='background:#1d4ed8;border-radius:14px 14px 0 0;padding:28px 28px 24px'>
    <div style='font-size:24px;font-weight:900;color:#fff'>Daily Market Screener</div>
    <div style='font-size:13px;color:#bfdbfe;margin-top:4px'>
      {date_str} &nbsp;|&nbsp; 1 USD = Rs.{usd_to_inr:.2f} &nbsp;|&nbsp;
      Portfolio: Rs.{PORTFOLIO_SIZE:,} split equally across {n_total} picks
    </div>
    <table cellpadding='0' cellspacing='0' style='margin-top:20px'>
      <tr>
        <td style='padding-right:28px'>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Strong Buy</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>{len(strong)}</div>
        </td>
        <td style='padding-right:28px'>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Watch</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>{len(watch)}</div>
        </td>
        <td style='padding-right:28px'>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Total Signals</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>{n_total}</div>
        </td>
        <td>
          <div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Per Asset</div>
          <div style='font-size:32px;font-weight:900;color:#fff'>Rs.{int(per_asset):,}</div>
        </td>
      </tr>
    </table>
  </div>

  <!-- REGIME BANNERS -->
  <table width='100%' cellpadding='6' cellspacing='0' style='margin:14px 0'>
    <tr>
      <td width='50%'>
        <div style='{rn_style};padding:12px 16px;border-radius:8px'>
          <div style='font-size:11px;color:{rn_color};font-weight:700;
                      text-transform:uppercase;letter-spacing:0.05em'>Nifty 50 Regime</div>
          <div style='font-size:15px;font-weight:800;color:{rn_color};margin-top:2px'>{rn_label}</div>
        </div>
      </td>
      <td width='50%'>
        <div style='{rs_style};padding:12px 16px;border-radius:8px'>
          <div style='font-size:11px;color:{rs_color};font-weight:700;
                      text-transform:uppercase;letter-spacing:0.05em'>S&amp;P 500 Regime</div>
          <div style='font-size:15px;font-weight:800;color:{rs_color};margin-top:2px'>{rs_label}</div>
        </div>
      </td>
    </tr>
  </table>

  <!-- STRONG BUY SECTION -->
  <div style='font-size:15px;font-weight:800;color:#15803d;
              margin:24px 0 14px;padding-bottom:8px;border-bottom:2px solid #bbf7d0'>
    STRONG BUY SIGNALS ({len(strong)})
  </div>
  {strong_cards}

  <!-- WATCH SECTION -->
  <div style='font-size:15px;font-weight:800;color:#a16207;
              margin:28px 0 14px;padding-bottom:8px;border-bottom:2px solid #fde68a'>
    WATCH LIST ({len(watch)})
  </div>
  {watch_cards}

  <!-- FOOTER -->
  <div style='margin-top:32px;padding:16px;background:#fff;border-radius:10px;
              font-size:11px;color:#9ca3af;border:1px solid #e5e7eb;line-height:1.6'>
    <strong style='color:#6b7280'>How scores work:</strong> Each asset is scored out of 110 across
    6 factors: RS vs Benchmark (max 30) + Trend / DMA (max 25) + RSI Quality (max 20) +
    MACD Momentum (max 15) + ADX Strength (max 10) + Volume Confirmation (max 10).
    Score is then adjusted for market regime (Bull x1.0, Neutral x0.9, Bear x0.75).
    Strong Buy = 60+, Watch = 40-59.
    <br><br>
    <strong style='color:#6b7280'>Disclaimer:</strong> This is an automated technical screener
    for informational purposes only. It does not constitute financial advice. Always conduct
    your own research before investing. Past signals do not guarantee future returns.
  </div>

</div>
</body></html>"""

    return html, per_asset

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
    today = datetime.now().strftime("%d %b %Y")
    print(f"\n{'='*55}")
    print(f"  Daily Screener — {today}")
    print(f"{'='*55}\n")

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
            "ASIANPAINT","MARUTI","TITAN","SUNPHARMA","BAJFINANCE","WIPRO","HCLTECH"
        ]
        nse_stocks = [s + ".NS" for s in fallback]

    all_tickers = (
        nse_stocks
        + list(INDIAN_ETFS.keys())
        + list(GLOBAL_ETFS.keys())
        + list(METALS_COMMODITIES.keys())
        + list(CRYPTO.keys())
    )

    extra    = ["^NSEI", "^GSPC", "BTC-USD", "USDINR=X"]
    dl_list  = list(dict.fromkeys(all_tickers + extra))

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

    # USD/INR rate
    try:
        usd_to_inr = float(raw["USDINR=X"]["Close"].dropna().iloc[-1])
    except Exception:
        usd_to_inr = 84.0
    print(f"\n  USD/INR rate: {usd_to_inr:.2f}")

    # Benchmark series
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
    print(f"  Nifty regime : {regime_nifty.upper()}")
    print(f"  S&P 500 regime: {regime_sp500.upper()}\n")

    # Get list of tickers available in downloaded data
    try:
        tickers_in_raw = set(raw.columns.get_level_values(0))
    except Exception:
        tickers_in_raw = set()

    results    = []
    cat_counts = {}

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

            df_a = df.loc[common].copy()
            b_a  = bench.loc[common].copy()

            if cat in ("Indian Stock", "Indian ETF"):
                regime = regime_nifty
            elif cat == "Crypto":
                regime = "neutral"
            else:
                regime = regime_sp500

            result = score_asset(ticker, df_a, b_a, cat, regime)
            if result is None:
                continue

            cc = cat_counts.get(cat, 0)
            if result["tier"] == "Watch" and cc >= MAX_PER_CATEGORY:
                continue
            cat_counts[cat] = cc + 1
            results.append(result)

        except Exception:
            continue

    # Sort: Strong Buy first, then by score descending
    tier_order = {"Strong Buy": 0, "Watch": 1}
    results.sort(key=lambda x: (tier_order[x["tier"]], -x["score"]))

    strong = [r for r in results if r["tier"] == "Strong Buy"]
    watch  = [r for r in results if r["tier"] == "Watch"]

    print(f"  Results: {len(strong)} Strong Buy  |  {len(watch)} Watch\n")
    for r in results:
        meta      = CATEGORY_META[r["category"]]
        price_str = f"${r['price']:.2f}" if meta["currency"] == "USD" else f"Rs.{r['price']:.2f}"
        print(f"  [{r['tier']:11s}] {r['ticker']:18s} {r['category']:18s} "
              f"Score={r['score']:5.1f}  RSI={r['rsi']:5.1f}  "
              f"RS={r['rs_pct']:+.1f}%  Dip={r['dip']:.1f}%  {price_str}")

    html, per_asset = build_email(results, regime_nifty, regime_sp500, usd_to_inr, today)
    subject = (
        f"[Screener {today}] "
        f"{len(strong)} Strong Buy | {len(watch)} Watch | "
        f"Nifty={regime_nifty.title()} | S&P={regime_sp500.title()}"
    )
    send_email(subject, html)
    print(f"\n  Done. Per-asset allocation: Rs.{int(per_asset):,}")


if __name__ == "__main__":
    main()
