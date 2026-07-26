# Runbook — Fishing Log

Operational procedures for whoever runs this app. Written for the owner, not
for a platform team: this is one Streamlit app on Community Cloud with one
Supabase database behind it.

Read [CLAUDE.md](CLAUDE.md) for how the code is put together. This file is only
about running it.

---

## The one thing to know first

**There is no server-side backup.** Supabase's own point-in-time recovery is not
enabled on the free tier. If the database is lost or a member deletes their
trips, the only way back is a backup ZIP somebody downloaded. Everything below
assumes that.

---

## Releasing

The deploy branch is `cloud-version`. Streamlit Community Cloud redeploys on
push, so **pushing is deploying** — there is no separate deploy step and no
approval gate.

1. Work on a branch, never directly on `cloud-version`.
2. `.venv/Scripts/python.exe -m pytest tests -q` — must be green.
3. `.venv/Scripts/python.exe -m pip_audit --requirement requirements.lock.txt`
   — must report no known vulnerabilities.
4. Run the app locally and click through Dashboard, Log a Session, Browse,
   Analytics, Map and Export. The test suite does not cover rendering.
5. Bump `APP_BUILD` in `app.py`. It shows at the bottom of the sidebar and is
   the only way to tell at a glance which build Cloud is actually serving.
6. Merge to `cloud-version` and push.
7. Watch the app come back up. Confirm the sidebar shows the new `APP_BUILD`.
8. **Sign in with Google.** Local development uses the email form, so the OIDC
   callback is never exercised until it is in production.

### Migrations

Schema changes live in `migrations/` and are applied **by hand, before** the
code that needs them is deployed. The app does not migrate itself — it checks
at startup and names the file to run if a column is missing.

Apply as `fishing_deploy` (or `postgres`), never as `fishing_app`, which has no
DDL rights on purpose.

---

## Rolling back

Cloud serves whatever is on `cloud-version`. To roll back, put the previous
commit back on that branch:

```bash
git revert <bad-commit> && git push
```

Prefer `revert` over force-pushing — it keeps the history readable and does not
race with anything else that may have been pushed.

**Rolling back code does not roll back a migration.** Migrations are written to
be additive (a new nullable column, a backfill) so older code keeps working
against a newer schema. Keep it that way: never make a migration that drops or
renames a column the previous release still reads.

If a release has to be pulled and a migration was part of it, roll back the code
first and leave the schema alone. A column nobody reads is harmless.

---

## Rotating credentials

Do this on any suspicion of exposure, and whenever someone who had access stops
needing it. `.streamlit/secrets.toml` is git-ignored, but it is a plain file on
a laptop — treat any tool that has read it as having read the password.

**Database (`database_url`)**

1. Supabase → Settings → Database → **Reset database password**.
2. Update `database_url` in Streamlit Cloud secrets.
3. Update `.streamlit/secrets.toml` locally.
4. Restart the Cloud app and confirm trips still load.

The runtime role should be `fishing_app`, not `postgres` — see
`migrations/001_rls_least_privilege.sql`. Rotating `fishing_app`'s password is
an `ALTER ROLE fishing_app PASSWORD '…'` as `postgres`.

**Google OIDC (`[auth.google]`)**

1. Google Cloud Console → Credentials → the OAuth client → reset the secret.
2. Update `client_secret` in Cloud secrets.
3. **Sign in immediately to confirm.** A wrong secret here fails only at the
   callback, which nothing local exercises.

**`cookie_secret`** — changing it signs everybody out. Harmless, occasionally
useful.

---

## When something is wrong

### A member reports an error with a reference code

Every failed write shows the angler a reference like `A3F9C21B`. Search the
Cloud logs for it:

```
correlation_id=A3F9C21B
```

That line carries the operation, scalar context, and the full traceback.
Nothing was written — failed writes roll back whole (see CR-4), so it is always
safe to tell them to try again.

### The sidebar shows a failure alert

The owner-only **📈 Health** panel counts failures in a rolling 15-minute
window and raises an alert at three. It also shows connection-pool usage.

- **Pool exhausted** → too many concurrent sessions for `pool_size=5,
  max_overflow=10` in `database.get_engine`. Raise it, or move off Community
  Cloud. Check whether Supabase's own connection limit is the real ceiling.
- **Repeated write failures** → usually Supabase being unreachable. Check the
  Supabase dashboard before changing anything here.

### The app shows "Sign-in is temporarily unavailable"

Authentication is failing closed, which is deliberate — it will not fall back
to letting people type an email. Causes, in order of likelihood:

1. `[auth]` / `[auth.google]` missing or malformed in Cloud secrets.
2. The OAuth client secret was rotated in Google but not here.
3. An Authlib upgrade broke the callback — see the Authlib note in CLAUDE.md;
   roll back to the previously pinned version.

Grep the logs for `[auth]`.

### The app shows "Schema is behind"

A migration in `migrations/` has not been applied. The message names the file.
Apply it as `fishing_deploy`.

### The app is asleep

Community Cloud hibernates after 12 hours without traffic. First visitor wakes
it and waits. This is expected on the free tier and is not a fault. If the club
needs it always-on, that is the hosting decision, not a bug to fix.

---

## Incident procedure

1. **Write down the time and what you saw.** Cloud logs are not retained long.
2. **Decide: is data at risk, or only availability?** Availability can wait.
   Data cannot.
3. **If data is at risk, stop writes** — take the app down in Cloud rather than
   let it keep half-working. A dark app loses nothing; a broken one can.
4. **Check Supabase first.** Most failures here are the database being
   unreachable, not the app.
5. **Roll back if a release is implicated.** Do not debug forward on
   production.
6. **Tell the club** what happened, whether their trips were affected, and
   whether they should restore from their own backups.
7. **Write down the cause afterwards.** Add it here if it can recur.

### If member data is lost

There is no server-side restore. Be honest and quick:

1. Establish what is gone and for whom.
2. Ask affected members to restore from their most recent backup ZIP via
   **Export → Restore from backup**. Restore is idempotent — restoring twice
   does not duplicate trips.
3. Anything nobody has a ZIP for is gone. Say so plainly.
4. Then fix the reason there was no backup.

---

## Health checks

- **Liveness:** `GET /_stcore/health` returns `200 ok`.
- **Auth:** sign in with Google. Nothing local covers the OIDC callback.
- **Data:** open the demo and confirm the dashboard shows trips.
- **Isolation:** with `fishing_app` credentials, in a transaction with no
  `app.user_email` set, `SELECT count(*) FROM sessions` must return **0**. See
  the verification block at the end of
  `migrations/001_rls_least_privilege.sql`. This is the check that proves
  members cannot see each other's data.

---

## What is not covered

Deliberately, so nobody assumes otherwise:

- **No uptime monitoring.** Nothing pages anyone. The health panel is only
  visible when the owner is looking at it.
- **No log retention or search** beyond what Community Cloud keeps.
- **No staging environment yet.** The review's concurrency test needs one — a
  second Supabase project with synthetic data. Never load-test production.
- **No automated database backup.** Members' own ZIPs are the only copies.
