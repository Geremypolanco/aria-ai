"""
ARIA Website Engine — Professional website and HTML generation.
Generates complete self-contained HTML using Tailwind CSS (CDN).
Supports multiple templates: saas, landing, portfolio, ecommerce, blog, restaurant.
Uses AIModel.CODE for AI-powered generation with a beautiful fallback template.
"""

from __future__ import annotations

import logging
import re
from typing import Any

logger = logging.getLogger("aria.website_engine")

# Supported templates
SUPPORTED_TEMPLATES = {"saas", "landing", "portfolio", "ecommerce", "blog", "restaurant"}

# Color palettes for landing page generator
COLOR_SCHEMES: dict[str, dict[str, str]] = {
    "blue": {"primary": "blue-600", "light": "blue-50", "dark": "blue-900", "accent": "blue-500"},
    "purple": {
        "primary": "purple-600",
        "light": "purple-50",
        "dark": "purple-900",
        "accent": "purple-500",
    },
    "green": {
        "primary": "green-600",
        "light": "green-50",
        "dark": "green-900",
        "accent": "green-500",
    },
    "red": {"primary": "red-600", "light": "red-50", "dark": "red-900", "accent": "red-500"},
    "orange": {
        "primary": "orange-600",
        "light": "orange-50",
        "dark": "orange-900",
        "accent": "orange-500",
    },
    "teal": {"primary": "teal-600", "light": "teal-50", "dark": "teal-900", "accent": "teal-500"},
    "indigo": {
        "primary": "indigo-600",
        "light": "indigo-50",
        "dark": "indigo-900",
        "accent": "indigo-500",
    },
}


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


