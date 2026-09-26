"""LLM-assisted interpretation of ambiguous Telegram messages the regex
parser (signals.py) can't confidently handle -- e.g. a bare-number repost
that's actually the channel's final close price, phrased with no
recognizable close keyword (the "266" case: RAJESH PALVIYA/Day Trader-style
channels repost a running LTP with no "TARGET HIT"/"BOOKED" wording at all).

Also handles OPENS (interpret_open()) -- a message that clearly announces a
new trade in a shape the regex parser doesn't recognize. looks_like_possible_
open() is a cheap, LLM-free pre-filter (a digit plus a signal-ish keyword)
so an 80+-channel, thousands-of-messages/day pipeline doesn't spend an LLM
call on every "good morning traders".

Scoped deliberately narrow, per this codebase's own "never fabricate a
price" rule (see close_eod()'s intrinsic-value estimates, close_stale_backlog,
reconcile_eod_settlement -- all real-data-or-honestly-blank, never guessed):
the LLM's job is understanding FORMAT (emoji decoration, shorthand,
code-switched text, which of several open legs a message refers to), not
guessing outcomes it wasn't told. It may only report a price (open OR close,
entry/target/stop_loss alike) that is a real number ACTUALLY PRESENT in the
message text -- enforced here by string containment on the raw text, not
just a prompt instruction, since a prompt instruction alone is not a safety
boundary (the model could still hallucinate a plausible-looking number).
Every LLM-interpreted trade is tagged '[llm-closed@<price>]' or
'[llm-opened: <reasoning>]' distinctly from every other open/close reason in
this codebase, so it is always auditable and never confused with a
regex-verified one.
"""
import json
import os
import re
import urllib.error
import urllib.request

from django.conf import settings

DEFAULT_BASE = 'https://api.omniroute.ai/v1'
MODEL = 'gpt-4o'

SYSTEM_PROMPT = (
    "You are helping a trading-signal tracker interpret a single Telegram "
    "message from a trade-call channel, given the channel's currently OPEN "
    "positions. Decide if this message reports one specific one of those "
    "positions being closed (target hit, stopped out, booked, trade done, "
    "etc).\n\n"
    "CRITICAL RULE: you may only extract a price that is LITERALLY WRITTEN "
    "as a number in the message text. Never estimate, infer, calculate, or "
    "invent a price. If the message doesn't contain an explicit number for "
    "the close, respond action=none even if it clearly implies the trade is "
    "done.\n\n"
    "Reply with ONLY a JSON object, no other text:\n"
    '{"action": "close" or "none", "trade": "<exact trade string copied '
    'verbatim from the open-positions list, or null>", "price": <number '
    'from the message, or null>, "confidence": "high" or "low", '
    '"reasoning": "<one short sentence>"}'
)


def _client_config():
    key = (getattr(settings, 'OMNIROUTE_API_KEY', '')
           or os.environ.get('USER_OMNIROUTE_API_KEY')
           or os.environ.get('USER_LLM_API_KEY'))
    base = (getattr(settings, 'OMNIROUTE_BASE_URL', '')
            or os.environ.get('USER_OMNIROUTE_BASE_URL')
            or DEFAULT_BASE).rstrip('/')
    return key, base


def is_configured():
    return bool(_client_config()[0])


def _chat(system, user, model=MODEL, timeout=30):
    """Raw OmniRoute chat completion. Returns the response text, or None if
    unconfigured/failed -- never raises, mirroring wealthai.llm.complete()'s
    never-raise contract, so a triage pass degrades to a no-op rather than
    crashing the caller."""
    key, base = _client_config()
    if not key:
        return None
    body = json.dumps({
        'model': model,
        'temperature': 0,
        'messages': [
            {'role': 'system', 'content': system},
            {'role': 'user', 'content': user},
        ],
    }).encode('utf-8')
    req = urllib.request.Request(
        base + '/chat/completions', data=body,
        headers={'Authorization': 'Bearer ' + key,
                 'Content-Type': 'application/json',
                 'User-Agent': 'tradeguru-triage/1.0'},
        method='POST')
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            data = json.loads(resp.read().decode('utf-8'))
        return data['choices'][0]['message']['content']
    except (urllib.error.URLError, urllib.error.HTTPError, KeyError, IndexError,
            ValueError, TimeoutError, OSError):
        return None


OPEN_SYSTEM_PROMPT = (
    "You are helping a trading-signal tracker interpret a single Telegram "
    "message from a trade-call channel. Decide if this message announces a "
    "NEW trade to open (an instrument -- index/stock option or a stock -- "
    "with a clear entry action), as opposed to market commentary, a "
    "promotional/subscription message, a running price update on an "
    "ALREADY-open leg, or general chatter.\n\n"
    "CRITICAL RULES:\n"
    "1. You may only extract a price (entry/target/stop_loss) that is "
    "LITERALLY WRITTEN as a number in the message text. Never estimate, "
    "infer, calculate, or invent a price.\n"
    "2. The instrument symbol/strike you report must also be words/numbers "
    "literally present in the message -- do not invent or complete a "
    "ticker.\n"
    "3. If the message doesn't clearly state BOTH an instrument and an "
    "entry price, respond action=none.\n\n"
    "Reply with ONLY a JSON object, no other text:\n"
    '{"action": "open" or "none", "trade": "<instrument string copied from '
    'the message, e.g. \'NIFTY 23400 PE\' or \'RELIANCE\', or null>", '
    '"direction": "BUY" or "SELL" or "CALL" or "PUT" or null, '
    '"asset_class": "option" or "stock" or "index" or "other", '
    '"entry": <number from the message, or null>, '
    '"target": <number from the message, or null>, '
    '"stop_loss": <number from the message, or null>, '
    '"confidence": "high" or "low", "reasoning": "<one short sentence>"}'
)

