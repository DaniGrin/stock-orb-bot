"""ORB stock paper bot — Opening Range Breakout + EMA50 trend filter + step-trail 2R, EOD exit.
Live prices via yfinance (works on GitHub Actions). Virtual money, state persists to JSON.
Session-aware: US regular hours 09:30-16:00 ET. One trade per day per ticker.
Timeframe configurable: 1h (validated over 2y) or 15m (user's original idea, experimental).

  python stock_paper.py --ticker SPY --interval 1h --once
  python stock_paper.py --ticker SPY --interval 1h --replay 700
  python stock_paper.py --ticker SPY --interval 15m --replay 55
"""
import os, sys, time, json, math, argparse, traceback, datetime
import numpy as np, pandas as pd, yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.0002
OPEN_M, CLOSE_M = 9*60+30, 16*60
GRACE_MIN = 2                      # let Yahoo finalise a bar before trusting it
SETTLE_MIN = 15                    # wait this long after an early close before reading the closing price

def log(tag, msg):
    line = f"[{time.strftime('%Y-%m-%d %H:%M:%S')}] {msg}"
    print(line, flush=True)
    open(os.path.join(HERE, f"paper_{tag}.log"), "a").write(line + "\n")

def sfile(tag): return os.path.join(HERE, f"paper_{tag}_state.json")
def load_state(tag, cap):
    if os.path.exists(sfile(tag)): return json.load(open(sfile(tag)))
    return {"equity": cap, "session_date": "", "orH": None, "orL": None, "traded": False,
            "side": 0, "entry": 0.0, "R": 0.0, "peak": 0.0, "stop": 0.0, "qty": 0.0,
            "last_bar_ts": 0, "trades": 0, "wins": 0}
def save_state(tag, s): json.dump(s, open(sfile(tag), "w"), indent=2)
def fresh(cap):
    return {"equity": cap, "session_date": "", "orH": None, "orL": None, "traded": False,
            "side": 0, "entry": 0.0, "R": 0.0, "peak": 0.0, "stop": 0.0, "qty": 0.0,
            "last_bar_ts": 0, "trades": 0, "wins": 0}

def fetch(ticker, period, interval):
    d = yf.download(ticker, period=period, interval=interval, progress=False, auto_adjust=True)
    if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.droplevel(1)
    d = d.rename(columns=str.lower)[["open","high","low","close"]].dropna()
    d["ema"] = d.close.ewm(span=50, adjust=False).mean()
    return closed_only(d, 15 if interval == "15m" else 60)

def session_close(day):
    """Minutes after midnight ET at which the US session ends. NYSE closes early, at 13:00, on the day after
    Thanksgiving, and on 3 July and 24 December when they fall Monday-Thursday (a Friday there is a holiday)."""
    nov1 = datetime.date(day.year, 11, 1)
    thanksgiving = nov1 + datetime.timedelta(days=(3 - nov1.weekday()) % 7 + 21)      # 4th Thursday
    early = (day == thanksgiving + datetime.timedelta(days=1)
             or ((day.month, day.day) in ((7, 3), (12, 24)) and day.weekday() <= 3))
    return 13*60 if early else CLOSE_M

def official_close(ticker, day):
    """The closing price of one session from the daily series, or None if it cannot be read yet."""
    try:
        d = yf.download(ticker, period="1mo", interval="1d", progress=False, auto_adjust=True)
        if isinstance(d.columns, pd.MultiIndex): d.columns = d.columns.droplevel(1)
        x = d["Close"][[t.date() == day for t in d.index]].dropna()
        return float(x.iloc[-1]) if len(x) else None
    except Exception:
        return None

def closed_only(d, tf_min, now=None):
    """Drop the bar that is still forming. A bar ends tf_min after it starts, or at the session close.
    Without this a half-built bar was processed, marked as seen, and its final high/low never checked."""
    if d.index.tz is None: d.index = d.index.tz_localize("America/New_York")
    now = pd.Timestamp.now(tz="America/New_York") if now is None else now
    end = d.index + pd.Timedelta(minutes=tf_min)
    close = d.index.normalize() + pd.to_timedelta([session_close(t.date()) for t in d.index], unit="min")
    end = end.where(end < close, close)
    return d[(end + pd.Timedelta(minutes=GRACE_MIN)) <= now]

def _open(s, side, entry, R, risk, tkr, ts):
    qty = (s["equity"] * risk) / R
    s.update({"side": side, "entry": entry, "R": R, "peak": 0.0, "qty": qty,
              "stop": entry - R if side == 1 else entry + R, "traded": True})
    log(tkr, f"  {ts:%Y-%m-%d %H:%M} ET  ENTER {'LONG' if side==1 else 'SHORT'} @ {entry:.2f}  qty {qty:.1f}  stop {s['stop']:.2f}")

def _close(s, px, reason, tkr, ts):
    side, entry, qty = s["side"], s["entry"], s["qty"]
    pnl = side*(px-entry)*qty - 2*COST*entry*qty
    s["equity"] += pnl; s["trades"] += 1
    if pnl > 0: s["wins"] += 1
    log(tkr, f"  {ts:%Y-%m-%d %H:%M} ET  EXIT {reason} @ {px:.2f}  PnL {pnl:+.2f}  equity {s['equity']:.2f}  (WR {s['wins']}/{s['trades']})")
    s.update({"side": 0, "entry": 0.0, "R": 0.0, "peak": 0.0, "qty": 0.0, "stop": 0.0})

