"""Private professional contacts, self-recorded interactions and follow-ups."""
from datetime import date
from urllib.parse import urlparse
from backend.database import get_db_connection

CHANNELS=('LinkedIn','Email','WhatsApp','Phone','Meeting','Other')
OUTCOMES=('No reply yet','Replied','Next step agreed','Closed')


def ensure_network_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS network_contacts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL,role TEXT NOT NULL DEFAULT '',company_id INTEGER NOT NULL DEFAULT 0,
      company_name TEXT NOT NULL DEFAULT '',email TEXT NOT NULL DEFAULT '',profile_url TEXT NOT NULL DEFAULT '',
      source TEXT NOT NULL DEFAULT '',source_url TEXT NOT NULL DEFAULT '',notes TEXT NOT NULL DEFAULT '',
      next_followup TEXT NOT NULL DEFAULT '',archived INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS network_interactions (
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      contact_id INTEGER NOT NULL REFERENCES network_contacts(id) ON DELETE CASCADE,
      happened_on TEXT NOT NULL,channel TEXT NOT NULL,direction TEXT NOT NULL,outcome TEXT NOT NULL,
      body TEXT NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP);
    CREATE TABLE IF NOT EXISTS network_followup_alerts (
      contact_id INTEGER NOT NULL REFERENCES network_contacts(id) ON DELETE CASCADE,
      due_date TEXT NOT NULL,PRIMARY KEY(contact_id,due_date));
    """)


def safe_link(value):
    value=str(value or '').strip()
    if not value:return ''
    parsed=urlparse(value)
    if len(value)>2000 or parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in value):raise ValueError('Use an HTTP or HTTPS link without credentials.')
    return value


def contacts(user_id,company_id=None,archived=False):
    conn=get_db_connection()
    try:
        sql='SELECT * FROM network_contacts WHERE user_id=? AND archived=?';args=[user_id,int(archived)]
        if company_id is not None:sql+=' AND company_id=?';args.append(company_id)
        rows=[dict(r) for r in conn.execute(sql+" ORDER BY CASE WHEN next_followup='' THEN 1 ELSE 0 END,next_followup,name,id",args)]
        for row in rows:row['due']=bool(row['next_followup'] and row['next_followup']<=date.today().isoformat())
        return rows
    finally:conn.close()


def contact(user_id,contact_id):
    conn=get_db_connection()
    try:
        row=conn.execute('SELECT * FROM network_contacts WHERE id=? AND user_id=?',(contact_id,user_id)).fetchone()
        return dict(row) if row else None
    finally:conn.close()


def save_contact(user_id,values,contact_id=None):
    fields={'name':200,'role':200,'company_name':250,'email':250,'source':250,'notes':4000}
    data={key:str(values.get(key,'')).strip() for key in fields}
    if not data['name'] or any(len(data[k])>limit for k,limit in fields.items()):raise ValueError('Enter a contact name and keep text within the indicated limits.')
    if data['email'] and ('@' not in data['email'] or any(c.isspace() for c in data['email']) or '\r' in data['email'] or '\n' in data['email']):raise ValueError('Enter a valid email address.')
    data.update(profile_url=safe_link(values.get('profile_url')),source_url=safe_link(values.get('source_url')),next_followup=str(values.get('next_followup') or '').strip(),company_id=int(values.get('company_id') or 0))
    if data['next_followup']:date.fromisoformat(data['next_followup'])
    conn=get_db_connection()
    try:
        with conn:
            if contact_id:
                sql=','.join(k+'=?' for k in data)
                return contact_id if conn.execute('UPDATE network_contacts SET '+sql+',updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(*data.values(),contact_id,user_id)).rowcount else None
            keys=','.join(data);marks=','.join('?' for _ in data)
            return conn.execute('INSERT INTO network_contacts(user_id,'+keys+') VALUES(?,'+marks+')',(user_id,*data.values())).lastrowid
    finally:conn.close()


def archive_contact(user_id,contact_id,archived):
    conn=get_db_connection()
    try:
        with conn:return conn.execute('UPDATE network_contacts SET archived=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(int(archived),contact_id,user_id)).rowcount
    finally:conn.close()


def interactions(user_id,contact_id=None,company_id=None):
    conn=get_db_connection()
    try:
        sql='SELECT i.*,c.name,c.company_id FROM network_interactions i JOIN network_contacts c ON c.id=i.contact_id WHERE i.user_id=? AND c.user_id=?';args=[user_id,user_id]
        if contact_id is not None:sql+=' AND i.contact_id=?';args.append(contact_id)
        if company_id is not None:sql+=' AND c.company_id=?';args.append(company_id)
        return [dict(r) for r in conn.execute(sql+' ORDER BY i.happened_on DESC,i.id DESC LIMIT 100',args)]
    finally:conn.close()


def add_interaction(user_id,contact_id,values):
    if not contact(user_id,contact_id):return False
    happened_on=str(values.get('happened_on',''));date.fromisoformat(happened_on)
    if happened_on>date.today().isoformat():raise ValueError('Choose today or a past date for recorded activity.')
    body=str(values.get('body','')).strip()
    channel=values.get('channel');direction=values.get('direction');outcome=values.get('outcome')
    if not body or len(body)>4000 or channel not in CHANNELS or direction not in {'Sent by me','Received','Meeting'} or outcome not in OUTCOMES:raise ValueError('Choose an activity type and add a short record of the conversation.')
    conn=get_db_connection()
    try:
        with conn:conn.execute('INSERT INTO network_interactions(user_id,contact_id,happened_on,channel,direction,outcome,body) VALUES(?,?,?,?,?,?,?)',(user_id,contact_id,happened_on,channel,direction,outcome,body))
    finally:conn.close()
    return True


def message_drafts(person,target=''):
    name=person['name'];company=person['company_name'] or '[company]';role=target or '[target role]'
    return {
      'English introduction':f'Hello {name}, I am interested in {role} opportunities at {company}. I would appreciate any advice on the team or the application process. Thank you for your time.',
      'Introduction française':f'Bonjour {name}, je m’intéresse aux opportunités de {role} chez {company}. Auriez-vous un conseil sur l’équipe ou le processus de candidature ? Merci pour votre temps.',
      'English follow-up':f'Hello {name}, I wanted to follow up on our previous exchange about {role}. Please let me know if there is a useful next step. Thank you.',
      'Relance française':f'Bonjour {name}, je reviens vers vous à propos de notre précédent échange concernant {role}. Pourriez-vous me préciser la prochaine étape, si une suite est possible ? Merci.'}


def emit_due_followups(today=None):
    today=(today or date.today()).isoformat()
    conn=get_db_connection()
    try:
        with conn:
            rows=conn.execute("SELECT c.* FROM network_contacts c LEFT JOIN user_settings s ON s.user_id=c.user_id WHERE c.archived=0 AND c.next_followup<>'' AND c.next_followup<=? AND COALESCE(s.email_notifications,1)=1 AND COALESCE(s.notification_frequency,'instant')<>'off'",(today,)).fetchall()
            for row in rows:
                inserted=conn.execute('INSERT OR IGNORE INTO network_followup_alerts(contact_id,due_date) VALUES(?,?)',(row['id'],row['next_followup']))
                if inserted.rowcount:conn.execute("INSERT INTO notifications(user_id,kind,title,message,url) VALUES(?,'networking',?,?,?)",(row['user_id'],'Follow up with '+row['name'],'Your reminder is due on '+row['next_followup']+'. Review the conversation before contacting them.','/networking/'+str(row['id'])))
    finally:conn.close()


def company_insights(user_id,company_id,offers):
    from backend.skill_gap_service import SKILLS,_contains
    from collections import Counter
    counts=Counter()
    for offer in offers:
        text=' '.join(str(offer.get(k) or '') for k in ('title','description','requirements'))
        for skill,_ in SKILLS:
            if _contains(text,skill):counts[skill]+=1
    conn=get_db_connection()
    try:
        metadata={}
        if conn.execute("SELECT 1 FROM sqlite_master WHERE name='offer_sync_metadata'").fetchone():
            ids={o['id'] for o in offers}
            metadata={r['offer_id']:dict(r) for r in conn.execute('SELECT * FROM offer_sync_metadata') if r['offer_id'] in ids}
    finally:conn.close()
    return dict(skills=counts.most_common(10),contacts=contacts(user_id,company_id),activity=interactions(user_id,company_id=company_id),metadata=metadata)
