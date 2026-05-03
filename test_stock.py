"""
Daily Market Screener — v5
Singapore-based investor edition

Key change in v5: DUAL SCORING MODES
  Mode 1 — Dip Buy (Indian Stocks, Indian ETFs)
    Objective: short-term recovery, 1-3 month horizon
    RSI 45-65 = ideal, RSI 70+ = overbought warning
    Benchmark-relative RS
    Bear regime = heavy penalty

  Mode 2 — Momentum/Trend Ride (Global ETFs, Crypto)
    Objective: 6-12 month trend capture
    RSI 55-75 = strong signal, RSI 80+ = slight caution only
    Absolute return RS (not relative to BTC for crypto)
    Dual RS lookback: 3M + 1M (catches recent breakouts)
    Breakout detection: near 52W high + volume surge = bonus
    Crypto: BTC regime sets floor, individual DMA confirms
    Global ETF: S&P regime as floor, individual DMA confirms

Other changes:
  - Expanded crypto universe: BTC, ETH, SOL, BNB, XRP, ADA, AVAX, DOT, LINK, MATIC, DOGE, TON-USD, SUI-USD
  - Expanded thematic ETFs: BOTZ, AIQ, FINX, CIBR, ICLN, HACK, ROBO, JETS, ARKW, ARKG
  - Budget SGD 4,000 | Indian 25% | Global ETF 40% | Metals 20% | Crypto 15%
"""

import yfinance as yf
import pandas as pd
import numpy as np
import warnings, smtplib, os, json, urllib.request
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from datetime import datetime

warnings.simplefilter("ignore")

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
TOTAL_BUDGET_SGD  = 4000
DATA_PERIOD       = "1y"
MIN_PRICE_INR     = 50
MIN_AVG_VOL_NS    = 300000
GLOBAL_MAX_PICKS  = 25
INDIAN_PICK_CAP   = 0.25       # max 25% of picks = ~6 Indian
SCORE_STRONG_BUY  = 60
SCORE_WATCH       = 40
HISTORY_FILE      = "screener_history.json"

CATEGORY_CAPS = {"indian": 0.25, "global": 0.40, "metal": 0.20, "crypto": 0.15}

# ══════════════════════════════════════════════════════
#  ASSET UNIVERSE
# ══════════════════════════════════════════════════════

GLOBAL_ETFS = {
    # US Broad
    "SPY":"SPDR S&P 500 ETF","QQQ":"Invesco QQQ (Nasdaq 100)","VTI":"Vanguard Total Market",
    "VOO":"Vanguard S&P 500","IVV":"iShares Core S&P 500","IWM":"iShares Russell 2000",
    "DIA":"SPDR Dow Jones",
    # Developed Markets
    "EFA":"iShares MSCI EAFE","VEA":"Vanguard Developed Markets","IEFA":"iShares Core MSCI EAFE",
    "EWJ":"iShares MSCI Japan","EWG":"iShares MSCI Germany","EWU":"iShares MSCI UK",
    "EWA":"iShares MSCI Australia","EWC":"iShares MSCI Canada","EWZ":"iShares MSCI Brazil","EWY":"iShares MSCI South Korea",
    # China / EM
    "MCHI":"iShares MSCI China","FXI":"iShares China Large Cap","KWEB":"KraneShares China Internet",
    "EEM":"iShares MSCI Emerging Markets","VWO":"Vanguard Emerging Markets",
    # Middle East
    "KSA":"iShares MSCI Saudi Arabia","UAE":"iShares MSCI UAE",
    # Sectors
    "XLK":"Technology Select SPDR","XLF":"Financial Select SPDR","XLE":"Energy Select SPDR",
    "XLV":"Health Care Select SPDR","XLI":"Industrials Select SPDR","XLP":"Consumer Staples SPDR",
    # Semis & Tech
    "SOXX":"iShares Semiconductor ETF","SMH":"VanEck Semiconductor ETF",
    # Thematic — AI / Robotics / Innovation
    "BOTZ":"Global X Robotics & AI ETF","AIQ":"Global X AI & Technology ETF",
    "ROBO":"ROBO Global Robotics ETF","ARKK":"ARK Innovation ETF","ARKW":"ARK Next Gen Internet ETF",
    "ARKG":"ARK Genomic Revolution ETF",
    # Thematic — Fintech / Cyber / Clean
    "FINX":"Global X Fintech ETF","CIBR":"First Trust Cybersecurity ETF",
    "HACK":"ETFMG Prime Cybersecurity ETF","ICLN":"iShares Global Clean Energy ETF",
    # Other thematic
    "JETS":"US Global Jets ETF (Airlines)",
}

METALS_COMMODITIES = {
    "GLD":"SPDR Gold Shares","IAU":"iShares Gold Trust","SLV":"iShares Silver Trust",
    "PPLT":"Aberdeen Platinum ETF","PALL":"Aberdeen Palladium ETF",
    "USO":"United States Oil Fund","BNO":"Brent Oil Fund","UNG":"US Natural Gas Fund",
    "CPER":"US Copper ETF","WEAT":"Teucrium Wheat","CORN":"Teucrium Corn",
    "SOYB":"Teucrium Soybean","DBA":"Invesco DB Agriculture","DJP":"iPath Bloomberg Commodity","GSG":"iShares GSCI Commodity",
}

CRYPTO = {
    "BTC-USD":"Bitcoin","ETH-USD":"Ethereum","SOL-USD":"Solana",
    "BNB-USD":"BNB","XRP-USD":"XRP","ADA-USD":"Cardano",
    "AVAX-USD":"Avalanche","DOT-USD":"Polkadot","LINK-USD":"Chainlink",
    "MATIC-USD":"Polygon","DOGE-USD":"Dogecoin",
    "TON11419-USD":"Toncoin","SUI20947-USD":"Sui",
}

INDIAN_ETFS = {
    "NIFTYBEES.NS":"Nippon Nifty BeES","JUNIORBEES.NS":"Nippon Junior BeES",
    "BANKBEES.NS":"Nippon Bank BeES","ITBEES.NS":"Nippon IT BeES",
    "GOLDBEES.NS":"Nippon Gold BeES","SILVERBEES.NS":"Nippon Silver BeES",
    "ICICIB22.NS":"ICICI Bharat 22 ETF","CPSE.NS":"CPSE ETF",
    "MAN50ETF.NS":"Mirae Asset Nifty 50 ETF","NETFIT.NS":"Nippon Nifty IT ETF",
    "PSUBNKBEES.NS":"Nippon PSU Bank BeES","PHARMABEES.NS":"Nippon Pharma BeES",
}

INDIAN_MF_LIST = [
    {"name":"Mirae Asset Large Cap Fund",      "category":"Large Cap",             "amc":"Mirae Asset",   "why":"Consistent top-quartile performer. Diversified across Nifty 100.",                                           "suggested_sip":15000,"risk":"Moderate"},
    {"name":"Axis Bluechip Fund",              "category":"Large Cap",             "amc":"Axis MF",       "why":"Quality-focused, lower drawdowns. Good for conservative equity exposure.",                                   "suggested_sip":10000,"risk":"Moderate"},
    {"name":"Parag Parikh Flexi Cap Fund",     "category":"Flexi Cap",             "amc":"PPFAS MF",      "why":"Invests up to 35% in international stocks (Google, Meta, Amazon). Natural global diversification.",          "suggested_sip":20000,"risk":"Moderate"},
    {"name":"HDFC Flexi Cap Fund",             "category":"Flexi Cap",             "amc":"HDFC MF",       "why":"One of India's most consistent flexi cap funds. Active large/mid allocation.",                              "suggested_sip":15000,"risk":"Moderate"},
    {"name":"Kotak Emerging Equity Fund",      "category":"Mid Cap",               "amc":"Kotak MF",      "why":"Strong mid-cap track record. Outperformed benchmark over 7 of last 10 years.",                             "suggested_sip":10000,"risk":"Moderately High"},
    {"name":"Nippon India Growth Fund",        "category":"Mid Cap",               "amc":"Nippon India",  "why":"One of India's oldest mid-cap funds. Proven long-term compounding over 5Y+ horizon.",                      "suggested_sip":10000,"risk":"Moderately High"},
    {"name":"SBI Small Cap Fund",              "category":"Small Cap",             "amc":"SBI MF",        "why":"Best-in-class small cap by consistency. Only for 7Y+ horizon.",                                             "suggested_sip":5000, "risk":"High"},
    {"name":"Axis Small Cap Fund",             "category":"Small Cap",             "amc":"Axis MF",       "why":"Quality-first in small caps — lower volatility than peers.",                                                "suggested_sip":5000, "risk":"High"},
    {"name":"Mirae Asset Tax Saver Fund",      "category":"ELSS",                  "amc":"Mirae Asset",   "why":"Best ELSS by risk-adjusted returns. 3Y lock-in, 80C benefit up to Rs.1.5L/year.",                          "suggested_sip":12500,"risk":"Moderate"},
    {"name":"Quant Tax Plan",                  "category":"ELSS",                  "amc":"Quant MF",      "why":"Quantitative model-driven ELSS. Higher risk but strong alpha generation.",                                  "suggested_sip":10000,"risk":"Moderately High"},
    {"name":"Motilal Oswal Nasdaq 100 FOF",    "category":"International / US",    "amc":"Motilal Oswal", "why":"Tracks Nasdaq 100 — Apple, Microsoft, Nvidia, Google exposure via Indian MF. No LRS needed.",               "suggested_sip":10000,"risk":"High"},
    {"name":"DSP World Gold Fund",             "category":"International / Commodity","amc":"DSP MF",     "why":"Global gold mining companies. Higher beta to gold price. Complements physical gold SIP.",                   "suggested_sip":5000, "risk":"High"},
]

