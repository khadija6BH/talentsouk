"""Conservative Marrakech/API provenance rules. Never infer city from a region."""
import re
import unicodedata
from urllib.parse import urlsplit, urlunsplit, parse_qsl, urlencode

PROVIDER_HOSTS = {'jooble': ('jooble.org',), 'adzuna': ('adzuna.com', 'adzuna.co.uk'),
                  'arbeitnow': ('arbeitnow.com',), 'jobicy': ('jobicy.com',)}
SOURCE_NAMES = {'jooble': 'Jooble', 'adzuna': 'Adzuna', 'arbeitnow': 'Arbeitnow', 'jobicy': 'Jobicy'}


def normalized(value):
    value = unicodedata.normalize('NFKD', str(value or '')).casefold()
    return ''.join(c for c in value if not unicodedata.combining(c))


def marrakech_location(value):
    text = normalized(value)
    # Marrakech-Safi is a region containing several cities, not proof of city.
    text = re.sub(r'marrake(?:ch|sh)\s*[-–]\s*(?:safi|tensift\s*[-–]\s*al\s*haouz)', '', text)
    text = re.sub(r'مراكش\s*[-–]\s*(?:آسفي|اسفي)', '', text)
    if not re.search(r'\bmarrake(?:ch|sh)\b|مراكش', text):
        return False
    # Multiple explicitly different cities require review rather than inference.
    return not re.search(r'\b(?:casablanca|rabat|safi|essaouira|tanger|berrechid|ben guerir|benguerir)\b', text)


def canonical_url(value):
    parts = urlsplit(str(value or '').strip())
    host = (parts.hostname or '').lower()
    # Jooble regenerates click/ranking parameters for the same announcement.
    # Only these paths contain a complete stable job ID; generic URLs may need
    # their query parameters to identify a job and must keep them.
    if (host == 'jooble.org' or host.endswith('.jooble.org')) and re.fullmatch(r'/(?:desc|jdp)/-?\d+/?', parts.path):
        return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), '', ''))
    params = [(k,v) for k,v in parse_qsl(parts.query, keep_blank_values=True)
              if not k.casefold().startswith('utm_') and k.casefold() not in {'gclid','fbclid'}]
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip('/'), urlencode(sorted(params)), ''))


def exclusion_reason(row):
    if not marrakech_location(row.get('location')):
        return 'outside_marrakech_or_region_only'
    adapter = str(row.get('adapter') or '').lower()
    if adapter not in SOURCE_NAMES or row.get('source') != SOURCE_NAMES[adapter]:
        return 'api_import_provenance_not_recorded'
    if not str(row.get('title') or '').strip() or not str(row.get('company_name') or '').strip():
        return 'missing_title_or_company'
    try:
        parts = urlsplit(str(row.get('url') or '').strip())
        host = (parts.hostname or '').lower()
        if parts.scheme not in {'http','https'} or not host or parts.username or parts.password:
            return 'invalid_source_url'
        if not any(host == suffix or host.endswith('.' + suffix) for suffix in PROVIDER_HOSTS[adapter]):
            return 'source_url_needs_review'
    except ValueError:
        return 'invalid_source_url'
    fields = ' '.join(str(row.get(k) or '') for k in ('title','company_name','url')).casefold()
    if any(marker in fields for marker in ('example.com','example.invalid','localhost','demo offer','sample job','test company','fake job')):
        return 'placeholder_marker'
    return None


def clean_offers(rows):
    retained, excluded, seen = [], [], {}
    # Prefer latest check for an identical URL. Different URLs stay distinct.
    for original in sorted(rows, key=lambda r: (str(r.get('last_checked') or ''), r.get('id',0)), reverse=True):
        row = dict(original)
        reason = exclusion_reason(row)
        if reason is None:
            key = canonical_url(row['url'])
            if key in seen:
                reason = 'duplicate_source_url'
                row['duplicate_of'] = seen[key]
            else:
                seen[key] = row['id']
        if reason:
            excluded.append({**row, 'exclusion_reason': reason})
        else:
            retained.append({**row, 'normalized_city': 'Marrakech',
                             'verification': 'api_import_recorded; current_listing_not_individually_confirmed'})
    return retained, excluded
