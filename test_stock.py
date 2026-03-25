import yfinance as yf
import pandas as pd
import warnings
import smtplib
import os
from email.mime.text import MIMEText

warnings.simplefilter("ignore")

portfolio_size = 100000

# ---------- ASSET NAME MAPPING ----------
asset_names = {
    "SPY": "SPDR S&P 500 ETF Trust",
    "QQQ": "Invesco QQQ Trust",
    "VTI": "Vanguard Total Stock Market ETF",
    "VOO": "Vanguard S&P 500 ETF",
    "IVV": "iShares Core S&P 500 ETF",
    "EFA": "iShares MSCI EAFE ETF",
    "VEA": "Vanguard FTSE Developed Markets ETF",
    "IEFA": "iShares Core MSCI EAFE ETF",
    "EWJ": "iShares MSCI Japan ETF",
    "EWG": "iShares MSCI Germany ETF",
    "EWU": "iShares MSCI UK ETF",
    "EWQ": "iShares MSCI France ETF",
    "MCHI": "iShares MSCI China ETF",
    "FXI": "iShares China Large Cap ETF",
    "KWEB": "KraneShares China Internet ETF",
    "EEM": "iShares MSCI Emerging Markets ETF",
    "VWO": "Vanguard Emerging Markets ETF",
    "KSA": "iShares MSCI Saudi Arabia ETF",
    "UAE": "iShares MSCI UAE ETF",
    "GLD": "SPDR Gold Shares",
    "SLV": "iShares Silver Trust",
    "USO": "United States Oil Fund",
    "CPER": "United States Copper ETF",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum",
    "SOL-USD": "Solana",
    "BNB-USD": "Binance Coin"
}

# ---------- CATEGORY FUNCTION ----------
def get_category(stock):
    if stock.endswith(".NS"):
        return "Indian Stock"
    elif stock in global_etfs:
        return "Global ETF"
    elif stock in commodities:
        return "Commodity"
    elif stock in crypto_assets:
        return "Crypto"
    else:
        return "Other"

# ---------- UNIVERSE ----------
url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
symbols = pd.read_csv(url)["SYMBOL"].tolist()
nse_stocks = [s + ".NS" for s in symbols]

# EXPANDED GLOBAL ETF LIST
global_etfs = [
    "SPY","QQQ","VTI","VOO","IVV",
    "EFA","IEFA","VEA",
    "EWJ","EWG","EWU","EWQ",
    "MCHI","FXI","KWEB",
    "EEM","VWO",
    "KSA","UAE"
]

commodities = ["GLD","SLV","USO","CPER"]

crypto_assets = ["BTC-USD","ETH-USD","SOL-USD","BNB-USD"]

stocks = nse_stocks + global_etfs + commodities + crypto_assets

print("Downloading data...")

data = yf.download(
    tickers=stocks,
    period="3mo",
    interval="1d",
    group_by="ticker",
    threads=True,
    progress=True
)

# ---------- BENCHMARKS ----------
nifty = yf.download("^NSEI", period="3mo", progress=False)
nifty_return = (nifty["Close"].iloc[-1] - nifty["Close"].iloc[0]) / nifty["Close"].iloc[0]

sp500 = yf.download("^GSPC", period="3mo", progress=False)
sp500_return = (sp500["Close"].iloc[-1] - sp500["Close"].iloc[0]) / sp500["Close"].iloc[0]

opportunities = []

print("Scanning assets...")

for stock in stocks:

    try:
        if stock not in data.columns.levels[0]:
            continue

        df = data[stock].dropna()
        if len(df) < 30:
            continue

        close = df["Close"]
        volume = df["Volume"]

        price = float(close.iloc[-1])
        avg_volume = float(volume.tail(20).mean())

        # NSE liquidity filter
        if stock.endswith(".NS"):
            if price < 50 or avg_volume < 200000:
                continue

        stock_return = (close.iloc[-1] - close.iloc[0]) / close.iloc[0]

        if stock.endswith(".NS"):
            rs = stock_return - nifty_return
        else:
            rs = stock_return - sp500_return

        # 🔧 FIX 1: relaxed RS (allow up to -10%)
        if rs < -0.10:
            continue

        # 🔧 FIX 2: relaxed trend filter
        ma200 = close.rolling(200).mean()
        if ma200.dropna().empty:
            continue

        trend_score = 1 if price > float(ma200.iloc[-1]) else 0

        if price < 0.90 * float(ma200.iloc[-1]):
            continue

        # Dip
        dip = (close.max() - price) / close.max() * 100

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs_val = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs_val))
        rsi_val = float(rsi.iloc[-1])

        if dip >= 2:

            # 🔧 FIX 5: improved scoring
            score = dip + (40 - rsi_val) + (trend_score * 5)

            opportunities.append({
                "asset": stock,
                "dip": round(dip,2),
                "score": score
            })

    except:
        continue

# ---------- SORT ----------
opportunities = sorted(opportunities, key=lambda x: x["score"], reverse=True)

# ---------- ALLOCATION ----------
final_allocations = []

top_n = 15
selected = opportunities[:top_n]

if len(selected) > 0:
    per_asset = portfolio_size / len(selected)

    for asset in selected:
        final_allocations.append({
            "asset": asset["asset"],
            "amount": round(per_asset,0),
            "dip": asset["dip"]
        })

# 🔧 FIX 6: fallback only if extremely low signals
if len(final_allocations) < 5:

    fallback = opportunities[:5]

    for asset in fallback:
        final_allocations.append({
            "asset": asset["asset"],
            "amount": portfolio_size * 0.1,
            "dip": asset["dip"]
        })

# ---------- OUTPUT ----------
message = "Daily Diversified Investment Plan\n\n"

for i,a in enumerate(final_allocations):

    name = asset_names.get(a["asset"], a["asset"])
    category = get_category(a["asset"])

    message += (
        f"{i+1}. [{category}] {name} ({a['asset']})\n"
        f"   → BUY ₹{int(a['amount'])} (Dip {a['dip']}%)\n\n"
    )

print(message)

# ---------- EMAIL ----------
msg = MIMEText(message)

email = os.getenv("EMAIL_ADDRESS")
password = os.getenv("EMAIL_PASSWORD")

msg["Subject"] = "Daily Investment Allocation"
msg["From"] = email
msg["To"] = email

server = smtplib.SMTP("smtp.gmail.com",587)
server.starttls()

server.login(email,password)
server.send_message(msg)
server.quit()

print("Email sent")
