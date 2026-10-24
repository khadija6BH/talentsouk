# Administration and support

The protected dashboard is `/admin`. The existing, verified
`talentsouk68@gmail.com` account is the explicitly approved administrator.
Privileges are stored by user ID in `admin_members`; session fields, signup
inputs and email changes cannot grant membership. Verified email ownership is
required on every admin request. Removing membership revokes existing sessions'
admin access immediately. No account deletion, password viewing, role editor,
or account-data export is exposed by the dashboard.

## Deployment

Before deploying this code to an existing PostgreSQL installation, run:

```text
python scripts/migrate_admin.py --admin-email talentsouk68@gmail.com
```

This is an additive migration. It does not change existing user credentials,
CVs, application records, or verification state. It enables row level security
on all operations tables with no client-side access policies; server-side
database access continues through the existing backend role. SQLite databases
create the tables during the usual initialization.

## Features and interpretation

- Account totals, verified accounts, registration trends, recent successful
  sign-ins and last signed-in activity. Activity writes are throttled to once
  per 15 minutes per account. These values are not an online-presence monitor.
- Sign-in history begins with this release; older sign-ins are not invented.
  Registrations use existing account creation dates. Dates are UTC.
- Optional page-view counters use only the registered endpoint name and date,
  only for signed-in users with `analytics_enabled`. Counters contain no user
  ID or IP address and are pruned to 90 days on successful sign-ins.
- `/support` lets verified users submit up to five reports per hour, inspect
  their own reports and read the administrator's response. Responses appear
  in the app; saving one does not send email. Private admin notes never appear
  in the user view. POST forms require a session-bound CSRF token.
- Incidents group server-side HTTP 5xx errors by route template, error class
  and status. They store counts, timestamps and a support reference, not raw
  URLs, query strings, exception messages, credentials or stack traces. The
  response includes `X-Support-Reference`. A new occurrence reopens a group.
- Support status changes, incident changes and initial admin grants are
  recorded in an audit log. Resolving an incident records the investigation
  outcome; it does not modify application code or guarantee a bug is fixed.
- Membership, activity and support reports cascade when their owning account
  is deleted. Audit actor IDs are cleared; anonymous aggregate counts remain.

Focused security tests are in `backend/tests/test_admin_operations.py` and
cover access control, ownership, CSRF, escaping, rate limits, opt-in analytics,
revocation, deletion cascades and redacted incident capture.
