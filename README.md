# stock-orb-bot
Opening Range Breakout paper bot (SPY/QQQ/DIA) — EMA50 trend filter + step-trail 2R, EOD exit.
Runs free on GitHub Actions during US market hours. 1h = validated over 2y; 15m = experimental.

## Fix log

**2026-11-27: closed bars only, and all of them.** The still-forming bar was processed and marked as seen, so its final high/low was never checked (about a third of runs fall inside the session). Only finished bars are processed now.

Trading rules are unchanged. Results recorded **before** this date were produced with the defect and have not been rewritten; treat 2026-11-27 as the start of the clean data.