CATEGORY_META = {
    "Indian Stock":    {"benchmark":"^NSEI",   "currency":"INR","label":"Indian Stock",    "mode":"dip"},
    "Indian ETF":      {"benchmark":"^NSEI",   "currency":"INR","label":"Indian ETF",      "mode":"dip"},
    "Global ETF":      {"benchmark":"^GSPC",   "currency":"USD","label":"Global ETF",      "mode":"momentum"},
    "Metal/Commodity": {"benchmark":"^GSPC",   "currency":"USD","label":"Metal/Commodity", "mode":"dip"},
    "Crypto":          {"benchmark":"BTC-USD", "currency":"USD","label":"Crypto",          "mode":"momentum"},
}

CATEGORY_ORDER  = ["Indian Stock","Indian ETF","Global ETF","Metal/Commodity","Crypto"]
CATEGORY_COLORS = {"Indian Stock":"#1d4ed8","Indian ETF":"#7c3aed","Global ETF":"#0369a1","Metal/Commodity":"#b45309","Crypto":"#0f766e"}
MF_CAT_COLORS   = {"Large Cap":"#1d4ed8","Flexi Cap":"#7c3aed","Mid Cap":"#0369a1","Small Cap":"#dc2626","ELSS":"#15803d","International / US":"#b45309","International / Commodity":"#0f766e"}

def get_category(t):
    if t in GLOBAL_ETFS: return "Global ETF"
    if t in METALS_COMMODITIES: return "Metal/Commodity"
    if t in CRYPTO: return "Crypto"
    if t in INDIAN_ETFS: return "Indian ETF"
    return "Indian Stock"

def get_display_name(t):
    return GLOBAL_ETFS.get(t) or METALS_COMMODITIES.get(t) or CRYPTO.get(t) or INDIAN_ETFS.get(t) or t

def cat_pool(cat):
    if cat in ("Indian Stock","Indian ETF"): return "indian"
    if cat == "Global ETF": return "global"
    if cat == "Metal/Commodity": return "metal"
    return "crypto"

# ══════════════════════════════════════════════════════
#  FX RATES
# ══════════════════════════════════════════════════════

def get_fx_rates(raw):
    def safe(ticker, default):
        try:
            s = raw[ticker]["Close"].dropna()
            return float(s.iloc[-1]) if not s.empty else default
        except: return default
    usd_to_inr = safe("USDINR=X", 84.0)
    sgd_to_usd = safe("SGDUSD=X", 0.74)
    return usd_to_inr, sgd_to_usd * usd_to_inr, sgd_to_usd

def format_amount(sgd_amt, price, currency, usd_to_inr, sgd_to_inr, sgd_to_usd):
    primary = f"SGD {sgd_amt:,.0f}"
    if currency == "INR":
        inr = sgd_amt * sgd_to_inr
        secondary = f"≈ Rs.{inr:,.0f}  |  ~{inr/price:.1f} shares" if price > 0 else f"≈ Rs.{inr:,.0f}"
    else:
        usd = sgd_amt * sgd_to_usd
        units = sgd_amt / (price / sgd_to_usd) if price > 0 else 0
        secondary = f"≈ ${usd:,.0f}  |  ~{units:.4f} units @ ${price:.2f}"
    return primary, secondary

# ══════════════════════════════════════════════════════
#  TECHNICAL INDICATORS
# ══════════════════════════════════════════════════════

def compute_rsi(s, p=14):
    d=s.diff(); g=d.clip(lower=0).rolling(p).mean(); l=(-d.clip(upper=0)).rolling(p).mean()
    return 100 - (100/(1+g/l.replace(0,np.nan)))

def compute_macd(s, fast=12, slow=26, signal=9):
    ef=s.ewm(span=fast,adjust=False).mean(); es=s.ewm(span=slow,adjust=False).mean()
    m=ef-es; sig=m.ewm(span=signal,adjust=False).mean(); return m, sig, m-sig

def compute_adx(df, p=14):
    hi=df["High"].squeeze(); lo=df["Low"].squeeze(); cl=df["Close"].squeeze()
    tr=pd.concat([hi-lo,(hi-cl.shift()).abs(),(lo-cl.shift()).abs()],axis=1).max(axis=1)
    atr=tr.rolling(p).mean()
    pdm=hi.diff().clip(lower=0); mdm=(-lo.diff()).clip(lower=0)
    mask=pdm>=mdm; pdm[~mask]=0; mdm[mask]=0
    pdi=100*pdm.rolling(p).mean()/atr.replace(0,np.nan)
    mdi=100*mdm.rolling(p).mean()/atr.replace(0,np.nan)
    dx=100*(pdi-mdi).abs()/(pdi+mdi).replace(0,np.nan)
    return dx.rolling(p).mean(), pdi, mdi

def abs_return(close, lookback):
    """Absolute return over lookback period (not relative to benchmark)."""
    if len(close) < lookback: return None
    return float((close.iloc[-1] - close.iloc[-lookback]) / close.iloc[-lookback])

def rel_strength(stock_close, bench_close, lookback=63):
    if len(stock_close)<lookback or len(bench_close)<lookback: return None
    sr=(stock_close.iloc[-1]-stock_close.iloc[-lookback])/stock_close.iloc[-lookback]
    br=(bench_close.iloc[-1]-bench_close.iloc[-lookback])/bench_close.iloc[-lookback]
    return float(sr-br)

def rel_strength_short(stock_close, bench_close, lookback=10):
    if len(stock_close)<lookback or len(bench_close)<lookback: return None
    sr=(stock_close.iloc[-1]-stock_close.iloc[-lookback])/stock_close.iloc[-lookback]
    br=(bench_close.iloc[-1]-bench_close.iloc[-lookback])/bench_close.iloc[-lookback]
    return float(sr-br)

# ══════════════════════════════════════════════════════
#  REGIME DETECTION
# ══════════════════════════════════════════════════════

def get_regime(cl):
    cl=cl.squeeze()
    if len(cl)<200: return "neutral"
    ma50=cl.rolling(50).mean().iloc[-1]; ma200=cl.rolling(200).mean().iloc[-1]
    ma200_1m=cl.rolling(200).mean().iloc[-22]; price=cl.iloc[-1]
    if price>ma50>ma200 and (ma200-ma200_1m)/ma200_1m>0: return "bull"
    if price<ma200*0.95: return "bear"
    return "neutral"

def get_crypto_regime(btc_close, asset_close):
    """
    BTC regime sets floor. Individual DMA confirms or reduces.
    Returns multiplier directly.
    """
    btc_regime = get_regime(btc_close)
    # Individual asset DMA check
    cl = asset_close.squeeze()
    if len(cl) < 50:
        individual_bull = False
        individual_bear = False
    else:
        ma50  = cl.rolling(50).mean().iloc[-1]
        ma200 = cl.rolling(200).mean().iloc[-1] if len(cl) >= 200 else ma50
        price = cl.iloc[-1]
        individual_bull = price > ma50 and price > ma200
        individual_bear = price < ma50 * 0.9

    if btc_regime == "bull":
        if individual_bull:  return 1.15, "bull"
        if individual_bear:  return 0.95, "neutral"
        return 1.0,  "bull"
    if btc_regime == "bear":
        return 0.65, "bear"
    # neutral BTC
    if individual_bull:  return 1.0,  "neutral"
    if individual_bear:  return 0.80, "bear"
    return 0.90, "neutral"

# ══════════════════════════════════════════════════════
#  TREND DIRECTION
# ══════════════════════════════════════════════════════

def get_trend(price, ma_vals):
    m20=ma_vals.get("MA20"); m50=ma_vals.get("MA50"); m200=ma_vals.get("MA200")
    if m20 and m50 and price>m20 and m20>m50:
        return ("Strong Uptrend","#15803d","↑↑") if m200 and price>m200 else ("Uptrend","#16a34a","↑")
    if m20 and m50 and price<m20 and m20<m50:
        return ("Strong Downtrend","#dc2626","↓↓") if m200 and price<m200 else ("Downtrend","#ef4444","↓")
    return ("Sideways","#d97706","→")

# ══════════════════════════════════════════════════════
#  PRICE TARGETS
# ══════════════════════════════════════════════════════

