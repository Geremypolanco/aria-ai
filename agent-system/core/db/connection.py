"""
ARIA Agent System — Conexión a PostgreSQL con SQLAlchemy asíncrono.
Pool de conexiones con reconexión automática y health checks.
"""
from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from typing import AsyncGenerator

from sqlalchemy.ext.asyncio import (
    AsyncSession,
    AsyncEngine,
    async_sessionmaker,
    create_async_engine,
)
from sqlalchemy import text

from core.config.settings import settings

logger = logging.getLogger("aria.db")

_engine: AsyncEngine | None = None
_session_factory: async_sessionmaker[AsyncSession] | None = None


async def get_engine() -> AsyncEngine:
    """Retorna el engine (singleton), creándolo si es necesario."""
    global _engine
    if _engine is None:
        db_url = str(settings.DATABASE_URL)
        logger.info("Creando pool de conexiones a PostgreSQL...")
        _engine = create_async_engine(
            db_url,
            pool_size=10,
            max_overflow=20,
            pool_pre_ping=True,           # Verifica conexión antes de usarla
            pool_recycle=3600,            # Recicla conexiones cada hora
            echo=False,
            connect_args={
                "command_timeout": 30,     # Timeout de comandos
                "server_settings": {
                    "application_name": "aria-agent-system",
                },
            },
        )
        # Verificar conectividad
        try:
            async with _engine.connect() as conn:
                await conn.execute(text("SELECT 1"))
            logger.info("Conexión a PostgreSQL establecida exitosamente")
        except Exception as e:
            logger.error("Error conectando a PostgreSQL: %s", e)
            raise

    return _engine


async def get_session_factory() -> async_sessionmaker[AsyncSession]:
    """Retorna la session factory (singleton)."""
    global _session_factory
    if _session_factory is None:
        engine = await get_engine()
        _session_factory = async_sessionmaker(
            engine,
            class_=AsyncSession,
            expire_on_commit=False,
            autoflush=False,
        )
    return _session_factory


@asynccontextmanager
async def get_session() -> AsyncGenerator[AsyncSession, None]:
    """Context manager que provee una sesión de base de datos con rollback automático."""
    factory = await get_session_factory()
    session = factory()
    try:
        yield session
        await session.commit()
    except Exception:
        await session.rollback()
        raise
    finally:
        await session.close()


async def close_db() -> None:
    """Cierra el pool de conexiones. Llamar en shutdown."""
    global _engine
    if _engine:
        logger.info("Cerrando pool de conexiones a PostgreSQL...")
        await _engine.dispose()
        _engine = None
        _session_factory = None
        logger.info("Pool de conexiones cerrado")


async def health_check() -> dict:
    """Verifica el estado de la base de datos."""
    try:
        async with get_session() as session:
            result = await session.execute(text("SELECT 1 AS ok"))
            row = result.fetchone()
            return {
                "status": "ok" if row and row.ok == 1 else "error",
                "pool_size": _engine.pool.size() if _engine else 0,
                "checked_in": _engine.pool.checkedin() if _engine else 0,
                "overflow": _engine.pool.overflow() if _engine else 0,
            } if _engine else {"status": "not_initialized"}
    except Exception as e:
        return {"status": "error", "message": str(e)}
