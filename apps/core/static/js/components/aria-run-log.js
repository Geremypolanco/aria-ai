/**
 * <aria-run-log> — the live "watch it work" panel embedded in the hero.
 * State machine: skeleton -> typing the goal -> steps resolving one by one
 * (pending -> active -> done) -> deliverable card -> loop to next mission.
 * Pauses on hover/focus and when the tab is hidden; replaced by a static
 * "done" frame under prefers-reduced-motion.
 */
const ARIA_MISSIONS = [
  {
    goal: "Research today's AI trends and ship a launch reel",
    title: 'Launch reel · AI trends',
    steps: [
      'Read 12 live sources',
      'Wrote the script + caption',
      'Generated hero image + 20s voiceover',
      'Published to 3 channels',
    ],
    file: 'launch-reel.mp4',
    meta: '1080×1920 · 22s · ready',
    time: '1m 12s',
  },
  {
    goal: "Turn this week's Stripe numbers into a report for the team",
    title: 'Weekly report · revenue',
    steps: [
      'Pulled the numbers from Stripe',
      'Found the trend worth flagging',
      'Wrote the summary + chart',
      'Shared it in Slack',
    ],
    file: 'weekly-report.pdf',
    meta: '3 pages · shared in #team',
    time: '1m 02s',
  },
  {
    goal: 'List the new product on our Shopify store',
    title: 'Product listing · Shopify',
    steps: [
      'Wrote the product description',
      'Generated the product photos',
      'Set pricing and inventory',
      'Published to the store',
    ],
    file: 'product-listing',
    meta: 'Live on Shopify · ready',
    time: '48s',
  },
  {
    goal: 'Build a waitlist page for the new feature',
    title: 'Waitlist page · new feature',
    steps: [
      'Drafted the copy and layout',
      'Generated the hero image',
      'Wrote the working HTML/CSS',
      'Deployed it live',
    ],
    file: 'waitlist.html',
    meta: 'Live · ready to share',
    time: '2m 20s',
  },
];

const ARIA_CHECK_ICON = `<svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3.4" stroke-linecap="round" stroke-linejoin="round"><path d="M20 6 9 17l-5-5"/></svg>`;

const STATUS_RUNNING =
  'inline-flex items-center gap-1.5 rounded-full border border-teal-200 bg-teal-50 px-2.5 py-1 text-[11px] font-bold text-teal-700';
const STATUS_DONE =
  'inline-flex items-center gap-1.5 rounded-full border border-emerald-200 bg-emerald-50 px-2.5 py-1 text-[11px] font-bold text-emerald-700';

class AriaRunLog extends HTMLElement {
  connectedCallback() {
    this._reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this._paused = false;
    this._mi = 0;
    this._timers = [];

    this._onEnter = () => { this._paused = true; };
    this._onLeave = () => { this._paused = false; };
    this._onVisibility = () => { this._paused = document.hidden; };
    this.addEventListener('mouseenter', this._onEnter);
    this.addEventListener('mouseleave', this._onLeave);
    document.addEventListener('visibilitychange', this._onVisibility);

    if (this._reduced) {
      this.paintFinal(ARIA_MISSIONS[0]);
      return;
    }
    this.render();
    this._timers.push(setTimeout(() => this.play(), 600));
  }

  disconnectedCallback() {
    this._timers.forEach(clearTimeout);
    document.removeEventListener('visibilitychange', this._onVisibility);
  }

  sleep(ms) {
    return new Promise((resolve) => {
      this._timers.push(setTimeout(resolve, ms));
    });
  }

  // Same total wait, but ticks in small slices so hover/tab-hidden can hold it.
  async holdFor(ms) {
    const slice = 80;
    let remaining = ms;
    while (remaining > 0) {
      if (!this._paused) remaining -= slice;
      await this.sleep(slice);
    }
  }

