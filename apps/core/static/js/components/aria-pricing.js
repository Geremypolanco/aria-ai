/**
 * <aria-pricing> — pricing tiers + a short objection-handling FAQ.
 * Prices are a single source of truth here and must match
 * apps/core/main.py BILLING_PLANS (cents) exactly — no annual/discount
 * toggle, because there is no annual price on the backend to charge.
 * Native <details>/<summary> for the FAQ: no JS needed, keyboard/AT free.
 */
const ARIA_PLANS = [
  {
    name: 'Free',
    price: '$0',
    sub: 'To try ARIA',
    cta: 'Start free',
    href: '/signup',
    highlight: false,
    features: ['Tasks: research, write, build, images', '15 tasks per day', '1 member'],
  },
  {
    name: 'Pro',
    price: '$29',
    period: '/mo',
    sub: 'For anyone shipping real work daily',
    cta: 'Go Pro',
    href: '/signup',
    highlight: true,
    tag: 'MOST POPULAR',
    features: [
      'Unlimited tasks',
      'The full team of 40+ AI specialists',
      'Advanced image, video & voice',
      'Autonomous execution across every connected app',
      'Expanded memory & priority AI',
    ],
  },
  {
    name: 'Business',
    price: '$99',
    period: '/mo',
    sub: 'For small teams working together',
    cta: 'Start Business',
    href: '/signup',
    highlight: false,
    features: [
      'Everything in Pro',
      'Up to 5 members, one shared workspace',
      'Invite & manage your team seats',
      'Scheduled autonomy & analytics',
      'Priority support',
    ],
  },
  {
    name: 'Scale',
    price: '$249',
    period: '/mo',
    sub: 'For growing teams that run on ARIA',
    cta: 'Start Scale',
    href: '/signup',
    highlight: false,
    features: [
      'Everything in Business',
      'Up to 15 members, one shared workspace',
      'Admin controls & higher usage limits',
      'Priority execution and support',
    ],
  },
  {
    name: 'Enterprise',
    price: 'Custom',
    sub: 'For organizations with security & scale needs',
    cta: 'Contact sales',
    href: 'mailto:litesaraph@gmail.com?subject=ARIA%20Enterprise',
    highlight: false,
    features: [
      'Unlimited members',
      'SSO & centralized administration',
      'Security review & custom terms',
      'Dedicated support',
    ],
  },
];

const ARIA_FAQ = [
  {
    q: 'Can I cancel any time?',
    a: 'Yes. Cancel from Settings whenever you like — you keep access through the end of the billing period you already paid for, no retention flow, no phone call.',
  },
  {
    q: "What counts against the Free plan's limit?",
    a: 'Each research, write, image or publish task ARIA runs counts as one message. There is no limit on how many channels you connect.',
  },
  {
    q: 'Do you refund if it’s not for me?',
    a: 'Yes — see our refund policy for the exact window and process.',
    linkHref: '/legal/refund-policy',
    linkText: 'Refund policy →',
  },
  {
    q: 'Does ARIA do anything without my approval?',
    a: 'No. Every mission ends with you reviewing the result — you approve before anything goes out to a connected tool, unless you explicitly turn on scheduled autonomy.',
  },
];

const CHECK_ICON = `<svg class="mt-0.5 h-4 w-4 flex-none text-emerald-600" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12l4 4L19 7"/></svg>`;
const CHEVRON_ICON = `<svg class="h-4 w-4 flex-none text-stone-500 transition-transform duration-300 group-open:rotate-180" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M6 9l6 6 6-6"/></svg>`;

class AriaPricing extends HTMLElement {
  connectedCallback() {
    this.className = 'block';
    this.innerHTML = `
      <div class="mx-auto max-w-2xl text-center" data-reveal>
        <span class="text-xs font-bold uppercase tracking-widest text-emerald-700">Pricing</span>
        <h2 class="mt-3 text-[clamp(1.9rem,3.6vw,2.75rem)] font-semibold tracking-tight text-stone-900">Simple, honest pricing.</h2>
        <p class="mt-4 text-lg text-stone-600">Start free. Upgrade when ARIA is doing real work for you. Cancel anytime.</p>
      </div>

      <div class="mx-auto mt-14 grid max-w-6xl gap-5 sm:grid-cols-2 lg:grid-cols-5 lg:items-stretch">
        ${ARIA_PLANS.map((plan, i) => this.planCard(plan, i)).join('')}
      </div>

      <div class="mx-auto mt-24 max-w-2xl" data-reveal>
        <h3 class="text-center text-xl font-semibold text-stone-900">Questions, answered</h3>
        <div class="mt-8 divide-y divide-stone-200 rounded-2xl border border-stone-200 bg-white">
          ${ARIA_FAQ.map((item) => this.faqRow(item)).join('')}
        </div>
      </div>
    `;
  }

  planCard(plan, i) {
    const ring = plan.highlight
      ? 'border-2 border-stone-900 shadow-2xl shadow-stone-900/10 md:scale-[1.04]'
      : 'border border-stone-200 shadow-sm';
    const ctaClass = plan.highlight
      ? 'bg-stone-900 text-white hover:bg-stone-800 shadow-lg shadow-stone-900/15'
      : 'border border-stone-300 bg-white text-stone-900 hover:border-stone-400';
    return `
      <div data-reveal style="--d:${i * 90}ms" class="relative rounded-3xl bg-white p-8 transition-transform duration-300 ease-out hover:-translate-y-1 ${ring}">
        ${plan.tag ? `<span class="absolute -top-3 left-1/2 -translate-x-1/2 rounded-full bg-stone-900 px-3.5 py-1 text-[11px] font-bold tracking-wide text-white">${plan.tag}</span>` : ''}
        <h3 class="text-sm font-semibold text-stone-500">${plan.name}</h3>
        <div class="mt-2 text-4xl font-bold tracking-tight text-stone-900">${plan.price}${plan.period ? `<small class="text-base font-medium text-stone-500">${plan.period}</small>` : ''}</div>
        <p class="mt-1 text-sm text-stone-500">${plan.sub}</p>
        <a href="${plan.href}" class="mt-6 block rounded-full px-5 py-3 text-center text-sm font-semibold transition-all duration-300 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-400 active:scale-[.98] ${ctaClass}">${plan.cta}</a>
        <ul class="mt-7 space-y-3">
          ${plan.features.map((f) => `<li class="flex gap-2.5 text-sm text-stone-700">${CHECK_ICON}<span>${f}</span></li>`).join('')}
        </ul>
      </div>
    `;
  }

  faqRow(item) {
    return `
      <details class="group px-6 py-5">
        <summary class="flex cursor-pointer list-none items-center justify-between gap-4 font-medium text-stone-900 marker:content-none [&::-webkit-details-marker]:hidden">
          ${item.q}
          ${CHEVRON_ICON}
        </summary>
        <p class="mt-3 text-sm leading-relaxed text-stone-600">
          ${item.a}
          ${item.linkHref ? `<a href="${item.linkHref}" class="font-semibold text-emerald-700 hover:underline">${item.linkText}</a>` : ''}
        </p>
      </details>
    `;
  }
}

customElements.define('aria-pricing', AriaPricing);
