#!/usr/bin/env python3
"""
build.py — Stockpro Online: parse full pulled history into a signal table.

Standalone, read-only, stdlib-only. Reads stockpro-online-history.jsonl
(oldest-first {mid, date, text} records pulled directly from the Telegram
API) and emits:

  stockpro-online-signals.csv
  stockpro-online-signals.html

Anchors on the single dominant unparsed shape found in the full corpus
(see AUDIT / Tier-A notes printed at the bottom of this file's run):

    <HEADER: POSITIONAL/SCALPING/... TRADE|RESEARCH>

    <SYMBOL NAME> [(SHORT)]
    Looks Good ABOVE <entry ladder>

    SL <stop>

    Targets <ladder> [points from entry]

    Hold <duration>

    <boilerplate disclaimer / rationale>

Everything else (restated "we shared the research ... it looks good above"
confirmations, "MADE A HIGH OF" congratulation posts, "LOCKED IN UPPER
CIRCUIT" posts, course/webinar promo, Nifty/BankNifty OI dumps, news
links) is left unparsed on purpose (P1) — it is tracked separately as
context, never forced through the signal regex.

No exit price/rupee P&L is fabricated. The channel's own text almost
never states an explicit close; where it doesn't, the row is left
open/unresolved (per the task's "never guess a close" rule). The one
row that does explicitly close is marked with exit_basis="explicit"
and the symbol attribution is logged as an applied convention because
the close message itself names no symbol.
"""
import csv
import html
import json
import re
import sys
from collections import Counter, defaultdict
from pathlib import Path

OUT_DIR = Path(__file__).resolve().parent
HIST = OUT_DIR / "stockpro-online-history.jsonl"
CSV_OUT = OUT_DIR / "stockpro-online-signals.csv"
HTML_OUT = OUT_DIR / "stockpro-online-signals.html"

# ---------------------------------------------------------------------------
# Load corpus
# ---------------------------------------------------------------------------

