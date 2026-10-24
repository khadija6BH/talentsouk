"""Protected operations dashboard and owner-scoped support reports."""
import hmac
import re
import secrets
from functools import wraps

from flask import Blueprint, abort, flash, g, got_request_exception, redirect, render_template, request, session, url_for
from backend import admin_service as service
from backend.database import get_user_by_id, get_user_settings
from backend.email_verification import verified

operations = Blueprint('operations', __name__)


def current_admin():
    user = get_user_by_id(session['user_id']) if session.get('user_id') else None
    return bool(verified(user) and service.member(user['id']))


def signed_in(view):
    @wraps(view)
    def wrapped(*args, **kwargs):
        user = get_user_by_id(session['user_id']) if session.get('user_id') else None
        if not user:
            return redirect(url_for('login'))
        if not verified(user):
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def admin_only(view):
    @wraps(view)
    @signed_in
    def wrapped(*args, **kwargs):
        if not current_admin():
            abort(403)
        return view(*args, **kwargs)
    return wrapped


def csrf_token():
    if 'operations_csrf' not in session:
        session['operations_csrf'] = secrets.token_urlsafe(32)
    return session['operations_csrf']


def check_csrf():
    expected = session.get('operations_csrf', '')
    if not expected or not hmac.compare_digest(expected, request.form.get('csrf_token', '')):
        abort(400, 'The form expired. Reload the page and try again.')


@operations.route('/admin')
@admin_only
def admin_dashboard():
    page = max(1, min(request.args.get('page', 1, type=int) or 1, 100000))
    days = request.args.get('days', 14, type=int)
    days = days if days in {7, 14, 30} else 14
    status = request.args.get('status', 'all')
    status = status if status in {'all', 'open', 'in_progress', 'resolved'} else 'all'
    search = request.args.get('q', '').strip()[:120]
    data = service.dashboard(search, page, status, days)
    return render_template('admin.html', active_page='admin', data=data, page=page,
                           search=search, selected_status=status, csrf_token=csrf_token())


@operations.route('/admin/tickets/<ticket_id>', methods=['POST'])
@admin_only
def manage_ticket(ticket_id):
    check_csrf()
    try:
        service.update_ticket(session['user_id'], ticket_id, request.form.get('status', ''),
                              request.form.get('reply', ''), request.form.get('internal_note', ''))
    except ValueError as error:
        abort(400, str(error))
    except LookupError:
        abort(404)
    flash('Report updated. The user can read your response in Help & support.', 'success')
    return redirect(url_for('operations.admin_dashboard', _anchor='reports'))


@operations.route('/admin/incidents/<incident_id>', methods=['POST'])
@admin_only
def manage_incident(incident_id):
    check_csrf()
    try:
        service.update_incident(session['user_id'], incident_id, request.form.get('status', ''),
                                request.form.get('internal_note', ''))
    except ValueError as error:
        abort(400, str(error))
    except LookupError:
        abort(404)
    flash('Incident updated.', 'success')
    return redirect(url_for('operations.admin_dashboard', _anchor='incidents'))


@operations.route('/support', methods=['GET', 'POST'])
@signed_in
def support():
    if request.method == 'POST':
        check_csrf()
        try:
            service.create_ticket(session['user_id'], request.form.get('title', ''),
                                  request.form.get('message', ''), request.form.get('category', ''),
                                  request.form.get('reference', ''))
        except ValueError as error:
            return render_template('support.html', active_page='support', error=str(error),
                                   tickets=service.my_tickets(session['user_id']), csrf_token=csrf_token()), 400
        flash('Your report has been submitted. You can follow its progress here.', 'success')
        return redirect(url_for('operations.support'))
    return render_template('support.html', active_page='support', tickets=service.my_tickets(session['user_id']),
                           csrf_token=csrf_token())


def install(app):
    app.register_blueprint(operations)

    @app.context_processor
    def admin_navigation():
        return {'can_manage_app': current_admin()}

    @app.before_request
    def prepare_operations():
        g.support_reference = secrets.token_hex(8).upper()

    def exception_type(sender, exception, **extra):
        # Provider error messages can contain credentials; keep only the class.
        g.operations_error_type = re.sub(r'[^A-Za-z0-9_]', '', type(exception).__name__)[:80]

    got_request_exception.connect(exception_type, app, weak=False)

    @app.after_request
    def operational_metrics(response):
        if request.path.startswith(('/admin', '/support')):
            response.headers['Cache-Control'] = 'private, no-store'
            response.headers['Vary'] = 'Cookie'
        endpoint = request.endpoint or 'unmatched'
        try:
            if response.status_code >= 500 and endpoint != 'static':
                reference = getattr(g, 'support_reference', secrets.token_hex(8).upper())
                response.headers['X-Support-Reference'] = reference
                route = request.url_rule.rule if request.url_rule else 'unmatched'
                service.record_incident(route, getattr(g, 'operations_error_type', 'HTTPServerError'), response.status_code, reference)
            uid = session.get('user_id')
            if uid and endpoint != 'static' and not request.path.startswith(('/admin', '/api/health')):
                user = get_user_by_id(uid)
                if verified(user):
                    login = request.method == 'POST' and endpoint in {'login', 'verify_email'} and 300 <= response.status_code < 400
                    consent = request.method == 'GET' and response.status_code == 200 and bool(get_user_settings(uid).get('analytics_enabled'))
                    service.record_activity(uid, login=login, endpoint=endpoint if consent else None, consent=consent)
        except Exception:
            app.logger.warning('Operational metrics could not be saved.')
        return response
