/**
 * <aria-agent-dashboard> — the landing page's "watch it work" panel, v2.
 *
 * Positioning shift: ARIA isn't a single-thread task runner anymore, it's an
 * orchestrator of parallel autonomous workers with real spending authority —
 * gated by human-in-the-loop (HITL) approval whenever a worker needs to
 * spend real money. This replaces the old single-mission <aria-run-log> with
 * three independent worker lanes (Legal / Ops / HR) running concurrently
 * against one mission, a wallet balance that actually moves, and a
 * glassmorphism approval card that appears the moment a worker needs to
 * spend.
 *
 * Same constraints as the component it replaces: light-DOM (no shadow root,
 * so Tailwind's runtime scanner can see these classes), pauses on
 * hover/focus/hidden-tab, static final frame under prefers-reduced-motion.
 */
const MISSION_LABEL = 'Mission: Launch a biotech startup';

const WORKERS = [
  {
    id: 'legal',
    name: 'Legal Worker',
    accent: 'sky',
    icon: `<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 3v18M5 8l-3 6a3 3 0 0 0 6 0l-3-6ZM19 8l-3 6a3 3 0 0 0 6 0l-3-6ZM5 8h14M9 21h6"/></svg>`,
    steps: [
      { label: 'Drafting LLC formation documents', ms: 1500 },
      { label: 'Filing incorporation with Delaware', ms: 1700 },
      { label: 'Drafting founder equity agreement', ms: 1400 },
      { label: 'Filing the trademark application', ms: 1300 },
    ],
  },
  {
    id: 'ops',
    name: 'Ops Worker',
    accent: 'emerald',
    icon: `<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><circle cx="12" cy="12" r="3"/><path d="M19.4 15a1.65 1.65 0 0 0 .33 1.82l.06.06a2 2 0 1 1-2.83 2.83l-.06-.06a1.65 1.65 0 0 0-1.82-.33 1.65 1.65 0 0 0-1 1.51V21a2 2 0 0 1-4 0v-.09A1.65 1.65 0 0 0 8 19.4a1.65 1.65 0 0 0-1.82.33l-.06.06a2 2 0 1 1-2.83-2.83l.06-.06a1.65 1.65 0 0 0 .33-1.82 1.65 1.65 0 0 0-1.51-1H2a2 2 0 0 1 0-4h.09A1.65 1.65 0 0 0 3.6 8a1.65 1.65 0 0 0-.33-1.82l-.06-.06a2 2 0 1 1 2.83-2.83l.06.06a1.65 1.65 0 0 0 1.82.33H8a1.65 1.65 0 0 0 1-1.51V2a2 2 0 0 1 4 0v.09a1.65 1.65 0 0 0 1 1.51 1.65 1.65 0 0 0 1.82-.33l.06-.06a2 2 0 1 1 2.83 2.83l-.06.06a1.65 1.65 0 0 0-.33 1.82V8a1.65 1.65 0 0 0 1.51 1H22a2 2 0 0 1 0 4h-.09a1.65 1.65 0 0 0-1.51 1z"/></svg>`,
    steps: [
      { label: 'Checking domain availability', ms: 1300 },
      {
        label: 'Buy domain ariahealth.com',
        ms: 900,
        spend: { amount: 14.99, vendor: 'Namecheap', item: 'ariahealth.com domain' },
      },
      { label: 'Provisioning cloud infrastructure', ms: 1800 },
      { label: 'Setting up company email + Slack', ms: 1300 },
    ],
  },
  {
    id: 'hr',
    name: 'HR Worker',
    accent: 'amber',
    icon: `<svg class="h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round"><path d="M17 21v-2a4 4 0 0 0-4-4H5a4 4 0 0 0-4 4v2"/><circle cx="9" cy="7" r="4"/><path d="M23 21v-2a4 4 0 0 0-3-3.87M16 3.13a4 4 0 0 1 0 7.75"/></svg>`,
    steps: [
      { label: 'Drafting the Lab Ops Lead job description', ms: 1400 },
      { label: 'Sourcing candidates on LinkedIn', ms: 1900 },
      { label: 'Scheduling 5 interviews', ms: 1200 },
      { label: 'Sending the offer letter', ms: 1000 },
    ],
  },
];

const ACCENTS = {
  sky: { chip: 'bg-sky-50 text-sky-700', dot: 'bg-sky-500', bar: 'bg-sky-400' },
  emerald: { chip: 'bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500', bar: 'bg-emerald-400' },
  amber: { chip: 'bg-amber-50 text-amber-700', dot: 'bg-amber-500', bar: 'bg-amber-400' },
};

