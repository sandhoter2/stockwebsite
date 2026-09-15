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
    # generic trading-jargon words that occasionally sit where a symbol
    # normally would ("OPTION SELLING ALSO\n\n24100CE...", "FUT\n\nPAGEIND
    # ONLY ABOVE 43500...") and get mis-read by RE_CASH/RE_VERB_FIRST/
    # RE_BUYSELL as a phantom ticker -- confirmed empirically to never be a
    # real symbol across all 82 channels' history (channels 49, 54, 70 each
    # had a bogus "FUT"/"OPTION" Trade row from a prior parse before this
    # fix). Same rationale as the SCALPING/BOTTOMED/INTRADAY entries above.
    'FUT', 'OPTION',
    # "INVALID BELOW <price> WITH ON CLOSING BASED" -- MARKET MASTER HUB's
    # recurring setup-invalidation sign-off, phrased as its own "<word>
    # BELOW <price>" clause right after the real TGT line -- RE_CASH reads
    # "INVALID" as if it were a second, phantom ticker ("MENON PISTON CMP
    # 74 ... TGT 94-108-135 ... INVALID BELOW 65 WITH ON CLOSING BASED").
    # Common English trading-jargon word, not a ticker -- same rationale as
    # SCALPING/BOTTOMED/INTRADAY/FUT/OPTION above.
    'INVALID',
    # "If it rises from 200 to 300 then 20/30 points normal correction" --
    # The Trading Marvel's ordinary conditional prose, matched by
    # _darshan_recap_signal's bare "<words> from N to M" shape as if "If"
    # were a ticker (that function's own symbol check is _is_symbol, i.e.
    # STOP_WORDS, not the separate STOCKGAINERS_DENY list). Common English
    # word, not a ticker.
    'IF',
    # "KEEP ON RADAR ABOVE <price>" -- Nivisha Verma (Bnf_unicorn)'s recurring
    # sign-off phrase after a call's bullet list -- RE_CASH's lazy word-bridge
    # otherwise reads "KEEP" as the symbol when the real symbol/level sits on
    # an earlier line with no ABOVE/BELOW of its own (e.g. "REC\n556+++\n\n
    # KEEP ON RADAR ABOVE 570+"). Common English phrase words, not tickers.
    'KEEP', 'RADAR',
    # Platinum Research's technical-analysis jargon/watchlist vocabulary
    # (CMP, HIGH, CLOSING, BREAKOUT, POINTS, WATCH, WATCHLIST, ROCKET,
    # READY, TIMEFRAME, TF, RSI, SUSTAIN, LIST, NUMBERS, STRANGLE, EMA,
    # SAY) sits immediately before a number or a "<strike> CE/PE" the same
    # way a real symbol would in this channel's dense, ALL-CAPS-heavy
    # prose ("...bullish RSI\n1360 CE keeping in watchlist" -- the real
    # symbol, #BDL, is a full sentence earlier), producing a phantom
    # option/cash Trade under the jargon word itself instead of no trade
    # at all (23 of the channel's 44 pre-fix trades were exactly this).
    # Checked each word individually against every channel's ALREADY-
    # parsed Trade rows before adding: none is a real ticker's full name
    # anywhere in the 82-channel tracked history (a real ticker that
    # merely STARTS with one of these as a substring, e.g. "EMAMILTD"/
    # "EMAMI"/"CMPDI", is a different exact token and is unaffected, since
    # this check is always on the full root word, never a prefix).
    'CMP', 'HIGH', 'CLOSING', 'BREAKOUT', 'POINTS', 'WATCH', 'WATCHLIST',
    'ROCKET', 'READY', 'TIMEFRAME', 'TF', 'RSI', 'SUSTAIN', 'LIST',
    'NUMBERS', 'STRANGLE', 'EMA', 'SAY',
    # LIVELONG HARI writes the ticker on its own line, then the entry band
    # on the next line as "BUY <ABV|RANGE> <price>[-<price>]" -- "ABV"
    # (shorthand for ABOVE) and "RANGE" are the trigger word right where a
    # real symbol would sit, so RE_VERB_FIRST/RE_CASH otherwise mis-read
    # them as a phantom ticker ("ABV 1590.0", "RANGE 2200.0") instead of
    # leaving the real ticker on the prior line to be picked up by
    # _hari_prev_line_signal below. Checked empirically: neither word is a
    # real ticker anywhere in the 82-channel tracked history.
    'ABV', 'RANGE',
    # Stockbox Trading's Open-Interest data table, e.g. "23,500 PE -- 1.14
    # Cr OI\n24,000 CE -- 1.20 Cr OI": the strike+CE/PE on each line is
    # informational OI reporting, not a trade order, but RE_OPT's root
    # bridges the newline back to the trailing "OI" from the PREVIOUS
    # line's "Cr OI" (the last uppercase word before the following line's
    # digit) and reads it as if it were the next line's ticker. No real
    # ticker is literally "OI" anywhere in the 82-channel tracked history.
    'OI',
    # Usha's Analysis's other live cash-equity/futures entry keyword:
    # "<TICKER>[ <MONTH> FUTURES]\n\n[BUY ]AROUND <price>\n\nTARGET ...".
    # "AROUND" sat right where a symbol would via the generic RE_VERB_FIRST
    # ("BUY <SYM> ... <NUM>" with SYM="AROUND"), so it needed the same
    # STOP_WORDS exclusion as ABV/RANGE above -- the real ticker is
    # recovered from the preceding line by _usha_around_entry_signal.
    'AROUND',
    # Usha's Analysis's subscription-combo-pack promo spam ("SPECIAL
    # OFFER'S FOR ... \n\nBUY 1 MONTH GET 2 FREE\n\nBUY 3 MONTHS GET 4
    # FREE") uses the word "BUY" as an ordinary subscription verb, which
    # defeats is_promo()'s TRADE_VERB override (a genuine "BUY" elsewhere
    # in the same message means the promo skip never kicks in) -- the
    # generic RE_VERB_FIRST/RE_BUYSELL fallbacks then misread "FREE"/
    # "EQUITY" (from "SHORT TERM EQUITY" a few words later in the same
    # promo) as phantom bare tickers. Neither is a real ticker anywhere in
    # the 82-channel tracked history.
    'FREE', 'EQUITY',
}


def _f(s):
    """Parse a possibly comma-grouped number to float.

    A comma is only ever a genuine Indian/Western thousands separator when
    the groups it splits into have a valid grouping SHAPE -- the leading
    group shorter than each later group, e.g. "23,650" (2+3 digits),
    "9,000" (1+3), "1,23,456" Indian-style (1+2+3). When a channel instead
    glues a multi-target/multi-level list together with no space after the
    comma -- "TARGET 165,190+" (LIVELONG HARI), "TGT 1600,1610++" -- every
    group has the SAME length as its neighbour, because each one is a
    complete, independent number rather than a fragment of one grouped
    total. In that case take only the FIRST group, per this file's existing
    "first/lower value is the representative one" convention (see the
    RE_CLOSE_EVENT / RE_STOCKPRO_CROSSED_TARGETS comments) -- rather than
    silently concatenating unrelated digits into one nonsense figure
    (e.g. "165,190" -> 165190.0, a phantom 6-figure target on a sub-200
    option premium). Verified empirically against the full 82-channel
    tracked corpus: no genuine grouped price anywhere has a final group the
    same length as its leading group (a valid group's tail is always
    exactly 3 digits and longer than what's in front of it), so this never
    changes a correct parse -- only the glued-list case, which was always
    wrong before.
    """
    s = str(s)
    if ',' in s:
        parts = s.split(',')
        if len(parts[0]) >= 2 and all(len(p) == len(parts[0]) for p in parts[1:]):
            return float(parts[0])
        s = s.replace(',', '')
    return float(s)


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
# Usha's Analysis's dominant option-leg header: underlying and expiry MONTH
# are two separate space-separated words before the strike, e.g.
# "BHARATFORG JUNE 1900 CE", "ZENTEC JULY 2700 CE" -- see the comment above
# the month-name skip in the RE_OPT loop for why RE_OPT itself can't read
# this (it starts matching at the month word, dropping the real ticker).
# Runs BEFORE RE_OPT below and claims its span so RE_OPT's own (excluded)
# attempt at the same text never fires a second, wrong match. Style-gated
# to 'mixed'.
RE_TICKER_MONTH_OPT = re.compile(
    r'\b([A-Z][A-Z0-9&\-]{1,20})\s+(?:JAN(?:UARY)?|FEB(?:RUARY)?|MAR(?:CH)?|'
    r'APR(?:IL)?|MAY|JUNE?|JULY?|AUG(?:UST)?|SEP(?:TEMBER)?|OCT(?:OBER)?|'
    r'NOV(?:EMBER)?|DEC(?:EMBER)?)\s+(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)\b',
    re.IGNORECASE)
# STOCK MARKET SCHOOL's dominant option-leg header: index name, then a
# "<DAY> <MON>" expiry date (no year), then the strike, e.g. "Buy Sensex 10
# Sep 74700 CE", "Buy Nifty 23 Jul 24150 CE" -- RE_OPT's own `[A-Z]+`
# root-matcher can't bridge "Sensex " (space) into "10" (its own root+
# strike shape requires letters directly followed by digits with only
# whitespace/underscore between, and here a title-case day+month sits in
# between instead), so this channel matched almost nothing before (7 of
# 1530 tracked messages). Scoped to the same small enumerated index-root
# set as RE_NASDAQMASTERS_FX's instrument list rather than a bare
# `[A-Z]+`, specifically so the case-insensitive month/CE-PE matching this
# needs (the source title-cases "Sensex"/"Sep") can't also swallow an
# unrelated capitalized-word-plus-date-plus-number sentence elsewhere.
RE_SMS_OPT_DATE = re.compile(
    r'\b(SENSEX|NIFTY|BANKNIFTY|FINNIFTY)\s+\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|'
    r'Jun|Jul|Aug|Sep|Oct|Nov|Dec)\w*\s+(\d[\d,]*(?:\.\d+)?)\s*(CE|PE|CALL|PUT)\b',
    re.IGNORECASE)
# the entry trigger for the shape above: "Only In Range @ 180 - 200 Target
# 225 240 280 310 350 & Above" -- the FIRST (nearer) number is kept as the
# entry, same "never average a ladder" convention as elsewhere in this
# file; "Target ..." is left for the existing message-level RE_TARGET
# fallback, which already reads a bare "Target <price>" generically.
# Requiring this phrase is also what keeps this channel-agnostic-safe: the
# channel's own repeated intraday LTP reposts of the SAME leg ("Dipped @
# 180 se 273", "Breakdown@ 4325 To 4308") never restate "Range", so they
# correctly produce no signal at all here instead of a second, blank-
# valued phantom Trade row for every repost (checked empirically: of the
# 931 corpus-wide matches for the header regex above, only this channel's
# own "Range @" messages ever pair with it -- the recap-only shapes at 10
# other channels that also happen to use a "<DAY> <MON>" header (e.g. "355
# To 745+", "CMP 22 Hero Zero") never contain the word "Range" either, so
# this stays a no-op there).
RE_SMS_RANGE_ENTRY = re.compile(r'\bRange\b\s*@?\s*' + NUM, re.IGNORECASE)
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
# 20PAISA..COM's dominant option-tip shape: the entry premium AND the level
# it already ran to sit on the very next non-blank line after the strike,
# joined by the WORD "To" (occasionally "@ <entry> To <exit>" in its "Done
# Of The Day" recap restating several legs from one message), e.g. "Nifty
# 22500CE\n\n\n\n\n175 To 260++", "✅Nifty 22600CE @ 177 To 193". Anchored
# immediately after the CE/PE match (like RE_OPT_PAREN_CMP above) so it
# only ever reads the number pair that belongs to THIS leg, not a later
# leg's numbers in the same recap message — filling entry/target here,
# before the message-level RE_PREMIUM fallback runs, is what keeps a
# multi-leg "Done Of The Day" recap from having every leg collapse onto
# the FIRST leg's price (that shared fallback does a single text-wide
# `.search()`, not one per leg). Consumed only when style == 'mixed'.
# Deliberately does NOT accept a bare "-" as the connector (only the word
# "to"/"To"/"TO"): checking other 'mixed' channels' full history found a
# few messages where a dash immediately after the strike is an ENTRY
# range, not an entry-target pair (Stock Gainers' "nifty 24050 ce 170-180
# support 120 view 230" — "170-180" is the entry band, the real target is
# the later "view 230"; Nivisha Verma's "Bank Nifty 49000CE 710-715 SL -
# 670" is the same shape). Accepting "-" here would have silently
# overridden that channel's own already-correct RE_RANGE/RE_TARGET_MIXED
# handling of the identical text. Channel 1 itself never uses a bare dash
# for this shape (723 "To"-word occurrences, 0 dash-only, across its full
# tracked history) so restricting to the word costs it nothing.
RE_OPT_ENTRY_TO_TARGET = re.compile(
    r'^[\s@]{0,15}' + NUM + r'\s*(?:to|To|TO)\s*' + NUM, re.IGNORECASE)
# 20PAISA..COM's "Done Of The Day" recap also restates a leg that never got
# a signal at all that day, with NO price of any kind -- "✅BNF 55900CE @ SL
# Taken", "✅Nifty 24000PE @ 20 Point SL" -- instead of an "<entry> To
# <exit>" pair. Without this guard, that leg falls through this file's
# generic per-signal entry with entry=None, and the SHARED message-level
# "sig['entry'] is None -> fill from RE_PREMIUM.search(text)" fallback near
# the end of parse_message() (a single text-wide `.search()`, not one per
# leg) then wrongly stamps it with the FIRST "@ <price>" found anywhere in
# the same multi-leg message -- an unrelated leg's entry, not this one's
# (this channel's own recap lists 3-8 legs per message). Emitting nothing
# for this leg is correct: the channel itself never stated a price for it.
# Checked channel-agnostic-safe: verified empirically this exact "@ SL
# Taken|SL Hitt|<N> Point SL" adjacency right after a CE/PE match is 0
# occurrences across every other channel's full tracked history (54
# occurrences, all channel 1) -- so left unconditional/ungated rather than
# style-gated, same convention as the STOP_WORDS entries above.
RE_OPT_NO_PRICE_CLOSE = re.compile(
    r'^\s*@?\s*(?:SL\s+Taken|SL\s+Hitt?|\d+\s*Point\s*SL)\b', re.IGNORECASE)
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
# NUM followed by a "%" is a percentage, not an absolute price ("SL 1%",
# "Target 4-6%" -- Mystocks.in's dominant SL/target phrasing) -- a
# negative lookahead keeps it out of these four SL/target regexes
# specifically (channel-agnostic-safe: a real SL/target price is never
# immediately followed by a percent sign; verified empirically this
# excludes 73 stray matches across the full 82-channel history, 45 of
# them in Mystocks.in alone, and creates none).
NUM_NOT_PCT = NUM + r'(?!\s*%|\s*-\s*\d[\d,.]*\s*%)'
RE_SUPPORT = re.compile(
    r'\b(?:SUPPORT|S/L|S/T|SL\b|STOP[\s\-]?LOSS|STOP|STCP)\s*(?:PRICE)?\s*[:\-]?\s*'
    r'(?:AT\s+|BELOW\s+|ABOVE\s+|NEAR\s+|ON\s+)?' + NUM_NOT_PCT, re.IGNORECASE)