def get_targets(price, ma_vals, close):
    above={k:v for k,v in ma_vals.items() if v and v>price}
    h3m=float(close.tail(63).max()); h52=float(close.tail(252).max())
    if above:
        nl=min(above,key=above.get); nv=above[nl]
        return {"nearest_ma_label":nl,"nearest_ma_val":round(nv,4),"upside_pct_ma":round((nv-price)/price*100,1),"three_month_high":round(h3m,4),"upside_pct_3m":round((h3m-price)/price*100,1),"above_all_mas":False}
    return {"nearest_ma_label":"52W High","nearest_ma_val":round(h52,4),"upside_pct_ma":round((h52-price)/price*100,1),"three_month_high":round(h3m,4),"upside_pct_3m":round((h3m-price)/price*100,1),"above_all_mas":True}

# ══════════════════════════════════════════════════════
#  RECOVERY WATCH (Mode 1 only)
# ══════════════════════════════════════════════════════

def recovery_watch(regime, rsi, price, ma_vals, close, bench):
    if regime not in ("bear","neutral") or not (35<=rsi<=52): return False
    m200=ma_vals.get("MA200")
    if m200 and price<m200*0.85: return False
    rsl=rel_strength(close,bench,63); rss=rel_strength_short(close,bench,10)
    return rsl is not None and rss is not None and rss>rsl

# ══════════════════════════════════════════════════════
#  PLAIN ENGLISH REASON
# ══════════════════════════════════════════════════════

def build_reason(r):
    parts=[]; bd=r["breakdown"]; mode=r.get("scoring_mode","dip")
    if mode=="momentum":
        # Momentum-specific language
        ar=r.get("abs_return_3m",0)
        if ar and ar>0.15: parts.append(f"up {ar*100:.0f}% over 3 months — strong trend in play")
        elif ar and ar>0.05: parts.append(f"up {ar*100:.0f}% over 3 months")
        ar1=r.get("abs_return_1m",0)
        if ar1 and ar1>0.08: parts.append(f"accelerating with +{ar1*100:.0f}% in last month alone")
        if r.get("breakout"): parts.append("breaking to new highs with strong volume — momentum breakout")
        if r["trend_dir"] in ("Strong Uptrend","Uptrend"): parts.append(f"in a confirmed {r['trend_dir'].lower()}")
        if 55<=r["rsi"]<=80: parts.append(f"RSI at {r['rsi']} — momentum healthy for a trend ride")
        elif r["rsi"]>80: parts.append(f"RSI at {r['rsi']} — extended but strong momentum often continues")
        if bd["MACD Momentum"]==15: parts.append("MACD rising strongly")
    else:
        # Dip buy language
        if bd["RS vs Benchmark"]>=20: parts.append(f"beating benchmark by {r['rs_pct']:+.1f}% over 3 months")
        if r["trend_dir"] in ("Strong Uptrend","Uptrend"): parts.append(f"in a clear {r['trend_dir'].lower()}")
        if 45<=r["rsi"]<=65: parts.append(f"RSI healthy at {r['rsi']}")
        elif r["rsi"]<40: parts.append(f"RSI oversold at {r['rsi']} — potential bounce zone")
        if bd["MACD Momentum"]==15: parts.append("MACD positive and rising")
        if bd.get("ADX Strength")==10: parts.append(f"strong directional trend (ADX {r['adx']})")
        if r.get("recovery"): parts.append("showing early reversal signs in beaten-down regime")
    if isinstance(r["vol_ratio"],float) and r["vol_ratio"]>=1.5: parts.append(f"volume {r['vol_ratio']}x above average")
    if not parts: return "Multiple technical factors aligning — review breakdown below."
    s=", ".join(parts[:3]); return s[0].upper()+s[1:]+"."

# ══════════════════════════════════════════════════════
#  MODE 1: DIP BUY SCORER (Indian Stocks + ETFs, Metals)
#  Max 110 — same as before
# ══════════════════════════════════════════════════════

def score_dip(ticker, df, bench_close, category, regime):
    try:
        close=df["Close"].squeeze(); volume=df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(dtype=float)
        if len(close)<60: return None
        price=float(close.iloc[-1])
        if np.isnan(price) or price<=0: return None
        if category=="Indian Stock" and not volume.empty:
            if price<MIN_PRICE_INR or float(volume.tail(20).mean())<MIN_AVG_VOL_NS: return None

        rs=rel_strength(close,bench_close,63)
        if rs is None or rs<-0.15: return None
        rs_score=min(30,max(0,(rs+0.05)*150))

        trend_score=0; ma_vals={}
        for w,pts in [(20,10),(50,10),(200,5)]:
            if len(close)>=w:
                ma=float(close.rolling(w).mean().iloc[-1]); ma_vals[f"MA{w}"]=round(ma,4)
                if price>ma: trend_score+=pts
        if "MA200" in ma_vals and price<ma_vals["MA200"]*0.85: return None

        rsi_s=compute_rsi(close); rsi_val=float(rsi_s.iloc[-1])
        if np.isnan(rsi_val): return None
        rsi_score=0 if rsi_val>75 else 5 if rsi_val<30 else 20 if 45<=rsi_val<=65 else 12 if 30<=rsi_val<45 else 8

        _,_,hist=compute_macd(close); hn=float(hist.iloc[-1]); hp=float(hist.iloc[-2]) if len(hist)>1 else hn
        macd_score=(10 if hn>0 else 0)+(5 if hn>hp else 0)

        adx_val=None; adx_score=0
        try:
            adx_s,pdi_s,mdi_s=compute_adx(df); adx_val=float(adx_s.iloc[-1])
            pdi_val=float(pdi_s.iloc[-1]); mdi_val=float(mdi_s.iloc[-1])
            adx_score=10 if adx_val>25 and pdi_val>mdi_val else 6 if adx_val>20 and pdi_val>mdi_val else 0
        except: pass

        vol_score=0; vol_ratio=None
        if not volume.empty and len(volume)>=20:
            avg=float(volume.tail(20).mean()); vol_ratio=float(volume.iloc[-1])/avg if avg>0 else 1.0
            vol_score=min(10,max(0,(vol_ratio-0.8)*12))

        dip=float((close.tail(63).max()-price)/close.tail(63).max()*100)
        rm={"bull":1.0,"neutral":0.9,"bear":0.75}[regime]
        raw=rs_score+trend_score+rsi_score+macd_score+adx_score+vol_score
        final=round(raw*rm,1)
        if final>=SCORE_STRONG_BUY: tier="Strong Buy"
        elif final>=SCORE_WATCH: tier="Watch"
        else: return None

        td,tc,ta=get_trend(price,ma_vals); targets=get_targets(price,ma_vals,close)
        rec=recovery_watch(regime,rsi_val,price,ma_vals,close,bench_close)

        result={"ticker":ticker,"name":get_display_name(ticker),"category":category,"price":round(price,4),"tier":tier,"score":final,"raw_score":round(raw,1),"regime":regime,"dip":round(dip,2),"rs_pct":round(rs*100,2),"rsi":round(rsi_val,1),"macd_hist":round(hn,6),"adx":round(adx_val,1) if adx_val else "n/a","vol_ratio":round(vol_ratio,2) if vol_ratio else "n/a","ma_vals":ma_vals,"trend_dir":td,"trend_color":tc,"trend_arrow":ta,"targets":targets,"recovery":rec,"allocation_sgd":0,"reason":"","scoring_mode":"dip","breakout":False,"abs_return_3m":None,"abs_return_1m":None,
                "breakdown":{"RS vs Benchmark":round(rs_score,1),"Trend (DMA)":trend_score,"RSI Quality":rsi_score,"MACD Momentum":macd_score,"ADX Strength":adx_score,"Volume":round(vol_score,1)}}
        result["reason"]=build_reason(result); return result
    except: return None

# ══════════════════════════════════════════════════════
#  MODE 2: MOMENTUM SCORER (Global ETFs + Crypto)
#  Objective: 6-12 month trend capture
#
#  Scoring (max 110):
#   Absolute 3M Return   0-20  (raw return, not vs benchmark)
#   1M Momentum          0-15  (recent acceleration)
#   Trend (DMA)          0-20  (MA50, MA200 — simpler)
#   RSI Momentum         0-20  (55-75 ideal, 80+ slight caution)
#   MACD Momentum        0-15  (unchanged)
#   Breakout Signal      0-10  (near 52W high + volume)
#   Volume               0-10  (confirmation)
# ══════════════════════════════════════════════════════

