"""
Daily Market Screener — v4
Singapore-based investor edition

Budget: SGD 4,000/month with live SGD→INR and SGD→USD conversion
Allocation: Indian 25%, Global ETF 40%, Metals 20%, Crypto 15%
Indian picks capped at 25% of total recommendations
MF section: curated static SIP list (Large Cap, Flexi Cap, Mid Cap, Small Cap, ELSS, International)
Signal history tracker: rolling 5-day performance
Telegram top 5 alert + plain English reason + macro context header
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
from datetime import datetime

warnings.simplefilter("ignore")

# ══════════════════════════════════════════════════════
#  CONFIG
# ══════════════════════════════════════════════════════
TOTAL_BUDGET_SGD   = 4000
DATA_PERIOD        = "1y"
MIN_PRICE_INR      = 50
MIN_AVG_VOLUME_NS  = 300000
GLOBAL_MAX_PICKS   = 25
SCORE_STRONG_BUY   = 60
SCORE_WATCH        = 40
HISTORY_FILE       = "screener_history.json"
INDIAN_PICK_CAP    = 0.25   # max 25% of GLOBAL_MAX_PICKS as Indian picks

CATEGORY_CAPS = {
    "indian":  0.25,
    "global":  0.40,
    "metal":   0.20,
    "crypto":  0.15,
}

# ══════════════════════════════════════════════════════
#  CURATED INDIAN MF LIST
# ══════════════════════════════════════════════════════
INDIAN_MF_LIST = [
    {"name": "Mirae Asset Large Cap Fund",        "category": "Large Cap",             "amc": "Mirae Asset",   "why": "Consistent top-quartile performer. Diversified across Nifty 100 with strong risk-adjusted returns over 5Y+.",                                                                            "suggested_sip": 15000, "risk": "Moderate"},
    {"name": "Axis Bluechip Fund",                 "category": "Large Cap",             "amc": "Axis MF",       "why": "Quality-focused portfolio, lower drawdowns than peers. Good for conservative equity exposure.",                                                                                           "suggested_sip": 10000, "risk": "Moderate"},
    {"name": "Parag Parikh Flexi Cap Fund",        "category": "Flexi Cap",             "amc": "PPFAS MF",      "why": "Invests up to 35% in international stocks (Google, Meta, Amazon). Natural global diversification within an Indian MF wrapper.",                                                          "suggested_sip": 20000, "risk": "Moderate"},
    {"name": "HDFC Flexi Cap Fund",                "category": "Flexi Cap",             "amc": "HDFC MF",       "why": "One of the largest and most consistent flexi cap funds. Active allocation between large and mid caps based on market conditions.",                                                         "suggested_sip": 15000, "risk": "Moderate"},
    {"name": "Kotak Emerging Equity Fund",         "category": "Mid Cap",               "amc": "Kotak MF",      "why": "Strong mid-cap track record with disciplined stock selection. Outperformed benchmark over 7 of last 10 years.",                                                                           "suggested_sip": 10000, "risk": "Moderately High"},
    {"name": "Nippon India Growth Fund",           "category": "Mid Cap",               "amc": "Nippon India",  "why": "One of India's oldest mid-cap funds with proven long-term compounding. Rewarding over 5Y+ horizon.",                                                                                      "suggested_sip": 10000, "risk": "Moderately High"},
    {"name": "SBI Small Cap Fund",                 "category": "Small Cap",             "amc": "SBI MF",        "why": "Best-in-class small cap fund by consistency. High conviction portfolio. Only for 7Y+ horizon.",                                                                                           "suggested_sip": 5000,  "risk": "High"},
    {"name": "Axis Small Cap Fund",                "category": "Small Cap",             "amc": "Axis MF",       "why": "Quality-first approach in small caps — lower volatility than peers. Good entry during market corrections.",                                                                               "suggested_sip": 5000,  "risk": "High"},
    {"name": "Mirae Asset Tax Saver Fund",         "category": "ELSS",                  "amc": "Mirae Asset",   "why": "Best ELSS by risk-adjusted returns. 3Y lock-in, 80C benefit up to Rs.1.5L/year. Treats it as large+mid cap blend.",                                                                     "suggested_sip": 12500, "risk": "Moderate"},
    {"name": "Quant Tax Plan",                     "category": "ELSS",                  "amc": "Quant MF",      "why": "Quantitative model-driven ELSS with stellar recent performance. Higher risk but strong alpha generation.",                                                                                 "suggested_sip": 10000, "risk": "Moderately High"},
    {"name": "Motilal Oswal Nasdaq 100 FOF",       "category": "International / US",    "amc": "Motilal Oswal", "why": "Tracks Nasdaq 100 — gives you Apple, Microsoft, Nvidia, Google exposure via Indian MF. No LRS/remittance needed.",                                                                        "suggested_sip": 10000, "risk": "High"},
    {"name": "DSP World Gold Fund",                "category": "International / Commodity", "amc": "DSP MF",    "why": "Invests in global gold mining companies. Higher beta to gold price — amplifies gold moves. Complements your physical gold SIP.",                                                          "suggested_sip": 5000,  "risk": "High"},
]

# ══════════════════════════════════════════════════════
#  ASSET UNIVERSE
# ══════════════════════════════════════════════════════

GLOBAL_ETFS = {
    "SPY":"SPDR S&P 500 ETF Trust","QQQ":"Invesco QQQ Trust (Nasdaq 100)","VTI":"Vanguard Total Stock Market ETF",
    "VOO":"Vanguard S&P 500 ETF","IVV":"iShares Core S&P 500 ETF","IWM":"iShares Russell 2000 ETF",
    "DIA":"SPDR Dow Jones Industrial ETF","EFA":"iShares MSCI EAFE ETF","VEA":"Vanguard FTSE Developed Markets ETF",
    "IEFA":"iShares Core MSCI EAFE ETF","EWJ":"iShares MSCI Japan ETF","EWG":"iShares MSCI Germany ETF",
    "EWU":"iShares MSCI UK ETF","EWQ":"iShares MSCI France ETF","EWA":"iShares MSCI Australia ETF",
    "EWC":"iShares MSCI Canada ETF","EWZ":"iShares MSCI Brazil ETF","EWY":"iShares MSCI South Korea ETF",
    "MCHI":"iShares MSCI China ETF","FXI":"iShares China Large Cap ETF","KWEB":"KraneShares China Internet ETF",
    "EEM":"iShares MSCI Emerging Markets ETF","VWO":"Vanguard Emerging Markets ETF",
    "KSA":"iShares MSCI Saudi Arabia ETF","UAE":"iShares MSCI UAE ETF",
    "XLK":"Technology Select Sector SPDR","XLF":"Financial Select Sector SPDR",
    "XLE":"Energy Select Sector SPDR","XLV":"Health Care Select Sector SPDR",
    "XLI":"Industrial Select Sector SPDR","XLP":"Consumer Staples Select Sector SPDR",
    "ARKK":"ARK Innovation ETF","SOXX":"iShares Semiconductor ETF",
}

METALS_COMMODITIES = {
    "GLD":"SPDR Gold Shares","IAU":"iShares Gold Trust","SLV":"iShares Silver Trust",
    "PPLT":"Aberdeen Platinum ETF","PALL":"Aberdeen Palladium ETF","USO":"United States Oil Fund (Crude)",
    "BNO":"United States Brent Oil Fund","UNG":"United States Natural Gas Fund","CPER":"United States Copper ETF",
    "WEAT":"Teucrium Wheat Fund","CORN":"Teucrium Corn Fund","SOYB":"Teucrium Soybean Fund",
    "DBA":"Invesco DB Agriculture Fund","DJP":"iPath Bloomberg Commodity ETN","GSG":"iShares S&P GSCI Commodity ETF",
}

CRYPTO = {
    "BTC-USD":"Bitcoin","ETH-USD":"Ethereum","SOL-USD":"Solana","BNB-USD":"BNB (Binance Coin)",
    "XRP-USD":"XRP (Ripple)","ADA-USD":"Cardano","AVAX-USD":"Avalanche",
    "DOT-USD":"Polkadot","LINK-USD":"Chainlink","MATIC-USD":"Polygon (MATIC)",
}

INDIAN_ETFS = {
    "NIFTYBEES.NS":"Nippon Nifty BeES","JUNIORBEES.NS":"Nippon Junior BeES","BANKBEES.NS":"Nippon Bank BeES",
    "ITBEES.NS":"Nippon IT BeES","GOLDBEES.NS":"Nippon Gold BeES","SILVERBEES.NS":"Nippon Silver BeES",
    "ICICIB22.NS":"ICICI Bharat 22 ETF","CPSE.NS":"CPSE ETF","MAN50ETF.NS":"Mirae Asset Nifty 50 ETF",
    "NETFIT.NS":"Nippon India ETF Nifty IT","PSUBNKBEES.NS":"Nippon PSU Bank BeES","PHARMABEES.NS":"Nippon Pharma BeES",
}

CATEGORY_META = {
    "Indian Stock":    {"benchmark":"^NSEI",   "currency":"INR","label":"Indian Stock"},
    "Indian ETF":      {"benchmark":"^NSEI",   "currency":"INR","label":"Indian ETF"},
    "Global ETF":      {"benchmark":"^GSPC",   "currency":"USD","label":"Global ETF"},
    "Metal/Commodity": {"benchmark":"^GSPC",   "currency":"USD","label":"Metal / Commodity"},
    "Crypto":          {"benchmark":"BTC-USD", "currency":"USD","label":"Crypto"},
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
    d = s.diff(); g = d.clip(lower=0).rolling(p).mean(); l = (-d.clip(upper=0)).rolling(p).mean()
    return 100 - (100 / (1 + g / l.replace(0, np.nan)))

def compute_macd(s, fast=12, slow=26, signal=9):
    ef = s.ewm(span=fast, adjust=False).mean(); es = s.ewm(span=slow, adjust=False).mean()
    m = ef - es; sig = m.ewm(span=signal, adjust=False).mean(); return m, sig, m - sig

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

def rs(sc, bc, lb=63):
    if len(sc)<lb or len(bc)<lb: return None
    return float((sc.iloc[-1]-sc.iloc[-lb])/sc.iloc[-lb] - (bc.iloc[-1]-bc.iloc[-lb])/bc.iloc[-lb])

def rs_short(sc, bc, lb=10):
    if len(sc)<lb or len(bc)<lb: return None
    return float((sc.iloc[-1]-sc.iloc[-lb])/sc.iloc[-lb] - (bc.iloc[-1]-bc.iloc[-lb])/bc.iloc[-lb])

# ══════════════════════════════════════════════════════
#  REGIME / TREND / TARGETS / RECOVERY
# ══════════════════════════════════════════════════════

def get_regime(cl):
    cl=cl.squeeze()
    if len(cl)<200: return "neutral"
    ma50=cl.rolling(50).mean().iloc[-1]; ma200=cl.rolling(200).mean().iloc[-1]
    ma200_1m=cl.rolling(200).mean().iloc[-22]; price=cl.iloc[-1]
    if price>ma50>ma200 and (ma200-ma200_1m)/ma200_1m>0: return "bull"
    if price<ma200*0.95: return "bear"
    return "neutral"

def get_trend(price, ma_vals):
    m20=ma_vals.get("MA20"); m50=ma_vals.get("MA50"); m200=ma_vals.get("MA200")
    if m20 and m50 and price>m20 and m20>m50:
        return ("Strong Uptrend","#15803d","↑↑") if m200 and price>m200 else ("Uptrend","#16a34a","↑")
    if m20 and m50 and price<m20 and m20<m50:
        return ("Strong Downtrend","#dc2626","↓↓") if m200 and price<m200 else ("Downtrend","#ef4444","↓")
    return ("Sideways","#d97706","→")

def get_targets(price, ma_vals, close):
    above={k:v for k,v in ma_vals.items() if v and v>price}
    h3m=float(close.tail(63).max()); h52=float(close.tail(252).max())
    if above:
        nl=min(above,key=above.get); nv=above[nl]; return {"nearest_ma_label":nl,"nearest_ma_val":round(nv,4),"upside_pct_ma":round((nv-price)/price*100,1),"three_month_high":round(h3m,4),"upside_pct_3m":round((h3m-price)/price*100,1),"above_all_mas":False}
    return {"nearest_ma_label":"52W High","nearest_ma_val":round(h52,4),"upside_pct_ma":round((h52-price)/price*100,1),"three_month_high":round(h3m,4),"upside_pct_3m":round((h3m-price)/price*100,1),"above_all_mas":True}

def recovery_watch(regime, rsi, price, ma_vals, close, bench):
    if regime not in ("bear","neutral") or not (35<=rsi<=52): return False
    m200=ma_vals.get("MA200")
    if m200 and price<m200*0.85: return False
    rsl=rs(close,bench,63); rss=rs_short(close,bench,10)
    return rsl is not None and rss is not None and rss>rsl

# ══════════════════════════════════════════════════════
#  PLAIN ENGLISH REASON
# ══════════════════════════════════════════════════════

def build_reason(r):
    parts=[]; bd=r["breakdown"]
    if bd["RS vs Benchmark"]>=20: parts.append(f"beating its benchmark by {r['rs_pct']:+.1f}% over 3 months")
    elif bd["RS vs Benchmark"]>=10: parts.append(f"modestly outperforming benchmark ({r['rs_pct']:+.1f}%)")
    if r["trend_dir"] in ("Strong Uptrend","Uptrend"): parts.append(f"in a clear {r['trend_dir'].lower()}")
    elif r["trend_dir"]=="Sideways": parts.append("consolidating sideways")
    if 45<=r["rsi"]<=65: parts.append(f"RSI healthy at {r['rsi']}")
    elif r["rsi"]<40: parts.append(f"RSI oversold at {r['rsi']} — potential bounce")
    if bd["MACD Momentum"]==15: parts.append("MACD positive and rising")
    elif bd["MACD Momentum"]==10: parts.append("MACD positive")
    if bd["ADX Strength"]==10: parts.append(f"strong trend (ADX {r['adx']})")
    if isinstance(r["vol_ratio"],float) and r["vol_ratio"]>=1.5: parts.append(f"volume {r['vol_ratio']}x above average")
    if r["recovery"]: parts.append("showing early reversal in beaten-down regime")
    if not parts: return "Multiple technical factors aligning — review breakdown below."
    s=", ".join(parts[:3]); return s[0].upper()+s[1:]+"."

# ══════════════════════════════════════════════════════
#  SCORING ENGINE
# ══════════════════════════════════════════════════════

def score_asset(ticker, df, bench_close, category, regime):
    try:
        close=df["Close"].squeeze(); volume=df["Volume"].squeeze() if "Volume" in df.columns else pd.Series(dtype=float)
        if len(close)<60: return None
        price=float(close.iloc[-1])
        if np.isnan(price) or price<=0: return None
        if category=="Indian Stock" and not volume.empty:
            if price<MIN_PRICE_INR or float(volume.tail(20).mean())<MIN_AVG_VOLUME_NS: return None
        r=rs(close,bench_close,63)
        if r is None or r<-0.15: return None
        rs_score=min(30,max(0,(r+0.05)*150))
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
            adx_s,pdi_s,mdi_s=compute_adx(df); adx_val=float(adx_s.iloc[-1]); pdi_val=float(pdi_s.iloc[-1]); mdi_val=float(mdi_s.iloc[-1])
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
        td,tc,ta=get_trend(price,ma_vals); targets=get_targets(price,ma_vals,close); rec=recovery_watch(regime,rsi_val,price,ma_vals,close,bench_close)
        result={"ticker":ticker,"name":get_display_name(ticker),"category":category,"price":round(price,4),"tier":tier,"score":final,"raw_score":round(raw,1),"regime":regime,"dip":round(dip,2),"rs_pct":round(r*100,2),"rsi":round(rsi_val,1),"macd_hist":round(hn,6),"adx":round(adx_val,1) if adx_val else "n/a","vol_ratio":round(vol_ratio,2) if vol_ratio else "n/a","ma_vals":ma_vals,"trend_dir":td,"trend_color":tc,"trend_arrow":ta,"targets":targets,"recovery":rec,"allocation_sgd":0,"reason":"","breakdown":{"RS vs Benchmark":round(rs_score,1),"Trend (DMA)":trend_score,"RSI Quality":rsi_score,"MACD Momentum":macd_score,"ADX Strength":adx_score,"Volume":round(vol_score,1)}}
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
    except Exception as e: print(f"  [WARN] history save failed: {e}")

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

def build_macro(bench_nifty, bench_sp500, usd_to_inr, sgd_to_usd, rn, rs_):
    def lc(s):
        s=s.dropna()
        if len(s)<2: return None,None,None
        p,t=float(s.iloc[-2]),float(s.iloc[-1]); return p,t,(t-p)/p*100
    _,nc,nchg=lc(bench_nifty); _,sc,schg=lc(bench_sp500)
    sentences={("bull","bull"):"Both Nifty and S&P are in bull mode — conditions are favourable across the board.",("bull","neutral"):"Nifty is bullish, S&P is sideways — Indian picks look stronger today.",("bull","bear"):"Nifty is bullish but S&P is under pressure — lean towards Indian over Global ETFs.",("neutral","bull"):"S&P is bullish, Nifty is consolidating — Global ETFs may have the edge today.",("neutral","neutral"):"Both markets are sideways — be selective, only the highest-scoring picks are worth acting on.",("neutral","bear"):"Nifty is consolidating, S&P is in a downtrend — tread carefully on Global ETFs.",("bear","bull"):"Nifty is under pressure but S&P is strong — Global ETFs and Crypto may be better bets.",("bear","neutral"):"Nifty is in a downtrend, S&P is sideways — watch for Recovery Watch signals specifically.",("bear","bear"):"Both markets are in downtrends — only act on Strong Buy signals with Recovery Watch flag."}
    return {"nifty_close":round(nc,2) if nc else "N/A","nifty_chg":round(nchg,2) if nchg else 0,"sp_close":round(sc,2) if sc else "N/A","sp_chg":round(schg,2) if schg else 0,"usd_inr":round(usd_to_inr,2),"sgd_usd":round(sgd_to_usd,4),"sgd_inr":round(sgd_to_usd*usd_to_inr,2),"regime_note":sentences.get((rn,rs_),"Review regime carefully before acting today.")}

# ══════════════════════════════════════════════════════
#  HTML BUILDERS
# ══════════════════════════════════════════════════════

TIER_BADGE={"Strong Buy":("background:#dcfce7;color:#15803d;border:1px solid #86efac","STRONG BUY"),"Watch":("background:#fef9c3;color:#a16207;border:1px solid #fde047","WATCH")}
REGIME_STYLE={"bull":("background:#f0fdf4;border-left:4px solid #16a34a","Bull Market","#15803d"),"neutral":("background:#fffbeb;border-left:4px solid #f59e0b","Neutral / Sideways","#a16207"),"bear":("background:#fef2f2;border-left:4px solid #dc2626","Bear Market - Caution","#dc2626")}

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
  <div style='font-size:12px;font-weight:700;color:#93c5fd;text-transform:uppercase;letter-spacing:0.06em;margin-bottom:12px'>Market Snapshot — Yesterday's Close</div>
  <table cellpadding='0' cellspacing='0' width='100%'><tr>
    <td style='padding-right:24px'><div style='font-size:11px;color:#93c5fd;margin-bottom:2px'>Nifty 50</div><div style='font-size:20px;font-weight:900;color:#fff'>{m["nifty_close"]:,}</div><div style='font-size:13px;font-weight:700;color:{nc}'>{na} {abs(m["nifty_chg"])}%</div></td>
    <td style='padding:0 24px;border-left:1px solid #2d5a8e'><div style='font-size:11px;color:#93c5fd;margin-bottom:2px'>S&amp;P 500</div><div style='font-size:20px;font-weight:900;color:#fff'>{m["sp_close"]:,}</div><div style='font-size:13px;font-weight:700;color:{sc}'>{sa} {abs(m["sp_chg"])}%</div></td>
    <td style='padding-left:24px;border-left:1px solid #2d5a8e'><div style='font-size:11px;color:#93c5fd;margin-bottom:2px'>FX</div><div style='font-size:14px;font-weight:800;color:#fff'>1 SGD = Rs.{m["sgd_inr"]}<br>1 USD = Rs.{m["usd_inr"]}</div></td>
  </tr></table>
  <div style='margin-top:14px;padding-top:12px;border-top:1px solid #2d5a8e;font-size:13px;color:#bfdbfe;line-height:1.6'>💡 {m["regime_note"]}</div>
</div>"""