RE_TARGET = re.compile(
    # "TRG" is Stock Thunder's abbreviation for TARGET (verified empirically
    # unique to it across all 76 channels' history) — added directly since
    # it's channel-agnostic-safe, unlike Nirmal Bang's "TG"/"ABV" below which
    # are ambiguous enough to need style-gating.
    #
    # CHANNEL-AGNOSTIC BUG FOUND while adding Systematix Group Official's
    # dedicated parser: a ranked multi-target list like "TGT 1)3575
    # 2)3470" (270 occurrences in that channel's tracked history) was
    # being read as target=1 -- NUM_NOT_PCT starts matching right where
    # this pattern's `[:\-]?\s*` leaves off, which is the "1" immediately
    # before the ")", and NUM has no way to skip past a bare digit that
    # isn't followed by more digits or a decimal point. The optional
    # `(?:\d\)\s*)?` below skips exactly that "<rank>)" prefix before
    # falling through to the real number. Verified empirically this
    # exact "TGT/TARGET/... <digit>)" adjacency is 0 occurrences in every
    # other channel's history except one harmless case (Trading Ideas By
    # Darshan's astrology-commentary "Pro Astro View :\n1) 26 Feb :
    # Mercury Turns Retrograde..." -- a numbered list under the word
    # "View", not a trade target; that message has no trade signal for
    # this fallback to attach a target to either way, so the change is a
    # no-op there).
    r'\b(?:VIEW|VIEWS|TARGETS?|TGT|TRG|SHT)\s*(?:PRICES?)?\s*[:\-]?\s*'
    r'(?:AT\s+|ON\s+|NEAR\s+)?(?:\d\)\s*)?' + NUM_NOT_PCT, re.IGNORECASE)
# Nirmal Bang Official abbreviates STOP LOSS as "SL ABV <price>" (ABV =
# above) and TARGET as "TG <price>" — kept as separate style-gated patterns
# (checked only when style == 'mixed') rather than folded into RE_SUPPORT/
# RE_TARGET above, so other channels' text can never match on "ABV"/"TG".
RE_SUPPORT_MIXED = re.compile(
    r'\b(?:SUPPORT|S/L|S/T|SL\b|STOP[\s\-]?LOSS|STOP|STCP)\s*[:\-]?\s*'
    r'(?:AT\s+|BELOW\s+|ABOVE\s+|ABV\s+|NEAR\s+|ON\s+)?' + NUM_NOT_PCT, re.IGNORECASE)
RE_TARGET_MIXED = re.compile(
    r'\b(?:VIEW|VIEWS|TARGETS?|TGT|TG|SHT)\s*[:\-]?\s*'
    r'(?:AT\s+|ON\s+|NEAR\s+)?(?:\d\)\s*)?' + NUM_NOT_PCT, re.IGNORECASE)
RE_RANGE = re.compile(r'₹?\s*' + NUM + r'\s*[-–]\s*' + NUM)  # entry-target "₹250-320"
# Bharath's Market Research / STOCK MARKET SCHOOL's "BUY RANGE - <hi>/<lo>"
# ladder entry -- see the comment above its use in the RE_OPT loop. Distinct
# from RE_RANGE above because the two numbers are "/"-separated here, not
# "-"-separated, and the "BUY RANGE" keyword itself (not just proximity to
# the strike) is what anchors this so it can't misfire on an unrelated
# nearby dash/slash pair.
RE_OPT_BUY_RANGE = re.compile(
    r'BUY\s+RANGE\s*[-:]?\s*' + NUM + r'(?:\s*[/\-]\s*' + NUM + r')?', re.IGNORECASE)
# a bare "<price> to <price>" restatement right after an option strike with
# no SL anywhere in the message -- see the comment above its use in the
# RE_OPT loop.
RE_OPT_RECAP_NO_ENTRY = re.compile(
    r'^\s*' + NUM + r'\s*(?:to|TO|To)\s*' + NUM, re.MULTILINE)
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
# optional colon between the keyword and the price ("BUY ABOVE : 1070",
# Sairam Stocks) as well as the plain "ABOVE 1070" shape other channels use.
# Sairam Stocks also has a second variant with a filler "ONLY" wedged in
# between ("BUY ABOVE ONLY 1060 LEVEL") -- skipped the same way. Also
# tolerates a colon-DASH ("ABOVE :- 142", Stock Gainers/ROCHIT SINGH
# STOCKS/channel 15/channel 55's shared house style) -- the dash is
# decorative list-item punctuation, not a minus sign (NUM itself never
# matches a leading "-", so this can't accidentally swallow a negative
# number). Verified empirically across the full 82-channel corpus: the
# colon-dash spelling occurs in exactly those 4 channels, always
# immediately before a plain positive price. Also tolerates a ">" after
# the keyword ("BUY ABOVE >500", ROCHIT SINGH STOCKS/channel 40's own
# decorative-arrow spelling) -- verified empirically unique to channel 40
# across the full 82-channel corpus (2 occurrences), always immediately
# before a plain positive price, same as the dash case above.
RE_ABOVE_BELOW = re.compile(
    r'\b(?:ABOVE|BELOW)\s*:?\s*[->]?\s*(?:ONLY\s+)?' + NUM, re.IGNORECASE)
# "NEAR <price>" entry trigger -- see the narrowly-windowed use site in the
# RE_OPT loop below for why this is a separate regex from RE_ABOVE_BELOW.
# Optional "LEVEL" plus a "--" separator tolerates Stock Gainers' (48) own
# spelling, "NEAR LEVEL -- 190" -- verified empirically unique to that
# channel (22 occurrences; 1 stray unrelated hit at channel 67, harmless
# since it's still a genuine "near <price>" trigger there too).
RE_NEAR_ENTRY = re.compile(r'\bNEAR\s*(?:LEVEL)?\s*:?\s*-{0,2}\s*' + NUM, re.IGNORECASE)
# a running price-update recap that restates an already-open option leg
# rather than posting a fresh order, e.g. "170 TO 199#NIFTY 23650PE" —
# the option match immediately follows the "#" here, not a BUY/SELL verb.
RE_PROGRESS_UPDATE = re.compile(r'\d[\d,.]*\s*TO\s*\d[\d,.]*\s*#', re.IGNORECASE)
# CHANNEL-AGNOSTIC BUG: a message consisting of NOTHING but "<root>
# <strike> CE/PE" followed by a single bare number on the next line is a
# live LTP-tracking repost of an ALREADY-open call, not a new signal --
# Trading With Ca Abhay (channel 66, "NIFTY 24200 PE\n154") and Stock
# Gainers (channel 48, "CRUDEOIL 9700 CE\n272") both post the real entry
# once with an explicit BUY/NEAR/ABOVE/CMP keyword, then repeat the bare
# symbol+current-price for 5-15 follow-up messages while the call is
# live. Because entry price ticks up/down on every repost, RE_OPT's own
# optional trailing NUM (needed elsewhere for genuine one-shot
# "<SYMBOL>\n\n<price>" entries, e.g. Options Train's "SEP 230000
# CE\n\n9300 TO 10500++") read each repost as a DISTINCT new trade under
# (channel, trade, entry) dedup, producing 10+ phantom duplicate Open
# rows per real call. Originally verified safe for channels 66 (124
# occurrences) and 48 (60), where the bare number has no trailing text.
# ROCHIT SINGH STOCKS (channel 40) uses the identical shape but decorates
# the repost price with trailing emoji, e.g. "NIFTY 24500 CE\n160🎯🎯💸💸"
# (150 occurrences) -- the original \s*\Z after the number missed these
# entirely, so they fell through to RE_OPT's own fallback and produced
# the same phantom-duplicate-Open-row bug this regex exists to prevent.
# Widened to allow up to 15 chars of trailing non-digit junk (mirroring
# RE_OPT_BARE_PRICE_REPOST_REV's own tolerance below), re-verified
# empirically safe across the full 82-channel corpus with the wider
# match: it also newly catches channels 6, 15, 17, 23, 32, 39 (1-8
# occurrences each) -- all of which are the same emoji/word-decorated
# "<symbol>\n<price>+junk" LTP/profit-celebration repost shape (e.g.
# channel 6's "SHREECEM 26000 CALL\n450+✨✨good profit", channel 17's
# "SIEMENS 3900 CE\n197.45 HIGH😍😍"), spot-checked against source text.
# A full unscoped clear+reparse shows this correctly drops a handful of
# pre-existing phantom duplicate rows in those already-specialized
# channels too (6: 488->486, 17: 188->180, 39: 268->267), with the full
# 163-test suite still green -- these were the same bug, simply never in
# the two channels the original fix sampled, not a new regression.
# Checked as a fullmatch on the STRIPPED WHOLE message, not a span
# exclusion, so it can never suppress a real entry that happens to share
# a strike with some other channel's genuine minimal-shape order
# elsewhere in the text.
# The rupee glyph occasionally prefixes the repost price too, e.g.
# ROCHIT SINGH STOCKS' "NIFTY 24100 CE\n₹ 150 \U0001F525\U0001F525✅" (3
# occurrences, verified unique to channel 40 across the full corpus with
# this exact widening) -- tolerated as an optional leading currency glyph
# so it doesn't leak through as yet another phantom entry-less duplicate.
RE_OPT_BARE_PRICE_REPOST = re.compile(
    r'\A[A-Za-z][A-Za-z ]*\d[\d,]*(?:\.\d+)?\s*(?:CE|PE|CALL|PUT)\s*'
    r'\n+\s*[₹]?\s*\d[\d,]*(?:\.\d+)?[^\d\n]{0,15}\Z', re.IGNORECASE)
# Stock Gainers' (channel 48) mirror-image variant of the same repost: the
# bare LTP comes FIRST, then the symbol, e.g. "155\xe2\x99\xa5\xef\xb8\x8f
# \n\n\nNIFTY 23550 PE" -- the option leg's own real, priced entry sits in
# an EARLIER message with a "<DAY> <MON>" expiry infix (see RE_SMS_OPT_DATE
# / the "ABOVE :- " fallback added to that block), which this bare
# no-date recap restates minus its own price. Without this, RE_OPT still
# matches the trailing "NIFTY 23550 PE" here (no date token to break it)
# with nothing following it, producing a second, blank-valued phantom
# Trade row alongside the real, priced one. Allows short trailing junk
# (emoji) after the leading number, since that's how this channel's
# reposts are actually punctuated -- verified empirically unique to
# channel 48 across the full 82-channel corpus (21 occurrences).
RE_OPT_BARE_PRICE_REPOST_REV = re.compile(
    r'\A\d[\d,]*(?:\.\d+)?[^\d\n]{0,15}'
    r'\n+\s*[A-Za-z][A-Za-z ]*\d[\d,]*(?:\.\d+)?\s*(?:CE|PE|CALL|PUT)\s*\Z',
    re.IGNORECASE)
# LIVELONG HARI's dominant CASH-order shape puts the ticker alone on its
# own line, then the entry band on the next paragraph as "BUY/SELL
# ABV/RANGE/ABOVE/BELOW/AT <price>[-<price>]" -- see _hari_cash_signal
# below, which anchors on this trigger and walks back to the ticker line.
# Anchored to the START of its own line (re.MULTILINE "^") -- without this,
# an ordinary English sentence that happens to contain "buy above <price>"
# or "buy at <price>" mid-line, with some OTHER word earlier on the same
# line, misreads that earlier word as the ticker: "Dnt buy above 7" (Platinum
# Research) walked back to "Dnt" (Hinglish for "don't", not a ticker), and
# "➡️Either buy above 95 if BO happens" (Ritvi Taneja) walked back
# to "Either". LIVELONG HARI's own genuine messages always put BUY/SELL as
# the first word of its line ("BUY ABV 1590-91", "Sell below 4800"), so this
# anchor costs it nothing.
RE_HARI_ENTRY_TRIGGER = re.compile(
    r'^\s*(BUY|SELL)\s+(?:ABV|RANGE|ABOVE|BELOW|AT)\s*[:\-]?\s*' + NUM,
    re.IGNORECASE | re.MULTILINE)

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


# Nivisha Verma (Bnf_unicorn)'s and Ritvi Taneja (Passionate Trader)'s
# shared dominant forward-call shape, found by checking coverage on their
# full tracked histories (only 7 and 10 trades existed respectively before
# this fix). A short symbol line (sometimes with a "(Weekly)" annotation),
# then a "✅"- or "➡"-bulleted list of chart commentary that somewhere
# states an entry trigger ("...above <price>" or "Breakout level <price>"),
# a support level, and a target, e.g. "PIDILITE IND\n✅Breakout above
# 3280+ possible\n✅Strong chart\n✅Large cap getting strong\n✅After
# breakout support will be 3160/3050\n✅Target 3350/3475/3600++\n✅Keep on
# radar" (Bnf_unicorn) / "HINDZINC\n➡ Re-creating Pole & Flag Pattern\n➡
# Breakout possible above 700\n➡ Support near 630\n➡ Keep on radar" (Ritvi
# Taneja). Loose (unlike RE_SUPPORT/RE_TARGET, tolerates arbitrary filler
# words between the keyword and the number, e.g. "Support level is at
# 475") but gated behind BOTH a bullet marker and the word "support"
# appearing anywhere in the message, and requires an explicit
# above/breakout-level entry trigger to even produce a signal (messages
# with only a support+target and no stated entry, e.g. a bare "AEROFLEX"
# call, are left deliberately unparsed rather than guessing an entry).
# Style-gated to 'mixed'; verified empirically that no other 'mixed'
# channel (Angel One Research, Ashika Calls, NIRMAL BANG OFFICIAL,
# Stockpro Online, Stocky Mind, Stock Gainers) has any message combining
# either bullet marker with the word "support" at all, so this can never
# fire outside these two channels.
RE_BNFU_ENTRY = re.compile(r'above\s*' + NUM, re.IGNORECASE)
RE_BNFU_ENTRY_BOLVL = re.compile(r'breakout\s+level\s*' + NUM, re.IGNORECASE)
RE_BNFU_SUPPORT = re.compile(r'support[^\d\n]{0,25}' + NUM, re.IGNORECASE)
RE_BNFU_TARGET = re.compile(r'targets?\s*[-:]?\s*' + NUM, re.IGNORECASE)
RE_BNFU_TARGET_FOR = re.compile(r'\bfor\s*' + NUM, re.IGNORECASE)
RE_BNFU_TARGET_HOLD = re.compile(r'\bhold[^\d\n]{0,20}' + NUM, re.IGNORECASE)


def _bnfunicorn_bullet_signal(text):
    """Nivisha Verma (Bnf_unicorn)'s / Ritvi Taneja's
    "<SYMBOL>\\n✅bullet...✅bullet..." (or "➡"-bulleted) breakout-call shape
    (see comment above). Returns one sig dict or None."""
    if ('✅' not in text and '➡' not in text) or not re.search(r'support', text, re.IGNORECASE):
        return None
    lines = [l.strip() for l in text.splitlines() if l.strip()]
    if not lines:
        return None
    sym = re.sub(r'\(.*?\)', '', lines[0]).strip()
    sym = re.sub(r'[^A-Za-z0-9 &\-]', '', sym).strip().upper()
    # a real ticker line here is always 1-3 words ("AEROFLEX", "YATHARTH
    # HOSP", "Gujarat Toolroom") -- longer than that means the first line is
    # ordinary prose that happens to mention a ticker mid-sentence, e.g.
    # "Place an alert in CENTRAL BANK above 42." (8 words).
    if not sym or not sym[0].isalpha() or len(sym.split()) > 3:
        return None
    if not _is_symbol(sym.split()[0]):
        return None
    em = RE_BNFU_ENTRY.search(text) or RE_BNFU_ENTRY_BOLVL.search(text)
    if not em:
        return None
    sm = RE_BNFU_SUPPORT.search(text)
    tm = (RE_BNFU_TARGET.search(text) or RE_BNFU_TARGET_FOR.search(text)
          or RE_BNFU_TARGET_HOLD.search(text))
    return {'trade': sym, 'direction': 'BUY', 'entry': _f(em.group(1)),
            'target': _f(tm.group(1)) if tm else None,
            'stop_loss': _f(sm.group(1)) if sm else None, 'status': 'Open'}