def score_momentum(ticker, df, bench_close, btc_close, category, market_regime):
    try:
        close=df["Close"].squeeze(); volume=df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(dtype=float)
        if len(close)<60: return None
        price=float(close.iloc[-1])
        if np.isnan(price) or price<=0: return None

        # ── Absolute 3M return (not relative to benchmark) ──
        ar3m=abs_return(close,63)
        if ar3m is None: return None
        # Exclude assets in strong downtrend (>20% down in 3M)
        if ar3m < -0.20: return None
        ar3m_score=min(20,max(0,(ar3m+0.02)*80))   # 0% = 1.6pts, 10% = 9.6pts, 25% = 20pts

        # ── 1M momentum (acceleration) ──
        ar1m=abs_return(close,21)
        ar1m_score=0
        if ar1m is not None:
            if ar1m>0.15:    ar1m_score=15   # >15% in 1M = top score
            elif ar1m>0.08:  ar1m_score=12
            elif ar1m>0.03:  ar1m_score=8
            elif ar1m>0:     ar1m_score=4
            else:            ar1m_score=0    # negative 1M = no score

        # ── Trend (MA50, MA200 — simpler for momentum) ──
        trend_score=0; ma_vals={}
        for w,pts in [(20,5),(50,8),(200,7)]:
            if len(close)>=w:
                ma=float(close.rolling(w).mean().iloc[-1]); ma_vals[f"MA{w}"]=round(ma,4)
                if price>ma: trend_score+=pts
        # Don't filter out assets above MAs — that's the signal we want

        # ── RSI Momentum (reward sustained momentum) ──
        rsi_s=compute_rsi(close); rsi_val=float(rsi_s.iloc[-1])
        if np.isnan(rsi_val): return None
        if   rsi_val>=80:            rsi_score=12   # extended but still strong
        elif 65<=rsi_val<80:         rsi_score=20   # sweet spot for momentum
        elif 55<=rsi_val<65:         rsi_score=16   # healthy
        elif 45<=rsi_val<55:         rsi_score=8    # weak momentum
        elif 35<=rsi_val<45:         rsi_score=3    # losing steam
        else:                        rsi_score=0    # RSI below 35 — not a momentum asset right now

        # ── MACD ──
        _,_,hist=compute_macd(close); hn=float(hist.iloc[-1]); hp=float(hist.iloc[-2]) if len(hist)>1 else hn
        macd_score=(10 if hn>0 else 0)+(5 if hn>hp else 0)

        # ── Breakout signal ──
        h52=float(close.tail(252).max())
        near_high=(price/h52)>=0.92   # within 8% of 52W high
        breakout=False; breakout_score=0
        if not volume.empty and len(volume)>=20:
            avg_vol=float(volume.tail(20).mean()); vol_ratio_val=float(volume.iloc[-1])/avg_vol if avg_vol>0 else 1.0
            if near_high and vol_ratio_val>=1.3:
                breakout=True; breakout_score=10
            elif near_high:
                breakout_score=5
        elif near_high:
            breakout_score=5   # no volume data but near high (crypto weekends etc)

        # ── Volume ──
        vol_score=0; vol_ratio=None
        if not volume.empty and len(volume)>=20:
            avg=float(volume.tail(20).mean()); vol_ratio=float(volume.iloc[-1])/avg if avg>0 else 1.0
            vol_score=min(10,max(0,(vol_ratio-0.8)*12))

        # ── Regime multiplier ──
        dip=float((close.tail(63).max()-price)/close.tail(63).max()*100) if close.tail(63).max()>0 else 0

        if category=="Crypto":
            rm, effective_regime = get_crypto_regime(btc_close, close)
        else:
            # Global ETF: S&P regime as floor, individual ETF DMA as boost
            base_rm={"bull":1.05,"neutral":0.92,"bear":0.75}[market_regime]
            # If ETF itself is above MA50 and MA200, small boost
            if ma_vals.get("MA50") and ma_vals.get("MA200") and price>ma_vals["MA50"] and price>ma_vals["MA200"]:
                rm=min(base_rm*1.05, 1.15)
            else:
                rm=base_rm
            effective_regime=market_regime

        raw=ar3m_score+ar1m_score+trend_score+rsi_score+macd_score+breakout_score+vol_score
        final=round(raw*rm,1)

        if final>=SCORE_STRONG_BUY: tier="Strong Buy"
        elif final>=SCORE_WATCH:    tier="Watch"
        else:                       return None

        td,tc,ta=get_trend(price,ma_vals); targets=get_targets(price,ma_vals,close)

        result={"ticker":ticker,"name":get_display_name(ticker),"category":category,"price":round(price,4),"tier":tier,"score":final,"raw_score":round(raw,1),"regime":effective_regime,"dip":round(dip,2),"rs_pct":round(ar3m*100,2),"rsi":round(rsi_val,1),"macd_hist":round(hn,6),"adx":"n/a","vol_ratio":round(vol_ratio,2) if vol_ratio else "n/a","ma_vals":ma_vals,"trend_dir":td,"trend_color":tc,"trend_arrow":ta,"targets":targets,"recovery":False,"allocation_sgd":0,"reason":"","scoring_mode":"momentum","breakout":breakout,"abs_return_3m":round(ar3m,4),"abs_return_1m":round(ar1m,4) if ar1m else None,
                "breakdown":{"3M Abs Return":round(ar3m_score,1),"1M Momentum":ar1m_score,"Trend (DMA)":trend_score,"RSI Momentum":rsi_score,"MACD Momentum":macd_score,"Breakout Signal":breakout_score,"Volume":round(vol_score,1)}}
        result["reason"]=build_reason(result); return result
    except: return None

# ══════════════════════════════════════════════════════
#  ALLOCATION + INDIAN CAP
# ══════════════════════════════════════════════════════

def apply_indian_pick_cap(results):
    max_indian=int(GLOBAL_MAX_PICKS*INDIAN_PICK_CAP)
    indian=[r for r in results if r["category"] in ("Indian Stock","Indian ETF")]
    non_indian=[r for r in results if r["category"] not in ("Indian Stock","Indian ETF")]
    if len(indian)<=max_indian: return results
    kept=sorted(indian,key=lambda x:-x["score"])[:max_indian]
    print(f"  Indian cap: kept {max_indian}, dropped {len(indian)-max_indian}")
    combined=kept+non_indian; combined.sort(key=lambda x:-x["score"])
    return combined[:GLOBAL_MAX_PICKS]

def compute_allocations(results):
    pools={k:TOTAL_BUDGET_SGD*v for k,v in CATEGORY_CAPS.items()}
    by_pool={}
    for r in results: by_pool.setdefault(cat_pool(r["category"]),[]).append(r)
    allocs={}
    for pname,picks in by_pool.items():
        budget=pools[pname]; total=sum(p["score"] for p in picks)
        for p in picks: allocs[p["ticker"]]=budget*(p["score"]/total) if total>0 else budget/len(picks)
    return allocs

# ══════════════════════════════════════════════════════
#  SIGNAL HISTORY
# ══════════════════════════════════════════════════════

def load_history():
    if not os.path.exists(HISTORY_FILE): return []
    try:
        with open(HISTORY_FILE) as f: data=json.load(f)
        return data[-5:] if len(data)>5 else data
    except: return []

def save_history(results, today):
    history=load_history()
    history.append({"date":today,"picks":[{"ticker":r["ticker"],"name":r["name"],"category":r["category"],"price":r["price"],"tier":r["tier"],"score":r["score"]} for r in results]})
    history=history[-5:]
    try:
        with open(HISTORY_FILE,"w") as f: json.dump(history,f,indent=2)
    except Exception as e: print(f"  [WARN] history: {e}")

def fetch_performance(history):
    if not history: return []
    tickers=list({p["ticker"] for e in history for p in e["picks"]})
    if not tickers: return []
    try: raw=yf.download(tickers,period="10d",interval="1d",group_by="ticker",threads=True,progress=False,auto_adjust=True)
    except: return []
    def latest(t):
        try:
            s=raw[t]["Close"].dropna() if len(tickers)>1 else raw["Close"].dropna()
            return float(s.iloc[-1]) if not s.empty else None
        except: return None
    rows=[]
    for e in history:
        for p in e["picks"]:
            cur=latest(p["ticker"])
            if cur: rows.append({"date":e["date"],"ticker":p["ticker"],"name":p["name"],"category":p["category"],"entry_price":p["price"],"current_price":round(cur,4),"return_pct":round((cur-p["price"])/p["price"]*100,2),"tier":p["tier"]})
    return rows

# ══════════════════════════════════════════════════════
#  MACRO CONTEXT
# ══════════════════════════════════════════════════════

def build_macro(bn, bs, usd_to_inr, sgd_to_usd, rn, rs_):
    def lc(s):
        s=s.dropna()
        if len(s)<2: return None,None,None
        p,t=float(s.iloc[-2]),float(s.iloc[-1]); return p,t,(t-p)/p*100
    _,nc,nchg=lc(bn); _,sc,schg=lc(bs)
    sentences={("bull","bull"):"Both Nifty and S&P are in bull mode — conditions favourable across the board.",("bull","neutral"):"Nifty bullish, S&P sideways — Indian picks look stronger today.",("bull","bear"):"Nifty bullish but S&P under pressure — lean Indian over Global ETFs.",("neutral","bull"):"S&P bullish, Nifty consolidating — Global ETFs and Crypto may have the edge.",("neutral","neutral"):"Both markets sideways — focus on momentum leaders and breakout signals.",("neutral","bear"):"Nifty consolidating, S&P in downtrend — tread carefully on Global ETFs.",("bear","bull"):"Nifty under pressure, S&P strong — Global ETFs and Crypto momentum plays look interesting.",("bear","neutral"):"Nifty downtrend, S&P sideways — watch Recovery Watch signals and crypto momentum.",("bear","bear"):"Both markets in downtrend — only Strong Buy signals with clear momentum confirmation."}
    return {"nifty_close":round(nc,2) if nc else "N/A","nifty_chg":round(nchg,2) if nchg else 0,"sp_close":round(sc,2) if sc else "N/A","sp_chg":round(schg,2) if schg else 0,"usd_inr":round(usd_to_inr,2),"sgd_usd":round(sgd_to_usd,4),"sgd_inr":round(sgd_to_usd*usd_to_inr,2),"regime_note":sentences.get((rn,rs_),"Review regime carefully before acting today.")}