class WebsiteEngine:
    """
    Production-quality website generation engine for ARIA AI.
    Generates complete, self-contained HTML with embedded Tailwind CSS via CDN.
    """

    def __init__(self) -> None:
        self._ai: Any = None

    async def _get_ai(self):
        if self._ai is None:
            from apps.core.tools.ai_client import get_ai_client_async

            self._ai = await get_ai_client_async()
        return self._ai

    # ── PUBLIC API ────────────────────────────────────────────────────────────

    async def generate_website(
        self,
        name: str,
        description: str,
        sections: list[str],
        template: str = "saas",
    ) -> dict[str, Any]:
        """
        Generate a complete self-contained HTML website.

        Args:
            name:        Product or site name.
            description: Short description of the product/service.
            sections:    List of section names (e.g. ["features", "pricing", "faq"]).
            template:    One of "saas", "landing", "portfolio", "ecommerce",
                         "blog", "restaurant".

        Returns:
            {
                "success":     bool,
                "html":        str,
                "html_bytes":  bytes,
                "filename":    str,
                "template":    str,
                "provider":    str,   # "ai" or "fallback"
            }
        """
        if template not in SUPPORTED_TEMPLATES:
            template = "saas"

        sections_str = ", ".join(sections) if sections else "hero, features, pricing, contact"
        ai_prompt = (
            f"Generate a complete, professional, modern, fully self-contained HTML website.\n"
            f"Product name: {name}\n"
            f"Description: {description}\n"
            f"Template style: {template}\n"
            f"Sections to include: {sections_str}\n\n"
            f"Requirements:\n"
            f"- Use Tailwind CSS via CDN (https://cdn.tailwindcss.com)\n"
            f"- Fully self-contained single HTML file, no external CSS/JS except Tailwind CDN\n"
            f"- Mobile-responsive\n"
            f"- Beautiful gradient hero section with the product name prominent\n"
            f"- Smooth scroll navigation\n"
            f"- Professional modern design that converts visitors\n"
            f"- All sections listed above must be present\n"
            f"- Use semantic HTML5 tags\n"
            f"- Add a sticky top navigation bar with the product name and links\n"
            f"- Footer with copyright\n"
            f"Return ONLY the raw HTML, starting with <!DOCTYPE html>. No explanation."
        )

        html = ""
        provider = "fallback"

        try:
            ai = await self._get_ai()
            resp = await ai.complete(
                system=(
                    "You are an expert front-end web developer specialising in "
                    "conversion-focused landing pages and SaaS websites. "
                    "You write clean, modern, fully self-contained HTML with Tailwind CSS. "
                    "Return ONLY the raw HTML — nothing else."
                ),
                user=ai_prompt,
                model=_import_ai_model_code(),
                max_tokens=4000,
                temperature=0.4,
                agent_name="website_engine",
            )
            if resp.success and resp.content.strip().startswith("<!"):
                html = resp.content.strip()
                provider = "ai"
            elif resp.success and "<html" in resp.content.lower():
                # Extract HTML block if model wrapped it
                match = re.search(r"<!DOCTYPE html>.*", resp.content, re.DOTALL | re.IGNORECASE)
                if match:
                    html = match.group(0).strip()
                    provider = "ai"
        except Exception as exc:
            logger.warning("[WebsiteEngine] AI generation failed: %s — using fallback", exc)

        if not html:
            logger.info("[WebsiteEngine] Using hardcoded fallback template for '%s'", name)
            html = _build_fallback_html(name, description, sections, template)
            provider = "fallback"

        html_bytes = html.encode("utf-8")
        filename = f"{_slug(name)}-website.html"

        return {
            "success": True,
            "html": html,
            "html_bytes": html_bytes,
            "filename": filename,
            "template": template,
            "provider": provider,
        }

    async def generate_landing_page(
        self,
        product_name: str,
        features: list[str],
        cta: str,
        color_scheme: str = "blue",
    ) -> dict[str, Any]:
        """
        Quick single-page landing page generator with strong CTA.

        Args:
            product_name:  Name of the product.
            features:      List of feature strings to highlight.
            cta:           Call-to-action button text.
            color_scheme:  One of "blue", "purple", "green", "red", "orange",
                           "teal", "indigo".

        Returns:
            Standard result dict with html / html_bytes / filename.
        """
        colors = COLOR_SCHEMES.get(color_scheme, COLOR_SCHEMES["blue"])
        html = _build_landing_page_html(product_name, features, cta, colors)
        html_bytes = html.encode("utf-8")
        filename = f"{_slug(product_name)}-landing.html"

        return {
            "success": True,
            "html": html,
            "html_bytes": html_bytes,
            "filename": filename,
            "template": "landing",
            "provider": "template",
        }

    async def generate_email_template(
        self,
        subject: str,
        headline: str,
        body: str,
        cta_text: str,
        cta_url: str,
    ) -> dict[str, Any]:
        """
        Generate an HTML email template compatible with major email clients.

        Args:
            subject:   Email subject line (used in <title>).
            headline:  Main headline inside the email.
            body:      Body text (may contain line breaks).
            cta_text:  Button label.
            cta_url:   Button URL.

        Returns:
            Standard result dict with html / html_bytes / filename.
        """
        html = _build_email_html(subject, headline, body, cta_text, cta_url)
        html_bytes = html.encode("utf-8")
        filename = f"email-{_slug(subject)}.html"

        return {
            "success": True,
            "html": html,
            "html_bytes": html_bytes,
            "filename": filename,
            "template": "email",
            "provider": "template",
        }


# ── HELPERS ───────────────────────────────────────────────────────────────────


def _import_ai_model_code():
    """Lazy import to avoid circular imports at module load time."""
    from apps.core.tools.ai_client import AIModel

    return AIModel.CODE


