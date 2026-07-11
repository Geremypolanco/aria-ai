"""
Distributed, fault-tolerant scaling primitives for ARIA.

- task_queue   : producer/consumer mission queue (Redis list, in-memory fallback)
- rate_limiter : Redis token-bucket for outbound 3rd-party API calls
- log_bus      : Redis Pub/Sub for live agent logs (+ WebSocket fan-out)
- worker       : stateless background worker that drains the queue

All backends degrade to an in-process implementation when REDIS_URL is unset, so
the app runs on a single container in dev and fans out to many web + worker
containers in production. See SCALE_ARCH.md.
"""
