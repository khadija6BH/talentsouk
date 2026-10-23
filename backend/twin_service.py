"""Hypothetical skill coverage, kept separate from actual candidate evidence."""
import json
from backend.database import get_db_connection
from backend.portfolio_service import CATALOG,canonical_skill
from backend.skill_gap_service import _contains


def ensure_twin_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS career_scenarios (
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      name TEXT NOT NULL,skills_json TEXT NOT NULL,offer_ids_json TEXT NOT NULL,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def validate_skills(values):
    if not isinstance(values,list) or len(values)>6:raise ValueError('Choose up to six skills for one scenario.')
    skills=[]
    for value in values:
        skill=canonical_skill(value)
        if not skill:raise ValueError('Choose skills from the list.')
        if skill not in skills:skills.append(skill)
    return skills


def simulate_skills(profile,offers,skills):
    skills=validate_skills(skills)
    evidence=' '.join(str(profile.get(k) or '') for k in ('skills','summary','experience','education','projects','certifications'))
    reports=[]
    for offer in offers:
        text=' '.join(str(offer.get(k) or '') for k in ('title','description','requirements'))
        mentions=[name for name in CATALOG if _contains(text,name)]
        documented=[name for name in mentions if _contains(evidence,name)]
        hypothetical=[name for name in mentions if name in skills and name not in documented]
        baseline=round(100*len(documented)/len(mentions)) if mentions else None
        future=round(100*(len(documented)+len(hypothetical))/len(mentions)) if mentions else None
        reports.append(dict(offer=offer,baseline=baseline,future=future,gain=future-baseline if baseline is not None else None,documented=documented,hypothetical=hypothetical,remaining=[s for s in mentions if s not in documented and s not in hypothetical],mentions=mentions))
    reports.sort(key=lambda r:(r['gain'] is not None,r['gain'] or 0,r['future'] or 0,r['baseline'] or 0,-r['offer']['id']),reverse=True)
    return reports


def save_scenario(user_id,name,skills,offer_ids):
    skills=validate_skills(skills);name=str(name or '').strip()
    if not skills or not name or len(name)>120 or not offer_ids or len(offer_ids)>10 or any(type(i) is not int or i<=0 for i in offer_ids):raise ValueError('Enter a scenario name, choose skills and include one to ten saved offers.')
    conn=get_db_connection()
    try:
        with conn:
            existing=conn.execute('SELECT id FROM career_scenarios WHERE user_id=? AND name=? AND skills_json=? AND offer_ids_json=?',(user_id,name,json.dumps(skills),json.dumps(offer_ids))).fetchone()
            if existing:return existing['id']
            return conn.execute('INSERT INTO career_scenarios(user_id,name,skills_json,offer_ids_json) VALUES(?,?,?,?)',(user_id,name,json.dumps(skills),json.dumps(offer_ids))).lastrowid
    finally:conn.close()


def scenarios(user_id,scenario_id=None):
    conn=get_db_connection()
    try:
        query='SELECT * FROM career_scenarios WHERE user_id=?';args=[user_id]
        if scenario_id is not None:query+=' AND id=?';args.append(scenario_id)
        result=[]
        for row in conn.execute(query+' ORDER BY id DESC LIMIT 30',args):
            item=dict(row);item['skills']=json.loads(item.pop('skills_json'));item['offer_ids']=json.loads(item.pop('offer_ids_json'));result.append(item)
        return result
    finally:conn.close()
