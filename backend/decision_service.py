"""Offer comparison with user weights and explicit missing data."""
import re
from backend.skill_gap_service import SKILLS,_contains

CONTRACTS={'any':'Any contract','permanent':'Permanent / CDI','internship':'Internship / Stage','contract':'Contract / Freelance','part_time':'Part time','full_time':'Full time'}
TERMS={'permanent':('permanent','cdi'),'internship':('internship','stage','intern'),'contract':('contract','freelance','cdd'),'part_time':('part-time','part time','temps partiel'),'full_time':('full-time','full time','temps plein')}


def compare_offers(offers,profile,location='',contract='any',weights=None):
    weights=weights or {'skills':5,'location':3,'contract':2}
    if contract not in CONTRACTS or any(type(v) is not int or not 0<=v<=5 for v in weights.values()) or set(weights)!={'skills','location','contract'}:raise ValueError('Choose valid priorities from 0 to 5.')
    active=dict(weights)
    if not location:active['location']=0
    if contract=='any':active['contract']=0
    total=sum(active.values())
    if not total:raise ValueError('Enable at least one priority with a preference you can compare.')
    evidence=' '.join(str(profile.get(k) or '') for k in ('skills','experience','projects','education','summary'))
    has_evidence=bool(evidence.strip())
    results=[]
    for offer in offers:
        text=' '.join(str(offer.get(k) or '') for k in ('title','description','requirements'))
        skills=[skill for skill,_ in SKILLS if _contains(text,skill)]
        present=[skill for skill in skills if _contains(evidence,skill)]
        missing=[skill for skill in skills if skill not in present]
        scores={'skills':round(100*len(present)/len(skills)) if skills and has_evidence else None,'location':None,'contract':None}
        reasons=[]
        if scores['skills'] is not None:reasons.append(str(len(present))+' of '+str(len(skills))+' detected skill mentions have evidence in your saved profile.')
        else:reasons.append('Skill overlap cannot be assessed: offer skill mentions or profile evidence are missing.')
        offer_location=str(offer.get('location') or '').strip()
        if location and offer_location:
            words=[w for w in re.findall(r'\w+',location.casefold()) if len(w)>1]
            scores['location']=100 if words and all(_contains(offer_location,w) for w in words) else 0
            reasons.append('Location '+('matches' if scores['location'] else 'does not match')+' your chosen preference.')
        offer_contract=str(offer.get('offer_type') or '').casefold().strip()
        if contract!='any' and offer_contract:
            dimension=('permanent','internship','contract') if contract in {'permanent','internship','contract'} else ('part_time','full_time')
            recognized=any(_contains(offer_contract,term) for kind in dimension for term in TERMS[kind])
            if recognized:
                scores['contract']=100 if any(_contains(offer_contract,term) for term in TERMS[contract]) else 0
                reasons.append('Recorded contract '+('matches' if scores['contract'] else 'does not match')+' your preference.')
            else:reasons.append('The recorded contract does not specify the contract dimension you selected.')
        known=sum(active[k] for k in active if scores[k] is not None)
        score=round(sum(active[k]*(scores[k] or 0) for k in active)/total) if known else None
        results.append(dict(offer=offer,scores=scores,score=score,coverage=round(100*known/total),present=present,missing=missing,reasons=reasons,skills=skills))
    results.sort(key=lambda row:(row['score'] is not None,row['score'] or 0,row['coverage'],-row['offer']['id']),reverse=True)
    return results
