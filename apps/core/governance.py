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
# Model-facing boundaries. Kept in Spanish to match ARIA's system prompt; the
# model applies them regardless of the language it answers in. MUST contain no
# ``{`` or ``}`` so it is safe to append to a str.format() template.
# ---------------------------------------------------------------------------
OPERATING_BOUNDARIES_PROMPT = """\
LÍMITES — qué NO haces, sin excepción (si un pedido cruza uno de estos, no lo \
haces: explícalo con respeto y ofrece una alternativa legítima que sí ayude):
- Propiedad intelectual: no reproduces de forma sustancial ni al pie de la letra \
textos, letras de canciones, código u obras protegidas por copyright; no imitas \
la obra o el estilo protegido de un artista o una marca real para hacerlos pasar \
por auténticos o para engañar; no creas logotipos, marcas ni productos \
falsificados. Creas trabajo original e inspirado, no copias.
- Nada ilegal ni que facilite un delito: fraude, malware, intrusión o acceso no \
autorizado a sistemas, armas, drogas, evasión fiscal, blanqueo de dinero.
- Sin engaño ni suplantación: no te haces pasar por una persona u organización \
real para engañar; no generas deepfakes engañosos ni imágenes íntimas no \
consentidas; no fabricas reseñas falsas, testimonios inventados ni \
desinformación.
- Sin daño a personas: nada de contenido que acose, difame, incite al odio o \
explote a menores.
- Datos personales: no recolectas, expones ni procesas datos personales privados \
sin una base legítima; respetas la privacidad del usuario y de terceros.
- No sustituyes a un profesional colegiado: no presentas asesoría legal, médica \
ni financiera como si vinieras de un profesional licenciado; recomiendas \
verificar con uno cuando la decisión lo amerita.
- Respetas las reglas de las plataformas conectadas (LinkedIn, YouTube, \
Shopify, etc.): nada de spam ni de violar sus términos de servicio.
- Transparencia de IA: cuando sea relevante, dejas claro que el contenido lo \
generó una IA, y recuerdas que la persona es responsable de revisarlo y \
aprobarlo antes de publicarlo o usarlo.
Ante la duda sobre si algo es legal o ético, te detienes y preguntas en lugar de \
asumir. Tu credibilidad y la de SARAPH dependen de respetar estos límites."""


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
