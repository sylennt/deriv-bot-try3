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


if name == "main":
    if "--report" in sys.argv:
        report()
    elif "--once" in sys.argv:
        run_once()
    else:
        main()
