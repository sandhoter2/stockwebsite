"""Telegram signal parser — converts raw channel messages into trade intents.

Pure functions (unit-testable). The `parse_signals` management command and any
poller feed TelegramMessage.text through parse_message()/parse_profit()/
parse_exit(). Deliberately conservative: no confident match → no trade.
Symbols must be ALL-CAPS (the ticker convention in these channels) so prose
words like "Not"/"supply" can never become phantom trades.
"""
import re

# number with optional thousands commas / decimals: 1570, 73,900, 0.3514, 8.50
NUM = r'(\d[\d,]*(?:\.\d+)?)'
# a bare all-caps ticker token
SYM = r'\b([A-Z][A-Z0-9&\-]{2,20})\b'

INDEX_ROOTS = {'NIFTY', 'BANKNIFTY', 'SENSEX', 'FINNIFTY', 'MIDCPN', 'NIFTYNXT50',
               'INDIAVIX'}
CRYPTO = {'BTC', 'ETH', 'XRP', 'SOL', 'BNB', 'DOGE', 'ADA', 'AVAX', 'DOT', 'LINK',
          'MATIC', 'TRX', 'LTC', 'BCH', 'JUP', 'ONDO', 'SUI', 'APT', 'ARB', 'OP',
          'NEAR', 'FIL', 'ATOM', 'USDT', 'USDC', 'ALT', 'CRYPTO', 'STX', 'TIA',
          'SEI', 'INJ', 'LDO', 'UNI', 'ETC', 'XLM', 'HBAR', 'ICP', 'SAND', 'MANA',
          'AXS', 'CHZ', 'ENJ', 'FLOW', 'XTZ', 'EOS', 'ALGO', 'VET', 'WIF', 'PEPE',
          'SHIB', 'AERO', 'PENGU', 'FET', 'RENDER', 'WLD', 'ENA', 'PYTH', 'JTO'}
METALS = {'GOLD', 'SILVER', 'PLATINUM', 'GOLDPETAL', 'SILVERPETAL', 'MCXGOLD',
          'MCXSILVER', 'COPPER', 'ALUMINUM', 'ZINC', 'LEAD', 'NICKEL'}
COMMODITY = {'CRUDE', 'CRUDEOIL', 'OIL', 'NATURALGAS', 'GAS', 'NG', 'LPG', 'COAL',
             'URINEA', 'MENTHA', 'COTTON', 'GUARGOM', 'JOJOB', 'TIN', 'METHANOL'}
FOREX = {'USDINR', 'EURUSD', 'GBPUSD', 'USDJPY', 'EURINR', 'GBPINR', 'AUDINR',
         'USDCAD', 'EURGBP', 'FX', 'FOREX', 'CURRENCY'}

STOP_WORDS = {
    'NOT', 'BUY', 'SELL', 'CALL', 'CALLS', 'PUT', 'PUTS', 'CASH', 'ABOVE',
    'BELOW', 'TARGET', 'TARGETS', 'TGT', 'VIEW', 'VIEWS', 'STOP', 'LOSS',
    'SUPPORT', 'HIT', 'BOOK', 'BOOKED', 'BOOKING', 'PROFIT', 'HOLDING',
    'HOLD', 'EXIT', 'TODAY', 'MARKET', 'LEVELS', 'LEVEL', 'OPINIONS',
    'EDUCATIONAL', 'PURPOSES', 'CONSULT', 'FINANCIAL', 'ADVISOR', 'BEFORE',
    'INVESTING', 'RESEARCH', 'DISCLAIMER', 'ARE', 'THE', 'AND', 'FOR',
    'ONLY', 'THESE', 'THAT', 'WITH', 'FROM', 'NEW', 'LOCK', 'INTRA',
    'BTST', 'SWING', 'INVESTMENT', 'UNDER', 'OVER', 'ENTRY', 'ENTER',
    'SAFE', 'HERE', 'SELLING', 'BOUGHT', 'TRADE', 'TRADES', 'POSITION',
    'POSITIONS', 'LONGTERM', 'SHORTTERM', 'GOLDEN', 'PLEASE', 'KINDLY',
    'ALSO', 'GET', 'OUR', 'YOU', 'YOUR', 'ALL', 'ANY', 'OUT', 'OFF', 'UP',
    'DOWN', 'NOW', 'RESULT', 'RESULTS', 'GOOD', 'JOIN', 'WHATSAPP',
    'WEBSITE', 'DISCLOSE', 'IN', 'ON', 'AT', 'POSITIONAL',
}


