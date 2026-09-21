"""Live market price service — best-effort, pluggable providers.

Requirement: paper trades must open at REAL market price, not the consumer's
posted price. Provider order: Yahoo (works from this machine via curl for NSE
equities/indices, US, crypto, metals, commodities, forex) → Dhan MCP (NSE
options etc., when connected) → None (caller falls back to posted price and
flags price_source='posted').

Never raises: a failed/unreachable quote returns None so a poll no-ops for
that symbol, exactly like the legacy fetch_market.py contract.
"""
import json
import re
import subprocess

YAHOO_CHART = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range=1d&interval=1d"
UA = "Mozilla/5.0"

# consumer symbol root -> Yahoo ticker
INDEX_TICKERS = {
    'NIFTY': '^NSEI', 'NIFTY50': '^NSEI', 'NIFTYBANK': '^NSEBANK',
    'BANKNIFTY': '^NSEBANK', 'SENSEX': '^BSESN', 'FINNIFTY': '^NSEFIN',
    'MIDCPN': '^NSEMID', 'NIFTYNXT50': '^NSECNXNXT', 'INDIAVIX': '^INDIAVIX',
}
CRYPTO_TICKERS = {
    'BTC': 'BTC-USD', 'ETH': 'ETH-USD', 'XRP': 'XRP-USD', 'SOL': 'SOL-USD',
    'BNB': 'BNB-USD', 'DOGE': 'DOGE-USD', 'ADA': 'ADA-USD', 'BCH': 'BCH-USD',
    'LINK': 'LINK-USD', 'LTC': 'LTC-USD', 'TRX': 'TRX-USD',
}
METAL_TICKERS = {'GOLD': 'GC=F', 'SILVER': 'SI=F', 'PLATINUM': 'PL=F',
                 'COPPER': 'HG=F'}
COMMODITY_TICKERS = {'CRUDE': 'CL=F', 'CRUDEOIL': 'CL=F', 'OIL': 'BZ=F',
                     'NATURALGAS': 'NG=F', 'GAS': 'NG=F'}
FOREX_TICKERS = {'USDINR': 'USDINR=X', 'EURUSD': 'EURUSD=X', 'GBPUSD': 'GBPUSD=X',
                 'USDJPY': 'USDJPY=X', 'EURINR': 'EURINR=X', 'GBPINR': 'GBPINR=X'}

# Optional Dhan MCP endpoint (NSE options / deeper India coverage). Not wired
# until the connector is authenticated; kept as a clean seam.
DHAN_MCP_URL = "https://mcp.dhan.co/mcp"


def yahoo_ticker(symbol, asset_class='stock'):
    s = (symbol or '').upper().strip()
    s = re.sub(r'\b(CE|PE|CALL|PUT)\b', '', s).strip()
    root = s.split()[0] if s.split() else s
    if root in INDEX_TICKERS:
        return INDEX_TICKERS[root]
    if root in CRYPTO_TICKERS:
        return CRYPTO_TICKERS[root]
    if root in METAL_TICKERS:
        return METAL_TICKERS[root]
    if root in COMMODITY_TICKERS:
        return COMMODITY_TICKERS[root]
    if root in FOREX_TICKERS:
        return FOREX_TICKERS[root]
    if asset_class == 'crypto':
        return f'{root}-USD'
    if asset_class == 'forex':
        return f'{root}=X'
    # default: NSE equity
    return f'{root}.NS'


def _curl_json(url):
    try:
        out = subprocess.run(
            ['curl', '-s', '--max-time', '15', url, '-H', f'User-Agent: {UA}'],
            capture_output=True, text=True, timeout=20)
        return json.loads(out.stdout) if out.stdout else None
    except (subprocess.SubprocessError, subprocess.SubprocessError, ValueError, OSError):
        return None


def yahoo_quote(symbol, asset_class='stock'):
    data = _curl_json(YAHOO_CHART.format(ticker=yahoo_ticker(symbol, asset_class)))
    try:
        meta = data['chart']['result'][0]['meta']
        price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
        return float(price) if price else None
    except (KeyError, TypeError, ValueError, IndexError):
        return None


YAHOO_CHART_RANGE = "https://query1.finance.yahoo.com/v8/finance/chart/{ticker}?range={rng}&interval=1d"


def yahoo_historical_series(symbol, asset_class, rng='5y'):
    """(date, close) pairs for the trailing `rng` of real daily bars -- for
    backlog trades whose own day's close_eod() never ran (see
    close_stale_backlog). Unlike yahoo_quote() (today's live/last price
    only), this is meant to be fetched ONCE per symbol and reused for every
    date lookup against it (closest_close_on_or_before), rather than
    re-fetched per trade. '5y' covers this project's entire observed
    backlog (oldest Open trade: 2022-02-08) in one call."""
    data = _curl_json(YAHOO_CHART_RANGE.format(
        ticker=yahoo_ticker(symbol, asset_class), rng=rng))
    try:
        result = data['chart']['result'][0]
        timestamps = result['timestamp']
        closes = result['indicators']['quote'][0]['close']
    except (KeyError, TypeError, IndexError):
        return []
    from datetime import datetime, timezone
    series = []
    for ts, close in zip(timestamps, closes):
        if close is None:
            continue
        d = datetime.fromtimestamp(ts, tz=timezone.utc).date()
        series.append((d, float(close)))
    series.sort()
    return series


def closest_close_on_or_before(series, target_date):
    """Last real close at or before target_date from a yahoo_historical_series()
    result -- so a weekend/holiday target still resolves to the prior real
    session instead of None. series must be sorted ascending by date."""
    best = None
    for d, close in series:
        if d <= target_date:
            best = close
        else:
            break
    return best


def yahoo_historical_close(symbol, asset_class, target_date):
    """Single-lookup convenience wrapper around yahoo_historical_series() +
    closest_close_on_or_before() -- fetches a right-sized range for one
    (symbol, date) pair. Prefer yahoo_historical_series() directly when
    looking up many dates for the same symbol (e.g. close_stale_backlog)."""
    from datetime import date
    days_back = (date.today() - target_date).days
    rng = '3mo' if days_back <= 60 else '2y' if days_back <= 400 else '5y'
    series = yahoo_historical_series(symbol, asset_class, rng=rng)
    return closest_close_on_or_before(series, target_date)


def dhan_quote(symbol, asset_class='stock'):
    """Placeholder seam for the Dhan MCP provider (NSE options etc.).

    Returns None until the Dhan connector is configured/authenticated. When
    wired, this should call DHAN_MCP_URL and return a float price or None.
    """
    return None


def get_price(symbol, asset_class='stock'):
    """Return (price, source) or (None, None). Yahoo first, then Dhan."""
    p = yahoo_quote(symbol, asset_class)
    if p:
        return p, 'yahoo'
    p = dhan_quote(symbol, asset_class)
    if p:
        return p, 'dhan'
    return None, None
