"""
Signals-only bot for Deriv synthetic indices.

- Pulls candles from Deriv's free WebSocket API
- Sends a Telegram alert when a signal fires
- Logs every signal to signals.csv and scores it HORIZON candles later
- `python synth_signals.py --report` shows results vs. a coin flip

Setup:
    pip install websocket-client pandas requests
    export TG_TOKEN="123456:ABC..."
    export TG_CHAT_ID="123456789"
    python synth_signals.py
"""
import json, math, os, sys, time
import pandas as pd
import requests
import websocket

# ---------- settings ----------
TOKEN = os.environ.get("TG_TOKEN", "")
CHAT_ID = os.environ.get("TG_CHAT_ID", "")
SYMBOLS = ["R_75", "R_100"]     # also: BOOM1000, CRASH1000, stpRNG, ...
GRANULARITY = 900                # candle size in seconds (900 = 15m)
HORIZON = 4                      # score each signal after this many candles
RSI_LEN, RSI_LOW, RSI_HIGH = 14, 30, 70
LOG_FILE = "signals.csv"
WS_URL = "wss://ws.derivws.com/websockets/v3?app_id=1089"
COLUMNS = ["epoch", "symbol", "direction", "entry", "status", "exit", "result"]


# ---------- data ----------
def fetch_candles(symbol, count=500):
    ws = websocket.create_connection(WS_URL, timeout=15)
    try:
        ws.send(json.dumps({
            "ticks_history": symbol, "end": "latest", "count": count,
            "style": "candles", "granularity": GRANULARITY,
        }))
        data = json.loads(ws.recv())
    finally:
        ws.close()
    if "candles" not in data:
        raise RuntimeError(data.get("error", data))
    df = pd.DataFrame(data["candles"])
    # the last candle is still forming, so drop it
    return df.iloc[:-1].reset_index(drop=True)


def rsi(close, n):
    delta = close.diff()
    gain = delta.clip(lower=0).ewm(alpha=1 / n, adjust=False).mean()
    loss = (-delta.clip(upper=0)).ewm(alpha=1 / n, adjust=False).mean()
    return 100 - 100 / (1 + gain / loss)


# ---------- strategy (replace this with your own rules to test) ----------
def check_signal(df):
    df = df.copy()
    df["rsi"] = rsi(df["close"], RSI_LEN)
    last = df.iloc[-1]
    if last["rsi"] < RSI_LOW:
        return "BUY", last
    if last["rsi"] > RSI_HIGH:
        return "SELL", last
    return None, last


# ---------- telegram ----------
def send(msg):
    if not TOKEN or not CHAT_ID:
        print("[no telegram configured]", msg)
        return
    try:
        requests.post(f"https://api.telegram.org/bot{TOKEN}/sendMessage",
                      data={"chat_id": CHAT_ID, "text": msg}, timeout=10)
    except requests.RequestException as e:
        print("Telegram error:", e)


# ---------- logging & scoring ----------
def load_log():
    if os.path.exists(LOG_FILE):
        return pd.read_csv(LOG_FILE)
    return pd.DataFrame(columns=COLUMNS)


def already_logged(log, symbol, epoch):
    return ((log["symbol"] == symbol) & (log["epoch"] == epoch)).any()


def resolve_pending(log, symbol, df):
    closes = df.set_index("epoch")["close"]
    mask = (log["symbol"] == symbol) & (log["status"] == "pending")
    for i in log[mask].index:
        target = int(log.at[i, "epoch"]) + HORIZON * GRANULARITY
        if target in closes.index:
            exit_price = float(closes[target])
            entry = float(log.at[i, "entry"])
            moved_up = exit_price > entry
            win = moved_up if log.at[i, "direction"] == "BUY" else (exit_price < entry)
            log.at[i, "status"] = "done"
            log.at[i, "exit"] = exit_price
            log.at[i, "result"] = "win" if win else "loss"
    return log


# ---------- report ----------
def report():
    log = load_log()
    done = log[log["status"] == "done"]
    n = len(done)
    if n == 0:
        print("No scored signals yet. Let the bot run longer.")
        return
    wins = int((done["result"] == "win").sum())
    rate = wins / n
    # two-sided z-test against a 50% coin flip
    z = (wins - n * 0.5) / math.sqrt(n * 0.25)
    p = math.erfc(abs(z) / math.sqrt(2))
    print(f"Scored signals: {n}")
    print(f"Wins: {wins}  Win rate: {rate:.1%}")
    print(f"p-value vs 50% coin flip: {p:.3f}")
    print("Note: ignores spread/fees, which make real results worse.")
    if n < 200:
        print("Sample is small (<200). Don't read much into this yet.")
    elif p > 0.05:
        print("Not distinguishable from random chance.")
    else:
        print("Statistically unusual, but re-test on fresh data before trusting it.")
    print("\nPer symbol:")
    print(done.groupby("symbol")["result"].apply(lambda s: f"{(s == 'win').mean():.1%} ({len(s)})"))


# ---------- main loop ----------
def run_once():
    log = load_log()
    for symbol in SYMBOLS:
        try:
            df = fetch_candles(symbol)
            log = resolve_pending(log, symbol, df)
            direction, last = check_signal(df)
            epoch = int(last["epoch"])
            if direction and not already_logged(log, symbol, epoch):
                row = dict(epoch=epoch, symbol=symbol, direction=direction,
                           entry=float(last["close"]), status="pending",
                           exit="", result="")
                log = pd.concat([log, pd.DataFrame([row])], ignore_index=True)
                send(f"{direction} signal on {symbol}\n"
                     f"Price: {last['close']}\n"
                     f"Candle: {GRANULARITY // 60}m | Scored after {HORIZON} candles")
        except Exception as e:
            print(f"{symbol} error:", e)
    log.to_csv(LOG_FILE, index=False)


def main():
    send(f"Signal bot started. Watching: {', '.join(SYMBOLS)}")
    while True:
        run_once()
        time.sleep(60)


if __name__ == "__main__":
    if "--report" in sys.argv:
        report()
    elif "--once" in sys.argv:
        run_once()
    else:
        main()
