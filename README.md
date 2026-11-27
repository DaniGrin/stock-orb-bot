# stock-orb-bot
Opening Range Breakout paper bot (SPY/QQQ/DIA) — EMA50 trend filter + step-trail 2R, EOD exit.
Runs free on GitHub Actions during US market hours. 1h = validated over 2y; 15m = experimental.

## Fix log

**2026-11-27: closed bars only, and all of them.** The still-forming bar was processed and marked as seen, so its final high/low was never checked (about a third of runs fall inside the session). Only finished bars are processed now.

Trading rules are unchanged. Results recorded **before** this date were produced with the defect and have not been rewritten; treat 2026-11-27 as the start of the clean data.

**2026-11-27: end-of-day exit on early-close days.** The code assumed every session ends at 16:00 ET, so on a 13:00 close the end-of-day exit never fired and the position was carried to the next session's open. Yahoo leaves the last half hour of those days empty, so the scheduled NYSE early closes are now recognised and any open position is closed at that day's official closing price once the session is over. This restores the strategy's own rule (no overnight positions). No recorded trade was affected: 2026-11-27 is the first early close since the bot started.
