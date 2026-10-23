"""Descriptive analytics of per-user application records, never causal claims."""
from collections import Counter,defaultdict
from datetime import date
from backend.application_status import normalize_application_status,APPLICATION_STATUSES


def _month(value):
    try:return date.fromisoformat(str(value or '')[:10]).isoformat()[:7]
    except ValueError:return None


def analyze_performance(records,history,companies,versions):
    company_map={c['id']:c for c in companies}
    version_map={v['id']:v for v in versions}
    attained=defaultdict(set)
    for event in history:
        if event['event_type']=='Status changed':
            status=str(event['description']).split('→')[-1].strip()
            if status in APPLICATION_STATUSES:attained[event['application_id']].add(status)
    states=Counter();monthly=defaultdict(lambda:dict(sent=0,outcomes=0,interviews=0,accepted=0))
    fields=defaultdict(lambda:dict(sent=0,outcomes=0,interviews=0))
    cvs=defaultdict(lambda:dict(sent=0,outcomes=0,interviews=0))
    stages=dict(sent=0,outcomes=0,interviews=0,accepted=0);undated=0
    for raw in records:
        item=dict(raw);state=normalize_application_status(item['status']);states[state]+=1
        reached=attained[item['id']]|{state}
        sent=bool(item.get('applied_at')) or state in {'Sent','Replied','Interview','Accepted','Rejected'} or 'Sent' in reached
        if not sent:continue
        outcome=bool(reached & {'Replied','Interview','Accepted','Rejected'})
        interview='Interview' in reached
        accepted='Accepted' in reached
        stages['sent']+=1;stages['outcomes']+=outcome;stages['interviews']+=interview;stages['accepted']+=accepted
        month=_month(item.get('applied_at'))
        if month:
            for key,value in dict(sent=1,outcomes=outcome,interviews=interview,accepted=accepted).items():monthly[month][key]+=int(value)
        else:undated+=1
        category=company_map.get(item['company_id'],{}).get('category') or 'Unknown field'
        for key,value in dict(sent=1,outcomes=outcome,interviews=interview).items():fields[category][key]+=int(value)
        choice=str(item.get('cv_used') or '')
        version_id=int(choice[8:]) if choice.startswith('version:') and choice[8:].isdigit() else None
        label=('CV #'+str(version_id)+' · '+str(version_map[version_id]['optimized'].get('offer_title') or 'Saved version')) if version_id in version_map else 'CV version not identified'
        for key,value in dict(sent=1,outcomes=outcome,interviews=interview).items():cvs[label][key]+=int(value)
    def groups(values):
        return [dict(label=label,**counts,outcome_rate=round(100*counts['outcomes']/counts['sent']) if counts['sent'] else None,small_sample=counts['sent']<5) for label,counts in sorted(values.items())]
    suggestions=[]
    if states['Draft']:suggestions.append(dict(text=str(states['Draft'])+' draft(s) are waiting. Review and personalize one application.',url='/applications'))
    if stages['sent'] and not stages['outcomes']:suggestions.append(dict(text='No outcome is recorded yet. Check replies and plan a relevant follow-up.',url='/crm'))
    if not records:suggestions.append(dict(text='Start with one suitable offer and track your application.',url='/opportunity-radar'))
    if stages['interviews']:suggestions.append(dict(text='Interview activity is recorded. Practice one answer and review the feedback.',url='/interview-helper'))
    return dict(total=len(records),states=[dict(label=s,count=states[s]) for s in APPLICATION_STATUSES],stages=stages,
        months=groups(monthly),fields=groups(fields),versions=groups(cvs),undated=undated,suggestions=suggestions,
        outcome_rate=round(100*stages['outcomes']/stages['sent']) if stages['sent'] else None)
