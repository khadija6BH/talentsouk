"""
TalentSouk â€” Flask application entry point.

TASK 0 â€” PROJECT FOUNDATION: base app + placeholder routes.
TASK 1 â€” LOGIN + REGISTER: real local authentication via Flask sessions
          and SQLite. Dashboard and other app pages are now gated behind
          login, but their own content/functionality is unchanged.
"""

import os
import re
import smtplib
import uuid
import mimetypes
import hmac
import hashlib
import secrets
from datetime import date, datetime, timedelta, timezone
from email.utils import parseaddr
from functools import wraps
from backend.upload_storage import UploadPath as Path

from backend.career_dna_service import get_career_dna, get_unified_candidate_profile, save_career_dna

from backend.interview_coaching import question_guide, interview_progress
from backend.learning_service import attach_learning_progress, save_learning_progress

from backend.application_status import APPLICATION_STATUSES, normalize_application_status

from flask import (
    Flask, flash, jsonify, make_response, redirect, render_template, request,
    send_from_directory, session, url_for,
)
from itsdangerous import URLSafeTimedSerializer, BadSignature
from werkzeug.exceptions import RequestEntityTooLarge
from werkzeug.middleware.proxy_fix import ProxyFix
from dotenv import load_dotenv
from werkzeug.security import check_password_hash, generate_password_hash
from werkzeug.utils import secure_filename

from backend.ai_service import (
    AIServiceError, FIELD_CATEGORIES, FIELD_OPTIONS, analyze_skill_gap, classify_by_status,
    generate_ai_cover_letter, generate_application_messages, generate_whatsapp_messages,
    generate_professional_summaries, generate_skill_gap_advice, generate_interview_questions,
    evaluate_interview_answers, get_ai_models, get_ai_status,
    get_recommendations, match_cv_to_job,
    optimize_cv_for_job, search_companies,
)
from backend.companies_data import get_all_companies, get_company
from backend.company_catalog import company_option_groups
from backend.tutorial_service import get_tutorial,change_tutorial,STEPS as TUTORIAL_STEPS
from backend.appearance_service import get_appearance,save_appearance,validate_appearance,THEMES as APPEARANCE_THEMES,AVATARS as APPEARANCE_AVATARS
from backend.database import (
    create_application, create_user, delete_cv, get_applications_for_user,
    get_application_for_user, get_gmail_credentials, save_gmail_credentials,
    delete_gmail_credentials, mark_application_sent,
    get_cv_builder_data, get_cv_for_user, get_initials, get_user_by_email,
    get_user_by_id, get_db_connection, init_db, save_cv, save_cv_profile, save_optimized_cv,
    get_cv_versions, get_cv_version, save_candidate_profile_metadata, update_application, update_user_profile,
    update_user_language, update_user_password, get_user_settings,
    save_user_settings, delete_user_account, save_company_search, get_company_search_history,
    add_history, create_notification, create_reminder, find_application,
    get_history, get_notifications, get_reminders, notification_action, update_reminder,
    count_recent_application_attempts, log_application_email_attempt,
    update_company_status,
    create_interview_session, complete_interview_session, get_interview_sessions,
    get_interview_session, get_interview_weak_skills,
    create_interview_schedule, get_interview_schedules, get_interview_schedule,
    delete_interview_schedule,
    create_password_reset_token, password_reset_token_is_valid,
    reset_password_with_token, reset_password_with_code,
)
from backend.cv_optimizer_service import get_offers
from backend.cv_service import CVExtractionError, extract_cv, extract_profile_fields
from backend.gmail_service import (
    GMAIL_SEND_SCOPE, GmailServiceError, authorization_url, build_message,
    create_oauth_state, decrypt_token, encrypt_token, ensure_access_token,
    exchange_authorization_code, gmail_is_configured, send_message,
    verified_google_identity,
)
from backend.matching_service import match_candidate_to_offer, match_company_offers
from backend.skill_gap_service import analyze_market_skill_gap
from backend.smtp_service import (
    SMTPConfigurationError, send_application_email, send_password_reset_email,
    smtp_configured, app_link,
)
from backend.sqlite_service import (
    connection_status, create_tracked_application, create_crm_record,
    delete_tracked_application, fetch_applications_for_api,
    delete_crm_record, fetch_crm_for_api,
    fetch_companies_for_api, fetch_contacts_for_api, fetch_jobs_for_api,
    fetch_ai_context, fetch_dashboard_stats,
    get_job_offer_for_application,
    query_companies_for_api, query_jobs_for_api,
    update_tracked_application, update_crm_record,
)

PROJECT_ROOT = Path(__file__).resolve().parent.parent
load_dotenv(PROJECT_ROOT / ".env")
STORAGE_ROOT = Path(os.environ.get("STORAGE_ROOT", PROJECT_ROOT)).resolve()
STORAGE_ROOT.mkdir(parents=True, exist_ok=True)
app = Flask(
    __name__,
    template_folder=str(PROJECT_ROOT / "frontend" / "templates"),
    static_folder=str(PROJECT_ROOT / "frontend" / "static"),
)
from backend.radar_cron import radar_cron
app.register_blueprint(radar_cron)

# Exactly one trusted reverse proxy (Nginx, Render, Railway, or Fly) sits in
# front of production. This makes Flask honor the original HTTPS scheme/host.
app.wsgi_app = ProxyFix(app.wsgi_app, x_for=1, x_proto=1, x_host=1, x_port=1)
app.config["SECRET_KEY"] = os.environ.get("SECRET_KEY")
if not app.config["SECRET_KEY"]:
    raise RuntimeError("SECRET_KEY must be configured in .env")
# Pick up template edits without retaining the previous page in memory.
app.config["TEMPLATES_AUTO_RELOAD"] = True
app.config["PERMANENT_SESSION_LIFETIME"] = timedelta(days=30)
app.config.update(
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
    SESSION_COOKIE_SECURE=os.environ.get("SESSION_COOKIE_SECURE", "0") == "1",
)
CV_TEMPLATES = ["Modern", "Minimal", "Professional", "Tech / AI"]
CV_ACCENT_COLORS = {
    "Deep Plum": "#673147", "Dark Eggplant": "#311432",
    "Dusty Mauve": "#A18F93", "Faded Lavender": "#D8C7D8",
}
CV_PROFILE_FIELD_LIMITS = {
    "full_name": 150,
    "job_title": 180,
    "email": 254,
    "phone": 60,
    "linkedin": 300,
    "github": 300,
    "accent_color": 20,
    "location": 120,
    "summary": 4000,
    "education": 10000,
    "experience": 12000,
    "skills": 5000,
    "projects": 10000,
    "certifications": 5000,
    "languages": 2000,
}

# TASK 6 â€” CV UPLOAD + SKILL GAP
app.config["CV_UPLOAD_FOLDER"] = str(STORAGE_ROOT / "uploads" / "cvs")
MAX_CV_FILE_SIZE = 5 * 1024 * 1024
# Leave room for multipart form fields while enforcing the file limit below.
app.config["MAX_CONTENT_LENGTH"] = MAX_CV_FILE_SIZE + 64 * 1024
ALLOWED_CV_EXTENSIONS = {"pdf", "doc", "docx"}
ALLOWED_PROFILE_PHOTO_EXTENSIONS = {"jpg", "jpeg", "png", "webp"}
CAREER_GOALS = {"internship": "Internship", "pfe": "PFE", "job": "Job"}
EDUCATION_LEVELS = {
    "high_school": "High school", "bac_plus_2": "Bac+2", "bachelor": "Bachelor's",
    "master": "Master's", "engineering": "Engineering degree", "doctorate": "Doctorate",
}
EXPERIENCE_LEVELS = {
    "student": "Student / no experience", "entry": "Entry level", "junior": "Junior (1–2 years)",
    "mid": "Mid-level (3–5 years)", "senior": "Senior (6+ years)",
}
TARGET_SKILL_OPTIONS = (
    "Python", "JavaScript", "Java", "SQL", "Data Analysis", "Machine Learning",
    "React", "Flask", "Communication", "Teamwork", "Project Management", "English",
)


def collect_target_skills(form):
    selected = [skill for skill in form.getlist("target_skills_selected") if skill in TARGET_SKILL_OPTIONS]
    custom = ",".join(form.getlist("target_skills"))
    custom_skills = [skill.strip() for skill in re.split(r"[,;\n]+", custom) if skill.strip()]
    return ", ".join(dict.fromkeys(selected + custom_skills))
os.makedirs(app.config["CV_UPLOAD_FOLDER"], exist_ok=True)
app.config["PROFILE_PHOTO_FOLDER"] = str(STORAGE_ROOT / "uploads" / "profile_photos")
os.makedirs(app.config["PROFILE_PHOTO_FOLDER"], exist_ok=True)
app.config["PORTRAIT_FOLDER"] = str(STORAGE_ROOT / "uploads" / "portraits")

init_db()

from backend.admin_routes import install as install_operations
install_operations(app)


@app.before_request
def ensure_background_notifications():
    # Also start with WSGI/flask run, where __main__ is never executed.
    if not app.testing and os.environ.get("NOTIFICATION_WORKER", "1") == "1":
        from backend.radar_watch import start_watcher
        start_watcher()


def get_candidate_match_profile(user_id):
    return get_unified_candidate_profile(user_id)


def onboarding_required(user_id):
    profile = get_cv_builder_data(user_id)
    return not str(profile.get("career_goal") or "").strip() or not str(profile.get("target_position") or "").strip()


def has_candidate_match_data(candidate):
    return any(
        candidate.get(field)
        for field in (
            "location", "summary", "education", "experience", "skills",
            "projects", "certifications", "languages",
        )
    )


def get_match_for_position(candidate, company, position, offers):
    offer = next(
        (
            item for item in offers
            if item["company_id"] == company["id"]
            and item["title"].casefold() == str(position or "").casefold()
        ),
        None,
    )
    if offer is None or not has_candidate_match_data(candidate):
        return None
    return match_candidate_to_offer(candidate, company, offer)


# ---------------------------------------------------------------------------
# Auth helpers
# ---------------------------------------------------------------------------

def login_required(view_func):
    @wraps(view_func)
    def wrapped_view(*args, **kwargs):
        if not session.get("user_id"):
            if request.path.startswith("/api/"):
                return jsonify(error="Session expirée. Veuillez vous reconnecter."), 401
            return redirect(url_for("login"))
        from backend.email_verification import verified
        account=get_user_by_id(session['user_id'])
        if account is None:
            session.clear()
            if request.path.startswith('/api/'):
                return jsonify(error='Session expired. Please log in again.'),401
            return redirect(url_for('login'))
        # Email ownership is mandatory, including sessions created before the
        # verification feature. The verification action itself exposes no app data.
        if not verified(account) and request.endpoint != 'verify_current_email':
            uid=session['user_id'];session.clear();session['pending_email_user']=uid
            if request.path.startswith('/api/'):return jsonify(error='Verify your email before continuing.',verification_url=url_for('verify_email')),403
            return redirect(url_for('verify_email'))
        # Recheck persisted preferences for existing sessions and older accounts too.
        if request.endpoint not in {"onboarding", "verify_current_email"} and onboarding_required(session["user_id"]):
            if request.path.startswith("/api/"):
                return jsonify(error="Complete your career preferences before continuing.", onboarding_url=url_for("onboarding")), 403
            return redirect(url_for("onboarding"))
        return view_func(*args, **kwargs)
    return wrapped_view


@app.errorhandler(RequestEntityTooLarge)
def handle_request_too_large(error):
    if request.path == "/api/apply":
        return jsonify(error="Le CV doit avoir une taille maximale de 5 Mo."), 413
    return error


app.jinja_env.filters['company_option_groups']=company_option_groups


@app.context_processor
def inject_current_user():
    """Make the logged-in user (and their initials) available to every template."""
    user = None
    if session.get("user_id"):
        row = get_user_by_id(session["user_id"])
        if row is not None:
            profile_metadata = get_cv_builder_data(row["id"])
            user = {
                "id": row["id"],
                "full_name": row["full_name"],
                "email": row["email"],
                "verified_email": row["verified_email"],
                "initials": get_initials(row["full_name"]),
                "preferred_language": row["preferred_language"],
                "has_profile_photo": bool(profile_metadata["profile_photo_filename"]),
            }
    appearance = get_appearance(user['id'] if user else None)
    if user:
        use_photo = user['has_profile_photo'] and appearance['avatar'] in {'auto','photo'}
        avatar = appearance['avatar'] if appearance['avatar'] in APPEARANCE_AVATARS else 'plum'
        user['avatar_url'] = url_for('profile_photo') if use_photo else url_for('static',filename='images/avatars/'+avatar+'.jpg')
    notifications = []
    if user:
        notifications = [dict(item) for item in get_notifications(user["id"])]
    language = user["preferred_language"] if user else request.cookies.get("ui_language", "en")
    if language not in {"en", "fr", "ar"}: language = "en"
    tutorial_state=get_tutorial(user['id']) if user else {'status':'not_started','step':0}
    tutorial_step=None
    if user and tutorial_state['status']=='running' and request.args.get('tour')=='1':
        candidate=TUTORIAL_STEPS[tutorial_state['step']]
        if request.endpoint==candidate['endpoint']:
            tutorial_step=dict(candidate,index=tutorial_state['step'],total=len(TUTORIAL_STEPS))
    return {"tutorial_state":tutorial_state,"tutorial_step":tutorial_step,"appearance": appearance, "appearance_themes": APPEARANCE_THEMES, "appearance_avatars": APPEARANCE_AVATARS, "ui_language": language, "current_user": user, "navbar_notifications": notifications,
            "unread_notification_count": sum(not item["is_read"] for item in notifications),
            "application_statuses": APPLICATION_STATUSES}


# ---------------------------------------------------------------------------
# Auth pages (standalone layout, no sidebar/topbar)
# ---------------------------------------------------------------------------

@app.route("/login", methods=["GET", "POST"])
def login():
    if session.get("user_id"):
        return redirect(url_for("onboarding") if onboarding_required(session["user_id"]) else url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        remember = request.form.get("remember") == "on"

        error = None
        if not email or not password:
            error = "Please enter both your email and password."
        else:
            user = get_user_by_email(email)
            if user is None or not check_password_hash(user["password_hash"], password):
                error = "Incorrect email or password."

        if error:
            flash(error, "error")
            return render_template("login.html", email=email), 401

        session.clear()
        from backend.email_verification import verified,require_verification
        if not verified(user):
            require_verification(user['id'])
            session['pending_email_user']=user['id']
            session['verify_remember']=remember
            _send_email_challenge(user['id'])
            return redirect(url_for('verify_email'))
        session["user_id"] = user["id"]
        session.permanent = remember
        return redirect(url_for("onboarding") if onboarding_required(user["id"]) else url_for("dashboard"))

    return render_template("login.html")


@app.route("/forgot-password", methods=["GET", "POST"])
def forgot_password():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        email = request.form.get("email", "").strip().lower()
        if not _valid_email(email) or len(email) > 254:
            flash("Enter a valid account email address.", "error")
            return render_template("forgot_password.html", email=email), 400
        # Persisted per-account limits work across serverless instances.
        user = get_user_by_email(email)
        limited = False
        if user is not None:
            conn = get_db_connection()
            recent = conn.execute(
                "SELECT COUNT(*) AS total FROM password_reset_tokens WHERE user_id = ? "
                "AND created_at > datetime('now', '-1 hour')", (user["id"],)
            ).fetchone()["total"]
            cooldown = conn.execute(
                "SELECT id FROM password_reset_tokens WHERE user_id = ? "
                "AND created_at > datetime('now', '-1 minute')", (user["id"],)
            ).fetchone()
            conn.close()
            limited = recent >= 5 or cooldown is not None
        if user is not None and not limited:
            reset_code = "".join(secrets.choice("ABCDEFGHJKLMNPQRSTUVWXYZ23456789") for _ in range(8))
            token_hash = hashlib.sha256(reset_code.encode("utf-8")).hexdigest()
            expires_at = (datetime.now(timezone.utc) + timedelta(minutes=60)).strftime("%Y-%m-%d %H:%M:%S")
            create_password_reset_token(user["id"], token_hash, expires_at)
            try:
                signed = URLSafeTimedSerializer(app.secret_key, salt="password-reset-email").dumps(reset_code)
                reset_url = app_link(url_for("reset_password_email", signed=signed))
                send_password_reset_email(recipient=user["email"], reset_code=reset_code, reset_url=reset_url)
            except (SMTPConfigurationError, smtplib.SMTPException, OSError):
                app.logger.exception("Password reset email delivery failed")

        flash(
            "If an account exists for that email, a password-reset code has been sent.",
            "success",
        )
        session["reset_email"] = email
        return redirect(url_for("reset_password_code"))

    return render_template("forgot_password.html", email=request.args.get("email", ""))


@app.route("/reset-password-code", methods=["GET", "POST"])
def reset_password_code():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))
    email = request.values.get("email", session.get("reset_email", "")).strip().lower()
    if request.method == "POST":
        code = re.sub(r"[\s\-\u200b\u200e\u200f\ufeff]", "", request.form.get("code", "")).upper()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if not email or "@" not in email or len(code) != 8:
            flash("Enter your account email and the 8-character code from the TalentSouk email.", "error")
        elif len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
        elif password != confirm_password:
            flash("Passwords do not match.", "error")
        else:
            code_hash = hashlib.sha256(code.encode("utf-8")).hexdigest()
            if reset_password_with_code(email, code_hash, generate_password_hash(password)):
                session.clear()
                flash("Your password has been reset. You can now log in.", "success")
                return redirect(url_for("login"))
            flash("The verification code is invalid, expired, or already used.", "error")
    return render_template("reset_password_code.html", email=email)


@app.route("/reset-password-email/<signed>", methods=["GET", "POST"])
def reset_password_email(signed):
    try:
        token = URLSafeTimedSerializer(app.secret_key, salt="password-reset-email").loads(signed, max_age=3600)
    except BadSignature:
        return render_template("reset_password.html", invalid_token=True), 400
    return _reset_password(token, url_for("reset_password_email", signed=signed))


@app.after_request
def protect_password_reset_response(response):
    if request.endpoint in {"forgot_password", "reset_password_code", "reset_password", "reset_password_email"}:
        response.headers["Cache-Control"] = "private, no-store"
        response.headers["Referrer-Policy"] = "no-referrer"
    return response


@app.route("/reset-password/<token>", methods=["GET", "POST"])
def reset_password(token):
    return _reset_password(token, url_for("reset_password", token=token))


def _reset_password(token, reset_action):
    token_hash = hashlib.sha256(token.encode("utf-8")).hexdigest()
    if not password_reset_token_is_valid(token_hash):
        return render_template("reset_password.html", invalid_token=True), 400

    if request.method == "POST":
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")
        if len(password) < 8:
            flash("Password must be at least 8 characters long.", "error")
            return render_template("reset_password.html", token=token, reset_action=reset_action), 400
        if password != confirm_password:
            flash("Passwords do not match.", "error")
            return render_template("reset_password.html", token=token, reset_action=reset_action), 400
        if not reset_password_with_token(token_hash, generate_password_hash(password)):
            return render_template("reset_password.html", invalid_token=True), 400
        session.clear()
        flash("Your password has been reset. You can now log in.", "success")
        return redirect(url_for("login"))

    return render_template("reset_password.html", token=token, reset_action=reset_action)


