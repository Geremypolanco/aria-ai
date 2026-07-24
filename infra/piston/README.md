# Piston → ARIA code execution

Lets ARIA (via the Artifacts panel's **Run** button, `POST /api/v1/code/execute`)
actually run code and see real stdout/stderr/exit codes, instead of only ever
writing code nobody executes.

## Why self-hosted, not the public API

Piston's public API (`emkc.org`) now requires manual authorization from its
maintainer, granted only for **non-commercial, low-volume, mostly educational**
use. ARIA is a paid product, so it doesn't qualify — self-hosting is the only
path available to us. This isn't a downgrade in safety: code always executes
on this separate instance, never inside ARIA's own container.

## 1. Deploy Piston

```bash
cd infra/piston
docker compose up -d api
```

`privileged: true` in the compose file is required by Piston itself (it needs
it to set up its own internal per-language sandboxing). Run this on its own
VM/host, not colocated with anything sensitive — same principle as any
container you'd let execute arbitrary untrusted code.

## 2. Install language runtimes

None are bundled by default. From a checkout of the
[Piston repo](https://github.com/engineer-man/piston) (only the `cli/`
folder is needed):

```bash
cd cli && npm i && cd -
cli/index.js ppman list                 # see what's available
cli/index.js ppman install python
cli/index.js ppman install javascript
# repeat for whichever languages you want ARIA's users to run
```

## 3. Point ARIA at it

```bash
fly secrets set PISTON_API_URL="http://<your-host>:2000" -a aria-ai
```

No trailing `/api/v2` — `code_sandbox.py` appends that itself. Once set:

```bash
curl -X POST https://aria-ai.fly.dev/api/v1/code/execute \
  -H 'Content-Type: application/json' -H 'Cookie: <your session cookie>' \
  -d '{"language":"python","code":"print(1+1)"}'
```

should return `{"success": true, "stdout": "2\n", ...}`.

## Notes

- `code_sandbox.py` resolves whatever language name/alias you pass (`"py"`,
  `"js"`, `"node"`, ...) against this instance's own `/api/v2/runtimes` list —
  it never hardcodes a name/version mapping, so installing a new language
  here makes it usable immediately, no ARIA code changes needed.
- `/api/v1/code/execute` requires a signed-in user and is rate-limited
  (10/min) separately from chat — running code is heavier and more abusable
  than a text reply.
