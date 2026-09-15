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
          'MCXSILVER', 'SILVERM', 'COPPER', 'ALUMINUM', 'ZINC', 'LEAD', 'NICKEL'}
COMMODITY = {'CRUDE', 'CRUDEOIL', 'OIL', 'NATURALGAS', 'NATGAS', 'GAS', 'NG',
             'LPG', 'COAL', 'URINEA', 'MENTHA', 'COTTON', 'GUARGOM', 'JOJOB',
             'TIN', 'METHANOL'}
FOREX = {'USDINR', 'EURUSD', 'GBPUSD', 'USDJPY', 'EURINR', 'GBPINR', 'AUDINR',
         'USDCAD', 'EURGBP', 'FX', 'FOREX', 'CURRENCY'}

# day + 3-letter-month expiry token used by Nirmal Bang Official, glued
# together with no/optional space and an optional trailing "T" ("15SEP",
# "29 SEP", "29SEPT") — sits between the index/symbol and the FUT/strike,
# breaking the generic verb-first/cash regexes' assumption that the entry
# price immediately follows the symbol.
MONTH_ABBR = r'JAN|FEB|MAR|APR|MAY|JUN|JUL|AUG|SEP|OCT|NOV|DEC'
EXPIRY = r'\d{1,2}\s?(?:' + MONTH_ABBR + r')T?'

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
    # header words from Stockpro Online's "POSITIONAL/SCALPING ... TRADE"
    # ladder-shape header (see _stockpro_ladder_signal) — without these,
    # RE_CASH's lazy word-bridge can latch onto the header word itself as a
    # phantom "symbol" when a later line in the same message happens to use
    # upper-case "ABOVE" (RE_CASH is case-sensitive on purpose elsewhere),
    # e.g. "SCALPING TRADE\n\nAPOLLO Micro\nLooks Good ABOVE 405-407"
    # otherwise mis-parsing as "BUY SCALPING ABOVE 405". Common English
    # trading-prose words, not real tickers, so channel-agnostic safe (same
    # rationale as the existing SWING/POSITIONAL entries above).
    'SCALPING', 'BOTTOMED', 'INTRADAY',
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
# Nirmal Bang Official futures orders that put an expiry token ("29SEP",
# "29 SEPT") either before or after the FUT/FUTURE(S) keyword, e.g. "Sell
# AMBER  FUTURE 29SEPT below 7170" and "Buy NIFTY 29SEP Future above 23305".
# Run BEFORE RE_CASH/RE_VERB_FIRST/RE_BUYSELL and its root is added to
# option_roots — without this, the expiry token confuses those looser
# regexes into either grabbing the wrong symbol or a bogus partial-digit
# entry price parsed out of the expiry token itself (e.g. "29" from
# "29SEP").
RE_FUT = re.compile(
    r'\b(?:BUY|SELL)\s+' + SYM + r'\s+(?:(?:' + EXPIRY + r')\s+)?'
    r'(?:FUTURES?|FUT)\b\s*(?:(?:' + EXPIRY + r')\s+)?(ABOVE|BELOW)\s+' + NUM,
    re.IGNORECASE)
# Nirmal Bang Official options with a compact expiry token between the index
# and the strike, e.g. "Buy NIFTY 15SEP 23300 CE above 85" — RE_OPT's root
# pattern requires the strike immediately after the root (no room for an
# expiry token) and its leading \b fails mid-word ("15SEP"), so this shape
# is otherwise invisible to RE_OPT and gets misread by RE_VERB_FIRST instead
# (partial-digit entry from the expiry token, e.g. "15" from "15SEP").
RE_OPT_EXPIRY2 = re.compile(
    r'\b(?:BUY|SELL)\s+([A-Z]+)\s+(?:' + EXPIRY + r')\s+' + NUM +
    r'\s*(CE|PE)\b(?:\s*(?:ABOVE|BELOW|AT)\s*' + NUM + r')?',
    re.IGNORECASE)
# Ashika Calls' cash/futures/options entries carry an expiry annotation in
# parentheses between the symbol/FUT keyword (or CE/PE strike) and the CMP
# price, e.g. "BUY TCS FUT (30 DEC)CMP 3100 SL 3010 TGT 3240", "BUY NIFTY
# 22500 CE (27 MAR) CMP 250-290 SL 150 TGT 780" — RE_VERB_FIRST/RE_OPT have
# no room for the parenthetical and so silently drop the CMP price (568 of
# 603 previously-unparsed messages in this channel's full 1956-message
# history use this shape — the dominant one, found by checking coverage
# across the full corpus, not just correctness on what already matched).
# Also special-cases the ticker "LT" (Larsen & Toubro, e.g. "BUY LT CMP
# 3850-3857 SL 3740 TGT 4035"), one character short of the shared SYM
# pattern's 3-char floor — named explicitly rather than lowering that floor
# globally, which would open the door to ordinary two-letter English words
# ("BUY TO ...") becoming phantom tickers elsewhere. Both style-gated to
# 'mixed'; verified empirically that no other 'mixed' channel (Angel One
# Research, NIRMAL BANG OFFICIAL, Stockpro Online) has the "BUY/SELL <SYM>
# (...)" parenthetical shape. The "LT" special-case DOES also fire for
# Angel One Research, which trades the same real ticker in its own
# "BUY LT 1 shares at 3495.00." broker-order format — a deliberate,
# verified-correct side effect (entry/SL/TGT match the stated values) of
# gating on shared style rather than a single channel, not a regression;
# confirmed via a full old-vs-new parse diff over Angel One's history that
# this is the ONLY thing this migration's regexes change there.
SYM_ASHIKA = r'\b(LT|[A-Z][A-Z0-9&\-]{2,20})\b'
RE_VERB_FIRST_ASHIKA = re.compile(
    r'\b(BUY|SELL)\s+' + SYM_ASHIKA + r'(?:\s+(?:CASH|FUT|FUTURES))?'
    r'(?:\s*\([^)]{1,20}\))?'
    r'(?:\s+\d[\d,]*(?:\.\d+)?\s*(?:shares?|lots?|qty))?'
    r'\s*(?:ABOVE|BELOW|AT|CMP|@|>)?\s*' + NUM,
    re.IGNORECASE)