@app.route("/register", methods=["GET", "POST"])
def register():
    if session.get("user_id"):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        full_name = request.form.get("full_name", "").strip()
        email = request.form.get("email", "").strip().lower()
        password = request.form.get("password", "")
        confirm_password = request.form.get("confirm_password", "")

        error = None
        if not full_name or not email or not password or not confirm_password:
            error = "Please fill in all fields."
        elif not _valid_email(email) or len(email) > 254:
            error = "Enter a valid email address."
        elif len(password) < 8:
            error = "Password must be at least 8 characters long."
        elif password != confirm_password:
            error = "Passwords do not match."
        elif get_user_by_email(email) is not None:
            error = "An account with this email already exists."

        if error:
            flash(error, "error")
            return render_template(
                "register.html", full_name=full_name, email=email
            ), 400

        password_hash = generate_password_hash(password)
        user_id = create_user(full_name, email, password_hash)
        language=request.cookies.get("ui_language","en")
        if language in {"en","fr","ar"}:update_user_language(user_id,language)

        session.clear()
        from backend.email_verification import require_verification
        require_verification(user_id)
        session['pending_email_user']=user_id
        _send_email_challenge(user_id)
        return redirect(url_for('verify_email'))

    return render_template("register.html")


def _send_email_challenge(user_id):
    from backend.email_verification import send_code
    try:
        send_code(user_id)
        flash('A verification code was sent. Check your inbox and spam folder.','success')
    except ValueError as error:flash(str(error),'error')
    except (SMTPConfigurationError,smtplib.SMTPException,OSError):
        app.logger.warning('Email verification delivery unavailable.')
        flash('Unable to send the code. Email sending must be available before you can verify your account. Try again shortly.','error')


@app.route('/verify-current-email', methods=['POST'])
@login_required
def verify_current_email():
    from backend.email_verification import verified, require_verification
    uid=session['user_id']
    if verified(get_user_by_id(uid)):
        return redirect(url_for('settings'))
    remember=session.permanent
    require_verification(uid)
    session.clear();session['pending_email_user']=uid;session['verify_remember']=remember
    _send_email_challenge(uid)
    return redirect(url_for('verify_email'))


@app.route('/verify-email',methods=['GET','POST'])
def verify_email():
    from backend.email_verification import confirm_code
    uid=session.get('pending_email_user')
    user=get_user_by_id(uid) if uid else None
    if not user:return redirect(url_for('login'))
    if request.method=='POST':
        if request.form.get('action')=='resend':
            _send_email_challenge(uid)
            return redirect(url_for('verify_email'))
        code=request.form.get('code','')[:64]
        if confirm_code(uid,code):
            remember=session.get('verify_remember',False)
            session.clear();session['user_id']=uid;session.permanent=remember
            flash('Your email is verified. Welcome to TalentSouk.','success')
            return redirect(url_for('onboarding') if onboarding_required(uid) else url_for('dashboard'))
        flash('Code invalid, expired or attempt limit reached. Request a new code.','error')
    return render_template('verify_email.html',email=user['email'])


@app.route("/logout")
def logout():
    session.clear()
    return redirect(url_for("login"))


@app.route("/onboarding", methods=["GET", "POST"])
@login_required
def onboarding():
    user_id = session["user_id"]
    builder_data = get_cv_builder_data(user_id)
    if request.method == "GET" and not onboarding_required(user_id):
        return redirect(url_for("dashboard"))

    if request.method == "POST":
        career_goal = request.form.get("career_goal", "").strip().lower()
        target_position = request.form.get("target_position", "").strip()
        target_skills = collect_target_skills(request.form)
        target_location = request.form.get("target_location", "").strip()
        education_level = request.form.get("education_level", "").strip()
        experience_level = request.form.get("experience_level", "").strip()
        if career_goal not in CAREER_GOALS or not target_position:
            flash("Choose a career goal and enter your target role.", "error")
        elif any(len(value) > 500 for value in (target_position, target_skills, target_location)):
            flash("Please shorten your target role, skills, or location.", "error")
        elif education_level and education_level not in EDUCATION_LEVELS:
            flash("Choose a valid education level.", "error")
        elif experience_level and experience_level not in EXPERIENCE_LEVELS:
            flash("Choose a valid experience level.", "error")
        else:
            save_candidate_profile_metadata(
                user_id, builder_data["career_objective"], builder_data["profile_photo_filename"],
                target_position=target_position, career_field=builder_data["career_field"],
                target_location=target_location, target_skills=target_skills,
                career_goal=career_goal, education_level=education_level,
                experience_level=experience_level,
            )
            flash("Your career preferences have been saved.", "success")
            if request.files.get("cv_file") and request.files["cv_file"].filename:
                before = get_cv_for_user(user_id)
                response = cv_upload()
                after = get_cv_for_user(user_id)
                if not after or (before and before['stored_filename'] == after['stored_filename']):
                    return response
            return redirect(url_for("personalize"))

    return render_template(
        "onboarding.html", profile=builder_data, career_goals=CAREER_GOALS,
        education_levels=EDUCATION_LEVELS, experience_levels=EXPERIENCE_LEVELS,
        target_skill_options=TARGET_SKILL_OPTIONS,
    )


# ---------------------------------------------------------------------------
# App pages (shared dashboard layout: sidebar + topbar) â€” login required
# ---------------------------------------------------------------------------

@app.route("/")
@app.route("/home")
def welcome():
    if session.get('user_id'):
        return redirect(url_for('dashboard'))
    return render_template('welcome.html',active_page='welcome',page_title='Home')


@app.route("/dashboard")
@login_required
def dashboard():
    user_id = session["user_id"]
    companies = get_all_companies()
    offers = get_offers()
    applications = [{**dict(a), "status": normalize_application_status(a["status"])} for a in get_applications_for_user(user_id)]
    reminders = [dict(r) for r in get_reminders(user_id) if not r["completed"]]
    companies_by_id = {company["id"]: company for company in companies}
    for reminder in reminders:
        company = companies_by_id.get(reminder["company_id"])
        reminder["company_name"] = company["name"] if company else "Company"
    for application in applications:
        company = companies_by_id.get(application.get("company_id"))
        application["company_name"] = company["name"] if company else "Company"

    statuses = [normalize_application_status(application.get("status")) for application in applications]
    category_counts = {}
    map_companies = []
    for company in companies:
        category = str(company.get("category") or "Other").strip() or "Other"
        category_counts[category] = category_counts.get(category, 0) + 1
        try:
            latitude = float(company.get("lat"))
            longitude = float(company.get("lng"))
        except (TypeError, ValueError):
            continue
        map_companies.append({
            "id": company["id"], "name": company["name"],
            "category": category, "area": company.get("area") or "Marrakech",
            "lat": latitude, "lng": longitude,
        })

    sorted_categories = sorted(category_counts.items(), key=lambda item: (-item[1], item[0]))
    category_chart = sorted_categories[:5]
    remaining_categories = sum(count for _category, count in sorted_categories[5:])
    if remaining_categories:
        category_chart.append(("Other categories", remaining_categories))

    category_colors = ["#311432", "#673147", "#A18F93", "#D8C7D8", "#8B6680", "#E6E6FA"]
    category_total = max(1, sum(count for _category, count in category_chart))
    category_stops = []
    category_cursor = 0.0
    category_chart_items = []
    for index, (category, count) in enumerate(category_chart):
        start = category_cursor
        category_cursor += (count / category_total) * 100
        color = category_colors[index % len(category_colors)]
        category_stops.append(f"{color} {start:.2f}% {category_cursor:.2f}%")
        category_chart_items.append({"name": category, "count": count, "color": color})

    company_dashboard = {
        "total": len(companies),
        "with_offers": len({offer.get("company_id") for offer in offers if offer.get("company_id")}),
        "offers": len(offers),
        "with_email": sum(bool(str(company.get("email") or "").strip()) for company in companies),
        "categories": sorted_categories[:10],
        "category_chart": category_chart_items,
        "category_gradient": ", ".join(category_stops) or "#E6E6FA 0% 100%",
        "map_companies": map_companies,
        "recent": companies[:6],
    }
    from backend.performance_service import analyze_performance
    activity = analyze_performance(applications, get_history(user_id), companies, get_cv_versions(user_id))
    from backend.dashboard_activity import saved_activity
    user_activity = saved_activity(user_id)
    user_dashboard = {
        "applications": len(applications),
        "wishlist": statuses.count("Wishlist"),
        "replies": activity["stages"]["outcomes"],
        "interviews": activity["stages"]["interviews"],
        "offers": statuses.count("Accepted") + statuses.count("Offer Received"),
        "recent": applications[:6],
    }
    preferences = get_cv_builder_data(user_id)
    profiles = preferences.get("profiles") or {}
    profile = {**(profiles.get("uploaded") or {}), **{k: v for k, v in (profiles.get("manual") or {}).items() if v}}
    profile_checks = [bool(str(profile.get(key) or "").strip()) for key in ("job_title", "summary", "skills", "experience", "education", "location")]
    profile_completion = round(100 * sum(profile_checks) / len(profile_checks))
    connection = get_db_connection()
    try:
        crm_count = connection.execute("SELECT COUNT(*) AS total FROM crm WHERE user_id=?", (user_id,)).fetchone()["total"]
    finally:
        connection.close()
    dashboard_home = {
        "profile_completion": profile_completion,
        "target_position": preferences.get("target_position") or "Your next career move",
        "target_location": preferences.get("target_location") or "Marrakech",
        "crm_count": crm_count,
        "latest_offers": sorted(offers, key=lambda offer: str(offer.get("publication_date") or ""), reverse=True)[:3],
    }
    return render_template(
        "dashboard.html", active_page="dashboard", page_title="Dashboard",
        company_dashboard=company_dashboard,
        user_dashboard=user_dashboard,
        reminders=reminders, user_activity=user_activity, dashboard_home=dashboard_home,
    )


@app.route("/companies")
@login_required
def companies():
    companies = get_all_companies()
    offers = get_offers(companies)
    skills_by_company = {}
    offer_link_by_company = {}
    for offer in offers:
        company_id = offer.get("company_id")
        if company_id is None:
            continue
        offer_url = str(offer.get("url") or "").strip()
        if (
            company_id not in offer_link_by_company
            and re.match(r"^https?://", offer_url, re.IGNORECASE)
        ):
            offer_link_by_company[company_id] = {
                "url": offer_url,
                "title": offer.get("title") or "View offer",
            }
        requirements = offer.get("requirements") or []
        if isinstance(requirements, str):
            requirements = re.split(r"[,;\n]+", requirements)
        saved = skills_by_company.setdefault(company_id, [])
        for skill in requirements:
            skill = str(skill).strip()
            if skill and skill.casefold() not in {item.casefold() for item in saved}:
                saved.append(skill)
    companies = [
        {
            **company,
            "skills": skills_by_company.get(company["id"], [])[:5],
            "offer_link": offer_link_by_company.get(company["id"]),
        }
        for company in companies
    ]
    from backend.company_catalog import enrich_catalog
    companies=enrich_catalog(companies,offers)
    companies=[company for company in companies if company['is_morocco']]
    source_options=sorted({str(offer.get('source') or '').strip() for offer in offers if offer.get('source')} | {source for company in companies for source in company['sources']})
    candidate = get_candidate_match_profile(session["user_id"])
    match_by_company = {}
    if has_candidate_match_data(candidate):
        for company in companies:
            match = match_company_offers(candidate, company, offers)
            if match is not None:
                match_by_company[str(company["id"])] = match
    return render_template(
        "companies.html", active_page="companies", companies=companies,
        match_by_company=match_by_company, data_unavailable=not companies, source_options=source_options
    )


@app.route("/api/company-search-history", methods=["POST"])
@login_required
def company_search_history_api():
    payload = request.get_json(silent=True) or {}
    save_company_search(session["user_id"], payload.get("query"))
    return jsonify(saved=True)


@app.route("/api/health")
def database_health():
    status = connection_status()
    return jsonify(status), 200 if status["ok"] else 503


@app.route('/api/dashboard/charts')
@login_required
def dashboard_chart_data():
    from backend.dashboard_charts import summarize_charts
    from backend.dashboard_activity import saved_activity
    response = jsonify(summarize_charts(get_all_companies(), saved_activity(session['user_id'])))
    response.headers['Cache-Control'] = 'no-store'
    return response


@app.route("/api/dashboard/stats")
@login_required
def api_dashboard_stats():
    try:
        return jsonify(fetch_dashboard_stats(session.get("user_id")))
    except Exception:
        app.logger.exception("SQLite dashboard statistics query failed")
        return jsonify(error="Dashboard statistics are temporarily unavailable."), 503


@app.route("/api/companies")
def api_companies():
    search = request.args.get("search", "").strip()
    city = request.args.get("city", "").strip()
    category = request.args.get("category", "").strip()
    raw_has_email = request.args.get("has_email", "").strip().casefold()
    raw_min_score = request.args.get("min_score", "").strip()
    raw_limit = request.args.get("limit", "100").strip()
    raw_offset = request.args.get("offset", "0").strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        return jsonify(error="limit must be an integer between 1 and 1000"), 400
    if not 1 <= limit <= 1000:
        return jsonify(error="limit must be between 1 and 1000"), 400
    try:
        offset = int(raw_offset)
    except ValueError:
        return jsonify(error="offset must be a non-negative integer"), 400
    if offset < 0:
        return jsonify(error="offset must be a non-negative integer"), 400
    if raw_has_email not in {"", "true", "false", "1", "0", "yes", "no"}:
        return jsonify(error="has_email must be true or false"), 400
    has_email = None if not raw_has_email else raw_has_email in {"true", "1", "yes"}
    try:
        min_score = float(raw_min_score) if raw_min_score else None
    except ValueError:
        return jsonify(error="min_score must be a non-negative number"), 400
    if min_score is not None and min_score < 0:
        return jsonify(error="min_score must be a non-negative number"), 400

    try:
        result = query_companies_for_api(
            query=search, city=city, category=category,
            has_email=has_email, min_score=min_score, limit=limit, offset=offset,
        )
    except Exception:
        app.logger.exception("SQLite companies query failed")
        return jsonify(error="Company data is temporarily unavailable."), 503

    companies = result["items"]
    return jsonify(companies=companies, count=len(companies), total=result["total"])


@app.route("/api/companies/<int:company_id>/status", methods=["PATCH"])
@login_required
def api_company_status(company_id):
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Company not found."), 404

    payload = request.get_json(silent=True) or {}
    status = str(payload.get("status", "")).strip()
    allowed_statuses = {
        "Discovered", "Contacted", "Wishlist", "Applied",
        "Replied", "Interview", "Offer Received",
    }
    if status not in allowed_statuses:
        return jsonify(error="Choose a valid company status."), 400
    if not update_company_status(company_id, status):
        return jsonify(error="Company status could not be updated."), 404

    user_id = session.get("user_id")
    if user_id:
        from backend.database import get_db_connection
        conn = get_db_connection()
        try:
            now = datetime.now().astimezone().isoformat()
            if status == "Wishlist":
                existing = conn.execute(
                    "SELECT id FROM applications WHERE user_id = ? AND company_id = ?",
                    (user_id, company_id)
                ).fetchone()
                if existing:
                    conn.execute(
                        "UPDATE applications SET status = 'Wishlist', updated_at = ? WHERE id = ?",
                        (now, existing["id"])
                    )
                    conn.execute(
                        "UPDATE crm SET status = 'Wishlist', updated_at = ? WHERE user_id = ? AND company_id = ?",
                        (now, user_id, company_id)
                    )
                else:
                    cur = conn.execute(
                        """
                        INSERT INTO applications (
                            user_id, company_id, position, contact_email, status,
                            last_contact_date, notes, created_at, updated_at
                        ) VALUES (?, ?, 'Wishlist opportunity', ?, 'Wishlist', '', 'Added from directory', ?, ?)
                        """,
                        (user_id, company_id, company.get("email") or "", now, now)
                    )
                    app_id = cur.lastrowid
                    conn.execute(
                        """
                        INSERT INTO crm (
                            user_id, company_id, application_id, contact_email, status,
                            last_contact_date, notes, created_at, updated_at
                        ) VALUES (?, ?, ?, ?, 'Wishlist', '', 'Added from directory', ?, ?)
                        """,
                        (user_id, company_id, app_id, company.get("email") or "", now, now)
                    )
                conn.commit()
            elif status == "Discovered":
                conn.execute(
                    "DELETE FROM crm WHERE user_id = ? AND company_id = ? AND status = 'Wishlist'",
                    (user_id, company_id)
                )
                conn.execute(
                    "DELETE FROM applications WHERE user_id = ? AND company_id = ? AND status = 'Wishlist'",
                    (user_id, company_id)
                )
                conn.commit()
            else:
                existing = conn.execute(
                    "SELECT id FROM applications WHERE user_id = ? AND company_id = ?",
                    (user_id, company_id)
                ).fetchone()
                if existing:
                    mapped = normalize_application_status(status)
                    conn.execute(
                        "UPDATE applications SET status = ?, updated_at = ? WHERE id = ?",
                        (mapped, now, existing["id"])
                    )
                    conn.execute(
                        "UPDATE crm SET status = ?, updated_at = ? WHERE user_id = ? AND company_id = ?",
                        (mapped, now, user_id, company_id)
                    )
                    conn.commit()
        except Exception:
            app.logger.exception("Failed to sync company status to user crm")
        finally:
            conn.close()

    return jsonify(company_id=company_id, status=status)


@app.route("/api/jobs")
def api_jobs():
    search = request.args.get("search", "").strip()
    location = request.args.get("location", "").strip()
    source = request.args.get("source", "").strip()
    contract_type = request.args.get("contract_type", "").strip()
    raw_company_id = request.args.get("company_id", "").strip()
    raw_limit = request.args.get("limit", "100").strip()
    try:
        limit = int(raw_limit)
    except ValueError:
        return jsonify(error="limit must be an integer between 1 and 1000"), 400
    if not 1 <= limit <= 1000:
        return jsonify(error="limit must be between 1 and 1000"), 400
    try:
        company_id = int(raw_company_id) if raw_company_id else None
    except ValueError:
        return jsonify(error="company_id must be an integer"), 400
    if company_id is not None and company_id < 1:
        return jsonify(error="company_id must be a positive integer"), 400

    try:
        result = query_jobs_for_api(
            query=search, location=location, source=source,
            contract_type=contract_type, company_id=company_id, limit=limit,
        )
    except Exception:
        app.logger.exception("SQLite jobs query failed")
        return jsonify(error="Job data is temporarily unavailable."), 503

    jobs = result["items"]
    return jsonify(jobs=jobs, count=len(jobs), total=result["total"])


@app.route("/api/contacts")
def api_contacts():
    company_id = request.args.get("company_id", "").strip()
    email_status = request.args.get("email_status", "all").strip().casefold()
    allowed_statuses = {"all", "available", "missing", "verified", "unverified"}
    if email_status not in allowed_statuses:
        return jsonify(
            error="email_status must be one of: all, available, missing, verified, unverified"
        ), 400
    if company_id:
        try:
            company_id = int(company_id)
        except ValueError:
            return jsonify(error="company_id must be an integer"), 400

    try:
        contacts = fetch_contacts_for_api()
    except Exception:
        app.logger.exception("SQLite company contacts query failed")
        return jsonify(error="Contact data is temporarily unavailable."), 503

    if company_id:
        contacts = [contact for contact in contacts if contact["company_id"] == company_id]
    if email_status == "available":
        contacts = [contact for contact in contacts if contact["email"]]
    elif email_status == "missing":
        contacts = [contact for contact in contacts if not contact["email"]]
    elif email_status == "verified":
        contacts = [contact for contact in contacts if contact["email"] and contact["is_verified"]]
    elif email_status == "unverified":
        contacts = [contact for contact in contacts if contact["email"] and not contact["is_verified"]]

    return jsonify(contacts=contacts, count=len(contacts))


@app.route("/companies/map")
@login_required
def companies_map():
    companies = get_all_companies()
    category_counts = {}
    for company in companies:
        category = company.get("category") or "Other"
        category_counts[category] = category_counts.get(category, 0) + 1
    category_stats = sorted(category_counts.items(), key=lambda item: (-item[1], item[0].casefold()))
    return render_template(
        "companies_map.html", active_page="companies", companies=companies,
        category_stats=category_stats, company_total=len(companies),
    )


