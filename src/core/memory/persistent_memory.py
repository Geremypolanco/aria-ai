import aiosqlite
import json
import logging
from typing import Any, Dict, List, Optional
from datetime import datetime

from src.core.memory.base import MemoryStore

logger = logging.getLogger("megan.core.memory.persistent")

class PersistentMemory(MemoryStore):
    """Memoria persistente (Semántica y Episódica) de MEGAN usando SQLite."""
    
    def __init__(self, db_path: str = "megan_memory.db"):
        self.db_path = db_path
        self._initialized = False

    async def initialize(self):
        """Inicializa la base de datos y las tablas necesarias."""
        if not self._initialized:
            async with aiosqlite.connect(self.db_path) as db:
                await db.execute('''
                    CREATE TABLE IF NOT EXISTS memory (
                        id INTEGER PRIMARY KEY AUTOINCREMENT,
                        key TEXT UNIQUE,
                        value TEXT,
                        metadata TEXT,
                        type TEXT,
                        timestamp DATETIME
                    )
                ''')
                await db.commit()
            self._initialized = True
            logger.info(f"Persistent Memory initialized at {self.db_path}")

    async def store(self, key: str, value: Any, metadata: Optional[Dict[str, Any]] = None, mem_type: str = "semantic"):
        """Almacena un dato en la memoria persistente."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('''
                INSERT OR REPLACE INTO memory (key, value, metadata, type, timestamp)
                VALUES (?, ?, ?, ?, ?)
            ''', (
                key, 
                json.dumps(value), 
                json.dumps(metadata or {}), 
                mem_type, 
                datetime.now().isoformat()
            ))
            await db.commit()
        logger.debug(f"Stored in Persistent Memory ({mem_type}): {key}")

    async def retrieve(self, key: str) -> Optional[Any]:
        """Recupera un dato por su clave."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute('SELECT value FROM memory WHERE key = ?', (key,)) as cursor:
                row = await cursor.fetchone()
                if row:
                    return json.loads(row[0])
        return None

    async def search(self, query: str, limit: int = 10, mem_type: Optional[str] = None) -> List[Dict[str, Any]]:
        """Búsqueda textual simple en la base de datos."""
        await self.initialize()
        sql = 'SELECT key, value, metadata, timestamp FROM memory WHERE (key LIKE ? OR value LIKE ? OR metadata LIKE ?)'
        params = [f'%{query}%', f'%{query}%', f'%{query}%']
        
        if mem_type:
            sql += ' AND type = ?'
            params.append(mem_type)
            
        sql += ' ORDER BY timestamp DESC LIMIT ?'
        params.append(limit)
        
        results = []
        async with aiosqlite.connect(self.db_path) as db:
            async with db.execute(sql, params) as cursor:
                async for row in cursor:
                    results.append({
                        "key": row[0],
                        "value": json.loads(row[1]),
                        "metadata": json.loads(row[2]),
                        "timestamp": row[3]
                    })
        return results

    async def clear(self):
        """Limpia toda la memoria persistente."""
        await self.initialize()
        async with aiosqlite.connect(self.db_path) as db:
            await db.execute('DELETE FROM memory')
            await db.commit()
        logger.info("Persistent Memory cleared")