def _f(s):
    """Parse a possibly comma-grouped number to float."""
    return float(str(s).replace(',', ''))


def _is_symbol(tok):
    if tok != tok.upper():          # tickers here are always ALL CAPS
        return False
    return tok not in STOP_WORDS and any(c.isalpha() for c in tok)


# ---- asset-class classification -------------------------------------------
def classify(trade_str, direction, text):
    t = (trade_str or '').upper()
    x = (text or '').upper()
    sym = t.split()[0] if t.split() else ''
    if re.search(r'\b(CE|PE)\b', t) or (sym in INDEX_ROOTS and re.search(r'\d{4,}', t)):
        return 'option'
    if re.search(r'\b(CE|PE|CALL|PUT)\b', t) and re.search(r'\d{3,}', t):
        return 'option'
    if sym in CRYPTO or re.search(r'\b(LONG|SHORT)\b', x) and re.search(r'\d+\s*[Xx]\b', x):
        return 'crypto'
    if sym in METALS or re.search(r'\b(GOLD|SILVER)\b', t):
        return 'metal'
    if sym in COMMODITY or re.search(r'\b(CRUDE|NATURALGAS)\b', t):
        return 'commodity'
    if sym in FOREX or re.search(r'\b(PIPS|PIP)\b', x) or re.search(r'USD\s*/?\s*INR', x):
        return 'forex'
    if sym in INDEX_ROOTS:
        return 'index'
    if sym and _is_symbol(sym):
        return 'stock'
    return 'other'


# ---- signal regexes --------------------------------------------------------
RE_CASH = re.compile(
    SYM + r'\s+(?:\w+\s+)*?(?:CASH\s+)?(BREAKOUT\s+)?(ABOVE|BELOW)\s+' + NUM)
# root/strike may be joined by an underscore instead of (or in addition to)
# whitespace, e.g. "NIFTY\xa0 _23650PE" (Stock Thunder's entry-message shape)
RE_OPT = re.compile(
    r'\b([A-Z]+\s*_?\s*\d[\d,]*(?:\.\d+)?)\s*(CE|PE|CALL|PUT)\b'
    r'[\s:,@]*' + NUM + r'?')
# broker-style option order with an expiry date between the index and the
# strike, and a lot-size clause between the CE/PE and the premium, e.g.
# "BUY NIFTY 03 JUL 25 25700 CE 1 lots at 109.00."
RE_OPT_EXPIRY = re.compile(
    r'\b(?:BUY|SELL)\s+([A-Z]+)\s+\d{1,2}\s+[A-Z]{3}\s+\d{2,4}\s+' + NUM +
    r'\s*(CE|PE)\b\s*\d*\s*(?:lots?|qty)?\s*(?:at)?\s*' + NUM + r'?',
    re.IGNORECASE)
RE_BUYSELL = re.compile(
    SYM + r'\s+(BUY|SELL)\b[\s:@]*(?:AT\s+|CMP\s+|BELOW\s+|ABOVE\s+|INR\s+)?' + NUM + r'?')
RE_VERB_FIRST = re.compile(
    r'\b(BUY|SELL)\s+' + SYM + r'(?:\s+(?:CASH|FUT|FUTURES))?'
    r'(?:\s+\d[\d,]*(?:\.\d+)?\s*(?:shares?|lots?|qty))?'
    r'\s*(?:ABOVE|BELOW|AT|CMP|@|>)?\s*' + NUM,
    re.IGNORECASE)
RE_CRYPTO = re.compile(
    SYM + r'\s+(LONG|SHORT)\b\s*(\d+\s*[Xx])?')
RE_ENTER = re.compile(r'(?:ENTER|ENTRY|ENT)\s*[-:]?\s*' + NUM, re.IGNORECASE)
RE_PREMIUM = re.compile(r'(?:@\s*|ENTRY\s+|ENTER\s+(?:AT|IN)\s+)' + NUM, re.IGNORECASE)
RE_SUPPORT = re.compile(
    r'\b(?:SUPPORT|S/L|S/T|SL\b|STOP[\s\-]?LOSS|STOP|STCP)\s*[:\-]?\s*'
    r'(?:AT\s+|BELOW\s+|ABOVE\s+|NEAR\s+|ON\s+)?' + NUM, re.IGNORECASE)