# the option-leg variant of the same parenthetical-expiry shape: the CMP
# price sits right after the "(<expiry>)" annotation that follows CE/PE.
RE_OPT_PAREN_CMP = re.compile(
    r'^\s*\([^)]{1,20}\)\s*(?:CMP\s*)?' + NUM, re.IGNORECASE)
# Ashika Calls occasionally writes the index name in lower/mixed case
# ("Nifty  25500 PE (JAN20) CMP 64 to 62  SL 35 TGT 100" instead of the
# usual "NIFTY 25500 PE") — RE_OPT's root is upper-case only by design (so
# ordinary prose never becomes a phantom ticker), so these never match at
# all. Restricted to the known index-root names, not any lower-case word,
# so it stays channel-agnostic-safe; consumed only when style == 'mixed'.
RE_OPT_INDEX_CI = re.compile(
    r'\b(NIFTY|BANKNIFTY|SENSEX|FINNIFTY)\s*_?\s*' + NUM + r'\s*(CE|PE|CALL|PUT)\b',
    re.IGNORECASE)
# MarketWolf's dominant (and, on the full 1960-message tracked history,
# only structured) signal shape — a paid-tip broker template with the real
# premium entry hidden three lines down from a misleading decoy number:
# "Trade SENSEX @11,400 only!\n\nIndex : SENSEX\n\nOPTION:\xa0 77400 CALL
# (CE) 30th APR\n\n\U0001F3F9 BUY : 540-570\n\n\U0001F3AF Target & Stop
# Loss : RA Team To Update ..." — the "@11,400" on line 1 is the
# SUBSCRIPTION price for the paid tip service, not a trade price (a naive
# "SYMBOL @ PRICE" regex would misread it as the option premium); the real
# entry is the first number of the "BUY : <low>-<high>" range three lines
# later, after an "Index"/"Commodity"/"Stock" line naming the underlying
# and an "OPTION: <strike> CALL|PUT (CE|PE) <expiry>" line giving the
# actual leg. 722 of 1960 tracked messages use this exact shape (verified
# empirically); the remainder is daily commentary ("Hunting Zones", "Post
# Market Update", Gift Nifty gap notes) and promo, correctly left
# unparsed. Style-gated to 'options' — verified empirically that neither
# other 'options'-style channel (Options Train, Stock Thunder) has this
# Index/Commodity/Stock + OPTION + BUY three-line shape anywhere in its
# history.
RE_MARKETWOLF_OPTION = re.compile(
    r'(?:Index|Commodity|Stock)\s*:\s*([A-Za-z0-9&][A-Za-z0-9 &]{0,30}?)\s*\n+'
    r'OPTION\s*:\s*' + NUM + r'\s*(CALL|PUT)\s*\((CE|PE)\)[^\n]*\n+'
    r'.{0,20}?BUY\s*:?\s*' + NUM, re.IGNORECASE)
# Short To Mid Term®™'s two dominant Hinglish cash-equity shapes (1938 of
# 1971 tracked messages previously produced zero signal — found by checking
# coverage, not just correctness on what already matched). Style-gated to
# 'cash'; verified empirically that the only other 'cash'-style channel
# (Motilal Oswal - Official) has zero occurrences of either shape.
# A. forward entry call, symbol given by the trailing hashtag (not the
#    display name before it, which can be an abbreviated/misspelled
#    variant, e.g. "NYKAA - FSN E-COMMERCE VENTURES Ltd." vs "#NAYAKA"):
#    "\U0001F195⬇️\U0001F4E2\n\n\U0001F4B9  CENTUM ELECTRONICS\n\n"
#    "\U0001F387  CMP-  1210-1212\n\n\U0001F3A0 UPSIDE RESISTANCE  - "
#    "1260-1310-1370-1450-1550\n\n#CENTUM\n\n\U0001F4A5 DISCLAIMER..." — CMP's
#    first number is the entry, the ladder's first number the target (same
#    single-value convention as RE_TARGET elsewhere in this file).
RE_STMT_ENTRY = re.compile(
    r'CMP\s*[-:]?\s*' + NUM + r'.*?'
    r'UPSIDE\s+(?:RESISTANCE|PATTERN|POSSIBLE)[.\s]*[-:]?\s*' + NUM + r'.*?'
    r'#([A-Z][A-Z0-9]{1,20})\b', re.IGNORECASE | re.DOTALL)
# B. retrospective "called it" recap that states both the entry and the
#    already-hit exit level in one line: "#IOC 94 TO 145+\U0001F680\U0001F680\U0001F680   "
#    "3RD TGT DONE ✅✅", "#CGPOWER 510-511 TO 541+ FIRST TGT DONE...".
#    KNOWN, DELIBERATE LIMITATION: despite "TGT DONE"/"REACHED" wording
#    confirming the position is already closed, this is recorded as an Open
#    trade with entry/target filled rather than Closed — parse_signals.py's
#    exit-PRICE path (unlike its profit path) evaluates before this same
#    message's signal has created the Trade row, so a same-message
#    create-and-close can never actually close here (and, once the message
#    is marked processed, never will on any later run either); fabricating
#    a "Closed"/realized status this codebase can't actually derive would
#    violate the realized-truthfulness rule far more than an Open row with
#    accurate entry/target values that simply doesn't self-close.
RE_STMT_RECAP = re.compile(
    r'#([A-Z][A-Z0-9]{1,20})\b[^\n#]{0,25}?' + NUM +
    r'(?:\s*-\s*' + NUM + r')?\s*TO\s*' + NUM, re.IGNORECASE)
# Stocky Mind's recurring "⚡️ <SYM> ... <entry> to <exit>" trade
# recap, e.g. "⚡️ CRUDEOIL\n\n9085 to 8920 | 5R+\n\nLocked the
# majority gains", "⚡️ APOLLOPIPE | Swing Trade\n\n429 to 454+ "
# "\U0001F4A5 | 6%+" (87 of 1954 tracked messages; most of the rest is
# trader-mindset prose/quotes-of-the-day with no price at all, correctly
# left unparsed). Direction is inferred from which side of the range is
# higher (down-move recap = SELL, e.g. the CRUDEOIL row above), same
# convention as the bare-crypto-prose fallback elsewhere in this file.
# Style-gated to 'mixed'; verified empirically that no other 'mixed'
# channel (Angel One Research, NIRMAL BANG OFFICIAL, Stockpro Online) has
# this "⚡ SYMBOL ... N to M" shape anywhere in its history.
RE_STOCKY_RECAP = re.compile(
    r'⚡️?\s*([A-Z][A-Z0-9&]{1,20})\b.{0,60}?' + NUM +
    r'\s*(?:to|➔|→)\s*' + NUM, re.IGNORECASE | re.DOTALL)