# ══════════════════════════════════════════════════════
#  HTML BUILDERS
# ══════════════════════════════════════════════════════

TIER_BADGE={"Strong Buy":("background:#dcfce7;color:#15803d;border:1px solid #86efac","STRONG BUY"),"Watch":("background:#fef9c3;color:#a16207;border:1px solid #fde047","WATCH")}
REGIME_STYLE={"bull":("background:#f0fdf4;border-left:4px solid #16a34a","Bull Market","#15803d"),"neutral":("background:#fffbeb;border-left:4px solid #f59e0b","Neutral / Sideways","#a16207"),"bear":("background:#fef2f2;border-left:4px solid #dc2626","Bear Market","#dc2626")}

def ma_label_html(price, ma_vals):
    parts=[]
    for k in ["MA20","MA50","MA200"]:
        if k in ma_vals:
            above=price>ma_vals[k]; c="#16a34a" if above else "#dc2626"
            parts.append(f"<span style='color:{c};font-weight:600'>{k}: {'above' if above else 'below'}</span>")
    return " &nbsp;|&nbsp; ".join(parts)

def macro_html(m):
    nc="#15803d" if m["nifty_chg"]>=0 else "#dc2626"; sc="#15803d" if m["sp_chg"]>=0 else "#dc2626"
    na="▲" if m["nifty_chg"]>=0 else "▼"; sa="▲" if m["sp_chg"]>=0 else "▼"
    return f"""<div style='background:#1e3a5f;border-radius:10px;padding:18px 20px;margin-bottom:16px'>
  <div style='font-size:12px;font-weight:700;color:#93c5fd;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:12px'>Market Snapshot</div>
  <table cellpadding='0' cellspacing='0' width='100%'><tr>
    <td style='padding-right:24px'><div style='font-size:11px;color:#93c5fd'>Nifty 50</div><div style='font-size:20px;font-weight:900;color:#fff'>{m["nifty_close"]:,}</div><div style='font-size:13px;font-weight:700;color:{nc}'>{na} {abs(m["nifty_chg"])}%</div></td>
    <td style='padding:0 24px;border-left:1px solid #2d5a8e'><div style='font-size:11px;color:#93c5fd'>S&amp;P 500</div><div style='font-size:20px;font-weight:900;color:#fff'>{m["sp_close"]:,}</div><div style='font-size:13px;font-weight:700;color:{sc}'>{sa} {abs(m["sp_chg"])}%</div></td>
    <td style='padding-left:24px;border-left:1px solid #2d5a8e'><div style='font-size:11px;color:#93c5fd'>FX Rates</div><div style='font-size:14px;font-weight:800;color:#fff'>1 SGD = Rs.{m["sgd_inr"]}<br>1 USD = Rs.{m["usd_inr"]}</div></td>
  </tr></table>
  <div style='margin-top:14px;padding-top:12px;border-top:1px solid #2d5a8e;font-size:13px;color:#bfdbfe;line-height:1.6'>💡 {m["regime_note"]}</div>
</div>"""

def perf_html(rows):
    if not rows: return ""
    r_rows=""
    for p in rows:
        rc="#15803d" if p["return_pct"]>=0 else "#dc2626"; ra="▲" if p["return_pct"]>=0 else "▼"
        cc=CATEGORY_COLORS.get(p["category"],"#374151")
        r_rows+=f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:7px 10px;font-size:11px;color:#9ca3af'>{p['date']}</td><td style='padding:7px 10px'><span style='font-size:12px;font-weight:700'>{p['ticker']}</span> <span style='font-size:10px;color:{cc};background:#f1f5f9;padding:1px 5px;border-radius:4px'>{p['category']}</span></td><td style='padding:7px 10px;font-size:12px'>{p['entry_price']:,.4f}</td><td style='padding:7px 10px;font-size:12px'>{p['current_price']:,.4f}</td><td style='padding:7px 10px;font-size:13px;font-weight:800;color:{rc}'>{ra} {abs(p['return_pct'])}%</td></tr>"
    return f"""<div style='margin-bottom:24px'><div style='font-size:15px;font-weight:800;color:#374151;margin-bottom:12px;padding-bottom:8px;border-bottom:2px solid #e5e7eb'>📈 HOW LAST PICKS PERFORMED</div>
  <table width='100%' cellpadding='0' cellspacing='0' style='border:1px solid #e5e7eb;border-radius:8px;overflow:hidden;border-collapse:collapse'>
    <thead><tr style='background:#f8fafc'><th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Date</th><th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Asset</th><th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Entry</th><th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Now</th><th style='padding:7px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Return</th></tr></thead>
    <tbody>{r_rows}</tbody></table></div>"""

def mf_html(sgd_to_inr):
    total=sum(m["suggested_sip"] for m in INDIAN_MF_LIST if m["suggested_sip"]>0)
    risk_c={"Moderate":"#15803d","Moderately High":"#d97706","High":"#dc2626"}
    cards=""
    for mf in INDIAN_MF_LIST:
        if mf["suggested_sip"]==0: continue
        cc=MF_CAT_COLORS.get(mf["category"],"#374151"); rc=risk_c.get(mf["risk"],"#374151")
        cards+=f"""<div style='border:1px solid #e5e7eb;border-left:4px solid {cc};border-radius:10px;padding:16px;margin-bottom:12px;background:#fff'>
  <table width='100%' cellpadding='0' cellspacing='0'><tr>
    <td valign='top'><div style='font-size:11px;color:{cc};font-weight:700;text-transform:uppercase'>{mf["category"]}</div><div style='font-size:15px;font-weight:800;color:#111;margin:3px 0'>{mf["name"]}</div><div style='font-size:11px;color:#9ca3af'>{mf["amc"]}</div></td>
    <td valign='top' align='right' style='white-space:nowrap;padding-left:12px'><div style='font-size:22px;font-weight:900;color:#1d4ed8'>Rs.{mf["suggested_sip"]:,}</div><div style='font-size:11px;color:#9ca3af'>≈ SGD {mf["suggested_sip"]/sgd_to_inr:,.0f}/month</div><span style='background:{rc}20;color:{rc};border:1px solid {rc}50;border-radius:10px;font-size:11px;font-weight:700;padding:2px 8px'>Risk: {mf["risk"]}</span></td>
  </tr></table>
  <div style='margin-top:10px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px;padding:8px 12px;font-size:12px;color:#374151;line-height:1.6'><strong style='color:#a16207'>Why:</strong> {mf["why"]}</div>
</div>"""
    return f"""<div style='margin-top:32px'><div style='font-size:15px;font-weight:800;color:#7c3aed;margin-bottom:8px;padding-bottom:8px;border-bottom:2px solid #e9d5ff'>🏦 INDIAN MF SIP RECOMMENDATIONS</div>
<div style='font-size:12px;color:#6b7280;margin-bottom:14px;line-height:1.6'>Standing SIP — invest monthly via Indian bank. Total: <strong>Rs.{total:,}/month</strong> (≈ SGD {total/sgd_to_inr:,.0f}/month). Review annually.</div>{cards}</div>"""

