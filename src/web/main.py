from fastapi import FastAPI, Request, Form
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
import os

import uvicorn

from src.core.config import settings
from src.core.orchestrator import orchestrator

app = FastAPI(title="Nexus - ARIA Platform")

TEMPLATES_DIR = os.path.join(os.path.dirname(__file__), "templates")
templates = Jinja2Templates(directory=TEMPLATES_DIR)

@app.get("/", response_class=HTMLResponse)
async def nexus_home(request: Request):
    return templates.TemplateResponse("nexus.html", {"request": request, "title": "Nexus • ARIA", "version": "Fase 3b"})

@app.post("/chat")
async def chat_endpoint(message: str = Form(...), user_id: str = Form(default="web_user")):
    result = orchestrator.execute(message, user_id=user_id)
    return {"success": True, "action": result["action"], "response": result["result"]}

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=8080)