const START_BALANCE = 500.0;
const fmt = (n) => `$${n.toFixed(2)}`;

class AriaAgentDashboard extends HTMLElement {
  connectedCallback() {
    this._reduced = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
    this._paused = false;
    this._timers = [];
    this._balance = START_BALANCE;
    this._activityGen = 0;
    this._pendingApproval = null; // { resolve } while the HITL card is showing

    this._onEnter = () => { this._paused = true; };
    this._onLeave = () => { this._paused = false; };
    this._onVisibility = () => { this._paused = document.hidden; };
    this.addEventListener('mouseenter', this._onEnter);
    this.addEventListener('mouseleave', this._onLeave);
    document.addEventListener('visibilitychange', this._onVisibility);

    this.render();

    if (this._reduced) {
      this.paintFinal();
      return;
    }
    WORKERS.forEach((worker, i) => {
      this._timers.push(setTimeout(() => this.runLane(worker), 500 + i * 450));
    });
  }

  disconnectedCallback() {
    this._timers.forEach(clearTimeout);
    document.removeEventListener('visibilitychange', this._onVisibility);
  }

  sleep(ms) {
    return new Promise((resolve) => { this._timers.push(setTimeout(resolve, ms)); });
  }

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
      <div class="flex flex-wrap items-center gap-2 border-b border-stone-100 pb-4">
        <span class="h-2 w-2 flex-none rounded-full bg-emerald-500"></span>
        <span class="font-mono text-xs text-stone-500">${MISSION_LABEL}</span>
        <span data-wallet-chip class="ml-auto inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-900 px-3 py-1 text-[11px] font-bold text-white">
          <svg class="h-3 w-3" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><rect x="2" y="6" width="20" height="13" rx="2"/><path d="M2 10h20M6 15h2"/></svg>
          <span data-wallet-amount>${fmt(this._balance)}</span> available
        </span>
      </div>

      <div data-lanes class="relative mt-4 space-y-4"></div>

      <div class="mt-5 flex flex-wrap items-center justify-between gap-3 rounded-2xl border border-stone-200 bg-stone-50 px-4 py-3">
        <div>
          <p class="text-[11px] font-semibold uppercase tracking-wide text-stone-500">Agent wallet</p>
          <p class="mt-0.5 text-xl font-bold text-stone-900"><span data-balance>${fmt(this._balance)}</span></p>
          <p data-activity class="mt-0.5 h-4 text-xs text-stone-500"></p>
        </div>
        <a href="/signup" class="inline-flex items-center gap-1.5 rounded-full bg-emerald-600 px-4 py-2 text-xs font-bold text-white shadow-sm shadow-emerald-900/20 transition-colors hover:bg-emerald-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-emerald-600">
          <svg class="h-3.5 w-3.5" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.4" stroke-linecap="round" stroke-linejoin="round"><path d="M12 5v14M5 12h14"/></svg>
          Add funds
        </a>
      </div>

      <p data-live class="sr-only" aria-live="polite" aria-atomic="true"></p>

