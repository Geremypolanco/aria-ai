"""
Cliente Redis sobre Upstash para colas y caché.
Usa REST API de Upstash — no requiere conexión persistente.
"""

import contextlib
import json
import time
from typing import Any

import httpx

from apps.core.config import settings


class AriaCache:

    def __init__(self):
        self._base_url = settings.UPSTASH_REDIS_REST_URL
        self._token = settings.UPSTASH_REDIS_REST_TOKEN
        self._http = httpx.AsyncClient(timeout=15.0)
        self._headers = {
            "Authorization": f"Bearer {self._token}",
            "Content-Type": "application/json",
        }

    async def _cmd(self, *args) -> Any:
        """Ejecuta un comando Redis via REST."""
        try:
            response = await self._http.post(
                self._base_url,
                headers=self._headers,
                json=list(args),
            )
            data = response.json()
            return data.get("result")
        except Exception:
            return None

    async def ping(self) -> bool:
        """Ping honesto: True sólo si Redis responde PONG en un ida-y-vuelta real.

        Usado por /health para reflejar la verdad — el objeto de caché siempre
        existe, así que su mera presencia no es señal de que el backend funcione.
        """
        try:
            return (await self._cmd("PING")) == "PONG"
        except Exception:
            return False

    # ── CACHÉ BÁSICO ──────────────────────────────────────
    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        result = await self._cmd("SET", key, serialized, "EX", ttl_seconds)
        return result == "OK"

    async def get(self, key: str) -> Any | None:
        result = await self._cmd("GET", key)
        if result is None:
            return None
        try:
            return json.loads(result)
        except (json.JSONDecodeError, TypeError):
            return result

    async def delete(self, key: str) -> bool:
        result = await self._cmd("DEL", key)
        return result == 1

    async def exists(self, key: str) -> bool:
        result = await self._cmd("EXISTS", key)
        return result == 1

    async def increment(self, key: str) -> int:
        return await self._cmd("INCR", key) or 0

    # ── COLAS DE TAREAS ───────────────────────────────────
    async def enqueue(self, queue: str, task: dict) -> bool:
        """Agrega una tarea al final de la cola."""
        serialized = json.dumps(task)
        result = await self._cmd("RPUSH", f"queue:{queue}", serialized)
        return result is not None and result > 0

    async def dequeue(self, queue: str) -> dict | None:
        """Obtiene y elimina la primera tarea de la cola."""
        result = await self._cmd("LPOP", f"queue:{queue}")
        if result is None:
            return None
        try:
            return json.loads(result)
        except Exception:
            return None

    async def queue_size(self, queue: str) -> int:
        result = await self._cmd("LLEN", f"queue:{queue}")
        return result or 0

    async def peek_queue(self, queue: str, count: int = 5) -> list:
        """Ve las próximas tareas sin eliminarlas."""
        result = await self._cmd("LRANGE", f"queue:{queue}", 0, count - 1)
        if not result:
            return []
        tasks = []
        for item in result:
            with contextlib.suppress(Exception):
                tasks.append(json.loads(item))
        return tasks

    # ── LIST OPERATIONS ──────────────────────────────────
    async def rpush(self, key: str, *values: str) -> int:
        """Append one or more values to the tail of a list."""
        result = await self._cmd("RPUSH", key, *values)
        return result or 0

    async def lpush(self, key: str, *values: str) -> int:
        """Prepend one or more values to the head of a list."""
        result = await self._cmd("LPUSH", key, *values)
        return result or 0

    async def lpop(self, key: str) -> str | None:
        """Remove and return the first element of the list."""
        return await self._cmd("LPOP", key)

    async def lrange(self, key: str, start: int, stop: int) -> list:
        """Return a slice of the list stored at key."""
        result = await self._cmd("LRANGE", key, start, stop)
        return result if isinstance(result, list) else []

    async def ltrim(self, key: str, start: int, stop: int) -> bool:
        """Trim a list to the specified range."""
        result = await self._cmd("LTRIM", key, start, stop)
        return result == "OK"

    async def llen(self, key: str) -> int:
        """Return the length of the list stored at key."""
        result = await self._cmd("LLEN", key)
        return result or 0

    async def expire(self, key: str, seconds: int) -> bool:
        """Set a timeout on key in seconds."""
        result = await self._cmd("EXPIRE", key, seconds)
        return result == 1

    # ── ESTADO DE AGENTES ─────────────────────────────────
    async def set_agent_status(self, agent_name: str, status: dict) -> bool:
        return await self.set(f"agent:{agent_name}:status", status, ttl_seconds=300)

    async def get_agent_status(self, agent_name: str) -> dict | None:
        return await self.get(f"agent:{agent_name}:status")

    async def set_agent_heartbeat(self, agent_name: str) -> bool:
        return await self.set(f"agent:{agent_name}:heartbeat", int(time.time()), ttl_seconds=120)

    async def is_agent_alive(self, agent_name: str) -> bool:
        heartbeat = await self.get(f"agent:{agent_name}:heartbeat")
        if heartbeat is None:
            return False
        return (int(time.time()) - int(heartbeat)) < 120

    # ── RATE LIMITING ─────────────────────────────────────
    async def check_rate_limit(self, key: str, max_calls: int, window_seconds: int) -> bool:
        """Retorna True si se puede hacer la llamada, False si excede el límite."""
        rate_key = f"ratelimit:{key}"
        current = await self._cmd("INCR", rate_key)
        if current == 1:
            await self._cmd("EXPIRE", rate_key, window_seconds)
        return current is not None and int(current) <= max_calls

    # ── LOCKS DISTRIBUIDOS ────────────────────────────────
    async def acquire_lock(self, resource: str, ttl_seconds: int = 60) -> bool:
        """Adquiere un lock para evitar ejecuciones duplicadas."""
        result = await self._cmd("SET", f"lock:{resource}", "1", "NX", "EX", ttl_seconds)
        return result == "OK"

    async def release_lock(self, resource: str) -> bool:
        return await self.delete(f"lock:{resource}")

    # ── MÉTRICAS EN TIEMPO REAL ───────────────────────────
    async def increment_metric(self, metric: str) -> int:
        return await self.increment(f"metric:{metric}") or 0

    async def get_metric(self, metric: str) -> int:
        result = await self.get(f"metric:{metric}")
        return int(result) if result else 0

    async def close(self):
        await self._http.aclose()


# ── SINGLETON ─────────────────────────────────────────────
_cache: AriaCache | None = None


def get_cache() -> AriaCache:
    global _cache
    if _cache is None:
        _cache = AriaCache()
    return _cache
