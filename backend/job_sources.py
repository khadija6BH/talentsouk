"""Official job API adapters. Credentials never leave the server response."""
import json
import os
import re
from datetime import datetime, timezone
from html import unescape
from urllib.parse import urlencode, urlparse
from urllib.request import Request, urlopen
from urllib.error import HTTPError, URLError

COUNTRIES = {'ma':'Morocco','fr':'France','gb':'United Kingdom','de':'Germany','us':'United States','remote':'Remote — Worldwide'}
PROVIDERS = {'jooble':'Jooble', 'adzuna':'Adzuna', 'arbeitnow':'Arbeitnow','jobicy':'Jobicy'}

class JobSourceError(ValueError):
    pass


def source_status():
    return {'jooble': bool(os.getenv('JOOBLE_API_KEY','').strip()),
            'adzuna': bool(os.getenv('ADZUNA_APP_ID','').strip() and os.getenv('ADZUNA_APP_KEY','').strip()),
            'arbeitnow': True, 'jobicy': True}


def _json(url, payload=None):
    body = json.dumps(payload).encode() if payload is not None else None
    request = Request(url, data=body, headers={'Accept':'application/json','Content-Type':'application/json','User-Agent':'TalentSouk/1.0'})
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(5_000_001)
            if len(raw)>5_000_000: raise JobSourceError('The source returned too much data. No offers were changed.')
            result = json.loads(raw)
            if not isinstance(result, dict): raise JobSourceError('Unexpected source response. No offers were changed.')
            return result
    except HTTPError as error:
        if error.code in (401,403): raise JobSourceError('Access refused by the source. Check the server credentials and account permissions.') from None
        if error.code == 429: raise JobSourceError('Source request limit reached. Try again later.') from None
        raise JobSourceError('The source is unavailable. No offers were changed.') from None
    except (URLError, TimeoutError, OSError, ValueError) as error:
        if isinstance(error,JobSourceError): raise
        raise JobSourceError('Could not read the source response. No offers were changed.') from None


def _jobicy_feed():
    from backend.database import get_db_connection
    conn=get_db_connection()
    try:
        conn.execute("CREATE TABLE IF NOT EXISTS public_job_feed_cache (provider TEXT PRIMARY KEY, payload TEXT NOT NULL, fetched_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)")
        row=conn.execute("SELECT payload FROM public_job_feed_cache WHERE provider='jobicy' AND fetched_at>datetime('now','-1 hour')").fetchone()
        if row:
            return json.loads(row['payload'])
        result=_json('https://jobicy.com/api/v2/remote-jobs?count=100')
        if not isinstance(result.get('jobs'),list):
            raise JobSourceError('Unexpected source response. No offers were changed.')
        conn.execute("INSERT INTO public_job_feed_cache(provider,payload) VALUES('jobicy',?) ON CONFLICT(provider) DO UPDATE SET payload=excluded.payload,fetched_at=CURRENT_TIMESTAMP",(json.dumps(result),))
        conn.commit()
        return result
    finally:
        conn.close()


def _text(value):
    return unescape(re.sub('<[^>]+>',' ',str(value or ''))).strip()


def fetch_offers(provider, country, keyword='', location='', page=1):
    if type(page) is not int or not 1 <= page <= 5:
        raise JobSourceError('Choose an API page between 1 and 5.')
    if provider not in PROVIDERS or country not in COUNTRIES:
        raise JobSourceError('Choose a valid source and country.')
    if provider == 'jooble' and country != 'ma':
        raise JobSourceError('This Jooble connection is for Morocco. Another country needs its own regional key.')
    if provider == 'adzuna' and country not in {'fr','gb','de','us'}:
        raise JobSourceError('Morocco is not enabled for this Adzuna connection. Choose France, UK, Germany or USA.')
    if provider == 'arbeitnow' and country != 'de':
        raise JobSourceError('This Arbeitnow connection provides the Germany feed. Choose Germany.')
    if provider == 'jobicy' and country != 'remote':
        raise JobSourceError('Choose Remote — Worldwide for Jobicy. Each offer shows its geographic eligibility.')
    if not source_status()[provider]:
        raise JobSourceError('This source needs credentials in the server .env file.')
    keyword=keyword.strip()[:200]; location=location.strip()[:200]
    if provider=='jooble':
        key=os.environ['JOOBLE_API_KEY'].strip()
        result=_json('https://ma.jooble.org/api/'+key, {'keywords':keyword,'location':location,'page':str(page)})
        items=result.get('jobs')
    elif provider=='adzuna':
        params={'app_id':os.environ['ADZUNA_APP_ID'].strip(),'app_key':os.environ['ADZUNA_APP_KEY'].strip(),
                'what':keyword,'where':location,'results_per_page':50,'sort_by':'date','content-type':'application/json'}
        result=_json('https://api.adzuna.com/v1/api/jobs/'+country+'/search/1?'+urlencode(params))
        items=result.get('results')
    elif provider=='jobicy':
        result=_jobicy_feed()
        items=result.get('jobs')
    else:
        result=_json('https://www.arbeitnow.com/api/job-board-api')
        items=result.get('data')
    if not isinstance(items,list) or any(not isinstance(item,dict) for item in items):
        raise JobSourceError('Unexpected source response. No offers were changed.')
    offers=[]
    skipped=0
    for item in items[:100]:
        if provider=='jooble':
            company=item.get('company');place=item.get('location');url=item.get('link');description=item.get('snippet');contract=item.get('type');published=item.get('updated')
        elif provider=='adzuna':
            company=(item.get('company') or {}).get('display_name');place=(item.get('location') or {}).get('display_name');url=item.get('redirect_url');description=item.get('description');contract=item.get('contract_type');published=item.get('created')
        elif provider=='jobicy':
            company=item.get('companyName');place=item.get('jobGeo');url=item.get('url');description=item.get('jobDescription') or item.get('jobExcerpt')
            contract=', '.join(str(v) for v in (item.get('jobType') or []));published=item.get('pubDate')
            item=dict(item,title=item.get('jobTitle'))
        else:
            company=item.get('company_name');place=item.get('location');url=item.get('url');description=item.get('description')
            contract=', '.join(str(v) for v in item.get('job_types',[]) or []);published=item.get('created_at')
            if isinstance(published,(int,float)):
                published=datetime.fromtimestamp(published,timezone.utc).isoformat()
        title=_text(item.get('title'));company=_text(company);place=_text(place);description=_text(description)
        if provider in {'arbeitnow','jobicy'} and ((keyword and keyword.casefold() not in (title+' '+company+' '+description).casefold()) or (location and location.casefold() not in place.casefold())):
            continue
        if not title or not company or not isinstance(url,str) or urlparse(url).scheme not in {'https','http'} or not urlparse(url).netloc:
            skipped+=1;continue
        offers.append({'title':title,'company_name':company,'location':place,'url':url,'description':description,
                       'offer_type':_text(contract),'publication_date':str(published or ''),'source':PROVIDERS[provider]})
    if items and skipped==len(items[:100]):
        raise JobSourceError('The source returned no usable offers. No offers were changed.')
    return offers, skipped
