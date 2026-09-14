"""Import recent Congress stock trade disclosures from public STOCK Act data.

Sources (both official/public, no scraping of anything non-public):

* House: the House Clerk's own bulk "Financial Disclosure" ZIP
  (https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.ZIP),
  an XML index of every filing. We filter to Periodic Transaction Reports
  (FilingType 'P') and parse the linked PTR PDF (also hosted by
  disclosures-clerk.house.gov) for the actual buy/sell rows.
* Senate: the Senate eFD search system (https://efdsearch.senate.gov/search/),
  the Senate's own public disclosure search tool. Best-effort: eFD requires
  accepting a click-through "prohibition agreement" (same one a human visitor
  accepts) before its search API responds, and the endpoint occasionally
  returns 503 "Site Under Maintenance" (observed during development of this
  command) -- when that happens we log a warning and continue rather than
  failing the whole import.
* Party/state affiliation: theunitedstates.io's public-domain
  congress-legislators dataset (GitHub: unitedstates/congress-legislators),
  matched by name against each filer.

Idempotent: re-running does not duplicate rows (see CongressTrade's
unique_together constraint) -- matching rows are updated in place.
"""
import re
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from io import BytesIO
from zipfile import ZipFile

from django.core.management.base import BaseCommand
from django.utils import timezone

from congress_trades.models import CongressTrade

HOUSE_ZIP_URL = 'https://disclosures-clerk.house.gov/public_disc/financial-pdfs/{year}FD.ZIP'
HOUSE_PTR_PDF_URL = 'https://disclosures-clerk.house.gov/public_disc/ptr-pdfs/{year}/{doc_id}.pdf'
LEGISLATORS_URL = ('https://raw.githubusercontent.com/unitedstates/congress-legislators/'
                    'main/legislators-current.yaml')
SENATE_BASE = 'https://efdsearch.senate.gov'

USER_AGENT = ('Mozilla/5.0 (compatible; congress-trade-tracker/1.0; '
              'personal research tool; +https://github.com)')

TRANSACTION_MAP = {'P': 'buy', 'S': 'sell', 'E': 'exchange'}

# Matches one PTR transaction row in the flattened (whitespace-collapsed)
# text of a House periodic-transaction-report PDF, e.g.:
#   "SP Netflix, Inc. - Common Stock (NFLX) [ST] S 12/12/2025 01/06/2026 $1,001 - $15,000"
ROW_RE = re.compile(
    r"(?P<asset>[A-Za-z0-9&,.'/ \-]{3,140}?)\s*"
    r"\((?P<ticker>[A-Z]{1,6})\)\s*\[(?P<atype>[A-Za-z]{1,3})\]\s*"
    r"(?P<ttype>[PSE])\s+"
    r"(?P<tdate>\d{2}/\d{2}/\d{4})\s+"
    r"(?P<ndate>\d{2}/\d{2}/\d{4})\s+"
    r"\$(?P<amin>[\d,]+)\s*-\s*\$(?P<amax>[\d,]+)"
)
OWNER_STRIP_RE = re.compile(r'^.*\b(?:SP|JT|DC)\b\s+')
NAME_RE = re.compile(r'Name:\s*(.+?)\s*Status:')
STATE_RE = re.compile(r'State/District:\s*([A-Z]{2})')


def _clean_asset(raw):
    cleaned = OWNER_STRIP_RE.sub('', raw).strip(' ,-')
    return cleaned[:255] or raw.strip()[:255]


def _mdy(s):
    return datetime.strptime(s, '%m/%d/%Y').date()


def _money(s):
    return int(s.replace(',', ''))


