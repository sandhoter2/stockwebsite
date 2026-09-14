TELEGRAM TRADE TRACKER — PRODUCT & DESIGN AUDIT
=================================================
Reviewed live at: https://269b-2607-fb90-a084-55f-6d30-bd34-4c7b-3e78.ngrok-free.app
Stack (confirmed from code): Django + DRF backend, single-page React 18 loaded
straight from CDN with in-browser Babel (no build step), Bootstrap 5 for styling.
Logged in as admin using the credentials documented in README.md to review the
real dashboard (Overview, Leaderboard, Favorite picks, Paper trading, Trades tabs)
at both desktop and mobile widths.

This is a first-pass analysis only. Nothing has been changed. Waiting for your
go-ahead before touching any code.

--------------------------------------------------------------
WHAT THE PRODUCT IS
--------------------------------------------------------------
A trading "signal tracker" that ingests trade calls posted in Telegram channels,
scores each channel's track record (win rate, realized/unrealized P/L, best/worst
trade, monthly history), shows cross-channel consensus on which symbols are being
bought/sold ("Favorite picks"), and lets a user auto- or manually paper-trade
those signals against real market prices with stop-loss/trailing-stop logic, then
scores each channel's *accuracy* (claimed move vs. what the market actually did).
Currently tracking 76 channels / 269 trades in the demo data.

It's a solid, data-dense analytics product. The core idea (rank channels by
verified accuracy, not just claimed P/L) is the differentiated part and it works.
The gaps below are almost all in the "last mile" — the polish, safety and
usability layer that separates an internal analytics tool from something you'd
put in front of real customers.

--------------------------------------------------------------
CRITICAL — FIX BEFORE ANY WIDER SHARING
--------------------------------------------------------------
1. Default admin password is "admin123" and is printed in plaintext in
   README.md, alongside a note that it's "intentionally weak." The app is
   currently reachable on a public ngrok URL. Anyone with the link can log in
   as admin, see the Django admin panel link in the navbar, and read/write all
   data. This is a live credential leak, not a hypothetical — treat it as the
   #1 priority before this URL is shared with anyone outside this session.

