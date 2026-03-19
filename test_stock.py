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
    "VGK": "Vanguard FTSE Europe ETF",
    "EWJ": "iShares MSCI Japan ETF",
    "MCHI": "iShares MSCI China ETF",
    "KWEB": "KraneShares CSI China Internet ETF",
    "KSA": "iShares MSCI Saudi Arabia ETF",
    "UAE": "iShares MSCI UAE ETF",
    "GLD": "SPDR Gold Shares",
    "SLV": "iShares Silver Trust",
    "USO": "United States Oil Fund",
    "CPER": "United States Copper Index Fund",
    "BTC-USD": "Bitcoin",
    "ETH-USD": "Ethereum"
}

# ---------- CATEGORY MAPPING ----------
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

print("Downloading data...")

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

print("Scanning...")

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

        if stock.endswith(".NS"):
            if price < 50 or avg_volume < 200000:
                continue

        stock_return = (close.iloc[-1] - close.iloc[0]) / close.iloc[0]

        if stock.endswith(".NS"):
            rs = stock_return - nifty_return
            asset_class = "india"
        else:
            rs = stock_return - sp500_return
            asset_class = "global"

        if rs < -0.05:
            continue

        ma200 = close.rolling(200).mean()
        if ma200.dropna().empty:
            continue

        if price < 0.97 * float(ma200.iloc[-1]):
            continue

        dip = (close.max() - price) / close.max() * 100

        if dip >= 2:
            opportunities.append({
                "asset": stock,
                "dip": round(dip,2),
                "score": dip + rs*100
            })

    except:
        continue

opportunities = sorted(opportunities, key=lambda x: x["score"], reverse=True)

# ---------- ALLOCATION ----------
final_allocations = []

if len(opportunities) == 0:
    final_allocations = [
        {"asset":"SPY","amount":50000,"dip":0},
        {"asset":"GLD","amount":30000,"dip":0},
        {"asset":"BTC-USD","amount":20000,"dip":0}
    ]
else:
    per_asset = portfolio_size / min(len(opportunities),10)

    for asset in opportunities[:10]:
        final_allocations.append({
            "asset":asset["asset"],
            "amount":round(per_asset,0),
            "dip":asset["dip"]
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
