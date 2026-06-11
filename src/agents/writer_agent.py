"""
WriterAgent - Especialista en generación de contenido
Crea ebooks, landing pages, posts, emails, scripts
"""
import logging
from typing import Dict, Any
from src.agents.base_agent import BaseAgent
from src.core.events.event_bus import EventBus, Event, EventType

logger = logging.getLogger("aria.agents.writer")

class WriterAgent(BaseAgent):
    """Agente especializado en creación de contenido."""
    
    def __init__(self, event_bus: EventBus):
        super().__init__(name="writer_agent", event_bus=event_bus)
        self.content_types = ["ebook", "landing_page", "blog_post", "email", "script", "course"]
    
    async def _subscribe_to_events(self):
        self.event_bus.subscribe(EventType.GOAL_CREATED, self.handle_content_task)
        self.event_bus.subscribe(EventType.AGENT_MESSAGE, self.handle_direct_message)
    
    async def handle_content_task(self, event: Event):
        """Maneja tareas de creación de contenido."""
        payload = event.payload
        if payload.get("type") == "content_generation":
            await self.generate_content(payload)
    
    async def handle_direct_message(self, event: Event):
        """Maneja mensajes directos al agente."""
        if event.payload.get("target") == self.name:
            await self.generate_content(event.payload)
    
    async def generate_content(self, task: Dict[str, Any]):
        """Genera contenido profesional."""
        content_type = task.get("content_type", "blog_post")
        topic = task.get("topic", "")
        
        logger.info(f"WriterAgent: Generando {content_type} sobre: {topic}")
        
        if content_type not in self.content_types:
            logger.error(f"Tipo de contenido no soportado: {content_type}")
            return
        
        # Simulación: en producción usaría Claude/GPT para generar contenido
        if content_type == "ebook":
            content = await self._generate_ebook(topic, task)
        elif content_type == "landing_page":
            content = await self._generate_landing_page(topic, task)
        elif content_type == "blog_post":
            content = await self._generate_blog_post(topic, task)
        elif content_type == "email":
            content = await self._generate_email(topic, task)
        elif content_type == "script":
            content = await self._generate_script(topic, task)
        elif content_type == "course":
            content = await self._generate_course(topic, task)
        else:
            content = ""
        
        logger.info(f"WriterAgent: Contenido generado ({len(content)} caracteres)")
        
        await self.event_bus.publish(Event(
            type=EventType.TASK_COMPLETED,
            payload={
                "task_id": task.get("id"),
                "agent": self.name,
                "content_type": content_type,
                "content": content,
                "word_count": len(content.split())
            },
            source=self.name
        ))
    
    async def _generate_ebook(self, topic: str, task: Dict[str, Any]) -> str:
        """Genera un ebook profesional."""
        return f"# Ebook: {topic}\n\n## Introducción\n\nContenido del ebook sobre {topic}..."
    
    async def _generate_landing_page(self, topic: str, task: Dict[str, Any]) -> str:
        """Genera una landing page HTML/CSS."""
        return f"""<!DOCTYPE html>
<html>
<head>
    <title>{topic}</title>
    <style>
        body {{ font-family: Arial, sans-serif; }}
        .hero {{ padding: 40px; text-align: center; }}
    </style>
</head>
<body>
    <div class="hero">
        <h1>{topic}</h1>
        <p>Landing page profesional generada automáticamente</p>
    </div>
</body>
</html>"""
    
    async def _generate_blog_post(self, topic: str, task: Dict[str, Any]) -> str:
        """Genera un post de blog."""
        return f"# {topic}\n\n## Introducción\n\nPost de blog sobre {topic}...\n\n## Conclusión\n\nEste es un post generado automáticamente."
    
    async def _generate_email(self, topic: str, task: Dict[str, Any]) -> str:
        """Genera un email de marketing."""
        return f"Subject: {topic}\n\nHola,\n\nEste es un email sobre {topic}.\n\nSaludos,\nAria"
    
    async def _generate_script(self, topic: str, task: Dict[str, Any]) -> str:
        """Genera un script (YouTube, podcast, etc)."""
        return f"# Script: {topic}\n\n[Intro]\n\n[Contenido principal sobre {topic}]\n\n[Conclusión]"
    
    async def _generate_course(self, topic: str, task: Dict[str, Any]) -> str:
        """Genera un curso completo."""
        return f"# Curso: {topic}\n\n## Módulo 1: Introducción\n## Módulo 2: Conceptos\n## Módulo 3: Práctica\n## Módulo 4: Proyecto Final"