@app.route("/companies/<int:company_id>")
@login_required
def company_detail(company_id):
    company = get_company(company_id)
    if company is None:
        flash("That company couldn't be found.", "error")
        return redirect(url_for("companies"))
    offers = get_offers(get_all_companies())
    candidate = get_candidate_match_profile(session["user_id"])
    match = (
        match_company_offers(candidate, company, offers)
        if has_candidate_match_data(candidate) else None
    )
    company_applications = []
    for item in get_applications_for_user(session["user_id"]):
        if item["company_id"] == company_id:
            entry = dict(item); entry["history"] = [dict(event) for event in get_history(session["user_id"], item["id"])]
            company_applications.append(entry)
    from backend.networking_service import company_insights
    intel=company_insights(session["user_id"],company_id,[o for o in offers if o["company_id"]==company_id])
    company_reminders=[dict(r) for r in get_reminders(session["user_id"]) if r["company_id"]==company_id]
    return render_template(
        "company_detail.html", active_page="companies", company=company, match=match,
        offers=[offer for offer in offers if offer["company_id"] == company_id], company_applications=company_applications, intel=intel, company_reminders=company_reminders
    )


@app.route("/applications")
@app.route("/crm/applications")
@login_required
def applications():
    user_id = session["user_id"]
    candidate = get_candidate_match_profile(user_id)
    has_candidate_details = has_candidate_match_data(candidate)
    offers = get_offers(get_all_companies())
    applications_list = []
    reminders_by_application = {}
    for reminder in get_reminders(user_id): reminders_by_application.setdefault(reminder["application_id"], []).append(dict(reminder))
    for application in get_applications_for_user(user_id):
        display_status = normalize_application_status(application["status"])
        company = get_company(application["company_id"])
        if display_status is None or company is None:
            continue

        position = application["position"]
        offer = next(
            (
                item for item in offers
                if item["company_id"] == company["id"]
                and item["title"].casefold() == position.casefold()
            ),
            None,
        )
        match = (
            match_candidate_to_offer(candidate, company, offer)
            if has_candidate_details and offer is not None else None
        )

        item = dict(application)
        try:
            item['cv_version'] = _owned_cv_choice(user_id,str(item.get('cv_used') or ''))
        except ValueError:
            item['cv_version'] = None
        item.update({
            "company_name": company["name"],
            "company_category": company["category"],
            "company_url": url_for("company_detail", company_id=company["id"]),
            "display_status": display_status,
            "applied_date": application["applied_at"] or application["created_at"],
            "last_update": (
                application["updated_at"]
                or application["last_contact_date"]
                or application["created_at"]
            ),
            "match_score": match["score"] if match else None,
            "match": match,
            "reminders": reminders_by_application.get(application["id"], []),
            "history": [dict(event) for event in get_history(user_id, application["id"])],
        })
        applications_list.append(item)

    return render_template(
        "applications.html",
        active_page="crm", crm_view="applications",
        applications=applications_list,
        statuses=APPLICATION_STATUSES,
    )


@app.route('/opportunity-radar')
@app.route('/jobs')
@login_required
def opportunity_radar():
    from backend.opportunity_radar import radar_data
    from backend.job_sources import source_status, COUNTRIES, PROVIDERS, MARRAKECH_PROVIDERS
    from backend.radar_watch import watch_status
    watcher,source_checks=watch_status()
    offers, last_refresh = radar_data()
    sources = sorted({o['source'] for o in offers if o['source']} | {PROVIDERS[p] for p in MARRAKECH_PROVIDERS})
    locations = sorted({o['location'] for o in offers if o['location']})
    contracts = sorted({o['offer_type'] for o in offers if o['offer_type']})
    search = request.args.get('q', '').strip()[:200]
    filters = {key: request.args.get(key, '').strip() for key in ('source', 'location', 'contract')}
    filtered = [o for o in offers if (not search or search.casefold() in ' '.join(str(o.get(k) or '') for k in ('title','company_name','description')).casefold())
        and (not filters['source'] or o['source'] == filters['source'])
        and (not filters['location'] or o['location'] == filters['location'])
        and (not filters['contract'] or o['offer_type'] == filters['contract'])]
    matching_companies = []
    has_matching_profile = False
    page = max(1, request.args.get('page', 1, type=int) or 1)
    pages = max(1, (len(filtered)+19)//20)
    page = min(page, pages)
    return render_template('opportunity_radar.html', active_page='opportunity_radar', offers=filtered[(page-1)*20:page*20],
        total=len(filtered), last_refresh=last_refresh, sources=sources, locations=locations, contracts=contracts,
        search=search, filters=filters, page=page, pages=pages, page_title='Job offers', matching_companies=matching_companies, has_matching_profile=has_matching_profile, source_status=source_status(), countries=COUNTRIES,watcher=watcher,source_checks=source_checks)


@app.route('/performance-lab')
@app.route('/crm/performance')
@login_required
def performance_lab():
    from backend.dashboard_activity import activity_calendar
    from backend.performance_service import analyze_performance
    report=analyze_performance(get_applications_for_user(session['user_id']),get_history(session['user_id']),get_all_companies(),get_cv_versions(session['user_id']))
    return render_template('performance_lab.html',active_page='crm',crm_view='performance',page_title='CRM',report=report,activity_calendar=activity_calendar(session['user_id']))


@app.route('/portfolio')
@login_required
def portfolio():
    from backend.portfolio_service import get_projects,CATALOG,canonical_skill,project_template,THEMES,studio_settings,suggested_projects
    skill=canonical_skill(request.args.get('skill',''))
    offer_id=request.args.get('offer_id',0,type=int) or 0
    offer=None
    if offer_id:
        from backend.opportunity_radar import radar_data
        offer=next((o for o in radar_data()[0] if o['id']==offer_id),None)
    if not offer:offer_id=0
    uid=session['user_id']
    profile=get_candidate_match_profile(uid)
    builder=get_cv_builder_data(uid)
    projects=get_projects(uid)
    return render_template('portfolio.html',active_page='portfolio',page_title='Portfolio Studio',
        projects=projects,catalog=CATALOG,selected_skill=skill,
        suggestion=project_template(skill) if skill else None,offer=offer,offer_id=offer_id,
        recommendations=suggested_projects(profile,builder.get('target_position','')),
        studio=studio_settings(uid),themes=THEMES,profile=profile,
        ready_projects=[p for p in projects if p['completed']])


@app.route('/api/portfolio/about-me', methods=['POST'])
@login_required
def portfolio_about_me():
    from backend.portfolio_ai import generate_about_me
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error='Invalid generation request.'), 400
    language = str(payload.get('language') or 'en').lower()
    headline = payload.get('headline', '')
    if language not in {'en', 'fr', 'ar'} or not isinstance(headline, str) or len(headline) > 180:
        return jsonify(error='Check your language and professional title.'), 400
    choice = _feature_ai_choice('generation')
    if not choice:
        return jsonify(error='AI generation is unavailable. Please check the Gemini configuration.'), 503
    try:
        bio = generate_about_me(get_candidate_match_profile(session['user_id']), headline, language, choice)
    except (AIServiceError, ValueError) as error:
        return jsonify(error=str(error)), getattr(error, 'status_code', 400)
    return jsonify(bio=bio)


@app.route('/portfolio/design',methods=['POST'])
@login_required
def portfolio_design():
    from backend.portfolio_service import save_studio_settings
    try:
        save_studio_settings(session['user_id'],request.form)
        flash('Your portfolio design and introduction are saved.','success')
    except ValueError as error:
        flash(str(error),'error')
    return redirect(url_for('portfolio')+'#design')


@app.route('/portfolio/preview')
@app.route('/portfolio/export',endpoint='portfolio_export')
@login_required
def portfolio_preview():
    from backend.portfolio_service import get_projects,studio_settings,THEMES
    uid=session['user_id']
    studio=studio_settings(uid)
    html=render_template('portfolio_showcase.html',studio=studio,theme=THEMES[studio['theme']],
        profile=get_candidate_match_profile(uid),
        projects=[p for p in get_projects(uid) if p['completed']])
    response=make_response(html)
    if request.path.endswith('/export'):
        response.headers['Content-Disposition']='attachment; filename="my-portfolio.html"'
    return response


@app.route('/portfolio/projects',methods=['POST'])
@login_required
def portfolio_create():
    from backend.portfolio_service import create_project
    try:
        offer_id=int(request.form.get('offer_id','0'))
        if offer_id:
            from backend.opportunity_radar import radar_data
            if not any(o['id']==offer_id for o in radar_data()[0]):raise ValueError('Offer no longer available. Choose a current offer or start without one.')
        project_id=create_project(session['user_id'],request.form.get('skill',''),offer_id)
    except (ValueError,TypeError) as error:
        flash(str(error),'error');return redirect(url_for('portfolio'))
    return redirect(url_for('portfolio_project',project_id=project_id))


@app.route('/portfolio/projects/<int:project_id>',methods=['GET','POST'])
@login_required
def portfolio_project(project_id):
    from backend.portfolio_service import get_project,save_project
    project=get_project(session['user_id'],project_id)
    if not project:return 'Project not found.',404
    if request.method=='POST':
        try:
            checked=[int(v) for v in request.form.getlist('checked')]
            save_project(session['user_id'],project_id,checked,request.form.get('evidence_url',''),request.form.get('summary',''),request.form.get('notes',''),request.form.get('completed')=='1')
            flash('Project progress and evidence saved.','success')
            return redirect(url_for('portfolio_project',project_id=project_id))
        except ValueError as error:
            flash(str(error),'error')
            project.update(checked=[i for i in range(len(project['checklist'])) if str(i) in request.form.getlist('checked')],evidence_url=request.form.get('evidence_url','')[:2000],summary=request.form.get('summary','')[:2000],notes=request.form.get('notes','')[:4000],completed=request.form.get('completed')=='1')
            return render_template('portfolio_project.html',active_page='portfolio',page_title='My proof project',project=project),400
    return render_template('portfolio_project.html',active_page='portfolio',page_title='My proof project',project=project)


@app.route('/portfolio/projects/<int:project_id>/readme')
@login_required
def portfolio_readme(project_id):
    from backend.portfolio_service import get_project,readme_text
    project=get_project(session['user_id'],project_id)
    if not project:return 'Project not found.',404
    response=make_response(readme_text(project))
    response.headers['Content-Type']='text/markdown; charset=utf-8'
    response.headers['Content-Disposition']='attachment; filename="README-project-'+str(project_id)+'.md"'
    return response


@app.route('/portfolio/projects/<int:project_id>/cv',methods=['POST'])
@login_required
def portfolio_cv(project_id):
    from backend.portfolio_service import add_to_cv
    try:
        if not add_to_cv(session['user_id'],project_id):return 'Project not found.',404
        flash('Project added to your editable CV and candidate profile. Review it in CV Builder before exporting.','success')
        return redirect(url_for('cv_builder'))
    except ValueError as error:
        flash(str(error),'error');return redirect(url_for('portfolio_project',project_id=project_id))


@app.route('/career-copilot')
@login_required
def career_copilot():
    from backend.copilot_service import get_plan, week_start
    week=request.args.get('week',week_start())
    try:
        parsed=date.fromisoformat(week)
        if parsed.weekday()!=0:raise ValueError()
    except (ValueError,TypeError):return 'Choose a valid week.',400
    plan,tasks,history=get_plan(session['user_id'],week)
    tasks=[task for task in tasks if not task['url'].startswith('/networking')]
    for task in tasks:
        if task['url'].startswith('/career-dna'):
            task['url']=url_for('profile');task['title']='Review my profile'
    completed=sum(task['completed'] for task in tasks)
    return render_template('career_copilot.html',active_page='career_copilot',page_title='My career plan',
        plan=plan,tasks=tasks,history=history,week=week,current_week=week_start(),
        end_date=(parsed+timedelta(days=6)).isoformat(),completed=completed,
        progress=round(100*completed/len(tasks)) if tasks else 0)


@app.route('/career-copilot/plan',methods=['POST'])
@login_required
def career_copilot_plan():
    from backend.copilot_service import create_plan
    create_plan(session['user_id'])
    flash('Weekly suggestions saved. Your existing tasks and progress are preserved.','success')
    return redirect(url_for('career_copilot'))


@app.route('/career-copilot/tasks',methods=['POST'])
@login_required
def career_copilot_add():
    from backend.copilot_service import add_custom_task,get_plan,week_start
    plan,tasks,_=get_plan(session['user_id'])
    title=request.form.get('title','').strip()
    try:
        due=date.fromisoformat(request.form.get('due_date',''))
        start=date.fromisoformat(week_start())
        if not title or len(title)>200 or not 0<=(due-start).days<=6 or not plan or len(tasks)>=25:raise ValueError()
    except ValueError:
        flash('Create your plan first, then enter a task and a date within this week (maximum 25 tasks).','error')
        return redirect(url_for('career_copilot'))
    add_custom_task(session['user_id'],title,due.isoformat())
    return redirect(url_for('career_copilot'))


@app.route('/career-copilot/tasks/<int:task_id>',methods=['POST'])
@login_required
def career_copilot_task(task_id):
    from backend.copilot_service import change_task
    conn=get_db_connection()
    try:row=conn.execute('SELECT * FROM career_tasks WHERE id=? AND user_id=?',(task_id,session['user_id'])).fetchone()
    finally:conn.close()
    if not row:return 'Task not found.',404
    values=dict(row)
    if request.form.get('action')=='toggle':values['completed']=not values['completed']
    elif request.form.get('action')=='edit':
        try:
            title=request.form.get('title','').strip();due=date.fromisoformat(request.form.get('due_date',''))
            if not title or len(title)>200 or not 0<=(due-date.fromisoformat(row['week'])).days<=6:raise ValueError()
            values.update(title=title,due_date=due.isoformat())
        except ValueError:
            flash('Enter a task title and a date within the selected week.','error')
            return redirect(url_for('career_copilot',week=row['week']))
    else:return 'Invalid action.',400
    change_task(session['user_id'],task_id,values)
    return redirect(url_for('career_copilot',week=row['week']))


@app.route('/opportunities/<int:offer_id>')
@login_required
def opportunity_detail(offer_id):
    from backend.opportunity_radar import radar_data
    offers,_=radar_data()
    offer=next((o for o in offers if o['id']==offer_id),None)
    if offer is None:return 'Offer not found',404
    return render_template('opportunity_detail.html',active_page='opportunity_radar',page_title='Job offers',offer=offer)


@app.route('/opportunity-radar/refresh', methods=['POST'])
@login_required
def opportunity_radar_refresh():
    from backend.opportunity_radar import refresh_local_offers, refresh_external_offers
    provider=request.form.get('provider','local_csv')
    try:
        if provider=='local_csv':
            result = refresh_local_offers(PROJECT_ROOT / 'data' / 'all_jobs_marrakech (2).csv')
        else:
            result = refresh_external_offers(provider, request.form.get('country','ma'), request.form.get('keyword',''),request.form.get('city',''),pages=5 if provider in {'jooble','adzuna'} else 1)
        flash('Refresh complete: %s new offers, %s existing offers checked.' % (result['created'],result['updated']), 'success')
    except (ValueError, OSError) as error:
        flash(str(error) if isinstance(error, ValueError) else 'The local offers file could not be read. Try again later.', 'error')
    except Exception:
        app.logger.warning('Opportunity refresh failed without exposing provider credentials')
        flash('Refresh failed. No offers were changed. Try again later.', 'error')
    return redirect(url_for('opportunity_radar'))


@app.route("/postulations")
@login_required
def postulations():
    user_id = session["user_id"]
    cv = get_cv_for_user(user_id)
    builder_data = get_cv_builder_data(user_id)
    manual_profile = builder_data["profiles"].get("manual") or {}
    cv_options = []
    if cv is not None:
        cv_options.append({"value": "uploaded", "label": cv["original_filename"]})
    if any(str(value or "").strip() for value in manual_profile.values()):
        cv_options.append({"value": "manual", "label": "Manual CV"})
    if builder_data.get("optimized"):
        cv_options.append({"value": "optimized", "label": "Saved optimized CV"})
    for version in get_cv_versions(user_id):
        cv_options.append({'value':'version:%s' % version['id'], 'label':'CV #%s · %s · %s · %s' % (version['id'], version['optimized'].get('offer_title') or 'Saved version', version['optimized'].get('company_name') or '', version['created_at'])})


    from backend.company_catalog import enrich_catalog, in_morocco
    all_companies=get_all_companies()
    all_offers=get_offers(all_companies)
    company_options=enrich_catalog(all_companies,all_offers)
    company_options=[company for company in company_options if company['is_morocco'] or company['id']==request.args.get('company_id',type=int)]
    offer_options=[offer for offer in all_offers if in_morocco({'area':offer.get('location')}) or offer['id']==request.args.get('job_id',type=int)]
    return render_template(
        "postulations.html",
        active_page="postulations",
        companies=company_options,
        offers=offer_options,
        cv_options=cv_options,
        selected_cv_choice=("version:%s" % request.args.get("cv_version_id", type=int)) if request.args.get("cv_version_id", type=int) else "",
        selected_company_id=request.args.get("company_id", type=int),
        selected_job_id=request.args.get("job_id", type=int),
        gmail_connected=get_gmail_credentials(user_id) is not None,
        gmail_configured=gmail_is_configured(),
    )


def _owned_cv_choice(user_id, choice):
    if not choice.startswith('version:'):
        return None
    try:
        version_id=int(choice.split(':',1)[1])
    except (ValueError,TypeError):
        raise ValueError('Choose one of your saved CV versions.')
    version=get_cv_version(user_id,version_id)
    if version is None or not isinstance(version['optimized'].get('profile'),dict):
        raise ValueError('Choose one of your saved CV versions.')
    return version


