"""Private, self-reported proof projects with explicit CV export."""
import json
from urllib.parse import urlparse
from backend.database import get_db_connection
from backend.skill_gap_service import SKILLS, SOFT_SKILLS

CATALOG=dict(SKILLS)
CATALOG.update({skill:'Professional' for skill in SOFT_SKILLS if skill not in CATALOG})

THEMES = {
    'orbit': {'name': 'Orbit', 'description': 'Midnight blue, electric accents and a bold project grid.', 'bg': '#101c30', 'ink': '#ecf4ff', 'accent': '#8ef0cf'},
    'folio': {'name': 'Folio', 'description': 'Warm paper, oversized typography and thoughtful case studies.', 'bg': '#f7f0e6', 'ink': '#302c29', 'accent': '#a74d35'},
    'bloom': {'name': 'Bloom', 'description': 'Soft violet, generous spacing and playful project cards.', 'bg': '#f0edff', 'ink': '#35245c', 'accent': '#7151b5'},
    'signal': {'name': 'Signal', 'description': 'Crisp white, cobalt details and a clear focus on your work.', 'bg': '#f5f8ff', 'ink': '#172d53', 'accent': '#225bd6'},
}


def studio_settings(user_id):
    from backend.database import get_cv_builder_data
    value = get_cv_builder_data(user_id)['templates'].get('portfolio_studio', {})
    value = value if isinstance(value, dict) else {}
    return {'theme': value.get('theme') if value.get('theme') in THEMES else 'orbit',
            'headline': str(value.get('headline') or ''), 'bio': str(value.get('bio') or '')}


def save_studio_settings(user_id, values):
    theme = values.get('theme', 'orbit')
    headline = str(values.get('headline', '')).strip()
    bio = str(values.get('bio', '')).strip()
    if theme not in THEMES or len(headline) > 180 or len(bio) > 2000:
        raise ValueError('Choose a design and keep your headline under 180 characters and introduction under 2,000.')
    conn = get_db_connection()
    try:
        with conn:
            row = conn.execute('SELECT templates_json FROM cv_builder_data WHERE user_id=?', (user_id,)).fetchone()
            templates = json.loads(row['templates_json']) if row else {}
            templates['portfolio_studio'] = dict(theme=theme, headline=headline, bio=bio)
            conn.execute('INSERT INTO cv_builder_data(user_id,templates_json) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET templates_json=excluded.templates_json,updated_at=CURRENT_TIMESTAMP', (user_id, json.dumps(templates)))
    finally:
        conn.close()


def suggested_projects(profile, target=''):
    from backend.skill_gap_service import _contains
    text = ' '.join(str(profile.get(k) or '') for k in ('skills', 'summary', 'experience', 'target_skills'))
    role = str(target).lower()
    priorities = []
    groups = [
        (('data', 'analyst', 'business intelligence'), ['SQL', 'Data Analysis', 'Python']),
        (('web', 'developer', 'software', 'frontend', 'fullstack'), ['JavaScript', 'React', 'Git']),
        (('cloud', 'devops', 'infrastructure'), ['Docker', 'Linux', 'CI/CD']),
        (('security', 'cyber', 'network'), ['Cybersecurity', 'Networking', 'Linux']),
        (('marketing', 'sales', 'business', 'finance'), ['Excel', 'Data Analysis', 'Communication']),
    ]
    for words, skills in groups:
        if any(word in role for word in words): priorities.extend((s, 'Useful practice for your target role') for s in skills)
    priorities.extend((s, 'Build evidence for a skill in your profile') for s in CATALOG if _contains(text, s))
    if not priorities: priorities = [(s, 'A starting point — add your target role for closer suggestions') for s in ('Excel', 'Communication', 'Project Management')]
    result = []
    for skill, reason in priorities:
        if any(p['skill'] == skill for p in result): continue
        result.append({**project_template(skill), 'reason': reason})
        if len(result) == 3: break
    return result