RE_TARGET = re.compile(
    r'\b(?:VIEW|VIEWS|TARGETS?|TGT|TRG|SHT)\s*[:\-]?\s*'
    r'(?:AT\s+|ON\s+|NEAR\s+)?' + NUM, re.IGNORECASE)
RE_RANGE = re.compile(r'₹?\s*' + NUM + r'\s*[-–]\s*' + NUM)  # entry-target "₹250-320"
RE_HOLDING = re.compile(r'\b(HOLDING|HOLD)\b', re.IGNORECASE)
# "ABOVE 190-200" / "ABOVE 10" immediately after an option strike with no
# premium of its own — the number right after ABOVE/BELOW is the entry
# trigger (Stock Thunder: "Buy NIFTY _23650PE Above 190-200", "BUY BIOCON
# 400 CE ABOVE 10 TRG - ..."). NUM stops at the first non-digit, so this
# naturally ignores a trailing "-200" range without a separate branch.
RE_ABOVE_BELOW = re.compile(r'\b(?:ABOVE|BELOW)\s+' + NUM, re.IGNORECASE)
# a running price-update recap that restates an already-open option leg
# rather than posting a fresh order, e.g. "170 TO 199#NIFTY 23650PE" —
# the option match immediately follows the "#" here, not a BUY/SELL verb.
RE_PROGRESS_UPDATE = re.compile(r'\d[\d,.]*\s*TO\s*\d[\d,.]*\s*#', re.IGNORECASE)

# promotional / PR / news posts that are never a trade signal (req 1.c)
PROMO = re.compile(
    r'\b(offer\b|opens here|valid for first|slots only|join\b|'
    r'\bipo\b|price band|apply now|listing|registration|batch|coaching|course|'
    r'cues for next week|news\b|breaking|read more|details below|'
    r'book your slot|limited seats|new batch|mentorship|follow us|'
    r'share this|forwarded|webinar|subscribe)\b', re.IGNORECASE)
TRADE_VERB = re.compile(
    r'\b(BUY|SELL|LONG|SHORT|ABOVE|BELOW|BREAKOUT|CE|PE|CALL|PUT)\b', re.IGNORECASE)


def is_promo(text):
    return bool(text and PROMO.search(text) and not TRADE_VERB.search(text))


