# SCALE_ARCH.md — ARIA Distributed Scaling Architecture

How ARIA processes missions asynchronously and scales horizontally on Fly.dev.

This document describes the async, fault-tolerant mission pipeline in
`apps/core/scale/` and how to run it as separate web + worker fleets. Every
primitive ships with a **Redis backend** (for real horizontal scale) **and an
in-process fallback** (so the exact same code runs in a single container and in
CI with zero external dependencies).

> **The one rule that governs everything below:** the web tier and the worker
> tier only share state through **Redis**. Without `REDIS_URL`, each container
> has its own in-memory queue / bucket / log bus and cannot see the others. So
> "scale out the workers" == "provision Redis first". Until then a single
> container self-processes and is fully functional.

---

## 1. Request path (why it stays fast under load)

```
                    HTTP 202 (instant)
  Browser ───POST /api/v1/missions──▶  Web (producer)
     ▲                                    │ enqueue(task)
     │ WS /ws/logs/{id}                   ▼
     │                              ┌─────────────┐
     │                              │  Mission     │   Redis LIST  (or in-mem deque)
     │                              │  Queue       │
     │                              └─────────────┘
     │                                    │ dequeue (BRPOP)
     │  live logs (Pub/Sub)               ▼
     └──────────────────────────────  Worker (consumer)
                                          │  · rate-limited outbound LLM calls
                                          │  · state: processing → completed|failed
                                          │  · self-healing retries
                                          ▼
                                   Mission status (Redis hash / in-mem dict)
```

The web endpoint never blocks on the LLM. It validates, enqueues, and returns
`202 Accepted` with a `task_id`, a `status_url` to poll, and a `logs_ws` to
stream. All heavy work happens in stateless workers.

---

## 2. The four primitives (`apps/core/scale/`)

### 2.1 Event-driven task queue — `task_queue.py`
- **Producer** (`POST /api/v1/missions`) validates + `enqueue()`s and returns
  **HTTP 202** immediately. **Consumers** (workers) `dequeue()` and run.
- Redis backend: `LPUSH`/`BRPOP` on `aria:mq:pending` + a per-task status key
  `aria:mq:status:{id}` (24h TTL). In-process backend: a module-level `deque`
  polled by `dequeue()` — deliberately **loop-agnostic** so it survives pytest's
  per-test event loops.
- State machine stored in the cache: `queued → processing → completed | failed`.

### 2.2 Stateless background workers — `worker.py`
- `python -m apps.core.scale.worker` — no local state; everything lives in Redis,
  so you can run N of them and kill/restart any at will.
- Per task: `set_status(processing)` → paced LLM call → `completed`/`failed`,
  wrapped in **self-healing retries** (`apps/core/ops/self_healing.py`,
  short schedule `5s / 15s / 30s` for missions; transient errors only).
- One bad task can never kill the loop (each is isolated in try/except).

### 2.3 Smart rate-limiting queue — `rate_limiter.py`
- A **token bucket** per provider (`anthropic`, `openai`, `groq`, …). Bursts up
  to `capacity` are allowed; sustained rate is capped at `refill_per_sec`.
- Excess calls are **paced (awaited), not rejected** — we respect provider
  quotas transparently instead of throwing overflow errors.
- `TokenBucket` (in-process, per worker) for single-container; `RedisTokenBucket`
  (atomic Lua script) to share one global quota across the whole worker fleet.

### 2.4 Pub/Sub live logs — `log_bus.py`
- Workers `publish()` each log line to `aria:logs:{task_id}`. The web server's
  `WS /ws/logs/{task_id}` `subscribe()`s and streams to the browser.
- Redis **Pub/Sub** when configured (fan-out across containers), else an
  in-process `asyncio.Queue` fan-out. Live logs never touch the durable DB, so
  they cost near-zero CPU/memory.

---

## 3. Horizontal scaling on Fly.dev

### 3.0 Single container (today, no Redis)
Works out of the box: the web machine auto-starts an **in-process worker** when
`REDIS_URL` is unset, draining its own in-memory queue. Good for dev and low
traffic. `fly scale count 1`. Nothing else to configure.

### 3.1 Provision Redis (the prerequisite for multi-container)
Fly's managed Redis (Upstash) gives a single shared broker:

```bash
fly redis create                 # provision (pick the primary region = ord)
fly redis status <name>          # copy the redis:// connection string
fly secrets set REDIS_URL="redis://default:<password>@<host>:<port>"
```

Once `REDIS_URL` is set, the queue, rate-limiter, and log bus all switch to
their Redis backends automatically — no code change. The web machine also stops
running its in-process worker by default (so work isn't processed twice).

### 3.2 Process groups (`fly.toml`)
`fly.toml` defines two process groups from the same image:

```toml
[processes]
  web    = "python -m uvicorn apps.core.main:app --host 0.0.0.0 --port 8080"
  worker = "python -m apps.core.scale.worker"

[http_service]
  processes = ["web"]   # only web serves HTTP; workers are headless
```

### 3.3 Scale each tier independently
```bash
fly deploy                          # ships both process groups
fly scale count web=3 worker=6      # 3 API machines, 6 worker machines
fly scale count worker=12           # burst the workers alone under load
fly machine list                    # verify the fleet
```
- **Scale `web`** for HTTP concurrency (more producers / WebSocket fan-out).
- **Scale `worker`** for mission throughput (more consumers). Because workers are
  stateless and pull from the shared Redis queue, adding machines linearly
  increases throughput up to the provider rate limits.
- Keep outbound within provider quotas by switching the dispatcher to
  `RedisTokenBucket` so the *global* fleet shares one bucket (otherwise each
  worker gets its own local bucket and aggregate rate = N × per-worker rate).

### 3.4 Autoscaling & regions
- `[http_service]` already has `auto_start_machines`/`min_machines_running` for
  the web tier. Add more regions with `fly regions add iad lhr` and Fly will
  spread machines; the Redis broker stays in the primary region (`ord`).
- Workers can `auto_stop`/`auto_start` on queue depth via Fly Machines metrics
  if you wire a metrics-based scaler; for now scale them manually with
  `fly scale count worker=N`.

---

## 4. Fault tolerance summary
| Failure | Behavior |
|---|---|
| Worker crashes mid-task | Task stays in Redis; a healthy worker re-pops it. No data loss (status TTL 24h). |
| Transient LLM/network error | Self-healing retries `5s/15s/30s`; permanent errors fail fast. |
| Provider rate limit | Token bucket paces calls; `429`s are also treated as transient and retried. |
| One poisoned task | Isolated in try/except — the worker loop keeps draining. |
| Redis down | Web still accepts/serves; falls back to in-process paths per container (no cross-container sharing until Redis returns). |

---

## 5. Local verification
```bash
# Single-container path (no Redis) — the default:
python -m pytest tests/unit/test_scale.py -q      # 18 tests, in-memory backends
python -c "import apps.core.main"                 # app imports with routers wired

# Two-process path locally (needs a local Redis):
REDIS_URL=redis://localhost:6379 python -m uvicorn apps.core.main:app --port 8080 &
REDIS_URL=redis://localhost:6379 python -m apps.core.scale.worker &
```

---

_All figures in this document are architectural limits and configuration
guidance, not measured production throughput. Benchmark against your own Fly
plan and provider quotas before committing to capacity numbers._
