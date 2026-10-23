import sys
from pathlib import Path
root=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(root/'.runtime-deps'),str(root)]
from datetime import date
from backend.tests.test_application_flow import ApplicationFlowTest
from backend.dashboard_activity import activity_calendar
from backend.database import get_db_connection
from backend.app import app

case=ApplicationFlowTest();case.setUp()
try:
    conn=get_db_connection()
    conn.execute("INSERT INTO skill_practice_attempts (user_id,skill,version,answers_json,correct,total,created_at) VALUES (?,?,?,?,?,?,?)",(case.user_id,'SQL',1,'[]',1,3,'2024-02-29 12:00:00'))
    conn.commit();conn.close()
    report=activity_calendar(case.user_id,date(2024,12,31))
    assert report['counts']['2024-02-29']==1
    assert all(key<='2024-12-31' for key in report['counts'])
    assert not activity_calendar(-100,date(2024,12,31))['counts']
    client=app.test_client()
    with client.session_transaction() as s:s['user_id']=case.user_id
    page=client.get('/crm/performance')
    assert page.status_code==200 and b'activity-calendar-data' in page.data
    import unittest
    suite=unittest.defaultTestLoader.loadTestsFromNames(['backend.tests.test_interface_language','backend.tests.test_performance_decision'])
    assert unittest.TextTestRunner().run(suite).wasSuccessful()
    print('Calendar ownership, leap day, future exclusion and page rendering passed.')
finally:case.tearDown()
