/**
 * <aria-hero> — the landing page's hero section.
 * Light-DOM custom element (no shadow root): Tailwind's runtime engine scans
 * the live document for class names, and can't see across a shadow boundary,
 * so encapsulation here is at the JS/module level, not the style level.
 *
 * Visual language: warm off-white canvas, near-black editorial type, a soft
 * organic pastel wash (not a neon glow) and a solid black pill CTA — the
 * OpenAI.com school of design rather than the "dark mode + neon blobs" SaaS
 * cliché.
 */
class AriaHero extends HTMLElement {
  connectedCallback() {
    this.className = 'aria-grain relative overflow-hidden bg-stone-50 pb-20 pt-32 text-center';
    this.innerHTML = `
      <div aria-hidden="true" class="pointer-events-none absolute inset-0">
        <div class="absolute -top-56 left-1/2 h-[720px] w-[1100px] -translate-x-1/2 rounded-[100%] bg-gradient-to-b from-emerald-100 via-teal-50 to-transparent opacity-90"></div>
        <div class="absolute top-10 right-[8%] h-64 w-64 rounded-full bg-amber-100/70 blur-3xl"></div>
        <div class="absolute top-40 left-[6%] h-56 w-56 rounded-full bg-sky-100/70 blur-3xl"></div>
      </div>

      <div class="relative z-10 mx-auto max-w-5xl px-6">
        <span data-reveal class="inline-flex items-center gap-2 rounded-full border border-stone-200 bg-white/80 px-4 py-2 text-xs font-semibold text-stone-600 shadow-sm shadow-stone-900/5 backdrop-blur">
          <span class="h-1.5 w-1.5 rounded-full bg-emerald-500"></span>
          One AI, every integration · for whatever you do
        </span>

        <h1 data-reveal style="--d:80ms" class="mx-auto mt-8 max-w-[17ch] text-[clamp(2.75rem,6.4vw,4.75rem)] font-semibold leading-[1.04] tracking-[-0.03em] text-stone-900">
          Give it the job.<br />
          <span class="text-emerald-700">It picks the tools and finishes it.</span>
        </h1>

        <p data-reveal style="--d:160ms" class="mx-auto mt-6 max-w-xl text-lg leading-relaxed text-stone-600">
          ARIA researches, writes, builds and ships — connected to Gmail, Slack, Notion, Shopify, Stripe and 9,000+ apps through Zapier. Marketer or engineer, founder or ops team: you approve, it executes.
        </p>

        <div data-reveal style="--d:240ms" class="mt-9 flex flex-wrap justify-center gap-3">
          <a
            href="/signup"
            class="group inline-flex items-center gap-2 rounded-full bg-stone-900 px-7 py-3.5 text-sm font-semibold text-white shadow-lg shadow-stone-900/15 transition-all duration-300 ease-out hover:-translate-y-0.5 hover:bg-stone-800 hover:shadow-xl hover:shadow-stone-900/20 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-900 active:translate-y-0 active:scale-[.98]"
          >
            Get started — no card
            <svg class="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          </a>
          <a
            href="#watch"
            class="inline-flex items-center gap-2 rounded-full border border-stone-300 bg-white px-7 py-3.5 text-sm font-semibold text-stone-900 transition-all duration-300 hover:-translate-y-0.5 hover:border-stone-400 hover:shadow-md focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-400 active:translate-y-0"
          >
            See it run
          </a>
        </div>

        <div id="watch" class="relative mx-auto mt-16 max-w-3xl text-left">
          <div class="relative overflow-hidden rounded-3xl border border-stone-200 bg-white shadow-2xl shadow-stone-900/10">
            <aria-agent-dashboard></aria-agent-dashboard>
          </div>
        </div>
      </div>
    `;
  }
}

customElements.define('aria-hero', AriaHero);
