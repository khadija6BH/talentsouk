"""Exercise Flask on the disposable staging schema, without real mail/API calls."""
import json
import os
import sys
import tempfile
import uuid
from io import BytesIO
from pathlib import Path
from unittest.mock import patch

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
load_dotenv(ROOT / '.env', override=True)
os.environ['DATABASE_BACKEND'] = 'postgres'
os.environ['DATABASE_SCHEMA'] = 'talentsouk_staging'


def run():
    from backend import database as db
    from backend.app import app
    from backend.dashboard_activity import saved_activity, activity_calendar
    from backend.networking_service import save_contact, contacts
    from backend.twin_service import save_scenario, scenarios
    from backend.portfolio_service import create_project, get_project
    from backend.copilot_service import create_plan, get_plan
    from werkzeug.security import generate_password_hash

    checks = []
    temp_uploads = tempfile.TemporaryDirectory(prefix='talentsouk-pg-upload-')
    original_upload_folder = app.config['CV_UPLOAD_FOLDER']
    app.config['CV_UPLOAD_FOLDER'] = temp_uploads.name
    synthetic_company_id = None
    email = 'migration-' + uuid.uuid4().hex + '@example.invalid'
    password = 'Migration-test-only-2026!'
    uid = db.create_user('Migration Test', email, generate_password_hash(password))
    assert uid > 0
    checks.append('insert_identity')
    app.config.update(TESTING=True)
    try:
        with db.get_db_connection() as conn:
            conn.execute('UPDATE users SET verified_email=? WHERE id=?', (email, uid))
        db.save_cv_profile(uid, 'manual', {'full_name': 'Migration Test', 'skills': 'Python, SQL', 'summary': 'Migration check'}, 'Modern')
        db.save_candidate_profile_metadata(uid, '', '', target_position='Data Analyst',
            career_field='IT', target_location='Marrakech', target_skills='Python, SQL',
            career_goal='job', education_level='bachelor', experience_level='entry')
        version_id = db.save_optimized_cv(uid, 'manual', {'profile': {'skills': 'Python, SQL'}, 'offer_title': 'Data Analyst'})
        assert db.get_cv_version(uid, version_id) is not None
        assert db.get_cv_version(uid + 999999, version_id) is None
        checks.extend(['cv_builder_upsert', 'cv_versions', 'cv_owner_isolation'])
        client = app.test_client()
        response = client.post('/login', data={'email': email, 'password': password})
        assert response.status_code == 302
        with client.session_transaction() as state:
            assert state['user_id'] == uid
        checks.append('password_login')
        with patch('backend.smtp_service.smtplib.SMTP', side_effect=AssertionError('Unexpected real SMTP')), \
             patch('backend.gmail_service.urllib.request.urlopen', side_effect=AssertionError('Unexpected real API request')):
            # GET pages and JSON endpoints exercise joins, calendars and matching.
            for path in ['/dashboard', '/companies', '/jobs', '/applications', '/postulations',
                         '/cv-builder', '/settings', '/portfolio', '/career-copilot',
                         '/performance-lab', '/api/dashboard/stats', '/api/dashboard/charts',
                         '/api/companies', '/api/jobs', '/api/health']:
                response = client.get(path)
                assert response.status_code == 200, (path, response.status_code)
                checks.append('GET ' + path)
                print('checked ' + path, flush=True)
            conn = db.get_db_connection()
            offer = conn.execute('SELECT id,company_id FROM offers WHERE company_id IS NOT NULL ORDER BY id LIMIT 1').fetchone()
            conn.close()
            response = client.post('/api/postulations', json={'company_id': offer['company_id'], 'job_id': offer['id'],
                                  'cv': 'manual', 'message': 'Migration test application', 'cover_letter': 'Test cover letter'})
            assert response.status_code == 201, response.status_code
            app_id = response.get_json()['application']['id']
            assert db.get_application_for_user(uid, app_id) is not None
            assert db.get_application_for_user(uid + 999999, app_id) is None
            checks.extend(['candidature_persistence', 'application_owner_isolation'])
        db.create_notification(uid, 'test', 'Migration check')
        conn = db.get_db_connection()
        assert conn.execute('SELECT COUNT(*) FROM notification_mail_queue WHERE user_id=?', (uid,)).fetchone()[0] > 0
        before = conn.execute('SELECT COUNT(*) FROM company_search_history WHERE user_id=?', (uid,)).fetchone()[0]
        conn.execute('INSERT INTO company_search_history(user_id,query) VALUES(?,?)', (uid, 'rollback check'))
        conn.rollback()
        assert conn.execute('SELECT COUNT(*) FROM company_search_history WHERE user_id=?', (uid,)).fetchone()[0] == before
        conn.close()
        checks.extend(['notification_queue_trigger', 'transaction_rollback'])
        assert saved_activity(uid)
        assert activity_calendar(uid) is not None
        checks.append('calendar_date_queries')
        from pypdf import PdfWriter
        pdf = BytesIO(); writer = PdfWriter(); writer.add_blank_page(width=612, height=792); writer.write(pdf)
        pdf_bytes = pdf.getvalue()
        response = client.post('/cv-builder/upload', data={'cv_file': (BytesIO(pdf_bytes), 'migration-test.pdf')}, content_type='multipart/form-data')
        assert response.status_code == 302
        assert db.get_cv_for_user(uid) is not None
        response = client.get('/cv-builder/download')
        assert response.status_code == 200 and response.data == pdf_bytes
        response.close()
        checks.extend(['cv_upload', 'cv_download_bytes'])
        conn = db.get_db_connection()
        with conn:
            synthetic_company_id = conn.execute('INSERT INTO companies(name,email) VALUES(?,?)', ('Migration Test Company', 'recruiting@example.invalid')).lastrowid
        conn.close()
        with patch('backend.app.send_application_email', return_value='test-smtp-message-id') as send:
            response = client.post('/api/apply', data={'company_id': str(synthetic_company_id), 'message': 'Synthetic migration application message.'})
            assert response.status_code == 200, response.status_code
            assert send.call_count == 1
        checks.append('smtp_candidature_with_mock_delivery')
        from backend.email_verification import send_code, confirm_code
        conn = db.get_db_connection()
        with conn:
            conn.execute("UPDATE users SET verified_email='' WHERE id=?", (uid,))
        conn.close()
        with patch('backend.email_verification.send_verification_email') as send:
            send_code(uid, now=1900000000)
            send_code(uid, now=1900000061)  # Exercises replacement/upsert on the same key.
            assert confirm_code(uid, send.call_args.kwargs['code'], now=1900000062)
        checks.append('verification_code_upsert_and_confirm')
        from backend.skill_practice_service import submit_practice, EXERCISES, attempt
        skill = next(iter(EXERCISES))
        attempt_id = submit_practice(uid, skill, [0] * len(EXERCISES[skill][1]))
        assert attempt(uid, attempt_id)
        checks.append('skill_practice_persistence')
        contact_id = save_contact(uid, {'name': 'Test Contact', 'company_id': offer['company_id'], 'email': 'contact@example.invalid'})
        assert contacts(uid)[0]['id'] == contact_id
        scenario_id = save_scenario(uid, 'Test scenario', ['Python'], [offer['id']])
        assert scenarios(uid, scenario_id)
        project = create_project(uid, 'Python')
        assert project
        create_plan(uid)
        assert get_plan(uid)
        checks.extend(['networking_crm', 'career_scenario', 'portfolio_conflict_ignore', 'career_plan'])
    finally:
        # Staging-only test account and dependent rows; no real user is touched.
        conn = db.get_db_connection()
        with conn:
            conn.execute('DELETE FROM crm WHERE user_id=?', (uid,))
            conn.execute('DELETE FROM cvs WHERE user_id=?', (uid,))
            conn.execute('DELETE FROM users WHERE id=?', (uid,))
            if synthetic_company_id is not None:
                conn.execute('DELETE FROM companies WHERE id=?', (synthetic_company_id,))
        conn.close()
        app.config['CV_UPLOAD_FOLDER'] = original_upload_folder
        temp_uploads.cleanup()
    result = {'schema': 'talentsouk_staging', 'checks_passed': len(checks), 'checks': checks, 'external_messages_sent': 0}
    (ROOT / '.runtime-logs' / 'postgres-smoke.json').write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result))


if __name__ == '__main__':
    run()
