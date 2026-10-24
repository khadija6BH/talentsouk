import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash

from backend import database, admin_service
from backend.app import app
from backend.admin_routes import csrf_token
from flask import got_request_exception


class AdminOperationsTest(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_path = database.DB_PATH
        database.DB_PATH = Path(self.temp.name) / 'operations.db'
        database.init_db()
        conn = database.get_db_connection()
        conn.execute('CREATE TABLE IF NOT EXISTS offers (id INTEGER PRIMARY KEY)')
        conn.commit()
        conn.close()
        from backend.sqlite_service import _ensure_sqlite_schema
        _ensure_sqlite_schema()
        self.old_testing = app.testing
        app.testing = True
        self.admin = database.create_user('Owner', 'owner@example.invalid', generate_password_hash('Password123'))
        self.user = database.create_user('Candidate', 'candidate@example.invalid', generate_password_hash('Password123'))
        self.other = database.create_user('Other', 'other@example.invalid', generate_password_hash('Password123'))
        conn = database.get_db_connection()
        conn.execute('UPDATE users SET verified_email=email,email_verification_required=1')
        conn.execute('INSERT INTO admin_members(user_id,created_at) VALUES(?,?)', (self.admin, admin_service.now_text()))
        conn.commit()
        conn.close()
        self.client = app.test_client()

    def tearDown(self):
        app.testing = self.old_testing
        database.DB_PATH = self.old_path
        self.temp.cleanup()

    def login_as(self, uid):
        with self.client.session_transaction() as session:
            session.clear()
            session['user_id'] = uid

    def token(self):
        with self.client.session_transaction() as session:
            session['operations_csrf'] = 'test-csrf'
        return 'test-csrf'

    def test_admin_is_closed_to_anonymous_regular_and_unverified_accounts(self):
        self.assertEqual(self.client.get('/admin').status_code, 302)
        self.login_as(self.user)
        self.assertEqual(self.client.get('/admin').status_code, 403)
        self.assertEqual(self.client.post('/admin/tickets/any', data={'status': 'resolved'}).status_code, 403)
        conn = database.get_db_connection()
        conn.execute("UPDATE users SET verified_email='' WHERE id=?", (self.admin,))
        conn.commit(); conn.close()
        self.login_as(self.admin)
        self.assertEqual(self.client.get('/admin').status_code, 403)

    def test_admin_page_renders_and_never_exposes_password_or_cv_content(self):
        self.login_as(self.admin)
        response = self.client.get('/admin?days=30&q=Candidate')
        self.assertEqual(response.status_code, 200)
        self.assertIn(b'Candidate', response.data)
        self.assertNotIn(b'candidate@example.invalid', response.data)
        self.assertNotIn(b'password_hash', response.data)
        self.assertIn('no-store', response.headers['Cache-Control'])

    def test_support_is_owner_scoped_and_private_notes_stay_private(self):
        ticket = admin_service.create_ticket(self.user, 'A CV issue', 'The save button did not work.', 'cv')
        other = admin_service.create_ticket(self.other, 'Other private report', 'Private other account message.', 'account')
        admin_service.update_ticket(self.admin, ticket, 'in_progress', 'We are investigating.', 'PRIVATE-ADMIN-NOTE')
        self.login_as(self.user)
        response = self.client.get('/support')
        self.assertIn(b'We are investigating.', response.data)
        self.assertNotIn(b'PRIVATE-ADMIN-NOTE', response.data)
        self.assertNotIn(b'Other private report', response.data)
        self.assertEqual(self.client.post('/admin/tickets/'+other, data={'csrf_token':self.token(),'status':'resolved'}).status_code, 403)

    def test_csrf_and_audit_for_admin_changes(self):
        ticket = admin_service.create_ticket(self.user, 'Email issue', 'A verification email did not arrive.', 'email')
        self.login_as(self.admin)
        self.assertEqual(self.client.post('/admin/tickets/'+ticket, data={'status':'resolved'}).status_code, 400)
        response = self.client.post('/admin/tickets/'+ticket, data={'csrf_token':self.token(),'status':'resolved','reply':'Please retry.','internal_note':'Provider checked.'})
        self.assertEqual(response.status_code, 302)
        self.assertEqual(admin_service.my_tickets(self.user)[0]['status'], 'resolved')
        conn = database.get_db_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_audit WHERE actor_id=?', (self.admin,)).fetchone()[0], 1)
        conn.close()

    def test_support_csrf_limits_and_html_escaping(self):
        self.login_as(self.user)
        fields={'title':'<script>alert(1)</script>','message':'A valid description of the problem.','category':'bug'}
        self.assertEqual(self.client.post('/support', data=fields).status_code,400)
        fields['csrf_token']=self.token()
        for _ in range(5):
            self.assertEqual(self.client.post('/support',data=fields).status_code,302)
        self.assertEqual(self.client.post('/support',data=fields).status_code,400)
        response=self.client.get('/support')
        self.assertNotIn(b'<script>alert(1)</script>',response.data)
        self.assertIn(b'&lt;script&gt;',response.data)

    def test_metrics_respect_opt_in_and_do_not_invent_historical_activity(self):
        admin_service.record_activity(self.user, login=True, endpoint='dashboard', consent=False)
        conn=database.get_db_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM admin_page_metrics').fetchone()[0],0)
        self.assertIsNone(conn.execute('SELECT * FROM account_activity WHERE user_id=?',(self.other,)).fetchone())
        conn.close()
        admin_service.record_activity(self.user,endpoint='dashboard',consent=True)
        result=admin_service.dashboard()
        self.assertEqual(result['summary']['logins'],1)
        self.assertEqual(result['pages'][0]['hits'],1)

    def test_incident_group_reopens_and_stores_only_safe_metadata(self):
        admin_service.record_incident('/api/tool/<item_id>','ValueError',500,'REF-ONE')
        incident=admin_service.dashboard()['incidents'][0]
        admin_service.update_incident(self.admin,incident['id'],'resolved','Investigated')
        admin_service.record_incident('/api/tool/<item_id>','ValueError',500,'REF-TWO')
        incident=admin_service.dashboard()['incidents'][0]
        self.assertEqual(incident['occurrences'],2)
        self.assertEqual(incident['status'],'open')
        self.assertEqual(incident['reference'],'REF-TWO')

    def test_member_grant_does_not_follow_an_email_change_to_another_user(self):
        database.update_user_profile(self.user,'Candidate','owner-new@example.invalid')
        self.assertFalse(admin_service.member(self.user))

    def test_error_hook_drops_exception_messages_and_query_strings(self):
        with app.test_request_context('/missing?token=DO-NOT-STORE'):
            got_request_exception.send(app, exception=ValueError('DO-NOT-STORE-SECRET'))
            response=app.process_response(app.response_class('',status=500))
            self.assertTrue(response.headers.get('X-Support-Reference'))
        incident=admin_service.dashboard()['incidents'][0]
        self.assertEqual(incident['error_type'],'ValueError')
        self.assertNotIn('DO-NOT-STORE',str(incident))

    def test_page_analytics_hook_honors_the_saved_preference(self):
        self.login_as(self.user)
        self.client.get('/support')
        self.assertEqual(admin_service.dashboard()['pages'],[])
        settings=database.get_user_settings(self.user)
        settings['analytics_enabled']=1
        database.save_user_settings(self.user,settings)
        self.client.get('/support')
        self.assertEqual(admin_service.dashboard()['pages'][0]['endpoint'],'operations.support')

    def test_revoked_membership_stops_an_existing_session(self):
        self.login_as(self.admin)
        conn=database.get_db_connection()
        conn.execute('DELETE FROM admin_members WHERE user_id=?',(self.admin,))
        conn.commit();conn.close()
        self.assertEqual(self.client.get('/admin').status_code,403)

    def test_deleted_accounts_remove_membership_support_and_activity(self):
        admin_service.create_ticket(self.user,'Delete me report','This report belongs to a deleted account.','other')
        admin_service.record_activity(self.user,login=True)
        database.delete_user_account(self.user)
        conn=database.get_db_connection()
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM support_tickets WHERE user_id=?',(self.user,)).fetchone()[0],0)
        self.assertEqual(conn.execute('SELECT COUNT(*) FROM account_activity WHERE user_id=?',(self.user,)).fetchone()[0],0)
        conn.close()

    def test_successful_login_hook_records_authentication(self):
        with patch('backend.app.onboarding_required',return_value=False):
            response=self.client.post('/login',data={'email':'candidate@example.invalid','password':'Password123'})
        self.assertEqual(response.status_code,302)
        self.assertEqual(admin_service.dashboard()['summary']['logins'],1)


if __name__=='__main__':
    unittest.main()
