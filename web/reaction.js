// Milo's reaction, out of the header dog: Milo looks up, two bubbles rise from his head, then a small cloud on the
// rim of his circle with the emoji in it and a few themed bits drifting out; then the emoji flies down and lands on
// the message as the chip. The user picked this in drafts (reaction-preview.html, "B, Thought"). The app skips it
// with reduced motion and for reactions it loads with a chat (app.js 'reaction').
const clamp = (x) => Math.max(0, Math.min(1, x));
const ss = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const R = (a, b) => a + Math.random() * (b - a);
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const DEG = Math.PI / 180;
const SPRING = 'cubic-bezier(.3,1.55,.5,1)';

const SVG = {
  heart: (c) => `<svg viewBox="0 0 24 22"><path fill="${c}" d="M12 21.2S2.6 15.5 2.6 8.9A5.1 5.1 0 0 1 12 6.1a5.1 5.1 0 0 1 9.4 2.8c0 6.6-9.4 12.3-9.4 12.3z"/></svg>`,
  spark: (c) => `<svg viewBox="0 0 24 24"><path fill="${c}" d="M12 0c.9 6.3 4.9 10.6 12 12-7.1 1.4-11.1 5.7-12 12-.9-6.3-4.9-10.6-12-12C7.1 10.6 11.1 6.3 12 0z"/></svg>`,
  flame: () => `<svg viewBox="0 0 24 30"><path fill="url(#rxFlame)" d="M12 29.5c-6 0-9.5-4-9.5-9.3 0-5.6 4.8-8.4 5.3-14.7 3.6 2.4 4.9 5.3 4.8 8 1.2-1 2-2.4 2.3-4.4 3.5 3 6.6 6.9 6.6 11.1 0 5.3-3.5 9.3-9.5 9.3z"/><path fill="url(#rxCore)" d="M12 29c-2.9 0-4.6-1.9-4.6-4.4 0-2.7 2.4-4 2.7-7.2 2.4 1.6 3.4 3.2 3.4 4.6.6-.5 1-1.2 1.2-2.2 1.7 1.5 2.1 3.2 2.1 4.8 0 2.5-1.8 4.4-4.8 4.4z"/></svg>`,
  drop: (c) => `<svg viewBox="0 0 16 22"><path fill="${c}" d="M8 1C5.6 6 2.5 9.4 2.5 13.6a5.5 5.5 0 0 0 11 0C13.5 9.4 10.4 6 8 1z"/><ellipse cx="6" cy="14" rx="1.4" ry="2.4" fill="#fff" opacity=".55"/></svg>`,
};
const DEFS = `<svg width="0" height="0" style="position:absolute" aria-hidden="true"><defs>
  <linearGradient id="rxCloud" gradientUnits="userSpaceOnUse" x1="0" y1="4" x2="0" y2="70"><stop offset="0" stop-color="#ffffff"/><stop offset=".55" stop-color="#fbf7f0"/><stop offset="1" stop-color="#ece3d5"/></linearGradient>
  <linearGradient id="rxCloudSad" gradientUnits="userSpaceOnUse" x1="0" y1="4" x2="0" y2="70"><stop offset="0" stop-color="#f8fafc"/><stop offset=".55" stop-color="#e3e9f0"/><stop offset="1" stop-color="#c9d3df"/></linearGradient>
  <linearGradient id="rxFlame" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#ffd25e"/><stop offset=".55" stop-color="#ff8a3d"/><stop offset="1" stop-color="#e2502a"/></linearGradient>
  <linearGradient id="rxCore" x1="0" y1="0" x2="0" y2="1"><stop offset="0" stop-color="#fff6c8"/><stop offset="1" stop-color="#ffc248"/></linearGradient>
</defs></svg>`;
const CLOUD = (sad) => `<svg viewBox="6 3 92 68"><g fill="url(#${sad ? 'rxCloudSad' : 'rxCloud'})"><circle cx="28" cy="44" r="20"/><circle cx="48" cy="30" r="25"/><circle cx="71" cy="34" r="20"/><circle cx="80" cy="50" r="15"/><ellipse cx="52" cy="52" rx="38" ry="17"/></g></svg>`;

