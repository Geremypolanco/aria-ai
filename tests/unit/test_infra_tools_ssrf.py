"""Regression test: InfraTools.monitor_api_health() fetched arbitrary
caller-supplied URLs with zero SSRF protection, same class of bug already
fixed in web_tools.py/browser_sandbox.py/multimodal.py/huggingface_suite.py/
knowledge_base.py. Defense-in-depth: currently unreachable from chat (see
test_aria_agent_infra_gate.py), but fixed here too in case a future dispatch
change makes it reachable.
"""

from __future__ import annotations

import pytest

from apps.core.tools.infra_tools import InfraTools

pytestmark = pytest.mark.asyncio


async def test_monitor_api_health_refuses_internal_address():
    tools = InfraTools()
    result = await tools.monitor_api_health(["http://169.254.169.254/latest/meta-data/"])
    entry = result["health"]["http://169.254.169.254/latest/meta-data/"]
    assert entry["up"] is False
    assert entry["status"] == "error"
