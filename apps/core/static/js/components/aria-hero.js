/**
 * <aria-hero> — the landing page's hero section.
 * Light-DOM custom element (no shadow root): Tailwind's runtime engine scans
 * the live document for class names, and can't see across a shadow boundary,
 * so encapsulation here is at the JS/module level, not the style level.
 */
class AriaHero extends HTMLElement {
  connectedCallback() {
    this.className = 'relative overflow-hidden bg-zinc-950 pb-24 pt-36 text-center';
    this.innerHTML = `
      <div aria-hidden="true" class="pointer-events-none absolute inset-0">
        <div class="absolute -top-40 -left-32 h-[560px] w-[560px] rounded-full bg-cyan-500/25 blur-[110px] animate-drift-a"></div>
        <div class="absolute -top-24 -right-32 h-[520px] w-[520px] rounded-full bg-violet-500/25 blur-[110px] animate-drift-b"></div>
        <div class="absolute inset-0 bg-[linear-gradient(rgba(255,255,255,.05)_1px,transparent_1px),linear-gradient(90deg,rgba(255,255,255,.05)_1px,transparent_1px)] bg-[size:48px_48px] [mask-image:radial-gradient(120%_70%_at_50%_0%,#000,transparent_72%)]"></div>
      </div>

      <div class="relative z-10 mx-auto max-w-5xl px-6">
        <span data-reveal class="inline-flex items-center gap-2 rounded-full border border-zinc-800/80 bg-zinc-900/60 px-4 py-2 text-xs font-semibold text-zinc-300 backdrop-blur-md">
          <span class="relative flex h-2 w-2">
            <span class="absolute inline-flex h-full w-full animate-ping rounded-full bg-cyan-400 opacity-60"></span>
            <span class="relative inline-flex h-2 w-2 rounded-full bg-cyan-400"></span>
          </span>
          Autonomous content engine · for founders &amp; creators
        </span>

        <h1 data-reveal style="--d:80ms" class="mx-auto mt-7 max-w-[15ch] text-[clamp(2.5rem,7.5vw,5.5rem)] font-extrabold leading-[0.98] tracking-tight text-white">
          One idea in.<br />
          <span class="bg-gradient-to-r from-cyan-300 via-sky-300 to-violet-400 bg-clip-text text-transparent">A week of content, published.</span>
        </h1>

        <p data-reveal style="--d:160ms" class="mx-auto mt-6 max-w-xl text-lg leading-relaxed text-zinc-400">
          ARIA researches the trend, writes the posts, designs the images and video, and publishes across your channels. You approve — it ships.
        </p>

        <div data-reveal style="--d:240ms" class="mt-9 flex flex-wrap justify-center gap-3">
          <a
            href="/signup"
            class="group inline-flex items-center gap-2 rounded-full bg-gradient-to-r from-cyan-400 to-violet-500 px-7 py-3.5 text-sm font-semibold text-zinc-950 shadow-glow transition-transform duration-300 ease-out hover:-translate-y-0.5 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-cyan-300 active:translate-y-0 active:scale-[.98]"
          >
            Get started — no card
            <svg class="h-4 w-4 transition-transform duration-300 group-hover:translate-x-0.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M5 12h14M13 6l6 6-6 6" /></svg>
          </a>
          <a
            href="#watch"
            class="inline-flex items-center gap-2 rounded-full border border-zinc-700/80 bg-zinc-900/50 px-7 py-3.5 text-sm font-semibold text-zinc-100 backdrop-blur-md transition-all duration-300 hover:-translate-y-0.5 hover:border-zinc-500 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-zinc-400 active:translate-y-0"
          >
            See it run
          </a>
        </div>

        <div id="watch" class="relative mx-auto mt-16 max-w-3xl">
          <div class="gradient-border rounded-3xl p-px shadow-2xl shadow-black/60">
            <div class="overflow-hidden rounded-[calc(1.5rem-1px)] bg-zinc-900/70 backdrop-blur-xl">
              <aria-run-log></aria-run-log>
            </div>
          </div>
        </div>
      </div>
    `;
  }
}

customElements.define('aria-hero', AriaHero);
