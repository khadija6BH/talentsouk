"""Shared SMTP delivery for application and account emails."""

import os
import smtplib
import ssl
from html import escape
from email.message import EmailMessage
from email.utils import formataddr, make_msgid
from pathlib import Path


class SMTPConfigurationError(RuntimeError):
    pass


def _settings():
    return {
        "host": os.environ.get("SMTP_HOST", "").strip(),
        "port": os.environ.get("SMTP_PORT", "").strip(),
        "user": os.environ.get("SMTP_USER", "").strip(),
        "password": os.environ.get("SMTP_PASSWORD", ""),
        "from_name": os.environ.get("SMTP_FROM_NAME", "").strip(),
        "use_tls": os.environ.get("SMTP_USE_TLS", "true").strip().casefold(),
    }


def smtp_configured():
    settings = _settings()
    try:
        port = int(settings["port"])
    except (TypeError, ValueError):
        return False
    return bool(
        settings["host"] and settings["user"] and settings["password"]
        and settings["from_name"] and 1 <= port <= 65535
    )


def _deliver(message):
    settings = _settings()
    port = int(settings["port"])
    context = ssl.create_default_context()
    if port == 465:
        with smtplib.SMTP_SSL(settings["host"], port, context=context, timeout=30) as server:
            server.login(settings["user"], settings["password"])
            server.send_message(message)
    else:
        with smtplib.SMTP(settings["host"], port, timeout=30) as server:
            if settings["use_tls"] in {"1", "true", "yes", "on"}:
                server.starttls(context=context)
            server.login(settings["user"], settings["password"])
            server.send_message(message)


def send_application_email(*, recipient, reply_to, copy_to, subject, body, cv_path, cv_filename, cv_mime_type="", cover_letter_text=""):
    if not smtp_configured():
        raise SMTPConfigurationError("Le service d’envoi d’e-mails n’est pas configuré.")

    settings = _settings()
    message = EmailMessage()
    message["From"] = formataddr((settings["from_name"], settings["user"]))
    message["Reply-To"] = reply_to
    message["To"] = recipient
    # Keep a private copy in the candidate's mailbox without exposing their
    # address to the company as a visible CC recipient.
    if copy_to and copy_to.casefold() != recipient.casefold():
        message["Bcc"] = copy_to
    message["Subject"] = subject
    message["Message-ID"] = make_msgid()
    message.set_content(body)

    path = Path(cv_path)
    data = path.read_bytes()
    mime_type = cv_mime_type or "application/octet-stream"
    maintype, _, subtype = mime_type.partition("/")
    if not subtype:
        maintype, subtype = "application", "octet-stream"
    message.add_attachment(data, maintype=maintype, subtype=subtype, filename=cv_filename)
    if str(cover_letter_text or "").strip():
        message.add_attachment(str(cover_letter_text).strip().encode("utf-8"), maintype="text", subtype="plain", filename="cover-letter.txt")

    _deliver(message)

    return message["Message-ID"]


def send_password_reset_email(*, recipient, reset_url=None, reset_code=None):
    if not smtp_configured():
        raise SMTPConfigurationError("The email service is not configured.")

    settings = _settings()
    message = EmailMessage()
    message["From"] = formataddr((settings["from_name"], settings["user"]))
    message["To"] = recipient
    message["Subject"] = "Reset your TalentSouk password"
    message["Message-ID"] = make_msgid()
    if reset_code:
        text_body = (
            "A password reset was requested for your TalentSouk account.\n\n"
            f"Your verification code is: {reset_code}\n\n"
            "Enter this code in the TalentSouk app within 60 minutes. It can be used only once.\n\n"
            "If you did not request this, you can ignore this email. Your password has not changed."
        )
        html_body = (
            "<p>A password reset was requested for your TalentSouk account.</p>"
            "<p>Your verification code is:</p>"
            f"<p style=\"font-size:28px;font-weight:700;letter-spacing:6px;color:#673147\">{escape(reset_code)}</p>"
            "<p>Enter it in TalentSouk within 60 minutes. It can be used only once.</p>"
            "<p>If you did not request this, you can ignore this email.</p>"
        )
    elif reset_url:
        text_body = (
            "A password reset was requested for your TalentSouk account.\n\n"
            f"Use this secure link within 60 minutes:\n{reset_url}\n\n"
            "If you did not request this, you can ignore this email. Your password has not changed."
        )
        safe_url = escape(reset_url, quote=True)
        html_body = (
            "<p>A password reset was requested for your TalentSouk account.</p>"
            "<p><a href=\"" + safe_url + "\">Reset your password</a></p>"
            "<p>This link expires in 60 minutes and can be used only once.</p>"
            "<p>If you did not request this, you can ignore this email.</p>"
        )
    else:
        raise ValueError("A reset URL or verification code is required.")
    # Keep the URL intact in plain-text clients and provide an explicit link for
    # HTML clients. Quoted-printable wrapping can otherwise split the token.
    message.set_content(text_body, cte="8bit")
    add_branded_html(message, html_body, "Forgot password", "/forgot-password")
    _deliver(message)
    return message["Message-ID"]


