# Current target: Back4app Containers Free (no card)

Render was not activated: this account requested card verification even with Free selected. The user requires no card and no paid subscription. Back4app's official Containers pricing explicitly offers a no-card Free container. Use that plan only.

Source: private GitHub repository khadija6BH/talentsouk, main branch, repository root, included Dockerfile. The container exposes 8080 and Gunicorn reads PORT=8080. Select one free container; no paid disk or new database is needed. The actual container build, memory use and public HTTPS smoke checks remain to be verified.

Use the existing Supabase PostgreSQL connection and private talentsouk-private storage bucket. Eight existing upload files were migrated and checksum-verified, and recovery with an empty local cache passed. Keep local originals as backups. UPLOAD_STORAGE=supabase makes /data/uploads a disposable cache. The service-role storage key stays only in server secrets; keep the bucket private with no public policies.

Copy approved application settings into server secrets: existing SECRET_KEY, DATABASE_URL, DATABASE_BACKEND=postgres, DATABASE_SCHEMA, AI/job-provider keys, SUPABASE_URL, SUPABASE_STORAGE_BUCKET, SUPABASE_STORAGE_KEY, UPLOAD_STORAGE=supabase, STORAGE_ROOT=/data, SESSION_COOKIE_SECURE=1, FLASK_DEBUG=0 and PORT=8080. Preserve SECRET_KEY for encrypted Gmail credentials. After the public URL is allocated, set APP_BASE_URL to that exact HTTPS origin. Gmail OAuth callback settings require their own public origin if enabled.

Brevo HTTPS email support is implemented and mocked tests pass. Account phone verification, a verified sender and a restricted Transactional email API key must be configured before enabling registration. Set EMAIL_PROVIDER=brevo, BREVO_API_KEY, BREVO_SENDER_EMAIL and SMTP_FROM_NAME=TalentSouk. Creating a new key and transferring server secrets to Back4app require the user's specific authorization. Do not send real test emails or applications without instructions.

Keep RADAR_AUTO_SYNC=0 initially. Free containers may sleep: background notifications are not continuous while the app is stopped. Supabase Free quotas also apply. Check /api/health, login, registration verification, private file downloads, profile pictures, free Photo Studio save/use/download, cold restart recovery and logout before reporting the deployment ready. Do not claim a live URL before the host reports it ready.

## Optional Render configuration
render.yaml remains a free-only alternative, without a disk. Do not activate paid services or card verification without explicit instructions. The existing Render draft was not deployed.
