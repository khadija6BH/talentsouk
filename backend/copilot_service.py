"""Explainable weekly planning from saved goals and evidence, without AI claims."""
from datetime import date, timedelta
from urllib.parse import urlencode
from backend.database import get_db_connection, get_cv_builder_data, get_applications_for_user, get_reminders
from backend.career_dna_service import get_career_dna
from backend.radar_watch import relevance_reason


def ensure_copilot_schema(conn):
    conn.executescript("""
    CREATE TABLE IF NOT EXISTS career_plans (
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      week TEXT NOT NULL, goal TEXT NOT NULL DEFAULT '', created_at TEXT DEFAULT CURRENT_TIMESTAMP,
      PRIMARY KEY(user_id,week));
    CREATE TABLE IF NOT EXISTS career_tasks (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      week TEXT NOT NULL, task_key TEXT NOT NULL, title TEXT NOT NULL, reason TEXT NOT NULL,
      url TEXT NOT NULL, due_date TEXT NOT NULL, completed INTEGER NOT NULL DEFAULT 0,
      custom INTEGER NOT NULL DEFAULT 0, UNIQUE(user_id,week,task_key));
    """)


def week_start(today=None):
    today = today or date.today()
    return (today - timedelta(days=today.weekday())).isoformat()


def suggestions(user_id, today=None):
    today = today or date.today()
    goals = get_cv_builder_data(user_id)
    profile = get_career_dna(user_id)['profile']
    from backend.opportunity_radar import radar_data
    offers, _ = radar_data()
    relevant = [(o, relevance_reason(goals,o)) for o in offers]
    relevant = [(o,r) for o,r in relevant if r]
    relevant.sort(key=lambda pair: (pair[1].startswith('Matches your target position:'), bool(goals['target_location'] and goals['target_location'].casefold() in (pair[0].get('location') or '').casefold()), pair[0].get('publication_date') or pair[0].get('first_seen') or '', pair[0]['id']), reverse=True)
    applications = [dict(a) for a in get_applications_for_user(user_id)]
    reminders = [dict(r) for r in get_reminders(user_id)]
    tasks = []
    def add(key,title,reason,url):
        due = min(today + timedelta(days=len(tasks)), date.fromisoformat(week_start(today)) + timedelta(days=6))
        tasks.append(dict(task_key=key,title=title,reason=reason,url=url,due_date=due.isoformat()))
    if not goals['target_position'] and not goals['career_field']:
        add('goals','Choose your career goal','A target position or career field helps identify relevant offers.','/profile')
    if not profile.get('skills') or not profile.get('experience'):
        add('profile','Review my profile','Your saved profile needs skills or experience evidence to guide preparation.','/profile')
    if not profile.get('summary'):
        add('cv','Write a clear CV summary','Your saved profile has no professional summary yet.','/cv-builder')
    applied = {(a['company_id'], (a.get('position') or '').casefold()) for a in applications}
    candidates = [(o,r) for o,r in relevant if (o.get('company_id'), o['title'].casefold()) not in applied][:2]
    for offer,reason in candidates:
        add('offer:'+str(offer['id']), 'Review '+offer['title'],reason+' · '+(offer.get('company_name') or 'Company'), '/opportunities/'+str(offer['id']))
    target = candidates[0][0] if candidates else (relevant[0][0] if relevant else None)
    if target:
        query=urlencode({'offer_id':target['id']})
        add('skills:'+str(target['id']),'Choose one skill to improve','Compare documented skills with requirements for '+target['title']+'.','/skill-gap?'+query)
        if target.get('company_id'):
            add('cv:'+str(target['id']),'Tailor your CV for one offer','Prepare a CV version for '+target['title']+' before applying.','/cv-builder?'+urlencode({'company_id':target['company_id'],'offer_id':target['id']})+'#cv-optimizer-workspace')
    else:
        add('radar','Explore current opportunities','No saved offer currently matches your career goal. Check offers or refine your goal.','/opportunity-radar')
        add('skills','Choose one skill to improve','Review your skill roadmap and pick one practical exercise.','/skill-gap')
    from backend.portfolio_service import get_projects
    unfinished=[p for p in get_projects(user_id) if not p['completed']]
    if unfinished:
        proof=unfinished[0]
        add('portfolio:'+str(proof['id']),'Make progress on your proof project','Document a deliverable for '+proof['skill']+'.','/portfolio/projects/'+str(proof['id']))
    else:
        add('portfolio','Build proof of one skill','Choose a small project, verify the result and save evidence.','/portfolio')
    add('interview','Practice one interview answer','Work on a clear answer and review feedback before your next interview.','/interview-helper'+('?' + urlencode({'offer_id':target['id']}) if target else ''))
    for reminder in reminders:
        if not reminder['completed'] and reminder['due_date'] <= (today+timedelta(days=6)).isoformat():
            add('reminder:'+str(reminder['id']),'Review a scheduled follow-up','Your application reminder is due on '+reminder['due_date']+'.','/applications')
            break
    return goals, tasks[:10], relevant[:3]


def create_plan(user_id, today=None):
    goals,tasks,_=suggestions(user_id,today)
    week=week_start(today)
    conn=get_db_connection()
    try:
        with conn:
            conn.execute('INSERT INTO career_plans(user_id,week,goal) VALUES(?,?,?) ON CONFLICT(user_id,week) DO UPDATE SET goal=excluded.goal',(user_id,week,goals['target_position'] or goals['career_field'] or 'Choose your career goal'))
            for task in tasks:
                conn.execute('INSERT OR IGNORE INTO career_tasks(user_id,week,task_key,title,reason,url,due_date) VALUES(?,?,?,?,?,?,?)',(user_id,week,task['task_key'],task['title'],task['reason'],task['url'],task['due_date']))
    finally:conn.close()


def get_plan(user_id, week=None):
    week=week or week_start()
    conn=get_db_connection()
    try:
        plan=conn.execute('SELECT * FROM career_plans WHERE user_id=? AND week=?',(user_id,week)).fetchone()
        tasks=[dict(r) for r in conn.execute('SELECT * FROM career_tasks WHERE user_id=? AND week=? ORDER BY completed,due_date,id',(user_id,week))]
        history=[dict(r) for r in conn.execute('SELECT week,goal FROM career_plans WHERE user_id=? ORDER BY week DESC LIMIT 12',(user_id,))]
        return dict(plan) if plan else None,tasks,history
    finally:conn.close()


def change_task(user_id,task_id,values):
    conn=get_db_connection()
    try:
        with conn:
            return conn.execute('UPDATE career_tasks SET title=?,due_date=?,completed=? WHERE id=? AND user_id=?',(values['title'],values['due_date'],int(values['completed']),task_id,user_id)).rowcount
    finally:conn.close()


def add_custom_task(user_id,title,due_date):
    import uuid
    conn=get_db_connection()
    try:
        with conn:
            conn.execute('INSERT INTO career_tasks(user_id,week,task_key,title,reason,url,due_date,custom) VALUES(?,?,?,?,?,?,?,1)',(user_id,week_start(),'custom:'+uuid.uuid4().hex,title,'Added by you','/career-copilot',due_date))
    finally:conn.close()
