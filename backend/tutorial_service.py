"""An optional, account-scoped tour. Progress is stored with account preferences."""
import json
from backend.database import get_db_connection

STEPS=[
 {'endpoint':'dashboard','selector':'.journey-hero','title':'Your career home','text':'Start here to see your activity and decide your next move. Browse offers, explore companies, or open your career tools.','label':'Dashboard'},
 {'endpoint':'companies','selector':'.directory-filters','title':'Find the right companies','text':'Search by name or activity. Use domains such as Génie civil, Construction / BTP or Tech, then combine location and contact filters. Open a company to explore its details.','label':'Companies'},
 {'endpoint':'cv_builder','selector':'.cv-source-switch','title':'Bring your experience into your CV','text':'Start from an uploaded CV or create one manually. Edit each section, choose a template, review the live preview, then save and export your CV.','label':'CV Builder'},
 {'endpoint':'cv_builder','selector':'#cv-portrait-studio > summary','title':'An optional professional portrait','text':'Open AI Portrait Studio if you want to turn a photo of yourself into a professional portrait. You choose whether to use a result in your CV, your app profile, or both. You can also keep your avatar.','label':'AI portraits'},
 {'endpoint':'ai_studio','args':{'tab':'recommendations'},'selector':'.ai-tabs','title':'Find opportunities for your profile','text':'In For your CV, choose your CV and find relevant jobs and companies. Other tabs help compare a role, tailor your CV and prepare a cover letter. Review every AI suggestion before using it.','label':'AI Career Studio'},
 {'endpoint':'applications','selector':'.pipeline-toolbar','title':'Keep track of your applications','text':'Use the board or list to follow your applications, replies and interviews. Filter by status to see what needs attention. You stay in control of sending applications.','label':'Applications'},
 {'endpoint':'profile','selector':'.profile-summary-card','title':'Keep your professional story current','text':'Update your experience, contact details and career goals. Your photo is optional, and your avatar and theme can be changed whenever you like.','label':'Your profile'},
 {'endpoint':'settings','selector':'.settings-side-nav','title':'Make the workspace work for you','text':'Manage appearance, notifications, language, AI preferences and connections here. You can replay this tutorial from General whenever you need a refresher.','label':'Settings'},
]
DEFAULT={'status':'not_started','step':0}


def get_tutorial(user_id):
    if not user_id:return dict(DEFAULT)
    conn=get_db_connection()
    try:
        row=conn.execute('SELECT appearance_json FROM user_settings WHERE user_id=?',(user_id,)).fetchone()
        value=json.loads(row['appearance_json']) if row else {}
        state=value.get('tutorial',{})
        if state.get('status') not in {'running','skipped','completed'}:return dict(DEFAULT)
        step=state.get('step',0)
        if not isinstance(step,int) or not 0<=step<len(STEPS):return dict(DEFAULT)
        return {'status':state['status'],'step':step}
    except (ValueError,TypeError,AttributeError):return dict(DEFAULT)
    finally:conn.close()


def change_tutorial(user_id,action):
    if not isinstance(action,str) or action not in {'start','resume','next','previous','skip','finish'}:raise ValueError('Choose a valid tutorial action.')
    state=get_tutorial(user_id)
    if action=='start':state={'status':'running','step':0}
    elif action=='resume':state['status']='running'
    elif action=='skip':state['status']='skipped'
    elif state['status']!='running':raise ValueError('Start the tutorial before moving between steps.')
    elif action=='previous':state['step']=max(0,state['step']-1)
    elif action=='next':
        if state['step']==len(STEPS)-1:state['status']='completed'
        else:state['step']+=1
    elif action=='finish':
        if state['step']!=len(STEPS)-1:raise ValueError('Use Next to continue the tutorial, or Skip to leave.')
        state['status']='completed'
    conn=get_db_connection()
    try:
        row=conn.execute('SELECT appearance_json FROM user_settings WHERE user_id=?',(user_id,)).fetchone()
        try:value=json.loads(row['appearance_json']) if row else {}
        except (TypeError,ValueError):value={}
        if not isinstance(value,dict):value={}
        value['tutorial']=state
        conn.execute("""INSERT INTO user_settings(user_id,appearance_json) VALUES (?,?) ON CONFLICT(user_id) DO UPDATE SET appearance_json=excluded.appearance_json,updated_at=CURRENT_TIMESTAMP""",(user_id,json.dumps(value)))
        conn.commit()
    finally:conn.close()
    return state
