"""Private dashboard summaries of saved records, not page visits or time spent."""
from datetime import datetime,timezone,timedelta
from backend.database import get_db_connection

SOURCES=[('Applications','applications','created_at','1=1','/applications'),
 ('CV versions','cv_versions','created_at','1=1','/cv-versions'),
 ('Interview practices completed','interview_sessions','completed_at',"completed_at != ''",'/interview-helper'),
 ('Projects started','proof_projects','created_at','1=1','/portfolio'),
 ('Skill exercises completed','skill_practice_attempts','created_at','1=1','/skill-practice')]

def saved_activity(user_id,today=None):
    today=today or datetime.now(timezone.utc).date()
    days=[dict(date=(today-timedelta(days=i)).isoformat(),count=0) for i in range(6,-1,-1)]
    counts={d['date']:d for d in days};groups=[]
    conn=get_db_connection()
    try:
        for label,table,column,condition,url in SOURCES:
            total=conn.execute(f'SELECT COUNT(*) FROM {table} WHERE user_id=? AND {condition}',(user_id,)).fetchone()[0]
            groups.append(dict(label=label,count=total,url=url))
            rows=conn.execute(f'SELECT date({column}) AS day,COUNT(*) AS n FROM {table} WHERE user_id=? AND {condition} AND date({column}) BETWEEN ? AND ? GROUP BY date({column})',
                (user_id,days[0]['date'],days[-1]['date']))
            for row in rows:counts[row['day']]['count']+=row['n']
    finally:conn.close()
    return dict(groups=groups,days=days,total=sum(g['count'] for g in groups),recent=sum(d['count'] for d in days),maximum=max(1,max(g['count'] for g in groups)),daily_maximum=max(1,max(d['count'] for d in days)))


def activity_calendar(user_id, today=None):
    """Daily saved actions belonging only to this user; UTC dates, no duration claims."""
    today = today or datetime.now(timezone.utc).date()
    counts = {}
    conn = get_db_connection()
    try:
        for _, table, column, condition, _ in SOURCES:
            rows = conn.execute(f"SELECT date({column}) AS day, COUNT(*) AS n FROM {table} WHERE user_id=? AND {condition} AND date({column})<=? GROUP BY date({column})", (user_id, today.isoformat()))
            for row in rows:
                if row['day']:
                    counts[row['day']] = counts.get(row['day'], 0) + row['n']
    finally:
        conn.close()
    years = sorted({today.year} | {int(day[:4]) for day in counts}, reverse=True)
    return dict(today=today.isoformat(), years=years, counts=counts)
