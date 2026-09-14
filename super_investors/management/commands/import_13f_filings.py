"""Pull recent Form 13F-HR ("13F") holdings disclosures for a curated list of
well-known investors/funds from SEC EDGAR and upsert them into Holding rows.

Data source (official, free, public — no API key):
  - https://data.sec.gov/submissions/CIK##########.json
      Per-filer submission history; used to find recent 13F-HR filings
      (accession number, filing date, report/quarter-end date).
  - https://www.sec.gov/Archives/edgar/data/{cik}/{accession-no-dashes}/index.json
      Directory listing for one filing, used to locate its information-table
      XML (filename varies by filer/year — 'infotable.xml', '<n>.xml', etc;
      it's whichever .xml file in the filing isn't 'primary_doc.xml').
  - That XML itself: the actual per-security holdings (issuer, CUSIP, value,
      shares) — see https://www.sec.gov/os/webmaster-faq#developers and the
      Form 13F instructions for the schema.

SEC's Fair Access policy (https://www.sec.gov/os/webmaster-faq#developers)
requires a descriptive User-Agent identifying the application/contact, and
caps automated access at 10 requests/second. We identify ourselves and stay
well under that cap (a fixed sleep between every HTTP call).

13F only reports CUSIP + issuer name, not ticker symbols, so tickers are
resolved via a small best-effort static map (`CUSIP_TICKER_MAP` below) for
well-known large caps; unmapped securities keep ticker blank and fall back
to issuer_name for display everywhere in this app.
"""
import ssl
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from datetime import datetime

from django.core.management.base import BaseCommand

from super_investors.models import Holding, SuperInvestor

try:
    import certifi
    _SSL_CONTEXT = ssl.create_default_context(cafile=certifi.where())
except ImportError:  # pragma: no cover - certifi ships with requests, should always be present
    _SSL_CONTEXT = ssl.create_default_context()

SEC_USER_AGENT = "Traderacker SuperInvestors Research vijay.tibco33@gmail.com"
REQUEST_DELAY_SECONDS = 0.35  # well under SEC's 10 req/s fair-access cap

# Curated "super investor" filers. CIKs verified live against
# https://data.sec.gov/submissions/CIK##########.json before shipping.
TRACKED_FILERS = [
    {'name': 'Warren Buffett', 'fund_name': 'Berkshire Hathaway Inc', 'cik': '0001067983'},
    {'name': 'Michael Burry', 'fund_name': 'Scion Asset Management LLC', 'cik': '0001649339'},
    {'name': 'Bill Ackman', 'fund_name': 'Pershing Square Capital Management', 'cik': '0001336528'},
    {'name': 'Stanley Druckenmiller', 'fund_name': 'Duquesne Family Office LLC', 'cik': '0001536411'},
    {'name': 'David Tepper', 'fund_name': 'Appaloosa LP', 'cik': '0001656456'},
    {'name': 'Seth Klarman', 'fund_name': 'Baupost Group LLC', 'cik': '0001061768'},
    {'name': 'Dan Loeb', 'fund_name': 'Third Point LLC', 'cik': '0001040273'},
    {'name': 'David Einhorn', 'fund_name': 'Greenlight Capital Inc', 'cik': '0001079114'},
]

# Best-effort CUSIP -> ticker map for common large caps that tend to show up
# in these filers' 13Fs. 13F filings only report CUSIP, not ticker, so this
# is deliberately a small, hand-maintained convenience map, not a full
# security master — unmapped names simply keep ticker blank.
CUSIP_TICKER_MAP = {
    '037833100': 'AAPL', '594918104': 'MSFT', '02079K305': 'GOOGL', '02079K107': 'GOOG',
    '023135106': 'AMZN', '30303M102': 'META', '88160R101': 'TSLA', '67066G104': 'NVDA',
    '007903107': 'AMD', '458140100': 'INTC', '084670702': 'BRKA', '084670108': 'BRKB',
    '060505104': 'BAC', '025816109': 'AXP', '191216100': 'KO', '20825C104': 'CVX',
    '674599105': 'OXY', '500754106': 'KHC', '615369105': 'MCO', '92343V104': 'VZ',
    '00206R102': 'T', '46625H100': 'JPM', '949746101': 'WFC', '902973304': 'USB',
    '172967424': 'C', '38141G104': 'GS', '617446448': 'MS', '91324P102': 'UNH',
    '717081103': 'PFE', '478160104': 'JNJ', '20030N101': 'CMCSA', '254687106': 'DIS',
    '64110L106': 'NFLX', '12572Q105': 'CRM', '68389X105': 'ORCL', '459200101': 'IBM',
    '30231G102': 'XOM', '17275R102': 'CSCO', '91324P342': 'UNH', '882508104': 'TXN',
    '00724F101': 'ADBE', '747525103': 'QCOM', '11135F101': 'AVGO', '549271109': 'LULU',
    '406216101': 'HAL', '60855R100': 'MOH', '760763108': 'RH', '30161N101': 'EL',
    '125523100': 'CI', '404119206': 'HCA', '09857L108': 'BKNG', '98978V103': 'ZTS',
    '37045V100': 'GM', '345370860': 'F', '037411105': 'ATVI', '11120U105': 'BMY',
    '532457108': 'ELV', '88579Y101': 'MCO', '69331C108': 'PARA', '02364W105': 'AAL',
    '780259206': 'RCL', '55261F104': 'MMC', '855244109': 'STT', '13645T204': 'CBOE',
    '65473P105': 'NKE', '855030102': 'STAA', '166764100': 'CHTR', '811065101': 'SCHW',
}