def ensure_portfolio_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS proof_projects (
      id INTEGER PRIMARY KEY AUTOINCREMENT,
      user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      skill TEXT NOT NULL, offer_id INTEGER NOT NULL DEFAULT 0,
      title TEXT NOT NULL, brief TEXT NOT NULL, checklist_json TEXT NOT NULL,
      checked_json TEXT NOT NULL DEFAULT '[]', evidence_url TEXT NOT NULL DEFAULT '',
      summary TEXT NOT NULL DEFAULT '', notes TEXT NOT NULL DEFAULT '',
      completed INTEGER NOT NULL DEFAULT 0, cv_added INTEGER NOT NULL DEFAULT 0,
      created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      updated_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP,
      UNIQUE(user_id,skill,offer_id))""")


def canonical_skill(value):
    return next((name for name in CATALOG if name.casefold()==str(value).strip().casefold()),None)


def project_template(skill):
    skill=canonical_skill(skill)
    if not skill:raise ValueError('Choose a skill from the list.')
    category=CATALOG[skill]
    if skill=='SQL':
        title='SQL: answer three questions with a small dataset'
        brief='Use a public or synthetic dataset in SQLite. Clean missing values, write queries with a JOIN and aggregation, and explain three findings.'
        checks=['Describe the dataset and three questions','Create tables and document the import','Save queries using JOIN, GROUP BY and filters','Check outputs with three known cases','Write findings, limitations and reproducible setup']
    elif skill=='Python':
        title='Python: build a command-line task tracker'
        brief='Build a small tracker that creates, lists and completes tasks. Persist entries in a local file and document how to run it.'
        checks=['Define inputs, commands and expected outputs','Implement add, list and complete commands','Persist tasks across restarts','Test empty input, invalid input and a successful flow','Document setup and show example output']
    elif skill in {'Power BI','Tableau','Excel','Data Analysis','Pandas'}:
        title=skill+': explain a dataset with a dashboard'
        brief='Use a public or synthetic dataset. Clean it, define three useful metrics and build a readable dashboard with an explanation of limitations.'
        checks=['Describe the dataset and its source','Document cleaning and missing values','Define three metrics and verify their calculations','Build a dashboard with labels and useful filters','Save screenshots and explain insights and limitations']
    elif skill in SOFT_SKILLS or category=='Professional':
        title=skill+': document a practical communication exercise'
        brief='Prepare a short project update or a STAR example from a real experience. Explain your own contribution, seek feedback if available, and improve your draft.'
        checks=['Describe a real context and objective','Write a first draft with your contribution','Record an example or save a written deliverable','Review clarity, structure and relevance','Save the revised version and explain one improvement']
    else:
        from backend.learning_service import learning_plan
        title=skill+': build a small practical demonstration'
        brief=learning_plan(skill,category)['actions'][1]
        checks=['Define a small objective and expected outcome','Implement a working demonstration using '+skill,'Document setup, inputs and outputs','Verify three cases and record the results','Save a deliverable and explain limitations']
    return dict(skill=skill,category=category,title=title,brief=brief,checklist=checks)


def _decode(row):
    result=dict(row)
    result['checklist']=json.loads(result.pop('checklist_json'))
    result['checked']=json.loads(result.pop('checked_json'))
    result['progress']=round(100*len(result['checked'])/len(result['checklist']))
    return result


def get_projects(user_id):
    conn=get_db_connection()
    try:return [_decode(row) for row in conn.execute('SELECT * FROM proof_projects WHERE user_id=? ORDER BY completed,updated_at DESC,id DESC',(user_id,))]
    finally:conn.close()


def get_project(user_id,project_id):
    conn=get_db_connection()
    try:
        row=conn.execute('SELECT * FROM proof_projects WHERE id=? AND user_id=?',(project_id,user_id)).fetchone()
        return _decode(row) if row else None
    finally:conn.close()


def create_project(user_id,skill,offer_id=0):
    template=project_template(skill)
    conn=get_db_connection()
    try:
        with conn:
            conn.execute('INSERT OR IGNORE INTO proof_projects(user_id,skill,offer_id,title,brief,checklist_json) VALUES(?,?,?,?,?,?)',(user_id,template['skill'],offer_id,template['title'],template['brief'],json.dumps(template['checklist'])))
            return conn.execute('SELECT id FROM proof_projects WHERE user_id=? AND skill=? AND offer_id=?',(user_id,template['skill'],offer_id)).fetchone()['id']
    finally:conn.close()


def save_project(user_id,project_id,checked,evidence_url,summary,notes,completed=False):
    project=get_project(user_id,project_id)
    if not project:return False
    if not isinstance(checked,list) or any(type(i) is not int or i not in range(len(project['checklist'])) for i in checked):raise ValueError('Choose valid checklist steps.')
    checked=sorted(set(checked))
    evidence_url=evidence_url.strip();summary=summary.strip();notes=notes.strip()
    if len(evidence_url)>2000 or len(summary)>2000 or len(notes)>4000:raise ValueError('Keep your evidence link, summary and notes within the indicated limits.')
    if evidence_url:
        parsed=urlparse(evidence_url)
        if parsed.scheme not in {'http','https'} or not parsed.hostname or parsed.username or parsed.password or any(c.isspace() for c in evidence_url):raise ValueError('Use a valid HTTP or HTTPS evidence link without credentials.')
    if completed and (len(checked)!=len(project['checklist']) or not evidence_url or not summary):raise ValueError('Finish the checklist, add an evidence link and describe your contribution before marking the project complete.')
    conn=get_db_connection()
    try:
        with conn:conn.execute('UPDATE proof_projects SET checked_json=?,evidence_url=?,summary=?,notes=?,completed=?,updated_at=CURRENT_TIMESTAMP WHERE id=? AND user_id=?',(json.dumps(checked),evidence_url,summary,notes,int(completed),project_id,user_id))
    finally:conn.close()
    return True


def readme_text(project):
    lines=['# '+project['title'],'','## Objective',project['brief'],'','## Skill',project['skill'],'','## Deliverables']
    lines += ['- ['+('x' if i in project['checked'] else ' ')+'] '+step for i,step in enumerate(project['checklist'])]
    lines += ['','## My contribution',project['summary'] or '[Describe only work you completed.]','','## Evidence',project['evidence_url'] or '[Add a repository, demo or document link.]','','## Setup and reproduction','[Explain prerequisites, steps and expected output.]','','## Validation and limitations',project['notes'] or '[Record test cases, results and limitations.]','','Completion is self-reported; it does not certify skill proficiency.','']
    return '\n'.join(lines)


def add_to_cv(user_id,project_id):
    project=get_project(user_id,project_id)
    if not project:return False
    if not project['completed']:raise ValueError('Complete the project and save your evidence before adding it to the CV.')
    from backend.database import get_cv_builder_data
    from backend.career_dna_service import get_career_dna
    builder=get_cv_builder_data(user_id)
    profile=get_career_dna(user_id)['profile']
    entry=project['title']+'\n'+project['summary']+'\n'+project['evidence_url']
    projects=(profile.get('projects') or '').strip()
    if entry not in projects:projects=(projects+'\n\n'+entry).strip()
    profiles=builder['profiles'];manual=profiles.get('manual',{})
    manual={**profile,**manual};manual['projects']=projects;profiles['manual']=manual
    conn=get_db_connection()
    try:
        with conn:
            fresh=conn.execute('SELECT cv_added FROM proof_projects WHERE id=? AND user_id=?',(project_id,user_id)).fetchone()
            if not fresh:return False
            if fresh['cv_added']:return True
            conn.execute("INSERT INTO cv_builder_data(user_id,profiles_json) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET profiles_json=excluded.profiles_json,updated_at=CURRENT_TIMESTAMP",(user_id,json.dumps(profiles)))
            dna=conn.execute('SELECT overrides_json FROM career_dna_profiles WHERE user_id=?',(user_id,)).fetchone()
            overrides=json.loads(dna['overrides_json']) if dna else {}
            overrides['projects']=projects
            conn.execute("INSERT INTO career_dna_profiles(user_id,overrides_json) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET overrides_json=excluded.overrides_json,updated_at=CURRENT_TIMESTAMP",(user_id,json.dumps(overrides)))
            conn.execute('UPDATE proof_projects SET cv_added=1 WHERE id=? AND user_id=?',(project_id,user_id))
    finally:conn.close()
    return True
