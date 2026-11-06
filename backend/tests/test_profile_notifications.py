import os
import tempfile
import unittest
from datetime import datetime,timezone,timedelta
from pathlib import Path
from unittest.mock import patch
from backend import database
from backend.radar_watch import alert_preferences,relevance_reason,sync_matching_notifications
from backend.offer_lifecycle import ensure_catalog_schema


class ProfileNotificationTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'SECRET_KEY':'test-profile-notifications-only','VERCEL':'1'})
        self.env.start()
        self.temp=tempfile.TemporaryDirectory()
        self.old_path=database.DB_PATH
        database.DB_PATH=Path(self.temp.name)/'alerts.db'
        database.init_db()
        from backend.app import app
        self.app=app
        self.old_testing=app.testing
        app.testing=True
        self.uid=database.create_user('Candidate','candidate@example.invalid','test-only-hash')
        self.other=database.create_user('Other','other@example.invalid','test-only-hash')
        c=database.get_db_connection()
        c.execute('UPDATE users SET verified_email=email')
        c.execute('''CREATE TABLE IF NOT EXISTS offers(id INTEGER PRIMARY KEY,title TEXT,description TEXT,
            source TEXT,location TEXT,publication_date TEXT)''')
        ensure_catalog_schema(c)
        c.commit();c.close()
        database.save_candidate_profile_metadata(self.uid,'','',target_position='Developer',
            target_skills='Python',target_location='Marrakech',career_goal='find_job')
        self.client=app.test_client()
        with self.client.session_transaction() as s:s['user_id']=self.uid

    def tearDown(self):
        self.app.testing=self.old_testing
        self.env.stop()
        database.DB_PATH=self.old_path
        self.temp.cleanup()

    def offer(self,identifier,title='Développeur web',**changes):
        row=dict(title=title,description='Public listing summary',source='Postule.ma',
            location='Marrakech',publication_date=datetime.now(timezone.utc).isoformat())
        row.update(changes)
        c=database.get_db_connection()
        c.execute('INSERT INTO offers(id,title,description,source,location,publication_date) VALUES(?,?,?,?,?,?)',(identifier,*row.values()))
        c.execute("INSERT INTO offer_catalog_status VALUES(?,1,CURRENT_TIMESTAMP,'recent_public_jobposting')",(identifier,))
        c.commit();c.close()

    def test_real_api_recovers_missed_import_marks_reads_and_does_not_recreate_cleared_alert(self):
        self.offer(1)
        response=self.client.get('/api/notifications')
        self.assertEqual(response.status_code,200)
        self.assertIn('no-store',response.headers['Cache-Control'])
        data=response.get_json()
        self.assertEqual(data['unread'],1)
        self.assertEqual(data['items'][0]['url'],'/opportunities/1')
        self.assertEqual(self.client.get('/api/notifications').get_json()['unread'],1)
        self.client.post('/api/notifications/read',json={'id':data['items'][0]['id']})
        self.assertEqual(self.client.get('/api/notifications').get_json()['unread'],0)
        self.client.post('/api/notifications/clear',json={})
        self.assertEqual(self.client.get('/api/notifications').get_json()['items'],[])
        self.offer(2)
        self.assertEqual(self.client.get('/api/notifications').get_json()['unread'],1)
        with self.client.session_transaction() as s:s.clear()
        self.assertEqual(self.client.get('/api/notifications').status_code,401)

    def test_irrelevant_hidden_stale_and_other_city_offers_never_alert(self):
        self.offer(1,title='Marketing Manager')
        self.offer(2,location='Rabat')
        self.offer(3,publication_date=(datetime.now(timezone.utc)-timedelta(days=40)).isoformat())
        for i,status in enumerate(('pending','rejected','archived'),4):
            self.offer(i)
            c=database.get_db_connection()
            c.execute('INSERT INTO admin_offer_reviews VALUES(?,?,?,CURRENT_TIMESTAMP)',(i,status,''))
            c.commit();c.close()
        self.assertEqual(sync_matching_notifications(self.uid),0)
        self.offer(8)
        self.assertEqual(sync_matching_notifications(self.other),0)
        self.assertEqual(sync_matching_notifications(self.uid),1)

    def test_uploaded_fields_are_used_when_manual_profile_contains_only_name(self):
        database.save_cv_profile(self.other,'manual',{'full_name':'Other'},'simple')
        database.save_cv_profile(self.other,'uploaded',{'job_title':'Data analyste','skills':'SQL'},'simple')
        prefs=dict(alert_preferences(self.other))
        self.assertEqual(prefs[self.other]['target_position'],'Data analyste')
        self.assertEqual(prefs[self.other]['alert_skills'],'SQL')
        self.assertIsNotNone(relevance_reason(prefs[self.other],{'title':'Data Analyst','description':'SQL','source':'Jooble'}))

    def test_profile_change_finds_existing_offer_and_user_cannot_read_others_alert(self):
        self.offer(1)
        self.assertEqual(sync_matching_notifications(self.other),0)
        database.save_candidate_profile_metadata(self.other,'','',target_position='Developer',career_goal='find_job')
        self.assertEqual(sync_matching_notifications(self.other),1)
        c=database.get_db_connection()
        identifier=c.execute('SELECT id FROM notifications WHERE user_id=?',(self.other,)).fetchone()[0]
        c.close()
        self.client.post('/api/notifications/read',json={'id':identifier})
        c=database.get_db_connection()
        self.assertEqual(c.execute('SELECT is_read FROM notifications WHERE id=?',(identifier,)).fetchone()[0],0)
        c.close()