@app.route("/api/postulations", methods=["POST"])
@login_required
def postulation_create():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="A JSON request body is required."), 400

    try:
        company_id = int(payload.get("company_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Choose a company."), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Company not found."), 400

    raw_job_id = payload.get("job_id")
    job_id = None
    offer = None
    if raw_job_id not in (None, ""):
        try:
            job_id = int(raw_job_id)
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid offer."), 400
        offer = get_job_offer_for_application(job_id)
        if offer is None:
            return jsonify(error="Job offer not found."), 400
        if offer.get("company_id") is not None and offer["company_id"] != company_id:
            return jsonify(error="The offer belongs to a different company."), 400

    user_id = session["user_id"]
    cv_choice = str(payload.get("cv", "")).strip()
    builder_data = get_cv_builder_data(user_id)
    manual_profile = builder_data["profiles"].get("manual") or {}
    valid_cv_choices = set()
    if get_cv_for_user(user_id) is not None:
        valid_cv_choices.add("uploaded")
    if any(str(value or "").strip() for value in manual_profile.values()):
        valid_cv_choices.add("manual")
    if builder_data.get("optimized"):
        valid_cv_choices.add("optimized")
    try:
        selected_version=_owned_cv_choice(user_id,cv_choice)
    except ValueError as exc:
        return jsonify(error=str(exc)),400
    if selected_version:
        valid_cv_choices.add(cv_choice)
    if cv_choice not in valid_cv_choices:
        return jsonify(error="Choose one of your saved CVs."), 400
    if cv_choice == 'optimized':
        version_id=builder_data['optimized'].get('version_id')
        if not version_id:
            versions=get_cv_versions(user_id)
            version_id=versions[0]['id'] if versions else None
        if version_id and get_cv_version(user_id,version_id):
            cv_choice='version:%s' % version_id


    message = str(payload.get("message", "")).strip()
    if not message or len(message) > 5000:
        return jsonify(error="Enter an application message of up to 5000 characters."), 400

    position = offer["title"] if offer else str(payload.get("position", "")).strip()
    if not position or len(position) > 180:
        return jsonify(error="Enter a target position of up to 180 characters."), 400
    cover_letter = str(payload.get("cover_letter", "")).strip()
    if len(cover_letter) > 15000:
        return jsonify(error="The cover letter must not exceed 15000 characters."), 400

    values = {
        "user_id": user_id,
        "profile_id": str(user_id),
        "company_id": company_id,
        "job_id": job_id,
        "position": position,
        "status": "Draft",
        "cv_used": cv_choice,
        "preserve_sent_cv": True,
        "application_message": message,
        "cover_letter_used": cover_letter,
    }
    try:
        application = create_tracked_application(values)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except Exception:
        app.logger.exception("SQLite postulation creation failed")
        return jsonify(error="The postulation could not be saved."), 503

    add_history(
        user_id,
        application["id"],
        "Application drafted",
        f"Draft created for {company['name']}",
    )
    return jsonify(
        success=True,
        message="Postulation saved locally. No email was sent.",
        application=application,
        applications_url=url_for("applications"),
    ), 201


def _cover_letter_context(payload):
    """Resolve a user-owned CV and a real SQLite target for letter generation."""
    try:
        company_id = int(payload.get("company_id", ""))
    except (TypeError, ValueError):
        raise ValueError("Choose a company.")
    company = get_company(company_id)
    if company is None:
        raise ValueError("Company not found.")

    job_id = payload.get("job_id")
    offer = None
    if job_id not in (None, ""):
        try:
            offer = get_job_offer_for_application(int(job_id))
        except (TypeError, ValueError):
            offer = None
        if offer is None:
            raise ValueError("Job offer not found.")
        if offer.get("company_id") is not None and offer["company_id"] != company_id:
            raise ValueError("The offer belongs to a different company.")

    cv_choice = str(payload.get("cv", payload.get("cv_source", ""))).strip()
    user_id = session["user_id"]
    builder = get_cv_builder_data(user_id)
    if cv_choice in {"manual", "uploaded"}:
        profile = dict(builder["profiles"].get(cv_choice) or {})
    elif cv_choice == "optimized" and builder.get("optimized"):
        profile = dict(builder["optimized"].get("profile") or {})
    elif cv_choice.startswith('version:'):
        version=_owned_cv_choice(user_id,cv_choice)
        profile=dict(version['optimized']['profile'])

    else:
        raise ValueError("Choose one of your saved CVs.")
    if cv_choice == "uploaded":
        uploaded = get_cv_for_user(user_id)
        if uploaded is None:
            raise ValueError("Choose one of your saved CVs.")
        profile["cv_text"] = uploaded["extracted_text"] or ""

    user = get_user_by_id(user_id)
    profile["full_name"] = profile.get("full_name") or (user["full_name"] if user else "")
    profile["email"] = profile.get("email") or (user["email"] if user else "")
    position = offer["title"] if offer else str(payload.get("position", "")).strip()
    if not position or len(position) > 180:
        raise ValueError("Enter a target position of up to 180 characters.")
    return profile, offer, company, position


@app.route("/api/postulations/channels", methods=["POST"])
@login_required
def postulation_channels():
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error="A JSON request body is required."),400
    try:
        _,offer,company,_=_cover_letter_context(payload)
    except ValueError as exc:return jsonify(error=str(exc)),400
    email=str(company.get('email') or '').strip()
    recipient=parseaddr(email)[1]
    if not _valid_email(recipient):recipient=''
    phone=str(company.get('phone') or '').strip()
    digits=re.sub(r'[^0-9]','',phone)
    if phone.startswith('00'):digits=digits[2:]
    elif not phone.startswith('+'):
        area=str(company.get('area') or '')+' '+str(company.get('address') or '')
        if digits.startswith('0') and len(digits)==10 and re.search(r'maroc|morocco|marrakech|casablanca|rabat',area,re.I):digits='212'+digits[1:]
        elif not digits.startswith('212'):digits=''
    if not 8<=len(digits)<=15:digits=''
    raw_url=str((offer or {}).get('url') or '')
    from urllib.parse import urlsplit
    try:
        parsed=urlsplit(raw_url)
        official_url=raw_url if parsed.scheme in {'http','https'} and parsed.netloc and not parsed.username and not parsed.password else ''
    except ValueError:
        official_url=''
    return jsonify(email=recipient,whatsapp_number=digits,offer_url=official_url,gmail_connected=get_gmail_credentials(session['user_id']) is not None,gmail_configured=gmail_is_configured())


@app.route("/api/postulations/message", methods=["POST"])
@login_required
def postulation_message():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="A JSON request body is required."), 400
    try:
        profile, offer, company, position = _cover_letter_context(payload)
        language = str(payload.get("language") or "en").lower()
        if language not in {"en", "fr", "ar"}:
            raise ValueError("Choose English, French, or Arabic.")
        messages = generate_application_messages(profile, company, _feature_ai_choice("generation"), language, offer=offer, position=position)
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except AIServiceError as exc:
        return _ai_error_response(exc)
    return jsonify(message=messages[0], messages=messages, evidence_only=True)


@app.route("/api/postulations/cover-letter", methods=["POST"])
@login_required
def postulation_cover_letter():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="A JSON request body is required."), 400
    try:
        profile, offer, company, position = _cover_letter_context(payload)
        language = str(payload.get("language") or "en").lower()
        if language not in {"en", "fr", "ar"}:
            raise ValueError("Choose English, French, or Arabic.")
        letter = generate_ai_cover_letter(
            profile, offer, company, position, language=language, ai_choice=_feature_ai_choice("generation")
        )
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    except AIServiceError as exc:
        return _ai_error_response(exc)
    return jsonify(
        cover_letter=letter,
        company_name=company["name"],
        position=position,
        target_type="offer" if offer else "spontaneous",
        evidence_only=True,
    )


@app.route("/gmail/connect")
@login_required
def gmail_connect():
    try:
        state = create_oauth_state()
        session["gmail_oauth_state"] = state
        destination = request.args.get("next", "postulations")
        session["gmail_oauth_return"] = (
            destination if destination in {"postulations", "applications", "settings"} else "postulations"
        )
        return redirect(authorization_url(state))
    except GmailServiceError as exc:
        flash(str(exc), "error")
        return redirect(url_for("postulations"))


@app.route("/gmail/callback")
@login_required
def gmail_callback():
    return_endpoint = session.pop("gmail_oauth_return", "postulations")
    expected_state = session.pop("gmail_oauth_state", "")
    received_state = request.args.get("state", "")
    if not expected_state or not hmac.compare_digest(expected_state, received_state):
        flash("Gmail connection was rejected because the OAuth state was invalid.", "error")
        return redirect(url_for(return_endpoint))
    if request.args.get("error"):
        flash("Gmail connection was cancelled. No email was sent.", "error")
        return redirect(url_for(return_endpoint))
    code = request.args.get("code", "")
    if not code:
        flash("Google did not return an authorization code.", "error")
        return redirect(url_for(return_endpoint))
    try:
        token = exchange_authorization_code(code)
        identity = verified_google_identity(token)
        encrypted = encrypt_token(token, app.config["SECRET_KEY"])
        save_gmail_credentials(
            session["user_id"], encrypted, token["expires_at"], GMAIL_SEND_SCOPE,
            account_email=identity["email"], email_verified=identity["email_verified"],
        )
    except GmailServiceError as exc:
        flash(str(exc), "error")
    else:
        flash(f"Verified Gmail account connected: {identity['email']}", "success")
    return redirect(url_for(return_endpoint))


@app.route("/gmail/disconnect", methods=["POST"])
@login_required
def gmail_disconnect():
    delete_gmail_credentials(session["user_id"])
    flash("Gmail disconnected. Stored OAuth tokens were removed.", "success")
    destination = request.form.get("next", "postulations")
    return redirect(url_for(destination if destination in {"postulations", "settings"} else "postulations"))


def _selected_cv_attachment(user_id, cv_choice):
    if cv_choice == "uploaded":
        cv = get_cv_for_user(user_id)
        if cv is None:
            raise ValueError("The selected uploaded CV no longer exists.")
        path = cv_storage_path(cv["stored_filename"])
        if not path.is_file():
            raise ValueError("The selected uploaded CV file is unavailable.")
        mime_type = cv["mime_type"] or mimetypes.guess_type(cv["original_filename"])[0]
        return cv["original_filename"], mime_type or "application/octet-stream", path.read_bytes()

    builder = get_cv_builder_data(user_id)
    if cv_choice == "manual":
        profile = builder["profiles"].get("manual") or {}
    elif cv_choice == "optimized" and builder.get("optimized"):
        profile = builder["optimized"].get("profile") or {}
    elif cv_choice.startswith('version:'):
        version=_owned_cv_choice(user_id,cv_choice)
        profile=version['optimized']['profile']

    else:
        raise ValueError("The selected CV no longer exists.")
    fields = (
        ("Full name", "full_name"), ("Email", "email"), ("Phone", "phone"),
        ("Location", "location"), ("Summary", "summary"),
        ("Education", "education"), ("Experience", "experience"),
        ("Skills", "skills"), ("Projects", "projects"),
        ("Certifications", "certifications"), ("Languages", "languages"),
    )
    sections = [f"{label}\n{str(profile.get(key) or '').strip()}" for label, key in fields if str(profile.get(key) or "").strip()]
    if not sections:
        raise ValueError("The selected CV has no saved content.")
    filename = "optimized-cv.txt" if cv_choice == "optimized" else "cv.txt"
    if cv_choice.startswith("version:"):
        filename="cv-version-%s.txt" % version["id"]
    return filename, "text/plain", "\n\n".join(sections).encode("utf-8")


@app.route("/api/postulations/<int:application_id>/send", methods=["POST"])
@login_required
def postulation_send(application_id):
    user_id = session["user_id"]
    application = get_application_for_user(user_id, application_id)
    if application is None:
        return jsonify(error="Application not found."), 404
    payload = request.get_json(silent=True) or {}
    if payload.get("confirmed") is not True:
        return jsonify(error="Confirm the final email before sending."), 400
    if application["status"] not in {"Draft", "Prepared"}:
        return jsonify(error="Only a draft application can be sent."), 409

    company = get_company(application["company_id"])
    recipient = str((company or {}).get("email") or "").strip()
    parsed_recipient = parseaddr(recipient)[1]
    if not parsed_recipient or "@" not in parsed_recipient:
        return jsonify(error="This company has no valid email address in the database."), 400
    if not application["cover_letter_used"].strip():
        return jsonify(error="Add and preview a cover letter before sending."), 400

    credential = get_gmail_credentials(user_id)
    if credential is None:
        return jsonify(
            error="Connect Gmail before sending.",
            connect_url=url_for("gmail_connect", next="applications"),
        ), 401
    try:
        token = decrypt_token(credential["token_encrypted"], app.config["SECRET_KEY"])
        token, refreshed = ensure_access_token(token)
        if refreshed:
            save_gmail_credentials(
                user_id, encrypt_token(token, app.config["SECRET_KEY"]),
                token["expires_at"], GMAIL_SEND_SCOPE,
            )
        cv_attachment = _selected_cv_attachment(user_id, application["cv_used"])
        cover_attachment = (
            "cover-letter.txt", "text/plain",
            application["cover_letter_used"].encode("utf-8"),
        )
        subject_prefix = "Application" if application["job_id"] is not None else "Spontaneous application"
        raw_message = build_message(
            parsed_recipient,
            f"{subject_prefix} — {application['position']}",
            application["application_message"],
            [cv_attachment, cover_attachment],
        )
        sent = send_message(token["access_token"], raw_message)
    except (GmailServiceError, ValueError, OSError) as exc:
        app.logger.warning("Gmail send failed for application %s: %s", application_id, exc)
        return jsonify(error=str(exc)), 503

    saved = mark_application_sent(user_id, application_id, sent["id"], parsed_recipient)
    return jsonify(
        success=True,
        message="Application sent successfully through Gmail.",
        application=serialize_application(saved),
        applications_url=url_for("applications"),
    )


@app.route("/crm")
@login_required
def crm():
    return render_template(
        "crm.html", active_page="crm", companies=get_all_companies()
    )


def serialize_application(application):
    result = dict(application)
    result["status"] = normalize_application_status(result.get("status"))
    company = get_company(result["company_id"])
    result.update({
        "company_name": company["name"],
        "category": company["category"],
        "company_email": company["email"],
        "company_url": url_for("company_detail", company_id=company["id"]),
    })
    offers = get_offers(get_all_companies())
    candidate = get_candidate_match_profile(session["user_id"])
    result["match"] = get_match_for_position(
        candidate, company, result["position"], offers
    ) if has_candidate_match_data(candidate) else None
    return result


@app.route("/api/applications", methods=["GET", "POST"])
@login_required
def application_collection():
    if request.method == "GET":
        try:
            return jsonify(fetch_applications_for_api(session["user_id"]))
        except Exception:
            app.logger.exception("SQLite applications query failed")
            return jsonify(error="Application data is temporarily unavailable."), 503

    payload = request.get_json(silent=True) or {}
    try:
        company_id = int(payload.get("company_id", payload.get("company", "")))
        job_id = int(payload.get("job_id", payload.get("offer_id", payload.get("job", ""))))
    except (TypeError, ValueError):
        return jsonify(error="company_id and job_id must be integers"), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Company not found."), 400
    offer = get_job_offer_for_application(job_id)
    if offer is None:
        return jsonify(error="Job offer not found."), 400
    if offer.get("company_id") is not None and offer["company_id"] != company_id:
        return jsonify(error="The job offer does not belong to the selected company."), 400

    status = str(payload.get("status", "Draft")).strip()
    applied_at = str(payload.get("date", payload.get("applied_at", ""))).strip()
    notes = str(payload.get("notes", "")).strip()
    if status not in APPLICATION_STATUSES:
        return jsonify(error="Choose a valid application status."), 400
    if applied_at:
        try:
            datetime.fromisoformat(applied_at.replace("Z", "+00:00"))
        except ValueError:
            return jsonify(error="date must be a valid ISO-8601 date/time"), 400
    if len(notes) > 5000:
        return jsonify(error="notes must be 5000 characters or fewer"), 400
    profile_id = str(session["user_id"])
    values = {"profile_id": profile_id, "user_id": session["user_id"], "company_id": company_id, "job_id": job_id, "status": status}
    if applied_at:
        values["applied_at"] = applied_at
    try:
        application = create_tracked_application(values, notes)
        return jsonify(application), 201
    except Exception:
        app.logger.exception("SQLite application create failed")
        return jsonify(error="Could not create the application."), 503


def _valid_email(value):
    return bool(re.fullmatch(r"[^\s@]+@[^\s@]+\.[^\s@]+", str(value or "").strip()))


def _safe_smtp_error(exc):
    message = str(exc).strip() or exc.__class__.__name__
    password = os.environ.get("SMTP_PASSWORD", "")
    if password:
        message = message.replace(password, "[masqué]")
    return message[:1000]


