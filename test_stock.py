import yfinance as yf
import pandas as pd
import warnings
import smtplib
import os
from email.mime.text import MIMEText

warnings.simplefilter("ignore")

portfolio_size = 100000

print("Loading asset universe...")

# NSE STOCKS
url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
symbols = pd.read_csv(url)["SYMBOL"].tolist()
nse_stocks = [s + ".NS" for s in symbols]

# GLOBAL ETFS
global_etfs = [
    "SPY","QQQ","VTI","VGK","EWJ","MCHI","KWEB","KSA","UAE"
]

# COMMODITIES
commodities = [
    "GLD","SLV","USO","CPER"
]

# CRYPTO
crypto_assets = [
    "BTC-USD","ETH-USD"
]

stocks = nse_stocks + global_etfs + commodities + crypto_assets

print("Downloading market data...")

data = yf.download(
    tickers=stocks,
    period="3mo",
    interval="1d",
    group_by="ticker",
    threads=True,
    progress=True
)

# BENCHMARKS
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

        # Benchmark logic
        if stock.endswith(".NS"):
            relative_strength = stock_return - nifty_return
            asset_class = "india"
        elif stock in global_etfs:
            relative_strength = stock_return - sp500_return
            asset_class = "etf"
        elif stock in commodities:
            relative_strength = stock_return - sp500_return
            asset_class = "commodity"
        elif stock in crypto_assets:
            relative_strength = stock_return - sp500_return
            asset_class = "crypto"
        else:
            asset_class = "flex"

        # 🔧 FIX 1: Relax RS
        if relative_strength < -0.05:
            continue

        # 🔧 FIX 2: Relax 200DMA
        ma200 = close.rolling(200).mean()
        if ma200.dropna().empty:
            continue

        if price < 0.97 * float(ma200.iloc[-1]):
            continue

        # Dip calculation
        recent_high = float(close.max())
        dip = (recent_high - price) / recent_high * 100

        # RSI
        delta = close.diff()
        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))
        rsi_val = float(rsi.iloc[-1])

        # 🔧 FIX 3: Relax dip threshold
        if dip >= 2:

            score = dip + (40 - rsi_val) + (relative_strength * 100)

            opportunities.append({
                "asset": stock,
                "class": asset_class,
                "dip": round(dip,2),
                "score": score
            })

    except:
        continue

# SORT
opportunities = sorted(opportunities, key=lambda x: x["score"], reverse=True)

# ALLOCATION LOGIC
allocations = {
    "india":0.30,
    "etf":0.30,
    "commodity":0.20,
    "crypto":0.10,
    "flex":0.10
}

max_assets = {
    "india":6,
    "etf":6,
    "commodity":6,
    "crypto":4,
    "flex":2
}

final_allocations = []

for asset_class, weight in allocations.items():

    budget = portfolio_size * weight
    class_assets = [x for x in opportunities if x["class"] == asset_class]

    if len(class_assets) == 0:
        continue

    cap = max_assets[asset_class]
    per_asset = budget / min(len(class_assets),cap)

    for asset in class_assets[:cap]:

        final_allocations.append({
            "asset":asset["asset"],
            "amount":round(per_asset,0),
            "dip":asset["dip"]
        })

# 🔧 FIX 4: Fallback allocation
if len(final_allocations) == 0:

    final_allocations = [
        {"asset":"SPY","amount":portfolio_size*0.5,"dip":0},
        {"asset":"GLD","amount":portfolio_size*0.3,"dip":0},
        {"asset":"BTC-USD","amount":portfolio_size*0.2,"dip":0}
    ]

print("\nPORTFOLIO ALLOCATION\n")

for i,a in enumerate(final_allocations):
    print(i+1,"BUY ₹",int(a["amount"]),"of",a["asset"],"(Dip",a["dip"],"%)")

# EMAIL
message = "Daily Diversified Investment Plan\n\n"

for i,a in enumerate(final_allocations):
    message += f"{i+1}. BUY ₹{int(a['amount'])} of {a['asset']} (Dip {a['dip']}%)\n"

msg = MIMEText(message)

email = os.getenv("EMAIL_ADDRESS")
password = os.getenv("EMAIL_PASSWORD")

msg["Subject"] = "Daily Global Investment Allocation"
msg["From"] = email
msg["To"] = email

server = smtplib.SMTP("smtp.gmail.com",587)
server.starttls()

server.login(email,password)
server.send_message(msg)
server.quit()

print("\nEmail sent successfully")
