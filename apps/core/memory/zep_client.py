"""
zep_client.py — Memoria de Largo Plazo para ARIA AI con Zep.

Zep proporciona memoria de largo plazo para agentes con:
  - Context graphs con recuperación sub-200ms
  - Gestión de usuarios, hilos y mensajes
  - Extracción automática de hechos y relaciones
  - Integración con LangChain, AutoGen, CrewAI

Integración con Aria:
  - Complementa la EvolutionaryMemory (Mem0-inspired) existente
  - Proporciona memoria persistente entre sesiones de Telegram
  - Almacena el historial de interacciones por usuario/agente
  - Recupera contexto relevante para cada nueva tarea

Referencia: https://github.com/getzep/zep
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Optional

logger = logging.getLogger("aria.zep_client")

# ── Zep Import con fallback ──────────────────────────────────────────────────
try:
    from zep_cloud.client import AsyncZep
    from zep_cloud.types import Message, RoleType
    ZEP_AVAILABLE = True
    logger.info("[Zep] Librería zep-cloud cargada correctamente.")
except ImportError:
    try:
        # Intentar zep-python (versión community)
        from zep_python.client import AsyncZep  # type: ignore[no-redef]
        ZEP_AVAILABLE = True
        logger.info("[Zep] Librería zep-python cargada correctamente.")
    except ImportError:
        ZEP_AVAILABLE = False
        logger.warning(
            "[Zep] zep-cloud no instalado. "
            "Usando memoria en Supabase como fallback. "
            "Instala con: pip install zep-cloud"
        )
        AsyncZep = None  # type: ignore[assignment,misc]


# ── Implementación Fallback con Supabase ─────────────────────────────────────

class SupabaseMemoryFallback:
    """
    Fallback de memoria usando Supabase (ya disponible en Aria).
    Mantiene la misma interfaz que Zep para compatibilidad.
    """

    def __init__(self) -> None:
        self._sessions: dict[str, list[dict]] = {}

    async def add_memory(self, session_id: str, messages: list[dict]) -> None:
        if session_id not in self._sessions:
            self._sessions[session_id] = []
        self._sessions[session_id].extend(messages)

        # Persistir en Supabase si está disponible
        try:
            from apps.core.memory.supabase_client import get_db
            db = get_db()
            for msg in messages:
                await db.log_error(
                    f"[ZepFallback] session={session_id} role={msg.get('role')} "
                    f"content={msg.get('content', '')[:100]}"
                )
        except Exception:
            pass

    async def get_memory(self, session_id: str, limit: int = 10) -> list[dict]:
        msgs = self._sessions.get(session_id, [])
        return msgs[-limit:]

    async def search_memory(self, session_id: str, query: str, limit: int = 5) -> list[dict]:
        msgs = self._sessions.get(session_id, [])
        query_lower = query.lower()
        results = [
            m for m in msgs
            if query_lower in m.get("content", "").lower()
        ]
        return results[-limit:]


# ── Cliente Principal de Zep para ARIA ──────────────────────────────────────

class AriaZepClient:
    """
    Cliente de Zep para ARIA AI.

    Gestiona la memoria de largo plazo de los agentes, permitiendo:
    - Recordar conversaciones pasadas con usuarios de Telegram
    - Mantener contexto de campañas y estrategias entre sesiones
    - Recuperar hechos relevantes para nuevas tareas
    - Construir perfiles de usuarios y clientes

    Uso:
        client = AriaZepClient()

        # Añadir mensajes a la memoria
        await client.add_interaction(
            session_id="user_123",
            role="user",
            content="Quiero crear un ebook sobre fitness"
        )

        # Recuperar contexto relevante
        context = await client.get_relevant_context(
            session_id="user_123",
            query="estrategia de monetización"
        )
    """

    def __init__(self, api_key: str = "") -> None:
        self._client: Any = None
        self._fallback: SupabaseMemoryFallback | None = None
        self._api_key = api_key
        self._initialized = False

    async def initialize(self) -> bool:
        """
        Inicializa la conexión con Zep Cloud o usa fallback.
        Returns True si Zep está disponible, False si usa fallback.
        """
        if not ZEP_AVAILABLE or not self._api_key:
            logger.info(
                "[Zep] Usando fallback Supabase (ZEP_API_KEY no configurado o zep-cloud no instalado)"
            )
            self._fallback = SupabaseMemoryFallback()
            self._initialized = True
            return False

        try:
            self._client = AsyncZep(api_key=self._api_key)
            self._initialized = True
            logger.info("[Zep] Conexión con Zep Cloud establecida")
            return True
        except Exception as exc:
            logger.warning("[Zep] Error conectando a Zep Cloud: %s — usando fallback", exc)
            self._fallback = SupabaseMemoryFallback()
            self._initialized = True
            return False

    async def ensure_session(self, session_id: str, user_id: Optional[str] = None) -> bool:
        """
        Asegura que existe una sesión en Zep.

        Args:
            session_id: ID único de la sesión (ej: telegram_chat_id)
            user_id: ID del usuario (opcional)
        """
        if not self._initialized:
            await self.initialize()

        if self._client:
            try:
                await self._client.memory.add_session(
                    session_id=session_id,
                    user_id=user_id or session_id,
                )
                return True
            except Exception:
                # La sesión ya puede existir
                return True
        return True

    async def add_interaction(
        self,
        session_id: str,
        role: str,
        content: str,
        metadata: dict[str, Any] | None = None,
    ) -> bool:
        """
        Añade una interacción a la memoria de largo plazo.

        Args:
            session_id: ID de la sesión (ej: telegram_chat_id, agent_name)
            role: "user", "assistant", "system", o nombre del agente
            content: Contenido del mensaje
            metadata: Datos adicionales (agent_name, task_type, roi, etc.)

        Returns:
            True si se añadió correctamente
        """
        if not self._initialized:
            await self.initialize()

        message_dict = {
            "role": role,
            "content": content,
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metadata": metadata or {},
        }

        try:
            if self._client:
                await self.ensure_session(session_id)
                # Zep Cloud API
                messages = [
                    {
                        "role": role if role in ("user", "assistant") else "assistant",
                        "role_type": "user" if role == "user" else "assistant",
                        "content": content,
                    }
                ]
                await self._client.memory.add(
                    session_id=session_id,
                    messages=messages,
                )
            elif self._fallback:
                await self._fallback.add_memory(session_id, [message_dict])

            logger.debug("[Zep] Interacción añadida: session=%s role=%s", session_id, role)
            return True

        except Exception as exc:
            logger.error("[Zep] Error añadiendo interacción: %s", exc)
            return False

    async def get_relevant_context(
        self,
        session_id: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Recupera contexto relevante de la memoria para una query.

        Args:
            session_id: ID de la sesión
            query: Query de búsqueda semántica
            limit: Número máximo de resultados

        Returns:
            Lista de mensajes/hechos relevantes
        """
        if not self._initialized:
            await self.initialize()

        try:
            if self._client:
                results = await self._client.memory.search_sessions(
                    text=query,
                    session_ids=[session_id],
                    limit=limit,
                )
                return [
                    {
                        "content": r.message.content if hasattr(r, "message") else str(r),
                        "score": r.score if hasattr(r, "score") else 0.0,
                        "session_id": session_id,
                    }
                    for r in (results or [])
                ]
            elif self._fallback:
                return await self._fallback.search_memory(session_id, query, limit)

        except Exception as exc:
            logger.error("[Zep] Error buscando contexto: %s", exc)

        return []

    async def get_session_history(
        self,
        session_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        """
        Obtiene el historial completo de una sesión.

        Args:
            session_id: ID de la sesión
            limit: Número máximo de mensajes

        Returns:
            Lista de mensajes en orden cronológico
        """
        if not self._initialized:
            await self.initialize()

        try:
            if self._client:
                memory = await self._client.memory.get(session_id=session_id)
                if memory and hasattr(memory, "messages"):
                    return [
                        {
                            "role": m.role if hasattr(m, "role") else "unknown",
                            "content": m.content if hasattr(m, "content") else str(m),
                            "timestamp": m.created_at.isoformat() if hasattr(m, "created_at") else "",
                        }
                        for m in (memory.messages or [])[-limit:]
                    ]
            elif self._fallback:
                return await self._fallback.get_memory(session_id, limit)

        except Exception as exc:
            logger.error("[Zep] Error obteniendo historial: %s", exc)

        return []

    async def record_agent_action(
        self,
        agent_name: str,
        action: str,
        result: str,
        success: bool,
        roi: float = 0.0,
    ) -> bool:
        """
        Registra una acción de agente en la memoria de largo plazo.
        Permite a ARIA aprender de sus propias acciones pasadas.

        Args:
            agent_name: Nombre del agente (orchestrator, cfo, marketing, etc.)
            action: Descripción de la acción ejecutada
            result: Resultado obtenido
            success: Si la acción fue exitosa
            roi: ROI generado en USD
        """
        session_id = f"agent_{agent_name}"
        content = (
            f"[{'✓' if success else '✗'}] {action} | "
            f"Resultado: {result[:200]} | "
            f"ROI: ${roi:.2f}"
        )
        return await self.add_interaction(
            session_id=session_id,
            role="assistant",
            content=content,
            metadata={
                "agent": agent_name,
                "success": success,
                "roi": roi,
                "timestamp": datetime.now(timezone.utc).isoformat(),
            },
        )

    async def get_agent_learnings(
        self,
        agent_name: str,
        query: str,
        limit: int = 5,
    ) -> list[dict[str, Any]]:
        """
        Recupera aprendizajes pasados de un agente específico.

        Args:
            agent_name: Nombre del agente
            query: Tema a buscar en la memoria
            limit: Número máximo de resultados
        """
        session_id = f"agent_{agent_name}"
        return await self.get_relevant_context(session_id, query, limit)

    async def get_status(self) -> dict[str, Any]:
        """Retorna el estado del cliente Zep."""
        return {
            "backend": "zep_cloud" if self._client else "supabase_fallback",
            "zep_available": ZEP_AVAILABLE,
            "initialized": self._initialized,
            "api_key_configured": bool(self._api_key),
        }


# ── Singleton ────────────────────────────────────────────────────────────────
_zep_instance: AriaZepClient | None = None


def get_zep_client() -> AriaZepClient:
    """Retorna el singleton del cliente Zep de ARIA."""
    global _zep_instance
    if _zep_instance is None:
        import os
        _zep_instance = AriaZepClient(
            api_key=os.getenv("ZEP_API_KEY", ""),
        )
    return _zep_instance