@app.route("/api/apply/context")
@login_required
def apply_context():
    try:
        company_id = int(request.args.get("company_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Entreprise invalide."), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Entreprise introuvable."), 404
    if not _valid_email(company.get("email")):
        return jsonify(error="Cette entreprise ne possède pas d’adresse e-mail valide."), 422

    user = get_user_by_id(session["user_id"])
    cv = get_cv_for_user(session["user_id"])
    builder = get_cv_builder_data(session["user_id"])
    company_offers = [offer for offer in get_offers(get_all_companies()) if offer.get("company_id") == company_id]
    user_email = user["email"] if user else ""
    return jsonify(
        company={"id": company["id"], "name": company["name"], "email": company["email"]},
        user_email=user_email,
        current_cv=(
            {"filename": cv["original_filename"], "size": cv["file_size"]}
            if cv else None
        ),
        offers=[{"id": offer["id"], "title": offer["title"]} for offer in company_offers],
        cv_sources={"manual": bool(builder["profiles"].get("manual")), "uploaded": cv is not None, "optimized": bool(builder.get("optimized"))},
        message=(
            f"Bonjour,\n\nJe vous adresse ma candidature spontanée afin de rejoindre "
            f"{company['name']}. Vous trouverez mon CV en pièce jointe.\n\n"
            f"Je reste à votre disposition pour tout échange complémentaire.\n\n"
            f"Cordialement,\n{user['full_name'] if user else user_email}"
        ),
        smtp_ready=smtp_configured(),
    )


@app.route("/api/apply/generate-message", methods=["POST"])
@login_required
def generate_apply_message():
    payload = request.get_json(silent=True) or {}
    try:
        company_id = int(payload.get("company_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Choose a valid company."), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Company not found."), 404
    ai_choice = _feature_ai_choice("generation")
    if not ai_choice:
        return jsonify(
            error="AI is not ready. Choose Gemini, Groq, or NVIDIA in Settings and configure its API key.",
            settings_url=url_for("settings"),
        ), 503
    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    profile = get_candidate_match_profile(user_id)
    profile["full_name"] = profile.get("full_name") or (user["full_name"] if user else "")
    cv = get_cv_for_user(user_id)
    if cv is not None and cv["extracted_text"]:
        profile["cv_text"] = cv["extracted_text"]
    language = str(payload.get("language") or (user["preferred_language"] if user else "fr")).lower()
    if language not in {"ar", "en", "fr"}:
        language = "fr"
    try:
        messages = generate_application_messages(profile, company, ai_choice, language)
    except (AIServiceError, ValueError) as exc:
        return jsonify(error=str(exc)), getattr(exc, "status_code", 400)
    return jsonify(
        message=messages[0],
        messages=messages,
        provider=ai_choice["provider"],
        model=ai_choice["model"],
    )


@app.route("/api/whatsapp/generate-message", methods=["POST"])
@login_required
def generate_whatsapp_message():
    payload = request.get_json(silent=True) or {}
    try:
        company_id = int(payload.get("company_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Choose a valid company."), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Company not found."), 404
    if not str(company.get("phone") or "").strip():
        return jsonify(error="This company does not have a WhatsApp phone number."), 422
    ai_choice = _feature_ai_choice("generation")
    if not ai_choice:
        return jsonify(
            error="AI is not ready. Choose Gemini, Groq, or NVIDIA in Settings and configure its API key.",
            settings_url=url_for("settings"),
        ), 503
    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    profile = get_candidate_match_profile(user_id)
    profile["full_name"] = profile.get("full_name") or (user["full_name"] if user else "")
    language = str(payload.get("language") or (user["preferred_language"] if user else "fr")).lower()
    if language not in {"ar", "en", "fr"}:
        language = "fr"
    try:
        messages = generate_whatsapp_messages(profile, company, ai_choice, language)
    except (AIServiceError, ValueError) as exc:
        return jsonify(error=str(exc)), getattr(exc, "status_code", 400)
    return jsonify(
        messages=messages, company_name=company["name"], phone=company["phone"],
        provider=ai_choice["provider"], model=ai_choice["model"],
    )


@app.route("/api/apply", methods=["POST"])
@login_required
def apply_to_company():
    user_id = session["user_id"]
    try:
        company_id = int(request.form.get("company_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Entreprise invalide."), 400

    company = get_company(company_id)
    recipient = str(company.get("email") if company else "").strip()
    uploaded = request.files.get("cv_file")
    uploaded_name = secure_filename(uploaded.filename) if uploaded and uploaded.filename else ""

    def fail(message, status_code):
        log_application_email_attempt(
            user_id, company_id, recipient, uploaded_name, "failed", message
        )
        return jsonify(error=message), status_code

    if company is None:
        return fail("Entreprise introuvable.", 404)
    if not _valid_email(recipient):
        return fail("Cette entreprise ne possède pas d’adresse e-mail valide.", 422)
    message = str(request.form.get("message", "")).strip()
    cover_letter = str(request.form.get("cover_letter", "")).strip()
    include_cover_letter = request.form.get("include_cover_letter") == "1"
    if not message:
        return fail("Le message ne peut pas être vide.", 400)
    if len(message) > 10000:
        return fail("Le message ne peut pas dépasser 10 000 caractères.", 400)
    if include_cover_letter and not cover_letter:
        return fail("Generate or add the cover letter before sending.", 400)
    if len(cover_letter) > 15000:
        return fail("The cover letter cannot exceed 15,000 characters.", 400)
    if count_recent_application_attempts(user_id) >= 15:
        return fail("Limite atteinte : 15 candidatures maximum par heure.", 429)

    cv = get_cv_for_user(user_id)
    old_cv = cv
    if uploaded_name:
        if not allowed_cv_file(uploaded_name):
            return fail("Le CV doit être au format PDF, DOC ou DOCX.", 400)
        extension = uploaded_name.rsplit(".", 1)[1].lower()
        data = uploaded.read(MAX_CV_FILE_SIZE + 1)
        if len(data) > MAX_CV_FILE_SIZE:
            return fail("Le CV doit avoir une taille maximale de 5 Mo.", 413)
        stored_filename = f"user{user_id}_{uuid.uuid4().hex}.{extension}"
        mime_type = mimetypes.guess_type(uploaded_name)[0] or "application/octet-stream"
        extracted_text = ""
        extraction_status = "not_supported" if extension == "doc" else "pending"
        page_count = None
        if extension in {"pdf", "docx"}:
            try:
                extracted = extract_cv(data, extension)
            except CVExtractionError as exc:
                return fail(str(exc), 400)
            mime_type = extracted.mime_type
            extracted_text = extracted.text
            extraction_status = extracted.extraction_status
            page_count = extracted.page_count
        new_path = cv_storage_path(stored_filename)
        try:
            new_path.write_bytes(data)
            save_cv(
                user_id, uploaded_name, stored_filename, extension, mime_type,
                len(data), "", extracted_text, extraction_status, page_count,
            )
            cv = get_cv_for_user(user_id)
        except Exception:
            new_path.unlink(missing_ok=True)
            app.logger.exception("Apply CV storage failed")
            return fail("Le CV n’a pas pu être enregistré.", 503)
        if old_cv is not None and old_cv["stored_filename"] != stored_filename:
            try:
                cv_storage_path(old_cv["stored_filename"]).unlink(missing_ok=True)
            except ValueError:
                app.logger.warning("Ignored an invalid legacy CV storage path")

    if cv is None:
        return fail("Aucun CV disponible. Ajoutez un CV avant d’envoyer votre candidature.", 400)
    try:
        cv_path = cv_storage_path(cv["stored_filename"])
    except ValueError:
        return fail("Le CV enregistré est invalide. Veuillez le téléverser à nouveau.", 400)
    if not cv_path.is_file():
        return fail("Le fichier du CV est introuvable. Veuillez le téléverser à nouveau.", 400)

    user = get_user_by_id(user_id)
    user_email = str(user["email"] if user else "").strip()
    if not _valid_email(user_email):
        return fail("Votre compte ne possède pas d’adresse e-mail valide.", 400)
    offer_id = request.form.get("offer_id")
    selected_offer = next((offer for offer in get_offers(get_all_companies()) if str(offer["id"]) == str(offer_id) and offer.get("company_id") == company_id), None) if offer_id else None
    position = selected_offer["title"] if selected_offer else "Candidature spontanée"
    subject = f"Candidature — {position} — {user_email}" if selected_offer else f"Candidature spontanée — {user_email}"
    try:
        message_id = send_application_email(
            recipient=recipient,
            reply_to=user_email,
            copy_to=user_email,
            subject=subject,
            body=message,
            cv_path=cv_path,
            cv_filename=cv["original_filename"],
            cv_mime_type=cv["mime_type"],
            cover_letter_text=cover_letter if include_cover_letter else "",
        )
    except (SMTPConfigurationError, smtplib.SMTPException, OSError) as exc:
        readable_error = _safe_smtp_error(exc)
        app.logger.warning("SMTP application delivery failed: %s", readable_error)
        return fail(f"Échec de l’envoi : {readable_error}", 502)

    application = create_application(
        user_id, company_id, position, recipient,
        "Sent", datetime.now().date().isoformat(), message,
    )
    update_application(user_id, application["id"], {
        "cover_letter_used": cover_letter if include_cover_letter else "",
        "cv_used": cv["original_filename"],
    })
    log_application_email_attempt(
        user_id, company_id, recipient, cv["original_filename"], "sent",
        application_id=application["id"],
    )
    return jsonify(
        success=True,
        message="Votre candidature a été envoyée. Une copie privée a été envoyée à votre adresse Gmail.",
        application_id=application["id"],
        application_status="Sent",
        smtp_message_id=message_id,
    )


@app.route("/api/applications/<int:application_id>", methods=["PUT", "PATCH", "DELETE"])
@login_required
def application_item(application_id):
    if request.method == "DELETE":
        try:
            if not delete_tracked_application(application_id, session["user_id"]):
                return jsonify(error="Application not found."), 404
            return jsonify(success=True)
        except Exception:
            app.logger.exception("SQLite application delete failed")
            return jsonify(error="Could not delete the application."), 503

    payload = request.get_json(silent=True) or {}
    fields = {}
    if "company_id" in payload or "company" in payload:
        try:
            fields["company_id"] = int(payload.get("company_id", payload.get("company")))
        except (TypeError, ValueError): return jsonify(error="company_id must be an integer"), 400
    if "job_id" in payload or "offer_id" in payload or "job" in payload:
        try:
            fields["job_id"] = int(payload.get("job_id", payload.get("offer_id", payload.get("job"))))
        except (TypeError, ValueError): return jsonify(error="job_id must be an integer"), 400
    if "status" in payload:
        fields["status"] = str(payload["status"]).strip()
        if fields["status"] not in APPLICATION_STATUSES:
            return jsonify(error="Choose a valid application status."), 400
    date_value = payload.get("date", payload.get("applied_at"))
    if date_value is not None:
        date_value = str(date_value).strip()
        try: datetime.fromisoformat(date_value.replace("Z", "+00:00"))
        except ValueError: return jsonify(error="date must be a valid ISO-8601 date/time"), 400
        fields["applied_at"] = date_value
    notes = None
    if "notes" in payload:
        notes = str(payload["notes"]).strip()
        if len(notes) > 5000: return jsonify(error="notes must be 5000 characters or fewer"), 400
    if not fields and notes is None:
        return jsonify(error="No supported fields were provided."), 400
    if "company_id" in fields and get_company(fields["company_id"]) is None:
        return jsonify(error="Company not found."), 400
    if "job_id" in fields:
        offer = get_job_offer_for_application(fields["job_id"])
        if offer is None: return jsonify(error="Job offer not found."), 400
        selected_company = fields.get("company_id")
        if selected_company is not None and offer.get("company_id") is not None and offer["company_id"] != selected_company:
            return jsonify(error="The job offer does not belong to the selected company."), 400
    try:
        application = update_tracked_application(
            application_id, session["user_id"], fields, notes
        )
        if application is None: return jsonify(error="Application not found."), 404
        return jsonify(application)
    except Exception:
        app.logger.exception("SQLite application update failed")
        return jsonify(error="Could not update the application."), 503


def _crm_payload(payload, require_company=False):
    if not isinstance(payload, dict):
        return None, "A JSON request body is required."
    values = {}
    if require_company or "company_id" in payload:
        try:
            company_id = int(payload.get("company_id", ""))
        except (TypeError, ValueError):
            return None, "company_id must be an integer"
        if get_company(company_id) is None:
            return None, "Company not found."
        values["company_id"] = company_id
    if "contact_email" in payload or "email" in payload:
        email = str(payload.get("contact_email", payload.get("email", ""))).strip()
        if len(email) > 254 or (email and "@" not in email):
            return None, "contact_email must be a valid email address"
        values["contact_email"] = email or None
    if require_company or "status" in payload:
        status = str(payload.get("status", "Draft")).strip()
        if status not in APPLICATION_STATUSES:
            return None, "Choose a valid application status."
        values["status"] = status
    for field in ("last_contact_date", "next_followup_date"):
        if field in payload:
            value = str(payload.get(field) or "").strip()
            if value:
                try:
                    date.fromisoformat(value)
                except ValueError:
                    return None, f"{field} must be a valid ISO date"
            values[field] = value or None
    if "notes" in payload:
        notes = str(payload.get("notes") or "").strip()
        if len(notes) > 5000:
            return None, "notes must be 5000 characters or fewer"
        values["notes"] = notes
    return values, None


@app.route("/api/crm", methods=["GET", "POST"])
@login_required
def crm_collection():
    if request.method == "GET":
        try:
            return jsonify(fetch_crm_for_api(session["user_id"]))
        except Exception:
            app.logger.exception("SQLite CRM query failed")
            return jsonify(error="CRM data is temporarily unavailable."), 503
    values, error = _crm_payload(request.get_json(silent=True), require_company=True)
    if error:
        return jsonify(error=error), 400
    values["user_id"] = session["user_id"]
    try:
        return jsonify(create_crm_record(values)), 201
    except Exception:
        app.logger.exception("SQLite CRM create failed")
        return jsonify(error="Could not create the CRM record."), 503


@app.route("/api/crm/<int:record_id>", methods=["PUT", "DELETE"])
@login_required
def crm_item(record_id):
    if request.method == "DELETE":
        try:
            if not delete_crm_record(record_id, session["user_id"]):
                return jsonify(error="CRM record not found."), 404
            return jsonify(success=True)
        except Exception:
            app.logger.exception("SQLite CRM delete failed")
            return jsonify(error="Could not delete the CRM record."), 503
    values, error = _crm_payload(request.get_json(silent=True))
    if error:
        return jsonify(error=error), 400
    if not values:
        return jsonify(error="No supported fields were provided."), 400
    values["updated_at"] = datetime.now().astimezone().isoformat()
    try:
        record = update_crm_record(record_id, session["user_id"], values)
        if record is None:
            return jsonify(error="CRM record not found."), 404
        return jsonify(record)
    except Exception:
        app.logger.exception("SQLite CRM update failed")
        return jsonify(error="Could not update the CRM record."), 503


@app.route("/api/reminders", methods=["POST"])
@login_required
def reminder_create():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict): return jsonify(error="Choose a valid application and date."), 400
    try: application_id = int(payload.get("application_id")); date.fromisoformat(str(payload.get("due_date", "")))
    except (TypeError, ValueError): return jsonify(error="Choose a valid application and date."), 400
    reminder_id = create_reminder(session["user_id"], application_id, payload["due_date"])
    if not reminder_id: return jsonify(error="Application not found."), 404
    return jsonify(id=reminder_id, success=True), 201


@app.route("/api/reminders/<int:reminder_id>", methods=["PATCH", "DELETE"])
@login_required
def reminder_update(reminder_id):
    update_reminder(session["user_id"], reminder_id, "delete" if request.method == "DELETE" else "complete")
    return jsonify(success=True)


@app.route("/api/opportunities/status")
@login_required
def opportunities_status():
    from backend.radar_watch import watch_status
    state, _ = watch_status()
    return jsonify(completed=state.get('last_finished'))


@app.route("/api/notifications", methods=["GET"])
@login_required
def notifications_list():
    items = [dict(item) for item in get_notifications(session["user_id"])]
    response=jsonify(items=items, unread=sum(not item["is_read"] for item in items))
    response.headers['Cache-Control']='private, no-store'
    return response


@app.route("/api/notifications/<action>", methods=["POST"])
@login_required
def notifications_update(action):
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict): return jsonify(error="Invalid notification request."), 400
    if action not in {"read", "read_all", "clear"}: return jsonify(error="Invalid action."), 400
    notification_action(session["user_id"], payload.get("id"), action)
    return jsonify(success=True)


@app.route("/api/auto-apply", methods=["POST"])
@login_required
def auto_apply():
    payload = request.get_json(silent=True) or {}; user_id = session["user_id"]
    try: company_id = int(payload.get("company_id"))
    except (TypeError, ValueError): return jsonify(error="Choose a company."), 400
    company = get_company(company_id); position = str(payload.get("position", "")).strip()
    if not company or not position: return jsonify(error="Choose a company and position."), 400
    existing = find_application(user_id, company_id, position)
    values = {"status": "Draft", "contact_email": str(payload.get("contact", company.get("email", ""))),
              "cv_used": str(payload.get("cv", "")), "cover_letter_used": str(payload.get("cover_letter", ""))}
    if existing:
        application = update_application(user_id, existing["id"], values)
        message = "Existing application updated; no duplicate was created."
    else:
        application = create_application(user_id, company_id, position, values["contact_email"], "Draft", "", "")
        application = update_application(user_id, application["id"], values); message = "Application saved."
    add_history(user_id, application["id"], "Application drafted", f"Draft created for {company['name']} — {position}")
    create_notification(user_id, "ai", "Auto-application completed", message, url_for("applications"))
    return jsonify(success=True, message=message, application=serialize_application(application))


@app.route("/api/search")
@login_required
def global_search():
    query = request.args.get("q", "").strip()[:100].casefold()
    if len(query) < 2:
        return jsonify(results=[])

    companies = get_all_companies()
    companies_by_id = {company["id"]: company for company in companies}
    results = []

    def add_result(name, result_type, location, status, target, searchable):
        if any(query in str(value or "").casefold() for value in searchable):
            results.append({
                "name": name,
                "type": result_type,
                "location": location or "",
                "status": status or "",
                "url": target,
                "rank": 0 if str(name).casefold().startswith(query) else 1,
            })

    for company in companies:
        add_result(
            company["name"], "Company", company.get("area"), company.get("status"),
            url_for("company_detail", company_id=company["id"]),
            (company.get(field) for field in (
                "name", "category", "area", "address", "description", "status",
                "email", "phone", "website",
            )),
        )

    for offer in get_offers(companies):
        company = companies_by_id.get(offer["company_id"], {})
        offer_target = (
            url_for("company_detail", company_id=offer["company_id"])
            if offer.get("company_id") is not None
            else offer.get("url") or url_for("companies")
        )
        add_result(
            offer["title"], "Job offer", company.get("area"), "Open offer",
            offer_target,
            (value for value in (
                offer.get("title"), offer.get("company_name"), offer.get("category"),
                offer.get("description"), *offer.get("requirements", []),
            )),
        )

    for application in get_applications_for_user(session["user_id"]):
        company = companies_by_id.get(application["company_id"], {})
        add_result(
            application["position"], "Application", company.get("area"), application["status"],
            url_for("applications"),
            (value for value in (
                application["position"], company.get("name"), company.get("area"),
                application["status"], application["contact_email"], application["notes"],
            )),
        )

        contact_email = application["contact_email"]
        if contact_email:
            add_result(
                contact_email, "Contact", company.get("area"), application["status"],
                url_for("applications"),
                (contact_email, company.get("name"), company.get("area")),
            )

    for company in companies:
        for contact in (company.get("email"), company.get("phone")):
            if contact:
                add_result(
                    contact, "Contact", company.get("area"), company.get("status"),
                    url_for("company_detail", company_id=company["id"]),
                    (contact, company.get("name"), company.get("area"), company.get("status")),
                )

    from backend.portfolio_service import get_projects
    for project in get_projects(session["user_id"]):
        add_result(project["title"], "Proof project", "", "Completed" if project["completed"] else "In progress",
            url_for("portfolio_project", project_id=project["id"]), (project["title"], project["skill"]))

    results.sort(key=lambda result: (result["rank"], result["name"].casefold()))
    for result in results:
        result.pop("rank")
    return jsonify(results=results[:12])


@app.route("/ai-studio")
@login_required
def ai_studio():
    tab=request.args.get('tab','match')
    if tab=='skills':
        return skill_gap.__wrapped__()
    if tab not in {'match','optimize','recommendations','cover'}:tab='match'
    uid=session['user_id']
    companies=get_all_companies()
    offers=get_offers(companies)
    from backend.company_catalog import enrich_catalog
    companies=enrich_catalog(companies,offers)
    return render_template('ai_studio.html',active_page='ai_studio',page_title='AI Career Studio',studio_tab=tab,
        companies=companies,studio_categories=sorted({'Génie civil','Construction / BTP'}|{domain for company in companies for domain in company.get('domains',[company.get('category') or 'Other'])},key=str.casefold),offers=offers,has_uploaded_cv=get_cv_for_user(uid) is not None)


@app.route('/api/ai-studio/run',methods=['POST'])
@login_required
def ai_studio_run():
    from backend.studio_service import run_studio
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Invalid analysis request.'),400
    try:
        return jsonify(run_studio(session['user_id'],payload,_feature_ai_choice))
    except (ValueError,LookupError,AIServiceError) as error:
        return jsonify(error=str(error)),getattr(error,'status_code',400)


@app.route("/api/career-dna", methods=["GET", "POST"])
@login_required
def career_dna_api():
    if request.method == "GET":
        return jsonify(get_career_dna(session["user_id"]))
    try:
        return jsonify(save_career_dna(session["user_id"], request.get_json(silent=True)))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400


@app.route("/api/skill-gap/progress", methods=["POST"])
@login_required
def skill_gap_progress():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Provide a learning progress update."), 400
    try:
        save_learning_progress(session["user_id"], payload.get("skill"), payload.get("action_index"), payload.get("status"), payload.get("notes", ""))
    except ValueError as exc:
        return jsonify(error=str(exc)), 400
    return jsonify(message="Learning progress saved. This does not certify a skill or change candidate profile.")


@app.route('/skill-practice', methods=['GET','POST'])
@app.route('/interview-helper/skills', methods=['GET','POST'])
@login_required
def skill_practice():
    from backend.skill_practice_service import EXERCISES, submit_practice, attempts, attempt
    skill=request.values.get('skill','SQL')
    if skill not in EXERCISES:
        flash('Choose one of the available practice exercises.','error')
        return redirect(url_for('skill_practice'))
    if request.method=='POST':
        answers=[]
        for index in range(len(EXERCISES[skill][1])):
            values=request.form.getlist('answer_'+str(index))
            allowed={str(i) for i in range(len(EXERCISES[skill][1][index][1]))}
            answers.append(int(values[0]) if len(values)==1 and values[0] in allowed else None)
        try:
            aid=submit_practice(session['user_id'],skill,answers)
        except ValueError as error:
            flash(str(error),'error')
            return redirect(url_for('skill_practice',skill=skill))
        return redirect(url_for('skill_practice',skill=skill,attempt_id=aid))
    result=None
    aid=request.args.get('attempt_id',type=int)
    if aid is not None:
        result=attempt(session['user_id'],aid)
        if result is None:return ('Practice result unavailable.',404)
        skill=result['skill']
    return render_template('skill_practice.html',active_page='interview_helper',page_title='AI Interview Simulator',
        catalog=EXERCISES,skill=skill,exercise=EXERCISES[skill],result=result,history=attempts(session['user_id']))


@app.route("/skill-gap")
@login_required
def skill_gap():
    if request.endpoint=='skill_gap':
        args=request.args.to_dict();args['tab']='skills'
        return redirect(url_for('ai_studio',**args))
    user_id = session["user_id"]
    builder = get_cv_builder_data(user_id)
    uploaded_cv = get_cv_for_user(user_id)
    source = request.args.get("cv_source", "dna")
    if source not in {"manual", "uploaded", "dna"} or (source == "uploaded" and uploaded_cv is None):
        source = "manual"
    field = request.args.get("field", "any")
    allowed_fields = {"any", "software", "ai_data", "cybersecurity", "cloud", "civil_engineering", "construction"}
    if field not in allowed_fields:
        field = "any"
    profile = get_candidate_match_profile(user_id) if source == "dna" else dict(builder["profiles"].get(source) or {})
    if source == "uploaded" and uploaded_cv and uploaded_cv["extracted_text"]:
        profile["cv_text"] = uploaded_cv["extracted_text"]
    companies = get_all_companies()
    offers = get_offers(companies)
    selected_offer_id = request.args.get("offer_id", type=int)
    target_offer = next((offer for offer in offers if offer["id"] == selected_offer_id), None)
    if selected_offer_id is not None and target_offer is None:
        flash("This offer is unavailable. Showing the selected market instead.", "error")
    analysis = analyze_market_skill_gap(profile, offers, companies, field, get_interview_weak_skills(user_id, position=target_offer["title"] if target_offer else None), target_offer=target_offer)
    attach_learning_progress(analysis, user_id)
    ai_advice = ""
    ai_choice = _feature_ai_choice("generation")
    if analysis["has_cv_evidence"] and ai_choice:
        try:
            ai_advice = generate_skill_gap_advice(analysis, profile, ai_choice)
        except AIServiceError:
            app.logger.warning("AI roadmap unavailable; using the evidence-based roadmap fallback.")
    return render_template(
        "studio_skills.html",
        active_page="ai_studio",page_title="AI Career Studio",studio_tab="skills",
        offers=offers, selected_offer=target_offer,
        analysis=analysis,
        cv_source=source,
        field=field,
        has_uploaded_cv=uploaded_cv is not None,
        has_created_cv=bool(builder["profiles"].get("manual")),
        uploaded_cv_name=uploaded_cv["original_filename"] if uploaded_cv else "",
        created_cv_name=(builder["profiles"].get("manual") or {}).get("full_name") or "Saved CV",
        ai_advice=ai_advice,
        ai_enabled=bool(ai_choice),
    )


def _interview_application_context(application_id):
    application = get_application_for_user(session["user_id"], application_id)
    if application is None or normalize_application_status(application["status"]) != "Interview":
        return None
    application = dict(application)
    company = get_company(application["company_id"])
    if company is None:
        return None
    offers = get_offers(get_all_companies())
    offer = next((item for item in offers if item.get("id") == application.get("job_id")), None)
    if offer is None:
        offer = next((item for item in offers if item.get("company_id") == company["id"] and str(item.get("title") or "").casefold() == str(application["position"]).casefold()), None)
    profile = get_candidate_match_profile(session["user_id"])
    return application, company, offer, profile


@app.route("/interview-helper")
@login_required
def interview_helper():
    all_companies = get_all_companies()
    companies = {item["id"]: item for item in all_companies}
    offers = get_offers(all_companies)
    interviews = []
    for row in get_interview_schedules(session["user_id"]):
        item = dict(row)
        item["company"] = (item.get("practice_context") or {}).get("custom_company") or companies.get(item["company_id"], {})
        item["offer"] = next((offer for offer in offers if offer["id"] == item.get("offer_id")), None)
        interviews.append(item)
    history = get_interview_sessions(session["user_id"])
    for item in history:
        item["company"] = (item.get("practice_context") or {}).get("custom_company") or companies.get(item["company_id"], {})
    today = date.today()
    return render_template("interview_helper.html", page_title="AI Interview Simulator", active_page="interview_helper", interviews=interviews, history=history,
                           companies=all_companies, offers=offers, progress=interview_progress(history), today=today.isoformat(), max_date=(today + timedelta(days=365)).isoformat())


@app.route("/api/interview-helper/schedule", methods=["POST"])
@login_required
def interview_helper_schedule():
    payload = request.get_json(silent=True) or {}
    try:
        company_id = int(payload.get("company_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Choose a company."), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Company not found."), 404
    try:
        interview_date = date.fromisoformat(str(payload.get("interview_date") or ""))
    except ValueError:
        return jsonify(error="Choose a valid interview date."), 400
    if interview_date < date.today() or interview_date > date.today() + timedelta(days=365):
        return jsonify(error="Interview date must be within the next 365 days."), 400
    offer_id = None
    offer = None
    if payload.get("offer_id") not in (None, ""):
        try: offer_id = int(payload["offer_id"])
        except (TypeError, ValueError): return jsonify(error="Choose a valid offer."), 400
        offer = next((item for item in get_offers(get_all_companies()) if item["id"] == offer_id and item.get("company_id") == company_id), None)
        if offer is None: return jsonify(error="Choose an offer from the selected company."), 400
    position = str(payload.get("position") or (offer or {}).get("title") or "Interview").strip()[:180]
    existing = next((row for row in get_applications_for_user(session["user_id"]) if row["company_id"] == company_id and str(row["position"]).casefold() == position.casefold()), None)
    application = existing or create_application(session["user_id"], company_id, position, company.get("email") or "", "Interview", "", "Scheduled from Interview Helper")
    if existing and existing["status"] != "Interview":
        update_application(session["user_id"], existing["id"], {"status": "Interview"})
    schedule_id = create_interview_schedule(session["user_id"], application["id"], company_id, offer_id, position, interview_date.isoformat(), str(payload.get("notes") or "")[:1000])
    return jsonify(id=schedule_id, message="Interview added to your calendar."), 201


@app.route("/api/interview-helper/schedule/<int:schedule_id>", methods=["DELETE"])
@login_required
def interview_helper_schedule_delete(schedule_id):
    if not delete_interview_schedule(session["user_id"], schedule_id):
        return jsonify(error="Interview schedule not found."), 404
    return jsonify(message="Interview removed from calendar.")


@app.route("/api/interview-helper/start", methods=["POST"])
@login_required
def interview_helper_start():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Provide a practice request."), 400
    mode = payload.get("mode", "standard")
    if not isinstance(mode, str) or mode not in {"standard", "beginner"}:
        return jsonify(error="Choose standard or beginner mode."), 400
    previous = None
    if payload.get("retry_session_id"):
        try:
            previous = get_interview_session(session["user_id"], int(payload["retry_session_id"]))
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid practice session."), 400
        if previous is None or not previous.get("completed_at"):
            return jsonify(error="Completed practice not found."), 404
        company = (previous.get("practice_context") or {}).get("custom_company") or get_company(previous["company_id"])
        if not company:
            return jsonify(error="Company not found."), 404
        application = {"id": previous["application_id"], "position": previous["position"]}
        offer = None
        profile = get_candidate_match_profile(session["user_id"])
        mode = (previous.get("practice_context") or {}).get("mode", "standard")
    elif payload.get("custom_job") is not None:
        custom = payload["custom_job"]
        if not isinstance(custom, dict):
            return jsonify(error="Provide your job details."), 400
        limits = {"title": 160, "company": 160, "description": 6000, "skills": 1000}
        if any(not isinstance(custom.get(key, ""), str) or len(custom.get(key, "")) > limit for key, limit in limits.items()):
            return jsonify(error="Job details are too long or invalid."), 400
        title = custom.get("title", "").strip()
        if not title:
            return jsonify(error="Enter the job title you want to practice for."), 400
        # External practice has no catalogue company; retain its label in session context.
        company = {"id": 0, "name": custom.get("company", "").strip() or "My target company", "description": ""}
        offer = {"title": title, "description": custom.get("description", "").strip(), "requirements": [part.strip() for part in custom.get("skills", "").replace(";", ",").split(",") if part.strip()]}
        profile = get_candidate_match_profile(session["user_id"])
        application = {"id": None, "position": title}
    elif payload.get("offer_id"):
        try:
            offer_id = int(payload["offer_id"])
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid offer."), 400
        offer = next((item for item in get_offers(get_all_companies()) if item["id"] == offer_id), None)
        company = get_company(offer["company_id"]) if offer else None
        if not company:
            return jsonify(error="Offer not found."), 404
        profile = get_candidate_match_profile(session["user_id"])
        application = {"id": None, "position": offer["title"]}
    else:
        try:
            schedule_id = int(payload.get("schedule_id", ""))
        except (TypeError, ValueError):
            return jsonify(error="Choose an offer or a scheduled interview."), 400
        schedule = get_interview_schedule(session["user_id"], schedule_id)
        context = _interview_application_context(schedule["application_id"]) if schedule and schedule.get("application_id") else None
        if context is None:
            return jsonify(error="Scheduled interview not found."), 404
        application, company, offer, profile = context
    interview_ai = _feature_ai_choice("interview")
    generation = {"questions": previous["questions"], "source": (previous.get("practice_context") or {}).get("question_source", "local")} if previous else generate_interview_questions(profile, company, offer, application["position"], interview_ai, include_metadata=True)
    questions = [{**question, "guide": question_guide(question)} for question in generation["questions"]]
    context = {"mode": mode, "offer_id": (offer or {}).get("id") or ((previous or {}).get("practice_context") or {}).get("offer_id"), "question_source": generation["source"]}
    if company["id"] == 0:
        context["custom_company"] = company
        context["custom_offer"] = offer or (previous.get("practice_context") or {}).get("custom_offer", {})
    session_id = create_interview_session(session["user_id"], application["id"], company["id"], application["position"], questions, practice_context=context)
    return jsonify(session_id=session_id, offer_id=context.get("offer_id"), mode=mode, questions=questions, company=company["name"], position=application["position"], provider="NVIDIA NIM / Kimi" if generation["source"] == "nvidia" else "Local practice questions")


@app.route("/api/interview-helper/<int:session_id>/complete", methods=["POST"])
@login_required
def interview_helper_complete(session_id):
    mock = get_interview_session(session["user_id"], session_id)
    if mock is None:
        return jsonify(error="Mock interview not found."), 404
    if mock.get("completed_at"):
        return jsonify(error="This practice is already completed. Use Repeat same questions to create a new attempt."), 409
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload, dict):
        return jsonify(error="Provide an answer list."), 400
    answers = payload.get("answers")
    if not isinstance(answers, list):
        return jsonify(error="Answer list is required."), 400
    if len(answers) != len(mock["questions"]) or any(not isinstance(answer, str) or len(answer) > 4000 for answer in answers):
        return jsonify(error="Provide one text answer per question, up to 4000 characters each."), 400
    answers = [answer.strip() for answer in answers]
    evaluation = evaluate_interview_answers(mock["questions"], answers, _feature_ai_choice("interview"))
    saved = complete_interview_session(session["user_id"], session_id, evaluation["results"], evaluation["score"], evaluation["weak_skills"], evaluation["feedback"], evaluation={key: value for key, value in evaluation.items() if key != "results"})
    if not saved:
        return jsonify(error="This practice was already completed. Start another attempt."), 409
    return jsonify(evaluation=evaluation, session_id=session_id, progress=interview_progress(get_interview_sessions(session["user_id"])), skill_gap_url=url_for("skill_gap"))


def _requested_ai_context():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify(error="A JSON request body is required."), 400)
    try:
        job_id = int(payload.get("job_id", payload.get("offer_id", "")))
    except (TypeError, ValueError):
        return None, (jsonify(error="job_id must be an integer"), 400)
    try:
        context = fetch_ai_context(job_id, session["user_id"])
        return context, None
    except LookupError as exc:
        return None, (jsonify(error=str(exc)), 404)
    except ValueError as exc:
        return None, (jsonify(error=str(exc)), 400)
    except Exception:
        app.logger.exception("SQLite AI context query failed")
        return None, (jsonify(error="AI data is temporarily unavailable."), 503)


def _requested_matching_context():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return None, (jsonify(error="A JSON request body is required."), 400)
    if payload.get("job_id") not in (None, "") or payload.get("offer_id") not in (None, ""):
        return _requested_ai_context()
    try:
        company_id = int(payload.get("company_id", ""))
    except (TypeError, ValueError):
        return None, (jsonify(error="Choose a company or job offer."), 400)
    company = get_company(company_id)
    if company is None:
        return None, (jsonify(error="Company not found."), 404)
    profile = get_candidate_match_profile(session["user_id"])
    return {"profile": profile, "company": company, "offer": None}, None


def _ai_error_response(error):
    app.logger.warning("AI feature unavailable: %s", error.feature or "unknown")
    return jsonify(error.to_dict()), error.status_code


def _user_ai_choice():
    preferences = get_user_settings(session["user_id"])
    if not preferences.get("ai_suggestions") or preferences.get("ai_provider") == "none":
        return None
    status = get_ai_status(preferences.get("ai_provider"), preferences.get("ai_model"))
    if not status["configured"]:
        return None
    return {"provider": status["provider"], "model": status["model"]}


def _feature_ai_choice(feature):
    """Use the requested provider for each product feature, with no silent cross-provider calls."""
    routes = {
        "interview": ("nvidia", os.getenv("NVIDIA_INTERVIEW_MODEL", "moonshotai/kimi-k3")),
        "matching": ("grok", os.getenv("XAI_MATCHING_MODEL", "grok-4.7")),
        "generation": ("gemini", os.getenv("GEMINI_GENERATION_MODEL", "gemini-3.5-flash-lite")),
    }
    provider, model = routes.get(feature, (None, None))
    status = get_ai_status(provider, model) if provider else {"configured": False}
    user=get_user_by_id(session["user_id"]) if session.get("user_id") else None
    language=user["preferred_language"] if user else request.cookies.get("ui_language","en")
    return {"provider": provider, "model": model, "language": language} if status["configured"] else None


@app.route("/api/ai/match", methods=["POST"])
@login_required
def ai_match_api():
    context, error = _requested_matching_context()
    if error: return error
    try:
        return jsonify(match=match_cv_to_job(
            context["profile"], context["offer"], context["company"],
            ai_choice=_feature_ai_choice("matching"),
        ))
    except AIServiceError as exc:
        return _ai_error_response(exc)


@app.route("/api/ai/cover-letter", methods=["POST"])
@login_required
def ai_cover_letter_api():
    context, error = _requested_ai_context()
    if error: return error
    try:
        return jsonify(cover_letter=generate_ai_cover_letter(
            context["profile"], context["offer"], context["company"],
            ai_choice=_feature_ai_choice("generation"),
        ))
    except AIServiceError as exc:
        return _ai_error_response(exc)


@app.route("/api/ai/optimize-cv", methods=["POST"])
@login_required
def ai_optimize_cv_api():
    context, error = _requested_matching_context()
    if error: return error
    try:
        optimization = optimize_cv_for_job(
            context["profile"], context["offer"], context["company"],
            ai_choice=_feature_ai_choice("matching"),
        )
        payload = request.get_json(silent=True) or {}
        source = payload.get("source")
        if source not in {"manual", "uploaded"}:
            source = "uploaded" if get_cv_for_user(session["user_id"]) else "manual"
        optimization["version_id"] = save_optimized_cv(session["user_id"], source, optimization)
        return jsonify(optimization=optimization)
    except AIServiceError as exc:
        return _ai_error_response(exc)


@app.route("/api/ai/skill-gap", methods=["POST"])
@login_required
def ai_skill_gap_api():
    context, error = _requested_ai_context()
    if error: return error
    try:
        return jsonify(skill_gap=analyze_skill_gap(
            context["profile"], context["offer"]
        ))
    except AIServiceError as exc:
        return _ai_error_response(exc)


@app.route("/api/cover-letter/generate", methods=["POST"])
@login_required
def cover_letter_generate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Invalid cover letter request."), 400

    try:
        company_id = int(payload.get("company_id", ""))
    except (TypeError, ValueError):
        return jsonify(error="Choose a company."), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="That company could not be found."), 400

    raw_offer_id = payload.get("offer_id")
    offer = None
    if raw_offer_id not in (None, ""):
        try:
            offer_id = int(raw_offer_id)
        except (TypeError, ValueError):
            return jsonify(error="Choose a valid offer for the selected company."), 400
        offer = next(
            (item for item in get_offers(get_all_companies())
             if item["id"] == offer_id and item["company_id"] == company_id),
            None,
        )
        if offer is None:
            return jsonify(error="Choose a valid offer for the selected company."), 400

    position = str(payload.get("position", "")).strip()
    if not position or len(position) > 180:
        return jsonify(error="Enter a position (up to 180 characters)."), 400
    source = payload.get("cv_source")
    if source not in {"manual", "uploaded", "dna"}:
        return jsonify(error="Choose a CV to use."), 400
    user_id = session["user_id"]
    if source == "uploaded" and get_cv_for_user(user_id) is None:
        return jsonify(error="Upload a CV before selecting it."), 400
    language = str(payload.get("language", "en")).strip().lower()
    if language not in {"en", "fr", "ar"}:
        return jsonify(error="Choose English, French, or Arabic."), 400

    user = get_user_by_id(user_id)
    profiles = get_cv_builder_data(user_id)["profiles"]
    candidate = get_candidate_match_profile(user_id) if source == "dna" else dict(profiles.get(source) or {})
    candidate["full_name"] = candidate.get("full_name") or (user["full_name"] if user else "Candidate")
    candidate["email"] = candidate.get("email") or (user["email"] if user else "")
    candidate["phone"] = candidate.get("phone", "")
    candidate["location"] = candidate.get("location", "")
    candidate["summary"] = candidate.get("summary", "")
    candidate["skills"] = candidate.get("skills", "")
    candidate["experience"] = candidate.get("experience", "")

    try:
        ai_choice = _feature_ai_choice("generation")
        letter = generate_ai_cover_letter(
            candidate, offer, company, position, language=language, ai_choice=ai_choice
        )
    except (AIServiceError, ValueError) as exc:
        return jsonify(error=str(exc)), getattr(exc, "status_code", 400)
    return jsonify(
        letter=letter,
        company_name=company["name"],
        position=position,
        offer_title=offer["title"] if offer else "Spontaneous application",
        cv_source=source,
        language=language,
        ai_provider=ai_choice["provider"] if ai_choice else "local",
        ai_model=ai_choice["model"] if ai_choice else None,
    )