def summary_html(results, usd_to_inr, sgd_to_inr, sgd_to_usd):
    by_cat={cat:[] for cat in CATEGORY_ORDER}
    for r in results:
        if r["category"] in by_cat: by_cat[r["category"]].append(r)
    rank={r["ticker"]:i+1 for i,r in enumerate(results)}
    sections=""
    for cat in CATEGORY_ORDER:
        items=by_cat[cat]
        if not items: continue
        cc=CATEGORY_COLORS.get(cat,"#374151"); meta=CATEGORY_META[cat]; rows=""
        for r in items:
            ps=f"${r['price']:.2f}" if meta["currency"]=="USD" else f"Rs.{r['price']:.2f}"
            tc_="#15803d" if r["tier"]=="Strong Buy" else "#a16207"; tb="#dcfce7" if r["tier"]=="Strong Buy" else "#fef9c3"
            rec="<span style='background:#ede9fe;color:#7c3aed;font-size:10px;font-weight:700;padding:1px 5px;border-radius:10px;margin-left:4px'>🔄</span>" if r.get("recovery") else ""
            brk="<span style='background:#fef3c7;color:#b45309;font-size:10px;font-weight:700;padding:1px 5px;border-radius:10px;margin-left:4px'>🚀</span>" if r.get("breakout") else ""
            mode_badge=f"<span style='font-size:9px;color:#6366f1;background:#eef2ff;padding:1px 4px;border-radius:4px;margin-left:3px'>{'momentum' if r.get('scoring_mode')=='momentum' else 'dip'}</span>"
            t=r["targets"]; ml="52W High" if t.get("above_all_mas") else t["nearest_ma_label"]
            ar=""
            if r.get("abs_return_3m") is not None: ar=f"<div style='font-size:10px;color:#15803d;font-weight:600'>+{r['abs_return_3m']*100:.1f}% (3M)</div>"
            rows+=f"""<tr style='border-bottom:1px solid #f1f5f9'>
              <td style='padding:8px 10px;font-size:13px;font-weight:700;color:#374151'>{rank[r["ticker"]]}</td>
              <td style='padding:8px 10px'><div style='font-size:13px;font-weight:800;color:#111'>{r["ticker"]}{mode_badge}</div><div style='font-size:11px;color:#9ca3af'>{r["name"][:28]}{"..." if len(r["name"])>28 else ""}</div>{ar}</td>
              <td style='padding:8px 10px;font-size:12px'>{ps}</td>
              <td style='padding:8px 10px;text-align:center'><span style='background:{tb};color:{tc_};border-radius:10px;font-size:11px;font-weight:700;padding:2px 8px'>{r["tier"]}</span>{rec}{brk}</td>
              <td style='padding:8px 10px;text-align:center'><span style='font-size:14px;font-weight:900;color:{r["trend_color"]}'>{r["trend_arrow"]}</span><div style='font-size:10px;color:{r["trend_color"]};font-weight:600'>{r["trend_dir"]}</div></td>
              <td style='padding:8px 10px;text-align:right'><span style='font-size:15px;font-weight:900;color:#1d4ed8'>{r["score"]}</span><span style='font-size:10px;color:#94a3b8'>/110</span></td>
              <td style='padding:8px 10px;font-size:12px;color:#15803d;font-weight:700;white-space:nowrap'>+{t["upside_pct_ma"]}% → {ml}</td>
              <td style='padding:8px 10px;font-size:13px;font-weight:800;color:#1d4ed8;white-space:nowrap'>SGD {r["allocation_sgd"]:,.0f}</td>
            </tr>"""
        sections+=f"""<table width='100%' cellpadding='0' cellspacing='0' style='border:1px solid #e5e7eb;border-radius:8px;margin-bottom:16px;overflow:hidden;border-collapse:collapse'>
          <thead><tr style='background:{cc}'><td colspan='8' style='color:#fff;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:0.06em;padding:8px 14px'>{cat} — {len(items)} pick{"s" if len(items)!=1 else ""}</td></tr>
          <tr style='background:#f8fafc'><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>#</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Asset</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>Price</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:center'>Signal</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:center'>Trend</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:right'>Score</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>Target</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>SGD</th></tr></thead>
          <tbody>{rows}</tbody></table>"""
    return sections

def asset_card(rank, r, usd_to_inr, sgd_to_inr, sgd_to_usd):
    meta=CATEGORY_META[r["category"]]; ts,tl=TIER_BADGE[r["tier"]]
    primary,secondary=format_amount(r["allocation_sgd"],r["price"],meta["currency"],usd_to_inr,sgd_to_inr,sgd_to_usd)
    ps=f"${r['price']:.4f}" if meta["currency"]=="USD" else f"Rs.{r['price']:.2f}"
    rc="#16a34a" if r["rs_pct"]>=0 else "#dc2626"; cc=CATEGORY_COLORS.get(r["category"],"#374151")
    regc={"bull":"#15803d","neutral":"#a16207","bear":"#dc2626"}.get(r["regime"],"#374151"); t=r["targets"]
    mode=r.get("scoring_mode","dip"); is_momentum=mode=="momentum"

    rec_banner=""
    if r.get("recovery"):
        rec_banner="<div style='background:#ede9fe;border:1px solid #c4b5fd;border-radius:8px;padding:10px 16px;margin:12px 0'><span style='font-size:12px;font-weight:800;color:#7c3aed'>🔄 Recovery Watch — </span><span style='font-size:12px;color:#6d28d9'>Showing early reversal in beaten-down regime. Confirm before acting.</span></div>"
    breakout_banner=""
    if r.get("breakout"):
        breakout_banner="<div style='background:#fef3c7;border:1px solid #fcd34d;border-radius:8px;padding:10px 16px;margin:12px 0'><span style='font-size:12px;font-weight:800;color:#b45309'>🚀 Momentum Breakout — </span><span style='font-size:12px;color:#92400e'>Near 52-week high with strong volume. Momentum is accelerating — trend ride opportunity.</span></div>"

    mode_note=f"<div style='font-size:11px;background:{'#eef2ff' if is_momentum else '#f0fdf4'};color:{'#4338ca' if is_momentum else '#15803d'};border-radius:4px;padding:4px 10px;display:inline-block;margin-bottom:8px'>{'📈 Momentum Mode — 6-12 month trend ride objective' if is_momentum else '🎯 Dip Buy Mode — 1-3 month recovery objective'}</div>"

    # Build 3M/1M return badges for momentum assets
    return_badges=""
    if is_momentum and r.get("abs_return_3m") is not None:
        r3=r["abs_return_3m"]*100; r1=r.get("abs_return_1m",0) or 0; r1=r1*100
        c3="#15803d" if r3>=0 else "#dc2626"; c1="#15803d" if r1>=0 else "#dc2626"
        return_badges=f"""<td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>3M Return</div><div style='font-size:16px;font-weight:800;color:{c3}'>{r3:+.1f}%</div></td>
        <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>1M Return</div><div style='font-size:16px;font-weight:800;color:{c1}'>{r1:+.1f}%</div></td>"""

    mx={"RS vs Benchmark":30,"Trend (DMA)":25,"RSI Quality":20,"MACD Momentum":15,"ADX Strength":10,"Volume":10,"3M Abs Return":20,"1M Momentum":15,"RSI Momentum":20,"Breakout Signal":10}
    bd_rows="".join(f"<tr><td style='padding:3px 12px 3px 0;color:#6b7280;font-size:12px;white-space:nowrap'>{k}</td><td><div style='height:10px;width:{min(int(v*220/mx.get(k,20)),220)}px;background:{'#6366f1' if is_momentum else '#3b82f6'};border-radius:4px;display:inline-block;vertical-align:middle'></div></td><td style='padding:3px 0 3px 8px;font-size:12px;font-weight:700;color:{'#4338ca' if is_momentum else '#1d4ed8'}'>{v}/{mx.get(k,'?')}</td></tr>" for k,v in r["breakdown"].items())
    an=("<div style='font-size:11px;color:#15803d;background:#dcfce7;border-radius:4px;padding:4px 8px;margin-bottom:8px;display:inline-block'>✓ Price above all MAs — full strength</div>" if t.get("above_all_mas") else "")

    rs_label="3M Abs Return" if is_momentum else "RS vs Benchmark"

    return f"""<div style='border:1px solid #e5e7eb;border-left:4px solid {cc};border-radius:12px;padding:20px;margin-bottom:20px;background:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif'>
  <table width='100%' cellpadding='0' cellspacing='0'><tr>
    <td valign='top'><div style='font-size:11px;color:{cc};font-weight:700;text-transform:uppercase;letter-spacing:0.05em'>#{rank} · {meta["label"]}</div><div style='font-size:18px;font-weight:800;color:#111;margin:4px 0 2px'>{r["name"]}</div><div style='font-size:13px;color:#9ca3af'>{r["ticker"]} | {ps}</div></td>
    <td valign='top' align='right' style='white-space:nowrap;padding-left:12px'><div style='display:inline-block;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:800;{ts}'>{tl}</div><div style='margin-top:4px'><span style='font-size:18px;font-weight:900;color:{r["trend_color"]}'>{r["trend_arrow"]}</span><span style='font-size:13px;font-weight:700;color:{r["trend_color"]};margin-left:4px'>{r["trend_dir"]}</span></div><div style='font-size:24px;font-weight:900;color:#1d4ed8;margin-top:4px'>{primary}</div><div style='font-size:11px;color:#9ca3af;margin-top:2px'>{secondary}</div></td>
  </tr></table>
  {mode_note}
  <div style='background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px;padding:10px 14px;margin:10px 0;font-size:13px;color:#374151;line-height:1.6'><strong style='color:#a16207'>Why:</strong> {r["reason"]}</div>
  {rec_banner}{breakout_banner}
  <div style='overflow-x:auto;margin:14px 0 4px'><table cellpadding='0' cellspacing='6' style='white-space:nowrap'><tr>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Score</div><div style='font-size:18px;font-weight:900;color:#1d4ed8'>{r["score"]}<span style='font-size:10px;color:#94a3b8'>/110</span></div></td>
    {return_badges}
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>{rs_label}</div><div style='font-size:16px;font-weight:800;color:{rc}'>{r["rs_pct"]:+.1f}%</div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>RSI</div><div style='font-size:16px;font-weight:800;color:#374151'>{r["rsi"]}</div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Vol Ratio</div><div style='font-size:16px;font-weight:800;color:#374151'>{r["vol_ratio"]}x</div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Regime</div><div style='font-size:14px;font-weight:800;color:{regc}'>{r["regime"].title()}</div></td>
  </tr></table></div>
  <div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px 16px;margin:12px 0'>
    <div style='font-size:11px;color:#15803d;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px'>Price Targets</div>{an}
    <table cellpadding='0' cellspacing='0'><tr>
      <td style='padding-right:24px'><div style='font-size:11px;color:#6b7280;margin-bottom:2px'>{"52W High" if t.get("above_all_mas") else "Nearest MA"}</div><div style='font-size:18px;font-weight:800;color:#15803d'>+{t["upside_pct_ma"]}%</div><div style='font-size:11px;color:#374151'>{t["nearest_ma_label"]} @ {t["nearest_ma_val"]:,.4f}</div></td>
      <td style='padding:0 24px;border-left:1px solid #bbf7d0'><div style='font-size:11px;color:#6b7280;margin-bottom:2px'>3M High Recovery</div><div style='font-size:18px;font-weight:800;color:#0369a1'>+{t["upside_pct_3m"]}%</div><div style='font-size:11px;color:#374151'>{t["three_month_high"]:,.4f}</div></td>
      <td style='padding-left:24px;border-left:1px solid #bbf7d0'><div style='font-size:11px;color:#6b7280;margin-bottom:2px'>Current Dip</div><div style='font-size:18px;font-weight:800;color:#d97706'>-{r["dip"]}%</div><div style='font-size:11px;color:#374151'>from 3M high</div></td>
    </tr></table>
  </div>
  <div style='font-size:12px;padding:8px 12px;background:#f8fafc;border-radius:6px;margin-bottom:12px'>{ma_label_html(r["price"],r["ma_vals"])}</div>
  <div style='border-top:1px solid #f1f5f9;padding-top:12px'><div style='font-size:11px;color:#9ca3af;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px'>Score Breakdown {'(Momentum Mode)' if is_momentum else '(Dip Buy Mode)'}</div><table cellpadding='0' cellspacing='0'>{bd_rows}</table></div>
</div>"""

