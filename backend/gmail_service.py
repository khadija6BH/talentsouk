"""Minimal Gmail OAuth/send service using only the gmail.send permission."""

import base64
import hashlib
import json
import os
import secrets
import urllib.error
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage

from cryptography.fernet import Fernet, InvalidToken


GMAIL_SEND_SCOPE = "https://www.googleapis.com/auth/gmail.send"
GOOGLE_IDENTITY_SCOPES = ("openid", "email")
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GMAIL_SEND_URL = "https://gmail.googleapis.com/gmail/v1/users/me/messages/send"


class GmailServiceError(RuntimeError):
    pass


def gmail_config():
    return {
        "client_id": os.getenv("GOOGLE_OAUTH_CLIENT_ID", "").strip(),
        "client_secret": os.getenv("GOOGLE_OAUTH_CLIENT_SECRET", "").strip(),
        "redirect_uri": os.getenv("GOOGLE_OAUTH_REDIRECT_URI", "").strip(),
    }


def gmail_is_configured():
    config = gmail_config()
    return all(config.values())


def create_oauth_state():
    return secrets.token_urlsafe(32)


def authorization_url(state):
    config = gmail_config()
    if not gmail_is_configured():
        raise GmailServiceError("Gmail OAuth is not configured on this application.")
    query = urllib.parse.urlencode({
        "client_id": config["client_id"],
        "redirect_uri": config["redirect_uri"],
        "response_type": "code",
        "scope": " ".join((GMAIL_SEND_SCOPE, *GOOGLE_IDENTITY_SCOPES)),
        "access_type": "offline",
        "prompt": "consent",
        "state": state,
    })
    return f"{GOOGLE_AUTH_URL}?{query}"


def _post_form(url, values):
    request = urllib.request.Request(
        url,
        data=urllib.parse.urlencode(values).encode("utf-8"),
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            return json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise GmailServiceError("Gmail authorization is temporarily unavailable.") from exc


def exchange_authorization_code(code):
    config = gmail_config()
    if not gmail_is_configured():
        raise GmailServiceError("Gmail OAuth is not configured on this application.")
    token = _post_form(GOOGLE_TOKEN_URL, {
        "code": code,
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "redirect_uri": config["redirect_uri"],
        "grant_type": "authorization_code",
    })
    if not token.get("access_token"):
        raise GmailServiceError("Google did not return a usable Gmail access token.")
    granted = set(str(token.get("scope") or "").split())
    if GMAIL_SEND_SCOPE not in granted:
        raise GmailServiceError("The Gmail send permission was not granted.")
    token["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=int(token.get("expires_in", 3600)))
    ).isoformat()
    return token


def verified_google_identity(token):
    """Validate Google's ID token and return its verified Gmail identity."""
    id_token = str((token or {}).get("id_token") or "").strip()
    if not id_token:
        raise GmailServiceError("Google did not return a verified account identity.")
    url = "https://oauth2.googleapis.com/tokeninfo?" + urllib.parse.urlencode({"id_token": id_token})
    try:
        with urllib.request.urlopen(url, timeout=30) as response:
            identity = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise GmailServiceError("Google account verification is temporarily unavailable.") from exc
    config = gmail_config()
    if str(identity.get("aud") or "") != config["client_id"]:
        raise GmailServiceError("Google returned an identity for another application.")
    email = str(identity.get("email") or "").strip().lower()
    verified = str(identity.get("email_verified") or "").lower() == "true"
    if not email or not verified:
        raise GmailServiceError("Connect a Google account with a verified Gmail address.")
    return {"email": email, "email_verified": True, "subject": identity.get("sub", "")}


def _cipher(secret_key):
    if not secret_key:
        raise GmailServiceError("Application token encryption is not configured.")
    key = base64.urlsafe_b64encode(hashlib.sha256(secret_key.encode("utf-8")).digest())
    return Fernet(key)


def encrypt_token(token, secret_key):
    payload = json.dumps(token, separators=(",", ":")).encode("utf-8")
    return _cipher(secret_key).encrypt(payload).decode("ascii")


def decrypt_token(encrypted, secret_key):
    try:
        payload = _cipher(secret_key).decrypt(encrypted.encode("ascii"))
        return json.loads(payload.decode("utf-8"))
    except (InvalidToken, ValueError, json.JSONDecodeError) as exc:
        raise GmailServiceError("The saved Gmail connection is invalid. Reconnect Gmail.") from exc


def refresh_access_token(token):
    refresh_token = token.get("refresh_token")
    if not refresh_token:
        raise GmailServiceError("Reconnect Gmail to continue sending.")
    config = gmail_config()
    refreshed = _post_form(GOOGLE_TOKEN_URL, {
        "client_id": config["client_id"],
        "client_secret": config["client_secret"],
        "refresh_token": refresh_token,
        "grant_type": "refresh_token",
    })
    if not refreshed.get("access_token"):
        raise GmailServiceError("Gmail authorization expired. Reconnect Gmail.")
    token.update(refreshed)
    token["refresh_token"] = refresh_token
    token["expires_at"] = (
        datetime.now(timezone.utc) + timedelta(seconds=int(refreshed.get("expires_in", 3600)))
    ).isoformat()
    return token


def ensure_access_token(token):
    try:
        expires_at = datetime.fromisoformat(str(token.get("expires_at") or ""))
    except ValueError:
        expires_at = datetime.min.replace(tzinfo=timezone.utc)
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=timezone.utc)
    if expires_at <= datetime.now(timezone.utc) + timedelta(seconds=60):
        return refresh_access_token(token), True
    return token, False


def build_message(recipient, subject, body, attachments):
    message = EmailMessage()
    message["To"] = recipient
    message["Subject"] = subject
    message.set_content(body)
    for filename, mime_type, content in attachments:
        main_type, sub_type = (mime_type or "application/octet-stream").split("/", 1)
        message.add_attachment(content, maintype=main_type, subtype=sub_type, filename=filename)
    return base64.urlsafe_b64encode(message.as_bytes()).decode("ascii")


def send_message(access_token, raw_message):
    request = urllib.request.Request(
        GMAIL_SEND_URL,
        data=json.dumps({"raw": raw_message}).encode("utf-8"),
        headers={
            "Authorization": f"Bearer {access_token}",
            "Content-Type": "application/json",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            result = json.loads(response.read().decode("utf-8"))
    except urllib.error.HTTPError as exc:
        if exc.code in {401, 403}:
            raise GmailServiceError("Gmail authorization failed. Reconnect Gmail and try again.") from exc
        raise GmailServiceError("Gmail could not send this application.") from exc
    except (urllib.error.URLError, json.JSONDecodeError) as exc:
        raise GmailServiceError("Gmail is temporarily unavailable. The application was not marked as sent.") from exc
    if not result.get("id"):
        raise GmailServiceError("Gmail did not confirm that the message was sent.")
    return result
