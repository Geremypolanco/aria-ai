"""
ARIA LangGraph — AgentState TypedDict for cognitive workflows.

Defines the shared state that flows through all LangGraph nodes.
Uses Annotated with operator.add for list fields so partial updates
append rather than replace.
"""
from __future__ import annotations

import operator
from typing import Annotated, TypedDict


class AgentState(TypedDict):
    """
    State shared across all nodes in the cognitive workflow.

    Fields:
        messages        — conversation history, appended on each update
        task            — the current task description
        context         — arbitrary contextual information dict
        reasoning_steps — free-form reasoning trace, appended per node
        plan            — ordered list of action steps
        current_step    — index of the step currently being executed
        result          — final or intermediate output text
        confidence      — 0.0–1.0 confidence in the current result
        iteration       — how many full analyze→plan→execute→reflect cycles ran
        max_iterations  — hard cap on cycles to prevent infinite loops
        status          — lifecycle state machine value:
                          "thinking" | "planning" | "executing"
                          | "reflecting" | "done" | "failed"
    """

    messages: Annotated[list[dict], operator.add]
    task: str
    context: dict
    reasoning_steps: Annotated[list[str], operator.add]
    plan: list[str]
    current_step: int
    result: str
    confidence: float
    iteration: int
    max_iterations: int
    status: str  # "thinking" | "planning" | "executing" | "reflecting" | "done" | "failed"
