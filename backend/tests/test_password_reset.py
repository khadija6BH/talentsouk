import os
import shutil
import tempfile
import unittest
from email import policy
from email.parser import BytesParser
from unittest.mock import patch
from urllib.parse import urlparse

from werkzeug.security import generate_password_hash

from backend import database
from backend.app import app
from backend.smtp_service import send_password_reset_email


class PasswordResetTest(unittest.TestCase):
    def setUp(self):
        self.original_db_path = database.DB_PATH
        self.original_server_name = app.config.get("SERVER_NAME")
        self.temp_dir = tempfile.TemporaryDirectory()
        database.DB_PATH = database.Path(self.temp_dir.name) / "database.db"
        shutil.copy2(self.original_db_path, database.DB_PATH)
        database.init_db()
        conn = database.get_db_connection()
        conn.execute("DELETE FROM password_reset_tokens")
        conn.execute("DELETE FROM users WHERE email = ?", ("reset-test@example.com",))
        cursor = conn.execute(
            "INSERT INTO users (full_name, email, password_hash) VALUES (?, ?, ?)",
            ("Reset Test", "reset-test@example.com", generate_password_hash("OldPassword1!")),
        )
        self.user_id = cursor.lastrowid
        conn.execute("UPDATE users SET verified_email=email WHERE id=?",(self.user_id,))
        conn.commit()
        conn.close()
        app.config.update(TESTING=True, SERVER_NAME="localhost")
        self.client = app.test_client()

    def tearDown(self):
        database.DB_PATH = self.original_db_path
        app.config["SERVER_NAME"] = self.original_server_name
        self.temp_dir.cleanup()

    @patch("backend.app.send_password_reset_email")
    def test_request_is_generic_and_stores_only_a_token_hash(self, send_email):
        known = self.client.post(
            "/forgot-password", data={"email": "reset-test@example.com"},
            follow_redirects=True,
        )
        unknown = self.client.post(
            "/forgot-password", data={"email": "missing@example.com"},
            follow_redirects=True,
        )
        generic = b"If an account exists for that email, a password-reset code has been sent."
        self.assertIn(generic, known.data)
        self.assertIn(generic, unknown.data)
        send_email.assert_called_once()
        raw_token = send_email.call_args.kwargs["reset_code"]
        conn = database.get_db_connection()
        row = conn.execute(
            "SELECT token_hash, expires_at, used_at FROM password_reset_tokens WHERE user_id = ?",
            (self.user_id,),
        ).fetchone()
        conn.close()
        self.assertIsNotNone(row)
        self.assertNotEqual(row["token_hash"], raw_token)
        self.assertEqual(len(row["token_hash"]), 64)
        self.assertIsNone(row["used_at"])

    @patch("backend.app.send_password_reset_email")
    def test_reset_email_includes_signed_link_and_backup_code(self, send_email):
        response = self.client.post(
            "/forgot-password", data={"email": "reset-test@example.com"}
        )
        self.assertEqual(response.status_code, 302)
        self.assertIn("/reset-password-code", response.headers["Location"])
        code = send_email.call_args.kwargs["reset_code"]
        self.assertEqual(len(code), 8)
        self.assertIn("/reset-password-email/", send_email.call_args.kwargs["reset_url"])

    @patch("backend.app.send_password_reset_email")
    def test_full_reset_is_single_use_and_login_uses_new_password(self, send_email):
        self.client.post("/forgot-password", data={"email": "reset-test@example.com"})
        code = send_email.call_args.kwargs["reset_code"]
        reset = self.client.post(
            "/reset-password-code",
            data={"email": "reset-test@example.com", "code": code,
                  "password": "NewPassword2!", "confirm_password": "NewPassword2!"},
            follow_redirects=True,
        )
        self.assertEqual(reset.status_code, 200)
        self.assertIn(b"Your password has been reset", reset.data)
        old_login = self.client.post(
            "/login", data={"email": "reset-test@example.com", "password": "OldPassword1!"}
        )
        self.assertEqual(old_login.status_code, 401)
        new_login = self.client.post(
            "/login", data={"email": "reset-test@example.com", "password": "NewPassword2!"}
        )
        self.assertEqual(new_login.status_code, 302)
        reused = app.test_client().post("/reset-password-code", data={
            "email": "reset-test@example.com", "code": code,
            "password": "AnotherPass3!", "confirm_password": "AnotherPass3!",
        })
        self.assertIn(b"invalid, expired, or already used", reused.data)

    @patch("backend.app.send_password_reset_email")
    def test_expired_token_and_invalid_password_are_rejected(self, send_email):
        self.client.post("/forgot-password", data={"email": "reset-test@example.com"})
        code = send_email.call_args.kwargs["reset_code"]
        mismatch = self.client.post(
            "/reset-password-code", data={"email": "reset-test@example.com", "code": code,
            "password": "NewPassword2!", "confirm_password": "different"}
        )
        self.assertEqual(mismatch.status_code, 200)
        self.assertIn(b"Passwords do not match", mismatch.data)
        conn = database.get_db_connection()
        conn.execute(
            "UPDATE password_reset_tokens SET expires_at = '2000-01-01 00:00:00' WHERE user_id = ?",
            (self.user_id,),
        )
        conn.commit()
        conn.close()
        expired = self.client.post("/reset-password-code", data={
            "email": "reset-test@example.com", "code": code,
            "password": "NewPassword2!", "confirm_password": "NewPassword2!",
        })
        self.assertIn(b"invalid, expired, or already used", expired.data)

    @patch("backend.app.send_password_reset_email")
    def test_signed_link_does_not_consume_on_get_and_invalidates_all_codes(self, send_email):
        import hashlib
        database.create_password_reset_token(self.user_id, hashlib.sha256(b"OLDER123").hexdigest(), "2099-01-01 00:00:00")
        conn = database.get_db_connection()
        conn.execute("UPDATE password_reset_tokens SET created_at='2000-01-01 00:00:00'")
        conn.commit(); conn.close()
        self.client.post("/forgot-password", data={"email": "reset-test@example.com"})
        path = urlparse(send_email.call_args.kwargs["reset_url"]).path
        opened = self.client.get(path)
        self.assertEqual(opened.status_code, 200)
        self.assertEqual(opened.headers["Referrer-Policy"], "no-referrer")
        self.assertIn(('action="'+path+'"').encode(), opened.data)
        self.assertEqual(self.client.get(path).status_code, 200)
        self.assertEqual(self.client.get(path+'tampered').status_code, 400)
        result = self.client.post(path, data={"password":"NewPassword2!", "confirm_password":"NewPassword2!"})
        self.assertEqual(result.status_code, 302)
        self.assertEqual(self.client.get(path).status_code, 400)
        self.assertFalse(database.password_reset_token_is_valid(hashlib.sha256(b"OLDER123").hexdigest()))

    @patch("backend.app.send_password_reset_email")
    def test_pasted_code_with_spaces_and_hyphen_works(self, send_email):
        self.client.post("/forgot-password", data={"email": "reset-test@example.com"})
        code = send_email.call_args.kwargs["reset_code"]
        pasted = " "+code[:4]+" - "+code[4:]+"\n"
        response = self.client.post("/reset-password-code", data={"email":"reset-test@example.com", "code":pasted,
            "password":"NewPassword2!", "confirm_password":"NewPassword2!"})
        self.assertEqual(response.status_code, 302)

    @patch("backend.app.send_password_reset_email")
    def test_repeat_request_does_not_replace_delivered_code(self, send_email):
        self.client.post("/forgot-password", data={"email":"reset-test@example.com"})
        self.client.post("/forgot-password", data={"email":"reset-test@example.com"})
        send_email.assert_called_once()
        conn=database.get_db_connection()
        self.assertEqual(conn.execute("SELECT COUNT(*) AS n FROM password_reset_tokens").fetchone()["n"],1)
        conn.close()

    @patch("backend.app.send_password_reset_email", side_effect=OSError("Delivery unavailable"))
    def test_failed_delivery_preserves_previous_code(self, send_email):
        import hashlib
        old_hash=hashlib.sha256(b"OLDER123").hexdigest()
        database.create_password_reset_token(self.user_id, old_hash, "2099-01-01 00:00:00")
        conn=database.get_db_connection()
        conn.execute("UPDATE password_reset_tokens SET created_at='2000-01-01 00:00:00'")
        conn.commit();conn.close()
        self.client.post("/forgot-password", data={"email":"reset-test@example.com"})
        self.assertTrue(database.password_reset_token_is_valid(old_hash))

    def test_email_contains_both_button_and_backup_code(self):
        environment={"SMTP_HOST":"smtp.example.com","SMTP_PORT":"587","SMTP_USER":"shared@example.com",
                     "SMTP_PASSWORD":"app-password","SMTP_FROM_NAME":"TalentSouk","SMTP_USE_TLS":"true","EMAIL_PROVIDER":"smtp"}
        with patch.dict(os.environ,environment,clear=False), patch("backend.smtp_service.smtplib.SMTP") as smtp:
            send_password_reset_email(recipient="reset-test@example.com", reset_code="AB12CD34",
                reset_url="https://careers.example/reset-password-email/signed-token")
        message=smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        for subtype in ("plain","html"):
            body=message.get_body(preferencelist=(subtype,)).get_content()
            self.assertIn("AB12CD34",body)
            self.assertIn("https://careers.example/reset-password-email/signed-token",body)

    def test_shared_smtp_account_sends_reset_link_without_a_password(self):
        environment = {
            "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
            "SMTP_USER": "shared@example.com", "SMTP_PASSWORD": "app-password",
            "SMTP_FROM_NAME": "TalentSouk", "SMTP_USE_TLS": "true",
        }
        with patch.dict(os.environ, environment, clear=False), patch(
            "backend.smtp_service.smtplib.SMTP"
        ) as smtp:
            send_password_reset_email(
                recipient="reset-test@example.com",
                reset_url="https://careers.example/reset-password/random-token",
            )
        sent = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        self.assertEqual(sent["From"], "TalentSouk <shared@example.com>")
        self.assertEqual(sent["To"], "reset-test@example.com")
        body = sent.get_body(preferencelist=("plain",)).get_content()
        self.assertIn("https://careers.example/reset-password/random-token", body)
        self.assertNotIn("app-password", body)

    def test_long_emailed_link_remains_intact_and_completes_reset(self):
        raw_token = "A" * 43
        reset_url = f"http://localhost/reset-password/{raw_token}"
        environment = {
            "SMTP_HOST": "smtp.example.com", "SMTP_PORT": "587",
            "SMTP_USER": "shared@example.com", "SMTP_PASSWORD": "app-password",
            "SMTP_FROM_NAME": "TalentSouk", "SMTP_USE_TLS": "true",
        }
        with patch.dict(os.environ, environment, clear=False), patch(
            "backend.smtp_service.smtplib.SMTP"
        ) as smtp:
            send_password_reset_email(recipient="reset-test@example.com", reset_url=reset_url)
        message = smtp.return_value.__enter__.return_value.send_message.call_args.args[0]
        serialized = message.as_bytes(policy=policy.SMTP)
        parsed = BytesParser(policy=policy.default).parsebytes(serialized)
        plain_body = parsed.get_body(preferencelist=("plain",)).get_content()
        html_body = parsed.get_body(preferencelist=("html",)).get_content()
        self.assertIn(reset_url, plain_body)
        self.assertIn(f'href="{reset_url}"', html_body)

        import hashlib
        token_hash = hashlib.sha256(raw_token.encode("utf-8")).hexdigest()
        database.create_password_reset_token(
            self.user_id, token_hash, "2099-01-01 00:00:00"
        )
        opened = self.client.get(urlparse(reset_url).path)
        self.assertEqual(opened.status_code, 200)
        self.assertIn(f'action="/reset-password/{raw_token}"'.encode(), opened.data)
        changed = self.client.post(
            urlparse(reset_url).path,
            data={"password": "DeliveredLink2!", "confirm_password": "DeliveredLink2!"},
        )
        self.assertEqual(changed.status_code, 302)
        self.assertEqual(self.client.get(urlparse(reset_url).path).status_code, 400)


if __name__ == "__main__":
    unittest.main()