class Command(BaseCommand):
    help = "Import recent Congress stock trade disclosures (House Clerk + Senate eFD)."

    def add_arguments(self, parser):
        parser.add_argument('--days', type=int, default=60,
                            help='Lookback window on filing/disclosure date (default 60).')
        parser.add_argument('--limit', type=int, default=250,
                            help='Max filings to fetch+parse per chamber, to keep runtime sane (default 250).')
        parser.add_argument('--house-only', action='store_true')
        parser.add_argument('--senate-only', action='store_true')

    def handle(self, *args, **opts):
        import requests
        self.requests = requests
        self.session = requests.Session()
        self.session.headers.update({'User-Agent': USER_AGENT})

        days = opts['days']
        limit = opts['limit']
        cutoff = timezone.localdate() - timedelta(days=days)

        self.stdout.write(f"Lookback: last {days} days (since {cutoff}), limit {limit}/chamber")

        legislators = self._load_legislators()
        self.stdout.write(f"Loaded {len(legislators)} legislator name keys for party/state lookup")

        created = updated = 0
        if not opts['senate_only']:
            c, u = self._import_house(cutoff, limit, legislators)
            created += c
            updated += u
            self.stdout.write(self.style.SUCCESS(f"House: {c} created, {u} updated"))

        if not opts['house_only']:
            try:
                c, u = self._import_senate(cutoff, limit, legislators)
                created += c
                updated += u
                self.stdout.write(self.style.SUCCESS(f"Senate: {c} created, {u} updated"))
            except Exception as exc:   # noqa: BLE001 - eFD is flaky; never fail the whole import over it
                self.stdout.write(self.style.WARNING(
                    f"Senate import skipped (eFD unavailable or changed shape): {exc}"))

        self.stdout.write(self.style.SUCCESS(f"Done. {created} created, {updated} updated total."))

    # ---- shared: legislator party/state lookup -----------------------------

    def _load_legislators(self):
        """Return {(last, first_word) -> (party, state, chamber)} from the
        public-domain congress-legislators dataset. Best-effort: an empty
        dict just means every trade imports with party='?'."""
        try:
            import yaml
        except ImportError:
            self.stdout.write(self.style.WARNING(
                "pyyaml not installed -- party/state lookup disabled (pip install pyyaml)"))
            return {}
        try:
            resp = self.session.get(LEGISLATORS_URL, timeout=30)
            resp.raise_for_status()
            data = yaml.safe_load(resp.text)
        except Exception as exc:   # noqa: BLE001
            self.stdout.write(self.style.WARNING(f"Could not load legislators dataset: {exc}"))
            return {}

        out = {}
        for person in data:
            name = person.get('name', {})
            last = (name.get('last') or '').lower().strip()
            first = (name.get('first') or '').split()[0].lower().strip() if name.get('first') else ''
            terms = person.get('terms') or []
            if not last or not terms:
                continue
            current = terms[-1]
            party = current.get('party', '')
            party_code = {'Democrat': 'D', 'Republican': 'R'}.get(party, 'I' if party else '?')
            state = (current.get('state') or '')[:2]
            chamber = 'Senate' if current.get('type') == 'sen' else 'House'
            out[(last, first)] = (party_code, state, chamber)
        return out

    def _lookup_party_state(self, legislators, full_name, fallback_state=''):
        # full_name may be "Hon. Richard W. Allen" or "Pelosi, Nancy"
        tokens = re.sub(r'^(Hon\.|Mr\.|Mrs\.|Ms\.|Dr\.)\s*', '', full_name).strip()
        if ',' in tokens:
            last, _, first = tokens.partition(',')
            last, first = last.strip(), first.strip().split()[0] if first.strip() else ''
        else:
            parts = tokens.split()
            if not parts:
                return '?', fallback_state
            last = parts[-1]
            first = parts[0]
        key = (last.lower(), first.lower())
        hit = legislators.get(key)
        if hit:
            return hit[0], hit[1] or fallback_state
        # fallback: match on last name alone if unambiguous
        matches = {v for (l, f), v in legislators.items() if l == last.lower()}
        if len(matches) == 1:
            hit = next(iter(matches))
            return hit[0], hit[1] or fallback_state
        return '?', fallback_state

    # ---- House ---------------------------------------------------------------

    def _import_house(self, cutoff, limit, legislators):
        created = updated = 0
        years = sorted({cutoff.year, timezone.localdate().year}, reverse=True)
        fetched = 0
        for year in years:
            if fetched >= limit:
                break
            filings = self._house_filings(year, cutoff)
            self.stdout.write(f"House {year}: {len(filings)} PTR filings in window")
            for f in filings:
                if fetched >= limit:
                    self.stdout.write(self.style.WARNING(
                        f"House: hit --limit={limit}, stopping (more filings available)"))
                    break
                fetched += 1
                try:
                    c, u = self._import_house_filing(f, year, legislators)
                    created += c
                    updated += u
                except Exception as exc:   # noqa: BLE001 - one bad PDF shouldn't kill the run
                    self.stdout.write(self.style.WARNING(f"  skip {f['doc_id']} ({f['name']}): {exc}"))
                time.sleep(0.2)   # be polite to disclosures-clerk.house.gov
        return created, updated

    def _house_filings(self, year, cutoff):
        resp = self.session.get(HOUSE_ZIP_URL.format(year=year), timeout=60)
        resp.raise_for_status()
        with ZipFile(BytesIO(resp.content)) as zf:
            xml_name = next(n for n in zf.namelist() if n.lower().endswith('.xml'))
            raw = zf.read(xml_name)
        # strip BOM if present
        root = ET.fromstring(raw.lstrip(b'\xef\xbb\xbf'))
        out = []
        for member in root.findall('Member'):
            if (member.findtext('FilingType') or '') != 'P':
                continue
            filing_date_raw = member.findtext('FilingDate') or ''
            try:
                filing_date = datetime.strptime(filing_date_raw, '%m/%d/%Y').date()
            except ValueError:
                continue
            if filing_date < cutoff:
                continue
            last = member.findtext('Last') or ''
            first = member.findtext('First') or ''
            out.append({
                'doc_id': member.findtext('DocID') or '',
                'name': f"{first} {last}".strip(),
                'state_dst': member.findtext('StateDst') or '',
                'filing_date': filing_date,
            })
        return out

    def _import_house_filing(self, filing, year, legislators):
        doc_id = filing['doc_id']
        pdf_url = HOUSE_PTR_PDF_URL.format(year=year, doc_id=doc_id)
        resp = self.session.get(pdf_url, timeout=30)
        if resp.status_code != 200 or not resp.content:
            return 0, 0
        from pypdf import PdfReader
        reader = PdfReader(BytesIO(resp.content))
        text = '\n'.join(page.extract_text() or '' for page in reader.pages)
        flat = re.sub(r'\s+', ' ', text.replace('\x00', ''))

        name_m = NAME_RE.search(flat)
        politician_name = (name_m.group(1) if name_m else filing['name']).strip()
        politician_name = re.sub(r'^(Hon\.|Mr\.|Mrs\.|Ms\.|Dr\.)\s*', '', politician_name)
        state = filing['state_dst'][:2] or (STATE_RE.search(flat).group(1) if STATE_RE.search(flat) else '')
        party, state = self._lookup_party_state(legislators, politician_name, state)

        created = updated = 0
        for m in ROW_RE.finditer(flat):
            ttype = TRANSACTION_MAP.get(m.group('ttype'))
            if not ttype:
                continue
            try:
                tdate = _mdy(m.group('tdate'))
                ndate = _mdy(m.group('ndate'))
                amin = _money(m.group('amin'))
                amax = _money(m.group('amax'))
            except ValueError:
                continue
            obj, was_created = CongressTrade.objects.update_or_create(
                chamber='House', source_doc_id=doc_id, ticker=m.group('ticker'),
                transaction_date=tdate, transaction_type=ttype,
                amount_min=amin, amount_max=amax,
                defaults={
                    'politician_name': politician_name,
                    'party': party,
                    'state': state,
                    'asset_description': _clean_asset(m.group('asset')),
                    'disclosure_date': ndate,
                    'filing_url': pdf_url,
                },
            )
            created += int(was_created)
            updated += int(not was_created)
        return created, updated

    # ---- Senate (best-effort) -------------------------------------------------

    def _import_senate(self, cutoff, limit, legislators):
        """Best-effort Senate eFD import. Senate eFD is a live government
        search tool with a click-through agreement and an endpoint that has
        been observed returning 503 'Site Under Maintenance' -- any failure
        here is caught by the caller and logged, never fatal to the run."""
        s = self.session
        home = s.get(f'{SENATE_BASE}/search/home/', timeout=30)
        home.raise_for_status()
        m = re.search(r'name="csrfmiddlewaretoken" value="([^"]+)"', home.text)
        if not m:
            raise RuntimeError('could not find csrf token on eFD landing page')
        agree = s.post(f'{SENATE_BASE}/search/home/',
                       data={'csrfmiddlewaretoken': m.group(1), 'prohibition_agreement': '1'},
                       headers={'Referer': f'{SENATE_BASE}/search/home/'}, timeout=30)
        agree.raise_for_status()
        s.get(f'{SENATE_BASE}/search/', timeout=30)
        csrftoken = s.cookies.get('csrftoken')
        if not csrftoken:
            raise RuntimeError('no csrftoken cookie after accepting eFD agreement')

        start_date = cutoff.strftime('%m/%d/%Y') + ' 00:00:00'
        rows = []
        page_start = 0
        page_len = 100
        while page_start < limit:
            payload = {
                'start': page_start, 'length': page_len, 'report_types': '[11]',
                'filer_types': '[]', 'submitted_start_date': start_date,
                'submitted_end_date': '', 'candidate_state': '[]', 'senator_state': '[]',
                'office_id': '[]', 'first_name': '', 'last_name': '',
                'csrfmiddlewaretoken': csrftoken,
            }
            resp = s.post(f'{SENATE_BASE}/search/report/data/', data=payload,
                          headers={'Referer': f'{SENATE_BASE}/search/', 'X-CSRFToken': csrftoken},
                          timeout=30)
            if resp.status_code != 200:
                raise RuntimeError(f'search endpoint returned HTTP {resp.status_code}')
            data = resp.json().get('data', [])
            if not data:
                break
            rows.extend(data)
            page_start += page_len
            if len(data) < page_len:
                break
            time.sleep(0.3)

        self.stdout.write(f"Senate: {len(rows)} PTR filings in window")
        created = updated = 0
        for row in rows[:limit]:
            try:
                c, u = self._import_senate_row(row, legislators)
                created += c
                updated += u
            except Exception as exc:   # noqa: BLE001
                self.stdout.write(self.style.WARNING(f"  senate row skip: {exc}"))
            time.sleep(0.2)
        return created, updated

    def _import_senate_row(self, row, legislators):
        # row: [first, last, office, "<a href='/search/view/.../{id}/'>...</a>", filed_date]
        first, last, office, link_html, filed_date_raw = row[0], row[1], row[2], row[3], row[4]
        href_m = re.search(r"href='([^']+)'", link_html) or re.search(r'href="([^"]+)"', link_html)
        if not href_m:
            return 0, 0
        detail_url = SENATE_BASE + href_m.group(1)
        if '/paper/' in detail_url:
            # scanned paper filing, no reliably parseable structured data -- skip
            return 0, 0

        resp = self.session.get(detail_url, timeout=30)
        if resp.status_code != 200:
            return 0, 0
        html = resp.text
        politician_name = f"{first} {last}".strip()
        state_m = re.search(r'\b([A-Z]{2})\b\s*</td>', html)
        party, state = self._lookup_party_state(legislators, politician_name, '')

        created = updated = 0
        # electronic PTR detail pages render one <tr> per transaction with
        # ticker/asset, transaction type, date, and amount cells
        for tr in re.findall(r'<tr[^>]*>(.*?)</tr>', html, re.S):
            cells = [re.sub('<[^>]+>', '', c).strip() for c in re.findall(r'<td[^>]*>(.*?)</td>', tr, re.S)]
            if len(cells) < 5:
                continue
            ticker_m = re.search(r'\(([A-Z]{1,6})\)', ' '.join(cells))
            date_m = re.search(r'(\d{2}/\d{2}/\d{4})', ' '.join(cells))
            amount_m = re.search(r'\$([\d,]+)\s*-\s*\$([\d,]+)', ' '.join(cells))
            type_text = ' '.join(cells).lower()
            if 'purchase' in type_text:
                ttype = 'buy'
            elif 'sale' in type_text or 'sold' in type_text:
                ttype = 'sell'
            elif 'exchange' in type_text:
                ttype = 'exchange'
            else:
                ttype = None
            if not (ticker_m and date_m and amount_m and ttype):
                continue
            tdate = _mdy(date_m.group(1))
            filed_date = _mdy(filed_date_raw) if re.match(r'\d{2}/\d{2}/\d{4}', filed_date_raw) else tdate
            obj, was_created = CongressTrade.objects.update_or_create(
                chamber='Senate', source_doc_id=detail_url.rsplit('/', 2)[-2],
                ticker=ticker_m.group(1), transaction_date=tdate, transaction_type=ttype,
                amount_min=_money(amount_m.group(1)), amount_max=_money(amount_m.group(2)),
                defaults={
                    'politician_name': politician_name,
                    'party': party,
                    'state': state,
                    'asset_description': cells[0][:255] if cells else ticker_m.group(1),
                    'disclosure_date': filed_date,
                    'filing_url': detail_url,
                },
            )
            created += int(was_created)
            updated += int(not was_created)
        return created, updated