# Stock Gainers (SEBI Registered)'s and Ritvi Taneja (Passionate Trader)'s
# shared "SYMBOL-line, then a blank-or-single-newline gap, then N to M"
# recap shape, found by checking coverage on their full tracked histories
# (1575 of 1950 / 1638 of 1927 messages were unparsed under the shapes that
# already existed for these channels beforehand). The ticker sits ALONE on
# its own line, followed by ONE OR MORE newlines, then the price data --
# unlike Stock Gainers' own daily "Live Analysis of <date>" digest recap,
# which lists many symbols back-to-back on the SAME line as their own
# numbers ("PGEL 520CE CE 14 TO 20"), never symbol-alone-then-newline-then-
# number, so the digest can never match this shape regardless of how many
# newlines are required (verified empirically: 0 matches on every sampled
# digest post).
# A. retrospective recap stating the entry and already-hit level in one
#    shot: "Astra Micro\n\n1440 to 1480", "AYE FINANCE \n\n153 To 166",
#    "BLS \n372 to 396" (Ritvi Taneja's single-newline variant) -- same "no
#    confident close, so stays Open" convention as RE_STOCKY_RECAP/
#    RE_STMT_RECAP elsewhere in this file.
# B. forward entry call with explicit levels: "DIAMOND POWER\n\nCMP 356\n\n
#    Support 340\n\n\nFor 385" (sometimes an extra commentary line between
#    CMP/Support/Support/For, e.g. "Support only 130" or "Can Accumulate
#    till 1000" -- the optional non-capturing group between each label
#    tolerates exactly one such line without swallowing a second symbol).
#    Stock Gainers only.
STOCKGAINERS_SYMWORD = r"[A-Za-z][A-Za-z&\-]{1,25}"
STOCKGAINERS_SYM = (STOCKGAINERS_SYMWORD + r"(?:[ \t]+" + STOCKGAINERS_SYMWORD
                     + r"){0,3}")
# ordinary commentary/adjective words that sit alone on a line above a
# blank-line-separated price -- verified false positives on these channels'
# full history ("Breakout", "Locked", "Weekly Study", "PERFECT SETUP", the
# generic post-type headers "BTST"/"Equity Pick"/etc., and Ritvi Taneja's
# own "WEBELSOLAR\nAgain upper circuit\n\n590 to 1421++" two-line calls,
# where the commentary line sits closer to the numbers than the real
# symbol and so wins the "nearest line above" heuristic) -- checked against
# only the FIRST word of the candidate line, same convention as STOP_WORDS.
STOCKGAINERS_DENY = {
    'AFTER', 'ALSO', 'BREAKOUT', 'LOCKED', 'MOVE', 'MOVED', 'PERFECT',
    'SHOWING', 'STRENGTH', 'SLOWLY', 'TILL', 'TIMING', 'UNBELIEVABLE', 'WAS',
    'WEEKLY', 'DOUBLE', 'REVERSAL', 'LOADING', 'POTENTIAL', 'SETUP', 'FAST',
    'TOO', 'STUDY', 'HIT', 'BOTH', 'BIGGER', 'ANOTHER', 'FRESH', 'CAN',
    'CONTINUOUSLY', 'ACCUMULATE', 'CLEAN', 'QUALITY', 'MOMENTUM', 'LOW',
    'RISK', 'SHORT', 'LONG', 'TERM', 'SWING', 'TRADE', 'PORTFOLIO', 'EQUITY',
    'PICK', 'CONVICTION', 'INTRA', 'BTST', 'VIEW', 'OPTION', 'BUYING',
    'STOCK', 'GOOD', 'MORNING', 'BLOCKBUSTER', 'EXCELLENT', 'FRIDAY',
    'GOING', 'IPO', 'MY', 'SOLID', 'VOLUMES', 'YESTERDAY', 'FOR', 'BEUTIFUL',
    'AGAIN', 'TREND', 'UPPER', 'AMAZING',
    # The Trading Marvel's own ordinary-prose sentences that happen to open
    # with a capitalized word directly above a "N to M" line, matching this
    # shape's loose "<up-to-4-word line>\n<N to M>" pattern as if the
    # sentence's first word were a ticker: "If it rises from 200 to 300
    # then 20/30 points normal correction" -> phantom "IF IT RISES", "What
    # you say now\n1677 to 1877" -> phantom "WHAT YOU SAY NOW", "Fired
    # \n700 to 960" -> phantom "FIRED". Common English words, not tickers.
    'WHAT', 'FIRED',
}
# a candidate whose LAST two words are "STRONG SUPPORT"/"STRONG RESISTANCE"
# is 20PAISA..COM's plain index-level commentary ("Nifty Strong Support
# \n\n\n\n24000 To 24050", a support-zone note, not a trade call) matching
# RE_STOCKGAINERS_RECAP's loose "<up-to-4-word line>\n<N to M>" shape with
# a real index root ("NIFTY") as its first word, so the existing
# first-word-only STOCKGAINERS_DENY check lets it through. Checked as a
# trailing PHRASE rather than folded into STOCKGAINERS_DENY as individual
# words, because Stockizen Research's genuine "NIFTY SEP FUT SHORT"
# futures call also ends in a lone DENY word ("SHORT") and must keep
# matching — this stays scoped to the exact two-word tail, verified 0
# occurrences as a real ticker's trailing words anywhere in the tracked
# corpus.
STOCKGAINERS_TRAILING_DENY = {('STRONG', 'SUPPORT'), ('STRONG', 'RESISTANCE')}

# Ritvi Taneja's third shape (smaller, ~10-100 occurrences depending on
# overlap with the recap/bullet shapes above): the symbol and its CMP/entry
# sit together on the FIRST line with no other keyword ("SBIN 1011", "DLF
# 663", "Central Bank 64.4"), and a "support" figure follows somewhere in
# the message, e.g. "SBIN 1011\nSupport 992\n\nAvg 1000-995\n\nCan hit
# 1025/1038/1050\n\nWeak below 992 closing". Style-gated to 'mixed';
# verified empirically that the only other 'mixed' channels this fires on
# at all are Stock Gainers and Bnf_unicorn (both already in this batch, and
# both genuinely use the same "<SYMBOL> <PRICE>" first-line convention), 0
# elsewhere.
RE_SYMLINE_ENTRY = re.compile(
    r'^(' + STOCKGAINERS_SYM + r')[ \t]+' + NUM + r'[ \t]*$', re.MULTILINE)
RE_SYMLINE_TARGET = re.compile(
    r'targets?\s*[-:]?\s*' + NUM + r'|can\s+hit\s*' + NUM + r'|towards\s*' + NUM,
    re.IGNORECASE)


def _symline_support_signal(text):
    """"<SYMBOL> <PRICE>" alone on the first line, with a "support" figure
    stated somewhere else in the message (see comment above). Returns one
    sig dict or None."""
    if not re.search(r'support', text, re.IGNORECASE):
        return None
    lines = text.splitlines()
    if not lines:
        return None
    m = RE_SYMLINE_ENTRY.match(lines[0])
    if not m:
        return None
    sym = m.group(1).strip().upper()
    if not _is_symbol(sym.split()[0]) or sym.split()[0] in STOCKGAINERS_DENY:
        return None
    sm = RE_BNFU_SUPPORT.search(text)
    tm = RE_SYMLINE_TARGET.search(text)
    target = None
    if tm:
        target = _f(next(g for g in tm.groups() if g is not None))
    return {'trade': sym, 'direction': 'BUY', 'entry': _f(m.group(2)),
            'target': target, 'stop_loss': _f(sm.group(1)) if sm else None,
            'status': 'Open'}


# Samco's formal "RECOMMENDATION ALERT" broker template -- found by checking
# coverage on the full 1927-message tracked history: this channel's 144
# pre-existing trades were phantoms (garbage roots like "MAR 23500 CE" torn
# out of a glued option ticker by the generic RE_VERB_FIRST/RE_CASH
# fallbacks, e.g. reading the "25" of "AUBANK25DEC980PE" as the entry
# price of a bogus cash trade named "AUBANK"), not real coverage. Two
# independent parses of the SAME alert, each individually sufficient
# (their (channel, trade, entry) upsert key collapses them into one Trade
# row when both fire on the same message, so running both is free):
# A. the structured field block itself, e.g. "Stock Name: Pfizer
#    Limited\nSymbol: PFIZER\nRating: Buy 🟢\nCMP: ₹4130\nStop loss:
#    ₹3890\nTarget: ₹4545\nDuration: 5-10 Days..." -- "Symbol:" is always
#    the real ticker (unlike "Stock Name:", which is the full company name
#    and sometimes blank for an index leg), "CMP:" the entry, "Stop loss:"/
#    "Target:" self-explanatory. 829 of 1927 messages match. Only ever
#    seen with Rating "Buy" (never "Sell"/"Hold") across the whole tracked
#    history, so direction is always BUY. Deliberately rejects the rare
#    (2 of 1927) multi-leg "Symbol: SELL BANKNIFTY 25APR 52000 CE CMP:
#    ₹574\n   SELL BANKNIFTY..." straddle/strangle alert -- its "Stop
#    loss"/"Target" are a total ₹ P&L figure across all four legs, not a
#    per-share price, and cramming it through this per-leg parser would
#    silently fabricate a wrong single-leg price.
# B. the trailing "Note: Buy <SYM> at <price> SL <sl> TGT <tgt>" one-liner
#    (or "... at CMP <price>...", "... at CMP of Rs.<price> with SL of
#    Rs.<sl>" for the no-Target "Momentum/Quality/Delivery Pick" durations)
#    -- kept as a second, independent path because a small number of
#    alerts (2 of 1927, "GLENMARK 2020 CE" style) restate the option leg
#    with different rounding between the two locations, and because A's
#    field block is occasionally malformed enough (rare parsing edge cases
#    not yet seen in this corpus) that a second read of the same
#    information is cheap insurance. 63 of 79 "Note:" lines match; the
#    other 16 are plain company-description prose the Note carries for the
#    long-duration picks (correctly left to path A instead).
# Both compact the option ticker's glued expiry token ("AUBANK25DEC980PE",
# "NIFTY25DEC26200CE", spaced or not) down to this codebase's normal "ROOT
# STRIKE CE/PE" convention via _parse_samco_symbol -- reusing the DDMMM
# expiry shape (2-digit day + 3-letter month) that appears in every case
# seen; the rare SENSEX weekly-numeric-expiry format ("SENSEX2561781500PE",
# 1 of 1927) doesn't match and is deliberately left as an ugly-but-honest
# literal symbol rather than guessing where the strike starts.
# Style-gated to 'mixed'; verified empirically that neither "RECOMMENDATION
# ALERT" field labels nor a "Note: Buy ... at/CMP ..." line appear in any
# other 'mixed' channel's history.
RE_SAMCO_OPT_SYM = re.compile(
    r'^([A-Z]+)\s*\d{1,2}[A-Z]{3}\s*(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)$')


def _parse_samco_symbol(raw):
    raw = re.sub(r'\s+', ' ', (raw or '').strip()).upper()
    m = RE_SAMCO_OPT_SYM.match(raw)
    if m:
        return f'{m.group(1)} {m.group(2).replace(",", "")} {m.group(3)}'
    return raw


RE_SAMCO_SYM_FIELD = re.compile(r'Symbol:\s*([^\n]+)')
RE_SAMCO_CMP_FIELD = re.compile(r'CMP:\s*₹\s*(\d[\d,]*(?:\.\d+)?)', re.IGNORECASE)
RE_SAMCO_SL_FIELD = re.compile(r'Stop loss:\s*₹\s*(\d[\d,]*(?:\.\d+)?)', re.IGNORECASE)
RE_SAMCO_TGT_FIELD = re.compile(r'Target:\s*₹\s*(\d[\d,]*(?:\.\d+)?)', re.IGNORECASE)


def _samco_block_signal(text):
    """Samco's structured "RECOMMENDATION ALERT" field block (see comment
    above). Returns one sig dict or None."""
    if 'RECOMMENDATION ALERT' not in text:
        return None
    sm = RE_SAMCO_SYM_FIELD.search(text)
    cm = RE_SAMCO_CMP_FIELD.search(text)
    if not sm or not cm:
        return None
    raw = sm.group(1).strip()
    # reject the rare multi-leg straddle/strangle alert, whose "Symbol:"
    # line embeds a second BUY/SELL leg and its own "CMP:" rather than
    # naming a single leg (see comment above).
    if not raw or len(raw) > 30 or ':' in raw or ' BUY ' in f' {raw} ' or ' SELL ' in f' {raw} ':
        return None
    sym = _parse_samco_symbol(raw)
    if not sym or not sym[0].isalpha():
        return None
    slm = RE_SAMCO_SL_FIELD.search(text)
    tm = RE_SAMCO_TGT_FIELD.search(text)
    return {'trade': sym, 'direction': 'BUY', 'entry': _f(cm.group(1)),
            'target': _f(tm.group(1)) if tm else None,
            'stop_loss': _f(slm.group(1)) if slm else None, 'status': 'Open'}


RE_SAMCO_NOTE_LINE = re.compile(r'Note:\s*(?:BUY|Buy)\s+([^\n]+)')
RE_SAMCO_NOTE_SPLIT = re.compile(
    r'^(.*?)\s+(?:at\s+CMP\s+of|at\s+CMP|CMP\s+of|at|CMP)\s*:?\s*(.*)$', re.IGNORECASE)
RE_SAMCO_NOTE_SL = re.compile(
    r'SL\s*(?:of\s+)?(?:Rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)|Stoploss\s+of\s+(?:Rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)',
    re.IGNORECASE)
RE_SAMCO_NOTE_TGT = re.compile(r'TGT\s*(\d[\d,]*(?:\.\d+)?)', re.IGNORECASE)


def _samco_note_signal(text):
    """Samco's "Note: Buy <SYM> at/CMP <price> SL <sl> TGT <tgt>" one-liner
    (see comment above _samco_block_signal). Returns one sig dict or None."""
    m = RE_SAMCO_NOTE_LINE.search(text)
    if not m:
        return None
    sm = RE_SAMCO_NOTE_SPLIT.match(m.group(1).strip())
    if not sm:
        return None
    raw, rest = sm.group(1), sm.group(2)
    if not raw or len(raw) > 30:
        return None
    sym = _parse_samco_symbol(raw)
    if not sym or not sym[0].isalpha():
        return None
    em = re.match(r'\s*(?:Rs\.?\s*)?(\d[\d,]*(?:\.\d+)?)', rest)
    if not em:
        return None
    slm = RE_SAMCO_NOTE_SL.search(rest)
    sl = _f(next(g for g in slm.groups() if g is not None)) if slm else None
    tm = RE_SAMCO_NOTE_TGT.search(rest)
    return {'trade': sym, 'direction': 'BUY', 'entry': _f(em.group(1)),
            'target': _f(tm.group(1)) if tm else None, 'stop_loss': sl,
            'status': 'Open'}