  render() {
    this.className = 'block p-6';
    this.innerHTML = `
      <div class="flex items-center gap-2 border-b border-stone-100 pb-4 font-mono text-xs text-stone-500">
        <span class="h-2 w-2 rounded-full bg-emerald-500"></span>
        aria · live run
        <button
          type="button"
          data-restart
          aria-label="Replay this run"
          class="ml-auto inline-flex items-center gap-1 rounded-full border border-stone-200 px-2.5 py-1 text-[11px] text-stone-500 transition-colors hover:border-stone-400 hover:text-stone-800 focus-visible:outline focus-visible:outline-2 focus-visible:outline-stone-400"
        >
          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"><path d="M4 4v5h5M20 20v-5h-5"/><path d="M5.5 9a7 7 0 0 1 12.3-2.5M18.5 15a7 7 0 0 1-12.3 2.5"/></svg>
          Replay
        </button>
      </div>

      <div class="mt-4 flex items-center gap-2 rounded-xl border border-stone-200 bg-stone-50 px-4 py-3 font-mono text-sm text-stone-800">
        <span class="text-emerald-600">›</span>
        <span data-goal></span><span data-caret class="ml-0.5 inline-block h-4 w-[2px] animate-blink bg-emerald-600 align-middle"></span>
      </div>

      <div class="mt-5 flex items-center justify-between">
        <b data-title class="text-sm font-semibold text-stone-900"></b>
        <span data-status class="${STATUS_RUNNING}">
          <span class="h-1.5 w-1.5 animate-pulse rounded-full bg-teal-500"></span>
          <span data-status-text>Queued</span>
        </span>
      </div>

      <ul data-steps class="mt-4 space-y-3"></ul>

      <div data-deliver class="mt-4 flex items-center gap-3 rounded-xl border border-stone-200 bg-stone-50 p-3 opacity-0 transition-opacity duration-500">
        <div data-thumb class="h-12 w-16 flex-none rounded-lg bg-gradient-to-br from-emerald-400 to-teal-500"></div>
        <div class="min-w-0">
          <b data-fname class="block truncate text-sm text-stone-900"></b>
          <span data-fmeta class="text-xs text-stone-500"></span>
        </div>
        <span class="ml-auto flex-none text-xs font-bold text-emerald-700">Open →</span>
      </div>
    `;

    this.$goal = this.querySelector('[data-goal]');
    this.$caret = this.querySelector('[data-caret]');
    this.$title = this.querySelector('[data-title]');
    this.$status = this.querySelector('[data-status]');
    this.$statusText = this.querySelector('[data-status-text]');
    this.$steps = this.querySelector('[data-steps]');
    this.$deliver = this.querySelector('[data-deliver]');
    this.$fname = this.querySelector('[data-fname]');
    this.$fmeta = this.querySelector('[data-fmeta]');
    this.querySelector('[data-restart]').addEventListener('click', () => {
      this._timers.forEach(clearTimeout);
      this._timers = [];
      this.play(this._mi);
    });
  }

  stepRow(label) {
    const li = document.createElement('li');
    li.className = 'flex items-center gap-3 text-sm';
    li.innerHTML = `
      <span data-dot class="grid h-5 w-5 flex-none place-items-center rounded-full border border-stone-300 bg-stone-100"></span>
      <span data-label class="h-3.5 w-40 animate-pulse rounded bg-stone-200"></span>
    `;
    li._label = label;
    return li;
  }

  paintFinal(mission) {
    this.render();
    this.$goal.textContent = mission.goal;
    this.$caret.style.display = 'none';
    this.$title.textContent = mission.title;
    this.$statusText.textContent = `Done · ${mission.time}`;
    this.$status.className = STATUS_DONE;

    mission.steps.forEach((label) => {
      const li = this.stepRow(label);
      const dot = li.querySelector('[data-dot]');
      dot.innerHTML = ARIA_CHECK_ICON;
      dot.className = 'grid h-5 w-5 flex-none place-items-center rounded-full border border-emerald-500 bg-emerald-500 text-white';
      const lbl = li.querySelector('[data-label]');
      lbl.textContent = label;
      lbl.className = 'text-stone-700';
      this.$steps.appendChild(li);
    });

    this.$deliver.classList.remove('opacity-0');
    this.$fname.textContent = mission.file;
    this.$fmeta.textContent = mission.meta;
  }

  async play(startAt) {
    this._mi = startAt !== undefined ? startAt : this._mi;
    const mission = ARIA_MISSIONS[this._mi % ARIA_MISSIONS.length];

    this.render();
    this.$title.textContent = mission.title;
    const rows = mission.steps.map((label) => this.stepRow(label));
    rows.forEach((row) => this.$steps.appendChild(row));

    await this.holdFor(500);
    for (let i = 0; i <= mission.goal.length; i++) {
      this.$goal.textContent = mission.goal.slice(0, i);
      await this.sleep(28);
    }
    this.$caret.style.display = 'none';
    this.$statusText.textContent = 'Running';
    await this.holdFor(400);

    for (let i = 0; i < rows.length; i++) {
      const row = rows[i];
      const dot = row.querySelector('[data-dot]');
      const label = row.querySelector('[data-label]');

      dot.className = 'relative grid h-5 w-5 flex-none place-items-center rounded-full border-2 border-teal-400 bg-white';
      dot.innerHTML = `<span class="absolute inset-1 animate-pulse rounded-full bg-teal-400"></span>`;
      label.textContent = row._label;
      label.className = 'font-medium text-stone-900';

      await this.holdFor(i === 2 ? 1200 : 800); // media generation takes a genuine beat longer

      dot.innerHTML = ARIA_CHECK_ICON;
      dot.className = 'grid h-5 w-5 flex-none place-items-center rounded-full border border-emerald-500 bg-emerald-500 text-white';
      label.className = 'text-stone-700';

      if (i === 2) {
        this.$deliver.classList.remove('opacity-0');
        this.$fname.textContent = mission.file;
        this.$fmeta.textContent = mission.meta;
      }
      await this.holdFor(250);
    }

    this.$statusText.textContent = `Done · ${mission.time}`;
    this.$status.className = STATUS_DONE;

    await this.holdFor(4200);
    this._mi++;
    this.play();
  }
}

customElements.define('aria-run-log', AriaRunLog);