def perf_html(rows):
    if not rows: return ""
    r_rows=""
    for p in rows:
        rc="#15803d" if p["return_pct"]>=0 else "#dc2626"; ra="▲" if p["return_pct"]>=0 else "▼"
        cc=CATEGORY_COLORS.get(p["category"],"#374151")
        r_rows+=f"<tr style='border-bottom:1px solid #f1f5f9'><td style='padding:7px 10px;font-size:11px;color:#9ca3af'>{p['date']}</td><td style='padding:7px 10px'><span style='font-size:12px;font-weight:700;color:#111'>{p['ticker']}</span> <span style='font-size:10px;color:{cc};background:#f1f5f9;padding:1px 5px;border-radius:4px'>{p['category']}</span></td><td style='padding:7px 10px;font-size:12px;color:#374151'>{p['entry_price']:,.4f}</td><td style='padding:7px 10px;font-size:12px;color:#374151'>{p['current_price']:,.4f}</td><td style='padding:7px 10px;font-size:13px;font-weight:800;color:{rc}'>{ra} {abs(p['return_pct'])}%</td></tr>"
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
        cards+=f"""<div style='border:1px solid #e5e7eb;border-left:4px solid {cc};border-radius:10px;padding:16px;margin-bottom:14px;background:#fff'>
  <table width='100%' cellpadding='0' cellspacing='0'><tr>
    <td valign='top'><div style='font-size:11px;color:{cc};font-weight:700;text-transform:uppercase;letter-spacing:0.05em'>{mf["category"]}</div><div style='font-size:16px;font-weight:800;color:#111;margin:4px 0 2px'>{mf["name"]}</div><div style='font-size:12px;color:#9ca3af'>{mf["amc"]}</div></td>
    <td valign='top' align='right' style='white-space:nowrap;padding-left:12px'><div style='font-size:11px;color:#9ca3af;margin-bottom:2px'>Suggested SIP</div><div style='font-size:22px;font-weight:900;color:#1d4ed8'>Rs.{mf["suggested_sip"]:,}</div><div style='font-size:11px;color:#9ca3af'>≈ SGD {mf["suggested_sip"]/sgd_to_inr:,.0f}/month</div><div style='margin-top:6px'><span style='background:{rc}20;color:{rc};border:1px solid {rc}50;border-radius:10px;font-size:11px;font-weight:700;padding:2px 8px'>Risk: {mf["risk"]}</span></div></td>
  </tr></table>
  <div style='margin-top:12px;background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px;padding:10px 14px;font-size:13px;color:#374151;line-height:1.6'><strong style='color:#a16207'>Why:</strong> {mf["why"]}</div>
</div>"""
    return f"""<div style='margin-top:32px'><div style='font-size:15px;font-weight:800;color:#7c3aed;margin-bottom:8px;padding-bottom:8px;border-bottom:2px solid #e9d5ff'>🏦 INDIAN MUTUAL FUND SIP RECOMMENDATIONS</div>
<div style='font-size:12px;color:#6b7280;margin-bottom:16px;line-height:1.6'>Standing SIP list — invest monthly via your Indian bank account regardless of market signals. Total: <strong>Rs.{total:,}/month</strong> (≈ SGD {total/sgd_to_inr:,.0f}/month). Review annually.</div>
{cards}</div>"""

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
            tc="#15803d" if r["tier"]=="Strong Buy" else "#a16207"; tb="#dcfce7" if r["tier"]=="Strong Buy" else "#fef9c3"
            rec="<span style='background:#ede9fe;color:#7c3aed;font-size:10px;font-weight:700;padding:1px 5px;border-radius:10px;margin-left:4px'>🔄</span>" if r["recovery"] else ""
            t=r["targets"]; ml="52W High" if t.get("above_all_mas") else t["nearest_ma_label"]
            rows+=f"""<tr style='border-bottom:1px solid #f1f5f9'>
              <td style='padding:8px 10px;font-size:13px;font-weight:700;color:#374151'>{rank[r["ticker"]]}</td>
              <td style='padding:8px 10px'><div style='font-size:13px;font-weight:800;color:#111'>{r["ticker"]}</div><div style='font-size:11px;color:#9ca3af'>{r["name"][:30]}{"..." if len(r["name"])>30 else ""}</div></td>
              <td style='padding:8px 10px;font-size:12px'>{ps}</td>
              <td style='padding:8px 10px;text-align:center'><span style='background:{tb};color:{tc};border-radius:10px;font-size:11px;font-weight:700;padding:2px 8px'>{r["tier"]}</span>{rec}</td>
              <td style='padding:8px 10px;text-align:center'><span style='font-size:15px;font-weight:900;color:{r["trend_color"]}'>{r["trend_arrow"]}</span><div style='font-size:10px;color:{r["trend_color"]};font-weight:600'>{r["trend_dir"]}</div></td>
              <td style='padding:8px 10px;text-align:right'><span style='font-size:15px;font-weight:900;color:#1d4ed8'>{r["score"]}</span><span style='font-size:10px;color:#94a3b8'>/110</span></td>
              <td style='padding:8px 10px;font-size:12px;color:#15803d;font-weight:700;white-space:nowrap'>+{t["upside_pct_ma"]}% → {ml}</td>
              <td style='padding:8px 10px;font-size:13px;font-weight:800;color:#1d4ed8;white-space:nowrap'>SGD {r["allocation_sgd"]:,.0f}</td>
            </tr>"""
        sections+=f"""<table width='100%' cellpadding='0' cellspacing='0' style='border:1px solid #e5e7eb;border-radius:8px;margin-bottom:16px;overflow:hidden;border-collapse:collapse'>
          <thead><tr style='background:{cc}'><td colspan='8' style='color:#fff;font-size:12px;font-weight:800;text-transform:uppercase;letter-spacing:0.06em;padding:8px 14px'>{cat} — {len(items)} pick{"s" if len(items)!=1 else ""}</td></tr>
          <tr style='background:#f8fafc'><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>#</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:left'>Asset</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>Price</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:center'>Signal</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:center'>Trend</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600;text-align:right'>Score</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>Target</th><th style='padding:6px 10px;font-size:11px;color:#9ca3af;font-weight:600'>SGD Allocate</th></tr></thead>
          <tbody>{rows}</tbody></table>"""
    return sections

