"""ORB stock paper bot — Opening Range Breakout + EMA50 trend filter + step-trail 2R, EOD exit.
Live prices via yfinance (works on GitHub Actions). Virtual money, state persists to JSON.
Session-aware: US regular hours 09:30-16:00 ET. One trade per day per ticker.
Timeframe configurable: 1h (validated over 2y) or 15m (user's original idea, experimental).

  python stock_paper.py --ticker SPY --interval 1h --once
  python stock_paper.py --ticker SPY --interval 1h --replay 700
  python stock_paper.py --ticker SPY --interval 15m --replay 55
"""
import os, sys, time, json, math, argparse, traceback
import numpy as np, pandas as pd, yfinance as yf

HERE = os.path.dirname(os.path.abspath(__file__))
COST = 0.0002
OPEN_M, CLOSE_M = 9*60+30, 16*60

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
    return d

def _open(s, side, entry, R, risk, tkr):
    qty = (s["equity"] * risk) / R
    s.update({"side": side, "entry": entry, "R": R, "peak": 0.0, "qty": qty,
              "stop": entry - R if side == 1 else entry + R, "traded": True})
    log(tkr, f"  ENTER {'LONG' if side==1 else 'SHORT'} @ {entry:.2f}  qty {qty:.1f}  stop {s['stop']:.2f}")

def _close(s, px, reason, tkr):
    side, entry, qty = s["side"], s["entry"], s["qty"]
    pnl = side*(px-entry)*qty - 2*COST*entry*qty
    s["equity"] += pnl; s["trades"] += 1
    if pnl > 0: s["wins"] += 1
    log(tkr, f"  EXIT {reason} @ {px:.2f}  PnL {pnl:+.2f}  equity {s['equity']:.2f}  (WR {s['wins']}/{s['trades']})")
    s.update({"side": 0, "entry": 0.0, "R": 0.0, "peak": 0.0, "qty": 0.0, "stop": 0.0})

def handle_bar(ts, o, h, l, c, ema, s, args, tkr):
    etmin = ts.hour*60 + ts.minute
    if etmin < OPEN_M or etmin >= CLOSE_M: return
    d = str(ts.date())
    if s["session_date"] != d:
        if s["side"] != 0: _close(s, o, "newday", tkr)
        s.update({"session_date": d, "orH": None, "orL": None, "traded": False})
    if etmin < OPEN_M + args.or_min:
        s["orH"] = h if s["orH"] is None else max(s["orH"], h)
        s["orL"] = l if s["orL"] is None else min(s["orL"], l)
        return
    isEOD = etmin + args.tf_min >= CLOSE_M
    # manage open position
    if s["side"] == 1:
        if l <= s["stop"]: _close(s, s["stop"], "stop", tkr)
        else:
            s["peak"] = max(s["peak"], (h - s["entry"]) / s["R"])
            lvl = math.floor(s["peak"] - args.activate) if s["peak"] >= args.activate else -1.0
            s["stop"] = s["entry"] + lvl * s["R"]
    elif s["side"] == -1:
        if h >= s["stop"]: _close(s, s["stop"], "stop", tkr)
        else:
            s["peak"] = max(s["peak"], (s["entry"] - l) / s["R"])
            lvl = math.floor(s["peak"] - args.activate) if s["peak"] >= args.activate else -1.0
            s["stop"] = s["entry"] - lvl * s["R"]
    # entry (trend-aligned breakout, one per day)
    orR = (s["orH"]-s["orL"]) if s["orH"] is not None else None
    if s["side"] == 0 and orR and orR > 0 and not s["traded"] and not isEOD:
        if c > ema and h >= s["orH"]:   _open(s, 1, s["orH"], orR, args.risk, tkr)
        elif c < ema and l <= s["orL"]: _open(s, -1, s["orL"], orR, args.risk, tkr)
    if isEOD and s["side"] != 0:
        _close(s, c, "EOD", tkr)

def process(d, s, args, tkr):
    changed = False
    for ts, row in d.iterrows():
        tms = int(ts.value // 10**6)
        if tms <= s["last_bar_ts"]: continue
        handle_bar(ts, float(row.open), float(row.high), float(row.low), float(row.close),
                   float(row.ema), s, args, tkr)
        s["last_bar_ts"] = tms; changed = True
    return changed

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
        if process(d, s, a, tkr=tag): save_state(tag, s)
    except Exception:
        log(tag, "ERROR:\n" + traceback.format_exc())
