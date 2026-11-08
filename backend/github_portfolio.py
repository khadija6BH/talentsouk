"""Public repository OAuth import for Portfolio Studio."""
import os, json, secrets, time, hashlib, base64
from urllib.parse import urlencode
from urllib.request import Request, urlopen
from urllib.error import URLError
from cryptography.fernet import Fernet, InvalidToken
from flask import session, request, redirect, url_for, flash, render_template, current_app
from backend.database import get_db_connection, get_cv_builder_data

def cipher():
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256((str(current_app.secret_key)+':github').encode()).digest()))

def connection(uid, value=None):
    if value is None: return get_cv_builder_data(uid)['templates'].get('github_connection', {})
    conn=get_db_connection()
    try:
        with conn:
            row=conn.execute('SELECT templates_json FROM cv_builder_data WHERE user_id=?',(uid,)).fetchone()
            data=json.loads(row['templates_json']) if row else {}
            data['github_connection']=value
            conn.execute('INSERT INTO cv_builder_data(user_id,templates_json) VALUES(?,?) ON CONFLICT(user_id) DO UPDATE SET templates_json=excluded.templates_json,updated_at=CURRENT_TIMESTAMP',(uid,json.dumps(data)))
    finally: conn.close()

def api(path, token=None, payload=None):
    headers={'Accept':'application/json','User-Agent':'TalentSouk'}
    if token: headers['Authorization']='Bearer '+token
    if payload is not None: headers['Content-Type']='application/json'
    try:
        with urlopen(Request('https://api.github.com'+path if path.startswith('/') else path, data=json.dumps(payload).encode() if payload is not None else None, headers=headers),timeout=15) as response: return json.load(response)
    except (URLError,ValueError): raise ValueError('GitHub unavailable or access expired. Reconnect and try again.') from None

def import_repo(uid, repo, summary, pid=0):
    from backend.portfolio_service import get_project, save_project
    if repo.get('private') or not repo.get('permissions',{}).get('push') or not repo.get('size'): raise ValueError('Choose a public repository you contribute to, containing project files.')
    summary=summary.strip()
    if not summary or len(summary)>2000: raise ValueError('Describe your contribution in 1 to 2,000 characters.')
    url='https://github.com/'+repo['full_name']
    if pid:
        project=get_project(uid,pid)
        if not project: raise ValueError('Project not found.')
        if len(project['checked'])!=len(project['checklist']): raise ValueError('Finish and save the checklist first.')
        save_project(uid,pid,project['checked'],url,summary,project['notes'],True)
        return pid
    conn=get_db_connection()
    try:
        with conn:
            key='GitHub:'+str(repo['id'])
            conn.execute('INSERT OR IGNORE INTO proof_projects(user_id,skill,title,brief,checklist_json,checked_json,evidence_url,summary,completed) VALUES(?,?,?,?,?,?,?,?,?)',(uid,key,repo['name'][:200],(repo.get('description') or '')[:2000],json.dumps(['Import repository and describe contribution']),'[0]',url,summary,1))
            return conn.execute('SELECT id FROM proof_projects WHERE user_id=? AND skill=? AND offer_id=0',(uid,key)).fetchone()['id']
    finally: conn.close()

def register(app, login_required):
    @app.route('/github/connect')
    @login_required
    def github_connect():
        if not os.getenv('GITHUB_CLIENT_ID') or not os.getenv('GITHUB_CLIENT_SECRET'):
            flash('GitHub requires administrator setup: GITHUB_CLIENT_ID and GITHUB_CLIENT_SECRET.','error')
            return redirect(url_for('portfolio'))
        state,verifier=secrets.token_urlsafe(32),secrets.token_urlsafe(48)
        session['github_oauth']=dict(state=state,verifier=verifier,issued=time.time(),uid=session['user_id'])
        challenge=base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b'=').decode()
        return redirect('https://github.com/login/oauth/authorize?'+urlencode(dict(client_id=os.environ['GITHUB_CLIENT_ID'],redirect_uri=url_for('github_callback',_external=True),state=state,scope='read:user',code_challenge=challenge,code_challenge_method='S256')))

    @app.route('/github/callback')
    @login_required
    def github_callback():
        flow=session.pop('github_oauth',{})
        if not flow or flow.get('uid')!=session['user_id'] or time.time()-flow.get('issued',0)>600 or not secrets.compare_digest(flow.get('state',''),request.args.get('state','')): return 'Invalid or expired GitHub request.',400
        try:
            result=api('https://github.com/login/oauth/access_token',payload=dict(client_id=os.environ['GITHUB_CLIENT_ID'],client_secret=os.environ['GITHUB_CLIENT_SECRET'],code=request.args.get('code',''),redirect_uri=url_for('github_callback',_external=True),code_verifier=flow['verifier']))
            token=result.get('access_token')
            if not token: raise ValueError('GitHub authorization cancelled or expired.')
            user=api('/user',token)
            connection(session['user_id'],dict(login=user['login'],token=cipher().encrypt(token.encode()).decode()))
            flash('GitHub connected. Choose a published project.','success')
        except ValueError as error: flash(str(error),'error')
        return redirect(url_for('github_repositories'))

    @app.route('/github/disconnect',methods=['POST'])
    @login_required
    def github_disconnect():
        if not secrets.compare_digest(request.form.get('csrf',''),session.get('github_csrf','!')): return 'Invalid request.',400
        connection(session['user_id'],{})
        flash('Disconnected. You can revoke authorization in GitHub Settings > Applications.','success')
        return redirect(url_for('portfolio'))

    @app.route('/github/repositories',methods=['GET','POST'])
    @login_required
    def github_repositories():
        from backend.portfolio_service import get_projects
        uid=session['user_id'];repos=[]
        page=max(1,min(100,request.args.get('page',1,type=int)))
        session.setdefault('github_csrf',secrets.token_urlsafe(32))
        try:
            account=connection(uid)
            if not account: return redirect(url_for('github_connect'))
            token=cipher().decrypt(account['token'].encode()).decode()
            repos=api('/user/repos?'+urlencode(dict(visibility='public',affiliation='owner,collaborator,organization_member',sort='updated',per_page=30,page=page)),token)
            if request.method=='POST':
                if not secrets.compare_digest(request.form.get('csrf',''),session['github_csrf']): return 'Invalid request.',400
                repo=next((r for r in repos if str(r['id'])==request.form.get('repository_id')),None)
                if not repo: raise ValueError('Choose a repository on this page.')
                pid=import_repo(uid,repo,request.form.get('summary',''),int(request.form.get('project_id') or 0))
                flash('Project imported. Completion is self-reported.','success')
                return redirect(url_for('portfolio_project',project_id=pid))
        except (ValueError,InvalidToken,KeyError) as error:
            flash(str(error) if isinstance(error,ValueError) else 'Reconnect GitHub to renew access.','error')
        return render_template('github_repositories.html',github=connection(uid),repos=repos,projects=[p for p in get_projects(uid) if not p['completed']],csrf=session['github_csrf'],page=page,active_page='portfolio')
