import json
import os
import smtplib
import unittest
from unittest.mock import patch,MagicMock
from urllib.error import HTTPError
from backend.smtp_service import smtp_configured,send_verification_email

class BrevoEmailTest(unittest.TestCase):
    def setUp(self):
        self.env=patch.dict(os.environ,{'EMAIL_PROVIDER':'brevo','BREVO_API_KEY':'test-key','BREVO_SENDER_EMAIL':'sender@example.invalid','SMTP_FROM_NAME':'TalentSouk','RENDER_EXTERNAL_URL':'https://example.onrender.com'})
        self.env.start()
    def tearDown(self):self.env.stop()
    def test_https_verification_delivery_keeps_code_and_branding(self):
        response=MagicMock();response.__enter__.return_value.read.return_value=b'{"messageId":"provider-id"}'
        with patch('urllib.request.urlopen',return_value=response) as send,patch('smtplib.SMTP') as smtp:
            result=send_verification_email(recipient='user@example.invalid',code='ABCDEFGH')
        self.assertEqual(result,'provider-id');smtp.assert_not_called()
        req=send.call_args.args[0];payload=json.loads(req.data)
        self.assertEqual(req.full_url,'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(payload['to'],[{'email':'user@example.invalid'}])
        self.assertIn('ABCDEFGH',payload['textContent']);self.assertIn('TalentSouk',payload['htmlContent'])
    def test_missing_brevo_key_does_not_fall_back_to_blocked_smtp(self):
        with patch.dict(os.environ,{'BREVO_API_KEY':''}):self.assertFalse(smtp_configured())
    def test_provider_errors_are_safe_and_do_not_report_success(self):
        with patch('urllib.request.urlopen',side_effect=HTTPError('https://api.brevo.com',429,'quota',{},None)):
            with self.assertRaises(smtplib.SMTPException) as caught:send_verification_email(recipient='user@example.invalid',code='ABCDEFGH')
        self.assertNotIn('test-key',str(caught.exception));self.assertIn('429',str(caught.exception))
