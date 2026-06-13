"""Agent organizational hierarchy with executive delegation and reporting chains."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional


class AgentRole(str, Enum):
    EXECUTIVE = "executive"
    DIRECTOR = "director"
    MANAGER = "manager"
    SPECIALIST = "specialist"
    WORKER = "worker"


class DelegationStatus(str, Enum):
    PENDING = "pending"
    ACCEPTED = "accepted"
    RUNNING = "running"
    DONE = "done"
    FAILED = "failed"
    REJECTED = "rejected"


@dataclass
class DelegationRecord:
    id: str
    from_agent: str
    to_agent: str
    task: str
    context: dict[str, Any]
    status: DelegationStatus = DelegationStatus.PENDING
    result: Any = None
    error: Optional[str] = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    finished_at: Optional[str] = None

    def to_dict(self) -> dict:
        return {
            "id": self.id,
            "from_agent": self.from_agent,
            "to_agent": self.to_agent,
            "task": self.task,
            "context": self.context,
            "status": self.status.value,
            "result": self.result,
            "error": self.error,
            "created_at": self.created_at,
            "finished_at": self.finished_at,
        }


@dataclass
class HierarchyNode:
    agent_id: str
    name: str
    role: AgentRole
    capabilities: list[str] = field(default_factory=list)
    parent_id: Optional[str] = None
    child_ids: list[str] = field(default_factory=list)
    handler: Optional[Callable] = None
    active: bool = True
    delegations_handled: int = 0
    delegations_failed: int = 0

    @property
    def success_rate(self) -> float:
        total = self.delegations_handled
        if total == 0:
            return 1.0
        return (total - self.delegations_failed) / total

    def can_handle(self, task: str) -> bool:
        if not self.capabilities:
            return True
        task_lower = task.lower()
        return any(cap.lower() in task_lower for cap in self.capabilities)

    def to_dict(self) -> dict:
        return {
            "agent_id": self.agent_id,
            "name": self.name,
            "role": self.role.value,
            "capabilities": self.capabilities,
            "parent_id": self.parent_id,
            "child_ids": self.child_ids,
            "active": self.active,
            "delegations_handled": self.delegations_handled,
            "delegations_failed": self.delegations_failed,
            "success_rate": round(self.success_rate, 3),
        }


class AgentHierarchy:
    """
    Tree-structured agent organization. Executive delegates to Directors,
    who delegate to Managers, who delegate to Specialists/Workers.
    Each node may have a callable handler for task execution.
    """

    def __init__(self) -> None:
        self._nodes: dict[str, HierarchyNode] = {}
        self._delegations: list[DelegationRecord] = {}
        self._delegations = []

    def register(
        self,
        agent_id: str,
        name: str,
        role: AgentRole,
        capabilities: Optional[list[str]] = None,
        parent_id: Optional[str] = None,
        handler: Optional[Callable] = None,
    ) -> HierarchyNode:
        node = HierarchyNode(
            agent_id=agent_id,
            name=name,
            role=role,
            capabilities=capabilities or [],
            parent_id=parent_id,
            handler=handler,
        )
        self._nodes[agent_id] = node
        if parent_id and parent_id in self._nodes:
            parent = self._nodes[parent_id]
            if agent_id not in parent.child_ids:
                parent.child_ids.append(agent_id)
        return node

    def get_node(self, agent_id: str) -> Optional[HierarchyNode]:
        return self._nodes.get(agent_id)

    def get_children(self, agent_id: str, role: Optional[AgentRole] = None) -> list[HierarchyNode]:
        node = self._nodes.get(agent_id)
        if node is None:
            return []
        children = [self._nodes[cid] for cid in node.child_ids if cid in self._nodes]
        if role is not None:
            children = [c for c in children if c.role == role]
        return [c for c in children if c.active]

    def best_delegate(self, from_agent_id: str, task: str) -> Optional[HierarchyNode]:
        """Select the best direct report for a task, prioritizing success_rate then capability match."""
        children = self.get_children(from_agent_id)
        capable = [c for c in children if c.can_handle(task)]
        if not capable:
            capable = children
        if not capable:
            return None
        return max(capable, key=lambda c: c.success_rate)

    async def delegate(
        self,
        from_agent_id: str,
        to_agent_id: str,
        task: str,
        context: Optional[dict] = None,
    ) -> DelegationRecord:
        rec = DelegationRecord(
            id=f"del_{uuid.uuid4().hex[:10]}",
            from_agent=from_agent_id,
            to_agent=to_agent_id,
            task=task,
            context=context or {},
        )
        self._delegations.append(rec)

        to_node = self._nodes.get(to_agent_id)
        if to_node is None or not to_node.active:
            rec.status = DelegationStatus.REJECTED
            rec.error = f"Agent '{to_agent_id}' not found or inactive"
            return rec

        rec.status = DelegationStatus.ACCEPTED
        if to_node.handler is None:
            rec.status = DelegationStatus.DONE
            rec.result = f"Task '{task}' acknowledged by {to_node.name} (no handler)"
            rec.finished_at = datetime.now(timezone.utc).isoformat()
            to_node.delegations_handled += 1
            return rec

        rec.status = DelegationStatus.RUNNING
        try:
            if asyncio.iscoroutinefunction(to_node.handler):
                result = await to_node.handler(task, context or {})
            else:
                result = to_node.handler(task, context or {})
            rec.status = DelegationStatus.DONE
            rec.result = result
            to_node.delegations_handled += 1
        except Exception as exc:
            rec.status = DelegationStatus.FAILED
            rec.error = str(exc)
            to_node.delegations_handled += 1
            to_node.delegations_failed += 1
        finally:
            rec.finished_at = datetime.now(timezone.utc).isoformat()

        return rec

    async def cascade(
        self,
        from_agent_id: str,
        task: str,
        context: Optional[dict] = None,
        max_depth: int = 3,
    ) -> DelegationRecord:
        """Auto-route task down the hierarchy to the best available agent."""
        current_id = from_agent_id
        for _ in range(max_depth):
            best = self.best_delegate(current_id, task)
            if best is None:
                break
            # If the best delegate has no handler and has children, go deeper
            if best.handler is None and best.child_ids:
                current_id = best.agent_id
                continue
            return await self.delegate(from_agent_id, best.agent_id, task, context)

        # Fallback: delegate to best direct report even without capability match
        children = self.get_children(from_agent_id)
        if children:
            return await self.delegate(from_agent_id, children[0].agent_id, task, context)

        rec = DelegationRecord(
            id=f"del_{uuid.uuid4().hex[:10]}",
            from_agent=from_agent_id,
            to_agent="none",
            task=task,
            context=context or {},
            status=DelegationStatus.REJECTED,
            error="No available agents in hierarchy",
        )
        self._delegations.append(rec)
        return rec

    def get_chain_of_command(self, agent_id: str) -> list[HierarchyNode]:
        """Returns path from root to agent."""
        node = self._nodes.get(agent_id)
        if node is None:
            return []
        chain = [node]
        while node.parent_id:
            parent = self._nodes.get(node.parent_id)
            if parent is None:
                break
            chain.insert(0, parent)
            node = parent
        return chain

    def reporting_structure(self) -> dict:
        """Tree representation of hierarchy."""
        def _subtree(agent_id: str) -> dict:
            node = self._nodes.get(agent_id)
            if node is None:
                return {}
            return {
                "id": agent_id,
                "name": node.name,
                "role": node.role.value,
                "capabilities": node.capabilities,
                "success_rate": round(node.success_rate, 3),
                "reports": [_subtree(cid) for cid in node.child_ids],
            }

        roots = [n for n in self._nodes.values() if n.parent_id is None]
        return {"roots": [_subtree(r.agent_id) for r in roots]}

    def summary(self) -> dict:
        total = len(self._delegations)
        done = sum(1 for d in self._delegations if d.status == DelegationStatus.DONE)
        return {
            "total_agents": len(self._nodes),
            "active_agents": sum(1 for n in self._nodes.values() if n.active),
            "total_delegations": total,
            "successful_delegations": done,
            "delegation_success_rate": round(done / total, 3) if total else 1.0,
            "roles": {role.value: sum(1 for n in self._nodes.values() if n.role == role) for role in AgentRole},
        }


_hierarchy: Optional[AgentHierarchy] = None


def get_agent_hierarchy() -> AgentHierarchy:
    global _hierarchy
    if _hierarchy is None:
        _hierarchy = AgentHierarchy()
        _bootstrap_aria_hierarchy(_hierarchy)
    return _hierarchy


def _bootstrap_aria_hierarchy(h: AgentHierarchy) -> None:
    """Bootstrap the default ARIA agent organizational structure."""
    h.register("aria_executive", "ARIA Executive", AgentRole.EXECUTIVE)
    h.register("dir_income", "Income Director", AgentRole.DIRECTOR,
               capabilities=["income", "revenue", "monetize"], parent_id="aria_executive")
    h.register("dir_content", "Content Director", AgentRole.DIRECTOR,
               capabilities=["content", "write", "blog", "article"], parent_id="aria_executive")
    h.register("dir_ops", "Operations Director", AgentRole.DIRECTOR,
               capabilities=["deploy", "infra", "monitor", "system"], parent_id="aria_executive")
    h.register("spec_shopify", "Shopify Specialist", AgentRole.SPECIALIST,
               capabilities=["shopify", "ecommerce", "product"], parent_id="dir_income")
    h.register("spec_affiliate", "Affiliate Specialist", AgentRole.SPECIALIST,
               capabilities=["affiliate", "link", "commission"], parent_id="dir_income")
    h.register("spec_writer", "Content Writer", AgentRole.SPECIALIST,
               capabilities=["write", "draft", "article", "blog"], parent_id="dir_content")
    h.register("spec_social", "Social Media Specialist", AgentRole.SPECIALIST,
               capabilities=["social", "twitter", "instagram", "post"], parent_id="dir_content")
    h.register("worker_scheduler", "Scheduler Worker", AgentRole.WORKER,
               capabilities=["schedule", "cron", "interval"], parent_id="dir_ops")