def _build_fallback_html(
    name: str,
    description: str,
    sections: list[str],
    template: str,
) -> str:
    """
    Hardcoded beautiful fallback template using Tailwind CDN.
    Renders a genuine product-quality page with hero, features grid, CTA, footer.
    """
    features_items = sections if sections else ["Fast & Reliable", "Easy to Use", "Affordable"]

    features_html = "\n".join(f"""
        <div class="bg-white rounded-2xl shadow-sm border border-gray-100 p-8 flex flex-col gap-3
                    hover:shadow-md transition-shadow duration-300">
          <div class="w-10 h-10 rounded-xl bg-indigo-100 flex items-center justify-center">
            <svg class="w-6 h-6 text-indigo-600" fill="none" stroke="currentColor"
                 viewBox="0 0 24 24">
              <path stroke-linecap="round" stroke-linejoin="round" stroke-width="2"
                    d="M5 13l4 4L19 7"/>
            </svg>
          </div>
          <h3 class="text-lg font-semibold text-gray-900">{feat}</h3>
          <p class="text-gray-500 text-sm leading-relaxed">
            Leverage {feat.lower()} to scale your business effortlessly and delight every customer.
          </p>
        </div>""" for feat in features_items)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{name} — {description[:60]}</title>
  <script src="https://cdn.tailwindcss.com"></script>
  <style>
    html {{ scroll-behavior: smooth; }}
    .gradient-hero {{
      background: linear-gradient(135deg, #4f46e5 0%, #7c3aed 50%, #2563eb 100%);
    }}
    .gradient-cta {{
      background: linear-gradient(135deg, #4f46e5, #7c3aed);
    }}
  </style>
</head>
<body class="bg-gray-50 text-gray-800 font-sans antialiased">

  <!-- NAV -->
  <header class="fixed top-0 left-0 right-0 z-50 bg-white/80 backdrop-blur border-b
                 border-gray-200 shadow-sm">
    <div class="max-w-7xl mx-auto px-6 h-16 flex items-center justify-between">
      <span class="text-xl font-bold text-indigo-600 tracking-tight">{name}</span>
      <nav class="hidden md:flex gap-8 text-sm font-medium text-gray-600">
        <a href="#features" class="hover:text-indigo-600 transition-colors">Features</a>
        <a href="#pricing"  class="hover:text-indigo-600 transition-colors">Pricing</a>
        <a href="#contact"  class="hover:text-indigo-600 transition-colors">Contact</a>
      </nav>
      <a href="#get-started"
         class="hidden md:inline-flex items-center gap-2 bg-indigo-600 text-white
                px-5 py-2 rounded-lg text-sm font-semibold hover:bg-indigo-700
                transition-colors shadow-sm">
        Get Started
      </a>
    </div>
  </header>

  <!-- HERO -->
  <section class="gradient-hero min-h-screen flex items-center pt-16">
    <div class="max-w-7xl mx-auto px-6 py-28 text-center">
      <span class="inline-block bg-white/20 text-white text-xs font-semibold
                   uppercase tracking-widest px-4 py-1.5 rounded-full mb-6">
        Introducing {name}
      </span>
      <h1 class="text-5xl md:text-7xl font-extrabold text-white leading-tight mb-6
                  drop-shadow-md">
        {name}
      </h1>
      <p class="text-xl md:text-2xl text-white/80 max-w-2xl mx-auto mb-10
                 leading-relaxed">
        {description}
      </p>
      <div class="flex flex-col sm:flex-row gap-4 justify-center">
        <a href="#get-started"
           id="get-started"
           class="bg-white text-indigo-700 px-8 py-4 rounded-xl font-bold text-lg
                  shadow-lg hover:shadow-xl hover:-translate-y-0.5 transition-all
                  duration-200">
          Start Free Today
        </a>
        <a href="#features"
           class="border-2 border-white/60 text-white px-8 py-4 rounded-xl font-semibold
                  text-lg hover:bg-white/10 transition-colors">
          Learn More
        </a>
      </div>

      <!-- SOCIAL PROOF STRIP -->
      <div class="mt-16 flex flex-wrap justify-center gap-10 text-white/70 text-sm font-medium">
        <span>✓ No credit card required</span>
        <span>✓ 14-day free trial</span>
        <span>✓ Cancel anytime</span>
      </div>
    </div>
  </section>

  <!-- FEATURES -->
  <section id="features" class="py-24 bg-gray-50">
    <div class="max-w-7xl mx-auto px-6">
      <div class="text-center mb-16">
        <h2 class="text-4xl font-extrabold text-gray-900 mb-4">
          Everything you need to succeed
        </h2>
        <p class="text-lg text-gray-500 max-w-xl mx-auto">
          {name} gives you the tools to grow faster, work smarter, and deliver
          results your customers will love.
        </p>
      </div>
      <div class="grid sm:grid-cols-2 lg:grid-cols-3 gap-8">
        {features_html}
      </div>
    </div>
  </section>

  <!-- STATS -->
  <section class="py-20 bg-indigo-600">
    <div class="max-w-7xl mx-auto px-6">
      <div class="grid grid-cols-2 md:grid-cols-4 gap-12 text-center">
        <div>
          <p class="text-5xl font-extrabold text-white">10k+</p>
          <p class="text-indigo-200 mt-1 text-sm font-medium">Happy Users</p>
        </div>
        <div>
          <p class="text-5xl font-extrabold text-white">99.9%</p>
          <p class="text-indigo-200 mt-1 text-sm font-medium">Uptime SLA</p>
        </div>
        <div>
          <p class="text-5xl font-extrabold text-white">4.9★</p>
          <p class="text-indigo-200 mt-1 text-sm font-medium">Average Rating</p>
        </div>
        <div>
          <p class="text-5xl font-extrabold text-white">24/7</p>
          <p class="text-indigo-200 mt-1 text-sm font-medium">Support</p>
        </div>
      </div>
    </div>
  </section>

  <!-- PRICING -->
  <section id="pricing" class="py-24 bg-white">
    <div class="max-w-7xl mx-auto px-6">
      <div class="text-center mb-16">
        <h2 class="text-4xl font-extrabold text-gray-900 mb-4">Simple, transparent pricing</h2>
        <p class="text-gray-500 text-lg">No hidden fees. No surprises. Cancel anytime.</p>
      </div>
      <div class="grid md:grid-cols-3 gap-8 max-w-5xl mx-auto">

        <!-- Starter -->
        <div class="border border-gray-200 rounded-2xl p-8 flex flex-col gap-4
                    hover:shadow-lg transition-shadow">
          <h3 class="text-lg font-bold text-gray-900">Starter</h3>
          <p class="text-4xl font-extrabold text-gray-900">$0
            <span class="text-base font-normal text-gray-400">/mo</span>
          </p>
          <ul class="flex flex-col gap-2 text-sm text-gray-600 flex-1">
            <li class="flex items-center gap-2">
              <span class="text-green-500">✓</span> Up to 3 projects
            </li>
            <li class="flex items-center gap-2">
              <span class="text-green-500">✓</span> Basic analytics
            </li>
            <li class="flex items-center gap-2">
              <span class="text-green-500">✓</span> Community support
            </li>
          </ul>
          <a href="#get-started"
             class="block text-center border-2 border-indigo-600 text-indigo-600
                    py-3 rounded-xl font-semibold hover:bg-indigo-50 transition-colors">
            Get Started Free
          </a>
        </div>

        <!-- Pro — highlighted -->
        <div class="gradient-cta rounded-2xl p-8 flex flex-col gap-4 shadow-2xl
                    ring-4 ring-indigo-400 ring-opacity-30 relative overflow-hidden">
          <span class="absolute top-4 right-4 bg-yellow-400 text-yellow-900
                       text-xs font-bold px-3 py-1 rounded-full uppercase tracking-wide">
            Most Popular
          </span>
          <h3 class="text-lg font-bold text-white">Pro</h3>
          <p class="text-4xl font-extrabold text-white">$29
            <span class="text-base font-normal text-white/60">/mo</span>
          </p>
          <ul class="flex flex-col gap-2 text-sm text-white/90 flex-1">
            <li class="flex items-center gap-2">
              <span class="text-white/80">✓</span> Unlimited projects
            </li>
            <li class="flex items-center gap-2">
              <span class="text-white/80">✓</span> Advanced analytics
            </li>
            <li class="flex items-center gap-2">
              <span class="text-white/80">✓</span> Priority support
            </li>
            <li class="flex items-center gap-2">
              <span class="text-white/80">✓</span> API access
            </li>
          </ul>
          <a href="#get-started"
             class="block text-center bg-white text-indigo-700 py-3 rounded-xl
                    font-bold hover:bg-indigo-50 transition-colors shadow-lg">
            Start Pro Trial
          </a>
        </div>

        <!-- Enterprise -->
        <div class="border border-gray-200 rounded-2xl p-8 flex flex-col gap-4
                    hover:shadow-lg transition-shadow">
          <h3 class="text-lg font-bold text-gray-900">Enterprise</h3>
          <p class="text-4xl font-extrabold text-gray-900">Custom</p>
          <ul class="flex flex-col gap-2 text-sm text-gray-600 flex-1">
            <li class="flex items-center gap-2">
              <span class="text-green-500">✓</span> Everything in Pro
            </li>
            <li class="flex items-center gap-2">
              <span class="text-green-500">✓</span> SSO &amp; SAML
            </li>
            <li class="flex items-center gap-2">
              <span class="text-green-500">✓</span> Dedicated manager
            </li>
            <li class="flex items-center gap-2">
              <span class="text-green-500">✓</span> SLA guarantee
            </li>
          </ul>
          <a href="#contact"
             class="block text-center border-2 border-indigo-600 text-indigo-600
                    py-3 rounded-xl font-semibold hover:bg-indigo-50 transition-colors">
            Contact Sales
          </a>
        </div>
      </div>
    </div>
  </section>

  <!-- CTA BANNER -->
  <section class="py-24 bg-gray-50">
    <div class="max-w-3xl mx-auto px-6 text-center">
      <h2 class="text-4xl font-extrabold text-gray-900 mb-4">
        Ready to get started with {name}?
      </h2>
      <p class="text-gray-500 text-lg mb-8">
        Join thousands of teams who already use {name} to grow their business.
      </p>
      <a href="#get-started"
         class="inline-block gradient-cta text-white px-10 py-4 rounded-xl font-bold
                text-lg shadow-lg hover:shadow-xl hover:-translate-y-0.5
                transition-all duration-200">
        Start Your Free Trial
      </a>
    </div>
  </section>

  <!-- CONTACT -->
  <section id="contact" class="py-24 bg-white">
    <div class="max-w-xl mx-auto px-6 text-center">
      <h2 class="text-3xl font-extrabold text-gray-900 mb-4">Get in touch</h2>
      <p class="text-gray-500 mb-8">
        Have questions? Our team is here to help you succeed.
      </p>
      <form class="flex flex-col gap-4 text-left">
        <input type="email" placeholder="Your email address"
               class="w-full border border-gray-300 rounded-xl px-5 py-3 text-sm
                      focus:outline-none focus:ring-2 focus:ring-indigo-500"/>
        <textarea rows="4" placeholder="Your message"
                  class="w-full border border-gray-300 rounded-xl px-5 py-3 text-sm
                         focus:outline-none focus:ring-2 focus:ring-indigo-500
                         resize-none"></textarea>
        <button type="submit"
                class="gradient-cta text-white py-3 rounded-xl font-bold
                       hover:opacity-90 transition-opacity">
          Send Message
        </button>
      </form>
    </div>
  </section>

  <!-- FOOTER -->
  <footer class="bg-gray-900 text-gray-400 py-12">
    <div class="max-w-7xl mx-auto px-6 flex flex-col md:flex-row items-center
                justify-between gap-4">
      <span class="text-white font-bold text-lg">{name}</span>
      <p class="text-sm">{description[:80]}</p>
      <p class="text-xs text-gray-600">
        &copy; 2025 {name}. All rights reserved.
      </p>
    </div>
  </footer>

</body>
</html>"""


def _build_landing_page_html(
    product_name: str,
    features: list[str],
    cta: str,
    colors: dict[str, str],
) -> str:
    """Build a quick single-page landing with strong CTA."""
    primary = colors["primary"]
    light = colors["light"]
    dark = colors["dark"]
    accent = colors["accent"]

    feature_items = "\n".join(f"""      <li class="flex items-start gap-3">
        <span class="mt-1 flex-shrink-0 w-5 h-5 rounded-full bg-{primary}
                     text-white text-xs flex items-center justify-center font-bold">✓</span>
        <span class="text-gray-700 text-base">{feat}</span>
      </li>""" for feat in features)

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{product_name}</title>
  <script src="https://cdn.tailwindcss.com"></script>
</head>
<body class="bg-{light} min-h-screen flex items-center justify-center px-4 py-16 font-sans antialiased">
  <div class="bg-white rounded-3xl shadow-2xl max-w-lg w-full p-10 flex flex-col gap-8 text-center">

    <div class="flex flex-col gap-3">
      <h1 class="text-4xl font-extrabold text-{dark}">{product_name}</h1>
      <p class="text-gray-500 text-base leading-relaxed">
        Everything you need, nothing you don't.
      </p>
    </div>

    <ul class="text-left flex flex-col gap-3">
{feature_items}
    </ul>

    <a href="#"
       class="block w-full bg-{primary} text-white py-4 rounded-2xl font-bold text-lg
              hover:bg-{accent} transition-colors shadow-lg">
      {cta}
    </a>

    <p class="text-gray-400 text-xs">No credit card required &bull; Free 14-day trial</p>
  </div>
</body>
</html>"""


def _build_email_html(
    subject: str,
    headline: str,
    body: str,
    cta_text: str,
    cta_url: str,
) -> str:
    """Build an HTML email template compatible with major email clients."""
    body_paragraphs = "\n".join(
        f'      <p style="margin:0 0 14px 0;color:#374151;font-size:15px;'
        f'line-height:1.7;">{para.strip()}</p>'
        for para in body.split("\n")
        if para.strip()
    )

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8"/>
  <meta name="viewport" content="width=device-width, initial-scale=1.0"/>
  <title>{subject}</title>
  <style>
    body {{ margin:0; padding:0; background:#f3f4f6; font-family: -apple-system,
           BlinkMacSystemFont, 'Segoe UI', Arial, sans-serif; }}
    .wrapper {{ max-width:600px; margin:40px auto; background:#ffffff;
                border-radius:16px; overflow:hidden;
                box-shadow:0 4px 24px rgba(0,0,0,.08); }}
    .header  {{ background:linear-gradient(135deg,#4f46e5,#7c3aed);
                padding:40px 40px 32px; text-align:center; }}
    .content {{ padding:40px; }}
    .btn     {{ display:inline-block; background:#4f46e5; color:#ffffff;
                text-decoration:none; padding:14px 36px; border-radius:10px;
                font-weight:700; font-size:15px; }}
    .footer  {{ background:#f9fafb; padding:24px 40px; text-align:center;
                color:#9ca3af; font-size:12px; }}
  </style>
</head>
<body>
  <div class="wrapper">
    <div class="header">
      <h1 style="margin:0;color:#ffffff;font-size:26px;font-weight:800;
                  letter-spacing:-0.5px;">{headline}</h1>
    </div>
    <div class="content">
{body_paragraphs}
      <div style="text-align:center;margin-top:32px;">
        <a href="{cta_url}" class="btn">{cta_text}</a>
      </div>
    </div>
    <div class="footer">
      <p style="margin:0;">{subject}</p>
      <p style="margin:6px 0 0;">You received this email because you signed up for updates.</p>
    </div>
  </div>
</body>
</html>"""
