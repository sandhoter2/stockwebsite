"""Fetch BlackRock's and JPMorgan's public market-outlook / research pages
and upsert short, scannable entries (title + short summary + link) into
MarketReport — never the full article text (product requirement + courtesy
to the source's copyright).

Idempotent: upserts keyed on source_url. Best-effort per page: a page whose
markup has changed (or that 404s/blocks us) is skipped with a warning, it
never aborts the whole run. Intended to run on a schedule, not in a loop —
one polite request per source page per run, with a real User-Agent.

  manage.py import_market_reports [--dry-run]
"""
import re
from datetime import datetime

import requests
from bs4 import BeautifulSoup
from django.core.management.base import BaseCommand
from django.utils import timezone

from institutional_reports.models import MarketReport

USER_AGENT = ('Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) '
             'AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0 Safari/537.36 '
             'TelegramTradeTracker/1.0 (+institutional-reports research aggregator)')
REQUEST_TIMEOUT = 20
MAX_SUMMARY_LEN = 500

DATE_FORMATS = ['%b %d, %Y', '%B %d, %Y']


def parse_date(text):
    """'Sep 11, 2026' / 'Jul 01, 2026' -> date(), or None."""
    if not text:
        return None
    text = text.strip()
    for fmt in DATE_FORMATS:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def absolute_url(base, href):
    if not href:
        return None
    if href.startswith('http'):
        return href
    from urllib.parse import urljoin
    return urljoin(base, href)


def clean_text(text, limit=MAX_SUMMARY_LEN):
    text = re.sub(r'\s+', ' ', text or '').strip()
    if len(text) > limit:
        text = text[:limit].rsplit(' ', 1)[0] + '…'
    return text


def guess_report_type(title, default):
    t = (title or '').lower()
    if 'weekly' in t:
        return MarketReport.TYPE_WEEKLY_COMMENTARY
    if 'quarter' in t or re.search(r'\bq[1-4]\b', t):
        return MarketReport.TYPE_QUARTERLY_OUTLOOK
    if 'outlook' in t or 'forecast' in t or 'year ahead' in t or 'mid-year' in t:
        return MarketReport.TYPE_YEARLY_FORECAST
    return default


def fetch(url):
    resp = requests.get(url, headers={'User-Agent': USER_AGENT}, timeout=REQUEST_TIMEOUT)
    resp.raise_for_status()
    return BeautifulSoup(resp.text, 'html.parser')


