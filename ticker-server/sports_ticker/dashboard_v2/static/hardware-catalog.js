/* Browse hardware cards with tabs, keyboard arrows, or horizontal scrolling. */
(function () {
  'use strict';
  const reducedMotion = matchMedia('(prefers-reduced-motion: reduce)').matches;
  document.querySelectorAll('[data-hardware-catalog]').forEach(root => {
    const strip = root.querySelector('.hardware-specs');
    const cards = [...strip.querySelectorAll('[data-hardware]')];
    const tabs = [...root.querySelectorAll('[data-catalog-index]')];
    let pending = false;
    function mark(index) {
      tabs.forEach((tab, i) => {
        tab.setAttribute('aria-selected', String(i === index));
        tab.tabIndex = i === index ? 0 : -1;
      });
    }
    function select(index, focus) {
      const chosen = (index + tabs.length) % tabs.length;
      strip.scrollTo({left: cards[chosen].offsetLeft - cards[0].offsetLeft, behavior: reducedMotion ? 'auto' : 'smooth'});
      mark(chosen);
      if (focus) tabs[chosen].focus();
    }
    tabs.forEach((tab, index) => {
      tab.addEventListener('click', () => select(index, false));
      tab.addEventListener('keydown', event => {
        const next = {ArrowLeft: index - 1, ArrowRight: index + 1, Home: 0, End: tabs.length - 1}[event.key];
        if (next === undefined) return;
        event.preventDefault(); select(next, true);
      });
    });
    strip.addEventListener('scroll', () => {
      if (pending) return;
      pending = true;
      requestAnimationFrame(() => {
        pending = false;
        const left = strip.getBoundingClientRect().left;
        const closest = cards.reduce((best, card, index) =>
          Math.abs(card.getBoundingClientRect().left - left) < Math.abs(cards[best].getBoundingClientRect().left - left) ? index : best, 0);
        mark(closest);
      });
    }, {passive: true});
  });
})();
