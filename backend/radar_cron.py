"""Authenticated, bounded refresh executed inside a serverless request."""
import hmac
import logging
import os
from flask import Blueprint, jsonify, request

radar_cron = Blueprint('radar_cron', __name__)


@radar_cron.route('/api/cron/offers', methods=['GET'])
def refresh_scheduled_offers():
    secret = os.environ.get('CRON_SECRET', '').strip()
    if not secret:
        return jsonify(error='Scheduled refresh is not configured.'), 503
    expected = ('Bearer ' + secret).encode('utf-8')
    if not hmac.compare_digest(request.headers.get('Authorization', '').encode('utf-8'), expected):
        return jsonify(error='Unauthorized'), 401
    from backend.job_sources import source_status,MARRAKECH_PROVIDERS
    configured = source_status()
    active = [provider for provider in MARRAKECH_PROVIDERS if configured.get(provider)]
    if not active:
        return jsonify(error='The Morocco offer source is not configured.'), 503
    from backend.radar_watch import run_cycle, watch_status
    try:
        # API and public-page collectors are bounded, without per-user searches.
        ran = run_cycle(include_profile_queries=False, pages=5)
        if not ran:
            return jsonify(status='skipped', reason='Refresh already running or checked recently.')
        _, checks = watch_status()
        failed = [check['provider'] for check in checks if check['provider'] in active and check['status']=='error']
        if len(failed)==len(active):
            return jsonify(error='Offer sources could not be refreshed. Saved offers are preserved.'), 503
        if failed:
            return jsonify(status='partial',failed_sources=failed)
        return jsonify(status='ok')
    except Exception:
        logging.getLogger(__name__).warning('Scheduled offer refresh failed')
        return jsonify(error='Offer refresh failed. Try again later.'), 503