def send_verification_email(*,recipient,code):
    if not smtp_configured():raise SMTPConfigurationError('Email sending is not configured.')
    settings=_settings()
    message=EmailMessage()
    message['From']=formataddr((settings['from_name'],settings['user']))
    message['To']=recipient
    message['Subject']='Verify your TalentSouk email'
    message['Message-ID']=make_msgid()
    message.set_content('Confirm that this email belongs to you.\n\nYour TalentSouk verification code: '+code+'\n\nIt expires in 10 minutes and can be used once. If you did not request this, ignore this email.')
    add_branded_html(message, "<p>Confirm ownership of your email.</p><p style=\"font-size:28px;font-weight:bold;letter-spacing:5px\">"+escape(code)+"</p><p>This code expires in 10 minutes. Ignore this email if you did not request it.</p>", "Create account / Email verification", "/verify-email")
    _deliver(message)
    return message['Message-ID']


def app_link(path):
    from urllib.parse import urlsplit
    base = os.environ.get("APP_BASE_URL", "http://127.0.0.1:8000").strip().rstrip("/")
    parsed = urlsplit(base)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc or parsed.username or parsed.password:
        base = "http://127.0.0.1:8000"
    path = str(path or "/home")
    if not path.startswith("/") or path.startswith("//") or "\\" in path:
        path = "/home"
    return base + path


def notification_page(path):
    path = str(path or "")
    for prefix, label in (("/opportunities", "Opportunity Radar"), ("/opportunity-radar", "Opportunity Radar"), ("/crm", "CRM"), ("/applications", "Applications"), ("/interview", "AI Interview Simulator"), ("/skill", "Skill Gap"), ("/career", "Career tools"), ("/profile", "Profile")):
        if path.startswith(prefix): return label
    return "TalentSouk notifications"


def add_branded_html(message, content, page, path):
    # Email clients reliably preserve table widths and cell backgrounds.
    safe_page = escape(page)
    safe_link = escape(app_link(path), quote=True)
    html = f'''<!doctype html><html><head><meta name="viewport" content="width=device-width,initial-scale=1"></head>
<body style="margin:0;padding:0;background-color:#f5f1f7;font-family:Arial,Helvetica,sans-serif;color:#311432">
<table role="presentation" width="100%" cellspacing="0" cellpadding="0" border="0" bgcolor="#f5f1f7"><tr><td align="center" style="padding:24px 12px">
<table role="presentation" width="560" cellspacing="0" cellpadding="0" border="0" bgcolor="#ffffff" style="width:100%;max-width:560px;border:1px solid #D8C7D8">
<tr><td bgcolor="#311432" style="padding:20px 24px;background-color:#311432">
<table role="presentation" cellspacing="0" cellpadding="0" border="0"><tr><td width="48" align="center" valign="middle" bgcolor="#E6E6FA" style="width:48px;height:48px;border-radius:24px 24px 8px 8px;background-color:#E6E6FA;color:#311432;font-family:Georgia,serif;font-size:22px;font-weight:bold">TS</td><td valign="middle" style="padding-left:14px;color:#ffffff;font-size:24px;font-weight:bold">TalentSouk<br><span style="color:#E6E6FA;font-size:12px;font-weight:normal">Your career space</span></td></tr></table>
</td></tr><tr><td style="padding:24px;color:#311432;font-size:15px;line-height:1.6;word-break:break-word">
<p style="margin:0 0 18px;color:#673147;font-size:13px;font-weight:bold">TalentSouk · {safe_page}</p>
{content}
<table role="presentation" cellspacing="0" cellpadding="0" border="0" style="margin-top:22px"><tr><td bgcolor="#673147" style="background-color:#673147;border-radius:8px"><a href="{safe_link}" style="display:inline-block;padding:12px 18px;color:#ffffff;text-decoration:none;font-size:14px;font-weight:bold">Open {safe_page}</a></td></tr></table>
</td></tr><tr><td bgcolor="#E6E6FA" style="padding:16px 24px;font-size:12px;color:#673147;line-height:1.5">Sent by TalentSouk<br>This message comes from the {safe_page} page.</td></tr>
</table></td></tr></table></body></html>'''
    message.add_alternative(html, subtype="html")


def send_notification_email(*, recipient, notifications):
    if not smtp_configured(): raise SMTPConfigurationError("Email sending is not configured.")
    settings = _settings()
    message = EmailMessage()
    message["From"] = formataddr(("TalentSouk", settings["user"]))
    message["To"] = recipient
    message["Subject"] = "TalentSouk · " + (str(notifications[0]["title"])[:140] if len(notifications)==1 else str(len(notifications))+" new notifications")
    message["Message-ID"] = make_msgid()
    plain = ["TalentSouk notifications"]
    content = []
    for row in notifications:
        page = notification_page(row["url"])
        link = app_link(row["url"])
        plain.append(page+" · "+row["title"]+"\n"+row["message"]+"\n"+link)
        content.append('<div style="border-bottom:1px solid #D8C7D8;padding:14px 0"><small>'+escape(page)+'</small><h2 style="font-size:18px">'+escape(row["title"])+'</h2><p>'+escape(row["message"])+'</p><a href="'+escape(link,quote=True)+'">View in TalentSouk</a></div>')
    plain.append("Manage email notifications: "+app_link("/settings"))
    message.set_content("\n\n".join(plain))
    add_branded_html(message, "".join(content)+'<p><a href="'+escape(app_link("/settings"),quote=True)+'">Manage email notifications</a></p>', notification_page(notifications[0]["url"]) if len(notifications)==1 else "Notifications", notifications[0]["url"] if len(notifications)==1 else "/home")
    _deliver(message)
    return message["Message-ID"]
