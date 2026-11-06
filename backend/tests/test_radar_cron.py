import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch
from flask import Flask
from backend.radar_cron import radar_cron


class RadarCronTest(unittest.TestCase):
    def setUp(self):
        self.app = Flask(__name__)
        self.app.register_blueprint(radar_cron)
        self.client = self.app.test_client()

    def test_unconfigured_and_unauthorized_requests_do_not_run_sync(self):
        with patch.dict(os.environ, {'CRON_SECRET': ''}):
            self.assertEqual(self.client.get('/api/cron/offers').status_code, 503)
        with patch.dict(os.environ, {'CRON_SECRET': 'test-only-secret'}), patch('backend.radar_watch.run_cycle') as sync:
            for header in ('', 'Bearer wrong', 'Bearer é'):
                self.assertEqual(self.client.get('/api/cron/offers', headers={'Authorization': header}).status_code, 401)
            sync.assert_not_called()

    def request_refresh(self):
        return self.client.get('/api/cron/offers', headers={'Authorization': 'Bearer test-only-secret'})

    def test_authenticated_run_is_bounded_and_lease_skip_is_successful(self):
        with patch.dict(os.environ, {'CRON_SECRET': 'test-only-secret'}), patch('backend.job_sources.source_status', return_value={'jooble': True}), patch('backend.radar_watch.run_cycle', return_value=True) as sync, patch('backend.radar_watch.watch_status', return_value=({}, [{'provider': 'jooble', 'status': 'ok'}])):
            self.assertEqual(self.request_refresh().get_json()['status'], 'ok')
            sync.assert_called_once_with(include_profile_queries=False, pages=5)
            sync.return_value = False
            self.assertEqual(self.request_refresh().get_json()['status'], 'skipped')

    def test_missing_provider_and_failed_source_report_failure(self):
        with patch.dict(os.environ, {'CRON_SECRET': 'test-only-secret'}), patch('backend.job_sources.source_status', return_value={'jooble': False}), patch('backend.radar_watch.run_cycle') as sync:
            self.assertEqual(self.request_refresh().status_code, 503)
            sync.assert_not_called()
        with patch.dict(os.environ, {'CRON_SECRET': 'test-only-secret'}), patch('backend.job_sources.source_status', return_value={'jooble': True}), patch('backend.radar_watch.run_cycle', return_value=True), patch('backend.radar_watch.watch_status', return_value=({}, [{'provider': 'jooble', 'status': 'error'}])):
            self.assertEqual(self.request_refresh().status_code, 503)

    def test_failure_does_not_expose_exception_details(self):
        with patch.dict(os.environ, {'CRON_SECRET': 'test-only-secret'}), patch('backend.job_sources.source_status', return_value={'jooble': True}), patch('backend.radar_watch.run_cycle', side_effect=RuntimeError('private database connection')):
            response = self.request_refresh()
            self.assertEqual(response.status_code, 503)
            self.assertNotIn(b'private database', response.data)

    def test_serverless_cycle_uses_one_query_and_preserves_database_lease(self):
        from backend.radar_watch import run_cycle
        with tempfile.TemporaryDirectory() as directory:
            def connect():
                conn = sqlite3.connect(os.path.join(directory, 'watch.db'))
                conn.row_factory = sqlite3.Row
                return conn
            preferences = [(1, {'target_position': 'Developer'}), (2, {'target_position': 'Analyst'})]
            with patch('backend.radar_watch.get_db_connection', side_effect=connect), patch('backend.radar_watch.alert_preferences', return_value=preferences), patch('backend.job_sources.source_status', return_value={'jooble': True}), patch('backend.opportunity_radar.refresh_external_offers', return_value={'created': 2, 'updated': 3}) as refresh:
                self.assertTrue(run_cycle(include_profile_queries=False, pages=5))
                refresh.assert_called_once_with('jooble', 'ma', '', 'Marrakech', pages=5)
                self.assertFalse(run_cycle(include_profile_queries=False, pages=5))
                refresh.assert_called_once()