# Trading Ideas By Darshan's two dominant shapes, found by checking
# coverage on the full 1903-message tracked history (0 trades existed
# before this fix -- most of the channel is astrology/"Planetary Aspects"
# commentary and macro news, correctly left unparsed, but a real minority
# of messages are option/cash calls in a consistent house style).
# A. the forward option order: "Nifty 26100 Ce (13 Jan Expiry)\nCmp 151\n
#    Target Open\nStoploss 120\n\n*Keep Proper Risk Management..." -- "Cmp"
#    is the entry, "Target Open" means no stated numeric target (kept
#    blank rather than guessed), "Stoploss" self-explanatory.
# B. the retrospective recap: "Sail from 129.3 to 141", "Sensex 74900 Ce
#    From 5 to 160", "Nifty 26100 Ce\nFrom 151 to 223" -- same "no
#    confident close, so stays Open" convention as RE_STOCKY_RECAP
#    elsewhere in this file. Shared between cash equities/indices and
#    option legs: a trailing "<strike> CE|PE" on the symbol candidate is
#    normalized into this codebase's "ROOT STRIKE CE/PE" convention by
#    _normalize_darshan_symbol; direction for an option leg comes from
#    CE/PE (never guessed from the price move), for cash/index from
#    whichever side of the range is higher (same convention as
#    RE_STOCKY_RECAP).
# Style-gated to 'mixed'; verified empirically that neither shape's
# keyword combination ("Cmp"+"Target Open"+"Stoploss" on consecutive
# lines, or a bare "<name> from <N> to <M>") appears in any other 'mixed'
# channel's history.
RE_DARSHAN_OPT_ENTRY = re.compile(
    r'^([A-Za-z][A-Za-z0-9 &]{1,25}?)\s+(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)\b[^\n]*\n'
    r'\s*Cmp\s*[:\-]?\s*(\d[\d,]*(?:\.\d+)?)\s*\n'
    r'(?:Target[^\n]*\n)?'
    r'\s*Stoploss\s*[:\-]?\s*(\d[\d,]*(?:\.\d+)?)',
    re.MULTILINE | re.IGNORECASE)
RE_DARSHAN_RECAP = re.compile(
    r'^([A-Za-z][A-Za-z0-9 &]{1,25}?)\s*\n?\s*(?:from|From|FROM)\s+'
    r'(\d[\d,]*(?:\.\d+)?)\s*(?:to|To|TO)\s*(\d[\d,]*(?:\.\d+)?)', re.MULTILINE)
# candidate words that ride along into the symbol group because they sit
# directly before "from" in ordinary market-commentary prose ("Gold
# rallied from...", "Silver moved from...") -- checked against every word
# in the candidate, not just the first (unlike STOP_WORDS elsewhere),
# since these are always the LAST word of a multi-word candidate.
DARSHAN_VERB_DENY = {'RALLIED', 'SURGED', 'MOVED', 'WENT', 'JUMPED',
                     'CRASHED', 'DROPPED', 'FELL', 'SPIKED', 'RECOVERED',
                     'BREAKOUT', 'MASSIVE',
                     # "NESTLE BREAKOUT - Decent numbers !!\nProper 2X
                     # trade from 27 to 54+" (Platinum Research) -- the
                     # real symbol (NESTLE) sits a line above "Proper 2X
                     # trade", which this catches instead without the
                     # extra deny words; TRADE/PROPER/2X never end a real
                     # Darshan symbol candidate either.
                     'TRADE', 'PROPER', '2X'}


def _normalize_darshan_symbol(raw):
    raw = re.sub(r'\s+', ' ', (raw or '').strip()).upper()
    m = re.match(r'^(.+?)\s+(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)$', raw)
    if m:
        return f'{m.group(1).strip()} {m.group(2).replace(",", "")} {m.group(3)}'
    return raw


def _darshan_option_entry_signal(text):
    m = RE_DARSHAN_OPT_ENTRY.search(text)
    if not m:
        return None
    root = re.sub(r'\s+', ' ', m.group(1).strip()).upper()
    if not _is_symbol(root.split()[0]):
        return None
    right = m.group(3).upper()
    sym = f'{root} {m.group(2).replace(",", "")} {right}'
    return {'trade': sym, 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
            'entry': _f(m.group(4)), 'target': None,
            'stop_loss': _f(m.group(5)), 'status': 'Open'}


def _darshan_recap_signal(text):
    m = RE_DARSHAN_RECAP.search(text)
    if not m:
        return None
    words = m.group(1).strip().upper().split()
    if not words or any(w in DARSHAN_VERB_DENY for w in words):
        return None
    sym = _normalize_darshan_symbol(m.group(1))
    if not sym or not _is_symbol(sym.split()[0]):
        return None
    entry_v, exit_v = _f(m.group(2)), _f(m.group(3))
    if sym.endswith(' CE') or sym.endswith(' PE'):
        direction = 'CALL (up)' if sym.endswith('CE') else 'PUT (down)'
    else:
        direction = 'BUY' if exit_v >= entry_v else 'SELL'
    return {'trade': sym, 'direction': direction, 'entry': entry_v,
            'target': exit_v, 'stop_loss': None, 'status': 'Open'}


# 𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒's dominant option-order shape, found by checking
# coverage on the full 1897-message tracked history: about half its real
# calls write CE/PE/PUT/CALL in lower or mixed case ("Dr reddy option\n\n
# 1320 ce at 14 sl 6 target 22 and 30", "Bank nifty 55000 ce at 1100 sl
# 1000 tgt 1180 and 1250", "Sensex 83500 put ... at 485 sl 360 target 585
# and 650"), invisible to every other option regex in this file (all
# case-sensitive on CE/PE by design, to keep ordinary prose from becoming
# a phantom ticker). Deliberately requires the FULL "<root> <strike>
# CE/PE/CALL/PUT ... SL <n> ... TARGET/TGT <n>" structure in one match,
# not just a bare "<number> CE/PE" -- this channel constantly discusses
# "<strike> PUT WRITER"/"<strike> CALL WRITER" market positioning as
# commentary, not as its own trade calls (e.g. "Bankex 65100 put from 12
# to 100", "24200 put writer are still there"), and requiring SL+TARGET
# excludes all of it without a separate WRITER-specific exclusion. Style-
# gated to 'mixed'; a full-corpus check found only two harmless side
# effects elsewhere: Angel One Research's "BANKNIFTY MAR 49500 CE @
# 361-365 SL 407 TGT 300" now gets its real entry (361) instead of no
# signal at all (this shape's multi-word root capture tolerates the
# "MAR" expiry token RE_OPT's own MONTH_ABBR guard has to reject
# elsewhere), and 4 already-mostly-covered Ashika Calls messages gain a
# second, blank-entry duplicate of a trade Ashika's own parser already
# captured correctly (harmless: same (channel, trade) key, no new row).
RE_FINSARTHI_OPT = re.compile(
    r'\b([A-Za-z][A-Za-z&\-]{0,20}(?:[ \t]+[A-Za-z][A-Za-z&\-]{0,20}){0,3})'
    r'[ \t]+(\d[\d,]*(?:\.\d+)?)[ \t]*(CE|PE|CALL|PUT)\b'
    r'(?:[ \t]*(?:AT|@)[ \t]*(\d[\d,]*(?:\.\d+)?)(?:[ \t]*-[ \t]*\d[\d,]*(?:\.\d+)?)?)?'
    r'[^\n]{0,40}?\bSL\b[ \t]*[:\-]?[ \t]*(\d[\d,]*(?:\.\d+)?)'
    r'[^\n]{0,40}?\b(?:TARGET|TGT)\b[ \t]*[:\-]?[ \t]*(\d[\d,]*(?:\.\d+)?)',
    re.IGNORECASE)
# leading filler words this channel prefixes the root with, stripped
# before use as the ticker ("BUY BNF 57000CE..." -> "BNF", "OPTION HZ
# NIFTY 24200CE..." -> "NIFTY").
RE_FINSARTHI_LEAD_STRIP = re.compile(
    r'^(?:BUY|SELL|OPTION|HZ|HERO|ZERO|INDEX)[ \t]+', re.IGNORECASE)


def _finsarthi_option_signal(text):
    m = RE_FINSARTHI_OPT.search(text)
    if not m:
        return None
    root = m.group(1).strip()
    while True:
        stripped = RE_FINSARTHI_LEAD_STRIP.sub('', root)
        if stripped == root:
            break
        root = stripped
    root = re.sub(r'\s+', ' ', root).strip().upper()
    if not root or not _is_symbol(root.split()[0]):
        return None
    right = {'CALL': 'CE', 'PUT': 'PE'}.get(m.group(3).upper(), m.group(3).upper())
    sym = f'{root} {m.group(2).replace(",", "")} {right}'
    return {'trade': sym, 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
            'entry': _f(m.group(4)) if m.group(4) else None,
            'target': _f(m.group(6)), 'stop_loss': _f(m.group(5)), 'status': 'Open'}


# 𝑵𝒂𝒔𝒅𝒂𝒒 𝒎𝒂𝒔𝒕𝒆𝒓𝒔's dominant forex/gold shape, found by checking coverage
# on the full 1891-message tracked history (125 trades already existed
# via the shared uppercase-only RE_VERB_FIRST/RE_BUYSELL, but only ~half
# of this channel's real calls write BUY/SELL in uppercase -- the other
# half use lowercase/mixed case, e.g. "XAUUSD sell 4335+4340", "*GOLD CAN
# BUY WITH 4402"). Making RE_BUYSELL itself case-insensitive on BUY/SELL
# was tried and rejected: a full-corpus check found it also fires on
# ordinary-English false positives elsewhere ("BIG sell-off in both the
# indexes...", a bulk-deal report's "...WORTHY DIS[COUNT]... BLW Buy",
# an RBI policy note's "...INR buy...") in channels far outside this
# batch. This is scoped instead to a small enumerated set of the actual
# instruments this channel trades (XAUUSD/GOLD/BTCUSD/SILVER/XAGUSD/
# EURUSD/GBPUSD/USDJPY), the same convention as RE_OPT_INDEX_CI's
# NIFTY/BANKNIFTY/SENSEX/FINNIFTY set -- verified empirically 0 matches
# on any other channel's history with this narrower set. A "+"-joined
# dual price ("4335+4340") keeps only the first number as the entry, same
# "never average or guess" convention as the ladder shapes elsewhere in
# this file. Style-gated to 'mixed'.
RE_NASDAQMASTERS_FX = re.compile(
    r'\b(XAUUSD|GOLD|BTCUSD|SILVER|XAGUSD|EURUSD|GBPUSD|USDJPY)\b\s*'
    r'(?:CAN\s+)?(BUY|SELL)\s*(?:WITH\s*)?[:.]?\s*(\d[\d,]*(?:\.\d+)?)'
    r'(?:\s*\+\s*\d[\d,]*(?:\.\d+)?)?', re.IGNORECASE)


def _nasdaqmasters_fx_signal(text):
    m = RE_NASDAQMASTERS_FX.search(text)
    if not m:
        return None
    sym = m.group(1).upper()
    side = m.group(2).upper()
    return {'trade': sym, 'direction': 'BUY' if side == 'BUY' else 'SELL',
            'entry': _f(m.group(3)), 'target': None, 'stop_loss': None,
            'status': 'Open'}


RE_STOCKGAINERS_RECAP = re.compile(
    r'^(' + STOCKGAINERS_SYM + r')[ \t]*\r?\n\s*'
    r'(\d[\d,]*(?:\.\d+)?)\s*(?:to|To|TO)\s*(\d[\d,]*(?:\.\d+)?)', re.MULTILINE)
RE_STOCKGAINERS_ENTRY = re.compile(
    r'^(' + STOCKGAINERS_SYM + r')[ \t]*\r?\n[ \t]*\r?\n[ \t]*'
    r'CMP\s*:?\s*₹?\s*(\d[\d,]*(?:\.\d+)?)(?:[ \t]*-[ \t]*\d[\d,]*(?:\.\d+)?)?[^\n]*\n[ \t]*\n?[ \t]*'
    r'(?:[A-Za-z][^\n]{0,20}\n[ \t]*\n?[ \t]*)?'
    r'Support\s*(?:only\s*)?:?\s*(\d[\d,]*(?:\.\d+)?)[^\n]*\n[ \t]*\n*[ \t]*'
    r'(?:[A-Za-z][^\n]{0,25}\n[ \t]*\n*[ \t]*)?'
    r'For\s*:?\s*(\d[\d,]*(?:\.\d+)?)',
    re.MULTILINE | re.IGNORECASE)


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


# Finance With Sunil's dominant structured option-order template:
#   "Stock Name- #KPIT\n\nStrike- June 760 CE 35-36\nLot Size-425\n
#   SL-28 (3/5 Min CB)\nTarget-40/44/50/58" -- also seen with a leading
# day-of-month token before the option-expiry month ("Strike- 8 SEP
# 23650 PE 23"). Root ticker comes from the "#SYM" hashtag (this channel's
# tickers are frequently lower/mixed-case, e.g. "#Mcx", "#Dixon" -- unlike
# most other channels' hashtags this codebase treats as tickers, so this
# is its own dedicated pattern rather than reusing RE_STMT_RECAP, which
# requires an all-caps symbol via _is_symbol). Gated on the literal
# "Strike-" field label, verified empirically unique to this channel
# across the full 82-channel tracked history (35 occurrences, all
# channel 14) -- safe to leave otherwise ungated.
RE_FINSUNIL_OPT = re.compile(
    r'#([A-Za-z][A-Za-z0-9]{1,20})\b.*?'
    r'Strike-\s*(?:\d{1,2}\s+)?(?:[A-Za-z]{3,9}\s+)?(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)\s*'
    r'(\d[\d,]*(?:\.\d+)?)(?:\s*-\s*(\d[\d,]*(?:\.\d+)?))?.*?'
    r'SL[\s\-]*(\d[\d,]*(?:\.\d+)?).*?'
    r'Target[\s\-]*(\d[\d,]*(?:\.\d+)?)',
    re.IGNORECASE | re.DOTALL)
# NOTE: Finance With Sunil's "Stock Name- #SYM\n#SYM <price> To <price>
# ... Target Done" recap (e.g. "Stock Name- #Dixon\n#Dixon 450 To 523+
# Second Target Done.") is DELIBERATELY NOT given its own signal pattern
# here. Checked empirically against every such message in the tracked
# history (98 occurrences): 97 carry a "Lot Size-" line and the 1 that
# doesn't ("#ofss 370 to 392 but not sustain now stoploss hit") is still
# about the same option leg -- so this shape is *always* a restatement of
# an option order already opened by a separate, earlier "Strike-" message
# (see RE_FINSUNIL_OPT), never a standalone signal. Parsing it as a bare
# "#SYM" cash symbol (the channel's tickers are lower/mixed-case, so
# _is_symbol can't reject it as it does elsewhere) would mint a phantom
# duplicate cash Trade next to the real option Trade every time -- e.g.
# "KPIT 760 CE" (opened at premium 35) restated 6 times as the option
# price runs 40.45 -> 41.90 -> 45 -> 49 -> 54 -> 70 would otherwise create
# 6 separate bare "KPIT" cash rows, exactly the "restated leg mistaken for
# a fresh order" trap this codebase repeatedly guards against elsewhere
# (RE_FRESH_BREAKOUT dedup, THEBULLOPTIONS repost handling, etc). Left
# unparsed rather than guessed at; a real fix would need to attribute the
# price move back to the option leg opened under the same hashtag, which
# needs cross-message state parse_message() doesn't have.
# Finance With Sunil's "Trade For Prime Members" option-leg recap:
# "#Lodha\n\nJuly 1140 CE 35-36 To 68", "#Sensex\n\nAug 77200 CE 380 To
# 830+" -- same channel, a second recurring shape for its paid-tier
# option calls (strike stated inline rather than behind "Strike-").
# Gated on the literal "Prime Members" header phrase a couple of lines up
# (verified empirically unique to channel 14, 8 occurrences, 0 elsewhere).
RE_FINSUNIL_OPT_RECAP = re.compile(
    r'#([A-Za-z][A-Za-z0-9]{1,20})\b\s*\n+\s*(?:[A-Za-z]{3,9}\s+)?(\d[\d,]*(?:\.\d+)?)\s*(CE|PE)\s+'
    r'(\d[\d,]*(?:\.\d+)?)(?:\s*-\s*(\d[\d,]*(?:\.\d+)?))?\s*To\s*(\d[\d,]*(?:\.\d+)?)',
    re.IGNORECASE)


