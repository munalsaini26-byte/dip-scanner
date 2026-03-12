import yfinance as yf
import pandas as pd
import warnings
import smtplib
from email.mime.text import MIMEText

warnings.simplefilter("ignore")

# Load NSE stocks
url = "https://archives.nseindia.com/content/equities/EQUITY_L.csv"
symbols = pd.read_csv(url)["SYMBOL"].tolist()
stocks = [s + ".NS" for s in symbols]

print("Downloading market data...")

# Batch download stock data
data = yf.download(
    tickers=stocks,
    period="3mo",
    interval="1d",
    group_by="ticker",
    threads=True,
    progress=True
)

# Download NIFTY index
nifty = yf.download("^NSEI", period="3mo", interval="1d", progress=False)
nifty_close = nifty["Close"]

nifty_return = (nifty_close.iloc[-1] - nifty_close.iloc[0]) / nifty_close.iloc[0]

opportunities = []

for stock in stocks:

    try:

        if stock not in data.columns.levels[0]:
            continue

        df = data[stock].dropna()

        if df.empty or len(df) < 30:
            continue

        close = df["Close"]
        volume = df["Volume"]

        current_price = float(close.iloc[-1])
        today_volume = float(volume.iloc[-1])
        avg_volume = float(volume.tail(20).mean())

        # Stock return
        stock_return = (close.iloc[-1] - close.iloc[0]) / close.iloc[0]

        # Relative strength vs NIFTY
        relative_strength = stock_return - nifty_return

        if current_price < 50:
            continue

        if avg_volume < 200000:
            continue

        # Skip stocks weaker than NIFTY
        if relative_strength < 0:
            continue

        ma200_series = close.rolling(200).mean()

        if ma200_series.dropna().empty:
            continue

        ma200 = float(ma200_series.iloc[-1])

        if current_price < ma200:
            continue

        volume_spike = today_volume > (1.5 * avg_volume)

        recent_high = float(close.max())
        dip = (recent_high - current_price) / recent_high * 100

        delta = close.diff()

        gain = delta.clip(lower=0)
        loss = -delta.clip(upper=0)

        avg_gain = gain.rolling(14).mean()
        avg_loss = loss.rolling(14).mean()

        rs = avg_gain / avg_loss
        rsi = 100 - (100 / (1 + rs))

        current_rsi = float(rsi.iloc[-1])

        if dip >= 3:

            score = dip + (40 - current_rsi) + (relative_strength * 100)

            if volume_spike:
                score += 5

            opportunities.append({
                "stock": stock,
                "dip": round(dip,2),
                "rsi": round(current_rsi,2),
                "rs": round(relative_strength*100,2),
                "volume_spike": volume_spike,
                "score": round(score,2)
            })

    except:
        continue


print("\nTOP OPPORTUNITIES TODAY\n")

opportunities = sorted(opportunities, key=lambda x: x["score"], reverse=True)
top10 = opportunities[:10]

for i, s in enumerate(top10):

    print(
        i+1,
        s["stock"],
        "Dip:", s["dip"], "%",
        "RSI:", s["rsi"],
        "RS:", s["rs"], "%",
        "Volume Spike:", s["volume_spike"],
        "Score:", s["score"]
    )

# Email results
message = "Top Dip Buying Opportunities\n\n"

if len(top10) == 0:

    message += "No qualifying opportunities today.\n"

else:

    for i, s in enumerate(top10):

        message += f"{i+1}. {s['stock']} | Dip {s['dip']}% | RSI {s['rsi']} | RS {s['rs']}%\n"


msg = MIMEText(message)

msg["Subject"] = "Daily Dip Buying Opportunities"
msg["From"] = "munalsaini26@gmail.com"
msg["To"] = "munalsaini26@gmail.com"

server = smtplib.SMTP("smtp.gmail.com", 587)
server.starttls()

server.login("munalsaini26@gmail.com", "zzdo vdat ccxx eawv")

server.send_message(msg)

server.quit()

print("\nEmail sent successfully!")