def allowed_cv_file(filename):
    return "." in filename and filename.rsplit(".", 1)[1].lower() in ALLOWED_CV_EXTENSIONS


def valid_profile_photo(data, extension):
    if not data:
        return False
    signatures = {
        "jpg": data.startswith(b"\xff\xd8\xff"),
        "jpeg": data.startswith(b"\xff\xd8\xff"),
        "png": data.startswith(b"\x89PNG\r\n\x1a\n"),
        "webp": len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP",
    }
    return signatures.get(extension, False)


def cv_storage_path(stored_filename):
    """Resolve a generated CV filename without allowing traversal outside storage."""
    filename = str(stored_filename or "")
    if not filename or Path(filename).name != filename or secure_filename(filename) != filename:
        raise ValueError("Invalid stored CV filename")
    folder = Path(app.config["CV_UPLOAD_FOLDER"]).resolve()
    path = (folder / filename).resolve()
    if path.parent != folder:
        raise ValueError("Invalid stored CV path")
    return path


@app.route("/cv-builder")
@login_required
def cv_builder():
    user_id = session["user_id"]
    cv = get_cv_for_user(user_id)
    skill_gap = None
    user = get_user_by_id(user_id)
    builder_data = get_cv_builder_data(user_id)
    default_profile = {
        "full_name": user["full_name"] if user else "",
        "job_title": "",
        "email": user["email"] if user else "",
        "phone": "",
        "linkedin": "",
        "github": "",
        "accent_color": "#673147",
        "location": "",
        "summary": "",
        "education": "",
        "experience": "",
        "skills": "",
        "projects": "",
        "certifications": "",
        "languages": "",
    }
    profiles = builder_data["profiles"]
    profiles.setdefault("manual", dict(default_profile))
    profiles.setdefault("uploaded", dict(default_profile))
    templates = builder_data["templates"]
    templates.setdefault("manual", "Modern")
    templates.setdefault("uploaded", "Modern")
    companies = get_all_companies()
    offers = get_offers(companies)
    optimized = builder_data.get("optimized") or {}
    if optimized:
        existing = list(optimized.get("existing_keywords") or [])
        missing = list(optimized.get("missing_keywords") or [])
        gap_skills = [
            {"name": skill, "category": "Offer keyword", "current": 100,
             "required": 100, "gap": 0, "gap_percent": 0, "status": "Strong"}
            for skill in existing
        ] + [
            {"name": skill, "category": "Offer keyword", "current": 0,
             "required": 100, "gap": 100, "gap_percent": 100, "status": "Missing"}
            for skill in missing
        ]
        total = len(gap_skills)
        match_percent = round(len(existing) / total * 100) if total else 0
        skill_gap = {
            "skills": gap_skills,
            "overall_match_percent": match_percent,
            "average_gap_percent": 100 - match_percent,
            "weak_or_missing_count": len(missing),
            "roadmap": [
                {"skill": skill, "action": f"Validate or develop {skill}, then add it only if you can demonstrate it.", "duration": "Self-paced"}
                for skill in missing
            ],
            "company_name": optimized.get("company_name"),
            "offer_title": optimized.get("offer_title"),
        }

    from backend.portrait_service import selected_cv_portrait,cv_photo_path,configured as portrait_configured,list_portraits,STYLES as PORTRAIT_STYLES
    cv_portrait_id=selected_cv_portrait(app.config['PORTRAIT_FOLDER'],user_id)
    cv_photo_url=url_for('cv_portrait_image',portrait_id=cv_portrait_id) if cv_portrait_id else url_for('cv_photo_image') if cv_photo_path(app.config['PORTRAIT_FOLDER'],app.config['PROFILE_PHOTO_FOLDER'],user_id) else ''
    company_recommendations = []
    return render_template(
        "cv_builder.html", active_page="cv_builder", cv=cv, skill_gap=skill_gap,
        builder_data={
            "profiles": profiles,
            "templates": templates,
            "optimized": builder_data["optimized"],
            "optimized_source": builder_data["optimized_source"],
            "initial_source": "uploaded" if cv else "manual",
            "profile_photo_url": cv_photo_url,
        },
        offers=offers,
        companies=companies,
        cv_templates=CV_TEMPLATES,
        cv_accent_colors=CV_ACCENT_COLORS,
        has_profile_photo=bool(builder_data["profile_photo_filename"]),
        cv_photo_url=cv_photo_url,portrait_ready=portrait_configured(),portrait_styles=PORTRAIT_STYLES,
        portrait_gallery=list_portraits(app.config['PORTRAIT_FOLDER'],user_id),selected_cv_portrait_id=cv_portrait_id,
        company_recommendations=company_recommendations[:6],
        extraction_needs_review=bool(session.get("cv_extraction_needs_review")),
    )


