"""Export clean API offers and quarantine/report JSON; never delete/update data.

Run with --check-live to compare one live Jooble Marrakech response. An HTTP/API
response is evidence of retrieval, not a guarantee an employer is genuine or
that all historical listings remain active. Credentials are never exported.
"""
import argparse
import json
import sys
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT))


def run(output, check_live=False):
    load_dotenv(ROOT / '.env', override=True)
    from backend.database import get_db_connection, uses_postgres
    from backend.offer_cleaning import clean_offers, canonical_url, marrakech_location
    output.mkdir(parents=True, exist_ok=False)
    conn = get_db_connection()
    try:
        # Consistent read-only snapshot, even if the background importer is active.
        conn.execute('BEGIN')
        if uses_postgres():
            conn.raw.execute('SET TRANSACTION ISOLATION LEVEL REPEATABLE READ READ ONLY')
        rows = [dict(r) for r in conn.execute('''SELECT o.*,m.adapter,m.first_seen,m.last_checked
            FROM offers o LEFT JOIN offer_sync_metadata m ON m.offer_id=o.id ORDER BY o.id''')]
        recent = [dict(r) for r in conn.execute('SELECT * FROM opportunity_refreshes ORDER BY id DESC LIMIT 10')]
        conn.rollback()
    finally:
        conn.close()
    cleaned, excluded = clean_offers(rows)
    report = {'checked_at_utc': datetime.now(timezone.utc).isoformat(),
              'backend': 'PostgreSQL' if uses_postgres() else 'SQLite',
              'database_was_modified': False, 'raw_total': len(rows),
              'raw_by_source': dict(Counter(r['source'] for r in rows)),
              'raw_with_api_sync_metadata': sum(bool(r['adapter']) for r in rows),
              'clean_api_marrakech_total': len(cleaned),
              'clean_by_source': dict(Counter(r['source'] for r in cleaned)),
              'excluded_total': len(excluded),
              'exclusions': dict(Counter(r['exclusion_reason'] for r in excluded)),
              'recent_refreshes': recent,
              'limitations': ['Historical API sync metadata does not confirm that every old listing is still active.',
                  'Legacy Trabajo.org rows without API sync evidence are unverified provenance, not automatically demo.',
                  'Only an explicitly identified Marrakech city is accepted; a Marrakech-Safi region alone is excluded.',
                  'No source records, applications, CVs or relationships were changed.']}
    if check_live:
        from backend.job_sources import fetch_offers, JobSourceError
        try:
            live, skipped = fetch_offers('jooble','ma',location='Marrakech')
            stored_urls = {canonical_url(r['url']) for r in rows if r.get('url')}
            matching = [r for r in live if marrakech_location(r['location'])]
            report['live_jooble_check'] = {'status': 'ok', 'returned': len(live), 'marrakech_city': len(matching),
                'urls_already_in_database': sum(canonical_url(r['url']) in stored_urls for r in matching),
                'note': 'Single response page; unmatched historical rows are not labelled fake or expired.'}
            (output/'live_jooble_marrakech.json').write_text(json.dumps(matching,ensure_ascii=False,indent=2),encoding='utf-8')
        except JobSourceError as error:
            report['live_jooble_check'] = {'status': 'unavailable', 'reason': str(error)}
    for name, data in [('api_offers_marrakech.json',cleaned),('excluded_offers_review.json',excluded),('audit_report.json',report)]:
        (output/name).write_text(json.dumps(data,ensure_ascii=False,indent=2),encoding='utf-8')
    print(json.dumps({k:v for k,v in report.items() if k not in {'recent_refreshes','limitations'}}))
    print('Output: '+str(output.resolve()))


if __name__=='__main__':
    p=argparse.ArgumentParser()
    p.add_argument('--output',type=Path,default=ROOT/'data'/'offer_cleaning'/datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S'))
    p.add_argument('--check-live',action='store_true')
    args=p.parse_args();run(args.output,args.check_live)