# ══════════════════════════════════════════════════════
#  EMAIL BUILDER
# ══════════════════════════════════════════════════════

def build_email(results, rn, rs_, usd_to_inr, sgd_to_inr, sgd_to_usd, date_str, macro, pf):
    strong=[r for r in results if r["tier"]=="Strong Buy"]; watch=[r for r in results if r["tier"]=="Watch"]
    rec_count=sum(1 for r in results if r.get("recovery")); brk_count=sum(1 for r in results if r.get("breakout"))
    total_sgd=sum(r["allocation_sgd"] for r in results)
    rns,rnl,rnc=REGIME_STYLE[rn]; rss_,rsl,rsc=REGIME_STYLE[rs_]
    strong_cards="".join(asset_card(i+1,r,usd_to_inr,sgd_to_inr,sgd_to_usd) for i,r in enumerate(results) if r["tier"]=="Strong Buy") or "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Strong Buy signals today.</p>"
    watch_cards="".join(asset_card(i+1,r,usd_to_inr,sgd_to_inr,sgd_to_usd) for i,r in enumerate(results) if r["tier"]=="Watch") or "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Watch signals today.</p>"
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head>
<body style='margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'>
<div style='max-width:760px;margin:0 auto;padding:24px 16px'>
  <div style='background:#1d4ed8;border-radius:14px 14px 0 0;padding:28px 28px 24px'>
    <div style='font-size:24px;font-weight:900;color:#fff'>Daily Market Screener <span style='font-size:14px;font-weight:500;color:#bfdbfe'>v5</span></div>
    <div style='font-size:13px;color:#bfdbfe;margin-top:4px'>{date_str} · Budget: SGD {TOTAL_BUDGET_SGD:,}/month · Deployed: SGD {total_sgd:,.0f}</div>
    <table cellpadding='0' cellspacing='0' style='margin-top:20px'><tr>
      <td style='padding-right:20px'><div style='font-size:11px;color:#93c5fd;text-transform:uppercase'>Strong Buy</div><div style='font-size:30px;font-weight:900;color:#fff'>{len(strong)}</div></td>
      <td style='padding-right:20px'><div style='font-size:11px;color:#93c5fd;text-transform:uppercase'>Watch</div><div style='font-size:30px;font-weight:900;color:#fff'>{len(watch)}</div></td>
      <td style='padding-right:20px'><div style='font-size:11px;color:#93c5fd;text-transform:uppercase'>Breakouts 🚀</div><div style='font-size:30px;font-weight:900;color:#fff'>{brk_count}</div></td>
      <td style='padding-right:20px'><div style='font-size:11px;color:#93c5fd;text-transform:uppercase'>Recovery 🔄</div><div style='font-size:30px;font-weight:900;color:#fff'>{rec_count}</div></td>
      <td><div style='font-size:11px;color:#93c5fd;text-transform:uppercase'>Total Picks</div><div style='font-size:30px;font-weight:900;color:#fff'>{len(results)}</div></td>
    </tr></table>
  </div>
  {macro_html(macro)}
  <table width='100%' cellpadding='6' cellspacing='0' style='margin:0 0 16px'><tr>
    <td width='50%'><div style='{rns};padding:12px 16px;border-radius:8px'><div style='font-size:11px;color:{rnc};font-weight:700;text-transform:uppercase'>Nifty Regime</div><div style='font-size:15px;font-weight:800;color:{rnc};margin-top:2px'>{rnl}</div></div></td>
    <td width='50%'><div style='{rss_};padding:12px 16px;border-radius:8px'><div style='font-size:11px;color:{rsc};font-weight:700;text-transform:uppercase'>S&amp;P Regime</div><div style='font-size:15px;font-weight:800;color:{rsc};margin-top:2px'>{rsl}</div></div></td>
  </tr></table>
  <div style='background:#eef2ff;border:1px solid #c7d2fe;border-radius:8px;padding:12px 16px;margin-bottom:16px;font-size:12px;color:#3730a3;line-height:1.7'>
    <strong>Scoring modes:</strong> &nbsp;
    <span style='background:#eef2ff;border:1px solid #6366f1;border-radius:4px;padding:1px 6px;font-size:11px'>📈 momentum</span> = Global ETFs &amp; Crypto — 6-12 month trend ride. Rewards high RSI, recent breakouts, absolute returns. &nbsp;
    <span style='background:#f0fdf4;border:1px solid #16a34a;border-radius:4px;padding:1px 6px;font-size:11px'>🎯 dip</span> = Indian Stocks &amp; ETFs, Metals — 1-3 month recovery. Rewards RS vs benchmark, healthy RSI zone, regime recovery.
  </div>
  {pf}
  <div style='font-size:15px;font-weight:800;color:#1d4ed8;margin:8px 0;padding-bottom:8px;border-bottom:2px solid #bfdbfe'>AT A GLANCE — TOP {len(results)} PICKS</div>
  {summary_html(results,usd_to_inr,sgd_to_inr,sgd_to_usd)}
  <div style='font-size:15px;font-weight:800;color:#15803d;margin:32px 0 14px;padding-bottom:8px;border-bottom:2px solid #bbf7d0'>STRONG BUY ({len(strong)})</div>
  {strong_cards}
  <div style='font-size:15px;font-weight:800;color:#a16207;margin:28px 0 14px;padding-bottom:8px;border-bottom:2px solid #fde68a'>WATCH LIST ({len(watch)})</div>
  {watch_cards}
  {mf_html(sgd_to_inr)}
  <div style='margin-top:32px;padding:16px;background:#fff;border-radius:10px;font-size:11px;color:#9ca3af;border:1px solid #e5e7eb;line-height:1.8'>
    <strong style='color:#6b7280'>Dual Scoring:</strong> Momentum mode (Global ETF/Crypto): 3M Return + 1M Momentum + Trend + RSI Momentum + MACD + Breakout + Volume = 110 max. Dip Buy mode (Indian/Metals): RS vs Benchmark + Trend + RSI + MACD + ADX + Volume = 110 max.<br>
    <strong style='color:#6b7280'>Crypto Regime:</strong> BTC trend sets floor multiplier. Individual asset DMA confirms or adjusts. Bull+confirmed = ×1.15, Bear = ×0.65.<br>
    <strong style='color:#6b7280'>Breakout 🚀:</strong> Asset within 8% of 52-week high with volume 1.3x+ average. Strong momentum continuation signal.<br>
    <strong style='color:#6b7280'>Budget:</strong> SGD 4,000/month — Indian ≤25%, Global ETF 40%, Metals 20%, Crypto 15%. Score-weighted within each pool.<br>
    <strong style='color:#6b7280'>Disclaimer:</strong> Not financial advice. Do your own research.
  </div>