# Cheap pre-filter before ANY LLM call -- across 80+ channels most
# regex-missed messages are chatter/promo (see is_promo()/PROMO in
# signals.py), and calling an LLM on every single one would be needless
# cost. A message must at minimum contain a digit and a common signal-ish
# keyword to even be considered a candidate for interpret_open().
_OPEN_CANDIDATE_RE = re.compile(
    r'\b(BUY|SELL|CE|PE|CALL|PUT|TARGET|TGT|SL\b|STOP\s*LOSS|ENTRY|LEVEL|'
    r'ABOVE|BELOW|@)\b', re.IGNORECASE)


def looks_like_possible_open(text):
    """Cheap, LLM-free pre-filter: does this message even plausibly warrant
    an interpret_open() call? Not a safety boundary (that's the literal-text
    check on whatever the LLM returns) -- purely a cost control so a
    76-channel, thousands-of-messages/day pipeline doesn't send every
    "good morning traders" to the LLM."""
    if not text:
        return False
    return bool(re.search(r'\d', text)) and bool(_OPEN_CANDIDATE_RE.search(text))


def _parse_json_response(raw):
    if not raw:
        return None
    try:
        cleaned = re.sub(r'^```(?:json)?|```$', '', raw.strip(), flags=re.MULTILINE).strip()
        return json.loads(cleaned)
    except (ValueError, TypeError):
        return None


def _number_literally_in_text(price, text):
    """True only if `price` appears as a real number token in `text` --
    the actual enforcement of "no fabricated prices" (string containment on
    the source, not trust in the model's claim). Accepts the integer form
    (266) as well as the exact float form (266.0) since channels almost
    always post whole numbers."""
    candidates = {str(price)}
    try:
        f = float(price)
        if f.is_integer():
            candidates.add(str(int(f)))
    except (TypeError, ValueError):
        return False
    return any(re.search(r'(?<!\d)' + re.escape(c) + r'(?!\d)', text) for c in candidates)


def interpret_close(message_text, open_trades):
    """open_trades: list of dicts with at least 'trade' and 'entry' keys
    (target/stop_loss optional, included as context for the model).

    Returns {'trade': str, 'price': float, 'reasoning': str} for a
    high-confidence close backed by a real number literally present in the
    message, else None -- covers: LLM unconfigured/unreachable, malformed
    response, action != 'close', confidence != 'high', missing price/trade,
    price not literally in the text, or trade not one of the given open
    positions.
    """
    if not open_trades or not message_text:
        return None
    positions = '\n'.join(
        f"- {t['trade']} (entry={t.get('entry')}, target={t.get('target')}, "
        f"sl={t.get('stop_loss')})" for t in open_trades)
    user = f"OPEN POSITIONS:\n{positions}\n\nMESSAGE:\n{message_text}"
    parsed = _parse_json_response(_chat(SYSTEM_PROMPT, user))
    if not parsed:
        return None
    if parsed.get('action') != 'close' or parsed.get('confidence') != 'high':
        return None
    price, trade = parsed.get('price'), parsed.get('trade')
    if price is None or trade is None:
        return None
    if not _number_literally_in_text(price, message_text):
        return None
    if trade not in {t['trade'] for t in open_trades}:
        return None
    return {'trade': trade, 'price': float(price), 'reasoning': parsed.get('reasoning', '')}


def interpret_open(message_text):
    """Returns a dict describing a new trade to open -- {'trade', 'direction',
    'asset_class', 'entry', 'target', 'stop_loss', 'reasoning'} -- only when
    the LLM is high-confidence AND every price it reports is literally
    present in message_text (the same string-containment safety boundary as
    interpret_close(); a prompt instruction alone is never trusted). Returns
    None otherwise -- unconfigured/unreachable LLM, malformed response,
    action != 'open', confidence != 'high', missing trade/entry, or any
    reported price that isn't literally in the text.

    Callers should gate with looks_like_possible_open(message_text) first to
    avoid spending an LLM call on messages with no chance of being a real
    signal."""
    if not message_text:
        return None
    parsed = _parse_json_response(_chat(OPEN_SYSTEM_PROMPT, message_text))
    if not parsed:
        return None
    if parsed.get('action') != 'open' or parsed.get('confidence') != 'high':
        return None
    trade, entry = parsed.get('trade'), parsed.get('entry')
    if not trade or entry is None:
        return None
    if not _number_literally_in_text(entry, message_text):
        return None
    for field in ('target', 'stop_loss'):
        value = parsed.get(field)
        if value is not None and not _number_literally_in_text(value, message_text):
            return None
    return {
        'trade': trade,
        'direction': parsed.get('direction') or '',
        'asset_class': parsed.get('asset_class') or 'other',
        'entry': float(entry),
        'target': float(parsed['target']) if parsed.get('target') is not None else None,
        'stop_loss': float(parsed['stop_loss']) if parsed.get('stop_loss') is not None else None,
        'reasoning': parsed.get('reasoning', ''),
    }
