"""Hourly local market polling, explainable alerts, and database lease."""
import re
import os
import threading
import logging
from backend.database import get_db_connection, get_cv_builder_data, get_user_settings


def ensure_watch_schema(conn):
    conn.execute("CREATE TABLE IF NOT EXISTS radar_watch_state (id INTEGER PRIMARY KEY CHECK(id=1), last_started TEXT, last_finished TEXT, lease_until TEXT)")
    conn.execute("CREATE TABLE IF NOT EXISTS radar_source_checks (provider TEXT PRIMARY KEY, checked_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP, status TEXT NOT NULL, message TEXT NOT NULL)")
    conn.execute("CREATE TABLE IF NOT EXISTS offer_alerts (user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, offer_id INTEGER, PRIMARY KEY(user_id,offer_id))")
    if any(row[2] == 'offers' for row in conn.execute('PRAGMA foreign_key_list(offer_alerts)')):
        conn.execute('ALTER TABLE offer_alerts RENAME TO offer_alerts_legacy')
        conn.execute('CREATE TABLE offer_alerts (user_id INTEGER REFERENCES users(id) ON DELETE CASCADE, offer_id INTEGER, PRIMARY KEY(user_id,offer_id))')
        conn.execute('INSERT INTO offer_alerts SELECT user_id,offer_id FROM offer_alerts_legacy')
        conn.execute('DROP TABLE offer_alerts_legacy')



def alert_preferences():
    conn=get_db_connection()
    try:users=[r['id'] for r in conn.execute('SELECT id FROM users')]
    finally:conn.close()
    preferences=[]
    for uid in users:
        settings=get_user_settings(uid)
        profile=get_cv_builder_data(uid)
        manual=(profile.get('profiles') or {}).get('manual') or (profile.get('profiles') or {}).get('uploaded') or {}
        profile['target_position']=profile.get('target_position') or manual.get('job_title','')
        profile['alert_skills']=profile.get('target_skills') or manual.get('skills','')
        preferences.append((uid,profile))
    return preferences


def relevance_reason(profile,offer):
    text=(offer.get('title','')+' '+offer.get('description','')).casefold()
    title=offer.get('title','').casefold()
    from backend.offer_cleaning import marrakech_location
    target_location=str(profile.get('target_location') or '').strip()
    if target_location and target_location.casefold() not in {'morocco','maroc','remote','worldwide'} and not marrakech_location(target_location):return None
    skills=[x.strip().casefold() for x in re.split(r'[,;\n]',str(profile.get('alert_skills') or '')) if len(x.strip())>1]
    if skills and not any(re.search(r'(?<!\w)'+re.escape(skill)+r'(?!\w)',text) for skill in skills):return None
    role=str(profile.get('target_position') or '').strip()
    field=str(profile.get('career_field') or '').strip()
    ignored={'senior','junior','intern','stage','the','and','de','du','en','des','of','job'}
    words=[w for w in re.findall(r'[\w+#]+',role.casefold()) if len(w)>2 and w not in ignored]
    if words and all(re.search(r'(?<!\w)'+re.escape(w)+r'(?!\w)',title) for w in words):
        return 'Matches your target position: '+role
    domains={
        'software':['software','developer','développeur','frontend','backend','logiciel'],
        'informatique':['software','developer','développeur','informatique','logiciel'],
        'ai_data':['data analyst','data scientist','machine learning','artificial intelligence'],
        'data':['data analyst','data scientist','data engineer','business intelligence'],
        'cybersecurity':['cybersecurity','cybersécurité','security engineer','soc analyst'],
        'marketing':['marketing','seo','social media'],
        'finance':['finance','financial','comptab','accountant'],
        'cloud':['cloud','devops','sre']}
    if field:
        terms=domains.get(field.casefold(),[])
        if any(re.search(r'(?<!\w)'+re.escape(term)+r'(?!\w)',title) for term in terms):return 'Matches your career field: '+field
        if not terms and len(field)>2 and re.search(r'(?<!\w)'+re.escape(field.casefold())+r'(?!\w)',title):return 'Matches your career field: '+field
    return None


def notify_new_offers(conn,new_offers,preferences):
    ensure_watch_schema(conn)
    for uid,profile in preferences:
        for offer in new_offers:
            reason=relevance_reason(profile,offer)
            if not reason:continue
            cursor=conn.execute('INSERT OR IGNORE INTO offer_alerts(user_id,offer_id) VALUES(?,?)',(uid,offer['id']))
            if cursor.rowcount:
                conn.execute("INSERT INTO notifications(user_id,kind,title,message,url) VALUES(?,'opportunity',?,?,?)",(uid,'New matching offer: '+offer['title'],reason+' · '+offer.get('source',''),'/opportunities/'+str(offer['id'])))