def asset_card(rank, r, usd_to_inr, sgd_to_inr, sgd_to_usd):
    meta=CATEGORY_META[r["category"]]; ts,tl=TIER_BADGE[r["tier"]]
    primary,secondary=format_amount(r["allocation_sgd"],r["price"],meta["currency"],usd_to_inr,sgd_to_inr,sgd_to_usd)
    ps=f"${r['price']:.4f}" if meta["currency"]=="USD" else f"Rs.{r['price']:.2f}"
    rc="#16a34a" if r["rs_pct"]>=0 else "#dc2626"; cc=CATEGORY_COLORS.get(r["category"],"#374151")
    regc={"bull":"#15803d","neutral":"#a16207","bear":"#dc2626"}[r["regime"]]; t=r["targets"]
    rec_banner=""
    if r["recovery"]:
        rec_banner="<div style='background:#ede9fe;border:1px solid #c4b5fd;border-radius:8px;padding:10px 16px;margin:12px 0'><span style='font-size:12px;font-weight:800;color:#7c3aed'>🔄 Recovery Watch — </span><span style='font-size:12px;color:#6d28d9'>Bear/neutral regime showing early reversal. RSI stabilising, short-term momentum improving. Confirm before acting.</span></div>"
    mx={"RS vs Benchmark":30,"Trend (DMA)":25,"RSI Quality":20,"MACD Momentum":15,"ADX Strength":10,"Volume":10}
    bd_rows="".join(f"<tr><td style='padding:3px 12px 3px 0;color:#6b7280;font-size:12px;white-space:nowrap'>{k}</td><td><div style='height:10px;width:{min(int(v*220/mx.get(k,30)),220)}px;background:#3b82f6;border-radius:4px;display:inline-block;vertical-align:middle'></div></td><td style='padding:3px 0 3px 8px;font-size:12px;font-weight:700;color:#1d4ed8'>{v}/{mx.get(k,'?')}</td></tr>" for k,v in r["breakdown"].items())
    an=("<div style='font-size:11px;color:#15803d;background:#dcfce7;border-radius:4px;padding:4px 8px;margin-bottom:8px;display:inline-block'>✓ Price above all MAs — full strength</div>" if t.get("above_all_mas") else "")
    return f"""<div style='border:1px solid #e5e7eb;border-left:4px solid {cc};border-radius:12px;padding:20px;margin-bottom:20px;background:#fff;font-family:-apple-system,BlinkMacSystemFont,sans-serif'>
  <table width='100%' cellpadding='0' cellspacing='0'><tr>
    <td valign='top'><div style='font-size:11px;color:{cc};font-weight:700;text-transform:uppercase;letter-spacing:0.05em'>#{rank} · {meta["label"]}</div><div style='font-size:18px;font-weight:800;color:#111;margin:4px 0 2px'>{r["name"]}</div><div style='font-size:13px;color:#9ca3af'>{r["ticker"]} | {ps}</div></td>
    <td valign='top' align='right' style='white-space:nowrap;padding-left:12px'><div style='display:inline-block;padding:4px 14px;border-radius:20px;font-size:12px;font-weight:800;{ts}'>{tl}</div><div style='margin-top:4px'><span style='font-size:18px;font-weight:900;color:{r["trend_color"]}'>{r["trend_arrow"]}</span><span style='font-size:13px;font-weight:700;color:{r["trend_color"]};margin-left:4px'>{r["trend_dir"]}</span></div><div style='font-size:24px;font-weight:900;color:#1d4ed8;margin-top:4px'>{primary}</div><div style='font-size:11px;color:#9ca3af;margin-top:2px'>{secondary}</div></td>
  </tr></table>
  <div style='background:#fffbeb;border-left:3px solid #f59e0b;border-radius:4px;padding:10px 14px;margin:12px 0;font-size:13px;color:#374151;line-height:1.6'><strong style='color:#a16207'>Why:</strong> {r["reason"]}</div>
  {rec_banner}
  <div style='overflow-x:auto;margin:14px 0 4px'><table cellpadding='0' cellspacing='6' style='white-space:nowrap'><tr>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Score</div><div style='font-size:18px;font-weight:900;color:#1d4ed8'>{r["score"]}<span style='font-size:10px;color:#94a3b8'>/110</span></div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>RS vs Bench</div><div style='font-size:16px;font-weight:800;color:{rc}'>{r["rs_pct"]:+.2f}%</div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>RSI</div><div style='font-size:16px;font-weight:800;color:#374151'>{r["rsi"]}</div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>ADX</div><div style='font-size:16px;font-weight:800;color:#374151'>{r["adx"]}</div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Vol Ratio</div><div style='font-size:16px;font-weight:800;color:#374151'>{r["vol_ratio"]}x</div></td>
    <td style='background:#f1f5f9;border-radius:8px;padding:8px 12px;text-align:center'><div style='font-size:10px;color:#94a3b8;margin-bottom:2px'>Regime</div><div style='font-size:14px;font-weight:800;color:{regc}'>{r["regime"].title()}</div></td>
  </tr></table></div>
  <div style='background:#f0fdf4;border:1px solid #bbf7d0;border-radius:8px;padding:14px 16px;margin:14px 0'>
    <div style='font-size:11px;color:#15803d;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px'>Price Targets</div>
    {an}
    <table cellpadding='0' cellspacing='0'><tr>
      <td style='padding-right:24px'><div style='font-size:11px;color:#6b7280;margin-bottom:2px'>{"52W High" if t.get("above_all_mas") else "Nearest MA"}</div><div style='font-size:18px;font-weight:800;color:#15803d'>+{t["upside_pct_ma"]}%</div><div style='font-size:11px;color:#374151'>{t["nearest_ma_label"]} @ {t["nearest_ma_val"]:,.4f}</div></td>
      <td style='padding:0 24px;border-left:1px solid #bbf7d0'><div style='font-size:11px;color:#6b7280;margin-bottom:2px'>3M High Recovery</div><div style='font-size:18px;font-weight:800;color:#0369a1'>+{t["upside_pct_3m"]}%</div><div style='font-size:11px;color:#374151'>{t["three_month_high"]:,.4f}</div></td>
      <td style='padding-left:24px;border-left:1px solid #bbf7d0'><div style='font-size:11px;color:#6b7280;margin-bottom:2px'>Current Dip</div><div style='font-size:18px;font-weight:800;color:#d97706'>-{r["dip"]}%</div><div style='font-size:11px;color:#374151'>from 3M high</div></td>
    </tr></table>
  </div>
  <div style='font-size:12px;padding:8px 12px;background:#f8fafc;border-radius:6px;margin-bottom:14px'>{ma_label_html(r["price"],r["ma_vals"])}</div>
  <div style='border-top:1px solid #f1f5f9;padding-top:12px'><div style='font-size:11px;color:#9ca3af;font-weight:700;text-transform:uppercase;letter-spacing:0.05em;margin-bottom:8px'>Score Breakdown</div><table cellpadding='0' cellspacing='0'>{bd_rows}</table></div>
</div>"""