def handle_bar(ts, o, h, l, c, ema, s, args, tkr):
    etmin = ts.hour*60 + ts.minute
    close_m = session_close(ts.date())
    if etmin < OPEN_M or etmin >= close_m: return
    d = str(ts.date())
    if s["session_date"] != d:
        if s["side"] != 0: _close(s, o, "newday", tkr, ts)
        s.update({"session_date": d, "orH": None, "orL": None, "traded": False})
    if etmin < OPEN_M + args.or_min:
        s["orH"] = h if s["orH"] is None else max(s["orH"], h)
        s["orL"] = l if s["orL"] is None else min(s["orL"], l)
        return
    isEOD = etmin + args.tf_min >= close_m
    # manage open position
    if s["side"] == 1:
        if l <= s["stop"]: _close(s, s["stop"], "stop", tkr, ts)
        else:
            s["peak"] = max(s["peak"], (h - s["entry"]) / s["R"])
            lvl = math.floor(s["peak"] - args.activate) if s["peak"] >= args.activate else -1.0
            s["stop"] = s["entry"] + lvl * s["R"]
    elif s["side"] == -1:
        if h >= s["stop"]: _close(s, s["stop"], "stop", tkr, ts)
        else:
            s["peak"] = max(s["peak"], (s["entry"] - l) / s["R"])
            lvl = math.floor(s["peak"] - args.activate) if s["peak"] >= args.activate else -1.0
            s["stop"] = s["entry"] - lvl * s["R"]
    # entry (trend-aligned breakout, one per day)
    orR = (s["orH"]-s["orL"]) if s["orH"] is not None else None
    if s["side"] == 0 and orR and orR > 0 and not s["traded"] and not isEOD:
        if c > ema and h >= s["orH"]:   _open(s, 1, s["orH"], orR, args.risk, tkr, ts)
        elif c < ema and l <= s["orL"]: _open(s, -1, s["orL"], orR, args.risk, tkr, ts)
    if isEOD and s["side"] != 0:
        _close(s, c, "EOD", tkr, ts)

def settle_early_close(s, args, tkr, now, price_of):
    """End-of-day exit for early-close days. Their last half hour arrives empty from Yahoo, so no bar can
    trigger the exit: once the session is over, close any open position at that day's official close."""
    if s["side"] == 0 or not s["session_date"]: return False
    day = datetime.date.fromisoformat(s["session_date"])
    close_m = session_close(day)
    if close_m == CLOSE_M: return False                  # normal day: the last bar of the session exits
    end = pd.Timestamp(s["session_date"], tz="America/New_York") + pd.Timedelta(minutes=close_m)
    if now < end + pd.Timedelta(minutes=SETTLE_MIN): return False
    px = price_of(args.ticker.upper(), day)
    if px is None: return False                          # try again on the next run
    _close(s, px, "EOD", tkr, end)
    return True

def process(d, s, args, tkr, now=None, price_of=official_close):
    changed = False
    for ts, row in d.iterrows():
        tms = int(ts.value // 10**6)
        if tms <= s["last_bar_ts"]: continue
        if str(ts.date()) != s["session_date"]:          # a new session starts: the old one is over
            settle_early_close(s, args, tkr, ts, price_of)
        handle_bar(ts, float(row.open), float(row.high), float(row.low), float(row.close),
                   float(row.ema), s, args, tkr)
        s["last_bar_ts"] = tms; changed = True
    now = pd.Timestamp.now(tz="America/New_York") if now is None else now
    return settle_early_close(s, args, tkr, now, price_of) or changed

if __name__ == "__main__":
    p = argparse.ArgumentParser()
    p.add_argument("--ticker", default="SPY")
    p.add_argument("--interval", default="1h", choices=["15m", "1h"])
    p.add_argument("--or_min", type=int, default=0, help="opening-range minutes (0 = one bar)")
    p.add_argument("--activate", type=float, default=2.0)
    p.add_argument("--risk", type=float, default=0.01)
    p.add_argument("--capital", type=float, default=10000)
    p.add_argument("--once", action="store_true")
    p.add_argument("--replay", type=int, default=0)
    a = p.parse_args()
    a.tf_min = 15 if a.interval == "15m" else 60
    if a.or_min == 0: a.or_min = a.tf_min          # OR = the first bar of the session
    tkr = a.ticker.upper()
    tag = f"{tkr}_{a.interval}"

    if a.replay:
        maxp = 59 if a.interval == "15m" else 720
        s = fresh(a.capital)
        d = fetch(tkr, f"{min(a.replay, maxp)}d", a.interval)
        log(tag, f"=== REPLAY {tkr} {a.interval} last {a.replay}d (paper ${a.capital:,.0f}) ===")
        process(d, s, a, tkr=tag)
        log(tag, f"=== REPLAY done: equity ${s['equity']:,.2f} ({(s['equity']/a.capital-1)*100:+.1f}%)  "
                 f"trades {s['trades']}  WR {100*s['wins']/max(s['trades'],1):.0f}% ===")
        sys.exit(0)

    s = load_state(tag, a.capital)
    log(tag, f"=== {tkr} {a.interval} ORB paper | equity ${s['equity']:,.2f} | activate {a.activate}R risk {a.risk:.0%} ===")
    try:
        d = fetch(tkr, "20d" if a.interval == "1h" else "10d", a.interval)
        if s["last_bar_ts"] == 0 and len(d):
            # FRESH START: don't backtest history — just mark it seen, trade only NEW bars from now
            s["last_bar_ts"] = int(d.index[-1].value // 10**6)
            log(tag, f"  initialized fresh at ${s['equity']:,.0f} — trading only NEW bars from now (history skipped for EMA only)")
            save_state(tag, s)
        elif process(d, s, a, tkr=tag):
            save_state(tag, s)
    except Exception:
        log(tag, "ERROR:\n" + traceback.format_exc())