@app.route('/api/cv-builder/portraits',methods=['POST'])
@login_required
def cv_portrait_generate():
    from backend.portrait_service import generate_portrait,store_portrait,list_portraits,generation_slot,PortraitError,MAX_INPUT
    mode=request.form.get('mode','ai')
    if mode not in {'free','ai'}:return jsonify(error='Choose a valid photo mode.'),400
    if mode=='ai' and request.form.get('consent')!='yes':
        return jsonify(error='Confirm that this is your photo and agree to send it to Gemini for portrait generation.'),400
    photo=request.files.get('photo')
    if not photo or not photo.filename:return jsonify(error='Choose a photo of yourself first.'),400
    uid=session['user_id']
    today=datetime.now(timezone.utc).date().isoformat()
    try:
        with generation_slot(app.config['PORTRAIT_FOLDER'],uid):
            if sum(item['created_at'].startswith(today) for item in list_portraits(app.config['PORTRAIT_FOLDER'],uid))>=6:
                return jsonify(error='You have generated 6 portraits today. You can reuse or download them below, or try again tomorrow.'),429
            if mode=='free':
                from backend.portrait_service import image_type
                output=photo.read(MAX_INPUT+1)
                if not output or len(output)>MAX_INPUT:raise PortraitError('Choose a photo up to 5 MB.')
                mime=image_type(output)
                style='free'
            else:
                output,mime=generate_portrait(photo.read(MAX_INPUT+1),request.form.get('style','studio'))
                style=request.form.get('style','studio')
            item=store_portrait(app.config['PORTRAIT_FOLDER'],uid,output,mime,style)
    except PortraitError as exc:return jsonify(error=str(exc)),exc.status
    except OSError:
        app.logger.warning('Portrait storage unavailable for user %s',uid)
        return jsonify(error='Your portrait could not be saved. Please try again.'),503
    item['url']=url_for('cv_portrait_image',portrait_id=item['id'])
    item['download_url']=url_for('cv_portrait_image',portrait_id=item['id'],download=1)
    return jsonify(portrait=item),201


@app.route('/cv-builder/photo')
@login_required
def cv_photo_image():
    from backend.portrait_service import cv_photo_path
    path=cv_photo_path(app.config['PORTRAIT_FOLDER'],app.config['PROFILE_PHOTO_FOLDER'],session['user_id'])
    if not path:return 'No CV photo selected.',404
    response=send_from_directory(path.parent,path.name)
    response.headers['Cache-Control']='private, no-store'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


@app.route('/cv-builder/portraits/<portrait_id>')
@login_required
def cv_portrait_image(portrait_id):
    from backend.portrait_service import portrait_path,PortraitError
    try:path=portrait_path(app.config['PORTRAIT_FOLDER'],session['user_id'],portrait_id)
    except PortraitError:return 'Portrait not found.',404
    response=send_from_directory(path.parent,path.name,as_attachment=request.args.get('download')=='1',download_name='TalentSouk-portrait'+path.suffix)
    response.headers['Cache-Control']='private, max-age=3600'
    response.headers['X-Content-Type-Options']='nosniff'
    return response


@app.route('/api/cv-builder/portraits/<portrait_id>/use',methods=['POST'])
@login_required
def cv_portrait_use(portrait_id):
    from backend.portrait_service import select_portrait,selected_cv_portrait,PortraitError
    payload=request.get_json(silent=True)
    if not isinstance(payload,dict):return jsonify(error='Choose where to use the portrait.'),400
    target=payload.get('target')
    try:select_portrait(app.config['PORTRAIT_FOLDER'],app.config['PROFILE_PHOTO_FOLDER'],session['user_id'],portrait_id,target)
    except PortraitError as exc:return jsonify(error=str(exc)),exc.status
    except OSError:return jsonify(error='The selected portrait could not be saved. Please try again.'),503
    cv_id=selected_cv_portrait(app.config['PORTRAIT_FOLDER'],session['user_id'])
    return jsonify(target=target,portrait_id=portrait_id,cv_photo_url=url_for('cv_portrait_image',portrait_id=cv_id) if cv_id else url_for('profile_photo'),profile_photo_url=url_for('profile_photo')+'?v='+uuid.uuid4().hex)


@app.route("/api/cv-builder/profile", methods=["POST"])
@login_required
def cv_builder_profile_save():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Invalid CV profile data."), 400

    source = payload.get("source")
    if source not in {"manual", "uploaded"}:
        return jsonify(error="Choose a valid CV source."), 400
    if source == "uploaded" and get_cv_for_user(session["user_id"]) is None:
        return jsonify(error="Upload a CV before using it as your starting point."), 400

    submitted_profile = payload.get("profile")
    if not isinstance(submitted_profile, dict):
        return jsonify(error="Invalid CV profile data."), 400
    profile = {}
    for field, limit in CV_PROFILE_FIELD_LIMITS.items():
        value = submitted_profile.get(field, "#673147" if field == "accent_color" else "")
        if not isinstance(value, str) or len(value) > limit:
            return jsonify(error=f"Check the {field.replace('_', ' ')} field length."), 400
        profile[field] = value.strip()
    if profile["accent_color"] not in CV_ACCENT_COLORS.values():
        return jsonify(error="Choose one of the available CV colors."), 400

    template = payload.get("template")
    if template not in CV_TEMPLATES:
        return jsonify(error="Choose one of the available CV templates."), 400

    save_cv_profile(session["user_id"], source, profile, template)
    if source == "uploaded":
        session.pop("cv_extraction_needs_review", None)
    return jsonify(profile=profile, template=template)


@app.route("/api/cv-builder/generate", methods=["POST"])
@login_required
def cv_builder_generate():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict) or not isinstance(payload.get("profile"), dict):
        return jsonify(error="Add your CV information first."), 400
    profile = {}
    for field, limit in CV_PROFILE_FIELD_LIMITS.items():
        value = payload["profile"].get(field, "")
        if not isinstance(value, str) or len(value) > limit:
            return jsonify(error="Check the " + field.replace('_', ' ') + " field."), 400
        profile[field] = value.strip()
    notes = payload.get("notes", "")
    language = payload.get("language", "en")
    if not isinstance(notes, str) or len(notes) > 12000 or language not in ("en", "fr", "ar"):
        return jsonify(error="Choose a valid language and keep your story under 12,000 characters."), 400
    if not profile.get("job_title") or not (notes.strip() or any(profile.get(k) for k in ("experience", "education", "skills", "projects"))):
        return jsonify(error="Add your target role and some experience, education, skills or career notes."), 400
    choice = _feature_ai_choice("generation")
    if not choice:
        return jsonify(error="Choose an AI provider in Settings to generate your CV.", settings_url=url_for("settings")), 503
    from backend.cv_generation import generate_cv_draft
    try:
        draft = generate_cv_draft(profile, notes, language, choice)
        for field, limit in CV_PROFILE_FIELD_LIMITS.items():
            if len(draft.get(field, "")) > limit:
                return jsonify(error="The generated CV is too long. Please try a shorter career story."), 502
    except (AIServiceError, ValueError) as exc:
        return jsonify(error=str(exc)), getattr(exc, "status_code", 400)
    return jsonify(profile=draft, provider=choice["provider"], model=choice["model"])


@app.route("/api/cv-builder/improve-section", methods=["POST"])
@login_required
def cv_builder_improve_section():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Add your notes first."), 400
    section = payload.get("section")
    allowed = ("job_title", "summary", "education", "skills", "experience", "projects", "certifications", "languages", "design")
    if section not in allowed:
        return jsonify(error="Choose a valid CV section."), 400
    text, language = payload.get("text", ""), payload.get("language", "en")
    limit = CV_PROFILE_FIELD_LIMITS.get(section, 5000)
    if not isinstance(text, str) or not text.strip() or len(text) > limit or language not in ("en", "fr", "ar"):
        return jsonify(error="Add valid notes and choose a language."), 400
    choice = _feature_ai_choice("generation")
    if not choice:
        return jsonify(error="Choose an AI provider in Settings."), 503
    from backend.cv_generation import improve_section
    try:
        result = improve_section(section, text.strip(), language, choice)
        if len(result) > limit or (section == "design" and result not in CV_TEMPLATES):
            return jsonify(error="Invalid AI draft. Please try again."), 502
    except (AIServiceError, ValueError) as exc:
        return jsonify(error=str(exc)), getattr(exc, "status_code", 400)
    return jsonify(text=result)


@app.route("/api/cv-builder/improve-experience", methods=["POST"])
@login_required
def cv_builder_improve_experience():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Describe your experience first."), 400
    text = payload.get("experience", "")
    language = payload.get("language", "en")
    if not isinstance(text, str) or not text.strip() or len(text) > CV_PROFILE_FIELD_LIMITS["experience"]:
        return jsonify(error="Describe your experience using up to 12,000 characters."), 400
    if language not in ("en", "fr", "ar"):
        return jsonify(error="Choose English, French, or Arabic."), 400
    choice = _feature_ai_choice("generation")
    if not choice:
        return jsonify(error="Choose an AI provider in Settings to improve your experience."), 503
    from backend.cv_generation import improve_experience
    try:
        result = improve_experience(text.strip(), language, choice)
    except (AIServiceError, ValueError) as exc:
        return jsonify(error=str(exc)), getattr(exc, "status_code", 400)
    return jsonify(experience=result)


@app.route("/api/cv-builder/generate-summary", methods=["POST"])
@login_required
def cv_builder_generate_summary():
    payload = request.get_json(silent=True) or {}
    submitted = payload.get("profile")
    if not isinstance(submitted, dict):
        return jsonify(error="Add your CV information before generating a summary."), 400
    profile = {}
    for field in ("job_title", "skills", "experience", "education", "projects", "certifications", "languages", "location"):
        value = submitted.get(field, "")
        if not isinstance(value, str) or len(value) > CV_PROFILE_FIELD_LIMITS[field]:
            return jsonify(error=f"Check the {field.replace('_', ' ')} field."), 400
        profile[field] = value.strip()
    language = str(payload.get("language") or "en").lower()
    if language not in {"ar", "en", "fr"}:
        return jsonify(error="Choose English, French, or Arabic."), 400
    ai_choice = _feature_ai_choice("generation")
    if not ai_choice:
        return jsonify(
            error="AI is not ready. Choose Gemini, Groq, or NVIDIA in Settings and configure its API key.",
            settings_url=url_for("settings"),
        ), 503
    try:
        summaries = generate_professional_summaries(profile, ai_choice, language)
    except (AIServiceError, ValueError) as exc:
        return jsonify(error=str(exc)), getattr(exc, "status_code", 400)
    return jsonify(summaries=summaries, provider=ai_choice["provider"], model=ai_choice["model"])


@app.route("/api/cv-builder/optimize", methods=["POST"])
@login_required
def cv_builder_optimize():
    payload = request.get_json(silent=True)
    if not isinstance(payload, dict):
        return jsonify(error="Invalid optimization request."), 400

    source = payload.get("source")
    if source not in {"manual", "uploaded", "dna"}:
        return jsonify(error="Choose a current CV."), 400
    if source == "uploaded" and get_cv_for_user(session["user_id"]) is None:
        return jsonify(error="Upload a CV before optimizing it."), 400

    raw_offer_id = payload.get("offer_id")
    offer = None
    available_offers = get_offers(get_all_companies())
    if raw_offer_id not in (None, ""):
        try:
            offer_id = int(raw_offer_id)
        except (TypeError, ValueError):
            return jsonify(error="Choose an available job or internship offer."), 400
        offer = next((item for item in available_offers if item["id"] == offer_id), None)
        if offer is None:
            return jsonify(error="Choose an available job or internship offer."), 400

    raw_company_id = payload.get("company_id")
    if raw_company_id in (None, "") and offer is not None:
        raw_company_id = offer["company_id"]
    try:
        company_id = int(raw_company_id)
    except (TypeError, ValueError):
        return jsonify(error="Choose a company."), 400
    company = get_company(company_id)
    if company is None:
        return jsonify(error="Choose a company from the database."), 400
    if offer is not None and offer["company_id"] != company_id:
        return jsonify(error="Choose an offer for the selected company."), 400

    data = get_cv_builder_data(session["user_id"])
    profile = get_candidate_match_profile(session["user_id"]) if source == "dna" else data["profiles"].get(source)
    if not isinstance(profile, dict):
        return jsonify(error="Save the selected CV profile before optimizing."), 400
    profile = dict(profile)
    if source == "uploaded":
        uploaded_cv = get_cv_for_user(session["user_id"])
        if uploaded_cv is not None and uploaded_cv["extracted_text"]:
            profile["cv_text"] = uploaded_cv["extracted_text"]
    optimized = optimize_cv_for_job(
        profile, offer, company, ai_choice=_feature_ai_choice("matching")
    )
    optimized["template"] = data["templates"].get(source, "Modern")
    optimized["version_id"] = save_optimized_cv(session["user_id"], source, optimized)
    return jsonify(optimized)


@app.route('/cv-versions')
@login_required
def cv_versions():
    return render_template('cv_versions.html', active_page='cv_builder', page_title='My CV versions', versions=get_cv_versions(session['user_id']))


@app.route('/cv-versions/<int:version_id>/changes')
@login_required
def cv_version_changes(version_id):
    version = get_cv_version(session['user_id'], version_id)
    if version is None:
        return jsonify(error='CV version not found.'), 404
    return render_template('cv_version_changes.html', active_page='cv_builder', page_title='CV Before / After', version=version)


@app.route('/cv-versions/<int:version_id>')
@login_required
def cv_version_view(version_id):
    version=get_cv_version(session['user_id'],version_id)
    if version is None:
        return jsonify(error='CV version not found.'),404
    if not isinstance(version['optimized'].get('profile'),dict):
        return jsonify(error='This saved version has no printable CV.'),422
    html=render_template('optimized_cv_print.html',optimized=version['optimized'])
    response=make_response(html)
    response.headers['Cache-Control']='private, no-store'
    if request.args.get('download')=='html':
        response.headers['Content-Disposition']='attachment; filename="TalentSouk-CV-%s.html"' % version_id
    return response


@app.route("/cv-builder/optimized/print")
@login_required
def optimized_cv_print():
    optimized = get_cv_builder_data(session["user_id"]).get("optimized")
    if not optimized or not isinstance(optimized.get("profile"), dict):
        flash("Generate an optimized CV before exporting it.", "error")
        return redirect(url_for("cv_builder", _anchor="optimizer-heading"))
    return render_template("optimized_cv_print.html", optimized=optimized)


@app.route("/cv-builder/upload", methods=["POST"])
@login_required
def cv_upload():
    user_id = session["user_id"]
    file = request.files.get("cv_file")

    if file is None or file.filename == "":
        flash("Please choose a PDF, DOC, or DOCX file to upload.", "error")
        return redirect(url_for("cv_builder"))

    if not allowed_cv_file(file.filename):
        flash("Only PDF, DOC, and DOCX files are supported.", "error")
        return redirect(url_for("cv_builder"))

    extension = file.filename.rsplit(".", 1)[1].lower()
    original_filename = secure_filename(file.filename) or f"cv.{extension}"
    stored_filename = f"user{user_id}_{uuid.uuid4().hex}.{extension}"
    data = file.read(MAX_CV_FILE_SIZE + 1)
    if len(data) > MAX_CV_FILE_SIZE:
        flash("The CV must be 5 MB or smaller.", "error")
        return redirect(url_for("cv_builder"))

    try:
        extracted = extract_cv(data, extension)
    except CVExtractionError as exc:
        flash(str(exc), "error")
        return redirect(url_for("cv_builder"))

    existing = get_cv_for_user(user_id)
    new_path = cv_storage_path(stored_filename)
    try:
        new_path.write_bytes(data)
        save_cv(
            user_id=user_id,
            original_filename=original_filename,
            stored_filename=stored_filename,
            file_extension=extension,
            mime_type=extracted.mime_type,
            file_size=len(data),
            content_sha256=extracted.content_sha256,
            extracted_text=extracted.text,
            extraction_status=extracted.extraction_status,
            page_count=extracted.page_count,
        )
    except Exception:
        new_path.unlink(missing_ok=True)
        app.logger.exception("CV storage failed")
        flash("The CV could not be stored. Your previous CV was preserved.", "error")
        return redirect(url_for("cv_builder"))

    if existing is not None and existing["stored_filename"] != stored_filename:
        try:
            cv_storage_path(existing["stored_filename"]).unlink(missing_ok=True)
        except ValueError:
            app.logger.warning("Ignored an invalid legacy CV storage path")

    if extracted.text:
        user = get_user_by_id(user_id)
        fields = extract_profile_fields(extracted.text)
        extracted_profile = {
            "full_name": user["full_name"] if user else "",
            "job_title": "", "email": fields["email"] or (user["email"] if user else ""),
            "phone": fields["phone"], "linkedin": fields["linkedin"], "github": fields["github"],
            "accent_color": "#673147", "location": "", "summary": fields["summary"],
            "education": fields["education"], "experience": fields["experience"],
            "skills": fields["skills"], "projects": fields["projects"],
            "certifications": fields["certifications"], "languages": fields["languages"],
        }
        save_cv_profile(user_id, "uploaded", extracted_profile, "Modern")
        session["cv_extraction_needs_review"] = True
        flash("CV information was extracted. Review every field below, then click Save CV.", "success")
    else:
        flash("Your CV was uploaded, but it contains no extractable text.", "success")
    return redirect(url_for("cv_builder"))