def _finsunil_signal(text):
    """Finance With Sunil's two dominant standalone shapes (see comments
    above RE_FINSUNIL_OPT/RE_FINSUNIL_OPT_RECAP). Returns one sig dict or
    None."""
    if 'Strike-' in text:
        m = RE_FINSUNIL_OPT.search(text)
        if m:
            sym = m.group(1).upper()
            if _is_symbol(sym):
                strike, right = m.group(2).replace(',', ''), m.group(3).upper()
                entry = _f(m.group(4))
                return {'trade': f'{sym} {strike} {right}',
                        'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                        'entry': entry, 'target': _f(m.group(7)),
                        'stop_loss': _f(m.group(6)), 'status': 'Open'}
    if 'Prime Members' in text:
        m = RE_FINSUNIL_OPT_RECAP.search(text)
        if m:
            sym = m.group(1).upper()
            if _is_symbol(sym):
                strike, right = m.group(2).replace(',', ''), m.group(3).upper()
                entry_v, exit_v = _f(m.group(4)), _f(m.group(6))
                return {'trade': f'{sym} {strike} {right}',
                        'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                        'entry': entry_v, 'target': exit_v, 'stop_loss': None,
                        'status': 'Open'}
    return None


# Stockizen Research's structured swing-trade template:
#   "\U0001F4A5 GE POWER INDIA LTD (NSE: GVPIL) - POSITIONAL SWING TRADE
#   \n\nENTRY ZONE: ₹780 - ₹790 (Current bounce zone)\n\nSL: ₹690
#   (As given) → Risk: ~11% to 13%\n\nTARGET 1: ₹900 (+12% to +15%)
#   \nTARGET 2: ₹990 (+25% to +28%)" -- the NSE ticker in parens is used
# as the trade symbol rather than the free-text company name, matching
# this codebase's normal "root ticker" convention. Only TARGET 1 is kept
# (the first, nearer target -- same "never average/guess" convention used
# elsewhere for multi-target ladders). Gated on the literal "POSITIONAL
# SWING TRADE" header, verified empirically unique to channel 54 (5
# occurrences, 0 elsewhere) -- safe to leave otherwise ungated.
RE_STOCKIZEN_SWING = re.compile(
    r'\(NSE:\s*([A-Z]+)\)\s*-\s*POSITIONAL\s+SWING\s+TRADE.*?'
    r'ENTRY\s+ZONE\s*:\s*₹?\s*(\d[\d,]*(?:\.\d+)?)\s*[-–]\s*₹?\s*(\d[\d,]*(?:\.\d+)?).*?'
    r'SL\s*:\s*₹?\s*(\d[\d,]*(?:\.\d+)?).*?'
    r'TARGET\s*1\s*:\s*₹?\s*(\d[\d,]*(?:\.\d+)?)',
    re.IGNORECASE | re.DOTALL)


def _stockizen_swing_signal(text):
    m = RE_STOCKIZEN_SWING.search(text)
    if not m:
        return None
    sym = m.group(1).upper()
    if not _is_symbol(sym):
        return None
    return {'trade': sym, 'direction': 'BUY', 'entry': _f(m.group(2)),
            'target': _f(m.group(5)), 'stop_loss': _f(m.group(4)), 'status': 'Open'}


# Systematix Group Official's dominant cash/futures-order template: "Buy
# BAJAJ AUTO in cash @ 8865-8855 SL 8665 TGT 9265", "Buy Mazagon Dock
# Shipbuilders Ltd in cash @ 2755-2750 SL 2640 TGT 1)2850 2)2950", "Buy
# NIFTY Fut @ 23380-23360 SL 23220 TGT 23700  (Cmp23412)", "Buy DIXON in
# 10472-10462 SL 10260 TGT 10900" (bare "in", no "cash" word), "Buy Kaveri
# Seed Company Ltd\nin at 750-745 SL 710 TGT 1)790 2)830" ("in at" instead
# of "in cash @"). The channel's real tickers are almost always company
# names, 1-7 words, frequently ending "Ltd"/"Limited" -- invisible to the
# shared single-word RE_VERB_FIRST/RE_BUYSELL, whose root is one bare
# ALL-CAPS token, and whose "BUY <SYM> [CASH|FUT|FUTURES]? ... <NUM>"
# shape has no room for the filler words "in"/"in cash"/"in at" this
# channel always inserts before the price. Restated close-out messages
# reuse this exact shape verbatim with a leading "Stopped out .."/"Target
# Achieved…"/"Book Profit & Exit @ <price>…." prefix (e.g. "Stopped out
# .. Buy HAL in cash @ 4941-4935 SL 4825 TGT 5170") -- deliberately NOT
# excluded here, since the entry/SL/target triple is identical to the
# original entry message and lands on the same (channel, trade, entry)
# upsert key, so it updates the same Trade row rather than duplicating it;
# the boolean exit itself is handled separately by parse_exit's existing
# "STOPPED OUT"/"EXIT" keyword scan on the same message. A trailing "Fut"
# after the root is dropped from the trade key, NOT kept as a distinct
# suffix -- matching this codebase's one existing convention for a
# futures leg (RE_FUT's own `sym` a few hundred lines up never appends a
# "FUT" marker either), and needed here for a more concrete reason: the
# shared single-word RE_VERB_FIRST/RE_BUYSELL ALSO matches this same
# channel's futures messages ("Sell AUBANK Fut @ 722.65-725 SL 740 TGT
# 680" -> plain "AUBANK", already correct, via its own optional FUT
# slot), so keeping a " FUT" suffix here would mint a second, redundant
# "AUBANK FUT" row for every futures call instead of the two matches
# converging on the same (channel, trade, entry) key. Style-gated to
# 'cash' (this channel's own style); verified
# empirically 0 matches on every other 'cash'-style channel's full
# history (Motilal Oswal - Official, Mystocks.in, Short To Mid Term®™,
# Swing Trader Vishal).
RE_SYSTEMATIX_CASH = re.compile(
    r'\b(BUY|SELL)\s+([A-Za-z][A-Za-z0-9&.]*(?:\s+[A-Za-z][A-Za-z0-9&.]*){0,6}?)\s+'
    r'(?:IN\s+CASH|IN|CASH|FUT(?:URES)?)\b\s*(?:AT\s+|@\s*)?' + NUM +
    r'(?:\s*-\s*' + NUM + r')?'
    r'[^\n]*?\bSL\s*[:\-]?\s*' + NUM +
    r'[^\n]*?\b(?:TGT|TARGET)\s*[:\-]?\s*(?:\d\)\s*)?' + NUM,
    re.IGNORECASE)
RE_SYSTEMATIX_SUFFIX_LEAD_STRIP = re.compile(r'\s+(?:LTD\.?|LIMITED)$', re.IGNORECASE)


def _systematix_cash_signal(text):
    m = RE_SYSTEMATIX_CASH.search(text)
    if not m:
        return None
    side = m.group(1).upper()
    root = re.sub(r'\s+', ' ', m.group(2).strip()).upper()
    root = RE_SYSTEMATIX_SUFFIX_LEAD_STRIP.sub('', root).strip()
    if not root or not _is_symbol(root.split()[0]):
        return None
    return {'trade': root, 'direction': 'BUY' if side == 'BUY' else 'SELL',
            'entry': _f(m.group(3)), 'target': _f(m.group(6)),
            'stop_loss': _f(m.group(5)), 'status': 'Open'}


# Systematix Group Official's "Stock Picks of the week" structured block,
# the ticker's OWN dominant shape for its weekly-pick messages (separate
# from the daily "Buy <sym> in cash @ ..." shape above): "Stock Picks of
# the week : Buy - Thermax Ltd\n\nBuy Range : Rs. 3,151 - Rs. 3,145\nStop
# Loss : Rs. 2,960\nTarget 1 : Rs. 3,345\nTarget 2 : Rs. 3,540". Only
# Target 1 (the nearer target) is kept, same "never average/guess"
# convention used for every other multi-target ladder in this file. Gated
# on the literal "Stock Picks of the week" + "Range :" header combination,
# verified empirically unique to channel 61 (35 occurrences, 0 elsewhere).
RE_SYSTEMATIX_WEEKLY = re.compile(
    r'Stock Picks of the week\s*:\s*(BUY|SELL)\s*-\s*([A-Za-z][A-Za-z0-9&.\s]{1,40}?)\s*\n+.*?'
    r'(?:BUY|SELL)\s+Range\s*:\s*Rs\.?\s*' + NUM + r'\s*-\s*Rs\.?\s*' + NUM + r'.*?'
    r'Stop\s+Loss\s*:\s*Rs\.?\s*' + NUM + r'.*?'
    r'Target\s*1\s*:\s*Rs\.?\s*' + NUM,
    re.IGNORECASE | re.DOTALL)


def _systematix_weekly_signal(text):
    m = RE_SYSTEMATIX_WEEKLY.search(text)
    if not m:
        return None
    side = m.group(1).upper()
    root = re.sub(r'\s+', ' ', m.group(2).strip()).upper()
    root = RE_SYSTEMATIX_SUFFIX_LEAD_STRIP.sub('', root).strip()
    root = re.sub(r'\s*\bFUT(?:URES)?\b\s*', '', root).strip()
    if not root or not _is_symbol(root.split()[0]):
        return None
    return {'trade': root, 'direction': 'BUY' if side == 'BUY' else 'SELL',
            'entry': _f(m.group(3)), 'target': _f(m.group(6)),
            'stop_loss': _f(m.group(5)), 'status': 'Open'}


def _hari_cash_signal(text):
    """LIVELONG HARI's dominant CASH-order shape: the ticker sits alone on
    its own line (often after an "EQUITY INTRADAY" header line), then the
    next paragraph gives the entry as "BUY/SELL ABV/RANGE/ABOVE/BELOW/AT
    <price>[-<price>]", e.g. "PAYTM\n\nBUY ABV 1590-91\n\nSL 1580\n\nTARGET
    1600,1610++", "EQUITY INTRADAY\n\nWOCKPHARMA \n\nBUY RANGE 2200-05\n\n
    SL 2150\n\nTarget 2220,2250+". "ABV"/"RANGE" are in STOP_WORDS so the
    generic RE_VERB_FIRST/RE_CASH steps can no longer misread them as a
    phantom ticker -- this recovers the REAL ticker by walking back to the
    nearest non-blank line above the trigger. Skipped when an option leg
    (CE/PE) already sits earlier in the message: that shape is handled by
    RE_OPT's own ABOVE_BELOW/RANGE fallbacks, not this one -- prevents this
    from double-counting an option order as a second, bare-symbol cash
    trade. SL/target are deliberately left blank here; the shared
    message-level RE_SUPPORT/RE_TARGET fallback (further down in
    parse_message) fills them from the same message's SL/TARGET lines.
    """
    m = RE_HARI_ENTRY_TRIGGER.search(text)
    if not m:
        return None
    if re.search(r'\b(?:CE|PE)\b', text[:m.start()], re.IGNORECASE):
        return None
    for line in reversed(text[:m.start()].splitlines()):
        # a multi-word line ("POSITIONAL TRADE", "EQUITY INTRADAY") is
        # never this channel's bare single-token ticker (WOCKPHARMA,
        # DATAPATTNS, PAYTM, ABB, ...) -- collapsing it into one blob by
        # stripping the internal space would dodge the STOP_WORDS check
        # (e.g. "POSITIONAL TRADE" -> "POSITIONALTRADE", neither word of
        # which is literally in STOP_WORDS even though "POSITIONAL" is) and
        # mint a phantom ticker out of a header/reminder line that names no
        # symbol at all, as Stockpro Online's "POSITIONAL TRADE\nBuy above
        # 400 incase missed it" did before this check was added. Bail
        # entirely rather than guess past it — the nearest non-blank line
        # not being a bare ticker means this message doesn't restate one.
        raw = line.strip()
        if not raw:
            continue
        if re.search(r'\s', raw):
            return None
        tok = re.sub(r'[^\w&\-]', '', raw.upper())
        if not tok:
            continue
        if not _is_symbol(tok):
            return None
        return {'trade': tok, 'direction': m.group(1).upper(),
                'entry': _f(m.group(2)), 'target': None,
                'stop_loss': None, 'status': 'Open'}
    return None


# Usha's Analysis's dominant live cash-equity entry: bare ticker, "AT", the
# entry price, then a TARGET line a few lines later, e.g. "SHORT TERM
# EQUITY\n\nQUADFUTURE AT 485\n\nTARGET 520,544+\n\nSTOP LOSS TO PREMIUM",
# "PENNY STOCK\n\nMAHABANK AT 85\n\nTARGET 90,95,100+\n\nSTOP LOSS TO
# PREMIUM". Deliberately case-SENSITIVE (unlike most of this file's other
# cash-entry regexes) so it can't fire on ordinary lower/mixed-case English
# "<word> at <price>" prose in another channel's message -- checked
# empirically that relaxing it to IGNORECASE picks up false positives like
# "shares at 3970.00" (Angel One Research) and "lots at 15.30" (Nirmal Bang
# Official) elsewhere in the 'mixed'-style corpus. The TARGET lookahead
# (within 3 lines) is the second guard: it's still needed even
# case-sensitive, since Nirmal Bang Official's own multi-leg combo orders
# contain the fragment "...CE AT 192-188 SL BELOW 170 TARGET 220-230" where
# "CE" reads as a plausible bare symbol -- excluded explicitly below.
RE_USHA_AT_ENTRY = re.compile(
    r'\b([A-Z][A-Z0-9&\-]{1,20})\s+AT\s+(\d[\d,]*(?:\.\d+)?)'
    r'(?:[^\n]*\n+){0,3}?\s*TARGET')


def _usha_at_entry_signal(text):
    m = RE_USHA_AT_ENTRY.search(text)
    if not m:
        return None
    root = m.group(1)
    if root in ('CE', 'PE') or not _is_symbol(root):
        return None
    return {'trade': root, 'direction': 'BUY', 'entry': _f(m.group(2)),
            'target': None, 'stop_loss': None, 'status': 'Open'}


# Usha's Analysis's OTHER live entry keyword: the ticker (optionally with a
# trailing "<MONTH> FUTURES"/"<MONTH> FUT" expiry suffix, for its futures
# calls) sits alone on the line above "[BUY ]AROUND <price>", e.g. "SHORT
# TERM EQUITY\n\nQUESS\n\nBUY AROUND 347\n\nTARGET 380,410+", "SHORT TERM\n\n
# MPHASIS AUG FUTURES \n\nAROUND 2515\n\nTARGET 2550,2600+". Anchored to the
# start of its own line, same false-positive reasoning as
# RE_HARI_ENTRY_TRIGGER above (an "AROUND" appearing mid-sentence after some
# other word must not have that word misread as the ticker).
RE_USHA_AROUND_ENTRY = re.compile(
    r'^\s*(?:BUY\s+)?AROUND\s*[:\-]?\s*' + NUM, re.IGNORECASE | re.MULTILINE)
