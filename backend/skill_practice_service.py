"""Small versioned knowledge exercises, not skill proficiency certification."""
import json
from backend.database import get_db_connection

VERSION=1
# Each item: prompt, choices, correct index, explanation.
EXERCISES={
'SQL': ('Technical', [
("A table has rows (id, salary): (1,100), (2,200), (3,NULL). What does SELECT COUNT(salary) return?", ['3','2','0'], 1, 'COUNT(column) counts non-NULL values; COUNT(*) counts rows.'),
("Which clause filters grouped results, such as departments with more than five employees?", ['ORDER BY','WHERE COUNT(*) > 5','HAVING COUNT(*) > 5'], 2, 'HAVING filters aggregates after grouping. WHERE filters rows before grouping.'),
("Keep every customer even if they have no orders. Which join is appropriate from customers to orders?", ['LEFT JOIN','INNER JOIN','CROSS JOIN'], 0, 'LEFT JOIN preserves rows from the left table, using NULL for missing matches.')]),
'Python': ('Technical', [
("a = [1, 2]; b = a; b.append(3). What is a now?", ['[1, 2]','[1, 2, 3]','An exception'], 1, 'Both names refer to the same mutable list. Use a copy when independent lists are needed.'),
("What is list(range(1, 4))?", ['[1, 2, 3, 4]','[0, 1, 2, 3]','[1, 2, 3]'], 2, 'The stop argument is excluded.'),
("Which block can release a resource whether or not an exception occurs?", ['finally','else only','except only'], 0, 'finally runs when leaving the try statement, including after an exception.')]),
'Git': ('Technical', [
("You edited a tracked file. Which command stages that file for the next commit?", ['git push','git add file.txt','git log'], 1, 'git add stages the current contents. It does not publish them.'),
("What does git status primarily show?", ['Only remote branches','Your passwords','Working tree and staging status'], 2, 'Status shows changes, staged files and untracked files; it does not commit them.'),
("Two branches changed the same lines and merging reports a conflict. What is the appropriate next step?", ['Review both changes, resolve the file, stage it and complete the merge','Delete the repository','Ignore the conflict and push'], 0, 'Resolve conflicts deliberately and check the result before completing the merge.')]),
'Communication': ('Soft skills', [
("A teammate asks an unclear question about a deadline. What is the best first response?", ['Assume what they mean','Ask which deliverable and deadline they mean','Promise immediate delivery'], 1, 'Clarify the need before proposing an answer or commitment.'),
("A customer reports a failure you cannot yet explain. Which update is most useful?", ['Say it is fixed before testing','Blame another team','Acknowledge the issue, state what is known and agree on the next update'], 2, 'An honest, concrete update builds shared understanding without inventing certainty.'),
("You describe a team project during an interview. How do you clarify your contribution?", ['Explain the context, your specific actions and the observed result','Claim every team achievement as yours','List tools without explaining actions'], 0, 'A concrete STAR example separates the team context from your own actions and evidence.')])}


def ensure_practice_schema(conn):
    conn.execute("""CREATE TABLE IF NOT EXISTS skill_practice_attempts (
      id INTEGER PRIMARY KEY AUTOINCREMENT,user_id INTEGER NOT NULL REFERENCES users(id) ON DELETE CASCADE,
      skill TEXT NOT NULL,version INTEGER NOT NULL,answers_json TEXT NOT NULL,
      correct INTEGER NOT NULL,total INTEGER NOT NULL,created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)""")


def submit_practice(user_id,skill,answers):
    if skill not in EXERCISES:raise ValueError('Choose one of the available exercises.')
    questions=EXERCISES[skill][1]
    if not isinstance(answers,list) or len(answers)!=len(questions) or any(type(a) is not int or a not in range(len(q[1])) for a,q in zip(answers,questions)):
        raise ValueError('Answer every question before checking your practice.')
    correct=sum(a==q[2] for a,q in zip(answers,questions))
    conn=get_db_connection()
    try:
        with conn:
            cursor=conn.execute('INSERT INTO skill_practice_attempts(user_id,skill,version,answers_json,correct,total) VALUES(?,?,?,?,?,?)',
                (user_id,skill,VERSION,json.dumps(answers),correct,len(questions)))
        return cursor.lastrowid
    finally:conn.close()


def attempts(user_id):
    conn=get_db_connection()
    try:return [dict(row) for row in conn.execute('SELECT id,skill,version,correct,total,created_at FROM skill_practice_attempts WHERE user_id=? ORDER BY id DESC LIMIT 20',(user_id,))]
    finally:conn.close()


def attempt(user_id,attempt_id):
    conn=get_db_connection()
    try:row=conn.execute('SELECT * FROM skill_practice_attempts WHERE user_id=? AND id=?',(user_id,attempt_id)).fetchone()
    finally:conn.close()
    if row is None:return None
    result=dict(row)
    result['answers']=json.loads(result.pop('answers_json'))
    result['details']=[]
    if result['version']==VERSION and result['skill'] in EXERCISES:
        for answer,q in zip(result['answers'],EXERCISES[result['skill']][1]):
            result['details'].append(dict(prompt=q[0],chosen=q[1][answer],expected=q[1][q[2]],correct=answer==q[2],explanation=q[3]))
    return result