def parse_message(text, style=None):
    """Return a list of signal dicts parsed from one message (possibly [])."""
    if not text or not text.strip():
        return []
    if style == 'promo' or is_promo(text):
        return []
    out = []
    # roots already claimed by an option match, e.g. "NIFTY" from
    # "NIFTY 25700 CE" — a later cash/verb-first/buysell match on the same
    # root is a false positive (see option_roots usage below), typically the
    # option regex's own index/date tokens ("...25 25700 CE..." parsed as a
    # bare "BUY NIFTY ... 03" cash order by a looser regex).
    option_roots = set()
    # spans already claimed by an explicit "EXIT/BOOK ... SYMBOL @ PRICE"
    # close-out — an option match inside one of these spans is the same
    # close-out being mis-read as a fresh order, not a new position.
    exit_price_spans = [m.span() for m in RE_EXIT_PRICE.finditer(text)]
    exit_price_spans += [m.span() for m in RE_EXIT_PRICE_BOOK.finditer(text)]
    # spans of "<price> TO <price>#" progress recaps — an option match that
    # starts right after one of these is the same leg being restated with a
    # running LTP, not a fresh order (Stock Thunder's update posts)
    progress_spans = [m.span() for m in RE_PROGRESS_UPDATE.finditer(text)]

    def add(sig):
        ac = classify(sig['trade'], sig['direction'], text)
        if style == 'crypto' and ac in ('stock', 'other'):
            ac = 'crypto'
        sig['asset_class'] = ac
        out.append(sig)

    # 1. options: "BANKNIFTY 57000 PE @ 505", "SENSEX 73,900 PE"
    for m in RE_OPT.finditer(text):
        root, right, prem = m.group(1).strip().upper(), m.group(2).upper(), m.group(3)
        root = re.sub(r'\s+', ' ', root).replace(',', '').replace('_', ' ')
        root = re.sub(r'\s+', ' ', root).strip()
        root_word = root.split()[0] if root.split() else root
        if root_word in STOP_WORDS:
            continue
        if any(s[0] < m.end() and s[1] > m.start() for s in exit_price_spans):
            continue
        if any(abs(s[1] - m.start()) <= 1 for s in progress_spans):
            continue
        option_roots.add(root_word)
        right = {'CALL': 'CE', 'PUT': 'PE'}.get(right, right)
        entry = _f(prem) if prem else None
        sig = {'trade': f'{root} {right}',
               'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
               'entry': entry, 'target': None, 'stop_loss': None, 'status': 'Open'}
        # "ABOVE 190-200" / "ABOVE 10" entry trigger right after the strike
        # (checked before the bare dash-range fallback below, since NUM stops
        # at the first non-digit and so already handles a trailing "-200")
        if entry is None:
            ab = RE_ABOVE_BELOW.search(text[m.end():m.end() + 20])
            if ab:
                sig['entry'] = _f(ab.group(1))
        # range entry "₹250-320" when no explicit premium
        if entry is None and sig['entry'] is None:
            rng = RE_RANGE.search(text[m.end():m.end() + 20])
            if rng:
                sig['entry'] = _f(rng.group(1))
                sig['target'] = _f(rng.group(2))
        add(sig)

    # 1b. broker-style options with an expiry date in the middle:
    # "BUY NIFTY 03 JUL 25 25700 CE 1 lots at 109.00."
    for m in RE_OPT_EXPIRY.finditer(text):
        root, strike, right, prem = m.group(1).upper(), m.group(2), m.group(3).upper(), m.group(4)
        trade = f'{root} {strike} {right}'
        option_roots.add(root)
        if any(o['trade'] == trade for o in out):
            continue
        add({'trade': trade,
             'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
             'entry': _f(prem) if prem else None,
             'target': None, 'stop_loss': None, 'status': 'Open'})

    # 2. crypto futures: "ONDO LONG 20x"
    for m in RE_CRYPTO.finditer(text):
        sym, side = m.group(1), m.group(2).upper()
        if not _is_symbol(sym):
            continue
        if any(o['trade'] == sym for o in out):
            continue
        ent = RE_ENTER.search(text)
        add({'trade': sym, 'direction': 'BUY' if side == 'LONG' else 'SELL',
             'entry': _f(ent.group(1)) if ent else None,
             'target': None, 'stop_loss': None, 'status': 'Open'})

    # 3. verb-after cash: "BLUESTARCO CASH ABOVE 1570"
    for m in RE_CASH.finditer(text):
        sym, side, level = m.group(1), m.group(3).upper(), m.group(4)
        if not _is_symbol(sym) or sym in option_roots or any(o['trade'] == sym for o in out):
            continue
        add({'trade': sym, 'direction': 'BUY' if side == 'ABOVE' else 'SELL',
             'entry': _f(level), 'target': None, 'stop_loss': None, 'status': 'Open'})

    # 4. verb-first: "Buy BHARTIHEXA above 1555" — also mis-fires on a
    # broker-style option order ("BUY NIFTY 03 JUL 25 25700 CE ... at
    # 109.00"), reading the expiry day-of-month as the entry price, so any
    # root already claimed by an option match above is excluded.
    for m in RE_VERB_FIRST.finditer(text):
        side, sym, level = m.group(1).upper(), m.group(2), m.group(3)
        if not _is_symbol(sym) or sym in option_roots or any(o['trade'] == sym for o in out):
            continue
        add({'trade': sym, 'direction': side, 'entry': _f(level),
             'target': None, 'stop_loss': None, 'status': 'Open'})

    # 5. plain "PAYTM BUY 1815"
    for m in RE_BUYSELL.finditer(text):
        sym, side, level = m.group(1), m.group(2).upper(), m.group(3)
        if not level or not _is_symbol(sym) or sym in option_roots or any(o['trade'] == sym for o in out):
            continue
        add({'trade': sym, 'direction': side, 'entry': _f(level),
             'target': None, 'stop_loss': None, 'status': 'Open'})

    if not out:
        return []

    # message-level levels attach to signals that lack them
    sl = RE_SUPPORT.search(text)
    tg = RE_TARGET.search(text)
    prem = RE_PREMIUM.search(text)
    enter = RE_ENTER.search(text)
    for sig in out:
        if sig['stop_loss'] is None and sl:
            sig['stop_loss'] = _f(sl.group(1))
        if sig['target'] is None and tg:
            sig['target'] = _f(tg.group(1))
        if sig['entry'] is None and sig['asset_class'] == 'option' and prem:
            sig['entry'] = _f(prem.group(1))
        if sig['entry'] is None and sig['asset_class'] == 'crypto' and enter:
            sig['entry'] = _f(enter.group(1))
        if sig['status'] == 'Open' and RE_HOLDING.search(text):
            sig['status'] = 'Open'
    return out


