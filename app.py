"""Vercel's Flask entry point; keep the local backend entry point unchanged."""
import os

if os.environ.get("VERCEL") == "1":
    # Function filesystems are read-only except for their disposable /tmp cache.
    os.environ.setdefault("STORAGE_ROOT", "/tmp/talentsouk")
    os.environ.setdefault("DATABASE_BACKEND", "postgres")
    os.environ.setdefault("UPLOAD_STORAGE", "supabase")
    os.environ.setdefault("SESSION_COOKIE_SECURE", "1")
    # A function may stop after its response; background threads are not a queue.
    os.environ["NOTIFICATION_WORKER"] = "0"
    os.environ["RADAR_AUTO_SYNC"] = "0"
    origin = os.environ.get("VERCEL_PROJECT_PRODUCTION_URL") or os.environ.get("VERCEL_URL")
    if origin:
        os.environ.setdefault("APP_BASE_URL", "https://" + origin)

from backend.app import app  # noqa: E402,F401
