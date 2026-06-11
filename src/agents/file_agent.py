"""
FileAgent - Especialista en gestión de archivos
Crea, lee, modifica archivos, genera PDFs, zips, imágenes
"""
import logging
import os
import json
from typing import Dict, Any
from src.agents.base_agent import BaseAgent
from src.core.events.event_bus import EventBus, Event, EventType

logger = logging.getLogger("aria.agents.file")

class FileAgent(BaseAgent):
    """Agente especializado en gestión de archivos."""
    
    def __init__(self, event_bus: EventBus):
        super().__init__(name="file_agent", event_bus=event_bus)
        self.supported_formats = ["txt", "json", "csv", "pdf", "zip", "md", "html"]
    
    async def _subscribe_to_events(self):
        self.event_bus.subscribe(EventType.GOAL_CREATED, self.handle_file_task)
        self.event_bus.subscribe(EventType.AGENT_MESSAGE, self.handle_direct_message)
    
    async def handle_file_task(self, event: Event):
        """Maneja tareas de gestión de archivos."""
        payload = event.payload
        if payload.get("type") == "file_operation":
            await self.execute_file_operation(payload)
    
    async def handle_direct_message(self, event: Event):
        """Maneja mensajes directos al agente."""
        if event.payload.get("target") == self.name:
            await self.execute_file_operation(event.payload)
    
    async def execute_file_operation(self, task: Dict[str, Any]):
        """Ejecuta operaciones de archivo."""
        operation = task.get("operation", "create")
        file_path = task.get("file_path", "")
        
        logger.info(f"FileAgent: Ejecutando operación {operation} en {file_path}")
        
        if operation == "create":
            result = await self._create_file(task)
        elif operation == "read":
            result = await self._read_file(task)
        elif operation == "update":
            result = await self._update_file(task)
        elif operation == "delete":
            result = await self._delete_file(task)
        elif operation == "generate_pdf":
            result = await self._generate_pdf(task)
        elif operation == "generate_zip":
            result = await self._generate_zip(task)
        else:
            result = {"success": False, "error": f"Operación desconocida: {operation}"}
        
        await self.event_bus.publish(Event(
            type=EventType.TASK_COMPLETED,
            payload={
                "task_id": task.get("id"),
                "agent": self.name,
                "operation": operation,
                "result": result
            },
            source=self.name
        ))
    
    async def _create_file(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Crea un nuevo archivo."""
        file_path = task.get("file_path", "")
        content = task.get("content", "")
        file_format = task.get("format", "txt")
        
        try:
            os.makedirs(os.path.dirname(file_path), exist_ok=True)
            
            if file_format == "json":
                with open(file_path, 'w') as f:
                    json.dump(content, f, indent=2)
            else:
                with open(file_path, 'w') as f:
                    f.write(content)
            
            return {
                "success": True,
                "file_path": file_path,
                "size": os.path.getsize(file_path),
                "message": f"Archivo creado exitosamente"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _read_file(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Lee un archivo."""
        file_path = task.get("file_path", "")
        
        try:
            with open(file_path, 'r') as f:
                content = f.read()
            
            return {
                "success": True,
                "file_path": file_path,
                "content": content,
                "size": len(content)
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _update_file(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Actualiza un archivo."""
        file_path = task.get("file_path", "")
        content = task.get("content", "")
        
        try:
            with open(file_path, 'w') as f:
                f.write(content)
            
            return {
                "success": True,
                "file_path": file_path,
                "message": "Archivo actualizado exitosamente"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _delete_file(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Elimina un archivo."""
        file_path = task.get("file_path", "")
        
        try:
            os.remove(file_path)
            return {
                "success": True,
                "file_path": file_path,
                "message": "Archivo eliminado exitosamente"
            }
        except Exception as e:
            return {"success": False, "error": str(e)}
    
    async def _generate_pdf(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Genera un PDF."""
        file_path = task.get("file_path", "")
        content = task.get("content", "")
        
        logger.info(f"FileAgent: Generando PDF: {file_path}")
        
        # Simulación: en producción usaría reportlab o weasyprint
        return {
            "success": True,
            "file_path": file_path,
            "format": "pdf",
            "message": "PDF generado exitosamente"
        }
    
    async def _generate_zip(self, task: Dict[str, Any]) -> Dict[str, Any]:
        """Genera un archivo ZIP."""
        zip_path = task.get("zip_path", "")
        files = task.get("files", [])
        
        logger.info(f"FileAgent: Generando ZIP: {zip_path} con {len(files)} archivos")
        
        # Simulación: en producción usaría zipfile
        return {
            "success": True,
            "zip_path": zip_path,
            "files_included": len(files),
            "message": "ZIP generado exitosamente"
        }
