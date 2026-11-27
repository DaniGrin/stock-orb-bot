# stock-orb-bot
Opening Range Breakout paper bot (SPY/QQQ/DIA) — EMA50 trend filter + step-trail 2R, EOD exit.
Runs free on GitHub Actions during US market hours.

> **Correction, 2026-11-27: this strategy has no demonstrated edge.** An earlier version of this README called the
> 1h variant "validated over 2y". That was wrong. The positive results came from the code itself, not the market.
> **All results recorded before 2026-11-27, including the live paper accounts, are inflated and invalid.**

## Fix log

**2026-11-27: closed bars only, and all of them.** The still-forming bar was processed and marked as seen, so its final high/low was never checked (about a third of runs fall inside the session). Only finished bars are processed now.

Trading rules are unchanged. Results recorded **before** this date were produced with the defect and have not been rewritten; treat 2026-11-27 as the start of the clean data.

**2026-11-27: end-of-day exit on early-close days.** The code assumed every session ends at 16:00 ET, so on a 13:00 close the end-of-day exit never fired and the position was carried to the next session's open. Yahoo leaves the last half hour of those days empty, so the scheduled NYSE early closes are now recognised and any open position is closed at that day's official closing price once the session is over. This restores the strategy's own rule (no overnight positions). No recorded trade was affected: 2026-11-27 is the first early close since the bot started.

**2026-11-27: entries that could really have been made.** The trend filter read the close of the very bar on which
the entry was booked, earlier in that bar, at the range edge (look-ahead). It also booked the edge price when the
bar had already opened beyond it, and ignored the stop on the entry bar. Now: the filter reads the previous bar, a
gap past the edge fills at the open, and an entry bar that also reaches the stop counts as stopped (the pessimistic
reading of an unknown intrabar order, matching how the bot already treats stops).

Two years of 1h bars, same signals and exits (SPY / QQQ / DIA):

| entry assumptions | SPY | QQQ | DIA |
|---|---|---|---|
| as previously coded | +40.6% | +77.5% | +42.5% |
| achievable fill price | +21.3% | +58.8% | +20.2% |
| + no look-ahead | -25.7% | +1.2% | -34.4% |
| **+ stop on the entry bar (current code)** | **-44.0%** | **-19.3%** | **-47.8%** |

`baseline_2026-11-27.json` records each account at the moment of the fix. Accounts were not reset and history was
not rewritten; measure the strategy only from that baseline.
