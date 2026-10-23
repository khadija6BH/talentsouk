"""Owner-scoped career tools used by AI Studio."""
from backend import database
from backend.ai_service import match_cv_to_job,optimize_cv_for_job,generate_ai_cover_letter
from backend.career_dna_service import get_unified_candidate_profile


def run_studio(uid,payload,choice):
    action=payload.get('action','match')
    if action not in {'match','optimize','recommendations','cover'}:raise ValueError('Choose a studio tool.')
    source=payload.get('source','dna')
    if source not in {'dna','manual','uploaded'}:raise ValueError('Choose a saved CV.')
    builder=database.get_cv_builder_data(uid)
    cv=database.get_cv_for_user(uid)
    if source=='uploaded' and not cv:raise ValueError('Upload your CV in CV Builder first.')
    profile=get_unified_candidate_profile(uid) if source=='dna' else dict(builder['profiles'].get(source) or {})
    if source=='uploaded' and cv:profile['cv_text']=cv['extracted_text'] or ''
    user=database.get_user_by_id(uid)
    profile['full_name']=profile.get('full_name') or user['full_name'];profile['email']=profile.get('email') or user['email']
    if not any(profile.get(k) for k in ('skills','summary','experience','education','projects','cv_text')):raise ValueError('Add CV information before running an analysis.')
    companies=database.get_all_companies_from_db()
    offers=database.get_all_offers_from_db()
    if action=='recommendations':
        grouped={}
        for offer in offers:grouped.setdefault(offer['company_id'],offer)
        results=[]
        for company in companies:
            result=match_cv_to_job(profile,grouped.get(company['id']),company)
            results.append({'id':company['id'],'name':company['name'],'score':result['score'],'skills':result.get('strong_matches',[]),'category':company.get('category','')})
        by_id={company['id']:company for company in companies}
        job_results=[]
        for offer in offers:
            company=by_id.get(offer['company_id'])
            if not company:
                continue
            match=match_cv_to_job(profile,offer,company)
            evidence=list(dict.fromkeys(match.get('strong_matches',[])+match.get('matching_keywords',[])))
            # A location match alone is not enough to recommend a job.
            if not evidence:
                continue
            job_results.append({'id':offer['id'],'company_id':company['id'],
                'title':offer['title'],'company_name':company['name'],
                'location':offer.get('location') or company.get('area',''),
                'contract_type':offer.get('contract_type',''),'score':match['score'],
                'matched_terms':evidence[:6],'missing_skills':match.get('missing_skills',[])[:4]})
        return {'recommendations':sorted(results,key=lambda r:(-r['score'],r['name']))[:6],
            'job_recommendations':sorted(job_results,key=lambda r:(-r['score'],r['title'],r['id']))[:6],
            'available_offer_count':len(offers)}
    try:company_id=int(payload.get('company_id',''));offer_id=int(payload.get('offer_id') or 0)
    except (TypeError,ValueError):raise ValueError('Choose a valid company and opportunity.')
    company=next((c for c in companies if c['id']==company_id),None)
    if not company:raise ValueError('Choose a company.')
    offer=next((o for o in offers if o['id']==offer_id and o['company_id']==company_id),None)
    if offer_id and not offer:raise ValueError('This offer is unavailable or belongs to another company.')
    if action=='match':return {'match':match_cv_to_job(profile,offer,company,ai_choice=choice('matching'))}
    if action=='optimize':
        result=optimize_cv_for_job(profile,offer,company,ai_choice=choice('matching'))
        result['version_id']=database.save_optimized_cv(uid,'uploaded' if source=='uploaded' else 'manual',result)
        return {'optimization':result}
    language=payload.get('language','en')
    if language not in {'en','fr','ar'}:raise ValueError('Choose English, French or Arabic.')
    position=payload.get('position') or (offer or {}).get('title') or builder.get('target_position','')
    if not isinstance(position,str) or len(position)>180:raise ValueError('Enter a target role under 180 characters.')
    return {'cover_letter':generate_ai_cover_letter(profile,offer,company,position,language,ai_choice=choice('generation'))}
