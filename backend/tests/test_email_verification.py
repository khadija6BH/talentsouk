import tempfile,time,unittest
from pathlib import Path
from unittest.mock import patch
from werkzeug.security import generate_password_hash
from backend import database
from backend.app import app
from backend.email_verification import send_code,confirm_code,verified,require_verification
from backend.smtp_service import SMTPConfigurationError

class EmailVerificationTest(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory();self.old=database.DB_PATH
        database.DB_PATH=Path(self.temp.name)/'verify.db';database.init_db()
        self.uid=database.create_user('Candidate','verify@example.invalid',generate_password_hash('Password123'))
        self.other=database.create_user('Other','other@example.invalid',generate_password_hash('Password123'))
        self.client=app.test_client()
        app.config['TESTING']=True
        self.sender=patch('backend.email_verification.send_verification_email').start()
    def tearDown(self):patch.stopall();database.DB_PATH=self.old;self.temp.cleanup()
    def test_registration_waits_for_code_and_never_logs_in_early(self):
        response=self.client.post('/register',data={'full_name':'New','email':'new@example.invalid','password':'Password123','confirm_password':'Password123'})
        self.assertTrue(response.location.endswith('/verify-email'))
        with self.client.session_transaction() as state:self.assertNotIn('user_id',state)
        self.assertEqual(self.client.get('/dashboard').status_code,302)
        code=self.sender.call_args.kwargs['code']
        response=self.client.post('/verify-email',data={'code':code})
        self.assertEqual(response.status_code,302)
        self.assertTrue(verified(database.get_user_by_email('new@example.invalid')))

    def test_legacy_flag_never_allows_an_unverified_session_into_app(self):
        conn=database.get_db_connection()
        conn.execute("UPDATE users SET email_verification_required=0,verified_email='' WHERE id=?",(self.uid,))
        conn.commit();conn.close()
        with self.client.session_transaction() as state:state['user_id']=self.uid
        response=self.client.get('/dashboard')
        self.assertTrue(response.location.endswith('/verify-email'))
        with self.client.session_transaction() as state:
            self.assertNotIn('user_id',state)
            self.assertEqual(state['pending_email_user'],self.uid)
        with self.client.session_transaction() as state:state['user_id']=self.uid
        response=self.client.get('/api/dashboard/stats')
        self.assertEqual(response.status_code,403)

    def test_deleted_user_session_is_not_authenticated(self):
        with self.client.session_transaction() as state:state['user_id']=99999999
        self.assertEqual(self.client.get('/api/dashboard/stats').status_code,401)
        with self.client.session_transaction() as state:self.assertNotIn('user_id',state)

    def test_new_accounts_require_verification_at_creation(self):
        account=database.get_user_by_id(self.uid)
        self.assertEqual(account['email_verification_required'],1)
        self.assertFalse(verified(account))
    def test_verify_existing_session_from_settings(self):
        with self.client.session_transaction() as state:state['user_id']=self.uid
        response=self.client.post('/verify-current-email')
        self.assertTrue(response.location.endswith('/verify-email'))
        with self.client.session_transaction() as state:self.assertNotIn('user_id',state)
        self.client.post('/verify-email',data={'code':self.sender.call_args.kwargs['code']})
        self.assertTrue(verified(database.get_user_by_id(self.uid)))

    def test_hash_expiry_single_use_and_user_scope(self):
        send_code(self.uid,now=1000);code=self.sender.call_args.kwargs['code']
        conn=database.get_db_connection();row=conn.execute('SELECT * FROM email_verification_codes WHERE user_id=?',(self.uid,)).fetchone();conn.close()
        self.assertNotEqual(row['code_hash'],code)
        self.assertFalse(confirm_code(self.other,code,now=1001))
        self.assertFalse(confirm_code(self.uid,code,now=1600))
        send_code(self.uid,now=1661);code=self.sender.call_args.kwargs['code']
        self.assertTrue(confirm_code(self.uid,code,now=1662))
        self.assertFalse(confirm_code(self.uid,code,now=1663))
    def test_attempt_limit_and_resend_throttle(self):
        send_code(self.uid,now=1000);code=self.sender.call_args.kwargs['code']
        with self.assertRaises(ValueError):send_code(self.uid,now=1020)
        for i in range(5):self.assertFalse(confirm_code(self.uid,'WRONG000',now=1021))
        self.assertFalse(confirm_code(self.uid,code,now=1022))
        for i in range(1,5):send_code(self.uid,now=1000+i*61)
        with self.assertRaises(ValueError):send_code(self.uid,now=1400)
        send_code(self.uid,now=4601)
    def test_unverified_login_gate_and_verified_password_login_without_smtp(self):
        response=self.client.post('/login',data={'email':'verify@example.invalid','password':'Password123'})
        self.assertTrue(response.location.endswith('/verify-email'))
        with self.client.session_transaction() as state:self.assertNotIn('user_id',state)
        code=self.sender.call_args.kwargs['code']
        self.client.post('/verify-email',data={'code':code})
        self.client.get('/logout')
        with patch('backend.app.smtp_configured',return_value=False):
            response=self.client.post('/login',data={'email':'verify@example.invalid','password':'Password123'})
        self.assertEqual(response.status_code,302)
        with self.client.session_transaction() as state:self.assertEqual(state['user_id'],self.uid)
    def test_mail_failure_does_not_verify_or_expose_code(self):
        self.sender.side_effect=SMTPConfigurationError('Missing SMTP')
        response=self.client.post('/login',data={'email':'verify@example.invalid','password':'Password123'},follow_redirects=True)
        self.assertIn(b'Unable to send the code',response.data)
        self.assertNotIn(self.sender.call_args.kwargs['code'].encode(),response.data)
        self.assertFalse(verified(database.get_user_by_id(self.uid)))
    def test_changed_email_invalidates_verification_and_old_code(self):
        send_code(self.uid);code=self.sender.call_args.kwargs['code']
        database.update_user_profile(self.uid,'Candidate','changed@example.invalid')
        self.assertFalse(confirm_code(self.uid,code))
        with self.client.session_transaction() as state:state['user_id']=self.uid
        self.assertEqual(self.client.get('/api/search?q=test').status_code,403)
        self.assertEqual(self.client.get('/dashboard').status_code,302)
    def test_email_validation_and_code_page_require_pending_session(self):
        self.assertEqual(self.client.get('/verify-email').status_code,302)
        response=self.client.post('/register',data={'full_name':'New','email':'bademail','password':'Password123','confirm_password':'Password123'})
        self.assertEqual(response.status_code,400)
        self.sender.assert_not_called()
