"""Official NSE F&O settlement prices, via jugaad-data's UDiFF daily-reports
client -- used only by reconcile_eod_settlement to upgrade close_eod()'s
same-day intrinsic-value *estimate* to the real traded closing premium,
after NSE actually publishes it (well after the 15:27-15:30 IST window
close_eod() itself runs in, so this can never be done in-place at close).

NSE's daily-reports API only serves the current and previous trading day --
this is a same-day/next-day reconciliation tool, not a historical backfill.

NSE derivatives only: index options (NIFTY, BANKNIFTY, FINNIFTY, ...) and
NSE stock options. BSE-listed SENSEX and MCX commodities/metals have no
row here and are always skipped by the caller.
"""
import csv
import io
import zipfile

from jugaad_data.nse.archives import NSEDailyReports

_reports = NSEDailyReports()

# Per-date parsed-bhavcopy cache: {date: {(root, strike, opt_type): [(expiry, close, settle), ...]}}
_cache = {}


def _fetch_rows(trade_date):
    """Download + parse that day's F&O UDiFF bhavcopy into a lookup dict,
    keyed by (root_symbol, strike, opt_type) -> list of (expiry, close, settle)
    sorted by expiry ascending. Returns {} if NSE has nothing for this date
    (weekend/holiday, or outside the current/previous-day API window)."""
    if trade_date in _cache:
        return _cache[trade_date]
    lookup = {}
    try:
        content = _reports.download_file(
            'FO-UDIFF-BHAVCOPY-CSV', trading_date=trade_date, segment='FO')
        with zipfile.ZipFile(io.BytesIO(content)) as zf:
            with zf.open(zf.namelist()[0]) as fp:
                text = fp.read().decode('utf-8')
    except Exception:
        _cache[trade_date] = lookup
        return lookup
    for row in csv.DictReader(io.StringIO(text)):
        opt_type = (row.get('OptnTp') or '').strip()
        if opt_type not in ('CE', 'PE'):
            continue  # futures rows have no OptnTp
        try:
            root = row['TckrSymb'].strip().upper()
            strike = float(row['StrkPric'])
            expiry = row['XpryDt'].strip()
            close = float(row['ClsPric'])
            settle = float(row['SttlmPric'])
        except (KeyError, ValueError):
            continue
        lookup.setdefault((root, strike, opt_type), []).append((expiry, close, settle))
    for rows in lookup.values():
        rows.sort(key=lambda r: r[0])
    _cache[trade_date] = lookup
    return lookup


def official_option_close(root_symbol, strike, opt_type, trade_date):
    """Real traded closing premium for the nearest non-expired contract
    matching (root_symbol, strike, opt_type) on trade_date, or None if NSE
    has no such row (not an NSE F&O underlying, contract never listed,
    bhavcopy unavailable for that date, etc). Prefers the actual last
    traded close price (ClsPric); falls back to the daily settlement price
    (SttlmPric, used for MTM) only when the contract had no trades that day."""
    rows = _fetch_rows(trade_date)
    candidates = rows.get((root_symbol.upper(), float(strike), opt_type))
    if not candidates:
        return None
    expiry_str = trade_date.strftime('%Y-%m-%d')
    upcoming = [r for r in candidates if r[0] >= expiry_str]
    expiry, close, settle = upcoming[0] if upcoming else candidates[0]
    return close if close > 0 else settle
