"""AriaAgent - LangGraph-based autonomous agent with tool use and memory."""
from __future__ import annotations
import logging
import os
from langchain.chat_models import init_chat_model
from langchain.schema import HumanMessage
from langchain_core.runnables import RunnableConfig
from langgraph.prebuilt import create_react_agent
from aria.integrations.registry import get_all_tools
from aria.memory.store import MemoryStore
from aria.self_improvement.reflector import Reflector

logger = logging.getLogger(__name__)

SYSTEM_PROMPT = """Eres Aria, un sistema autonomo de negocios e inteligencia operativa.
Tienes acceso a herramientas: CRM (HubSpot), e-commerce (Shopify),
productividad (Notion, Airtable, Trello, Asana, Google Workspace),
comunicacion (Gmail, Telegram, Mailchimp), finanzas (Stripe, PayPal),
marketing (Google Ads, Facebook, TikTok, LinkedIn, Buffer),
analytics (Google Analytics 4), codigo (GitHub),
almacenamiento (Dropbox, Google Drive), calendario (Calendly, Google Calendar),
y audio (ElevenLabs).

Principios:
1. Razona paso a paso antes de usar herramientas.
2. Cuando no estes seguro, pregunta. No inventes datos.
3. Si una tarea puede automatizarse mas, proponselo al usuario.
4. Aprende de cada interaccion y actualiza tu memoria.
5. Responde en el idioma del usuario."""


class AriaAgent:
    def __init__(self, memory: MemoryStore) -> None:
        self.memory = memory
        self.reflector = Reflector()
        self._llm = init_chat_model(
            model=os.getenv("ARIA_MODEL", "gpt-4o"),
            model_provider=os.getenv("ARIA_MODEL_PROVIDER", "openai"),
            api_key=os.getenv("OPENAI_API_KEY"),
            temperature=0,
        )
        tools = get_all_tools()
        self._graph = create_react_agent(
            model=self._llm,
            tools=tools,
            state_modifier=SYSTEM_PROMPT,
        )
        logger.info("AriaAgent initialised with %d tools.", len(tools))

    async def run(self, *, user_id: str, message: str) -> str:
        history = await self.memory.get_history(user_id)
        messages = history + [HumanMessage(content=message)]
        config: RunnableConfig = {"configurable": {"thread_id": user_id}}
        result = await self._graph.ainvoke({"messages": messages}, config=config)
        response_msg = result["messages"][-1]
        response_text = (
            response_msg.content if hasattr(response_msg, "content") else str(response_msg)
        )
        await self.memory.add_turn(
            user_id=user_id,
            user_message=message,
            assistant_response=response_text,
        )
        await self.reflector.reflect(
            user_id=user_id,
            user_message=message,
            assistant_response=response_text,
        )
        return response_text

    async def get_status(self) -> str:
        tools = get_all_tools()
        tool_names = ", ".join(t.name for t in tools)
        return (
            f"*ARIA STATUS*\n"
            f"Model: `{os.getenv('ARIA_MODEL', 'gpt-4o')}`\n"
            f"Tools loaded: `{len(tools)}`\n"
            f"Tool list: {tool_names}"
        )
