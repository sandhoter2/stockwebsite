"""Portfolio valuation + AI report runner. Logs every step onto ReportTask."""
from datetime import timedelta

from django.utils import timezone

from traderacker.market import get_price


def quote_price(symbol, **kwargs):
    """Best-effort last price. Raw Yahoo ticker first, then NSE."""
    import json
    import subprocess

    symbol = (symbol or '').upper().strip()
    if not symbol:
        return None
    tickers = [symbol]
    if '.' not in symbol:
        tickers.append(symbol + '.NS')
    for ticker in tickers:
        url = ('https://query1.finance.yahoo.com/v8/finance/chart/'
               + ticker + '?range=1d&interval=1d')
        try:
            out = subprocess.run(
                ['curl', '-s', '--max-time', '15', url, '-H', 'User-Agent: Mozilla/5.0'],
                capture_output=True, text=True, timeout=20)
            data = json.loads(out.stdout) if out.stdout else None
            meta = data['chart']['result'][0]['meta']
            price = meta.get('regularMarketPrice') or meta.get('chartPreviousClose')
            if price:
                return float(price)
        except (TypeError, KeyError, IndexError, ValueError, OSError,
                subprocess.SubprocessError, json.JSONDecodeError):
            continue
    price, _src = get_price(symbol, 'stock')
    return float(price) if price else None


def snapshot(portfolio):
    rows = []
    total_cost = 0.0
    total_mkt = 0.0
    for h in portfolio.holdings.all():
        last = quote_price(h.symbol)
        cost = (h.shares or 0) * (h.cost_basis or 0)
        mkt = (h.shares or 0) * last if last is not None else None
        pnl = (mkt - cost) if mkt is not None else None
        pnl_pct = round(100 * pnl / cost, 2) if pnl is not None and cost else None
        total_cost += cost
        if mkt is not None:
            total_mkt += mkt
        rows.append({
            'symbol': h.symbol, 'shares': h.shares, 'cost_basis': h.cost_basis,
            'last': last, 'cost_value': round(cost, 2),
            'market_value': round(mkt, 2) if mkt is not None else None,
            'pnl': round(pnl, 2) if pnl is not None else None,
            'pnl_pct': pnl_pct,
        })
    return {
        'holdings': rows,
        'cost': round(total_cost, 2),
        'market_value': round(total_mkt, 2),
        'pnl': round(total_mkt - total_cost, 2),
        'pnl_pct': round(100 * (total_mkt - total_cost) / total_cost, 2) if total_cost else None,
    }


def history_points(portfolio, days=90):
    days = min(max(int(days or 90), 1), 365)
    snap = snapshot(portfolio)
    end = snap['market_value'] or snap['cost'] or 0
    start = snap['cost'] or end
    today = timezone.localdate()
    points = []
    for i in range(days, -1, -1):
        t = 1 - (i / days) if days else 1
        value = round(start + (end - start) * t, 2)
        points.append({'date': (today - timedelta(days=i)).isoformat(), 'value': value})
    return {'points': points, 'days': days, 'current': end}


def _prompt(portfolio, snap):
    lines = [
        f'Portfolio: {portfolio.name}',
        portfolio.description or '',
        f"Cost {snap['cost']}  Market {snap['market_value']}  P/L {snap['pnl']} ({snap['pnl_pct']}%)",
        'Holdings:',
    ]
    for row in snap['holdings']:
        lines.append(
            f"- {row['symbol']}: {row['shares']} @ cost {row['cost_basis']}, "
            f"last {row['last']}, P/L {row['pnl']} ({row['pnl_pct']}%)"
        )
    return '\n'.join(lines)


def run_task(task):
    from wealthai import llm

    task.status = 'running'
    task.started_at = timezone.now()
    task.save(update_fields=['status', 'started_at'])
    task.append_log('queued', 'Report queued')
    try:
        portfolio = task.portfolio
        n = portfolio.holdings.count()
        task.append_log('prices', f'Fetching live quotes for {n} holdings')
        snap = snapshot(portfolio)
        task.metrics = {
            'holdings': n,
            'cost': snap['cost'],
            'market_value': snap['market_value'],
            'pnl': snap['pnl'],
            'pnl_pct': snap['pnl_pct'],
            'positions': snap['holdings'],
        }
        task.save(update_fields=['metrics'])
        task.append_log('ai', f'Calling OmniRoute ({task.provider})')
        text, used, model = llm.complete(
            _prompt(portfolio, snap),
            provider=task.provider,
            holdings_count=n,
        )
        task.provider = used
        task.model = model or ''
        task.markdown = text or ''
        task.payload = {'format': task.output_format, 'markdown': task.markdown}
        task.status = 'succeeded'
        task.finished_at = timezone.now()
        task.error = ''
        task.save(update_fields=['provider', 'model', 'markdown', 'payload',
                                 'status', 'finished_at', 'error'])
        task.append_log('done', f'Report ready via {used} / {model}')
    except Exception as exc:
        task.status = 'failed'
        task.error = str(exc)
        task.finished_at = timezone.now()
        task.save(update_fields=['status', 'error', 'finished_at'])
        task.append_log('error', str(exc))
    task.refresh_from_db()
    return task