RE_USHA_FUTURES_SUFFIX = re.compile(
    r'\s+(?:' + MONTH_ABBR + r')[A-Z]*\s+(?:FUTURES?|FUT)\.?$', re.IGNORECASE)


def _usha_around_entry_signal(text):
    m = RE_USHA_AROUND_ENTRY.search(text)
    if not m:
        return None
    for line in reversed(text[:m.start()].splitlines()):
        raw = line.strip()
        if not raw:
            continue
        raw = RE_USHA_FUTURES_SUFFIX.sub('', raw.upper()).strip()
        if re.search(r'\s', raw):
            return None
        tok = re.sub(r'[^\w&\-]', '', raw)
        if not tok:
            continue
        if not _is_symbol(tok):
            return None
        return {'trade': tok, 'direction': 'BUY', 'entry': _f(m.group(1)),
                'target': None, 'stop_loss': None, 'status': 'Open'}
    return None


# Momentum Trades' dominant real-signal shape, found by checking coverage
# on the full 1678-message tracked history (0 trades existed beforehand --
# this channel is mostly sarcastic Hinglish commentary/banter with a
# genuine one-shot entry->target call sitting in single, terse lines):
# "Graphite 604 to 617", "Skipper 560 to 577", "Ifci 82 to 87",
# "Kei 4741 to 4900" (single-word symbol, capitalized-only-first-letter,
# directly followed by "N to M" on the SAME line), or the symbol alone on
# its own line with the price pair on the next ("Aeroflex\n\n470 to 511").
# Deliberately narrow: a bare single capitalized word is otherwise a huge
# false-positive surface in a chatty channel like this one ("For me the
# range 22000 to 22200...", "Mark Minervini Position Sizing...", "Tariff
# reduced from 25% to 18%"), so this requires the word to sit IMMEDIATELY
# against the number (no verb/preposition between), rejects the index
# roots (this channel also posts "Nifty 22800 to 23800 zones" broad-market
# commentary, not a single-stock call), and reuses the shared _is_symbol/
# STOP_WORDS deny check. The many undated "NNN to MMM" progress-update
# reposts of the SAME running trade with no symbol restated ("813 to 845",
# then "813 to 870", "813 to 900"...) never match at all since there is no
# capitalized word to anchor on -- exactly the desired behavior, since
# re-parsing each update as a fresh trade would be a phantom-duplicate bug.
# Style-gated to 'cash'; verified empirically against every other 'cash'-
# style channel's full history (24 Motilal Oswal, 25 Mystocks.in, 47 Short
# To Mid Term, 60 Swing Trader Vishal, 61 Systematix Group Official): 0
# false-positive matches after excluding the index roots and a small
# prose-word deny set.
RE_MOMENTUM_SAMELINE = re.compile(
    r'^([A-Z][A-Za-z]{2,15})\s+(\d[\d,]*(?:\.\d+)?)\s+to\s+(\d[\d,]*(?:\.\d+)?)',
    re.MULTILINE)
RE_MOMENTUM_NEXTLINE = re.compile(
    r'^([A-Z][A-Za-z]{2,15})[ \t]*\r?\n[ \t]*\r?\n?[ \t]*'
    r'(\d[\d,]*(?:\.\d+)?)\s+to\s+(\d[\d,]*(?:\.\d+)?)', re.MULTILINE)
MOMENTUM_DENY = {'FROM', 'FOR', 'THE', 'RANGE', 'TODAY', 'TARGET', 'SUPPORT',
                 'AGAIN', 'TRADE', 'CMP', 'NEAR', 'AREA', 'EXPECTED', 'COMING'}


# Equity99's dominant "Special Situation Stock" / "Special day pick" /
# "Investment Pick" pick-of-the-day shape, found by checking coverage on the
# full 1700-message tracked history (only 3 phantom trades existed
# beforehand -- torn out of promo prose by the generic fallbacks). The
# multi-word company name sits alone on its own line immediately followed
# by "Cmp"/"At" and the current price, e.g. "Rudra Global Infra Cmp 24",
# "Univastu India Cmp 127", "RTN Power Cmp 10 / 11", optionally with a BSE
# scrip code in between ("Rudra Global Infra BSE Code 539226 At 37"); the
# resistance/target ladder follows a paragraph or two later as
# "Test Resistance 47 / 53" (first number kept as the target, same "never
# average a ladder" convention as the other multi-target shapes in this
# file) and an optional "Sl <price>" a few lines after that, which the
# existing message-level RE_SUPPORT fallback already attaches generically
# (verified: "SL\b" fires on "Sl 300"/"Sl 7"/"Sl 40" case-insensitively).
# Style-gated to 'cash'; verified empirically 0 false-positive matches on
# every other 'cash'-style channel's full history (22 Momentum Trades, 24
# Motilal Oswal, 25 Mystocks.in, 47 Short To Mid Term, 60 Swing Trader
# Vishal, 61 Systematix Group Official) -- deliberately NOT style-gated to
# 'mixed' even though that would also cover this channel, because the same
# entry regex produces real false positives across several 'mixed' channels
# ("ON RADAR"/"SL HIT BOOK"/"NET PROFIT"/"GOLD" all match "<word(s)> At/Cmp
# <num>" incidentally in prose or results digests -- checked empirically
# across all 19 'mixed' channels before rejecting that gate).
EQUITY99_SYMWORD = r"(?!(?:At|Cmp)\b)(?i:[A-Za-z][A-Za-z]{1,20})"
RE_EQUITY99_ENTRY = re.compile(
    r'^([A-Z][A-Za-z]{1,20}(?:[ \t]+' + EQUITY99_SYMWORD + r'){0,3})'
    r'[ \t]*(?:BSE[ \t]+Code[ \t]+\d+[ \t]+)?(?:At|(?i:Cmp))\s*[:.]?\s*(\d[\d,]*(?:\.\d+)?)',
    re.MULTILINE)
RE_EQUITY99_TARGET = re.compile(
    r'Test\s+Resistance\s*[:.]?\s*(\d[\d,]*(?:\.\d+)?)', re.IGNORECASE)


def _equity99_special_signal(text):
    # require the "Test Resistance" anchor phrase to co-occur in the SAME
    # message -- without it, the bare "<Words> At/Cmp <price>" entry shape
    # alone is a large false-positive surface (verified empirically: it
    # matches incidental prose like "BUY HINDCOPPER ... AT 55" or "NET
    # PROFIT ... AT ..." across several other channels' results digests).
    # Requiring "Test Resistance" too narrows this to 0 matches on every
    # OTHER channel across the full 82-channel corpus -- this shape is
    # unique to Equity99.
    if not RE_EQUITY99_TARGET.search(text):
        return None
    m = RE_EQUITY99_ENTRY.search(text)
    if not m:
        return None
    sym = re.sub(r'\s+', ' ', m.group(1).strip()).upper()
    if not sym or sym.split()[0] in INDEX_ROOTS or not _is_symbol(sym):
        return None
    tm = RE_EQUITY99_TARGET.search(text)
    return {'trade': sym, 'direction': 'BUY', 'entry': _f(m.group(2)),
            'target': _f(tm.group(1)), 'stop_loss': None, 'status': 'Open'}


def _momentum_word_to_word_signal(text):
    for rx in (RE_MOMENTUM_SAMELINE, RE_MOMENTUM_NEXTLINE):
        m = rx.search(text)
        if not m:
            continue
        sym = m.group(1).upper()
        if sym in INDEX_ROOTS or sym in MOMENTUM_DENY or not _is_symbol(sym):
            continue
        entry_v, target_v = _f(m.group(2)), _f(m.group(3))
        return {'trade': sym, 'direction': 'BUY' if target_v >= entry_v else 'SELL',
                'entry': entry_v, 'target': target_v, 'stop_loss': None,
                'status': 'Open'}
    return None


# promotional / PR / news posts that are never a trade signal (req 1.c)
PROMO = re.compile(
    r'\b(offer\b|offers\b|opens here|valid for first|slots only|join\b|'
    r'joining link|combo pack|'
    r'\bipo\b|price band|apply now|listing|registration|batch|coaching|course|'
    r'cues for next week|news\b|breaking|read more|details below|'
    r'book your slot|limited seats|new batch|mentorship|follow us|'
    r'share this|forwarded|webinar|subscribe)\b', re.IGNORECASE)
TRADE_VERB = re.compile(
    r'\b(BUY|SELL|LONG|SHORT|ABOVE|BELOW|BREAKOUT|CE|PE|CALL|PUT)\b', re.IGNORECASE)
# Usha's Analysis's subscription-combo-pack spam uses "BUY" as an ordinary
# subscription verb ("BUY 1 MONTH GET 2 FREE", "BUY 3 MONTHS GET 4 MONTHS
# FREE"), which otherwise defeats is_promo()'s TRADE_VERB override -- a
# message that is ENTIRELY this pricing template plus a PROMO hit (join
# link, "SPECIAL OFFER'S", etc) has no OTHER real trade verb, so this
# specific "BUY" usage is stripped out before the TRADE_VERB check runs.
RE_SUBSCRIPTION_BUY = re.compile(
    r'\bBUY\s+\d+\s+MONTHS?\s+GET\s+\d+\s*(?:MONTHS?\s*)?FREE\b', re.IGNORECASE)


def is_promo(text):
    if not text or not PROMO.search(text):
        return False
    return not TRADE_VERB.search(RE_SUBSCRIPTION_BUY.sub('', text))