class Command(BaseCommand):
    help = ("Fetch BlackRock/JPMorgan public market-outlook pages and upsert "
           "short MarketReport entries (title + short summary + link).")

    def add_arguments(self, parser):
        parser.add_argument('--dry-run', action='store_true',
                            help="Parse and print, don't write to the DB.")

    def handle(self, *args, **opts):
        dry_run = opts['dry_run']
        total_seen = total_created = total_updated = 0

        extractors = [
            ('https://www.jpmorgan.com/insights/research', MarketReport.FIRM_JPMORGAN,
             self._extract_jpm_research),
            ('https://www.jpmorgan.com/insights/markets-and-economy/outlook', MarketReport.FIRM_JPMORGAN,
             self._extract_jpm_outlook),
            ('https://www.blackrock.com/us/individual/insights', MarketReport.FIRM_BLACKROCK,
             self._extract_blackrock_listing),
            ('https://www.blackrock.com/us/individual/insights/blackrock-investment-institute/weekly-commentary',
             MarketReport.FIRM_BLACKROCK, self._extract_blackrock_weekly),
        ]

        for url, firm, extractor in extractors:
            self.stdout.write(f'Fetching {url} ...')
            try:
                soup = fetch(url)
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f'  skip (fetch failed): {exc}'))
                continue

            try:
                items = extractor(soup, url, firm)
            except Exception as exc:
                self.stderr.write(self.style.WARNING(f'  skip (parse failed): {exc}'))
                continue

            self.stdout.write(f'  parsed {len(items)} item(s)')
            for item in items:
                total_seen += 1
                if dry_run:
                    self.stdout.write(f'    [dry-run] {item["title"]!r} ({item["published_date"]}) {item["source_url"]}')
                    continue
                obj, created = MarketReport.objects.update_or_create(
                    source_url=item['source_url'],
                    defaults={
                        'firm': item['firm'],
                        'title': item['title'],
                        'published_date': item['published_date'],
                        'report_type': item['report_type'],
                        'short_summary': item['short_summary'],
                    },
                )
                if created:
                    total_created += 1
                else:
                    total_updated += 1

        self.stdout.write(self.style.SUCCESS(
            f'Done: {total_seen} item(s) parsed'
            + ('' if dry_run else f' · {total_created} created · {total_updated} updated')))

    # -- per-source extractors -------------------------------------------------
    # Each is defensive: missing pieces on a card just cause that card to be
    # skipped (site markup drifts over time), never a hard crash.

    def _extract_jpm_research(self, soup, base_url, firm):
        """jpmorgan.com/insights/research — one 'featured insight' card."""
        out = []
        for card in soup.select('.insights-card-package'):
            a = card.select_one('a.card-headline')
            if not a or not a.get('href'):
                continue
            title = clean_text(a.get_text())
            date_el = card.select_one('p.date')
            pub_date = parse_date(date_el.get_text() if date_el else None)
            if not title or not pub_date:
                continue
            info_el = card.select_one('p.info')
            summary = clean_text(info_el.get_text()) if info_el else ''
            out.append({
                'firm': firm, 'title': title, 'published_date': pub_date,
                'report_type': guess_report_type(title, MarketReport.TYPE_RESEARCH_NOTE),
                'short_summary': summary,
                'source_url': absolute_url(base_url, a['href']),
            })
        return out

    def _extract_jpm_outlook(self, soup, base_url, firm):
        """jpmorgan.com/insights/markets-and-economy/outlook — related-insights
        carousel of cards."""
        out = []
        for card in soup.select('.related-insights__cards-content'):
            a = card.select_one('a.card-link')
            if not a or not a.get('href'):
                continue
            title = clean_text(a.get_text())
            date_el = card.select_one('p.date')
            pub_date = parse_date(date_el.get_text() if date_el else None)
            if not title or not pub_date:
                continue
            desc_el = card.select_one('p.long-description') or card.select_one('p.short-description')
            summary = clean_text(desc_el.get_text()) if desc_el else ''
            out.append({
                'firm': firm, 'title': title, 'published_date': pub_date,
                'report_type': guess_report_type(title, MarketReport.TYPE_RESEARCH_NOTE),
                'short_summary': summary,
                'source_url': absolute_url(base_url, a['href']),
            })
        return out

    def _extract_blackrock_listing(self, soup, base_url, firm):
        """blackrock.com/us/individual/insights — grid of article tiles."""
        out = []
        for card in soup.select('.article-cntnr'):
            a = card.select_one('a.article-wrapper-link')
            if not a or not a.get('href'):
                continue
            title_el = card.select_one('h2.title') or card.select_one('.title')
            title = clean_text(title_el.get_text()) if title_el else clean_text(a.get('title', ''))
            date_el = card.select_one('.attribution-text.date span') or card.select_one('.attribution-text span')
            pub_date = parse_date(date_el.get_text() if date_el else None)
            if not title or not pub_date:
                continue
            desc_el = card.select_one('.description')
            summary = clean_text(desc_el.get_text()) if desc_el else ''
            out.append({
                'firm': firm, 'title': title, 'published_date': pub_date,
                'report_type': guess_report_type(title, MarketReport.TYPE_RESEARCH_NOTE),
                'short_summary': summary,
                'source_url': absolute_url(base_url, a['href']),
            })
        return out

    def _extract_blackrock_weekly(self, soup, base_url, firm):
        """blackrock.com .../weekly-commentary — single current-week article
        (headline + first bullet takeaways), not a listing."""
        out = []
        headline = None
        for h2 in soup.find_all('h2', class_='extra-bold'):
            text = clean_text(h2.get_text())
            if text and text.lower() not in ('week ahead',):
                headline = text
                break
        if not headline:
            return out

        date_el = soup.select_one('.date-format')
        pub_date = parse_date(date_el.get_text() if date_el else None)
        if not pub_date:
            return out

        bullets = [clean_text(b.get_text()) for b in soup.select('.bullet-summary')]
        bullets = [b for b in bullets if b]
        summary = clean_text(' '.join(bullets[:2]))

        out.append({
            'firm': firm, 'title': headline, 'published_date': pub_date,
            'report_type': MarketReport.TYPE_WEEKLY_COMMENTARY,
            'short_summary': summary,
            'source_url': base_url,
        })
        return out