@app.route("/cv-builder/view")
@login_required
def cv_view():
    cv = get_cv_for_user(session["user_id"])
    if cv is None:
        flash("No CV on file yet.", "error")
        return redirect(url_for("cv_builder"))
    try:
        path = cv_storage_path(cv["stored_filename"])
    except ValueError:
        return "", 404
    if not path.is_file():
        return "", 404
    return send_from_directory(
        path.parent, path.name, as_attachment=False,
        download_name=cv["original_filename"], mimetype=cv["mime_type"] or None,
    )


@app.route("/cv-builder/download")
@login_required
def cv_download():
    cv = get_cv_for_user(session["user_id"])
    if cv is None:
        flash("No CV on file yet.", "error")
        return redirect(url_for("cv_builder"))
    try:
        path = cv_storage_path(cv["stored_filename"])
    except ValueError:
        return "", 404
    if not path.is_file():
        return "", 404
    return send_from_directory(
        path.parent, path.name, as_attachment=True,
        download_name=cv["original_filename"], mimetype=cv["mime_type"] or None,
    )


@app.route("/cv-builder/delete", methods=["POST"])
@login_required
def cv_delete():
    user_id = session["user_id"]
    cv = get_cv_for_user(user_id)
    if cv is not None:
        delete_cv(user_id)
        try:
            cv_storage_path(cv["stored_filename"]).unlink(missing_ok=True)
        except ValueError:
            app.logger.warning("Ignored an invalid legacy CV storage path")
        flash("Your CV was deleted.", "success")
    return redirect(url_for("cv_builder"))


@app.route("/profile")
@login_required
def profile():
    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    builder_data = get_cv_builder_data(user_id)
    manual = builder_data["profiles"].get("manual") or {}
    uploaded = builder_data["profiles"].get("uploaded") or {}
    profile_data = dict(uploaded)
    profile_data.update({
        field: value for field, value in manual.items()
        if value not in (None, "")
    })
    profile_data["full_name"] = user["full_name"] if user else ""
    profile_data["email"] = user["email"] if user else ""
    profile_data["career_objective"] = builder_data["career_objective"]
    for goal in (
        "target_position", "career_field", "target_location", "target_skills",
        "career_goal", "education_level", "experience_level",
    ):
        profile_data[goal] = builder_data[goal]
    cv = get_cv_for_user(user_id)
    return render_template(
        "profile.html",
        active_page="profile",
        profile=profile_data,
        cv=cv,
        has_profile_photo=bool(builder_data["profile_photo_filename"]),
        initials=get_initials(profile_data["full_name"]),
        career_goals=CAREER_GOALS,
        education_levels=EDUCATION_LEVELS,
        experience_levels=EXPERIENCE_LEVELS,
        target_skill_options=TARGET_SKILL_OPTIONS,
    )


@app.route("/profile/photo")
@login_required
def profile_photo():
    photo_filename = get_cv_builder_data(session["user_id"])["profile_photo_filename"]
    if not photo_filename:
        return "", 404
    if not (Path(app.config["PROFILE_PHOTO_FOLDER"]) / photo_filename).is_file():
        return "", 404
    return send_from_directory(app.config["PROFILE_PHOTO_FOLDER"], photo_filename)


@app.route("/profile/update", methods=["POST"])
@login_required
def profile_update():
    user_id = session["user_id"]
    full_name = request.form.get("full_name", "").strip()
    email = request.form.get("email", "").strip().lower()
    if not full_name or not email or "@" not in email:
        flash("Enter a name and valid email address.", "error")
        return redirect(url_for("profile"))

    builder_data = get_cv_builder_data(user_id)
    photo_file = request.files.get("profile_photo")
    new_photo_filename = ""
    new_photo_data = None
    if photo_file and photo_file.filename:
        extension = photo_file.filename.rsplit(".", 1)[-1].lower()
        if "." not in photo_file.filename or extension not in ALLOWED_PROFILE_PHOTO_EXTENSIONS:
            flash("Profile photos must be JPG, PNG, or WebP images.", "error")
            return redirect(url_for("profile"))
        new_photo_data = photo_file.read(2 * 1024 * 1024 + 1)
        if len(new_photo_data) > 2 * 1024 * 1024:
            flash("Profile photos must be 2 MB or smaller.", "error")
            return redirect(url_for("profile"))
        if not valid_profile_photo(new_photo_data, extension):
            flash("The selected file is not a valid profile image.", "error")
            return redirect(url_for("profile"))
        new_photo_filename = f"user{user_id}_{uuid.uuid4().hex}.{extension}"

    fields = (
        "phone", "location", "linkedin", "github", "summary", "education", "skills", "languages", "experience",
        "projects", "certifications",
    )
    limits = {
        "phone": 60, "location": 120, "linkedin": 300, "github": 300,
        "summary": 4000, "education": 10000, "skills": 5000,
        "languages": 2000, "experience": 12000, "projects": 10000,
        "certifications": 5000,
    }
    manual_profile = dict(builder_data["profiles"].get("manual") or {})
    manual_profile.update({"full_name": full_name, "email": email})
    for field in fields:
        value = request.form.get(field, "").strip()
        if len(value) > limits[field]:
            flash(f"The {field.replace('_', ' ')} field is too long.", "error")
            return redirect(url_for("profile"))
        manual_profile[field] = value
    social_patterns = {
        "linkedin": r"^https://(www\.)?linkedin\.com/",
        "github": r"^https://(www\.)?github\.com/",
    }
    for field, pattern in social_patterns.items():
        if manual_profile.get(field) and not re.match(pattern, manual_profile[field], re.IGNORECASE):
            flash(f"Enter a valid HTTPS {field.title()} profile URL.", "error")
            return redirect(url_for("profile"))

    career_objective = request.form.get("career_objective", "").strip()
    if len(career_objective) > 4000:
        flash("Career objective must be 4000 characters or fewer.", "error")
        return redirect(url_for("profile"))

    if not update_user_profile(user_id, full_name, email):
        flash("An account with that email already exists.", "error")
        return redirect(url_for("profile"))

    if new_photo_filename:
        (Path(app.config["PROFILE_PHOTO_FOLDER"]) / new_photo_filename).write_bytes(new_photo_data)
    save_cv_profile(
        user_id, "manual", manual_profile,
        builder_data["templates"].get("manual", "Modern"),
    )
    uploaded_profile = builder_data["profiles"].get("uploaded")
    if uploaded_profile is not None:
        uploaded_profile["full_name"] = full_name
        uploaded_profile["email"] = email
        save_cv_profile(
            user_id, "uploaded", uploaded_profile,
            builder_data["templates"].get("uploaded", "Modern"),
        )

    photo_filename = new_photo_filename or builder_data["profile_photo_filename"]
    goals = {name: request.form.get(name, "").strip()[:500] for name in ("target_position", "career_field", "target_location")}
    goals["target_skills"] = collect_target_skills(request.form)[:500]
    career_goal = request.form.get("career_goal", "").strip().lower()
    education_level = request.form.get("education_level", "").strip()
    experience_level = request.form.get("experience_level", "").strip()
    if career_goal and career_goal not in CAREER_GOALS:
        flash("Choose a valid career goal.", "error")
        return redirect(url_for("profile"))
    if education_level and education_level not in EDUCATION_LEVELS:
        flash("Choose a valid education level.", "error")
        return redirect(url_for("profile"))
    if experience_level and experience_level not in EXPERIENCE_LEVELS:
        flash("Choose a valid experience level.", "error")
        return redirect(url_for("profile"))
    save_candidate_profile_metadata(
        user_id, career_objective, photo_filename, **goals,
        career_goal=career_goal, education_level=education_level,
        experience_level=experience_level,
    )
    if new_photo_filename and builder_data["profile_photo_filename"]:
        previous_path = os.path.join(
            app.config["PROFILE_PHOTO_FOLDER"], builder_data["profile_photo_filename"]
        )
        if os.path.exists(previous_path):
            os.remove(previous_path)

    if new_photo_filename:
        save_appearance(user_id,dict(get_appearance(user_id),avatar="photo"))
    flash("Your profile has been updated.", "success")
    return redirect(url_for("profile"))


@app.route("/profile/photo/update", methods=["POST"])
@login_required
def profile_photo_update():
    user_id = session["user_id"]
    photo_file = request.files.get("profile_photo")
    if photo_file is None or not photo_file.filename:
        flash("Choose a JPG, PNG, or WebP image.", "error")
        return redirect(url_for("profile"))
    filename = secure_filename(photo_file.filename)
    extension = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
    if extension not in ALLOWED_PROFILE_PHOTO_EXTENSIONS:
        flash("Profile photos must be JPG, PNG, or WebP images.", "error")
        return redirect(url_for("profile"))
    data = photo_file.read(2 * 1024 * 1024 + 1)
    if len(data) > 2 * 1024 * 1024:
        flash("Profile photos must be 2 MB or smaller.", "error")
        return redirect(url_for("profile"))
    if not valid_profile_photo(data, extension):
        flash("The selected file is not a valid profile image.", "error")
        return redirect(url_for("profile"))

    builder_data = get_cv_builder_data(user_id)
    new_filename = f"user{user_id}_{uuid.uuid4().hex}.{extension}"
    new_path = Path(app.config["PROFILE_PHOTO_FOLDER"]) / new_filename
    try:
        new_path.write_bytes(data)
        save_candidate_profile_metadata(
            user_id, builder_data["career_objective"], new_filename,
            target_position=builder_data["target_position"],
            career_field=builder_data["career_field"],
            target_location=builder_data["target_location"],
            target_skills=builder_data["target_skills"],
            career_goal=builder_data["career_goal"],
            education_level=builder_data["education_level"],
            experience_level=builder_data["experience_level"],
        )
    except Exception:
        new_path.unlink(missing_ok=True)
        app.logger.exception("Profile photo update failed")
        flash("The profile photo could not be saved.", "error")
        return redirect(url_for("profile"))
    old_filename = builder_data["profile_photo_filename"]
    if old_filename and old_filename != new_filename:
        (Path(app.config["PROFILE_PHOTO_FOLDER"]) / Path(old_filename).name).unlink(missing_ok=True)
    saved_appearance=get_appearance(user_id)
    save_appearance(user_id,dict(saved_appearance,avatar="photo"))
    flash("Profile photo updated.", "success")
    destination = request.form.get("next", "profile")
    if destination=='cv_builder':
        from backend.portrait_service import owner_folder,atomic_json
        folder=owner_folder(app.config['PORTRAIT_FOLDER'],user_id)
        if folder.exists():atomic_json(folder/'selection.json',{'cv_photo_id':None})
    return redirect(url_for(destination if destination in {"cv_builder","profile","settings","personalize","dashboard","tutorial_intro"} else "profile"))


@app.route('/getting-started')
@login_required
def tutorial_intro():
    return render_template('tutorial_intro.html',active_page='profile',page_title='Get started',tutorial_steps=TUTORIAL_STEPS)


@app.route('/tutorial/action',methods=['POST'])
@login_required
def tutorial_action():
    payload=request.get_json(silent=True) if request.is_json else request.form
    if not isinstance(payload,dict) and not hasattr(payload,'get'):return jsonify(error='Choose a tutorial action.'),400
    action=payload.get('action')
    try:state=change_tutorial(session['user_id'],action)
    except ValueError as exc:return jsonify(error=str(exc)),400
    if state['status']=='running':
        step=TUTORIAL_STEPS[state['step']]
        target=url_for(step['endpoint'],tour='1',**step.get('args',{}))
        config=dict(step,index=state['step'],total=len(TUTORIAL_STEPS))
    else:
        target=url_for('dashboard')
        config=None
    if request.is_json:return jsonify(url=target,state=state,step=config)
    return redirect(target)


@app.route('/personalize')
@login_required
def personalize():
    return render_template('personalize.html',active_page='profile',page_title='Make it yours')


@app.route('/settings/appearance',methods=['POST'])
@login_required
def settings_appearance():
    destination=request.form.get('next','settings')
    if destination not in {'profile','settings','personalize','dashboard','tutorial_intro'}:
        destination='settings'
    uid=session['user_id']
    photo=request.files.get('profile_photo')
    values={key:request.form.get(key,default) for key,default in get_appearance(uid).items()}
    try:
        values=validate_appearance(values)
        if photo and photo.filename:
            extension=photo.filename.rsplit('.',1)[-1].lower() if '.' in photo.filename else ''
            data=photo.read(2*1024*1024+1)
            photo.stream.seek(0)
            if extension not in ALLOWED_PROFILE_PHOTO_EXTENSIONS or len(data)>2*1024*1024 or not valid_profile_photo(data,extension):
                raise ValueError('Choose a valid JPG, PNG or WebP photo, up to 2 MB.')
            values['avatar']='photo'
        elif values['avatar']=='photo' and not get_cv_builder_data(uid)['profile_photo_filename']:
            raise ValueError('Upload a photo first or choose one of the avatars.')
        save_appearance(uid,values)
    except ValueError as error:
        flash(str(error),'error')
        return redirect(url_for('personalize' if destination in {'dashboard','tutorial_intro'} else destination))
    if photo and photo.filename:
        return profile_photo_update()
    flash('Your avatar and appearance have been saved.','success')
    return redirect(url_for(destination,_anchor='settings-appearance' if destination=='settings' else None))


@app.route("/settings", methods=["GET", "POST"])
@login_required
def settings():
    if request.method == "POST":
        language = request.form.get("language", "").strip().lower()
        if not update_user_language(session["user_id"], language):
            flash("Choose Arabic, French, or English.", "error")
        else:
            flash("Settings saved.", "success")
        return redirect(url_for("settings"))
    return render_template(
        "settings.html", active_page="settings",
        gmail_connection=get_gmail_credentials(session["user_id"]),
        gmail_configured=gmail_is_configured(),
        preferences=get_user_settings(session["user_id"]),
        ai_status=get_ai_status(
            get_user_settings(session["user_id"]).get("ai_provider"),
            get_user_settings(session["user_id"]).get("ai_model"),
        ),
        ai_models=get_ai_models(),
    )


@app.route("/settings/preferences", methods=["POST"])
@login_required
def settings_preferences():
    frequency = request.form.get("notification_frequency", "daily")
    provider = request.form.get("ai_provider", "gemini")
    model = request.form.get("ai_model", "")
    provider_models = get_ai_models().get(provider, [])
    if not model and provider_models:
        model = provider_models[0]["id"]
    visibility = request.form.get("profile_visibility", "private")
    if frequency not in {"instant", "daily", "weekly", "off"}:
        flash("Choose a valid notification frequency.", "error")
    elif provider not in {"gemini", "groq", "grok", "nvidia", "none"}:
        flash("Choose a valid preferred AI provider.", "error")
    elif provider != "none" and model not in {
        item["id"] for item in provider_models
    }:
        flash("Choose a valid AI model.", "error")
    elif visibility not in {"private", "recruiters"}:
        flash("Choose a valid profile visibility.", "error")
    else:
        save_user_settings(session["user_id"], {
            "email_notifications": request.form.get("email_notifications") == "on",
            "ai_suggestions": request.form.get("ai_suggestions") == "on",
            "notification_frequency": frequency,
            "ai_provider": provider,
            "ai_model": model,
            "profile_visibility": visibility,
            "analytics_enabled": request.form.get("analytics_enabled") == "on",
        })
        flash("Preferences saved.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/change-password", methods=["POST"])
@login_required
def settings_change_password():
    user = get_user_by_id(session["user_id"])
    current_password = request.form.get("current_password", "")
    new_password = request.form.get("new_password", "")
    confirm_password = request.form.get("confirm_password", "")
    if user is None or not check_password_hash(user["password_hash"], current_password):
        flash("Current password is incorrect.", "error")
    elif len(new_password) < 8:
        flash("New password must be at least 8 characters long.", "error")
    elif new_password != confirm_password:
        flash("New passwords do not match.", "error")
    elif check_password_hash(user["password_hash"], new_password):
        flash("Choose a password different from your current password.", "error")
    else:
        update_user_password(user["id"], generate_password_hash(new_password))
        flash("Password changed successfully.", "success")
    return redirect(url_for("settings"))


@app.route("/settings/export-data")
@login_required
def settings_export_data():
    user_id = session["user_id"]
    conn = get_db_connection()
    user = conn.execute(
        "SELECT id, full_name, email, preferred_language, created_at FROM users WHERE id = ?",
        (user_id,),
    ).fetchone()
    export = {"exported_at": datetime.now(timezone.utc).isoformat(), "account": dict(user)}
    for table in (
        "cvs", "applications", "cv_builder_data", "reminders", "notifications",
        "application_history", "application_email_attempts", "user_settings",
    ):
        rows = conn.execute(f"SELECT * FROM {table} WHERE user_id = ?", (user_id,)).fetchall()
        export[table] = [dict(row) for row in rows]
    conn.close()
    response = make_response(jsonify(export))
    response.headers["Content-Disposition"] = f'attachment; filename="talentsouk-data-{user_id}.json"'
    return response


@app.route("/settings/delete-account", methods=["POST"])
@login_required
def settings_delete_account():
    user_id = session["user_id"]
    user = get_user_by_id(user_id)
    password = request.form.get("password", "")
    confirmation = request.form.get("confirmation", "").strip().upper()
    if user is None or not check_password_hash(user["password_hash"], password):
        flash("Password is incorrect. Your account was not deleted.", "error")
        return redirect(url_for("settings"))
    if confirmation != "DELETE":
        flash("Type DELETE to confirm account deletion.", "error")
        return redirect(url_for("settings"))
    cv = get_cv_for_user(user_id)
    builder = get_cv_builder_data(user_id)
    if not delete_user_account(user_id):
        flash("The account could not be deleted.", "error")
        return redirect(url_for("settings"))
    if cv:
        try:
            cv_storage_path(cv["stored_filename"]).unlink(missing_ok=True)
        except ValueError:
            app.logger.warning("Ignored invalid CV path while deleting account %s", user_id)
    if builder["profile_photo_filename"]:
        (Path(app.config["PROFILE_PHOTO_FOLDER"]) / Path(builder["profile_photo_filename"]).name).unlink(missing_ok=True)
    from backend.portrait_service import owner_folder
    portrait_root=Path(app.config['PORTRAIT_FOLDER']).resolve()
    portrait_owner=owner_folder(portrait_root,user_id).resolve()
    if portrait_owner.parent==portrait_root:
        from backend.upload_storage import delete_folder
        delete_folder(portrait_owner)
    if portrait_owner.parent==portrait_root and portrait_owner.is_dir():
        import shutil
        shutil.rmtree(portrait_owner)
    session.clear()
    flash("Your TalentSouk account and personal data were deleted.", "success")
    return redirect(url_for("login"))


@app.route("/api/settings/language", methods=["POST"])
def settings_language():
    payload = request.get_json(silent=True) or {}
    if not isinstance(payload,dict):return jsonify(error="Choose Arabic, French, or English."),400
    language = str(payload.get("language", "")).strip().lower()
    if language not in {"en", "fr", "ar"}:
        return jsonify(error="Choose Arabic, French, or English."), 400
    if session.get("user_id") and not update_user_language(session["user_id"], language):
        return jsonify(error="Language could not be saved."), 400
    response=jsonify(success=True, language=language)
    response.set_cookie("ui_language",language,max_age=31536000,samesite="Lax",httponly=True,secure=request.is_secure)
    return response


if __name__ == "__main__":
    from backend.radar_watch import start_watcher
    start_watcher()
    app.run(
        host=os.environ.get("FLASK_HOST", "0.0.0.0"),
        port=int(os.environ.get("PORT", "5000")),
        debug=os.environ.get("FLASK_DEBUG", "0") == "1",
    )