# Swing Trader Vishal's dominant entry phrasing — "Bought #<SYM> <PRICE>"
# with the ticker as a (often lower/mixed-case) hashtag, e.g. "Bought
# #BFUTILITIE 810", "Bought #Vascon 63.8", "Bought #tatacomm @ 1946" (70 of
# 1987 tracked messages; most of the channel is promo for the paid
# "Premium Members" channel, teaser screenshots with no stated price, and
# Hinglish market commentary, correctly left unparsed). Style-gated to
# 'cash'; verified empirically that no other 'cash'-style channel (Motilal
# Oswal - Official, Short To Mid Term®™) has this "Bought #SYM"
# hashtag shape anywhere in its history.
RE_VISHAL_BOUGHT = re.compile(
    r'\bBought\b(?:[^\n#]{0,20})?#([A-Za-z][A-Za-z0-9]{1,20})\b[^\n\d]{0,15}?' + NUM,
    re.IGNORECASE)
RE_CRYPTO = re.compile(
    # symbol and LONG/SHORT may be joined by a plain space ("STX LONG 10x")
    # or an em/en-dash ("DOGE – LONG", "LINK – SHORT" — Serezha Calls' format)
    SYM + r'\s*[-–—]?\s*(LONG|SHORT)\b\s*(\d+\s*[Xx])?')
RE_ENTER = re.compile(
    r'(?:ENTER|ENTRY|ENT)\s*(?:PRICE)?\s*[-:]?\s*' + NUM, re.IGNORECASE)
RE_PREMIUM = re.compile(r'(?:@\s*|ENTRY\s+|ENTER\s+(?:AT|IN)\s+)' + NUM, re.IGNORECASE)
RE_SUPPORT = re.compile(
    r'\b(?:SUPPORT|S/L|S/T|SL\b|STOP[\s\-]?LOSS|STOP|STCP)\s*(?:PRICE)?\s*[:\-]?\s*'
    r'(?:AT\s+|BELOW\s+|ABOVE\s+|NEAR\s+|ON\s+)?' + NUM, re.IGNORECASE)
RE_TARGET = re.compile(
    # "TRG" is Stock Thunder's abbreviation for TARGET (verified empirically
    # unique to it across all 76 channels' history) — added directly since
    # it's channel-agnostic-safe, unlike Nirmal Bang's "TG"/"ABV" below which
    # are ambiguous enough to need style-gating.
    r'\b(?:VIEW|VIEWS|TARGETS?|TGT|TRG|SHT)\s*(?:PRICES?)?\s*[:\-]?\s*'
    r'(?:AT\s+|ON\s+|NEAR\s+)?' + NUM, re.IGNORECASE)
# Nirmal Bang Official abbreviates STOP LOSS as "SL ABV <price>" (ABV =
# above) and TARGET as "TG <price>" — kept as separate style-gated patterns
# (checked only when style == 'mixed') rather than folded into RE_SUPPORT/
# RE_TARGET above, so other channels' text can never match on "ABV"/"TG".
RE_SUPPORT_MIXED = re.compile(
    r'\b(?:SUPPORT|S/L|S/T|SL\b|STOP[\s\-]?LOSS|STOP|STCP)\s*[:\-]?\s*'
    r'(?:AT\s+|BELOW\s+|ABOVE\s+|ABV\s+|NEAR\s+|ON\s+)?' + NUM, re.IGNORECASE)
RE_TARGET_MIXED = re.compile(
    r'\b(?:VIEW|VIEWS|TARGETS?|TGT|TG|SHT)\s*[:\-]?\s*'
    r'(?:AT\s+|ON\s+|NEAR\s+)?' + NUM, re.IGNORECASE)
RE_RANGE = re.compile(r'₹?\s*' + NUM + r'\s*[-–]\s*' + NUM)  # entry-target "₹250-320"
RE_HOLDING = re.compile(r'\b(HOLDING|HOLD)\b', re.IGNORECASE)
# a one-line "<option leg> \n\n <entry> TO <exit>" recap with a rupee PROFIT
# figure nearby, e.g. "BSE 3500 CE\n\n85 TO 114\n\n5,800+++++ PROFIT" (Options
# Train's end-of-day recap posts, sometimes the ONLY message for a trade).
# Case-insensitive since a couple of these recaps use mixed-case symbols
# ("Paytm 1720 CE"); harmless when broadened since it only feeds the boolean
# parse_exit() signal, gated on the literal word PROFIT following shortly
# after — verified empirically against all 76 channels' full history to
# match ONLY this channel (other channels' "<price> TO <price>" recaps use
# "POINT DONE" / "ROI ... DONE" phrasing without the word PROFIT nearby).
RE_TO_RANGE_OPT = re.compile(
    r'\b[A-Z]+\s?\d[\d,]*(?:\.\d+)?\s*(?:CE|PE|CALL|PUT)\b\s*\n+\s*' + NUM +
    r'\s*(?:TO|-)\s*' + NUM, re.IGNORECASE)

# Stockpro Online writes its levels in lower/mixed case rather than the
# ALL-CAPS "ABOVE"/"BELOW"/"BREAKOUT" the rest of the corpus uses, so the
# channel-agnostic RE_CASH (case-sensitive on purpose, to avoid matching
# ordinary prose sentences like "...that it looks good above 237" elsewhere)
# never fires for it. These two patterns use a scoped (?i:...) group so only
# the fixed keyword phrase is case-insensitive — the leading symbol token(s)
# stay ALL-CAPS-only, keeping the same false-positive protection RE_CASH has.
# 1. the standalone breakout call: "LUMINO fresh breakout above 112",
#    "APOLLO MICRO fresh breakout above 418" (only the first word becomes the
#    trade symbol, same shorthand-ticker convention as the rest of the file).
RE_FRESH_BREAKOUT = re.compile(
    r'\b([A-Z][A-Z0-9&\-]{1,20})\b(?:\s+[A-Z][A-Z0-9&\-]{1,20})*'
    r'\s+(?i:fresh\s+breakout\s+(above|below))\s+' + NUM)
