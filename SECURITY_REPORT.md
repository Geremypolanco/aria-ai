# 🛡️ ARIA — Security Audit & Remediation Report

**Scope:** full repository — secret scanning, dependency audit (SCA), and SAST
(OWASP Top 10) on the FastAPI backend + server-rendered frontend.
**Outcome:** 1 Critical, 2 High, 3 Medium and 3 Low findings — **all remediated**.

---

## TL;DR

| Sev | Finding | Status |
|-----|---------|--------|
| 🔴 Critical | Session cookies signed with a **hardcoded public fallback key** → anyone could forge any user (and become owner/admin) | ✅ Fixed |
| 🟠 High | **Unauthenticated** powerful API endpoints (`/api/v1/run`, `/code`, `/research`, anon `/chat`) — Broken Access Control | ✅ Fixed |
| 🟠 High | `aiohttp 3.10.5` — **dozens of CVEs** | ✅ Bumped to 3.14.1 |
| 🟡 Medium | Sessions **never expired** (forever-valid cookies) | ✅ Fixed (30-day max age) |
| 🟡 Medium | **No rate limiting** on public/expensive endpoints | ✅ Added |
| 🟡 Medium | OAuth `state` **not bound to the browser** (weak CSRF) | ✅ Fixed (state cookie + freshness) |
| 🟢 Low | `__PROFILE_JSON__` embedded in `<script>` without escaping `<` (XSS defence-in-depth) | ✅ Hardened |
| 🟢 Low | Inline `secret = "webhook_secret"` placeholder | ✅ Moved to env (`WEBHOOK_SECRET`) |
| 🟢 Low | Incomplete `.env.example` | ✅ Completed |
| ⚪ Info | `starlette` / `protobuf` / `mcp` CVEs constrained by pinned parents | ⚠️ Documented (see below) |

---

## 1. Secret scanning ✅ clean

- **No** hardcoded API keys, tokens, DB credentials or passwords in source.
- **No** `.env` file committed to git.
- All secrets load from the environment via `apps/core/config.py` (pydantic `BaseSettings`).
- The only offender was a placeholder `secret = "webhook_secret"` in
  `apps/core/integrations/advanced_integrations.py` → now reads `settings.WEBHOOK_SECRET`.
- `.env.example` was completed with every secret the app reads (see file).

## 2. Dependency audit (SCA) — `pip-audit`

**Fixed:**
- `aiohttp 3.10.5 → 3.14.1` — cleared **~30 CVEs** (RCE-adjacent request smuggling,
  parser and multipart issues). Verified: requirements resolve, `aiohttp` re-audits
  **clean**, app imports.

**Constrained (documented, not blindly bumped):**
- `starlette 0.38.6`, `protobuf 4.25.9`, `mcp 1.12.4` carry CVEs but are pinned by
  `fastapi==0.115.0`, `opentelemetry-*`, and our `pydantic==2.8.2` respectively.
  Bumping them safely requires a **coordinated** FastAPI / OpenTelemetry / pydantic
  upgrade, which is a separate, test-heavy change — tracked as follow-up rather than
  risking a breaking change in this security pass.
- `pytest`, `black` advisories are **dev/CI-only** (not shipped) — deferred to avoid
  CI formatting churn.

## 3. SAST (OWASP Top 10)

### 🔴 A07 Identification & Authentication — Session forgery (Critical)
`apps/core/auth.py` `_secret()` fell back to the **literal public string**
`"aria-session-fallback"` when no admin/API key was configured. Since the `aria_user`
session cookie is an HMAC signed with this key — and the owner/admin check trusts the
email **inside** that cookie — anyone could forge a cookie and impersonate any user,
including the owner, gaining `/admin`.
**Fix:** new dedicated `SESSION_SECRET` (config), preference chain
`SESSION_SECRET → ADMIN_PASSWORD → ARIA_API_KEY`, and — critically — a **random
per-process ephemeral key** if none is set (with a startup warning). The public
constant is **gone**.

### 🟠 A01 Broken Access Control (High)
`/api/v1/run` (drives the autonomous **execution engine**), `/api/v1/code`,
`/api/v1/research` had **no authentication**; `/api/v1/chat` served anonymous callers
with **no quota** → resource/cost abuse and unauthorized autonomous actions.
**Fix:** `/api/v1/run` is now **owner-only** (403 otherwise); `/code` + `/research`
require a signed-in user; `/chat` requires sign-in. All are rate-limited.

### 🟡 A07 Session management — no expiry (Medium)
`verify_user` never checked the token's `t` timestamp → cookies valid forever.
**Fix:** tokens older than **30 days** are rejected.

### 🟡 A05 Security misconfiguration — no rate limiting (Medium)
**Fix:** added a dependency-free, in-process sliding-window limiter keyed by client IP
(`chat` 30/min, `code`/`research` 20/min, `run` 10/min).

### 🟡 A01 CSRF — OAuth state not bound (Medium)
The OAuth `state` was signed but not tied to the initiating browser and had no expiry.
**Fix:** `state` is now stored in a short-lived (`httponly, secure, samesite=lax`,
10-min) cookie and compared on callback, plus a freshness check.

### 🟢 A03 Injection / XSS
- **No SQL injection:** the Supabase layer uses the parameterized query builder
  (`.table().select().eq().execute()`), never raw string SQL.
- **Reflected/stored XSS:** user `name/work/goals` substituted into the dashboard HTML
  are sanitized by `_safe_name` (strips `< > " ' \\ \` \n \t`). **Hardened further:**
  `__PROFILE_JSON__` embedded in an inline `<script>` now escapes `< > &` and the
  U+2028/U+2029 separators so it can't break out of the script context.

### ✅ Already solid (verified, no change)
- Session + admin cookies set `httponly`, `secure`, `samesite=lax`.
- `/admin` is gated by `_is_admin`; admin login uses timing-safe `hmac.compare_digest`
  and stays locked until `ADMIN_PASSWORD` is configured.
- No `eval` / `exec` / `os.system` / `pickle.loads` on untrusted input in the request path.

---

## Files changed

| File | Change |
|------|--------|
| `apps/core/auth.py` | Removed public fallback key; ephemeral secret; session expiry; OAuth-state binding + freshness |
| `apps/core/config.py` | Added `SESSION_SECRET`, `WEBHOOK_SECRET` |
| `apps/core/main.py` | Auth gates on `/api/v1/run` (owner) `/code` `/research` `/chat`; in-process rate limiter; OAuth-state cookie wiring; `_json_for_script` XSS hardening |
| `apps/core/integrations/advanced_integrations.py` | Webhook secret from `WEBHOOK_SECRET` env |
| `apps/core/requirements.txt` | `aiohttp 3.10.5 → 3.14.1` |
| `.env.example` | Completed with all secrets incl. `SESSION_SECRET` |
| `tests/unit/test_auth_security.py` | New — sign/verify, expiry, no-public-key, OAuth-state binding (7 tests) |

## Verification
- `aiohttp` re-audits **clean**; full requirements resolve.
- `apps.core.main` + `apps.core.auth` import; **7/7** new auth security tests pass.
- `ruff` + `black` clean on changed files.

## Recommended operational follow-ups (not code)
1. **Set `SESSION_SECRET`** (and `ADMIN_PASSWORD`) in production — otherwise sessions
   are ephemeral per process.
2. Plan a coordinated **FastAPI + OpenTelemetry + pydantic/mcp** upgrade to clear the
   remaining constrained CVEs.
3. Consider a shared (Redis) rate-limit store for multi-instance deployments.
