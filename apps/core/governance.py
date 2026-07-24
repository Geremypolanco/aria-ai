"""
ARIA governance — the operating boundaries the assistant works within.

This module is the single source of truth for *what ARIA will and will not do*.
``OPERATING_BOUNDARIES_PROMPT`` is injected into ARIA's system prompt so the
limits shape actual behaviour (an LLM follows its system prompt), not just a
policy page. ``PUBLIC_BOUNDARIES`` and ``COMPLIANCE_STATUS`` are the plain,
English, user-facing versions rendered on the public Trust Center.

Honesty note: the compliance entries describe status truthfully — controls that
are *in place* today versus frameworks we are *working toward*. Nothing here
claims a certification ARIA has not actually earned, because a false compliance
claim is exactly the kind of legal exposure this layer exists to prevent.
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# Model-facing boundaries, appended straight into aria_mind.py's SYSTEM_TEMPLATE
# (see the import below) so this text sits inside the same system prompt as
# everything else there — it must stay in English to match, not mix languages
# mid-prompt. The model still applies these limits regardless of the language
# it replies in. MUST contain no ``{`` or ``}`` so it is safe to append to a
# str.format() template.
# ---------------------------------------------------------------------------
OPERATING_BOUNDARIES_PROMPT = """\
LIMITS — what you do NOT do, no exceptions (if a request crosses one of these, \
you don't do it: explain why respectfully and offer a legitimate alternative \
that actually helps):
- Intellectual property: you don't substantially or verbatim reproduce \
copyrighted text, song lyrics, code, or other protected work; you don't imitate \
a real artist's or brand's protected work or style to pass it off as authentic \
or to deceive; you don't create counterfeit logos, trademarks, or products. \
You create original, inspired work — not copies.
- Nothing illegal or that facilitates a crime: fraud, malware, unauthorized \
system intrusion or access, weapons, drugs, tax evasion, money laundering.
- No deception or impersonation: you don't pass yourself off as a real person \
or organization to deceive; you don't generate deceptive deepfakes or \
non-consensual intimate imagery; you don't fabricate fake reviews, invented \
testimonials, or disinformation.
- No harm to people: nothing that harasses, defames, incites hatred, or \
exploits minors.
- Personal data: you don't collect, expose, or process private personal data \
without a legitimate basis; you respect the privacy of the user and of others.
- You don't substitute for a licensed professional: you don't present legal, \
medical, or financial advice as if it came from a licensed professional; you \
recommend checking with one when the decision warrants it.
- You respect the rules of connected platforms (LinkedIn, YouTube, Shopify, \
etc.): no spam, no violating their terms of service.
- AI transparency: when it's relevant, you make clear that content was \
AI-generated, and remind the person that they're responsible for reviewing and \
approving it before publishing or using it.
When in doubt about whether something is legal or ethical, you stop and ask \
instead of assuming. Your credibility and SARAPH's depend on respecting these \
limits."""


# ---------------------------------------------------------------------------
# Public, English, user-facing version — rendered on the Trust Center.
# ---------------------------------------------------------------------------
PUBLIC_BOUNDARIES: dict[str, list[str]] = {
    "will": [
        "Create original content, research with cited sources, and help you publish your own work.",
        "Tell you when it is unsure, when something failed, and when a claim needs checking.",
        "Ask before consequential or ambiguous actions instead of guessing.",
        "Disclose that content is AI-generated when that matters, and keep you in control of what ships.",
        "Draft and organize legal, financial, and other documents to work alongside your own licensed professional.",
    ],
    "wont": [
        "Reproduce copyrighted text, lyrics, code, or artwork, or imitate a real artist's or brand's "
        "protected work to pass it off as authentic — it creates original work, not copies.",
        "Produce counterfeit logos, trademarks, or products.",
        "Help with anything illegal or that facilitates a crime — fraud, malware, intrusion, "
        "money laundering, and the like.",
        "Deceptively impersonate a real person or organization, create misleading deepfakes or "
        "non-consensual intimate imagery, or fabricate fake reviews, testimonials, or disinformation.",
        "Generate content that harasses, defames, incites hatred, or exploits minors.",
        "Collect or expose private personal data without a lawful basis.",
        "Present itself as a licensed attorney, doctor, or financial adviser, or give professional "
        "advice as a substitute for one.",
        "Spam or violate the terms of the platforms you connect (LinkedIn, YouTube, Shopify, and others).",
    ],
}


# ---------------------------------------------------------------------------
# Compliance status — honest. "in_place" = a control we actually run today.
# "in_progress" / "roadmap" = we are working toward it; NOT yet certified.
# ---------------------------------------------------------------------------
COMPLIANCE_STATUS: list[dict[str, str]] = [
    {
        "name": "SOC 2 Type II",
        "status": "in_progress",
        "detail": "We are building the controls and evidence a SOC 2 Type II audit requires. "
        "We are not yet SOC 2 certified; certification depends on an independent auditor.",
    },
    {
        "name": "ISO/IEC 27001",
        "status": "roadmap",
        "detail": "An information-security management system aligned to ISO/IEC 27001 is on our "
        "roadmap. We are not yet ISO 27001 certified.",
    },
    {
        "name": "HIPAA",
        "status": "roadmap",
        "detail": "ARIA is not a HIPAA-compliant service today and we do not sign Business Associate "
        "Agreements yet. Do not use ARIA to store or process protected health information (PHI).",
    },
    {
        "name": "GDPR & CCPA",
        "status": "in_progress",
        "detail": "We honor data access and deletion requests and are formalizing our data-protection "
        "practices in line with GDPR and CCPA. Email us to exercise your data rights.",
    },
    {
        "name": "EU AI Act & AI transparency",
        "status": "in_progress",
        "detail": "ARIA discloses AI-generated content where relevant and keeps a human in control of "
        "consequential actions. We are tracking the EU AI Act and other AI rules as they take effect.",
    },
]

# Security controls that are genuinely in place today (see main.py middleware,
# the OAuth-only sign-in, and Stripe-handled payments).
SECURITY_CONTROLS: list[str] = [
    "All traffic is served over HTTPS, with HSTS enforced.",
    "Baseline security headers on every response (content-type, framing, referrer, permissions).",
    "Sign-in is delegated to Google and GitHub OAuth — ARIA never sees or stores your password.",
    "Payments are processed by Stripe; ARIA does not store card numbers.",
    "Secrets are kept in environment configuration, never committed to the codebase.",
    "ARIA operates within explicit, published operating boundaries (see Responsible AI, above).",
]

SECURITY_CONTACT = "litesaraph@gmail.com"
