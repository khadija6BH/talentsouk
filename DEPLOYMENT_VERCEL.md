# Vercel deployment — prepared, not yet deployed

Use the Hobby plan only. Import the private GitHub repository
`khadija6BH/talentsouk`, with the repository root and Flask framework preset.
The root `app.py` exports the existing Flask app. The build command copies
`frontend/static/` to `public/static/` for CDN delivery. Python is pinned to 3.12.

## Private environment settings

Preserve the existing `SECRET_KEY` and `DATABASE_URL`. Configure:

```dotenv
DATABASE_BACKEND=postgres
DATABASE_SCHEMA=talentsouk
UPLOAD_STORAGE=supabase
SUPABASE_URL=https://jmmwqrqbmxybjmqnundd.supabase.co
SUPABASE_STORAGE_BUCKET=talentsouk-private
SUPABASE_STORAGE_KEY=<existing server-side key>
EMAIL_PROVIDER=brevo
BREVO_API_KEY=<restricted Transactional email key>
BREVO_SENDER_EMAIL=<existing verified sender>
SMTP_FROM_NAME=TalentSouk
STORAGE_ROOT=/tmp/talentsouk
SESSION_COOKIE_SECURE=1
FLASK_DEBUG=0
NOTIFICATION_WORKER=0
RADAR_AUTO_SYNC=0
```

Enter actual keys only in the project's server-side environment settings;
never commit them. Set `APP_BASE_URL` to the final public HTTPS origin when
available. The entry point otherwise uses Vercel's production domain variable.
Optional AI and job-provider keys require separate configuration.

## Runtime limits

Uploads live in the private Supabase bucket; `/tmp` is only a disposable cache.
Vercel functions do not provide a continuous notification/radar process, so
both background workers are disabled. Inline account verification and password
reset email still use the Brevo HTTPS path. Automatic background mail requires
a separate scheduling design; none is enabled by this deployment.

Vercel's function request-body limit can reject uploads below the app's local
5 MB ceiling. Verify actual CV upload limits on the deployed service before
claiming feature parity. Test `/api/health`, static assets, login redirects,
authentication, and private file downloads after the deployment becomes ready.

Official reference: https://vercel.com/docs/frameworks/backend/flask