class SecEdgarError(Exception):
    pass


def _get_json(url):
    req = urllib.request.Request(url, headers={'User-Agent': SEC_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
        import json
        return json.loads(resp.read().decode('utf-8'))


def _get_text(url):
    req = urllib.request.Request(url, headers={'User-Agent': SEC_USER_AGENT})
    with urllib.request.urlopen(req, timeout=30, context=_SSL_CONTEXT) as resp:
        return resp.read().decode('utf-8', errors='replace')


NS = {'n': 'http://www.sec.gov/edgar/document/thirteenf/informationtable'}


def _parse_infotable(xml_text):
    """Parse a 13F information-table XML into a list of holding dicts.
    Handles both namespaced and non-namespaced variants (older filings
    sometimes omit the default namespace), and tolerates missing optional
    fields — returns [] (never raises) on structurally broken XML so one
    bad filing can't crash the whole import."""
    rows = []
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return rows

    # strip namespace from tags so we don't have to guess the exact URI
    def local(tag):
        return tag.rsplit('}', 1)[-1] if '}' in tag else tag

    for info in root.iter():
        if local(info.tag) != 'infoTable':
            continue
        fields = {local(child.tag): child for child in info}

        def text(name, default=''):
            el = fields.get(name)
            return el.text.strip() if el is not None and el.text else default

        shares_el = fields.get('shrsOrPrnAmt')
        shares = 0
        if shares_el is not None:
            for c in shares_el:
                if local(c.tag) == 'sshPrnamt' and c.text:
                    try:
                        shares = int(float(c.text.strip()))
                    except ValueError:
                        shares = 0

        cusip = text('cusip')
        issuer = text('nameOfIssuer')
        if not cusip or not issuer:
            continue  # unusable row, skip rather than crash
        try:
            value = int(float(text('value', '0') or '0'))
        except ValueError:
            value = 0

        rows.append({'cusip': cusip, 'issuer_name': issuer, 'shares': shares, 'value': value})
    return rows


class Command(BaseCommand):
    help = ("Import recent 13F-HR holdings for the curated super-investor list from "
           "SEC EDGAR (data.sec.gov + www.sec.gov Archives).")

    def add_arguments(self, parser):
        parser.add_argument('--quarters', type=int, default=8,
                            help="Max recent 13F-HR filings per filer to import (default 8, ~2 years).")
        parser.add_argument('--cik', type=str, default=None,
                            help="Limit to a single filer's CIK (for testing/debugging one filer).")

    def handle(self, *args, **options):
        quarters = options['quarters']
        only_cik = options.get('cik')

        filers = TRACKED_FILERS
        if only_cik:
            filers = [f for f in filers if f['cik'] == only_cik or f['cik'].lstrip('0') == only_cik.lstrip('0')]

        total_upserted = 0
        summary = []

        for filer in filers:
            investor, _ = SuperInvestor.objects.update_or_create(
                cik=filer['cik'],
                defaults={'name': filer['name'], 'fund_name': filer['fund_name']},
            )
            self.stdout.write(f"== {investor} (CIK {investor.cik}) ==")
            try:
                filings = self._recent_13f_filings(filer['cik'], quarters)
            except Exception as exc:
                self.stderr.write(self.style.ERROR(
                    f"  submissions fetch failed for {filer['name']}: {exc}"))
                summary.append((filer['name'], 0, 0, 'submissions-fetch-failed'))
                continue

            if not filings:
                self.stdout.write("  no 13F-HR filings found")
                summary.append((filer['name'], 0, 0, 'no-filings'))
                continue

            ok_quarters = 0
            failed_quarters = 0
            rows_upserted = 0
            for filing in filings:
                try:
                    n = self._import_one_filing(investor, filer['cik'], filing)
                    rows_upserted += n
                    ok_quarters += 1
                    self.stdout.write(f"  {filing['reportDate']} (filed {filing['filingDate']}): {n} holdings")
                except Exception as exc:
                    failed_quarters += 1
                    self.stderr.write(self.style.WARNING(
                        f"  {filing.get('reportDate', '?')}: parse/fetch failed, skipping ({exc})"))
                    continue

            total_upserted += rows_upserted
            summary.append((filer['name'], ok_quarters, failed_quarters, rows_upserted))

        self.stdout.write(self.style.SUCCESS(f"\nDone. {total_upserted} holding rows upserted."))
        self.stdout.write("Per-filer summary (quarters ok / failed, rows):")
        for name, ok, failed, rows in summary:
            self.stdout.write(f"  {name}: {ok} ok, {failed} failed, {rows if isinstance(rows, int) else 0} rows")

    def _recent_13f_filings(self, cik, quarters):
        """Return up to `quarters` most recent 13F-HR filings for a CIK, as
        dicts with accessionNumber/filingDate/reportDate, newest first."""
        cik10 = str(cik).zfill(10)
        data = _get_json(f"https://data.sec.gov/submissions/CIK{cik10}.json")
        time.sleep(REQUEST_DELAY_SECONDS)

        out = []

        def _scan(block):
            forms = block.get('form', [])
            for i, form in enumerate(forms):
                if form != '13F-HR':  # skip notices (13F-NT) and amendments
                    continue
                out.append({
                    'accessionNumber': block['accessionNumber'][i],
                    'filingDate': block['filingDate'][i],
                    'reportDate': block['reportDate'][i],
                })

        recent = data.get('filings', {}).get('recent', {})
        _scan(recent)

        # older filings live in paginated files referenced under filings.files
        if len(out) < quarters:
            for extra in data.get('filings', {}).get('files', []):
                try:
                    more = _get_json(f"https://data.sec.gov/submissions/{extra['name']}")
                    time.sleep(REQUEST_DELAY_SECONDS)
                except Exception:
                    continue
                _scan(more)
                if len(out) >= quarters:
                    break

        out.sort(key=lambda f: f['reportDate'], reverse=True)
        return out[:quarters]

    def _import_one_filing(self, investor, cik, filing):
        cik_int = str(int(cik))
        accession_nodash = filing['accessionNumber'].replace('-', '')
        index_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/index.json"
        index = _get_json(index_url)
        time.sleep(REQUEST_DELAY_SECONDS)

        items = index.get('directory', {}).get('item', [])
        xml_name = None
        for item in items:
            name = item.get('name', '')
            if name.lower().endswith('.xml') and name.lower() != 'primary_doc.xml':
                xml_name = name
                break
        if not xml_name:
            raise SecEdgarError('no information-table XML found in filing index')

        xml_url = f"https://www.sec.gov/Archives/edgar/data/{cik_int}/{accession_nodash}/{xml_name}"
        xml_text = _get_text(xml_url)
        time.sleep(REQUEST_DELAY_SECONDS)

        rows = _parse_infotable(xml_text)
        if not rows:
            raise SecEdgarError('information table parsed to zero usable rows')

        quarter_end = datetime.strptime(filing['reportDate'], '%Y-%m-%d').date()
        filed_date = datetime.strptime(filing['filingDate'], '%Y-%m-%d').date()

        # a filer can report the same CUSIP more than once in one filing
        # (e.g. split share classes/put+call rows); collapse by summing so
        # the unique (investor, cusip, quarter) upsert key holds
        collapsed = {}
        for r in rows:
            key = r['cusip']
            c = collapsed.setdefault(key, {'cusip': key, 'issuer_name': r['issuer_name'],
                                           'shares': 0, 'value': 0})
            c['shares'] += r['shares']
            c['value'] += r['value']

        n = 0
        for r in collapsed.values():
            Holding.objects.update_or_create(
                investor=investor, cusip=r['cusip'], filing_quarter=quarter_end,
                defaults={
                    'issuer_name': r['issuer_name'][:255],
                    'ticker': CUSIP_TICKER_MAP.get(r['cusip'], ''),
                    'shares': r['shares'],
                    'market_value': r['value'],
                    'filed_date': filed_date,
                    'accession_number': filing['accessionNumber'],
                },
            )
            n += 1
        return n
