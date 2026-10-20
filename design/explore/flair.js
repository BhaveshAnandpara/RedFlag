// Redflag scan chat flair: shared by scan.html and quick.html (styles in flair.css).
window.RF = {
  // a row of n flags, one per test
  strip(el, n) { el.innerHTML = Array.from({ length: n }, () => '<span class="mf"><i></i><b></b></span>').join(''); },
  // the test now running
  now(el, i) { el.querySelectorAll('.mf').forEach((f, k) => f.classList.toggle('now', k === i)); },
  // a test finished: mark its flag, and on a fail raise a flag on the reply, pulse the window and pop the counter
  result({ strip, i, status, bubble, wrap, counter }) {
    const f = strip?.children[i];
    if (f) { f.classList.remove('now'); f.classList.add(status === 'fail' ? 'fail' : 'pass'); }
    if (status === 'fail') {
      bubble.classList.add('fouled');
      bubble.insertAdjacentHTML('afterbegin', '<span class="bflag" aria-hidden="true"><i></i><b></b></span>');
      if (wrap) { wrap.classList.remove('rf-pulse'); void wrap.offsetWidth; wrap.classList.add('rf-pulse'); }
      if (counter) { counter.classList.remove('rf-pop'); void counter.offsetWidth; counter.classList.add('rf-pop'); }
    } else {
      bubble.classList.add('held');
    }
  },
  // a copy of the finished row, for the end card
  clone(strip) { const c = strip.cloneNode(true); c.removeAttribute('id'); c.querySelectorAll('.mf').forEach(f => f.classList.remove('now')); return c; },
  // count a number up from zero
  countUp(el, to, ms = 900) {
    if (matchMedia('(prefers-reduced-motion: reduce)').matches || !to) { el.textContent = to; return; }
    const t0 = performance.now();
    const step = now => { const k = Math.min(1, (now - t0) / ms); el.textContent = Math.round(to * (1 - Math.pow(1 - k, 3))); if (k < 1) requestAnimationFrame(step); };
    requestAnimationFrame(step);
  },
};
