# Render deployment (current target)

`render.yaml` describes one Docker web service in Frankfurt with one 1 GB persistent disk mounted at `/data`, the existing Supabase database, HTTPS session cookies and `/api/health`. It is a PAID configuration; review the dashboard quote before creating it. Current published minimum compute is $7/month plus $0.25/GB-month for disk, excluding taxes and usage overages. No service is created by writing this file.

Connect a private Git repository containing this directory as its root. Keep `.env`, uploads, SQLite databases, backups and runtime tools excluded. If the repository contains the outer workspace instead, explicitly set the service root directory to this application folder. Use Docker and the included Dockerfile. Add existing SECRET_KEY and DATABASE_URL privately, followed by SMTP and enabled AI/job-provider settings. Set APP_BASE_URL to the generated public HTTPS address before testing verification mail. Preserve SECRET_KEY when moving encrypted Gmail credentials. Do not create another database.

Before opening the site to existing users, transfer private `uploads/` into `/data/uploads/` using Render's authenticated service shell/SSH. Never commit these files or put them in a public image. Verify the attached disk, database health, email verification, CV downloads, profile photos, free Photo Studio and logout. Update Gmail OAuth redirect origin if enabled. Existing cloud database rows do not copy local files automatically.

Docker has not been built locally because the Docker daemon is unavailable. The Render build and public smoke checks must still be completed.

---

# Railway deployment

The application is prepared for one Docker service with one persistent volume and the existing Supabase PostgreSQL database. The build copies only source, static assets and public catalog CSVs; local accounts, uploads, backups and .env are excluded.

1. Sign in to Railway and create an empty project and service. Upload this project using Railway CLI from this directory (not the outer workspace). No public Git repository is required.
2. Attach a persistent volume at `/data` BEFORE the first deployment. Set `STORAGE_ROOT=/data`. Keep one replica. Never deploy uploads to ephemeral storage.
3. Add private service variables using the current local configuration: `SECRET_KEY` (preserve the current value if migrating encrypted Gmail credentials), `DATABASE_BACKEND=postgres`, `DATABASE_URL`, `DATABASE_SCHEMA=talentsouk`, `SESSION_COOKIE_SECURE=1`, `FLASK_DEBUG=0`. Do not publish these values or commit .env.
4. Add SMTP_HOST, SMTP_PORT, SMTP_USER, SMTP_PASSWORD, SMTP_FROM_NAME, SMTP_USE_TLS from the existing configuration. Email ownership verification needs working SMTP before new users can enter. Copy the configured Groq/NVIDIA/Jooble keys if those features are enabled. Gemini portraits remain optional; free Photo Studio needs no key.
5. Deploy. The Dockerfile uses Gunicorn, one process and four threads; Railway sets PORT. `/api/health` must return 200.
6. Generate a public Railway domain. Set `APP_BASE_URL` to that exact HTTPS URL and redeploy. Update any Gmail OAuth authorized redirect URI to the application's existing callback under this origin before testing Gmail.
7. Transfer the existing `uploads/` directory privately into `/data/uploads/` before sharing the site with existing users. Database rows refer to those filenames; never put private files inside the image or a public repository. Keep a backup of both Supabase and the volume.
8. Verify login, verification email, companies, uploaded CV download, existing profile photo, free Photo Studio save/use/download and logout over HTTPS. Do not send real applications during smoke checks.

## Costs and account access
Railway may offer trial credits subject to eligibility. An ongoing service and its volume consume resources; confirm the displayed account plan and cost before upgrading. No paid plan is enabled by these files. Deployment is not complete until the external service is running, private files have been migrated and public smoke checks pass.