      <div
        data-hitl
        inert
        aria-hidden="true"
        class="pointer-events-none absolute inset-x-4 bottom-4 z-10 translate-y-3 rounded-2xl border border-amber-200/70 bg-white/70 p-4 opacity-0 shadow-2xl shadow-amber-900/10 ring-1 ring-white/40 backdrop-blur-xl transition-all duration-300 ease-out"
      >
        <div class="flex items-start gap-3">
          <span class="relative grid h-8 w-8 flex-none place-items-center rounded-full bg-amber-100 text-amber-700">
            <span class="absolute inset-0 animate-ping rounded-full bg-amber-300/60"></span>
            <svg class="relative h-4 w-4" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round"><path d="M12 9v4M12 17h.01M10.29 3.86 1.82 18a2 2 0 0 0 1.71 3h16.94a2 2 0 0 0 1.71-3L13.71 3.86a2 2 0 0 0-3.42 0Z"/></svg>
          </span>
          <div class="min-w-0 flex-1">
            <p class="text-[11px] font-bold uppercase tracking-wide text-amber-700">Approval needed</p>
            <p data-hitl-msg class="mt-0.5 text-sm leading-snug text-stone-800"></p>
          </div>
        </div>
        <div class="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-amber-900/10 pt-3">
          <span class="text-xs text-stone-600">Funds available: <b data-hitl-balance>${fmt(this._balance)}</b></span>
          <div class="flex gap-2">
            <button type="button" data-deny class="rounded-full border border-stone-300 bg-white/80 px-3 py-1.5 text-xs font-semibold text-stone-600 transition-colors hover:border-stone-400 hover:text-stone-900 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-stone-400">Deny</button>
            <button type="button" data-approve class="rounded-full bg-amber-600 px-4 py-1.5 text-xs font-bold text-white shadow-sm shadow-amber-900/30 transition-colors hover:bg-amber-700 focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-amber-700">Approve spend</button>
          </div>
        </div>
      </div>
    `;

    this.$lanes = this.querySelector('[data-lanes]');
    this.$balance = this.querySelector('[data-balance]');
    this.$walletAmount = this.querySelector('[data-wallet-amount]');
    this.$activity = this.querySelector('[data-activity]');
    this.$live = this.querySelector('[data-live]');
    this.$hitl = this.querySelector('[data-hitl]');
    this.$hitlMsg = this.querySelector('[data-hitl-msg]');
    this.$hitlBalance = this.querySelector('[data-hitl-balance]');
    this.$hitl.querySelector('[data-approve]').addEventListener('click', () => this._resolveApproval(true));
    this.$hitl.querySelector('[data-deny]').addEventListener('click', () => this._resolveApproval(false));

    this._laneEls = {};
    WORKERS.forEach((worker) => {
      const accent = ACCENTS[worker.accent];
      const lane = document.createElement('div');
      lane.className = 'rounded-xl border border-stone-200 bg-white p-3';
      lane.innerHTML = `
        <div class="flex items-center gap-2">
          <span class="grid h-7 w-7 flex-none place-items-center rounded-full ${accent.chip}">${worker.icon}</span>
          <span class="text-sm font-semibold text-stone-900">${worker.name}</span>
          <span data-pill class="ml-auto inline-flex items-center gap-1.5 rounded-full border border-stone-200 bg-stone-50 px-2.5 py-1 text-[11px] font-bold text-stone-500">
            <span class="h-1.5 w-1.5 rounded-full bg-stone-300"></span>
            <span data-pill-text>Queued</span>
          </span>
        </div>
        <p data-step class="mt-2 truncate text-sm text-stone-700">Waiting to start…</p>
        <div class="mt-2 h-1 overflow-hidden rounded-full bg-stone-100">
          <div data-bar class="h-full ${accent.bar}" style="width:0%"></div>
        </div>
      `;
      this.$lanes.appendChild(lane);
      this._laneEls[worker.id] = {
        pill: lane.querySelector('[data-pill]'),
        pillText: lane.querySelector('[data-pill-text]'),
        step: lane.querySelector('[data-step]'),
        bar: lane.querySelector('[data-bar]'),
      };
    });
  }

  setPill(worker, mode) {
    const el = this._laneEls[worker.id];
    const modes = {
      queued: { cls: 'border-stone-200 bg-stone-50 text-stone-500', dot: 'bg-stone-300', text: 'Queued' },
      running: { cls: 'border-teal-200 bg-teal-50 text-teal-700', dot: 'bg-teal-500 animate-pulse', text: 'Working' },
      waiting: { cls: 'border-amber-200 bg-amber-50 text-amber-700', dot: 'bg-amber-500 animate-pulse', text: 'Awaiting approval' },
      done: { cls: 'border-emerald-200 bg-emerald-50 text-emerald-700', dot: 'bg-emerald-500', text: 'Cycle complete' },
    }[mode];
    el.pill.className = `ml-auto inline-flex items-center gap-1.5 rounded-full border px-2.5 py-1 text-[11px] font-bold ${modes.cls}`;
    el.pill.querySelector('span:not([data-pill-text])')?.remove();
    el.pill.insertAdjacentHTML('afterbegin', `<span class="h-1.5 w-1.5 rounded-full ${modes.dot}"></span>`);
    el.pillText.textContent = modes.text;
  }

  async runLane(worker) {
    const el = this._laneEls[worker.id];
    this.setPill(worker, 'running');
    for (;;) {
      for (const step of worker.steps) {
        el.step.textContent = `${step.label}…`;
        el.bar.style.transition = 'none';
        el.bar.style.width = '0%';
        // eslint-disable-next-line no-unused-expressions
        el.bar.offsetHeight; // force reflow so the width reset applies before animating
        el.bar.style.transition = `width ${step.ms}ms linear`;
        el.bar.style.width = '100%';

        if (step.spend) {
          await this.holdFor(step.ms * 0.55);
          this.setPill(worker, 'waiting');
          const approved = await this.requestApproval(worker, step);
          this.setPill(worker, 'running');
          el.step.textContent = approved
            ? `${step.label} — approved`
            : `${step.label} — skipped (denied)`;
          await this.holdFor(step.ms * 0.3);
        } else {
          await this.holdFor(step.ms);
        }
      }
      this.setPill(worker, 'done');
      await this.holdFor(2600);
      this.setPill(worker, 'running');
    }
  }

  requestApproval(worker, step) {
    return new Promise((resolve) => {
      this.$hitlMsg.innerHTML = `<b>${worker.name}</b> wants to buy <b>${step.spend.item}</b> from ${step.spend.vendor} for <b>${fmt(step.spend.amount)}</b>`;
      this.$hitlBalance.textContent = fmt(this._balance);
      this.$hitl.classList.remove('pointer-events-none', 'opacity-0', 'translate-y-3');
      this.$hitl.removeAttribute('inert');
      this.$hitl.setAttribute('aria-hidden', 'false');
      this.announce(
        `${worker.name} needs approval to spend ${fmt(step.spend.amount)} on ${step.spend.item}.`
      );
      this._pendingApproval = { worker, step, resolve, settled: false };

      // Passive visitors still see the loop move — auto-approve if nobody clicks.
      const auto = setTimeout(() => this._resolveApproval(true), 4000);
      this._timers.push(auto);
      this._pendingApproval.autoTimer = auto;
    });
  }

  announce(text) {
    // Re-set even for repeated text so assistive tech re-announces it (a
    // live region only fires on an actual text change).
    this.$live.textContent = '';
    this._timers.push(setTimeout(() => { this.$live.textContent = text; }, 30));
  }

  _resolveApproval(approved) {
    const pending = this._pendingApproval;
    if (!pending || pending.settled) return;
    pending.settled = true;
    clearTimeout(pending.autoTimer);

    this.$hitl.classList.add('pointer-events-none', 'opacity-0', 'translate-y-3');
    this.$hitl.setAttribute('inert', '');
    this.$hitl.setAttribute('aria-hidden', 'true');

    const gen = ++this._activityGen;
    if (approved) {
      this._balance -= pending.step.spend.amount;
      // This demo loops forever — reset the wallet once it can no longer
      // cover the next cycle's purchase instead of drifting negative.
      if (this._balance < pending.step.spend.amount) {
        this._balance = START_BALANCE;
      }
      this.$balance.textContent = fmt(this._balance);
      this.$walletAmount.textContent = fmt(this._balance);
      this.$activity.textContent = `−${fmt(pending.step.spend.amount)} · ${pending.step.spend.item}`;
      this.announce(`Approved. ${fmt(pending.step.spend.amount)} spent on ${pending.step.spend.item}.`);
      this._timers.push(setTimeout(() => {
        if (gen === this._activityGen) this.$activity.textContent = '';
      }, 3400));
    } else {
      this.$activity.textContent = `Skipped: ${pending.step.spend.item} (denied)`;
      this.announce(`Denied. ${pending.step.spend.item} was skipped.`);
      this._timers.push(setTimeout(() => {
        if (gen === this._activityGen) this.$activity.textContent = '';
      }, 3400));
    }

    this._pendingApproval = null;
    pending.resolve(approved);
  }

  paintFinal() {
    WORKERS.forEach((worker) => {
      const el = this._laneEls[worker.id];
      this.setPill(worker, 'done');
      const lastStep = worker.steps[worker.steps.length - 1];
      el.step.textContent = lastStep.label + ' — done';
      el.bar.style.width = '100%';
    });
    // Reduced-motion visitors never see the animated approval — still tell
    // the wallet/spend part of the story as a static fact.
    const opsSpend = WORKERS.find((w) => w.id === 'ops').steps.find((s) => s.spend).spend;
    this._balance -= opsSpend.amount;
    this.$balance.textContent = fmt(this._balance);
    this.$walletAmount.textContent = fmt(this._balance);
    this.$activity.textContent = `−${fmt(opsSpend.amount)} · ${opsSpend.item} (approved)`;
  }
}

customElements.define('aria-agent-dashboard', AriaAgentDashboard);