# ══════════════════════════════════════════════════════
#  EMAIL + TELEGRAM + SEND
# ══════════════════════════════════════════════════════

def build_email(results, rn, rs_, usd_to_inr, sgd_to_inr, sgd_to_usd, date_str, macro, pf_html):
    strong=[r for r in results if r["tier"]=="Strong Buy"]; watch=[r for r in results if r["tier"]=="Watch"]
    rec_count=sum(1 for r in results if r["recovery"]); total_sgd=sum(r["allocation_sgd"] for r in results)
    rns,rnl,rnc=REGIME_STYLE[rn]; rss_,rsl,rsc=REGIME_STYLE[rs_]
    sc=asset_cards=[]; ac=""
    for i,r in enumerate(results):
        if r["tier"]=="Strong Buy": sc.append(asset_card(i+1,r,usd_to_inr,sgd_to_inr,sgd_to_usd))
    strong_cards="".join(sc) or "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Strong Buy signals today.</p>"
    wc=[]
    for i,r in enumerate(results):
        if r["tier"]=="Watch": wc.append(asset_card(i+1,r,usd_to_inr,sgd_to_inr,sgd_to_usd))
    watch_cards="".join(wc) or "<p style='color:#9ca3af;font-size:13px;padding:12px 0'>No Watch signals today.</p>"
    return f"""<!DOCTYPE html><html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'></head>
<body style='margin:0;padding:0;background:#f1f5f9;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif'>
<div style='max-width:760px;margin:0 auto;padding:24px 16px'>
  <div style='background:#1d4ed8;border-radius:14px 14px 0 0;padding:28px 28px 24px'>
    <div style='font-size:24px;font-weight:900;color:#fff'>Daily Market Screener</div>
    <div style='font-size:13px;color:#bfdbfe;margin-top:4px'>{date_str} &nbsp;|&nbsp; Budget: SGD {TOTAL_BUDGET_SGD:,}/month &nbsp;|&nbsp; Deployed: SGD {total_sgd:,.0f}</div>
    <table cellpadding='0' cellspacing='0' style='margin-top:20px'><tr>
      <td style='padding-right:24px'><div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Strong Buy</div><div style='font-size:32px;font-weight:900;color:#fff'>{len(strong)}</div></td>
      <td style='padding-right:24px'><div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Watch</div><div style='font-size:32px;font-weight:900;color:#fff'>{len(watch)}</div></td>
      <td style='padding-right:24px'><div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Recovery 🔄</div><div style='font-size:32px;font-weight:900;color:#fff'>{rec_count}</div></td>
      <td><div style='font-size:11px;color:#93c5fd;text-transform:uppercase;letter-spacing:0.05em'>Total Picks</div><div style='font-size:32px;font-weight:900;color:#fff'>{len(results)}</div></td>
    </tr></table>
  </div>
  {macro_html(macro)}
  <table width='100%' cellpadding='6' cellspacing='0' style='margin:0 0 16px'><tr>
    <td width='50%'><div style='{rns};padding:12px 16px;border-radius:8px'><div style='font-size:11px;color:{rnc};font-weight:700;text-transform:uppercase;letter-spacing:0.05em'>Nifty Regime</div><div style='font-size:15px;font-weight:800;color:{rnc};margin-top:2px'>{rnl}</div></div></td>
    <td width='50%'><div style='{rss_};padding:12px 16px;border-radius:8px'><div style='font-size:11px;color:{rsc};font-weight:700;text-transform:uppercase;letter-spacing:0.05em'>S&amp;P Regime</div><div style='font-size:15px;font-weight:800;color:{rsc};margin-top:2px'>{rsl}</div></div></td>
  </tr></table>
  {pf_html}
  <div style='font-size:15px;font-weight:800;color:#1d4ed8;margin:8px 0;padding-bottom:8px;border-bottom:2px solid #bfdbfe'>AT A GLANCE — TOP {len(results)} PICKS (Indian ≤25% · Global ETF 40% · Metals 20% · Crypto 15%)</div>
  {summary_html(results,usd_to_inr,sgd_to_inr,sgd_to_usd)}
  <div style='font-size:15px;font-weight:800;color:#15803d;margin:32px 0 14px;padding-bottom:8px;border-bottom:2px solid #bbf7d0'>STRONG BUY ({len(strong)})</div>
  {strong_cards}
  <div style='font-size:15px;font-weight:800;color:#a16207;margin:28px 0 14px;padding-bottom:8px;border-bottom:2px solid #fde68a'>WATCH LIST ({len(watch)})</div>
  {watch_cards}
  {mf_html(sgd_to_inr)}
  <div style='margin-top:32px;padding:16px;background:#fff;border-radius:10px;font-size:11px;color:#9ca3af;border:1px solid #e5e7eb;line-height:1.8'>
    <strong style='color:#6b7280'>Budget:</strong> SGD 4,000/month — Indian ≤25%, Global ETF 40%, Metals 20%, Crypto 15%. Score-weighted within each pool.<br>
    <strong style='color:#6b7280'>Scoring:</strong> RS (30) + Trend (25) + RSI (20) + MACD (15) + ADX (10) + Volume (10) = 110 max. Regime multiplier: Bull ×1.0, Neutral ×0.9, Bear ×0.75.<br>
    <strong style='color:#6b7280'>MF Section:</strong> Standing SIP via Indian bank account — invest monthly regardless of market signals.<br>
    <strong style='color:#6b7280'>Disclaimer:</strong> Not financial advice. Do your own research.
  </div>
</div></body></html>"""