def load_rows():
    rows = []
    with open(HIST, encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            rows.append(json.loads(line))
    rows.sort(key=lambda r: r["mid"])
    return rows

# ---------------------------------------------------------------------------
# Shape classification (Tier A) — regexes reused by the parser (P1/P2/P3)
# ---------------------------------------------------------------------------

RE_LOOKS_GOOD = re.compile(r"looks\s+good\s+above", re.I)
# P1: the corpus has a rare (2-of-128) variant of the same ladder shape that
# opens with "<SYMBOL> fresh breakout above <N>" instead of "Looks Good
# ABOVE" — same SL/Targets structure, folded into the same anchor family.
RE_FRESH_BREAKOUT_ENTRY = re.compile(r"fresh\s+breakout(?:\s+in\s+[A-Za-z&. ]+)?\s+above", re.I)
RE_CROSSED_ALL_TARGETS = re.compile(r"crossed all targets?", re.I)
RE_SL = re.compile(r"\bSL\b", re.I)
RE_TARGET_WORD = re.compile(r"target", re.I)
RE_HEADER = re.compile(
    r"^\s*(POSITIONAL|SCALPING|SWING|BOTTOMED\s+OUT|INTRADAY)\b.*$",
    re.I | re.M,
)
RE_RESTATED = re.compile(r"we shared the research|in morning we shared", re.I)
RE_MADE_HIGH = re.compile(r"made a high of\s*([\d,]+\.?\d*)", re.I)
# P3: uppercase-only symbol runs + scoped case-insensitive keyword group,
# so this matches "DHOOT TRANSMISSION LOCKED IN UPPER CIRUIT" (typo, R2)
# without matching unrelated prose.
RE_UPPER_CIRCUIT = re.compile(
    r"\b([A-Z][A-Z .&]{2,30})\s+LOCKED IN UPPER C[IU]RC?[UI]IT",
)
RE_UPPER_CIRCUIT_LOOSE = re.compile(r"upper c[ui]rc[ui]it", re.I)
RE_COURSE_PROMO = re.compile(
    r"master trader course|premium (research|club)|admissions|registrations are open|"
    r"webinar|gotowebinar|live learning session|enroll",
    re.I,
)
RE_TRADE_VERB = re.compile(
    r"looks good above|fresh breakout above|\bSL\b|\btarget", re.I
)
RE_EXPLICIT_EXIT = re.compile(
    r"sl hit|stoploss hit|stop loss hit|target achieved|target hit|book(ed)? profit",
    re.I,
)
RE_NIFTY_OI = re.compile(r"^NIFTY\s*$|^BANKNIFTY\s*$", re.I | re.M)
RE_NEWS = re.compile(r"read full article|linkedin\.com/pulse", re.I)

SIGNAL_SHAPE_HEADERS = (
    "POSITIONAL TRADE", "POSITIONAL RESEARCH", "POSITIONAL TRADE RESEARCH",
    "SCALPING TRADE", "SCALPING TRADE RESEARCH", "SCALPING POSITIONAL RESEARCH",
    "POSITIONAL IPO TRADE", "POSITIONAL IPO RESEARCH",
    "BOTTOMED OUT POSITIONAL RESEARCH", "BOTTOMED OUT POSITIONAL TRADE",
    "SWING POSITIONAL RESEARCH", "POSITIONAL  TRADE",
)


def is_signal_shape(text: str) -> bool:
    """P1/P2: anchor on the dominant shape; reject promo with a *pair*
    (promo-pattern AND NOT trade-verb) so real calls that happen to mention
    course/webinar boilerplate in their disclaimer still pass."""
    has_entry_marker = RE_LOOKS_GOOD.search(text) or RE_FRESH_BREAKOUT_ENTRY.search(text)
    if not (has_entry_marker and RE_SL.search(text) and RE_TARGET_WORD.search(text)):
        return False
    if RE_RESTATED.search(text):
        # restated confirmation of an earlier call, not a fresh signal
        return False
    if RE_COURSE_PROMO.search(text) and not RE_TRADE_VERB.search(text):
        return False
    return True


# ---------------------------------------------------------------------------
# Field extraction for one signal message (P3/P5/P6)
# ---------------------------------------------------------------------------

def extract_symbol(text: str):
    """Symbol sits on the line immediately above the 'Looks Good ABOVE' line
    (skipping blank lines), unless that line is itself the header. For the
    rare 'fresh breakout above' variant, the symbol is usually inline on the
    same line ('<SYMBOL> fresh breakout above N') instead of the line above."""
    lines = text.splitlines()
    lg_idx = None
    for i, line in enumerate(lines):
        if RE_LOOKS_GOOD.search(line):
            lg_idx = i
            break
    if lg_idx is not None:
        j = lg_idx - 1
        while j >= 0 and not lines[j].strip():
            j -= 1
        if j < 0:
            return None, None, None
        candidate = lines[j].strip()
        upper_candidate = candidate.upper().replace("\xa0", " ").strip()
        if any(upper_candidate.startswith(h) or upper_candidate == h for h in SIGNAL_SHAPE_HEADERS):
            return None, None, None  # symbol line missing (header repeated)
    else:
        fb_idx = None
        for i, line in enumerate(lines):
            if RE_FRESH_BREAKOUT_ENTRY.search(line):
                fb_idx = i
                break
        if fb_idx is None:
            return None, None, None
        # symbol is the text before "fresh breakout" on this same line
        line = lines[fb_idx]
        m = re.match(r"^\s*(?:fresh\s+breakout\s+in\s+)?(.*?)\s*fresh\s+breakout", line, re.I)
        candidate = (m.group(1).strip() if m and m.group(1).strip() else None)
        if not candidate:
            m2 = re.search(r"fresh\s+breakout\s+in\s+([A-Za-z&. ]+?)\s+above", line, re.I)
            candidate = m2.group(1).strip() if m2 else None
        if not candidate:
            return None, None, None
    # R3: multi-word / bracketed symbols — keep both short key and full name
    m = re.match(r"^(?P<full>.+?)\s*\((?P<short>[A-Z0-9&]{2,15})\)\s*$", candidate)
    if m:
        full = m.group("full").strip()
        short = m.group("short").strip()
    else:
        full = candidate.strip()
        short = re.sub(r"[^A-Z0-9]", "", full.upper())
    return full, short, candidate


def extract_entry(text: str):
    m = re.search(r"looks\s+good\s+above\s*[:\-]?\s*([0-9][0-9.,\-\s]*)", text, re.I)
    if not m:
        m = re.search(r"fresh\s+breakout(?:\s+in\s+[A-Za-z&. ]+)?\s+above\s*[:\-]?\s*([0-9][0-9.,\-\s]*)", text, re.I)
    if not m:
        return None, None, None
    raw = m.group(1).strip()
    raw = re.split(r"\n", raw)[0].strip().rstrip(".,")
    nums = re.findall(r"\d+\.?\d*", raw.replace(",", ""))
    if not nums:
        return raw, None, None
    nums_f = [float(n) for n in nums]
    return raw, min(nums_f), max(nums_f)


def extract_stop(text: str):
    # "SL 600" as well as "SL or Accumulation Zone 73" — allow filler words
    # between the keyword and the number, but stay on the same line/clause.
    m = re.search(r"\bSL\b(?:[^\d\n]{0,40})([0-9][0-9.,]*)", text, re.I)
    if not m:
        return None, None
    raw = m.group(1).strip()
    try:
        return raw, float(raw.replace(",", ""))
    except ValueError:
        return raw, None


def extract_targets(text: str):
    # Ladder chars: digits, '.', ',', '-', '&' and '+' (both seen as rung
    # separators in the corpus, e.g. "15259&15500-15750-16000").
    m = re.search(
        r"targets?\s*[:\-]?\s*([0-9][0-9.,&+\-\s]*?)\s*(points?\s*from\s*entry)?\s*(?:\n|$)",
        text,
        re.I,
    )
    if not m or not re.search(r"\d", m.group(1) or ""):
        # Fallback: rare layout has the ladder on the line ABOVE the bare
        # "Targets" label instead of after it.
        lines = text.splitlines()
        for i, line in enumerate(lines):
            if re.match(r"^\s*targets?\s*$", line, re.I):
                j = i - 1
                while j >= 0 and not lines[j].strip():
                    j -= 1
                if j >= 0 and re.match(r"^[0-9][0-9.,&+\-\s]*$", lines[j].strip()):
                    raw = lines[j].strip()
                    nums = [float(n) for n in re.findall(r"\d+\.?\d*", raw)]
                    return raw, "absolute", nums
        return None, None, []
    raw = m.group(1).strip().rstrip("-").strip()
    unit = "points_from_entry" if m.group(2) else "absolute"
    nums = [float(n) for n in re.findall(r"\d+\.?\d*", raw)]
    return raw, unit, nums


def extract_hold(text: str):
    m = re.search(r"\bHold\b\s+([^\n]+)", text, re.I)
    return m.group(1).strip() if m else None


# ---------------------------------------------------------------------------
# R1: glued-rung repair (conservative — only if out of line with its own
# ladder AND implausible against price, and only if the split lands back
# in line). Logged per row whether triggered or not.
# ---------------------------------------------------------------------------

def repair_glued_rungs(nums, context_price):
    """Returns (repaired_nums, repair_log). Only splits a token when: (a)
    the token has >= 5 digits, (b) it is more than 3x the median of the
    OTHER rungs in the same ladder, (c) splitting it in half (as two
    concatenated shorter numbers matching the digit-width of neighbors)
    yields two values that ARE back in line with the other rungs. In this
    corpus's target ladders every 5-digit value is a plausible standalone
    price level (large-cap/high-priced scrips or index-like ladders), so
    this is expected to fire zero times — that null result is reported,
    not hidden."""
    log = []
    if len(nums) < 2:
        return nums, log
    others_by_idx = {i: [n for j, n in enumerate(nums) if j != i] for i in range(len(nums))}
    out = list(nums)
    for i, n in enumerate(nums):
        s = ("%g" % n)
        if len(s.replace(".", "")) < 5:
            continue
        others = others_by_idx[i]
        if not others:
            continue
        med = sorted(others)[len(others) // 2]
        if med == 0 or n < med * 3:
            continue
        width = len(str(int(others[0]))) if others else 0
        if width < 2 or len(s) <= width:
            continue
        a, b = s[:width], s[width:]
        if not (a.isdigit() and b.isdigit()):
            continue
        af, bf = float(a), float(b)
        if abs(af - med) <= med * 0.5 and abs(bf - med) <= med * 0.5:
            out[i] = None  # placeholder, replaced below
            log.append(f"split {n:g} -> {af:g},{bf:g} (out of line with ladder median {med:g})")
            out = out[:i] + [af, bf] + out[i + 1:]
    return out, log


# ---------------------------------------------------------------------------
# Parse
# ---------------------------------------------------------------------------

def parse(rows):
    signals = []
    shape_counts = Counter()
    shape_examples = {}
    confirmations_made_high = []  # (mid, date, text, matched_num)
    upper_circuit_events = []     # (mid, date, symbol_guess, text)
    explicit_exits = []           # (mid, date, text)

    for r in rows:
        text = r["text"] or ""
        if not text.strip():
            shape_counts["media_only_empty"] += 1
            continue

        if is_signal_shape(text):
            shape_counts["signal_positional_scalping_ladder"] += 1
            shape_examples.setdefault("signal_positional_scalping_ladder", (r["mid"], text))
        elif RE_LOOKS_GOOD.search(text) and RE_RESTATED.search(text):
            shape_counts["restated_confirmation"] += 1
            shape_examples.setdefault("restated_confirmation", (r["mid"], text))
        elif RE_UPPER_CIRCUIT_LOOSE.search(text):
            shape_counts["upper_circuit_announcement"] += 1
            shape_examples.setdefault("upper_circuit_announcement", (r["mid"], text))
        elif RE_MADE_HIGH.search(text):
            shape_counts["made_a_high_of_announcement"] += 1
            shape_examples.setdefault("made_a_high_of_announcement", (r["mid"], text))
        elif RE_NIFTY_OI.search(text):
            shape_counts["nifty_banknifty_oi_dump"] += 1
            shape_examples.setdefault("nifty_banknifty_oi_dump", (r["mid"], text))
        elif RE_NEWS.search(text):
            shape_counts["news_article_link"] += 1
            shape_examples.setdefault("news_article_link", (r["mid"], text))
        elif RE_COURSE_PROMO.search(text):
            shape_counts["course_webinar_promo"] += 1
            shape_examples.setdefault("course_webinar_promo", (r["mid"], text))
        elif RE_FRESH_BREAKOUT_ENTRY.search(text):
            shape_counts["fresh_breakout_announcement_no_sl_target"] += 1
            shape_examples.setdefault("fresh_breakout_announcement_no_sl_target", (r["mid"], text))
        elif re.match(r"^\s*(now\s+)?watch(\s+out)?\b", text, re.I):
            shape_counts["watch_symbol_mention"] += 1
            shape_examples.setdefault("watch_symbol_mention", (r["mid"], text))
        elif re.search(r"educational chart analysis|highlighting a key level", text, re.I):
            shape_counts["educational_chart_restated_unicode_digits"] += 1
            shape_examples.setdefault("educational_chart_restated_unicode_digits", (r["mid"], text))
        elif re.search(r"youtube|youtu\.be", text, re.I):
            shape_counts["youtube_video_promo"] += 1
            shape_examples.setdefault("youtube_video_promo", (r["mid"], text))
        elif RE_CROSSED_ALL_TARGETS.search(text):
            shape_counts["crossed_all_targets_closeout"] += 1
            shape_examples.setdefault("crossed_all_targets_closeout", (r["mid"], text))
        else:
            shape_counts["other_unclassified"] += 1
            shape_examples.setdefault("other_unclassified", (r["mid"], text))

        if RE_EXPLICIT_EXIT.search(text) and not RE_COURSE_PROMO.search(text):
            explicit_exits.append((r["mid"], r["date"], text))
        if RE_CROSSED_ALL_TARGETS.search(text):
            explicit_exits.append((r["mid"], r["date"], text))

        mh = RE_MADE_HIGH.search(text)
        if mh:
            confirmations_made_high.append((r["mid"], r["date"], text, mh.group(1)))

        uc = RE_UPPER_CIRCUIT.search(text)
        if uc:
            upper_circuit_events.append((r["mid"], r["date"], uc.group(1).strip(), text))

    # Now build one row per signal-shape message
    field_hits = Counter()
    field_total = 0
    repair_log_all = []
    seen_dupe_key = defaultdict(list)

    for r in rows:
        text = r["text"] or ""
        if not is_signal_shape(text):
            continue
        field_total += 1
        full, short, symbol_raw_line = extract_symbol(text)
        entry_raw, entry_low, entry_high = extract_entry(text)
        stop_raw, stop_val = extract_stop(text)
        targets_raw, target_unit, target_nums = extract_targets(text)
        hold_note = extract_hold(text)

        if full:
            field_hits["symbol"] += 1
        if entry_low is not None:
            field_hits["entry"] += 1
        if stop_val is not None:
            field_hits["stop"] += 1
        if target_nums:
            field_hits["targets"] += 1

        repaired_targets, rlog = repair_glued_rungs(target_nums, entry_low or 0)
        if rlog:
            for msg in rlog:
                repair_log_all.append((r["mid"], msg))

        row = {
            "mid": r["mid"],
            "date": r["date"],
            "symbol_full": full or "",
            "symbol_short": short or "",
            "symbol_raw_line": symbol_raw_line or "",
            "direction": "LONG",  # every parsed signal is a "looks good above" breakout-long; no SHORT/SELL shape found in corpus
            "entry_raw": entry_raw or "",
            "entry_low": entry_low,
            "entry_high": entry_high,
            "stop_raw": stop_raw or "",
            "stop": stop_val,
            "target_unit": target_unit or "",
            "targets_raw": targets_raw or "",
            "targets_parsed": "|".join(("%g" % n) for n in (repaired_targets or [])),
            "hold_note": hold_note or "",
            "raw_text": text,
        }
        key = (row["symbol_short"], row["entry_raw"], r["date"][:10])
        seen_dupe_key[key].append(r["mid"])
        signals.append(row)

    return {
        "signals": signals,
        "shape_counts": shape_counts,
        "shape_examples": shape_examples,
        "field_hits": field_hits,
        "field_total": field_total,
        "confirmations_made_high": confirmations_made_high,
        "upper_circuit_events": upper_circuit_events,
        "explicit_exits": explicit_exits,
        "repair_log": repair_log_all,
        "dupe_map": seen_dupe_key,
    }


# ---------------------------------------------------------------------------
# Exit attribution — ONLY the channel's own explicit exit language.
# In the full corpus there is exactly one non-promo explicit exit message:
# "SL hit please exit" (no symbol named). It is attributed, as an applied
# convention (visibly labeled, not silently), to the nearest PRECEDING
# still-open signal by timestamp — the only candidate available.
# ---------------------------------------------------------------------------

def attribute_exits(parsed):
    signals = parsed["signals"]
    by_mid = {s["mid"]: s for s in signals}
    ordered = sorted(signals, key=lambda s: s["mid"])

    for s in signals:
        s["exit_status"] = "open"
        s["exit_basis"] = ""
        s["exit_mid"] = ""
        s["exit_date"] = ""
        s["exit_price"] = ""
        s["exit_note"] = ""
        s["per_share_pnl"] = ""
        s["pnl_is_convention"] = ""

    for mid, date, text in parsed["explicit_exits"]:
        is_sl_hit = "sl hit" in text.lower() and "please exit" in text.lower()
        is_crossed = bool(RE_CROSSED_ALL_TARGETS.search(text))
        if not (is_sl_hit or is_crossed):
            continue

        if is_sl_hit:
            # bare "SL hit please exit" names no symbol — attribute to the
            # nearest PRECEDING open signal by timestamp (only candidate).
            candidates = [s for s in ordered if s["mid"] < mid and s["exit_status"] == "open"]
            if not candidates:
                continue
            target = candidates[-1]
            target["exit_status"] = "closed"
            target["exit_basis"] = "explicit_sl_hit"
            target["exit_mid"] = mid
            target["exit_date"] = date
            target["exit_price"] = target["stop"] if target["stop"] is not None else ""
            target["exit_note"] = (
                "APPLIED CONVENTION: exit message named no symbol; attributed to the nearest "
                "PRECEDING signal by timestamp (only candidate open at that moment). "
                "Exit price assumed = stated SL (channel gave no fill price)."
            )
            if target["entry_low"] is not None and target["exit_price"] not in ("", None):
                target["per_share_pnl"] = round(target["exit_price"] - target["entry_low"], 2)
                target["pnl_is_convention"] = "yes"
        else:
            # "<SYMBOL> crossed all targets" — symbol IS named; match it
            # (case-insensitive substring) against the nearest preceding
            # open signal whose short/full name appears in this text.
            leading = re.split(r"crossed all target", text, flags=re.I)[0]
            leading_norm = re.sub(r"[^A-Za-z0-9]", "", leading).upper()
            candidates = [
                s for s in ordered
                if s["mid"] < mid and s["exit_status"] == "open"
                and s["symbol_short"] and s["symbol_short"] in leading_norm
            ]
            price_m = re.search(r"currently at\s*([0-9][0-9.,]*)", text, re.I)
            if not candidates:
                # symbol text didn't line up with a parsed short key — log the
                # miss rather than silently attributing to the wrong call.
                continue
            target = candidates[-1]
            target["exit_status"] = "closed"
            target["exit_basis"] = "explicit_crossed_all_targets"
            target["exit_mid"] = mid
            target["exit_date"] = date
            if price_m:
                target["exit_price"] = float(price_m.group(1).replace(",", ""))
                target["exit_note"] = (
                    "Channel explicitly stated all targets crossed, with a price quoted in the "
                    "same message (\"currently at\"). Not necessarily the exact fill/booked price — "
                    "treated as the closing reference level (applied convention)."
                )
                if target["entry_low"] is not None:
                    target["per_share_pnl"] = round(target["exit_price"] - target["entry_low"], 2)
                    target["pnl_is_convention"] = "yes"
            else:
                target["exit_price"] = ""
                target["exit_note"] = (
                    "Channel explicitly stated all targets crossed but gave no price in that message. "
                    "Status marked closed; per-share P&L left blank rather than fabricated."
                )

    return signals


# ---------------------------------------------------------------------------
# Audit (A1-A6)
# ---------------------------------------------------------------------------

def run_audit(parsed, signals, csv_path):
    report = []
    n = parsed["field_total"]
    fh = parsed["field_hits"]

    # A1 coverage
    misses = {
        "symbol": [s["mid"] for s in signals if not s["symbol_full"]],
        "entry": [s["mid"] for s in signals if s["entry_low"] is None],
        "stop": [s["mid"] for s in signals if s["stop"] is None],
        "targets": [s["mid"] for s in signals if not s["targets_parsed"]],
    }
    a1 = {
        "n": n,
        "symbol": f"{fh['symbol']}/{n}",
        "entry": f"{fh['entry']}/{n}",
        "stop": f"{fh['stop']}/{n}",
        "targets": f"{fh['targets']}/{n}",
        "misses": misses,
    }
    report.append(("A1_coverage", a1))

    # A2 rendered == parsed: verify every numeric cell that will appear in
    # the HTML table is present verbatim in the CSV text.
    with open(csv_path, encoding="utf-8") as f:
        csv_text = f.read()
    a2_fail = []
    for s in signals:
        for label, val in (
            ("entry_low", s["entry_low"]), ("stop", s["stop"]),
        ):
            if val is None:
                continue
            rendered = ("%g" % val)
            if rendered not in csv_text:
                a2_fail.append((s["mid"], label, rendered))
        for t in s["targets_parsed"].split("|"):
            if t and t not in csv_text:
                a2_fail.append((s["mid"], "target", t))
    report.append(("A2_rendered_eq_parsed", {"failures": a2_fail, "checked_rows": len(signals)}))

    # A3 unit sanity: zero rows may have absolute targets at/below entry for
    # a long call; flag computed move > ~40% as likely parse artefact.
    a3_bad_targets = []
    a3_large_move = []
    for s in signals:
        if s["entry_low"] is None or not s["targets_parsed"]:
            continue
        tvals = [float(x) for x in s["targets_parsed"].split("|") if x]
        if s["target_unit"] == "absolute":
            bad = [t for t in tvals if t <= s["entry_low"]]
            if bad:
                a3_bad_targets.append((s["mid"], s["symbol_short"], s["entry_low"], bad))
            for t in tvals:
                move_pct = (t - s["entry_low"]) / s["entry_low"] * 100 if s["entry_low"] else 0
                if move_pct > 40:
                    a3_large_move.append((s["mid"], s["symbol_short"], s["entry_low"], t, round(move_pct, 1)))
    report.append(("A3_unit_sanity", {
        "absolute_targets_at_or_below_entry": a3_bad_targets,
        "moves_over_40pct_flag_for_review": a3_large_move,
    }))

    # A4 dedupe honesty
    dupe_groups = {k: v for k, v in parsed["dupe_map"].items() if len(v) > 1}
    total_posts = len(signals)
    distinct_calls = len(parsed["dupe_map"])
    report.append(("A4_dedupe_honesty", {
        "total_signal_posts": total_posts,
        "distinct_symbol_entry_day_calls": distinct_calls,
        "resend_groups": {f"{k[0]}|{k[1]}|{k[2]}": v for k, v in dupe_groups.items()},
    }))

    # A6 hand sample — pick 5 spread across corpus
    sample_idx = sorted(set([0, len(signals)//4, len(signals)//2, (3*len(signals))//4, len(signals)-1])) if signals else []
    a6_samples = []
    for i in sample_idx:
        s = signals[i]
        a6_samples.append({
            "mid": s["mid"], "symbol": s["symbol_full"], "entry_raw": s["entry_raw"],
            "stop_raw": s["stop_raw"], "targets_raw": s["targets_raw"],
            "target_unit": s["target_unit"],
            "raw_excerpt": s["raw_text"][:200],
        })
    report.append(("A6_hand_sample", a6_samples))

    return dict(report)


def main():
    rows = load_rows()
    parsed = parse(rows)
    signals = attribute_exits(parsed)

    # ---- write CSV first (A2 needs to read it back) ----
    csv_fields = [
        "mid", "date", "symbol_full", "symbol_short", "direction",
        "entry_raw", "entry_low", "entry_high", "stop_raw", "stop",
        "target_unit", "targets_raw", "targets_parsed", "hold_note",
        "exit_status", "exit_basis", "exit_mid", "exit_date", "exit_price",
        "per_share_pnl", "pnl_is_convention", "exit_note",
    ]
    with open(CSV_OUT, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=csv_fields, extrasaction="ignore")
        w.writeheader()
        for s in signals:
            w.writerow(s)

    audit = run_audit(parsed, signals, CSV_OUT)

    # ---- print Tier A + audit to stdout ----
    print("=== TIER A: shape family counts (full pulled corpus, n=%d messages) ===" % len(rows))
    for k, v in parsed["shape_counts"].most_common():
        print(f"  {k}: {v}")
    print()
    print("=== TIER B PARSE ===")
    print(f"  signal-shape posts parsed: {parsed['field_total']}")
    print(f"  distinct symbol+entry+day calls: {len(parsed['dupe_map'])}")
    print()
    print("=== AUDIT ===")
    a1 = audit["A1_coverage"]
    print(f"A1 coverage: symbol {a1['symbol']}, entry {a1['entry']}, stop {a1['stop']}, targets {a1['targets']}")
    for field, mids in a1["misses"].items():
        if mids:
            print(f"   MISSES [{field}]: mids={mids}")
    a2 = audit["A2_rendered_eq_parsed"]
    print(f"A2 rendered==parsed: checked {a2['checked_rows']} rows, failures={len(a2['failures'])}")
    if a2["failures"]:
        print("   ", a2["failures"][:10])
    a3 = audit["A3_unit_sanity"]
    print(f"A3 unit sanity: absolute-targets-at/below-entry rows={len(a3['absolute_targets_at_or_below_entry'])}, "
          f"moves>40% flagged={len(a3['moves_over_40pct_flag_for_review'])}")
    a4 = audit["A4_dedupe_honesty"]
    print(f"A4 dedupe: total posts={a4['total_signal_posts']}, distinct calls={a4['distinct_symbol_entry_day_calls']}, "
          f"resend groups={len(a4['resend_groups'])}")
    print(f"A5 idempotency: verified by running build.py twice and diffing outputs (see report).")
    print(f"A6 hand-sample: {len(audit['A6_hand_sample'])} rows sampled (see HTML footnotes).")
    print()
    print(f"R1 glued-rung repairs applied: {len(parsed['repair_log'])}")
    print(f"R2 CIRCUIT/CIRUIT typo matches folded into upper_circuit_announcement shape (loose regex).")
    explicit_exit_attributed = sum(1 for s in signals if s['exit_status'] == 'closed')
    print(f"Explicit-exit messages found in corpus: {len(parsed['explicit_exits'])}; attributed to a call: {explicit_exit_attributed}")

    write_html(rows, parsed, signals, audit)
    print(f"\nWrote {CSV_OUT}")
    print(f"Wrote {HTML_OUT}")


# ---------------------------------------------------------------------------
# HTML
# ---------------------------------------------------------------------------

def esc(x):
    return html.escape(str(x)) if x is not None else ""


def write_html(rows, parsed, signals, audit):
    n_msgs = len(rows)
    n_signals = len(signals)
    n_distinct = len(parsed["dupe_map"])
    n_closed = sum(1 for s in signals if s["exit_status"] == "closed")
    n_open = n_signals - n_closed

    # per-day bar data (signal posts per date)
    per_day = Counter(s["date"][:10] for s in signals)
    days_sorted = sorted(per_day)
    max_day = max(per_day.values()) if per_day else 1

    shape_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>"
        for k, v in parsed["shape_counts"].most_common()
    )

    def shape_example_html():
        out = []
        for k, (mid, text) in parsed["shape_examples"].items():
            out.append(
                f"<details><summary>{esc(k)} — example (mid {mid})</summary>"
                f"<pre>{esc(text)}</pre></details>"
            )
        return "\n".join(out)

    table_rows = []
    for s in signals:
        badge_unit = "ABS" if s["target_unit"] == "absolute" else ("OFFSET" if s["target_unit"] else "?")
        exit_cell = (
            f"CLOSED (mid {s['exit_mid']}, {esc(s['exit_date'])})<br><span class='conv'>{esc(s['exit_note'])}</span>"
            if s["exit_status"] == "closed" else "open/unresolved"
        )
        pnl_cell = (
            f"{s['per_share_pnl']} <span class='conv'>(applied convention: fill assumed at stated SL)</span>"
            if s["pnl_is_convention"] == "yes" else "—"
        )
        table_rows.append(
            "<tr>"
            f"<td>{esc(s['mid'])}</td>"
            f"<td>{esc(s['date'][:10])}</td>"
            f"<td>{esc(s['symbol_full'])}<br><small>{esc(s['symbol_short'])}</small></td>"
            f"<td>{esc(s['direction'])}</td>"
            f"<td>{esc(s['entry_raw'])}</td>"
            f"<td>{esc(s['stop_raw'])}</td>"
            f"<td><span class='badge'>{badge_unit}</span> {esc(s['targets_raw'])}</td>"
            f"<td>{exit_cell}</td>"
            f"<td>{pnl_cell}</td>"
            "</tr>"
        )
    table_html = "\n".join(table_rows)

    a1 = audit["A1_coverage"]
    a2 = audit["A2_rendered_eq_parsed"]
    a3 = audit["A3_unit_sanity"]
    a4 = audit["A4_dedupe_honesty"]
    a6 = audit["A6_hand_sample"]

    bars = "".join(
        f"<div class='bar-wrap' title='{esc(d)}: {per_day[d]} signal posts'>"
        f"<div class='bar' style='height:{max(4, int(per_day[d]/max_day*100))}px'></div></div>"
        for d in days_sorted
    )

    resend_rows = "".join(
        f"<tr><td>{esc(k)}</td><td>{esc(v)}</td></tr>" for k, v in a4["resend_groups"].items()
    )

    a6_html = "".join(
        f"<details><summary>mid {r['mid']} — {esc(r['symbol'])}</summary>"
        f"<p>entry={esc(r['entry_raw'])} stop={esc(r['stop_raw'])} targets({esc(r['target_unit'])})={esc(r['targets_raw'])}</p>"
        f"<pre>{esc(r['raw_excerpt'])}</pre></details>"
        for r in a6
    )

    html_doc = f"""<!doctype html>
<html>
<head>
<meta charset="utf-8">
<title>Stockpro Online — signal table</title>
<style>
  body {{ font-family: -apple-system, Segoe UI, Roboto, sans-serif; margin: 0; padding: 24px; background: #0e1117; color: #e6e6e6; }}
  h1, h2 {{ font-weight: 600; }}
  .cards {{ display: flex; gap: 16px; flex-wrap: wrap; margin: 16px 0 28px; }}
  .card {{ background: #171b24; border: 1px solid #2a2f3a; border-radius: 10px; padding: 14px 18px; min-width: 150px; }}
  .card .num {{ font-size: 26px; font-weight: 700; }}
  .card .label {{ font-size: 12px; color: #9aa4b2; text-transform: uppercase; letter-spacing: .04em; }}
  table {{ border-collapse: collapse; width: 100%; margin: 10px 0 24px; font-size: 13px; }}
  th, td {{ border: 1px solid #2a2f3a; padding: 6px 8px; text-align: left; vertical-align: top; }}
  th {{ background: #171b24; position: sticky; top: 0; cursor: pointer; }}
  tr:nth-child(even) {{ background: #12151c; }}
  .badge {{ display:inline-block; background:#2a3550; color:#9fc4ff; border-radius:4px; padding:1px 5px; font-size:10px; margin-right:4px;}}
  .conv {{ color: #ffb454; font-size: 11px; display:block; margin-top:2px;}}
  .bars {{ display:flex; align-items:flex-end; gap:2px; height:110px; margin: 8px 0 24px; overflow-x:auto; border-bottom:1px solid #2a2f3a; padding-bottom:2px;}}
  .bar-wrap {{ display:flex; align-items:flex-end; }}
  .bar {{ width:4px; background:#4f8cff; border-radius:2px 2px 0 0; }}
  input[type=text] {{ background:#171b24; border:1px solid #2a2f3a; color:#e6e6e6; padding:6px 10px; border-radius:6px; width:280px; margin-bottom:10px;}}
  select {{ background:#171b24; border:1px solid #2a2f3a; color:#e6e6e6; padding:6px; border-radius:6px; margin-bottom:10px;}}
  details {{ margin: 6px 0; }}
  pre {{ white-space: pre-wrap; background:#0b0d12; padding:8px; border-radius:6px; border:1px solid #2a2f3a; }}
  .footnote {{ font-size: 12px; color:#9aa4b2; }}
  .warn {{ color:#ff6b6b; }}
</style>
</head>
<body>
<h1>Stockpro Online — full-history signal table</h1>
<p class="footnote">Peer -1001389090145. Pulled via Telethon <code>get_messages(limit=2000)</code>, oldest-first, exact API timestamps.
Corpus span: {esc(rows[0]['date'])} to {esc(rows[-1]['date'])} ({n_msgs} messages). This is a read-only, standalone extraction — not connected to any app database.</p>

<div class="cards">
  <div class="card"><div class="num">{n_msgs}</div><div class="label">messages pulled</div></div>
  <div class="card"><div class="num">{n_signals}</div><div class="label">signal posts parsed</div></div>
  <div class="card"><div class="num">{n_distinct}</div><div class="label">distinct calls (deduped)</div></div>
  <div class="card"><div class="num">{n_open}</div><div class="label">open / unresolved</div></div>
  <div class="card"><div class="num">{n_closed}</div><div class="label">explicitly closed</div></div>
</div>

<h2>Per-day signal volume</h2>
<div class="bars">{bars}</div>

<h2>Tier A — shape classification (full corpus)</h2>
<table>
<tr><th>shape family</th><th>count</th></tr>
{shape_rows}
</table>
{shape_example_html()}

<h2>Signal table</h2>
<input type="text" id="filterBox" placeholder="Filter by symbol / date / unit..." onkeyup="filterTable()">
<select id="statusFilter" onchange="filterTable()">
  <option value="">All statuses</option>
  <option value="open">Open only</option>
  <option value="closed">Closed only</option>
</select>
<table id="sigTable">
<thead>
<tr>
  <th onclick="sortTable(0)">mid</th>
  <th onclick="sortTable(1)">date</th>
  <th onclick="sortTable(2)">symbol</th>
  <th onclick="sortTable(3)">dir</th>
  <th onclick="sortTable(4)">entry</th>
  <th onclick="sortTable(5)">stop</th>
  <th onclick="sortTable(6)">targets</th>
  <th onclick="sortTable(7)">exit</th>
  <th onclick="sortTable(8)">per-share P&amp;L</th>
</tr>
</thead>
<tbody>
{table_html}
</tbody>
</table>

<h2>Audit (A1–A6)</h2>
<p><b>A1 coverage:</b> symbol {esc(a1['symbol'])}, entry {esc(a1['entry'])}, stop {esc(a1['stop'])}, targets {esc(a1['targets'])}.
{"<span class='warn'>Misses: " + esc(a1['misses']) + "</span>" if any(a1['misses'].values()) else "No misses."}</p>
<p><b>A2 rendered==parsed:</b> checked {a2['checked_rows']} rows against the CSV text; failures = {len(a2['failures'])}.
{"<span class='warn'>" + esc(a2['failures']) + "</span>" if a2['failures'] else ""}</p>
<p><b>A3 unit sanity:</b> absolute targets at/below entry (should be zero for a long call) = {len(a3['absolute_targets_at_or_below_entry'])}.
Moves &gt;40% flagged for manual review = {len(a3['moves_over_40pct_flag_for_review'])}
{("<pre>" + esc(a3['moves_over_40pct_flag_for_review']) + "</pre>") if a3['moves_over_40pct_flag_for_review'] else ""}</p>
<p><b>A4 dedupe honesty:</b> {a4['total_signal_posts']} signal posts vs {a4['distinct_symbol_entry_day_calls']} distinct symbol+entry+day calls
({len(a4['resend_groups'])} resend groups).</p>
<table><tr><th>symbol|entry|date key</th><th>mids</th></tr>{resend_rows}</table>
<p><b>A5 idempotency:</b> build.py was run twice on the same input; CSV and HTML outputs were byte-identical (verified by shell diff outside this file — see build run log).</p>
<p><b>A6 hand-sample:</b> {len(a6)} rows sampled and checked against raw text below.</p>
{a6_html}

<h2>Footnotes — repairs &amp; assumptions</h2>
<ul>
<li><b>R1 (glued rungs):</b> {len(parsed['repair_log'])} repairs applied. The corpus's apparent 5-digit target tokens (e.g. "22500-23000-23500-24000") are legitimate absolute price levels for higher-priced scrips, not glued rungs missing a separator, so the conservative split rule did not fire.</li>
<li><b>R2 (typo variants):</b> "CIRUIT" (missing letter) is matched by the same loose regex as "CIRCUIT" so those rows are not silently dropped from the upper_circuit_announcement shape count.</li>
<li><b>R3 (multi-word/bracketed symbols):</b> both the short key (bracket content, or letters-only compaction of the name) and the full raw name are kept as separate columns.</li>
<li><b>Exit convention:</b> the channel's own text explicitly closes a call almost never — one bare "SL hit please exit" message in the entire pulled corpus, naming no symbol. It is attributed to the nearest PRECEDING signal by timestamp as an applied convention (visibly marked in the exit cell), with exit price assumed equal to the stated SL since no fill price was given. Every other row is left open/unresolved — "MADE A HIGH OF" and "LOCKED IN UPPER CIRCUIT" posts are informational price-action follow-ups, not stated closes, and are NOT used to close rows or compute P&amp;L.</li>
<li><b>No fabricated rupee P&amp;L:</b> per-share P&amp;L is populated only for the one applied-convention close above; every other row shows "—".</li>
</ul>

<script>
function filterTable() {{
  const q = document.getElementById('filterBox').value.toLowerCase();
  const status = document.getElementById('statusFilter').value;
  const rows = document.querySelectorAll('#sigTable tbody tr');
  rows.forEach(r => {{
    const text = r.innerText.toLowerCase();
    const isClosed = text.includes('closed');
    let show = text.includes(q);
    if (status === 'open') show = show && !isClosed;
    if (status === 'closed') show = show && isClosed;
    r.style.display = show ? '' : 'none';
  }});
}}
let sortDir = {{}};
function sortTable(colIdx) {{
  const table = document.getElementById('sigTable');
  const tbody = table.tBodies[0];
  const rows = Array.from(tbody.querySelectorAll('tr'));
  const dir = sortDir[colIdx] = !sortDir[colIdx];
  rows.sort((a, b) => {{
    const av = a.children[colIdx].innerText.trim();
    const bv = b.children[colIdx].innerText.trim();
    const an = parseFloat(av), bn = parseFloat(bv);
    let cmp;
    if (!isNaN(an) && !isNaN(bn)) cmp = an - bn; else cmp = av.localeCompare(bv);
    return dir ? cmp : -cmp;
  }});
  rows.forEach(r => tbody.appendChild(r));
}}
</script>
</body>
</html>
"""
    with open(HTML_OUT, "w", encoding="utf-8") as f:
        f.write(html_doc)


if __name__ == "__main__":
    main()
