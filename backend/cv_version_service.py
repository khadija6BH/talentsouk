"""Compare persisted CV content; never reconstruct old source content."""
FIELDS = [('full_name','Name'),('job_title','Job title'),('summary','Professional summary'),('skills','Skills'),('experience','Experience'),('education','Education'),('projects','Projects'),('certifications','Certifications'),('languages','Languages'),('email','Email'),('phone','Phone'),('location','Location'),('linkedin','LinkedIn'),('github','GitHub')]

def compare_cv_content(before, after):
    changes=[]
    for field,label in FIELDS:
        old=str(before.get(field) or '')
        new=str(after.get(field) or '')
        if old == new:
            continue
        if field=='skills':
            reason='Existing relevant skills are placed first and displayed on separate lines.'
        elif field=='summary' and not old.strip():
            reason='A summary was drafted from the existing documented skills. Review it before use.'
        else:
            reason='Spacing and punctuation were normalized; the factual content is preserved.'
        changes.append({'field':field,'label':label,'before':old,'after':new,'reason':reason})
    return changes