// the emoji Milo can pick (features.py REACTIONS) and the move and bits each gets
export const THEME_OF = { '\u2764': 'love', '\u{1F44D}': 'like', '\u{1F602}': 'laugh', '\u{1F62E}': 'wow', '\u{1F389}': 'party', '\u{1F525}': 'fire', '\u{1F64F}': 'pray', '\u{1F622}': 'sad' };
export const themeOf = (emoji) => THEME_OF[String(emoji).replace(/️/g, '')] || 'like';
const THEMES = {
  love: { motion: 'float', make: () => ({ svg: SVG.heart(pick(['#e5484d', '#f06a7c', '#f59aa8', '#d94a64'])), w: R(11, 18) }) },
  fire: { motion: 'float', make: (i) => (i % 3 === 2 ? { cls: 'dot', bg: pick(['#ffb347', '#ffd25e', '#ff7a3d']), w: R(3, 5), ember: true } : { svg: SVG.flame(), w: R(12, 19), h: 1.25 }) },
  like: { motion: 'burst', make: (i) => (i % 3 ? { svg: SVG.spark(pick(['#f5b83d', '#ffd36b', '#ffc54d'])), w: R(9, 15) } : { cls: 'dot', bg: '#d97757', w: R(4, 6) }) },
  laugh: { motion: 'spray', make: () => ({ svg: SVG.drop(pick(['#58a6e8', '#7dbbf0', '#4a90d9'])), w: R(8, 12), h: 1.38 }) },
  wow: { motion: 'pop', make: () => ({}) },
  party: { motion: 'burst', make: (i) => ({ cls: 'confetti', bg: pick(['#d97757', '#f5b83d', '#6cc3a0', '#6a8cf0', '#e5484d', '#b98ce8']), w: i % 2 ? R(5, 7) : R(3, 4), h: i % 2 ? 1.5 : 3.2 }) },
  pray: { motion: 'float', slow: true, make: (i) => (i % 2 ? { cls: 'glow', bg: 'radial-gradient(circle,#fff6d8,#ffd27a 55%,rgba(255,210,122,0) 72%)', w: R(10, 16) } : { svg: SVG.spark(pick(['#f5c66b', '#ffe3a3'])), w: R(8, 12) }) },
  sad: { motion: 'fall', grey: true, make: () => ({ svg: SVG.drop(pick(['#7fa7cf', '#94b6d8', '#6b95c2'])), w: R(6, 9), h: 1.38 }) },
};

// A few gentle bits from the cloud, in px from its center
function drift(theme) {
  const T = THEMES[theme], out = [];
  const P = (o) => out.push({ x: 0, y: 0, vx: 0, vy: 0, g: 0, drag: 0, wob: 0, wf: R(2, 3.5), ph: R(0, 6), rot: 0, spin: 0, s0: 0.3, s1: 0.6, life: 1.4, delay: 0, ...o });
  if (T.motion === 'float') {
    for (let i = 0; i < 4; i++) {
      const look = T.make(i), sp = T.slow ? 0.6 : 1;
      P({ ...look, x: R(-22, 22), y: -16, vx: R(-8, 8), vy: R(-40, -28) * sp, g: look.ember ? -30 : -6, drag: 0.3, wob: 5, rot: R(-15, 15), life: 1.7, delay: 0.1 + i * 0.3, s0: 0.2, s1: 0.5 });
    }
  } else if (T.motion === 'burst') {   // sparkles that twinkle on the cloud's edge
    for (let i = 0; i < 5; i++) {
      const a = R(0, 360) * DEG;
      P({ ...T.make(i), x: Math.cos(a) * 42, y: Math.sin(a) * 30, vy: -8, life: 0.8, delay: 0.25 + i * 0.22, s0: 0, s1: 0, spin: 120 });
    }
  } else if (T.motion === 'spray') {   // tears fly out of both sides, like laughing
    for (let i = 0; i < 4; i++) {
      const side = i % 2 ? 1 : -1, a = (side > 0 ? R(-62, -22) : R(-158, -118)) * DEG, v = R(70, 100);
      P({ ...T.make(i), x: side * 30, y: 2, vx: Math.cos(a) * v, vy: Math.sin(a) * v, g: 380, drag: 0.6, rot: side * -35, spin: side * 90, life: 1, delay: 0.15 + Math.floor(i / 2) * 0.35, s0: 0.5, s1: 0.8 });
    }
  } else if (T.motion === 'pop') {   // surprise lines out of the cloud, and a ring
    for (let i = 0; i < 7; i++) {
      const a = (i / 7 * 360 - 90) * DEG;
      P({ cls: 'line', bg: '#d97757', w: 3, h: 3.2, x: Math.cos(a) * 40, y: Math.sin(a) * 31, vx: Math.cos(a) * 170, vy: Math.sin(a) * 170, drag: 7, rot: a / DEG + 90, life: 0.55, s0: 0.6, s1: 0.2 });
    }
    P({ cls: 'ring', border: '#d97757', w: 50, life: 0.7, delay: 0.05, s0: 0.5, s1: 1.6 });
  } else {   // rain from the cloud's underside
    for (let i = 0; i < 7; i++) P({ ...T.make(i), x: R(-28, 28), y: 18, vy: R(20, 50), g: 320, life: R(0.8, 1), delay: 0.25 + i * 0.2, s0: 0.6, s1: 0.9 });
  }
  return out;
}