# 2. the "we shared the research" recap/social-proof post that retrospectively
#    documents an earlier call's entry level, e.g. "✅MILKYMIST 🔥 - We shared
#    the research 2nd September 2026 only that it looks good above 237" or
#    "✅DHOOTTRANS 🔥 - In morning we shared the research that it looks good
#    above 1620" — the only record of that call in the tracked history, so
#    treated as a real (if late) signal rather than ignored.
RE_SHARED_RESEARCH = re.compile(
    r'\b([A-Z][A-Z0-9&\-]{1,20})\b(?:\s+[A-Z][A-Z0-9&\-]{1,20})*.*?'
    r'(?i:we\s+shared\s+the\s+research).*?'
    r'(?i:it\s+looks\s+good\s+(above|below))\s*' + NUM, re.DOTALL)
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

# Stockpro Online's DOMINANT signal shape (found on the full 2000-message
# tracked history, not just the 51-message sample the RE_FRESH_BREAKOUT/
# RE_SHARED_RESEARCH fix above was built from): 279 of 2000 messages / 275
# distinct symbol+entry+day calls, vs. ~13 caught by the shapes above. A
# multi-line "POSITIONAL/SCALPING ... TRADE|RESEARCH" header, then on its
# own line the symbol, then "Looks Good ABOVE <entry ladder>" (rarely
# "<SYMBOL> fresh breakout above <ladder>" instead — a 2-of-279 variant of
# the SAME shape, distinct from the single-line RE_FRESH_BREAKOUT case
# above because here the symbol is NOT glued onto the same clause and the
# message also carries SL/Targets), then "SL <stop>" (sometimes "SL or
# Accumulation Zone <stop>"), then "Targets <ladder>" (absolute prices in
# ~62% of rows, "<ladder> points from entry" offsets in ~38%), then "Hold
# <duration>". All lower/mixed-case like the shapes above — gated to
# style == 'mixed' so no other channel's text can ever reach this block.
# Only the FIRST rung of each ladder is kept (entry = lowest trigger,
# target = first target) to match this codebase's existing single
# entry/target convention (see RE_TARGET's NUM taking only the first
# number of a "TARGETS 640-650-660" ladder) — never averaged or guessed.
RE_LADDER_ENTRY_LG = re.compile(r'(?i:looks\s+good\s+above)\s*[:\-]?\s*' + NUM)
RE_LADDER_ENTRY_FB = re.compile(
    r'(?i:fresh\s+breakout(?:\s+in\s+[A-Za-z&.\s]+)?\s+above)\s*[:\-]?\s*' + NUM)
# "SL 600" / "SL or Accumulation Zone 73" — allow filler words between the
# keyword and the number, but stay on the same clause (no newline).
RE_LADDER_SL = re.compile(r'\bSL\b(?:[^\d\n]{0,40})' + NUM, re.IGNORECASE)
# Ladder chars seen in the corpus as rung separators: '-', '&', '+', ';'.
RE_LADDER_TARGETS = re.compile(
    r'(?i:targets?)\s*[:\-]?\s*([0-9][0-9.,&+;\-\s]*?)'
    r'(\s*(?i:points?\s*from\s*entry))?\s*(?:\n|$)')
RE_LADDER_HEADER_LINE = re.compile(
    r'^\s*(POSITIONAL|SCALPING|SWING|BOTTOMED\s+OUT|INTRADAY)\b', re.IGNORECASE)


