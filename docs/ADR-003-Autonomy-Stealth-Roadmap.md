# ADR-003: Full Autonomy and Stealth Implementation

## Context
Implement local-first LLM (Ollama), stealth browser (Camoufox), Qdrant memory, PyAutoGUI UI.

## Decision
- LLM Provider abstraction
- Docker services for local stack
- Backward compatible with cloud

## Consequences
Increased privacy, reduced costs, higher stealth. Potential latency trade-off.

Status: Implemented