def send_telegram(results, rn, rs_, macro, date_str):
    token=os.environ.get("TELEGRAM_BOT_TOKEN",""); chat_id=os.environ.get("TELEGRAM_CHAT_ID","")
    if not token or not chat_id: print("  [INFO] Telegram not configured — skipping."); return
    na="▲" if macro["nifty_chg"]>=0 else "▼"; sa="▲" if macro["sp_chg"]>=0 else "▼"
    lines=[f"📊 *Daily Screener — {date_str}*",f"Nifty: {macro['nifty_close']:,} {na}{abs(macro['nifty_chg'])}%  |  S&P: {macro['sp_close']:,} {sa}{abs(macro['sp_chg'])}%",f"1 SGD = Rs.{macro['sgd_inr']}  |  Regime: Nifty={rn.title()} · S&P={rs_.title()}","",f"💡 _{macro['regime_note']}_","","*🏆 TOP 5 PICKS*"]
    for i,r in enumerate(results[:5],1):
        icon="🟢" if r["tier"]=="Strong Buy" else "🟡"; rec=" 🔄" if r["recovery"] else ""
        lines.append(f"{i}. {icon} *{r['ticker']}* [{r['category']}]{rec}\n   SGD {r['allocation_sgd']:,.0f}  |  Score: {r['score']}/110  |  +{r['targets']['upside_pct_ma']}% target\n   {r['trend_arrow']} {r['trend_dir']}\n   _{r['reason']}_")
    lines.append("\nFull breakdown in your email 📧")
    try:
        url=f"https://api.telegram.org/bot{token}/sendMessage"
        payload=json.dumps({"chat_id":chat_id,"text":"\n".join(lines),"parse_mode":"Markdown"}).encode()
        req=urllib.request.Request(url,data=payload,headers={"Content-Type":"application/json"},method="POST")
        with urllib.request.urlopen(req,timeout=10) as resp: print("  Telegram sent." if resp.status==200 else f"  Telegram status {resp.status}")
    except Exception as e: print(f"  [WARN] Telegram failed: {e}")

