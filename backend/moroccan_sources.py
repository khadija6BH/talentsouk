"""Bounded public JobPosting collection from Moroccan job boards.

No login, private API or protection bypass. Robots rules and source links are
preserved. Only factual metadata with a real employer, date and Marrakech city
is imported; the full announcement remains on the publisher's website.
"""
import json
import re
import time
from datetime import datetime, timezone
from html import unescape
from html.parser import HTMLParser
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlsplit, parse_qs
from urllib.request import Request, build_opener, HTTPRedirectHandler
from urllib.robotparser import RobotFileParser

from backend.job_sources import JobSourceError
from backend.offer_cleaning import canonical_url, marrakech_location
from backend.offer_lifecycle import recent_offer

SOURCES = {
    'postule': ('Postule.ma', 'https://www.postule.ma/offres-emploi/marrakech', '/job/'),
    'jobradar': ('JobRadar.ma', 'https://www.jobradar.ma/emploi/ville/marrakech', '/offre/'),
    'marocemploi': ('MarocEmploi', 'https://marocemploi.net/marrakech/', '/offre/'),
}
USER_AGENT = 'TalentSouk/1.0 (+https://talentsouk.vercel.app/)'
MAX_DETAILS = 40
MAX_LISTINGS = 2
MAX_BYTES = 2_000_000


class PublicMarkup(HTMLParser):
    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.links = []
        self.structured = []
        self.current = None

    def handle_starttag(self, tag, attrs):
        attrs = dict(attrs)
        if tag == 'a' and attrs.get('href'):
            self.links.append(attrs['href'])
        if tag == 'script' and attrs.get('type', '').lower() == 'application/ld+json':
            self.current = []

    def handle_data(self, text):
        if self.current is not None:
            self.current.append(text)

    def handle_endtag(self, tag):
        if tag == 'script' and self.current is not None:
            try:
                self.structured.append(json.loads(''.join(self.current)))
            except ValueError:
                pass
            self.current = None


def _text(value):
    return ' '.join(unescape(re.sub('<[^>]+>', ' ', str(value or ''))).split())


def job_nodes(value):
    if isinstance(value, dict):
        kind = value.get('@type', [])
        kind = [kind] if isinstance(kind, str) else kind if isinstance(kind, list) else []
        if any(str(item).rstrip('/').split('/')[-1] == 'JobPosting' for item in kind):
            yield value
        else:
            for child in value.values():
                yield from job_nodes(child)
    elif isinstance(value, list):
        for child in value:
            yield from job_nodes(child)


def _date(value):
    try:
        parsed = datetime.fromisoformat(str(value or '').strip().replace('Z', '+00:00'))
        return parsed if parsed.tzinfo else parsed.replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def parse_jobposting(node, source, page_url, now=None):
    now = now or datetime.now(timezone.utc)
    if node.get('url') and canonical_url(urljoin(page_url,str(node['url']))) != canonical_url(page_url):
        return None
    organization = node.get('hiringOrganization') or {}
    if not isinstance(organization, dict):
        return None
    employer = _text(organization.get('name'))
    title = _text(node.get('title'))
    # An account email or missing employer is not an invented company name.
    if not title or not employer or '@' in employer or employer.casefold() in {'anonymous', 'anonyme', 'confidentiel', 'confidential'}:
        return None
    places = node.get('jobLocation') or []
    places = [places] if isinstance(places, dict) else places
    cities = []
    for place in places if isinstance(places, list) else []:
        address = place.get('address') if isinstance(place, dict) else None
        if not isinstance(address, dict):
            continue
        city = _text(address.get('addressLocality'))
        country = address.get('addressCountry') or ''
        country = country.get('name', '') if isinstance(country, dict) else country
        if country and str(country).strip().casefold() not in {'ma', 'maroc', 'morocco', 'المغرب'}:
            return None
        if city:
            cities.append(city)
    # A city-specific listing page or a region alone is not location evidence.
    if not cities or not all(marrakech_location(city) for city in cities):
        return None
    published = _date(node.get('datePosted'))
    if published is None:
        return None
    expiry = _date(node.get('validThrough'))
    if node.get('validThrough') and (expiry is None or expiry < now):
        return None
    contract = node.get('employmentType') or ''
    contract = ', '.join(_text(item) for item in contract) if isinstance(contract, list) else _text(contract)
    # Keep factual discovery data and attribution, not the publisher's full text.
    row = {'title': title[:300], 'company_name': employer[:240],
           'location': 'Marrakech, Maroc', 'publication_date': published.isoformat(),
           'url': canonical_url(page_url), 'offer_type': contract[:160], 'source': source,
           'description': f'{title[:300]} · {employer[:240]} · Marrakech. '
                          f'Contrat : {contract or "Voir l’annonce"}. Offre complète sur {source}.'}
    return row if recent_offer(row, now) else None


