"""Regression test: _exec_newsletter_issue()'s Mailchimp fallback called
mc.create_campaign(subject=..., body=full_issue) — but the real signature
(mailchimp_tools.py) requires list_id, from_name, reply_to, and body_html
(not body), none of which were passed except subject. This raised
TypeError every time, silently swallowed by a bare except, so Mailchimp
delivery for the newsletter never worked regardless of configuration.
Also, the old code checked `mc_r.get("id")` for success, but
create_campaign() actually returns {"success": True, "campaign_id": ...}
on success — "id" is never a key in that dict, so even a successful send
would have been reported as failed.
"""

from __future__ import annotations

import inspect

from apps.core.tools.income_loop import IncomeLoop
from apps.core.tools.mailchimp_tools import MailchimpTools


def test_newsletter_issue_mailchimp_call_site_matches_real_signature():
    sig = inspect.signature(MailchimpTools.create_campaign)

    source = inspect.getsource(IncomeLoop._exec_newsletter_issue)
    start = source.index("await mc.create_campaign(") + len("await mc.create_campaign")
    depth = 0
    end = start
    for i, ch in enumerate(source[start:], start):
        if ch == "(":
            depth += 1
        elif ch == ")":
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    call_args = f"create_campaign{source[start:end]}"

    ns = {
        "create_campaign": lambda *a, **k: sig.bind(None, *a, **k),
        "mc_lists": {"lists": [{"id": "abc123"}]},
        "issue_num": 1,
        "subject": "Test Subject",
        "settings": type(
            "S", (), {"MAILCHIMP_FROM_NAME": None, "MAILCHIMP_REPLY_TO": None}
        )(),
        "full_issue": "full body",
    }
    eval(call_args, ns)  # raises TypeError if kwargs don't match the real signature

    assert 'mc_r.get("id")' not in source
    assert 'mc_r.get("success")' in source
