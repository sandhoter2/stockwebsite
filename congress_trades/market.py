"""Approximate pricing for congressional trade disclosures.

Congress (STOCK Act) disclosures report a dollar *range* for each
transaction -- never a share count or a per-share price -- so there is no
exact P/L to read off a filing the way traderacker.PaperTrade reads a real
entry/exit price. Anything computed here is therefore an ESTIMATE:

* the transaction's dollar value is approximated as the midpoint of the
  disclosed amount_min/amount_max range (see CongressTrade.amount_mid);
* the price move behind a trade is approximated from the ticker's actual
  market price on the transaction date vs. either (a) the price on a later
  matched sale's transaction date (realized), or (b) today's price (open /
  unrealized) -- i.e. the disclosed dollar amount is treated as a notional
  that rides the stock's real subsequent % return, the same "% move on a
  notional" shape traderacker.PaperTrade already uses for paper trades.

We reuse traderacker.market's never-raises curl/JSON fetch helper (same
provider, same failure-safe contract: a bad network/response just yields
None) instead of building a second fetch mechanism from scratch. We do NOT
reuse traderacker.market.yahoo_ticker/get_price for the actual symbol
resolution, though: that helper defaults an unrecognized ticker to NSE
(`SYMBOL.NS`), because traderacker's channels post Indian-market calls.
Congress disclosures are all US-listed (NYSE/NASDAQ) securities, so a plain
ticker here should resolve to itself, not to an NSE symbol -- reusing
yahoo_ticker's default branch as-is would silently price nearly every
Congress trade against the wrong market (this was caught by a first real
run: every US ticker got treated as absent because '<TICKER>.NS' doesn't
exist on Yahoo). We still defer to traderacker's INDEX/CRYPTO/METAL/
COMMODITY/FOREX tables for the handful of non-plain-equity tickers a
disclosure might list (e.g. a member trading gold or a crypto-linked
asset), since those *are* market-agnostic and correctly shared.
"""
from datetime import timedelta

from traderacker.market import (COMMODITY_TICKERS, CRYPTO_TICKERS, FOREX_TICKERS,
                                INDEX_TICKERS, METAL_TICKERS, _curl_json)

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
YAHOO_CHART_RANGE = (
    "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}"
    "?period1={p1}&period2={p2}&interval=1d"
)


def congress_yahoo_ticker(ticker):
    """Resolve a disclosed ticker to a Yahoo Finance symbol, assuming a
    plain US-listed equity by default (unlike traderacker.market.yahoo_ticker,
    which defaults to NSE) -- see module docstring for why."""
    root = (ticker or '').upper().strip()
    if not root:
        return root
    return (INDEX_TICKERS.get(root) or CRYPTO_TICKERS.get(root) or METAL_TICKERS.get(root)
            or COMMODITY_TICKERS.get(root) or FOREX_TICKERS.get(root) or root)


def get_price(ticker):
    """Current price for a Congress-disclosed US ticker, or (None, None) on
    any failure. Same (price, source) shape as traderacker.market.get_price,
    just resolved against the correct (US, not NSE) default market."""
    data = _curl_json(YAHOO_CHART.format(ticker=congress_yahoo_ticker(ticker)))
    try:
        meta = data['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
        return (float(price), 'yahoo') if price else (None, None)
    except (KeyError, TypeError, ValueError, IndexError):
        return None, None


def historical_price(ticker, on_date):
    """Best-effort closing price for `ticker` on or shortly after `on_date`
    (a date object). Looks up to 7 calendar days forward to land on the
    next trading day when on_date falls on a weekend/holiday.

    Never raises -- returns None on any failure (unknown ticker, no
    network, unexpected response shape), exactly like traderacker.market's
    get_price contract, so callers can treat "no price" as "cannot
    estimate" rather than a crash.
    """
    if not ticker or not on_date:
        return None
    try:
        import time as _time
        p1 = int(_time.mktime(on_date.timetuple()))
        p2 = int(_time.mktime((on_date + timedelta(days=7)).timetuple()))
    except (OverflowError, ValueError, OSError):
        return None
    url = YAHOO_CHART_RANGE.format(ticker=congress_yahoo_ticker(ticker), p1=p1, p2=p2)
    data = _curl_json(url)
    try:
        result = data['chart']['result'][0]
        closes = result['indicators']['quote'][0]['close']
        for c in closes:
            if c is not None:
                return float(c)
        return None
    except (KeyError, TypeError, IndexError):
        return None
