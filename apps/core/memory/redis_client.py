"""
Cliente Redis sobre Upstash para colas y caché.
Usa REST API de Upstash — no requiere conexión persistente.
"""
import json
import time
from typing import Optional, Any
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

    # ── CACHÉ BÁSICO ──────────────────────────────────────
    async def set(self, key: str, value: Any, ttl_seconds: int = 3600) -> bool:
        serialized = json.dumps(value) if not isinstance(value, str) else value
        result = await self._cmd("SET", key, serialized, "EX", ttl_seconds)
        return result == "OK"

    async def get(self, key: str) -> Optional[Any]:
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

    async def dequeue(self, queue: str) -> Optional[dict]:
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
            try:
                tasks.append(json.loads(item))
            except Exception:
                pass
        return tasks

    # ── ESTADO DE AGENTES ─────────────────────────────────
    async def set_agent_status(self, agent_name: str, status: dict) -> bool:
        return await self.set(f"agent:{agent_name}:status", status, ttl_seconds=300)

    async def get_agent_status(self, agent_name: str) -> Optional[dict]:
        return await self.get(f"agent:{agent_name}:status")

    async def set_agent_heartbeat(self, agent_name: str) -> bool:
        return await self.set(
            f"agent:{agent_name}:heartbeat",
            int(time.time()),
            ttl_seconds=120
        )

    async def is_agent_alive(self, agent_name: str) -> bool:
        heartbeat = await self.get(f"agent:{agent_name}:heartbeat")
        if heartbeat is None:
            return False
        return (int(time.time()) - int(heartbeat)) < 120

    # ── RATE LIMITING ─────────────────────────────────────
    async def check_rate_limit(
        self,
        key: str,
        max_calls: int,
        window_seconds: int
    ) -> bool:
        """Retorna True si se puede hacer la llamada, False si excede el límite."""
        rate_key = f"ratelimit:{key}"
        current = await self._cmd("INCR", rate_key)
        if current == 1:
            await self._cmd("EXPIRE", rate_key, window_seconds)
        return current is not None and int(current) <= max_calls

    # ── LOCKS DISTRIBUIDOS ────────────────────────────────
    async def acquire_lock(self, resource: str, ttl_seconds: int = 60) -> bool:
        """Adquiere un lock para evitar ejecuciones duplicadas."""
        result = await self._cmd(
            "SET", f"lock:{resource}", "1", "NX", "EX", ttl_seconds
        )
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
_cache: Optional[AriaCache] = None


def get_cache() -> AriaCache:
    global _cache
    if _cache is None:
        _cache = AriaCache()
    return _cache