</div></body></html>"""

# ══════════════════════════════════════════════════════
#  TELEGRAM
# ══════════════════════════════════════════════════════

def send_telegram(results, rn, rs_, macro, date_str):
    token=os.environ.get("TELEGRAM_BOT_TOKEN",""); chat_id=os.environ.get("TELEGRAM_CHAT_ID","")
    if not token or not chat_id: print("  [INFO] Telegram not configured."); return
    na="▲" if macro["nifty_chg"]>=0 else "▼"; sa="▲" if macro["sp_chg"]>=0 else "▼"
    lines=[f"📊 *Daily Screener v5 — {date_str}*",f"Nifty: {macro['nifty_close']:,} {na}{abs(macro['nifty_chg'])}%  |  S&P: {macro['sp_close']:,} {sa}{abs(macro['sp_chg'])}%",f"1 SGD = Rs.{macro['sgd_inr']}  |  Nifty={rn.title()} · S&P={rs_.title()}","",f"💡 _{macro['regime_note']}_","","*🏆 TOP 5 PICKS*"]
    for i,r in enumerate(results[:5],1):
        icon="🟢" if r["tier"]=="Strong Buy" else "🟡"; mode="📈" if r.get("scoring_mode")=="momentum" else "🎯"
        extras=(" 🚀" if r.get("breakout") else "")+(" 🔄" if r.get("recovery") else "")
        ar=f" | +{r['abs_return_3m']*100:.1f}% (3M)" if r.get("abs_return_3m") else ""
        lines.append(f"{i}. {icon}{mode} *{r['ticker']}* [{r['category']}]{extras}\n   SGD {r['allocation_sgd']:,.0f}  |  Score: {r['score']}/110{ar}\n   {r['trend_arrow']} {r['trend_dir']}  |  Target: +{r['targets']['upside_pct_ma']}%\n   _{r['reason']}_")
    lines.append("\nFull breakdown in your email 📧")
    try:
        url=f"https://api.telegram.org/bot{token}/sendMessage"
        payload=json.dumps({"chat_id":chat_id,"text":"\n".join(lines),"parse_mode":"Markdown"}).encode()
        req=urllib.request.Request(url,data=payload,headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=10) as resp: print("  Telegram sent." if resp.status==200 else f"  Telegram status {resp.status}")
    except Exception as e: print(f"  [WARN] Telegram: {e}")

def send_email(subject, html_body):
    em=os.environ["EMAIL_ADDRESS"]; pw=os.environ["EMAIL_PASSWORD"]
    msg=MIMEMultipart("alternative"); msg["Subject"]=subject; msg["From"]=em; msg["To"]=em
    msg.attach(MIMEText(html_body,"html"))
    try:
        with smtplib.SMTP("smtp.gmail.com",587) as s: s.starttls(); s.login(em,pw); s.send_message(msg)
        print("  Email sent.")
    except Exception as e: print(f"  Email error: {e}")

# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════

def main():
    today=datetime.now().strftime("%d %b %Y"); today_key=datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*55}\n  Daily Screener v5 (Singapore) — {today}\n{'='*55}\n")

    history=load_history(); print(f"  History: {len(history)} entries")

    nse_stocks=[]
    try:
        df_nse=pd.read_csv("https://archives.nseindia.com/content/indices/ind_nifty500list.csv")
        nse_stocks=[s.strip()+".NS" for s in df_nse["Symbol"].dropna().tolist()]
        print(f"  Nifty 500: {len(nse_stocks)} stocks")
    except Exception as e:
        print(f"  [WARN] Nifty 500 failed ({e}). Fallback.")
        nse_stocks=[s+".NS" for s in ["RELIANCE","TCS","HDFCBANK","INFY","ICICIBANK","HINDUNILVR","SBIN","BHARTIARTL","ITC","KOTAKBANK","LT","AXISBANK","ASIANPAINT","MARUTI","TITAN","SUNPHARMA","BAJFINANCE","WIPRO","HCLTECH","ADANIENT","ADANIPORTS","BAJAJFINSV","BRITANNIA","CIPLA","COALINDIA","DIVISLAB","DRREDDY","EICHERMOT","GRASIM","HEROMOTOCO","HINDALCO","INDUSINDBK","JSWSTEEL","M&M","NESTLEIND","NTPC","ONGC","POWERGRID","SBILIFE","TATAMOTORS","TATACONSUM","TATASTEEL","TECHM","ULTRACEMCO","UPL","VEDL"]]

    all_tickers=nse_stocks+list(INDIAN_ETFS.keys())+list(GLOBAL_ETFS.keys())+list(METALS_COMMODITIES.keys())+list(CRYPTO.keys())
    dl_list=list(dict.fromkeys(all_tickers+["^NSEI","^GSPC","BTC-USD","USDINR=X","SGDUSD=X"]))
    print(f"  Downloading {len(dl_list)} tickers...\n")

    raw=yf.download(dl_list,period=DATA_PERIOD,interval="1d",group_by="ticker",threads=True,progress=True,auto_adjust=True)
    usd_to_inr,sgd_to_inr,sgd_to_usd=get_fx_rates(raw)
    print(f"\n  1 USD=Rs.{usd_to_inr:.2f}  |  1 SGD=Rs.{sgd_to_inr:.2f}  |  1 SGD=${sgd_to_usd:.4f}")

    def get_close(t):
        try: s=raw[t]["Close"].dropna(); return s.squeeze() if not s.empty else pd.Series(dtype=float)
        except: return pd.Series(dtype=float)

    bn=get_close("^NSEI"); bs=get_close("^GSPC"); bb=get_close("BTC-USD")
    benchmarks={"Indian Stock":bn,"Indian ETF":bn,"Global ETF":bs,"Metal/Commodity":bs,"Crypto":bb}
    rn=get_regime(bn) if not bn.empty else "neutral"
    rs_=get_regime(bs) if not bs.empty else "neutral"
    print(f"  Nifty: {rn.upper()}  |  S&P: {rs_.upper()}\n")

    macro=build_macro(bn,bs,usd_to_inr,sgd_to_usd,rn,rs_)
    print("  Fetching past performance..."); pf_rows=fetch_performance(history); pf=perf_html(pf_rows)

    try: tickers_in_raw=set(raw.columns.get_level_values(0))
    except: tickers_in_raw=set()

    all_results=[]
    for ticker in all_tickers:
        if ticker not in tickers_in_raw: continue
        try:
            df=raw[ticker].dropna(how="all")
            if df.empty or len(df)<60: continue
            cat=get_category(ticker); bench=benchmarks.get(cat,pd.Series(dtype=float))
            if bench.empty: continue
            common=df.index.intersection(bench.index)
            if len(common)<60: continue
            df_a=df.loc[common].copy(); b_a=bench.loc[common].copy()
            mode=CATEGORY_META[cat]["mode"]
            if mode=="momentum":
                result=score_momentum(ticker,df_a,b_a,bb,cat,rs_)
            else:
                regime=rn if cat in ("Indian Stock","Indian ETF") else rs_
                result=score_dip(ticker,df_a,b_a,cat,regime)
            if result: all_results.append(result)
        except: continue

    all_results.sort(key=lambda x:-x["score"])
    results=all_results[:GLOBAL_MAX_PICKS]
    results=apply_indian_pick_cap(results)
    results.sort(key=lambda x:(0 if x["tier"]=="Strong Buy" else 1,-x["score"]))

    allocs=compute_allocations(results)
    for r in results: r["allocation_sgd"]=round(allocs.get(r["ticker"],0),2)

    strong=[r for r in results if r["tier"]=="Strong Buy"]; watch=[r for r in results if r["tier"]=="Watch"]
    rec_count=sum(1 for r in results if r.get("recovery")); brk_count=sum(1 for r in results if r.get("breakout"))
    print(f"  Qualified: {len(all_results)}  |  Top {len(results)}  |  Strong Buy: {len(strong)}  |  Watch: {len(watch)}  |  Breakouts: {brk_count}  |  Recovery: {rec_count}\n")
    for r in results:
        meta=CATEGORY_META[r["category"]]; ps=f"${r['price']:.2f}" if meta["currency"]=="USD" else f"Rs.{r['price']:.2f}"
        mode_tag="[M]" if r.get("scoring_mode")=="momentum" else "[D]"
        brk="🚀" if r.get("breakout") else "  "; rec="🔄" if r.get("recovery") else "  "
        print(f"  {mode_tag} [{r['tier']:11s}] {r['ticker']:16s} {r['category']:18s} Score={r['score']:5.1f}  SGD={r['allocation_sgd']:,.0f}  {r['trend_arrow']} {brk}{rec}  {ps}")

    save_history(results,today_key)
    html=build_email(results,rn,rs_,usd_to_inr,sgd_to_inr,sgd_to_usd,today,macro,pf)
    breakout_str=f" | {brk_count} Breakouts 🚀" if brk_count>0 else ""
    subject=f"[Screener {today}] {len(strong)} Strong Buy | {len(watch)} Watch{breakout_str} | {rec_count} Recovery 🔄 | SGD {TOTAL_BUDGET_SGD:,} | Nifty={rn.title()} · S&P={rs_.title()}"
    send_email(subject,html)
    send_telegram(results,rn,rs_,macro,today)
    print(f"\n  Done. SGD deployed: {sum(r['allocation_sgd'] for r in results):,.0f}")

if __name__=="__main__":
    main()