class SameOriginRedirect(HTTPRedirectHandler):
    def __init__(self, origin):
        self.origin = origin

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urlsplit(newurl)
        if target.scheme != 'https' or target.netloc != self.origin or target.username or target.password:
            raise JobSourceError('The job source redirected outside its public site.')
        return super().redirect_request(req, fp, code, msg, headers, newurl)


class PublicClient:
    def __init__(self, listing):
        parts = urlsplit(listing)
        self.origin = parts.netloc
        self.base = 'https://' + self.origin
        self.opener = build_opener(SameOriginRedirect(self.origin))
        self.deadline = time.monotonic() + 40
        self.last_request = 0
        self.delay = .25
        self.rules = RobotFileParser()
        try:
            rules = self._read(self.base + '/robots.txt', max_bytes=500_000)
        except HTTPError as error:
            if error.code not in (404, 410):
                raise JobSourceError('The source does not allow its crawling rules to be checked.') from None
            rules = 'User-agent: *\nAllow: /'
        self.rules.parse(rules.splitlines())
        crawl_delay = self.rules.crawl_delay('TalentSouk')
        if crawl_delay:
            if crawl_delay > 2:
                raise JobSourceError('The source requires a slower collection schedule.')
            self.delay = max(self.delay, crawl_delay)

    def _read(self, url, max_bytes=MAX_BYTES):
        parts = urlsplit(url)
        if parts.scheme != 'https' or parts.netloc != self.origin or parts.username or parts.password:
            raise JobSourceError('Invalid job source address.')
        time.sleep(max(0, self.delay - (time.monotonic() - self.last_request)))
        self.last_request = time.monotonic()
        remaining = self.deadline - time.monotonic()
        if remaining <= 0:
            raise JobSourceError('The source collection time limit was reached.')
        with self.opener.open(Request(url, headers={'User-Agent': USER_AGENT, 'Accept': 'text/html,text/plain'}), timeout=min(10,remaining)) as response:
            raw = response.read(max_bytes + 1)
            if len(raw) > max_bytes:
                raise JobSourceError('The source page is too large.')
            return raw.decode(response.headers.get_content_charset() or 'utf-8', errors='replace')

    def get(self, url):
        if not self.rules.can_fetch('TalentSouk', url):
            raise JobSourceError('The source does not allow collection of this page.')
        try:
            return self._read(url)
        except HTTPError as error:
            if error.code in (401, 403, 429):
                raise JobSourceError('The source refused collection or reached its request limit.') from None
            raise JobSourceError('The source page is temporarily unavailable.') from None
        except (URLError, OSError, TimeoutError):
            raise JobSourceError('The source could not be reached.') from None


def fetch_marrakech(provider, keyword='', location=''):
    if provider not in SOURCES:
        raise JobSourceError('Choose a supported Moroccan source.')
    if location and not marrakech_location(location):
        raise JobSourceError('This collection is limited to Marrakech.')
    source, listing, prefix = SOURCES[provider]
    try:
        client = PublicClient(listing)
        documents, listings, details = [], [listing], []
        visited = set()
        for page in listings:
            if len(visited) >= MAX_LISTINGS:
                break
            if page in visited:
                continue
            visited.add(page)
            document = PublicMarkup(); document.feed(client.get(page))
            documents.append(document)
            for href in document.links:
                url = urljoin(page, href)
                parts = urlsplit(url)
                if parts.scheme != 'https' or parts.netloc != urlsplit(listing).netloc:
                    continue
                if parts.path.startswith(prefix) and parts.path.rstrip('/') != prefix.rstrip('/'):
                    if url not in details:
                        details.append(url)
                elif parts.path == urlsplit(listing).path and parse_qs(parts.query).get('page'):
                    if url not in listings and len(listings) < MAX_LISTINGS and client.rules.can_fetch('TalentSouk',url):
                        listings.append(url)
        rows, seen, skipped, readable, structured_count = [], set(), 0, 0, 0
        for url in details[:MAX_DETAILS]:
            try:
                document = PublicMarkup(); document.feed(client.get(url))
                readable += 1
            except JobSourceError:
                skipped += 1
                if time.monotonic() >= client.deadline:
                    break
                continue
            found = list(job_nodes(document.structured))
            structured_count += len(found)
            if not found:
                skipped += 1
                continue
            for node in found:
                row = parse_jobposting(node, source, url)
                if not row:
                    skipped += 1
                    continue
                if keyword and keyword.casefold() not in (row['title']+' '+row['company_name']).casefold():
                    continue
                key = canonical_url(row['url'])
                if key not in seen:
                    rows.append(row); seen.add(key)
        if details and not readable:
            raise JobSourceError('The source detail pages could not be checked. Saved offers are preserved.')
        if not details:
            raise JobSourceError('The source listing format could not be read. Saved offers are preserved.')
        if readable and not structured_count:
            raise JobSourceError('The source job format could not be verified. Saved offers are preserved.')
        return rows, skipped
    except (HTTPError, URLError, OSError, TimeoutError):
        raise JobSourceError('The Moroccan source is temporarily unavailable.') from None
