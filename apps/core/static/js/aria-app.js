/**
 * Page-level bootstrap shared by every section: nav scroll state, the
 * mobile menu toggle, and the scroll-reveal IntersectionObserver that both
 * plain sections and the custom elements' internal [data-reveal] nodes rely
 * on. Runs after the component modules so their markup already exists.
 */
document.getElementById('yr').textContent = new Date().getFullYear();

const nav = document.getElementById('nav');
function onScroll() {
  nav.classList.toggle('is-scrolled', window.scrollY > 40);
}
onScroll();
window.addEventListener('scroll', onScroll, { passive: true });

const menuBtn = document.getElementById('menuBtn');
const mobileMenu = document.getElementById('mobileMenu');
menuBtn.addEventListener('click', () => {
  const open = mobileMenu.classList.toggle('flex');
  mobileMenu.classList.toggle('hidden', !open);
  menuBtn.setAttribute('aria-expanded', String(open));
});
mobileMenu.querySelectorAll('a').forEach((a) => {
  a.addEventListener('click', () => {
    mobileMenu.classList.add('hidden');
    mobileMenu.classList.remove('flex');
    menuBtn.setAttribute('aria-expanded', 'false');
  });
});

const reduce = window.matchMedia('(prefers-reduced-motion: reduce)').matches;
function observeReveals() {
  const targets = document.querySelectorAll('[data-reveal]:not(.in)');
  if (reduce || !('IntersectionObserver' in window)) {
    targets.forEach((el) => el.classList.add('in'));
    return;
  }
  const io = new IntersectionObserver(
    (entries) => {
      entries.forEach((e) => {
        if (e.isIntersecting) {
          e.target.classList.add('in');
          io.unobserve(e.target);
        }
      });
    },
    { threshold: 0.16, rootMargin: '0px 0px -8% 0px' }
  );
  targets.forEach((el) => io.observe(el));
}
// Custom elements upgrade synchronously during parse, but give the module
// graph a tick to finish before scanning for [data-reveal].
requestAnimationFrame(observeReveals);
