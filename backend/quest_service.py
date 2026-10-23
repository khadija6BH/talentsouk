"""Derived progress badges; no permanent rewards or invented activity streaks."""
from collections import defaultdict
from backend.database import get_cv_builder_data,get_cv_versions,get_interview_sessions
from backend.copilot_service import get_plan
from backend.portfolio_service import get_projects
from backend.learning_service import get_learning_progress
from backend.networking_service import contacts,interactions


def quest_progress(user_id):
    goals=get_cv_builder_data(user_id)
    versions=get_cv_versions(user_id)
    interviews=[s for s in get_interview_sessions(user_id) if s.get('completed_at') and s.get('answers')]
    proofs=[p for p in get_projects(user_id) if p['completed'] and p['evidence_url'] and p['summary'] and len(p['checked'])==len(p['checklist'])]
    learning=defaultdict(set)
    for (skill,index),step in get_learning_progress(user_id).items():
        if step['status']=='completed' and step['notes'].strip():learning[skill].add(index)
    learned=sum(len(indices)==3 for indices in learning.values())
    _,tasks,_=get_plan(user_id)
    weekly=sum(bool(t['completed']) and not t['custom'] for t in tasks)
    connections=bool(contacts(user_id)) and bool(interactions(user_id))
    milestones=[
      dict(key='goal',title='Set a career direction',description='Save a target position or career field.',count=int(bool(goals['target_position'] or goals['career_field'])),target=1,xp=20,url='/profile',badge='Direction set'),
      dict(key='cv',title='Save one CV version',description='Keep a tailored CV version you can review before applying.',count=len(versions),target=1,xp=20,url='/ai-studio',badge='CV prepared'),
      dict(key='interview',title='Complete one interview practice',description='Save your answers and review the feedback.',count=len(interviews),target=1,xp=30,url='/interview-helper',badge='Interview practiced'),
      dict(key='proof',title='Finish a proof project',description='Complete the checklist, document your contribution and save evidence.',count=len(proofs),target=1,xp=40,url='/portfolio',badge='Evidence builder'),
      dict(key='learning',title='Document three learning actions for one skill',description='Complete all three tracked actions and record notes for each.',count=learned,target=1,xp=30,url='/skill-gap',badge='Learning documented'),
      dict(key='network',title='Record a professional conversation',description='Save an active contact and record an interaction.',count=int(connections),target=1,xp=20,url='/networking',badge='Network organized'),
      dict(key='week',title='Complete three weekly plan tasks',description='Mark three suggested tasks complete in the current week. Custom tasks do not earn points.',count=weekly,target=3,xp=30,url='/career-copilot',badge='Weekly focus')]
    for step in milestones:
        step['done']=step['count']>=step['target'];step['progress']=min(100,round(100*step['count']/step['target']))
    xp=sum(step['xp'] for step in milestones if step['done'])
    return dict(milestones=milestones,xp=xp,max_xp=sum(s['xp'] for s in milestones),completed=sum(s['done'] for s in milestones),total=len(milestones),weekly_count=weekly,weekly_target=3)