# ---- profit / exit ---------------------------------------------------------
RE_PROFIT_POST = re.compile(NUM + r'\s*\+*\s*(?:K)?\s*PROFIT', re.IGNORECASE)   # "2,175+ PROFIT"
RE_PROFIT_PRE = re.compile(r'PROFIT\s*(?:₹|OF|:)?\s*₹?\s*' + NUM, re.IGNORECASE)  # "PROFIT ₹5000"
RE_PIPS = re.compile(r'[₹+]?\s*' + NUM + r'\s*(?:Pips|POINTS|Pts)', re.IGNORECASE)
# Stock Thunder's running-P&L phrasing: "GAINING RS- 4000/ 2 LOTS" (never
# uses the word "profit" itself)
RE_GAINING = re.compile(r'\bGAINING\s*RS[\s:\-]*' + NUM, re.IGNORECASE)
RE_EXIT = re.compile(
    r'\b(SAFE BOOK|BOOK HERE|BOOKED|BOOK PROFIT|TARGET HIT|EXIT|EXITED|'
    r'STOPPED OUT|SL HIT|S/L HIT|STOP HIT|FULL BOOK|PARTIAL BOOK|SOLD)\b',
    re.IGNORECASE)
# a clean close-out that gives an exit PRICE rather than a rupee profit
# figure, e.g. "EXIT RTNINDIA @ 63.3", "Exit from Banknifty 59000 ce @ 364"
RE_EXIT_PRICE = re.compile(
    r'\bEXIT(?:\s+FROM)?\s+([A-Z][A-Z0-9 ]{1,24}?)\s*@\s*' + NUM, re.IGNORECASE)
# broker-style close-out that names the symbol instead of giving a rupee
# profit total, e.g. "BOOK PROFIT IN RAYMOND @ 636.5", "BOOK PROFIT IN
# GMDCLTD @422.5" (Angel One Research)
RE_EXIT_PRICE_BOOK = re.compile(
    r'\bBOOK(?:\s+PROFIT)?\s+IN\s+([A-Z][A-Z0-9 ]{1,24}?)\s*@\s*' + NUM, re.IGNORECASE)
JUNK = re.compile(
    r'good morning|account (handling|management)|disclaimer|webinar|'
    r'subscribe|premium|youtube|whatsapp|t\.me/|https?://', re.IGNORECASE)


def parse_profit(text):
    """Running/booked profit ₹ if the message reports one, else None.

    Legacy rule: the number is the TOTAL for the position — caller must use
    max/last across messages, never sum.
    """
    if not text:
        return None
    m = (RE_PROFIT_POST.search(text) or RE_PROFIT_PRE.search(text)
         or RE_PIPS.search(text) or RE_GAINING.search(text))
    if not m:
        return None
    val = _f(m.group(1))
    if m.re.match(text[m.start():]) and 'K' in m.group(0).upper():
        val *= 1000
    return val


def parse_exit(text):
    """True when the message explicitly books/exits (SAFE BOOK, TARGET HIT, …)."""
    return bool(text and RE_EXIT.search(text))


def parse_exit_price(text):
    """(symbol, price) for a clean 'EXIT [FROM] SYMBOL @ PRICE' or
    'BOOK [PROFIT] IN SYMBOL @ PRICE' close-out, else None. Distinct from
    parse_profit(): that looks for an explicit rupee profit figure; this
    captures the raw exit price when the message gives a price instead
    (no profit wording to match on)."""
    if not text:
        return None
    m = RE_EXIT_PRICE.search(text) or RE_EXIT_PRICE_BOOK.search(text)
    if not m:
        return None
    sym = re.sub(r'\s+', ' ', m.group(1).strip().upper())
    if sym.split()[0] in STOP_WORDS:
        return None
    return sym, _f(m.group(2))
