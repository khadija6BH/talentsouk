"""Read-time company normalization; original records and IDs are preserved."""
import re
import unicodedata
from urllib.parse import urlsplit

def normalized(value):
    return ''.join(c for c in unicodedata.normalize('NFKD',str(value or '')) if not unicodedata.combining(c)).casefold()

def official_site(value):
    raw=str(value or '').strip()
    if not raw or raw.casefold() in {'nan','none','null','n/a','-'}:return ''
    if '://' not in raw:raw='https://'+raw
    try:
        parsed=urlsplit(raw)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or '.' not in parsed.hostname or parsed.username or parsed.password:return ''
        host=parsed.hostname.lower()
        if any(host==h or host.endswith('.'+h) for h in ('facebook.com','instagram.com','linkedin.com','google.com','goo.gl','maps.app.goo.gl','wa.me','adzuna.com','arbeitnow.com','trabajo.org','jooble.org','jobicy.com')):return ''
        return raw
    except ValueError:return ''

def in_morocco(company):
    text=normalized(str(company.get('area') or '')+' '+str(company.get('address') or ''))
    if re.search(r'\b(morocco|maroc|المغرب|marrakech|marrakesh|casablanca|rabat|agadir|tanger|tangier|fes|fez|meknes|oujda|kenitra|tetouan|safi|el jadida|beni mellal|sale|essaouira|nador|berrechid|bouskoura|temara)\b',text):return True
    try:
        lat=float(company.get('lat'));lng=float(company.get('lng'))
        if 27.5<=lat<=36 and -13.5<=lng<=-1:return True
    except (TypeError,ValueError):pass
    site=official_site(company.get('website'))
    return bool(site and urlsplit(site).hostname.endswith('.ma'))

CIVIL_DOMAIN = 'Génie civil'
CONSTRUCTION_DOMAIN = 'Construction / BTP'


def attach_domains(raw,offers=()):
    company=dict(raw)
    text=normalized(' '.join(str(company.get(key) or '') for key in ('name','category','description','website'))+' '+' '.join(str(offer.get('title') or '')+' '+str(offer.get('requirements') or '') for offer in offers))
    civil=r'\bgenie civil\b|\bcivil engineer(?:ing)?\b|\bingenieur(?:e)? (?:en )?structures?\b|\bstructural engineer|geotechni|topograph|\bgeometre\b|\bbeton arme\b|\bbureau d.etudes techniques\b|\bvrd\b|الهندسة المدنية'
    construction=r'\bconstruction\b|\bbtp\b|\bbatiment\b|\bbuilding contractor\b|\bgeneral contractor\b|\btravaux publics\b|\bgros oeuvre\b|\bchantier\b|\bmaconnerie\b|\bentreprise generale\b|البناء|الأشغال العمومية'
    inferred=[]
    if re.search(civil,text):inferred.append(CIVIL_DOMAIN)
    if re.search(construction,text):inferred.append(CONSTRUCTION_DOMAIN)
    category=str(company.get('category') or 'Other').strip() or 'Other'
    company['domains']=list(dict.fromkeys([category,*inferred]))
    company['display_category']=inferred[0] if inferred else category
    return company


def company_option_groups(companies):
    groups={}
    for company in companies:
        row=attach_domains(company)
        # Keep offer-based enrichment when the caller has already supplied it.
        group=company.get('display_category') or row['display_category']
        groups.setdefault(group,[]).append(row)
    return [(label,sorted(rows,key=lambda row:normalized(row.get('name')))) for label,rows in sorted(groups.items(),key=lambda pair:normalized(pair[0]))]


def enrich_catalog(companies,offers):
    by_company={}
    for offer in offers:
        by_company.setdefault(offer.get('company_id'),[]).append(offer)
    result=[]
    for raw in companies:
        company=dict(raw)
        for key in ('name','category','area','address','email','phone','description'):
            value=str(company.get(key) or '').strip()
            company[key]='' if value.casefold() in {'nan','none','null','n/a'} else value
        company['category']=company['category'] or 'Other' 
        company['website']=official_site(company.get('website'))
        linked=by_company.get(company['id'],[])
        text=normalized(' '.join(str(company.get(k) or '') for k in ('name','category','description','website'))+' '+' '.join(str(o.get('title') or '')+' '+str(o.get('requirements') or '') for o in linked))
        groups={'Web / Software':r'technolog|web|software|logiciel|developpe|frontend|backend|javascript|python', 'IT / Networks':r'informati|\bit\b|reseau|network|telecom', 'Data / AI':r'\bdata\b|\bai\b|intelligence artificielle|machine learning|\bsql\b', 'Cloud / DevOps':r'cloud|devops', 'Cybersecurity':r'cyber|securite informatique', 'Digital':r'digital|agence seo|referencement'}
        company['tech_specialties']=[label for label,pattern in groups.items() if re.search(pattern,text)]
        company['is_tech']=bool(company['tech_specialties'])
        company=attach_domains(company,linked)
        company['is_morocco']=in_morocco(company)
        company['sources']=sorted({str(o.get('source') or '').strip() for o in linked if o.get('source')}|{str(company.get('data_source') or 'Local directory')})
        result.append(company)
    return sorted(result,key=lambda c:(not bool(c['website']),normalized(c['name'])))