// keyframes from a short simulation, so each bit moves like it has weight (or lift)
function track(p) {
  const N = 16, dt = 1 / 60, frames = [];
  let x = p.x, y = p.y, vx = p.vx, vy = p.vy, t = 0;
  for (let i = 0; i <= N; i++) {
    const until = p.life * i / N;
    while (t < until - 1e-6) { vx *= Math.exp(-p.drag * dt); vy = vy * Math.exp(-p.drag * dt) + p.g * dt; x += vx * dt; y += vy * dt; t += dt; }
    const u = i / N, sc = u < 0.18 ? p.s0 + (1 - p.s0) * ss(0, 0.18, u) : 1 + (p.s1 - 1) * ss(0.4, 1, u);
    const wx = p.wob * Math.sin(t * p.wf * 2 + p.ph);
    frames.push({ offset: u, opacity: u < 0.1 ? u / 0.1 : 1 - ss(0.6, 1, u),
      transform: `translate(${x + wx}px,${y}px) translate(-50%,-50%) rotate(${p.rot + p.spin * t}deg) scale(${sc})` });
  }
  return frames;
}

const pos = (x, y, s = 1) => `translate(${x}px,${y}px) translate(-50%,-50%) scale(${s})`;
const SP = 0.55, SW = 0.85;   // the bits' travel and size: small enough to stay around the 68px circle