def send_email(subject, html_body):
    email=os.environ["EMAIL_ADDRESS"]; pwd=os.environ["EMAIL_PASSWORD"]
    msg=MIMEMultipart("alternative"); msg["Subject"]=subject; msg["From"]=email; msg["To"]=email
    msg.attach(MIMEText(html_body,"html"))
    try:
        with smtplib.SMTP("smtp.gmail.com",587) as s: s.starttls(); s.login(email,pwd); s.send_message(msg)
        print("  Email sent.")
    except Exception as e: print(f"  Email error: {e}")

# ══════════════════════════════════════════════════════
#  MAIN
# ══════════════════════════════════════════════════════

def main():
    today=datetime.now().strftime("%d %b %Y"); today_key=datetime.now().strftime("%Y-%m-%d")
    print(f"\n{'='*55}\n  Daily Screener v4 (Singapore) — {today}\n{'='*55}\n")

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
    rn=get_regime(bn) if not bn.empty else "neutral"; rs_=get_regime(bs) if not bs.empty else "neutral"
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
            regime=rn if cat in ("Indian Stock","Indian ETF") else ("neutral" if cat=="Crypto" else rs_)
            result=score_asset(ticker,df.loc[common].copy(),bench.loc[common].copy(),cat,regime)
            if result: all_results.append(result)
        except: continue

    all_results.sort(key=lambda x:-x["score"])
    results=all_results[:GLOBAL_MAX_PICKS]
    results=apply_indian_pick_cap(results)
    results.sort(key=lambda x:(0 if x["tier"]=="Strong Buy" else 1,-x["score"]))

    allocs=compute_allocations(results)
    for r in results: r["allocation_sgd"]=round(allocs.get(r["ticker"],0),2)

    strong=[r for r in results if r["tier"]=="Strong Buy"]; watch=[r for r in results if r["tier"]=="Watch"]
    rec_count=sum(1 for r in results if r["recovery"])
    print(f"  Qualified: {len(all_results)}  |  Showing: {len(results)}  |  Strong Buy: {len(strong)}  |  Watch: {len(watch)}  |  Recovery: {rec_count}\n")
    for r in results:
        meta=CATEGORY_META[r["category"]]; ps=f"${r['price']:.2f}" if meta["currency"]=="USD" else f"Rs.{r['price']:.2f}"
        print(f"  [{r['tier']:11s}] {r['ticker']:18s} {r['category']:18s} Score={r['score']:5.1f}  SGD={r['allocation_sgd']:,.0f}  {r['trend_arrow']} {r['trend_dir']:<18s}  {ps}")

    save_history(results,today_key)
    html=build_email(results,rn,rs_,usd_to_inr,sgd_to_inr,sgd_to_usd,today,macro,pf)
    subject=f"[Screener {today}] {len(strong)} Strong Buy | {len(watch)} Watch | {rec_count} Recovery 🔄 | SGD {TOTAL_BUDGET_SGD:,} | Nifty={rn.title()} · S&P={rs_.title()}"
    send_email(subject,html)
    send_telegram(results,rn,rs_,macro,today)
    print(f"\n  Done. SGD deployed: {sum(r['allocation_sgd'] for r in results):,.0f}")

if __name__=="__main__":
    main()