def _stockpro_ladder_signal(text):
    """Stockpro Online's dominant ladder shape (see comment above). Returns
    one sig dict or None — never a close: status is always 'Open', matching
    this channel's confirmed behavior of (almost) never stating an explicit
    exit (see parse_exit_price's RE_STOCKPRO_CROSSED_TARGETS for the rare
    case that does)."""
    m = RE_LADDER_ENTRY_LG.search(text)
    fresh = False
    if not m:
        m = RE_LADDER_ENTRY_FB.search(text)
        fresh = True
    if not m:
        return None
    # require the full ladder structure (SL + a "target(s)" keyword
    # somewhere) so this never fires on the single-line "<SYM> fresh
    # breakout above N" case with no SL/Targets (that's RE_FRESH_BREAKOUT's
    # job) or on a restated "we shared the research" recap.
    if not (RE_LADDER_SL.search(text) and re.search(r'\btargets?\b', text, re.IGNORECASE)):
        return None
    if re.search(r'we\s+shared\s+the\s+research', text, re.IGNORECASE):
        return None

    lines = text.splitlines()
    entry_line_idx = None
    pos = 0
    for i, line in enumerate(lines):
        end = pos + len(line)
        if pos <= m.start() <= end:
            entry_line_idx = i
            break
        pos = end + 1  # +1 for the stripped '\n'
    cand = None
    if fresh:
        # symbol is inline, immediately before "fresh breakout above" on
        # the same line, e.g. "GRAPHITE Fresh breakout above 876-878" —
        # or, when the line opens with "fresh breakout" itself, embedded
        # in an "... in <SYMBOL> above" clause instead, e.g. "Fresh
        # breakout in Bectorfood above 220".
        line = lines[entry_line_idx] if entry_line_idx is not None else ''
        mm = re.match(r'^\s*(.*?)\s*(?i:fresh\s+breakout)', line)
        cand = mm.group(1).strip() if mm and mm.group(1) and mm.group(1).strip() else None
        if not cand:
            mm3 = re.search(r'(?i:fresh\s+breakout\s+in)\s+([A-Za-z&.\s]+?)\s+(?i:above)', line)
            cand = mm3.group(1).strip() if mm3 else None
    else:
        # symbol sits on the nearest non-blank line ABOVE "Looks Good
        # ABOVE", unless that line is the header itself (some variants
        # repeat/omit it).
        j = (entry_line_idx or 0) - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j >= 0:
            cand = lines[j].strip()
            if RE_LADDER_HEADER_LINE.match(cand):
                cand = None
    if not cand:
        return None
    # Unlike RE_FRESH_BREAKOUT/RE_SHARED_RESEARCH's inline "SYMBOL fresh
    # breakout above N" (where trailing words are ordinary sentence text,
    # so only the first token is trusted as the ticker), this shape's
    # symbol sits ALONE on its own dedicated line/clause, so the full
    # line IS the name — concatenating every word avoids truncating a
    # multi-word name down to a common English word that collides with
    # this channel's own macro-commentary prose (e.g. "DATA PATTERN"
    # truncated to "DATA" would collide with "Data positive/negative..."
    # daily-outlook posts and get its profit/close state corrupted by
    # parse_signals.py's substring-word profit-attribution fallback).
    # A trailing "(SHORTALIAS)" gives the channel's own short ticker
    # instead, e.g. "PN GADGIL (PNGJL)" -> "PNGJL", "SML MAHINDRA
    # (SMLMAH)" -> "SMLMAH" (verified against every such row in the full
    # tracked history).
    alias_m = re.match(r'^(?P<full>.+?)\s*\((?P<short>[A-Za-z0-9&]{2,15})\)\s*$', cand)
    if alias_m:
        sym = re.sub(r'[^A-Za-z0-9]', '', alias_m.group('short')).upper()
    else:
        # keep a single space between words for a multi-word name ("CENTURY
        # ENKA", "MANKIND PHARMA") — stripping it entirely (as a bare
        # [^A-Za-z0-9] scrub would) glues them into one unrecognizable
        # token ("CENTURYENKA") that matches no message in the corpus.
        sym = re.sub(r'[^A-Za-z0-9\s]', '', cand)
        sym = re.sub(r'\s+', ' ', sym).strip().upper()
    if not sym or not sym[0].isalpha():
        return None
    if not _is_symbol(sym):
        return None

    entry = _f(m.group(1))
    sl_m = RE_LADDER_SL.search(text)
    stop_loss = _f(sl_m.group(1)) if sl_m else None

    target = None
    tg_m = RE_LADDER_TARGETS.search(text)
    if tg_m:
        nums = re.findall(r'\d+\.?\d*', tg_m.group(1).replace(',', ''))
        if nums:
            first = float(nums[0])
            # "N points from entry" offsets must be added to entry, never
            # compared to it as if they were an absolute price (a raw
            # offset like "10" read as an absolute target would silently
            # produce a nonsensical below-entry "target").
            target = entry + first if tg_m.group(2) else first

    return {'trade': sym, 'direction': 'BUY', 'entry': entry,
            'target': target, 'stop_loss': stop_loss, 'status': 'Open'}


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
    if style == 'mixed':
        # Nirmal Bang Official-specific close-out shapes — gated so another
        # channel's text can never lose a signal to this exclusion.
        exit_price_spans += [m.span() for m in RE_EXIT_PRICE_CLOSE.finditer(text)]
        exit_price_spans += [m.span() for m in RE_CLOSE_EVENT.finditer(text)]
        exit_price_spans += [m.span() for m in RE_EXIT_PRICE_SL_TRIGGER.finditer(text)]
    # spans already claimed by RE_FUT/RE_OPT_EXPIRY2 (Nirmal Bang Official's
    # expiry-token orders) — a cash/verb-first match starting earlier in the
    # same span (e.g. an unrelated all-caps filler word like "DAYS" bridged
    # through to the real "ABOVE <price>") is a false positive, not a second
    # signal.
    claimed_spans = []
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
        # claim the root so a later cash/verb-first/buysell match doesn't
        # re-read this option order's own strike as a bare "BUY <ROOT>
        # <STRIKE>" cash order, e.g. "OPTION BUY CRUDEOIL 9650 PE 395-385
        # ..." also spuriously matching "BUY CRUDEOIL 9650" (Nirmal Bang
        # Official commodity options with no expiry date), or "BUY BIOCON
        # 400 CE ABOVE 10..." also matching a phantom "BUY BIOCON 400" cash
        # order (Stock Thunder). Unconditional/channel-agnostic: this is the
        # original exclusion both fixes above depend on.
        option_roots.add(root_word)
        right = {'CALL': 'CE', 'PUT': 'PE'}.get(right, right)
        entry = _f(prem) if prem else None
        # a stray number that is really the running-profit figure, not a
        # price, e.g. "IDEA 15 CE \n\n3500++ Profit" (Options Train one-line
        # recap with no "@" premium marker at all) — only discard when there
        # was no explicit "@"/":" price marker in the match, since genuine
        # cross-newline entries in other channels ("SEP 230000 CE\n\n9300 TO
        # 10500++") are never followed immediately by "++"/PROFIT.
        if entry is not None and '@' not in m.group(0) and ':' not in m.group(0):
            tail = text[m.end():m.end() + 15]
            if re.match(r'\s*\+{1,3}', tail) or re.match(r'\s*PROFIT', tail, re.IGNORECASE):
                entry = None
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
        # Ashika Calls' "<ROOT> <STRIKE> CE (27 MAR) CMP 250-290" shape —
        # see the comment above RE_VERB_FIRST_ASHIKA/RE_OPT_PAREN_CMP.
        # Style-gated to 'mixed' so it can't fire for another channel's
        # option leg whose text happens to have a parenthetical nearby.
        # Must run BEFORE the bare dash-range fallback below: that
        # fallback's 20-char window, applied to a message like "NIFTY
        # 25100 CE (23 SEPT) CMP 150-160 SL 120 TGT 240", gets truncated by
        # the parenthetical to "150-16" (the trailing "0" falls outside the
        # window) and would otherwise misread "16" as the target instead of
        # correctly leaving target blank here so the message-level "TGT
        # 240" fallback further down fills it.
        if style == 'mixed' and entry is None and sig['entry'] is None:
            pc = RE_OPT_PAREN_CMP.match(text[m.end():m.end() + 40])
            if pc:
                sig['entry'] = _f(pc.group(1))
        # range entry "₹250-320" when no explicit premium
        if entry is None and sig['entry'] is None:
            rng = RE_RANGE.search(text[m.end():m.end() + 20])
            if rng:
                sig['entry'] = _f(rng.group(1))
                sig['target'] = _f(rng.group(2))
        # THEBULLOPTIONS reposts the SAME option leg many times through the
        # day as a running-LTP ticker: "\U0001F4CA SENSEX 74000 PE (04 JUN)
        # \n375", "...\n380", ..., "...\nFIRST TARGET DONE", "...\nBoom 370
        # To 485 = 115+ Point big Jackpot" — only the ORIGINAL "\U0001F4C8
        # BUY ABOVE <price>" trigger message states the real entry; every
        # other repost must stay entry=None so it collapses into the same
        # Open row via the (channel, trade, entry=None) upsert key, rather
        # than being misread as a fresh entry at that leg's current LTP —
        # which would otherwise mint a new phantom Trade row on every
        # repost. Searches the full remainder of the message (not the
        # small window RE_ABOVE_BELOW's other fallback below uses) since
        # the trigger phrase can sit several lines past the parenthetical
        # expiry annotation. Style-gated to 'options'; verified empirically
        # that this doesn't change a single parsed signal for either other
        # 'options'-style channel (Options Train, Stock Thunder) or
        # MarketWolf (also 'options') — none of their option-leg messages
        # with a still-missing entry at this point also contain a later
        # ABOVE/BELOW word.
        if style == 'options' and entry is None and sig['entry'] is None:
            ab = RE_ABOVE_BELOW.search(text[m.end():])
            if ab:
                sig['entry'] = _f(ab.group(1))
        add(sig)

    # 1a. Ashika Calls' lower/mixed-case index option names (see comment
    # above RE_OPT_INDEX_CI) — style-gated to 'mixed'.
    if style == 'mixed':
        for m in RE_OPT_INDEX_CI.finditer(text):
            root = m.group(1).upper()
            strike = m.group(2).replace(',', '')
            right = {'CALL': 'CE', 'PUT': 'PE'}.get(m.group(3).upper(), m.group(3).upper())
            trade = f'{root} {strike} {right}'
            option_roots.add(root)
            if any(o['trade'] == trade for o in out):
                continue
            # same close-out-span exclusion RE_OPT's own loop applies above
            # (e.g. Nirmal Bang's "NIFTY 23600CE CLOSE @31") — without it
            # this case-insensitive variant would re-read a close-out as a
            # fresh order.
            if any(s[0] < m.end() and s[1] > m.start() for s in exit_price_spans):
                continue
            entry = None
            pc = RE_OPT_PAREN_CMP.match(text[m.end():m.end() + 40])
            if pc:
                entry = _f(pc.group(1))
            add({'trade': trade,
                 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                 'entry': entry, 'target': None, 'stop_loss': None, 'status': 'Open'})

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

    # 1c/1d only apply to Nirmal Bang Official's expiry-token shapes
    # (style == 'mixed') — the day+month token these rely on ("15SEP",
    # "29 SEP") is specific enough to this channel's format that gating
    # keeps every other channel's parsing byte-for-byte unchanged.
    if style == 'mixed':
        # 1c. futures orders with a compact expiry token, e.g. "Sell AMBER
        # FUTURE 29SEPT below 7170", "Buy NIFTY 29SEP Future above 23305".
        for m in RE_FUT.finditer(text):
            sym, side = m.group(1), m.group(2).upper()
            if not _is_symbol(sym):
                continue
            option_roots.add(sym)
            claimed_spans.append(m.span())
            if any(o['trade'] == sym for o in out):
                continue
            add({'trade': sym, 'direction': 'BUY' if side == 'ABOVE' else 'SELL',
                 'entry': _f(m.group(3)), 'target': None, 'stop_loss': None,
                 'status': 'Open'})

        # 1d. options with a compact expiry token between the root and the
        # strike, e.g. "Buy NIFTY 15SEP 23300 CE above 85".
        for m in RE_OPT_EXPIRY2.finditer(text):
            root, strike, right, prem = m.group(1).upper(), m.group(2), m.group(3).upper(), m.group(4)
            trade = f'{root} {strike.replace(",", "")} {right}'
            option_roots.add(root)
            claimed_spans.append(m.span())
            if any(o['trade'] == trade for o in out):
                continue
            add({'trade': trade,
                 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                 'entry': _f(prem) if prem else None,
                 'target': None, 'stop_loss': None, 'status': 'Open'})

    # 1e. MarketWolf's "Index/Commodity/Stock + OPTION + BUY" three-line
    # shape (see comment above RE_MARKETWOLF_OPTION) — style-gated to
    # 'options'.
    if style == 'options':
        for m in RE_MARKETWOLF_OPTION.finditer(text):
            root = re.sub(r'\s+', ' ', m.group(1).strip()).upper()
            strike = m.group(2).replace(',', '')
            right = m.group(4).upper()
            trade = f'{root} {strike} {right}'
            option_roots.add(root)
            if any(o['trade'] == trade for o in out):
                continue
            add({'trade': trade,
                 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                 'entry': _f(m.group(5)), 'target': None, 'stop_loss': None,
                 'status': 'Open'})

    # 1f. Short To Mid Term®™'s two dominant shapes (see comment above
    # RE_STMT_ENTRY/RE_STMT_RECAP) — style-gated to 'cash'.
    if style == 'cash':
        m = RE_STMT_ENTRY.search(text)
        if m:
            sym = m.group(3)
            if _is_symbol(sym) and sym not in option_roots and not any(o['trade'] == sym for o in out):
                add({'trade': sym, 'direction': 'BUY', 'entry': _f(m.group(1)),
                     'target': _f(m.group(2)), 'stop_loss': None, 'status': 'Open'})
        for m in RE_STMT_RECAP.finditer(text):
            sym = m.group(1)
            if not _is_symbol(sym) or sym in option_roots or any(o['trade'] == sym for o in out):
                continue
            add({'trade': sym, 'direction': 'BUY', 'entry': _f(m.group(2)),
                 'target': _f(m.group(4)), 'stop_loss': None, 'status': 'Open'})
        m = RE_VISHAL_BOUGHT.search(text)
        if m:
            sym = m.group(1).upper()
            if _is_symbol(sym) and sym not in option_roots and not any(o['trade'] == sym for o in out):
                add({'trade': sym, 'direction': 'BUY', 'entry': _f(m.group(2)),
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

    # 2b. bare crypto symbol named in prose with no LONG/SHORT keyword at
    # all, but fully-labeled Entry/Target/Stop-loss PRICE lines, e.g.
    # "#ETH ... Entry Price: 2455  Target Prices: 2479/2546/2605  Stop Loss
    # Price: 2379" (Serezha Calls). Gated on the known CRYPTO ticker set
    # plus ALL THREE labels being present so an ordinary prose mention of a
    # coin never turns into a phantom trade. Direction comes from comparing
    # the first target to the entry (never guessed from sentiment words).
    if not out:
        ent_m, tg_m, sl_m = RE_ENTER.search(text), RE_TARGET.search(text), RE_SUPPORT.search(text)
        if ent_m and tg_m and sl_m:
            for tok in re.findall(r'\b([A-Z][A-Z0-9]{1,10})\b', text):
                if tok in CRYPTO:
                    entry_v, target_v = _f(ent_m.group(1)), _f(tg_m.group(1))
                    add({'trade': tok,
                         'direction': 'BUY' if target_v >= entry_v else 'SELL',
                         'entry': entry_v, 'target': target_v,
                         'stop_loss': _f(sl_m.group(1)), 'status': 'Open'})
                    break

    # 3. verb-after cash: "BLUESTARCO CASH ABOVE 1570"
    for m in RE_CASH.finditer(text):
        sym, side, level = m.group(1), m.group(3).upper(), m.group(4)
        if not _is_symbol(sym) or sym in option_roots or any(o['trade'] == sym for o in out):
            continue
        # RE_CASH's lazy word-bridge can latch onto an unrelated earlier
        # all-caps filler word (e.g. "DAYS" in "1-2 DAYS ... BUY BANKNIFTY
        # FUT 29 SEPT ABOVE 56120.4") instead of the real symbol, whenever
        # that match's span reaches into text already claimed by RE_FUT/
        # RE_OPT_EXPIRY2 above — skip it rather than trust the wrong root.
        if any(s[0] < m.end() and s[1] > m.start() for s in claimed_spans):
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

    # 5b. Ashika Calls' parenthetical-expiry cash/futures shape and its
    # 2-char "LT" ticker (see comment above RE_VERB_FIRST_ASHIKA). Runs only
    # if nothing above already matched this symbol (e.g. a plain "BUY LTF
    # FUT (JULY26) CMP 286-288" already caught by RE_VERB_FIRST once the
    # paren is skipped by *this* regex, but a 3+-char symbol with no paren
    # was already caught by RE_VERB_FIRST above, so this just dedups).
    if style == 'mixed':
        for m in RE_VERB_FIRST_ASHIKA.finditer(text):
            side, sym, level = m.group(1).upper(), m.group(2), m.group(3)
            if not _is_symbol(sym) or sym in option_roots or any(o['trade'] == sym for o in out):
                continue
            add({'trade': sym, 'direction': side, 'entry': _f(level),
                 'target': None, 'stop_loss': None, 'status': 'Open'})

    # 6. Stockpro Online's lower/mixed-case level phrasing (see the comment
    # above RE_FRESH_BREAKOUT/RE_SHARED_RESEARCH): "SYMBOL fresh breakout
    # above N" and "SYMBOL ... we shared the research ... it looks good
    # above N". Only runs if nothing above matched this symbol already.
    for rx in (RE_FRESH_BREAKOUT, RE_SHARED_RESEARCH):
        for m in rx.finditer(text):
            sym, side, level = m.group(1), m.group(2).upper(), m.group(3)
            if not _is_symbol(sym) or sym in option_roots or any(o['trade'] == sym for o in out):
                continue
            add({'trade': sym, 'direction': 'BUY' if side == 'ABOVE' else 'SELL',
                 'entry': _f(level), 'target': None, 'stop_loss': None, 'status': 'Open'})

    # 6a. Stocky Mind's "⚡ SYMBOL ... N to M" recap (see comment above
    # RE_STOCKY_RECAP) — style-gated to 'mixed'.
    if style == 'mixed':
        m = RE_STOCKY_RECAP.search(text)
        if m:
            sym = m.group(1)
            if _is_symbol(sym) and sym not in option_roots and not any(o['trade'] == sym for o in out):
                entry_v, exit_v = _f(m.group(2)), _f(m.group(3))
                add({'trade': sym, 'direction': 'BUY' if exit_v >= entry_v else 'SELL',
                     'entry': entry_v, 'target': exit_v, 'stop_loss': None, 'status': 'Open'})

    # 6b. Stockpro Online's dominant "POSITIONAL/SCALPING ... Looks Good
    # ABOVE ... SL ... Targets ... Hold" ladder shape (see comment above
    # _stockpro_ladder_signal) — style-gated to 'mixed'. Skipped if a
    # symbol above already claimed this trade (e.g. the rare "fresh
    # breakout above" ladder variant, already caught by RE_FRESH_BREAKOUT).
    if style == 'mixed':
        lsig = _stockpro_ladder_signal(text)
        if lsig and lsig['trade'] not in option_roots and not any(
                o['trade'] == lsig['trade'] for o in out):
            add(lsig)

    if not out:
        return []

    # message-level levels attach to signals that lack them
    sl = RE_SUPPORT.search(text)
    tg = RE_TARGET.search(text)
    if style == 'mixed':
        sl = sl or RE_SUPPORT_MIXED.search(text)
        tg = tg or RE_TARGET_MIXED.search(text)
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

    # a crypto match that still has no entry price after all fill attempts
    # is a follow-up post repeating the "SYMBOL LONG 10x" header from an
    # earlier message (e.g. "STX LONG 10x\n1 TP" / "JUP LONG 10x\n...
    # stopped out"), not a fresh order — emitting it would upsert as a
    # phantom duplicate Open trade (channel, trade, entry=None) alongside
    # the real one. Drop it; conservative "no confident match -> no trade".
    out = [s for s in out if not (s['asset_class'] == 'crypto' and s['entry'] is None)]
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
# Nirmal Bang Official's plain close-out for an option leg, e.g. "NIFTY
# 23600CE CLOSE @31" — without this, RE_OPT (asset-class step 1) reads the
# option root/strike as a fresh order and the message-level RE_PREMIUM
# fallback ("@ <price>") mis-fills its entry from the close price.
RE_EXIT_PRICE_CLOSE = re.compile(
    r'\b([A-Z]+)\s?(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)\s*CLOSE\s*@\s*' + NUM,
    re.IGNORECASE)
# Nirmal Bang Official's stop-loss-hit close-out, e.g. "VEDL 280CE SL
# TRIGGER @3", "HINDALCO SL Triggered @1005", "AMBER FUTURE SL TRIGGER
# @7230" — confirmed empirically unique to this channel across the full
# tracked history of all 76 channels (no other channel phrases a stop-loss
# exit this way), so left ungated/global like the sibling RE_EXIT_PRICE*
# patterns above.
RE_EXIT_PRICE_SL_TRIGGER = re.compile(
    r'\b([A-Z][A-Z0-9 \xa0]{1,24}?)\s+(?i:SL\s+TRIGGER(?:ED)?)\s*@\s*' + NUM)
# Stockpro Online's "<SYMBOL> crossed all targets, currently at <PRICE>"
# close-out — one of only a handful of explicit close-outs this channel
# ever posts (confirmed on the full tracked history: "crossed all targets"
# appears a few times, but almost always with NO price, e.g. "IFCI crossed
# all Targets" / "GRAPHITE crossed all Targets" — those are deliberately
# left unhandled here rather than fabricating an exit price; only this
# "currently at <price>" variant gives a real number to close at). Symbol
# must be an ALL-CAPS token (this codebase's ticker convention) immediately
# before the phrase, same false-positive protection as the patterns above.
RE_STOCKPRO_CROSSED_TARGETS = re.compile(
    r'\b([A-Z][A-Z0-9&\-]{1,20})\b[^.\n]{0,40}?crossed\s+all\s+targets?'
    r'[^.\n]{0,40}?currently\s+at\s*' + NUM, re.IGNORECASE)
# Nirmal Bang Official's "Book Partial Profit(s) in <SYM> at <PRICE>" /
# "Target Achieved in <SYM> at <PRICE>" close-out phrasing — gives a raw
# exit price (sometimes a small range, e.g. "387.7-389"; the first/lower
# number is used as the representative exit price) rather than a rupee
# profit figure or the "EXIT SYM @ PRICE" shape RE_EXIT_PRICE expects.
# "CMP" is an equally-common price marker for the same shape — Ashika
# Calls' dominant close-out phrasing (564 of its tracked messages, e.g.
# "BOOK PARTIAL PROFIT IN ESCORTS  CMP 3623", "BOOK PROFIT IN LT CMP
# 3907"), also seen a handful of times in Samco ("BOOK PROFIT IN
# DATAPATTNS CMP 1785", "BOOK PROFIT IN APLAPOLLO25DEC1800CE CMP 23") —
# left ungated (this function has no `style` parameter to gate on, and a
# full-corpus grep across all 82 channels turns up the shape only in these
# two, both a genuine close in every occurrence, never a false positive).
RE_CLOSE_EVENT = re.compile(
    r'\b(?:BOOK\s+(?:PARTIAL\s+)?PROFITS?|TARGET\s+ACHIEVED)\s+IN\s+'
    r'([A-Z][A-Z0-9 \xa0]{1,30}?)\s*(?:AT\b|@|CMP)\s*' + NUM, re.IGNORECASE)
_EXPIRY_TOKEN = re.compile(r'\b' + EXPIRY + r'\b', re.IGNORECASE)


def _normalize_close_symbol(raw):
    """Normalize a raw 'in <SYM...>' phrase from a Nirmal Bang Official
    Book-Partial-Profit(s)/Target-Achieved close message into the canonical
    trade string parse_message() would have used at entry time — stripping
    an expiry token ("15SEP") and any trailing FUT/FUTURE(S) suffix."""
    raw = re.sub(r'\s+', ' ', (raw or '').strip().upper())
    raw = _EXPIRY_TOKEN.sub('', raw)
    raw = re.sub(r'\s+', ' ', raw).strip()
    m = re.match(r'^([A-Z][A-Z0-9&\-]*)\s+(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)$', raw)
    if m:
        return f'{m.group(1)} {m.group(2).replace(",", "")} {m.group(3)}'
    m = re.match(r'^([A-Z][A-Z0-9&\-]*)\s+(?:FUTURES?|FUT)$', raw)
    if m:
        return m.group(1)
    tok = raw.split()[0] if raw.split() else None
    return tok if tok and tok not in STOP_WORDS else None


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
    # "BOOK PROFIT 237400-BUY SILVERM 235700-400 SL BELOW 233400 TG 238000"
    # (Nirmal Bang Official) restates the original order right after the
    # number — that number is a commodity price level, not a rupee profit
    # total, so treat it as no confident profit figure rather than booking
    # a wildly wrong "profit".
    if re.match(r'\s*-\s*(?:BUY|SELL)\b', text[m.end():], re.IGNORECASE):
        return None
    val = _f(m.group(1))
    if m.re.match(text[m.start():]) and 'K' in m.group(0).upper():
        val *= 1000
    return val


def parse_exit(text):
    """True when the message explicitly books/exits (SAFE BOOK, TARGET HIT, …)."""
    if not text:
        return False
    if RE_EXIT.search(text):
        return True
    # "<option leg>\n\n<entry> TO <exit>" recap with a rupee PROFIT figure
    # shortly after — see RE_TO_RANGE_OPT.
    m = RE_TO_RANGE_OPT.search(text)
    if m and re.search(r'PROFIT', text[m.end():m.end() + 80], re.IGNORECASE):
        return True
    return False


def parse_exit_price(text):
    """(symbol, price) for a clean 'EXIT [FROM] SYMBOL @ PRICE', 'BOOK
    [PROFIT] IN SYMBOL @ PRICE', 'SYMBOL CLOSE @ PRICE', or Nirmal Bang
    Official's 'Book Partial Profit(s)/Target Achieved in SYMBOL at PRICE'
    close-out, else None. Distinct from parse_profit(): that looks for an
    explicit rupee profit figure; this captures the raw exit price when the
    message gives a price instead (no profit wording to match on)."""
    if not text:
        return None
    m = RE_EXIT_PRICE.search(text) or RE_EXIT_PRICE_BOOK.search(text)
    if m:
        sym = re.sub(r'\s+', ' ', m.group(1).strip().upper())
        if sym.split()[0] in STOP_WORDS:
            return None
        return sym, _f(m.group(2))
    m = RE_EXIT_PRICE_CLOSE.search(text)
    if m:
        root, strike, right = m.group(1).upper(), m.group(2).replace(',', ''), m.group(3).upper()
        return f'{root} {strike} {right}', _f(m.group(4))
    m = RE_CLOSE_EVENT.search(text)
    if m:
        sym = _normalize_close_symbol(m.group(1))
        if sym:
            return sym, _f(m.group(2))
    m = RE_EXIT_PRICE_SL_TRIGGER.search(text)
    if m:
        sym = _normalize_close_symbol(m.group(1))
        if sym:
            return sym, _f(m.group(2))
    m = RE_STOCKPRO_CROSSED_TARGETS.search(text)
    if m:
        sym = m.group(1).upper()
        if sym not in STOP_WORDS:
            return sym, _f(m.group(2))
    return None