def parse_message(text, style=None):
    """Return a list of signal dicts parsed from one message (possibly [])."""
    if not text or not text.strip():
        return []
    if style == 'promo' or is_promo(text):
        return []
    if RE_OPT_BARE_PRICE_REPOST.match(text.strip()) or RE_OPT_BARE_PRICE_REPOST_REV.match(text.strip()):
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

    # -1. STOCK MARKET SCHOOL's "<INDEX> <DAY> <MON> <STRIKE> CE/PE" option
    # header (see comment above RE_SMS_OPT_DATE/RE_SMS_RANGE_ENTRY) -- must
    # run before RE_OPT below so the real ticker is claimed first. Style-
    # gated to 'options'.
    if style == 'options':
        for m in RE_SMS_OPT_DATE.finditer(text):
            root = m.group(1).upper()
            strike, right = m.group(2).replace(',', ''), m.group(3).upper()
            right = {'CALL': 'CE', 'PUT': 'PE'}.get(right, right)
            trade = f'{root} {strike} {right}'
            option_roots.add(root)
            claimed_spans.append(m.span())
            if any(o['trade'] == trade for o in out):
                continue
            rm = RE_SMS_RANGE_ENTRY.search(text[m.end():m.end() + 60])
            # Stock Gainers' (48) and ROCHIT SINGH STOCKS' (40) shared
            # variant of this same "<INDEX> <DAY> <MON> <STRIKE> CE/PE"
            # header uses "ABOVE :- <price>" as its entry trigger instead
            # of "Range @ <price>" -- same header shape, different keyword.
            # Tried only after RE_SMS_RANGE_ENTRY so STOCK MARKET SCHOOL's
            # own "Range" convention is untouched. Without this, the real
            # entry message was invisible to every regex in this file (the
            # date infix breaks RE_OPT's root match, and this whole -1
            # block requires style=='options' with a matched entry to emit
            # anything) while a LATER reversed-order recap of the same
            # leg with no date token ("145\n\nNIFTY 23550 PE") DID match
            # plain RE_OPT below with no entry, producing a blank-valued
            # phantom trade instead of the real, priced one.
            ab = rm or RE_ABOVE_BELOW.search(text[m.end():m.end() + 60])
            if not ab:
                continue
            add({'trade': trade, 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                 'entry': _f(ab.group(1)), 'target': None, 'stop_loss': None, 'status': 'Open'})

    # 0. Usha's Analysis's "<TICKER> <MONTH> <STRIKE> CE/PE" option header
    # (see comment above RE_TICKER_MONTH_OPT) -- must run before RE_OPT
    # below so the real ticker is claimed first.
    if style == 'mixed':
        for m in RE_TICKER_MONTH_OPT.finditer(text):
            root = m.group(1).upper()
            if not _is_symbol(root):
                continue
            # same close-out exclusion as the main RE_OPT loop below --
            # without it, "EXIT FROM NIFYU APR 23250 CE @ 2.8" and "BOOK
            # PROFIT IN HINDALCO MAR 680 CE AT 14" (Angel One Research, also
            # 'mixed'-style) get misread as a fresh order instead of the
            # close-out they are.
            if any(s[0] < m.end() and s[1] > m.start() for s in exit_price_spans):
                continue
            # Samco's "Exit at <price> in <SYMBOL> <MONTH> <STRIKE>CE" close
            # -out (word order: price BEFORE the symbol, "at"/"in" instead
            # of "@") isn't covered by RE_EXIT_PRICE/RE_EXIT_PRICE_BOOK
            # above (both expect "<SYMBOL> @ <price>" or "IN <SYMBOL> @
            # <price>", price after the symbol) -- a literal "EXIT" word
            # anywhere earlier in the same message is a cheap, conservative
            # guard against reading this channel's own close-out as a fresh
            # order; verified this never suppresses a genuine Usha's
            # Analysis / Stockizen Research entry (neither channel's
            # tracked history uses the word "EXIT" on an entry message).
            if re.search(r'\bEXIT\b', text[:m.start()], re.IGNORECASE):
                continue
            strike, right = m.group(2).replace(',', ''), m.group(3).upper()
            trade = f'{root} {strike} {right}'
            option_roots.add(root)
            claimed_spans.append(m.span())
            if any(o['trade'] == trade for o in out):
                continue
            entry = None
            tail = text[m.end():m.end() + 20]
            am = re.match(r'\s*[\s:,@]*' + NUM, tail)
            if am:
                entry = _f(am.group(1))
            add({'trade': trade,
                 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                 'entry': entry, 'target': None, 'stop_loss': None,
                 'status': 'Open'})

    # 1. options: "BANKNIFTY 57000 PE @ 505", "SENSEX 73,900 PE"
    for m in RE_OPT.finditer(text):
        root, right, prem = m.group(1).strip().upper(), m.group(2).upper(), m.group(3)
        # CHANNEL-AGNOSTIC BUG: an expiry date written "24-SEP-2026" right
        # after the strike+CE/PE (MARKET MASTER HUB's dominant shape, "BUY
        # #JIOFIN 270 CE 24-SEP-2026 AT 5.7") gets its leading DAY number
        # ("24") read by this regex's own optional trailing NUM as if it
        # were the premium -- entry became a constant "24" (or "8", "28",
        # ...) on hundreds of DIFFERENT option legs regardless of their
        # real stated price, silently discarding the real "AT 5.7"/"AT 20"
        # a few words later. Verified empirically unique to this channel
        # across the full 82-channel corpus (420 occurrences, channel 19
        # only) -- drop the false premium here so the later "AT <price>"
        # fallback further down in this loop gets a chance to fill the
        # real one instead.
        if prem and re.match(r'\s*-[A-Za-z]{3}-\d{4}', text[m.end(3):]):
            date_tail = text[m.end(3):m.end(3) + 40]
            at_m = re.match(r'\s*-[A-Za-z]{3}-\d{4}\s+AT\s+' + NUM, date_tail, re.IGNORECASE)
            prem = at_m.group(1) if at_m else None
        root = re.sub(r'\s+', ' ', root).replace(',', '').replace('_', ' ')
        root = re.sub(r'\s+', ' ', root).strip()
        root_word = root.split()[0] if root.split() else root
        if root_word in STOP_WORDS:
            continue
        # a "root" that is literally a 3-letter month abbreviation glued to
        # digits ("APR12275", "JUL13025") is never a real ticker -- it is
        # this regex misreading a compact "<ROOT><DDMMM><STRIKE>CE/PE"
        # option symbol (Samco's dominant options format, e.g.
        # "NIFTY25APR12275CE") from the middle: [A-Z]+ can't bridge the
        # digit-then-letter gap between the root and the DDMMM expiry
        # token, so it backtracks onto the expiry token's own month letters
        # as if THEY were the root, producing a phantom all-blank trade
        # (no entry/target/SL ever fills in, since none of that data is
        # attributed to a fake "APR" ticker). Verified empirically this
        # never rejects a real match elsewhere: no genuine ticker in the
        # tracked corpus is a bare month abbreviation immediately followed
        # by a digit.
        if re.match(r'^(?:' + MONTH_ABBR + r')(?:\d.*)?$', root_word):
            continue
        # same trap as the 3-letter case just above, but with the FULL
        # month word instead of its abbreviation ("JUNE", not "JUN") --
        # Usha's Analysis's dominant option-leg header names the underlying
        # AND the expiry month as two separate space-separated words before
        # the strike, e.g. "BHARATFORG JUNE 1900 CE": RE_OPT's `[A-Z]+`
        # can't bridge "BHARATFORG " (letters-space-letters) so it starts
        # matching at "JUNE" instead, silently dropping the real ticker and
        # creating a phantom "JUNE 1900 CE"/"JULY 1900 CE" row that
        # collapses many different underlyings into the same fake symbol.
        # The real ticker is recovered by _usha_month_option_signal below
        # (style-gated to 'mixed'); this bare check is the channel-agnostic
        # safety net for every OTHER channel, where "no trade" beats a
        # wrong one. Verified empirically no genuine ticker anywhere in the
        # 82-channel corpus is spelled out as a full month name.
        if re.match(r'^(?:JANUARY|FEBRUARY|MARCH|APRIL|MAY|JUNE|JULY|AUGUST|'
                     r'SEPTEMBER|OCTOBER|NOVEMBER|DECEMBER)$', root_word):
            continue
        # a >6-digit trailing digit run is never a real strike (even the
        # highest index strikes are at most 6 figures) -- it is Samco's
        # weekly-numeric-expiry option symbol with NO letter month code at
        # all ("NIFTY2540323300CE": year+week+strike all run together),
        # which this regex's simple root+digits+CE/PE shape reads whole as
        # if the entire run were the strike. Left to _samco_block_signal's
        # dedicated parser (which reads the real CMP/SL/Target from the
        # structured field block instead of trying to split this digit
        # run), rather than emitting a second, blank-valued phantom row
        # under a differently-spaced trade key that the (channel, trade,
        # entry) dedup can't merge with the real one. Verified empirically
        # unique to this channel across the full 82-channel tracked
        # history (58 occurrences, all channel 43).
        digit_run = re.search(r'\d+$', root_word)
        if digit_run and len(digit_run.group()) > 6:
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
        # 20PAISA..COM's no-price closure recap leg (see RE_OPT_NO_PRICE_CLOSE
        # comment) -- skip this leg entirely rather than let the shared
        # message-level entry fallback stamp it with an unrelated leg's price.
        if entry is None and RE_OPT_NO_PRICE_CLOSE.match(text[m.end():m.end() + 30]):
            continue
        sig = {'trade': f'{root} {right}',
               'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
               'entry': entry, 'target': None, 'stop_loss': None, 'status': 'Open'}
        # "ABOVE 190-200" / "ABOVE 10" entry trigger right after the strike
        # (checked before the bare dash-range fallback below, since NUM stops
        # at the first non-digit and so already handles a trailing "-200")
        if entry is None:
            # search a wider slice than the 20-char "nearby" budget below
            # implies, but only ACCEPT a match whose ABOVE/BELOW keyword
            # itself starts within that budget -- the keyword must be near
            # the strike, but its price shouldn't be truncated just because
            # an expiry annotation ("SEP 2026") sits between them and pads
            # out the gap, e.g. Sairam Stocks' "BANKNIFTY 55500 CALL SEP
            # 2026\nBUY ABOVE 1070 LEVEL ONLY" -- a plain 20-char slice cuts
            # "1070" down to "1" (the digits after the window boundary are
            # invisible to the search), producing a nonsense sub-₹1 entry
            # instead of leaving it for the wider 'options'-style fallback
            # near the end of this loop -- which never got a chance to run
            # because THIS narrower check had already set sig['entry'] to
            # the wrong truncated value.
            ab = RE_ABOVE_BELOW.search(text[m.end():m.end() + 60])
            # "SL BELOW <price>" / "STOP LOSS BELOW <price>" right before
            # the match is a stop-loss threshold, not an entry trigger --
            # without this, Nirmal Bang Official's "Option BUY CRUDE 7850CE
            # BR 370-350 SL BELOW 280 TGT 450-480" (which never uses the
            # word ABOVE/BELOW for its OWN entry -- that's the unlabelled
            # "BR 370-350" range a few lines down) now reaches "BELOW 280"
            # within the widened 60-char budget above and misreads the stop
            # -loss figure as if it were the entry.
            near = text[m.end():m.end() + ab.start()] if ab else ''
            if ab and ab.start() < 20 and not re.search(r'\bSL\b|\bSTOP\s*LOSS\b', near[-6:], re.IGNORECASE):
                sig['entry'] = _f(ab.group(1))
        # "NEAR <price>" entry trigger right after the strike -- Trading
        # With Ca Abhay's and ROCHIT SINGH STOCKS' dominant entry shape,
        # "SENSEX 78100 PE\n\nNEAR 330\n\nTGT open\n\nSl follow",
        # "NIFTY 24100 CE\n\nNear 140\n\nTGT open\n\nSl follow" -- NOT
        # folded into RE_ABOVE_BELOW itself: that regex's OTHER use site
        # (a few lines below, searching to the end of the message with no
        # window limit) would then pick up completely unrelated "Support
        # near <price>"/"trading near <price>" market commentary dozens of
        # lines later in other channels' messages as if it were an entry
        # trigger. Kept in its own tightly-windowed (<20 chars, right after
        # the strike) check instead, mirroring the ABOVE/BELOW one just
        # above. Verified empirically unique to channels 66/40 within this
        # narrow window across the full 82-channel corpus -- "NEAR" is
        # common prose elsewhere (Ritvi Taneja, Nasdaq masters, PL
        # Technical Research, ...) but never sits directly after a
        # strike+CE/PE token in any OTHER channel.
        if sig['entry'] is None:
            nr = RE_NEAR_ENTRY.search(text[m.end():m.end() + 20])
            if nr:
                sig['entry'] = _f(nr.group(1))
        # Richie by Chase Alpha's dominant option-order shape: "NIFTY 19500
        # CE CMP 215 add till 210 SL 170 Target 260-280-300", "BANKNIFTY
        # 47600 PE CMP 40 Hero Zero" — bare "CMP <price>" immediately after
        # the strike+right, with no parenthetical expiry between them
        # (unlike Ashika Calls' RE_OPT_PAREN_CMP just below, which requires
        # one). Style-gated to 'options' (this channel's own style) rather
        # than 'mixed': checked empirically that gating to 'mixed' instead
        # collides with two OTHER mixed-style channels' shared shapes on
        # this same channel's text once its style is switched to 'mixed'
        # -- Trading Ideas By Darshan's RE_DARSHAN_RECAP (a bare "<free
        # text> from N to M" pattern with no ticker restriction on the
        # free text) turns "BANK NIFTY 59000 CE on App from 18 to 150"
        # into a phantom "BANK NIFTY 59000 CE ON APP" trade, and
        # 𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒's RE_FINSARTHI_OPT (also 'mixed'-gated) creates a
        # second, differently-named "BANK NIFTY 45500 CE" row once this
        # CMP fallback fills the entry on the already-added truncated
        # "NIFTY 45500 CE" placeholder RE_OPT produces beforehand (that
        # placeholder's entry used to stay blank, which is what let the
        # existing Finsarthi dedup below silently absorb it — see the
        # comment there). 'options' avoids both collisions; this channel's
        # own text has no use for either 'mixed'-gated shape. Checked
        # before the bare dash-range fallback below for the same reason as
        # the Ashika block (a trailing "-15" in "CMP 210-15" would
        # otherwise get misread as a target by that fallback instead of
        # correctly leaving target blank here). Left OFF the exit-side
        # "BOOK PARTIAL PROFIT IN <SYM> CMP <price>" close-out shape
        # (Ashika Calls' own dominant close-out, see RE_CLOSE_EVENT)
        # because that phrase never occurs anywhere in this channel's
        # tracked history (verified empirically, 0 occurrences) — unlike
        # Ashika, whose own 'mixed' style already excludes those spans via
        # `exit_price_spans` before this fallback ever runs.
        if entry is None and sig['entry'] is None:
            cm = re.match(r'^\s*CMP\s*[:\-]?\s*' + NUM, text[m.end():m.end() + 20], re.IGNORECASE)
            if style == 'options' and cm:
                sig['entry'] = _f(cm.group(1))
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
                # a second number with FEWER digits than the first is not a
                # target -- it's an entry BAND written in shorthand, only
                # the trailing digits given ("262-65" means 262 to 265,
                # "2200-05" means 2200 to 2205), e.g. LIVELONG HARI's "BUY
                # abv 262-65\n\nSL 240\n\nTARGET 280,300+". Leave target
                # unset here so the message's own TARGET/TGT line fills it
                # via the shared message-level fallback further down,
                # instead of this shorthand band tail being misread as the
                # real target (was landing target=65 on a 262-entry PE
                # whose real target, from the TARGET line, is 280).
                # Checked empirically against the rest of the 82-channel
                # corpus: every OTHER channel's use of this fallback has a
                # second number with equal-or-more digits than the first
                # (a genuine ascending entry-target range like "250-320"),
                # so this guard only ever changes LIVELONG HARI's shorthand
                # shape.
                if len(rng.group(2)) >= len(rng.group(1)):
                    sig['target'] = _f(rng.group(2))
        # Bharath's Market Research's dominant "<ROOT> <STRIKE>CE/PE ...
        # Series\n\nBUY RANGE - <high>/<low>\n\nSL <price>" ladder (also
        # used, with the same "/"-separated range, by STOCK MARKET SCHOOL) —
        # found by checking coverage on the full tracked history: 313 of
        # 410 pre-existing trades had entry=None because the generic
        # dash-range fallback above (RE_RANGE) only recognizes a "-"-
        # separated pair immediately after the strike, and this channel's
        # own range separator is "/", arriving a few words later ("Sep
        # Series"/"JUNE SERIES" sits in between) — up to 21 characters away
        # in the tracked corpus, comfortably inside this fallback's 60-char
        # budget. Takes the FIRST (higher, more conservative) number as the
        # entry, same "never average a ladder" convention as the dash-range
        # fallback right above; SL/TARGETS are left for the existing
        # message-level RE_SUPPORT/RE_TARGET fallback further down, which
        # already reads "SL <price>"/"Stoploss - <price>"/"TARGETS -
        # <price>" generically with no change needed here. Style-gated to
        # 'options'; verified empirically 0 effect on the other two
        # 'options'-style channels (MarketWolf, Stock Thunder) — every
        # "Buy Range"/"BUY RANGE" occurrence in their own tracked history
        # already has an entry filled in by an earlier fallback in this
        # same loop before this one gets a turn.
        if style == 'options' and entry is None and sig['entry'] is None:
            br = RE_OPT_BUY_RANGE.search(text[m.end():m.end() + 60])
            if br:
                sig['entry'] = _f(br.group(1))
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
        # a same-day recap restating "<price> to <price>+" right after the
        # strike, with NO SL/stop-loss wording anywhere else in the message,
        # is never a fresh entry -- it's a same-day repost of an ALREADY-
        # given call's running result (Bharath's Market Research / STOCK
        # MARKET SCHOOL's "<ROOT> <STRIKE> CE/PE SEP Series\n11.2 to
        # 13.5+\nTarget 1 Done & Dusted", no "Buy Range" this time). Without
        # this, the recap creates a second, blank-valued phantom Trade row
        # alongside the real entry (their (channel, trade, entry) upsert
        # keys differ -- None vs the real price -- so they can't merge).
        # Genuine first-time entries that also happen to state "<price> to
        # <price>" right after the strike (e.g. Stock Thunder's own
        # dominant shape) always state an SL *somewhere* in the same
        # message -- checked empirically across the whole 82-channel corpus:
        # this exact "no premium marker, recap number pair, no SL anywhere"
        # combination is 619/620 real entries for Stock Thunder (kept, SL
        # present) vs 51/52 genuine recaps for this channel (correctly
        # dropped, SL absent), with only a handful of stray one-two-message
        # cases elsewhere, so requiring SL's absence is what keeps this
        # channel-agnostic-safe rather than needing a style gate.
        if sig['entry'] is None:
            tail = text[m.end():m.end() + 60]
            if RE_OPT_RECAP_NO_ENTRY.search(tail) and not RE_SUPPORT.search(text):
                continue
        add(sig)

    # 1a. Ashika Calls' lower/mixed-case index option names (see comment
    # above RE_OPT_INDEX_CI) — style-gated to 'mixed'.
    if style == 'mixed':
        for m in RE_OPT_INDEX_CI.finditer(text):
            root = m.group(1).upper()
            strike = m.group(2).replace(',', '')
            # a >6-digit strike is never real -- see the matching guard
            # (and its comment) in RE_OPT's own loop above; this is the
            # same Samco weekly-numeric-expiry symbol
            # ("NIFTY2540323300CE") read whole by this case-insensitive
            # variant since it has no digit-length limit of its own.
            if len(strike.split('.')[0]) > 6:
                continue
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
            if RE_OPT_NO_PRICE_CLOSE.match(text[m.end():m.end() + 30]):
                continue
            entry = None
            target = None
            pc = RE_OPT_PAREN_CMP.match(text[m.end():m.end() + 40])
            if pc:
                entry = _f(pc.group(1))
            else:
                ttm = RE_OPT_ENTRY_TO_TARGET.match(text[m.end():m.end() + 60])
                if ttm:
                    entry = _f(ttm.group(1))
                    target = _f(ttm.group(2))
            add({'trade': trade,
                 'direction': 'CALL (up)' if right == 'CE' else 'PUT (down)',
                 'entry': entry, 'target': target, 'stop_loss': None, 'status': 'Open'})

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

    # 1g. Samco's "RECOMMENDATION ALERT" broker template -- both the
    # structured field block and the "Note: Buy ..." one-liner (see comment
    # above _samco_block_signal) -- style-gated to 'mixed'. Runs here,
    # BEFORE the generic verb-first/cash fallbacks (steps 3-5b below)
    # rather than alongside the other channel-specific shapes at step 6+,
    # because a spaced glued-expiry symbol in the Note line ("Buy AUBANK
    # 25DEC980PE at 10.5...") would otherwise already be mis-read by
    # RE_VERB_FIRST as a bogus cash order "AUBANK" @ 25 (the "25" of the
    # expiry token) before this ever gets a turn -- the same root-cause bug
    # documented at RE_OPT's own MONTH_ABBR/digit-length guards above, just
    # hitting the "Note:" line's plain verb-first shape instead of RE_OPT.
    # Claims the root (via option_roots) and the Note/Symbol span (via
    # claimed_spans) so those later fallbacks skip it entirely. Each of the
    # two parses checked independently against `out` so a message where
    # both fire on the same symbol only produces one signal.
    if style == 'mixed':
        for sig_fn in (_samco_block_signal, _samco_note_signal):
            csig = sig_fn(text)
            if csig and csig['trade'] not in option_roots and not any(
                    o['trade'] == csig['trade'] for o in out):
                add(csig)
                option_roots.add(csig['trade'].split()[0])
        if out and any(o['trade'] for o in out):
            nm = RE_SAMCO_NOTE_LINE.search(text)
            if nm:
                claimed_spans.append(nm.span())
            sm = RE_SAMCO_SYM_FIELD.search(text)
            if sm:
                claimed_spans.append(sm.span())

    # 1h. 𝐅𝐈𝐍𝐀𝐍𝐂𝐈𝐀𝐋 𝐒𝐀𝐑𝐓𝐇𝐈𝐒's lower/mixed-case option-order shape (see
    # comment above RE_FINSARTHI_OPT) -- style-gated to 'mixed'. Runs here
    # rather than at step 6+ for the same reason as Samco's Note line
    # above: claims the root via option_roots before the generic verb-
    # first/cash fallbacks below get a chance to misread the same text.
    # Step 1's RE_OPT, unconditional and case-sensitive-immune to this
    # multi-word root ("Bank nifty 55000 ce" -> RE_OPT already grabbed a
    # truncated "NIFTY 55000 CE" moments earlier, entry blank, from the
    # lowercase "nifty" alone since its root pattern can't span the
    # space), has ALREADY run by this point -- drop that truncated
    # placeholder in favor of this shape's full root rather than leaving
    # both a correct and a blank-duplicate row for the same strike/right.
    if style == 'mixed':
        fsig = _finsarthi_option_signal(text)
        if fsig and fsig['trade'] not in option_roots and not any(
                o['trade'] == fsig['trade'] for o in out):
            suffix = ' ' + ' '.join(fsig['trade'].split()[-2:])
            # a truncated placeholder for the SAME leg can have picked up
            # a real entry by now (e.g. Richie by Chase Alpha's "BANK
            # NIFTY 45500 CE CMP 360 ..." -- RE_OPT's own root capture
            # can't span the "BANK "/"NIFTY" word gap, so step 1 already
            # added a blank-root "NIFTY 45500 CE", and its CMP-inline
            # fallback fills that placeholder's entry from the SAME "CMP
            # 360" this shape also reads -- BEFORE this step ever runs).
            # Originally this only dropped placeholders whose entry was
            # still None, which silently left both rows once RE_OPT
            # started filling CMP entries (verified empirically: this
            # channel's "BANK NIFTY"/"BANK NIFTY" root split produced a
            # genuine duplicate pair, "NIFTY 45500 CE" + "BANK NIFTY 45500
            # CE", not the harmless same-key overlap the comment above
            # this function describes for Ashika Calls). Now unconditional
            # on entry, and carries a placeholder's entry over to fsig
            # when fsig's own AT/@ capture came up empty, rather than
            # discarding real data neither the correct row nor a stray
            # duplicate should lose.
            placeholders = [o for o in out if o['trade'] != fsig['trade'] and o['trade'].endswith(suffix)]
            if placeholders and fsig['entry'] is None:
                carried = next((p['entry'] for p in placeholders if p['entry'] is not None), None)
                if carried is not None:
                    fsig['entry'] = carried
            out[:] = [o for o in out if o not in placeholders]
            add(fsig)
            option_roots.add(fsig['trade'].split()[0])

    # 2. crypto futures: "ONDO LONG 20x"
    #
    # CHANNEL-AGNOSTIC BUG FOUND during the Stockizen Research sample
    # (channel 54): RE_CRYPTO's SYM is any bare ALL-CAPS word immediately
    # followed by LONG/SHORT -- it isn't restricted to known crypto
    # tickers, so ordinary prose like "WE WERE SHORT FROM MORNING!!"
    # matches with sym="WERE". The end-of-function cleanup that drops a
    # still-entry-less crypto match ("no confident match -> no trade") only
    # checks `asset_class == 'crypto'`, so a phantom match that classify()
    # calls 'stock'/'other'/'index' (anything that ISN'T a recognized
    # crypto ticker and has no nearby "<N>x" leverage marker) sailed
    # through as a permanent blank-entry Open row. Verified empirically
    # against the full 82-channel/tracked-history corpus: 196 such
    # matches, 38 distinct phony "symbols", every one an ordinary English
    # word next to LONG/SHORT as a verb/adjective (WERE, AFTER, AGAIN,
    # BIG, FIRST, LAST, NEXT, SECOND, TAKE, THIS, ...) or a macro noun
    # (NIFTY, SENSEX, GOLD, STEEL, INDEX, INDIA) used the same way ("Nifty
    # short term view") -- NONE of them a real trade. The two exceptions
    # in that same scan that DO carry a real stated entry price (Serezha
    # Calls' "CYBER LONG 20х" / "AEVO LONG 20х", genuine crypto
    # legs classify() simply doesn't recognize by ticker) are unaffected
    # by this fix, since it only drops the entry-less case -- a stock/
    # index/other-classified match never gets its entry filled by ANY
    # later step in this function either (only 'option'/'crypto' asset
    # classes get a message-level entry-price fallback below), so an
    # entry-less non-crypto match was always going to end up a permanent
    # blank-entry row; dropping it here is the same "no confident entry ->
    # no trade" convention already applied everywhere else in this file.
    for m in RE_CRYPTO.finditer(text):
        sym, side = m.group(1), m.group(2).upper()
        if not _is_symbol(sym):
            continue
        if any(o['trade'] == sym for o in out):
            continue
        ent = RE_ENTER.search(text)
        entry_v = _f(ent.group(1)) if ent else None
        if entry_v is None and classify(sym, 'BUY' if side == 'LONG' else 'SELL', text) != 'crypto':
            continue
        add({'trade': sym, 'direction': 'BUY' if side == 'LONG' else 'SELL',
             'entry': entry_v,
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

    # 6c. Stock Gainers (SEBI Registered)'s two dominant shapes (see comment
    # above RE_STOCKGAINERS_RECAP/RE_STOCKGAINERS_ENTRY) -- style-gated to
    # 'mixed'. Only runs if nothing above already matched this symbol
    # (e.g. Stocky Mind's own RE_STOCKY_RECAP at 6a fires on the exact same
    # "SYMBOL\n\nN to M" shape for its own channel -- verified empirically
    # that the only other 'mixed' channel these two patterns match anything
    # on at all is Stocky Mind, and there only on messages RE_STOCKY_RECAP
    # already claimed, so the dedup check below is what keeps this
    # channel-agnostic-safe rather than the style gate alone).
    if style == 'mixed':
        m = RE_STOCKGAINERS_ENTRY.search(text)
        if m:
            sym = re.sub(r'\s+', ' ', m.group(1).strip()).upper()
            if (_is_symbol(sym.split()[0]) and sym.split()[0] not in STOCKGAINERS_DENY
                    and tuple(sym.split()[-2:]) not in STOCKGAINERS_TRAILING_DENY
                    and sym not in option_roots and not any(o['trade'] == sym for o in out)):
                add({'trade': sym, 'direction': 'BUY', 'entry': _f(m.group(2)),
                     'target': _f(m.group(4)), 'stop_loss': _f(m.group(3)),
                     'status': 'Open'})
        m = RE_STOCKGAINERS_RECAP.search(text)
        if m:
            sym = re.sub(r'\s+', ' ', m.group(1).strip()).upper()
            if (_is_symbol(sym.split()[0]) and sym.split()[0] not in STOCKGAINERS_DENY
                    and tuple(sym.split()[-2:]) not in STOCKGAINERS_TRAILING_DENY
                    and sym not in option_roots and not any(o['trade'] == sym for o in out)):
                entry_v, exit_v = _f(m.group(2)), _f(m.group(3))
                add({'trade': sym, 'direction': 'BUY' if exit_v >= entry_v else 'SELL',
                     'entry': entry_v, 'target': exit_v, 'stop_loss': None,
                     'status': 'Open'})

    # 6d. Nivisha Verma (Bnf_unicorn)'s "✅"-bulleted breakout-call shape
    # (see comment above _bnfunicorn_bullet_signal) — style-gated to
    # 'mixed'.
    if style == 'mixed':
        bsig = _bnfunicorn_bullet_signal(text)
        if bsig and bsig['trade'] not in option_roots and not any(
                o['trade'] == bsig['trade'] for o in out):
            add(bsig)

    # 6e. Ritvi Taneja's "<SYMBOL> <PRICE>" first-line + support shape (see
    # comment above _symline_support_signal) — style-gated to 'mixed'.
    if style == 'mixed':
        ssig = _symline_support_signal(text)
        if ssig and ssig['trade'] not in option_roots and not any(
                o['trade'] == ssig['trade'] for o in out):
            add(ssig)

    # 6f. Trading Ideas By Darshan's option-entry and recap shapes (see
    # comment above _darshan_option_entry_signal/_darshan_recap_signal) —
    # style-gated to 'mixed'. An option leg stated as "Nifty 24150 Ce\n
    # From 113 to 227" (no "@"/premium marker right after "Ce") is ALSO
    # matched by step 1's generic RE_OPT with entry=None (that step runs
    # unconditionally, before any style-specific shape gets a turn, and
    # doesn't consult `out`) — rather than silently losing the real entry/
    # target this shape states, patch that blank placeholder in place
    # instead of skipping when one is already sitting in `out`.
    if style == 'mixed':
        for sig_fn in (_darshan_option_entry_signal, _darshan_recap_signal):
            dsig = sig_fn(text)
            if not dsig or dsig['trade'] in option_roots:
                continue
            existing = next((o for o in out if o['trade'] == dsig['trade']), None)
            if existing is None:
                add(dsig)
            elif existing['entry'] is None and dsig['entry'] is not None:
                existing.update(entry=dsig['entry'], target=dsig['target'],
                                stop_loss=dsig['stop_loss'], direction=dsig['direction'])

    # 6g. 𝑵𝒂𝒔𝒅𝒂𝒒 𝒎𝒂𝒔𝒕𝒆𝒓𝒔's lower/mixed-case forex/gold BUY/SELL shape (see
    # comment above RE_NASDAQMASTERS_FX) — style-gated to 'mixed'. Only
    # adds if nothing above already produced this exact (trade, entry)
    # pair (the uppercase-only shape already covers about half this
    # channel's calls via the generic RE_VERB_FIRST/RE_BUYSELL).
    if style == 'mixed':
        nsig = _nasdaqmasters_fx_signal(text)
        if nsig and not any(o['trade'] == nsig['trade'] for o in out):
            add(nsig)

    # 6h. Finance With Sunil's two dominant shapes (see comment above
    # _finsunil_signal) -- style-gated to 'options' (NOT 'cash': this
    # channel's hashtags are frequently ALL-CAPS too, e.g. "#DIXON", "#BSE"
    # -- setting it to 'cash' would also switch on RE_STMT_RECAP/
    # RE_STMT_ENTRY/RE_VISHAL_BOUGHT, Short To Mid Term/Swing Trader
    # Vishal's own cash-recap patterns, which happily match this channel's
    # all-caps "#SYM <price> To <price>" option-leg restatements too and
    # mint the exact phantom bare-symbol duplicate the comment above
    # RE_FINSUNIL_OPT_RECAP describes -- verified empirically by first
    # trying 'cash' and observing duplicate bare "DIXON"/"BSE"/"MCX" rows
    # alongside the real "DIXON 11500 PE" etc. option rows). Each
    # sub-pattern below is additionally guarded on a literal label phrase
    # ("Strike-"/"Prime Members") verified empirically unique to this
    # channel, so the style gate alone isn't load-bearing.
    if style == 'options':
        fsig = _finsunil_signal(text)
        if fsig and fsig['trade'] not in option_roots and not any(
                o['trade'] == fsig['trade'] for o in out):
            add(fsig)

    # 6i. Stockizen Research's structured "POSITIONAL SWING TRADE" ladder
    # (see comment above _stockizen_swing_signal) -- style-gated to
    # 'mixed'; also guarded on the literal "POSITIONAL SWING TRADE" header
    # verified empirically unique to channel 54.
    if style == 'mixed':
        zsig = _stockizen_swing_signal(text)
        if zsig and zsig['trade'] not in option_roots and not any(
                o['trade'] == zsig['trade'] for o in out):
            add(zsig)

    # 6j. Systematix Group Official's two dominant shapes (see comments
    # above _systematix_cash_signal/_systematix_weekly_signal) -- style-
    # gated to 'cash'. A single-word root ("PIIND", "AUBANK", ...) is ALSO
    # visible to the generic RE_VERB_FIRST/RE_BUYSELL fallback that already
    # ran by this point in the function, but that generic path's own
    # message-level RE_TARGET/RE_SUPPORT fallback (further down, after
    # this step) mis-reads this channel's ranked "TGT 1)3575 2)3470"
    # target lists as target=1 (NUM stops at the ")" right after the rank
    # digit) -- this shape's own regex parses that correctly. So rather
    # than skip outright when the generic step already added this trade
    # (as every other per-channel shape in this file does), patch that
    # placeholder's entry/target/stop_loss from the more careful parse
    # here when the generic one is missing data or the same leg's entry
    # confirms it's the identical message.
    if style == 'cash':
        for sig_fn in (_systematix_cash_signal, _systematix_weekly_signal):
            csig = sig_fn(text)
            if not csig or csig['trade'] in option_roots:
                continue
            existing = next((o for o in out if o['trade'] == csig['trade']), None)
            if existing is None:
                add(csig)
            elif existing['entry'] == csig['entry']:
                existing.update(target=csig['target'], stop_loss=csig['stop_loss'],
                                 direction=csig['direction'])

    # 6k. LIVELONG HARI's ticker-on-its-own-line cash order (see comment
    # above _hari_cash_signal) -- style-gated to 'mixed'.
    if style == 'mixed':
        hsig = _hari_cash_signal(text)
        if hsig and hsig['trade'] not in option_roots and not any(
                o['trade'] == hsig['trade'] for o in out):
            add(hsig)

    # 6l. Usha's Analysis's "<TICKER> AT <price> ... TARGET ..." cash entry
    # (see comment above _usha_at_entry_signal) -- style-gated to 'mixed'.
    if style == 'mixed':
        usig = _usha_at_entry_signal(text)
        if usig and usig['trade'] not in option_roots and not any(
                o['trade'] == usig['trade'] for o in out):
            add(usig)

    # 6m. Usha's Analysis's "<TICKER>\n\n[BUY ]AROUND <price>" cash/futures
    # entry (see comment above _usha_around_entry_signal) -- style-gated to
    # 'mixed'.
    if style == 'mixed':
        asig = _usha_around_entry_signal(text)
        if asig and asig['trade'] not in option_roots and not any(
                o['trade'] == asig['trade'] for o in out):
            add(asig)

    # 6n. Momentum Trades' one-word-symbol "<Symbol> N to M" recap (see
    # comment above _momentum_word_to_word_signal) -- style-gated to 'cash'.
    if style == 'cash':
        msig = _momentum_word_to_word_signal(text)
        if msig and msig['trade'] not in option_roots and not any(
                o['trade'] == msig['trade'] for o in out):
            add(msig)

    # 6o. Equity99's "<Company Name> Cmp/At <price> ... Test Resistance
    # <price>" pick-of-the-day shape (see comment above
    # _equity99_special_signal) -- style-gated to 'cash'.
    if style == 'cash':
        esig = _equity99_special_signal(text)
        if esig and esig['trade'] not in option_roots and not any(
                o['trade'] == esig['trade'] for o in out):
            add(esig)

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