// Plays the reaction from the dog's circle `face`. dog: mascot.js avatar (its move), side: 1 puts the cloud on the
// right of the circle, -1 on the left (when the 3D thinking bubble is on the right). chip(): the message's chip, or
// null when it isn't on screen any more. done() runs when the emoji has landed (or faded), and shows the chip.
export function playReaction({ face, dog, emoji, side = 1, chip, done }) {
  const theme = themeOf(emoji), grey = !!THEMES[theme].grey;
  const r = face.getBoundingClientRect();
  const fx = document.createElement('div');
  fx.className = 'rx' + (grey ? ' sad' : ''); fx.setAttribute('aria-hidden', 'true');
  fx.style.left = `${r.left + r.width / 2}px`; fx.style.top = `${r.top + r.height / 2}px`;
  fx.innerHTML = DEFS;
  document.body.append(fx);
  const add = (cls, html = '', to = fx) => { const d = document.createElement('div'); d.className = cls; d.innerHTML = html; to.append(d); return d; };
  const pl = add('pl');
  const cx = 25 * side, cy = -25, X = (x) => x * side;   // the cloud on the rim: about half in, half out of the circle
  dog?.react(theme, side);
  const puffs = [[9, -13, 3], [13, -17, 4.5]].map(([x, y, d], i) => {
    const p = add('puff'); p.style.width = p.style.height = `${d}px`; p.style.opacity = 0;
    p.animate([{ transform: pos(X(x - 3), y + 4, 0), opacity: 0 }, { transform: pos(X(x), y, 1.25), opacity: 1, offset: 0.6 }, { transform: pos(X(x), y, 1), opacity: 1 }],
      { duration: 300, delay: 120 + i * 140, easing: 'ease-out', fill: 'forwards' });
    return p;
  });
  const cloud = add('cloud', CLOUD(grey)), em = add('emoji', emoji);
  cloud.style.opacity = 0; em.style.opacity = 0;
  if (side < 0) cloud.firstElementChild.style.transform = 'scaleX(-1)';   // its big puff stays on the outside
  cloud.animate([{ transform: pos(cx - X(4), cy + 2, 0), opacity: 0 }, { transform: pos(cx, cy, 1), opacity: 1 }], { duration: 480, delay: 400, easing: SPRING, fill: 'forwards' });
  cloud.animate([{ translate: '0 0' }, { translate: '0 -2px' }, { translate: '0 0' }], { duration: 1800, delay: 900, iterations: Infinity, easing: 'ease-in-out' });
  em.animate([{ transform: pos(cx, cy + 6, 0.6), opacity: 0 }, { transform: pos(cx, cy + 2, 1), opacity: 1 }], { duration: 420, delay: 700, easing: SPRING, fill: 'forwards' });
  const timers = [];
  timers.push(setTimeout(() => {
    for (const p of drift(theme)) {
      for (const k of ['x', 'y', 'vx', 'vy', 'g', 'wob']) p[k] *= SP;
      p.w *= SW; p.x += cx; p.y += cy - 6;
      const d = add('p ' + (p.cls || ''), p.svg || '', pl);
      d.style.width = `${p.w}px`; d.style.height = `${p.w * (p.h || 1)}px`;
      if (p.bg) d.style.background = p.bg;
      if (p.border) d.style.border = `2px solid ${p.border}`;
      d.style.opacity = 0;
      d.animate(track(p), { duration: p.life * 1000, delay: p.delay * 1000, easing: 'linear', fill: 'both' });
    }
  }, 1000));
  let ended = false;
  const end = () => { if (ended) return; ended = true; timers.forEach(clearTimeout); fx.remove(); done?.(); };
  timers.push(setTimeout(() => {
    puffs.forEach((p, i) => p.animate([{ scale: 1, opacity: 1 }, { scale: 0, opacity: 0 }], { duration: 220, delay: i * 90, easing: 'ease-in', fill: 'forwards' }));
    cloud.animate([{ opacity: 1, filter: 'blur(0px)', scale: 1 }, { opacity: 0, filter: 'blur(3px)', scale: 0.9 }], { duration: 320, easing: 'ease-in', fill: 'forwards' });
    // the emoji flies to the chip in an arc, at the chip's size; the chip then shows (its pop is the landing)
    const c = chip?.(), f = fx.getBoundingClientRect(), x = cx, y = cy + 2;
    if (!c) {
      em.animate([{ transform: pos(x, y, 1), opacity: 1 }, { transform: pos(x, y - 5, 1.15), opacity: 0 }], { duration: 320, easing: 'ease-in', fill: 'forwards' })
        .finished.then(end, end);
      return;
    }
    const b = c.getBoundingClientRect(), tx = b.left + b.width / 2 - f.left, ty = b.top + b.height / 2 - f.top;
    const mx = (x + tx) / 2 + 10 * side, my = Math.min(y, ty) - 6;
    em.animate([{ transform: pos(x, y, 1) }, { transform: pos(x, y, 1.12), offset: 0.15 }, { transform: pos(mx, my, 0.85), offset: 0.55 }, { transform: pos(tx, ty, 15 / 16) }],
      { duration: 620, easing: 'cubic-bezier(.5,0,.3,1)', fill: 'forwards' }).finished.then(end, end);
  }, 2500));
  timers.push(setTimeout(end, 5000));   // whatever happens to the animations, the chip shows
  return end;
}