2. No production build. The dashboard ships React + ReactDOM + Babel-standalone
   from CDN and transpiles JSX in the browser on every page load (confirmed via
   a console warning: "You are using the in-browser Babel transformer... precompile
   your scripts for production"). This means: slower first paint, no code
   splitting, no minification of app code, and the entire UI logic (~700 lines)
   is delivered as readable source to any visitor. Fine for a personal/internal
   tool; not something to scale or demo externally as-is.

3. Mobile layout is broken, not just "unoptimized." At a 375px viewport the top
   navbar does not wrap: the "Django · DRF · React" subtitle, the API docs/Django
   admin links, and the Logout button are clipped off the right edge of the
   screen — Logout is not reachable at all on a phone without a workaround. The
   channel sidebar also renders as a full-width list above the main content
   instead of collapsing into a drawer/accordion, so a mobile user scrolls past
   ~40 channel rows before reaching the actual dashboard tabs.

--------------------------------------------------------------
HIGH — USABILITY / DATA-INTEGRITY GAPS
--------------------------------------------------------------
4. Channel names truncate illegibly in the sidebar even on desktop ("Money
   cre...", "Equitymast...", "Stocktwits ..."). There's a `title` attribute for
   hover, but on a list a user scans quickly, that's not discoverable — most
   users won't hover 40 rows to find the one they want. Needs either a wider
   sidebar, a two-line wrap, or truncation tuned to actually fit the common
   name lengths in this dataset.

5. The Trades tab is a 14-column table (Date, Posted, Channel, Sector, Trade,
   Dir, Entry, Target, SL, LTP/Exit, Unreal, P/L, Status, Note) inside a
   ~10-column-wide content area — "Target" is already clipped at the right edge
   on a standard laptop screen. This is the single densest, most
   information-critical view in the product and it's the one most likely to be
   unreadable without horizontal scrolling most users won't discover.

6. Destructive action has no confirmation. Deleting a paper trade (✕ button on
   the Paper Trading tab) fires immediately on click with no "are you sure" —
   easy to fat-finger on a table with a delete icon in the last column of every
   row.

7. No empty/loading skeletons beyond plain text ("Loading…", "Loading
   accuracy…") — acceptable for an internal tool, but any of these views hitting
   a slow API response reads as "is this broken?" rather than "this is working."

8. Numbers-as-truth without visible provenance in a few spots: "Favorite picks"
   shows BULLISH/BEARISH based on raw buy/sell channel counts with no visible
   weighting by channel accuracy — a channel with a 10% verified hit-rate counts
   the same as one with 95%. Given the product's own differentiator is
   *verified* accuracy, the consensus view arguably should reflect it, or at
   least visually flag when it doesn't.

--------------------------------------------------------------
MEDIUM — POLISH
--------------------------------------------------------------
9. Visual language is functional Bootstrap-default rather than a considered
   design system: color usage (indigo/blue/green/red/amber/purple/teal) is
   applied fairly ad hoc across sector badges, pulse-card accents, and buttons
   without a documented palette rationale — it reads busy, especially with 8
   sector colors plus win/loss red-green plus rank-medal gold/silver/bronze all
   competing on one screen.
10. No dark mode, despite the login screen itself using a dark gradient
    background that the dashboard then completely abandons for a light theme —
    a visual disconnect between the two screens of the same product.
11. No favicon / browser tab identity beyond the page `<title>`.
12. The "₹" rupee-symbol logo is a plain Unicode glyph, not a real mark — fine
    for now, but worth flagging if this is meant to look like a finished product
    rather than a working prototype.
13. API docs and Django admin links sit directly in the primary navbar next to
    Logout — appropriate for an internal/admin tool, but these are
    developer-facing surfaces that shouldn't be one click away for a
    non-technical end user in any customer-facing version.

--------------------------------------------------------------
WHAT'S ALREADY WORKING WELL
--------------------------------------------------------------
- Information architecture is genuinely good: Overview → Leaderboard → Favorite
  picks → Paper trading → Trades is a sensible progression from summary to
  detail, and the period/sector filter bar applies consistently across tabs.
- The "Track record vs Accuracy" toggle on the Leaderboard is the product's
  best idea, made visible and simple to use.
- Paper trading auto-preferences (capital/trade, SL%, trailing%) are exposed
  inline and editable without a modal — low friction.
- Backend design is clean: fat-queryset analytics methods (stats/breakdown/
  picks) keep the views thin, sensible unique constraints prevent duplicate
  trade rows, and the accuracy-scoring model (PaperTrade.mark/_close) is a
  well-isolated piece of business logic.

--------------------------------------------------------------
SUGGESTED PRIORITY ORDER
--------------------------------------------------------------
1. Rotate the admin password / stop shipping it in README.md before the ngrok
   link goes to anyone else.
2. Fix the mobile navbar (wrap or hamburger-collapse the topbar) — this is a
   full feature blocker on phone, not a nice-to-have.
3. Fix Trades-table overflow (sticky/scrollable table container, or a
   responsive column-priority scheme that hides secondary columns under a
   breakpoint).
4. Add a confirm step to paper-trade delete.
5. Everything else in MEDIUM is genuine polish — worth doing before an external
   demo, not urgent for continued internal use.

--------------------------------------------------------------
PRODUCT / USER PERSPECTIVE
--------------------------------------------------------------
Everything above was an engineering-eyes pass. Here's the same product looked
at as the person actually using it: someone who follows a bunch of Telegram
"buy this now" channels, is trying to work out which ones are worth trusting
with real money, and wants to act on today's calls — not just review history.

Who is this for, really?
  The product answers "how has this channel performed" very well. It does not
  yet answer the question that person opens the app to ask each morning:
  "what should I look at *today*?" Right now every tab is backward-looking
  (leaderboards, closed trades, monthly history). There is no "what's live
  right now" view — no list of today's/this-hour's calls across channels,
  sorted by the accuracy score you've already built. That's the single
  biggest product gap: the app knows which channels to trust, but never
  surfaces "here's what the trustworthy ones are saying right now" as a
  headline feature.

A. NO CLEAR VERDICT — just numbers
   The leaderboard gives success rate, W/L, realized ₹. It never just tells
   the user, in plain language, "follow this channel" / "this one is not
   worth your time." A first-time user has to do the interpretation
   themselves across 8 columns and 76 rows. A simple tiering (e.g. Top tier /
   Watch / Avoid, driven by the accuracy + sample-size data you already have)
   would turn a spreadsheet into a decision tool.

B. SMALL-SAMPLE CHANNELS LOOK AS CREDIBLE AS PROVEN ONES
   "NIRMAL BANG OFFICIAL" shows 100% success on 3 trades right next to
   "Angel One Research" at 90% on 56 trades — visually they read the same
   (both green, both bold %). A 3-trade streak and a 56-trade track record
   are not the same claim, but the UI presents them with equal confidence.
   This is the exact trap a trader relying on this tool could fall into:
   over-trusting a channel that just got lucky a few times. Worth flagging a
   trades-count/confidence indicator next to every percentage.

C. NO WAY TO FOLLOW/WATCHLIST CHANNELS
   With 76 channels, most users will only ever care about a handful. There's
   a search box but no "star" / "my channels" / saved shortlist — every
   session starts from the full unfiltered list again.

D. NO ALERTS — the app is pull-only
   To find out a top-accuracy channel just posted a new call, the user has to
   have the dashboard open and refresh. No email/Telegram/push notification
   when: a followed channel posts, a paper trade hits its stop-loss/target,
   or a channel's accuracy crosses a threshold (good or bad). For a
   time-sensitive product like trade signals, this is the difference between
   "useful" and "you'll actually use it."

E. PAPER TRADING HAS NO PORTFOLIO-LEVEL VIEW
   Each open paper position shows its own P/L, but there's no "total capital
   deployed right now," no exposure-by-sector breakdown, no view of whether
   the user is accidentally overloaded on one symbol or sector across
   multiple channels' calls. Risk is invisible at the portfolio level even
   though it's the thing that actually matters for real money decisions.

F. NO EXPLANATION LAYER FOR LESS-EXPERIENCED USERS
   Terms like "trailing %", "unrealized", "claimed-vs-market gap" are shown
   with zero inline explanation. This product's core value is trust/
   credibility scoring — that's exactly the audience most likely to include
   less sophisticated retail traders who need "accuracy = how often this
   channel's tips actually played out in real prices" spelled out, not
   assumed.

G. NOTHING IS SHAREABLE OR EXPORTABLE
   Someone in a Telegram trading community will want to say "here's this
   channel's real track record" or export their own trade log for their own
   records/taxes. No CSV export, no shareable per-channel report link.

H. NO SENSE OF "WHAT CHANGED"
   No daily/weekly digest ("3 new channels started posting this week", "your
   top-tier channel just dropped to 60% after 2 losses"). Everything is a
   live snapshot; there's no narrative of change over time that would pull a
   user back in regularly.

I. FIRST-TIME EXPERIENCE IS "HERE'S EVERYTHING AT ONCE"
   41 channels, 269 trades, 6 summary cards, filters, and a tab bar all load
   simultaneously with no onboarding — a new user has no guided path to "look
   at this first." A short "start here: your top 5 channels by verified
   accuracy" card on first login would do a lot of work.

Suggested product priority (highest leverage first):
  1. "Today's calls" / live feed view, ranked by channel accuracy — turns the
     product from a report into a daily habit.
  2. Plain-language trust tiers + a visible confidence/sample-size signal, so
     a 3-trade streak can't be mistaken for a proven track record.
  3. Follow/watchlist for channels, so the app narrows to what one person
     actually cares about.
  4. Alerts (new call from a followed channel; paper trade hit SL/target).
  5. Portfolio-level exposure view for paper trading.
  6. Inline glossary/tooltips on trading jargon.

--------------------------------------------------------------
Reply with which of the above you'd like me to act on (any item from either
section) and I'll get started.
--------------------------------------------------------------