def watch_status():
    conn=get_db_connection()
    try:
        state=conn.execute('SELECT * FROM radar_watch_state WHERE id=1').fetchone()
        checks=[dict(r) for r in conn.execute('SELECT * FROM radar_source_checks ORDER BY provider')]
        return dict(state) if state else {},checks
    finally:conn.close()


def run_cycle(*, include_profile_queries=True, pages=1):
    conn=get_db_connection()
    try:
        with conn:
            ensure_watch_schema(conn)
            conn.execute('INSERT OR IGNORE INTO radar_watch_state(id) VALUES(1)')
            cursor=conn.execute("UPDATE radar_watch_state SET last_started=CURRENT_TIMESTAMP,lease_until=datetime('now','+15 minutes') WHERE id=1 AND (lease_until IS NULL OR lease_until<CURRENT_TIMESTAMP) AND (last_started IS NULL OR last_started<=datetime('now','-15 minutes'))")
            if not cursor.rowcount:return False
    finally:conn.close()
    from backend.job_sources import source_status,JobSourceError,MARRAKECH_PROVIDERS
    from backend.opportunity_radar import refresh_external_offers
    preferences=alert_preferences()
    queries=[]
    status=source_status()
    for provider in MARRAKECH_PROVIDERS:
        if status.get(provider):queries.append((provider,'ma','','Marrakech'))
    # International adapters stay outside this Marrakech-only schedule.
    # Bound authenticated calls per hour; rotate extra user searches each hour.
    extras=[]
    for _,p in preferences:
        role=str(p.get('target_position') or '').strip()[:200]
        city='Marrakech'
        if role and status['jooble']:extras.append(('jooble','ma',role,city))
    extras=list(dict.fromkeys(extras))
    if extras and include_profile_queries:
        import time
        start=(int(time.time()//3600)*3)%len(extras)
        queries.extend((extras+extras)[start:start+min(3,len(extras))])
    try:
        for provider,country,keyword,city in queries:
            try:
                if pages == 1 or provider not in {'jooble','adzuna'}:
                    result=refresh_external_offers(provider,country,keyword,city)
                else:
                    result=refresh_external_offers(provider,country,keyword,city,pages=pages)
                state='ok';message=str(result['created'])+' new offers; '+str(result['updated'])+' checked'
            except (JobSourceError,ValueError) as error:state='error';message=str(error)
            except Exception:state='error';message='Source temporarily unavailable. Saved offers are preserved.'
            conn=get_db_connection()
            try:
                with conn:conn.execute("INSERT INTO radar_source_checks(provider,status,message) VALUES(?,?,?) ON CONFLICT(provider) DO UPDATE SET checked_at=CURRENT_TIMESTAMP,status=excluded.status,message=excluded.message",(provider,state,message))
            finally:conn.close()
    finally:
        conn=get_db_connection()
        try:
            with conn:conn.execute('UPDATE radar_watch_state SET last_finished=CURRENT_TIMESTAMP,lease_until=NULL WHERE id=1')
        finally:conn.close()
    return True


def notification_cycle():
    # Each source is isolated: a failed job refresh must never block reminders/mail.
    from backend.notification_events import emit_due_reminders
    from backend.networking_service import emit_due_followups
    from backend.notification_mail import deliver_pending
    for task in (emit_due_reminders, emit_due_followups, deliver_pending):
        try:
            task()
        except Exception:
            logging.getLogger(__name__).exception('Notification background task failed; will retry')


_worker_lock = threading.Lock()
_worker_threads = []


def start_watcher():
    with _worker_lock:
        if _worker_threads:
            return _worker_threads[0]

        def radar_loop():
            while True:
                try:
                    if os.environ.get("RADAR_AUTO_SYNC", "1") == "1":
                        run_cycle()
                except Exception:
                    logging.getLogger(__name__).exception('Radar background cycle failed; will retry')
                threading.Event().wait(60)

        def mail_loop():
            while True:
                notification_cycle()
                threading.Event().wait(60)

        for target, name in ((radar_loop, 'opportunity-radar'), (mail_loop, 'notifications')):
            thread = threading.Thread(target=target, name=name, daemon=True)
            thread.start()
            _worker_threads.append(thread)
        return _worker_threads[0]
