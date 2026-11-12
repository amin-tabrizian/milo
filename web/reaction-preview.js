// Drafts for Milo's reactions coming out of the real 3D dog (mascot.js makeDog). A preview only: the app does not use it.
import * as THREE from './vendor/three/three.module.min.js';
import { makeDog } from './mascot.js';

const calm = matchMedia('(prefers-reduced-motion: reduce)').matches;
const clamp = (x) => Math.max(0, Math.min(1, x));
const ss = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const hop = (t, at, len) => (t > at && t < at + len ? Math.sin((t - at) / len * Math.PI) : 0);
const R = (a, b) => a + Math.random() * (b - a);
const pick = (a) => a[Math.floor(Math.random() * a.length)];
const DEG = Math.PI / 180;
const SPRING = 'cubic-bezier(.3,1.55,.5,1)', SOFT = 'cubic-bezier(.25,.6,.3,1)';

// ---------- the dog: the header avatar's renderer, lights and camera (mascot.js avatar), with a reaction pose on top
const HEAD_Y = 2.58;
const FACE = { hx: 0, hy: 0, hz: 0.06, ry: -0.2, y: 0, ear: -0.25, eyes: 1, wide: 1 };
// each emoji's move: offsets from the idle face, `e` is the envelope (in, hold, out)
const MOVES = {
  love: { len: 2.1, f: (t, e) => ({ hz: 0.3 * e, hx: -0.06 * e, eyes: -0.62 * e, ear: 0.12 * e, y: 0.1 * hop(t, 0.05, 0.38) }) },
  fire: { len: 1.9, f: (t, e) => ({ y: 0.16 * hop(t, 0.05, 0.3) + 0.12 * hop(t, 0.38, 0.28), hz: 0.09 * Math.sin(t * 9) * e, eyes: -0.35 * e, ear: (0.08 + 0.14 * Math.sin(t * 15)) * Math.exp(-1.5 * t) }) },
  like: { len: 1.7, f: (t, e) => ({ hx: 0.24 * (hop(t, 0.1, 0.34) + 0.75 * hop(t, 0.48, 0.32)), eyes: -0.45 * e }) },
  laugh: { len: 2.1, f: (t, e) => ({ hx: -0.16 * e, y: 0.05 * Math.abs(Math.sin(t * 19)) * e, hz: 0.07 * Math.sin(t * 9.5) * e, eyes: -0.78 * e, ear: (0.06 + 0.1 * Math.sin(t * 19)) * e }) },
  wow: { len: 1.9, f: (t, e) => ({ hx: -0.2 * e, y: 0.09 * hop(t, 0, 0.24), wide: 0.38 * e, ear: -0.08 * e }) },
  party: { len: 2.1, f: (t, e) => ({ y: 0.32 * hop(t, 0.05, 0.5) + 0.1 * hop(t, 0.6, 0.28), ry: 0.32 * Math.sin(t * 7) * e, eyes: -0.5 * e, ear: (0.1 + 0.15 * Math.sin(t * 13)) * Math.exp(-1.4 * t) }) },
  pray: { len: 2.2, f: (t, e) => ({ hx: 0.34 * e, eyes: -0.9 * e, hz: -0.05 * e, ear: 0.06 * e }) },
  sad: { len: 2.5, f: (t, e) => ({ hx: 0.25 * e, hz: -0.14 * e, ear: 0.24 * e, eyes: -0.3 * e, y: -0.03 * e }) },
};

function makeAvatar(canvas) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, 3));
  renderer.toneMapping = THREE.NeutralToneMapping;
  const sc = new THREE.Scene();
  sc.add(new THREE.HemisphereLight(0xffffff, 0xeee9df, 2.0));
  const key = new THREE.DirectionalLight(0xffffff, 1.8); key.position.set(-3, 6, 5); sc.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 0.9); rim.position.set(4, 3, -4); sc.add(rim);
  const parts = makeDog(); sc.add(parts.dog);
  parts.head.rotation.order = 'YXZ';
  const cam = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  const far = 3.5 / (2 * Math.tan(15 * DEG));
  cam.position.set(0, HEAD_Y + 0.25, far); cam.lookAt(0, HEAD_Y - 0.12, 0);
  let move = null, look = 0, t0 = 0, raf = 0, last = 0, blinkAt = -9;
  const draw = (now) => {
    const p = { ...FACE };
    const t = now - t0;
    if (move) {
      const m = MOVES[move], e = ss(0, 0.25, t) * (1 - ss(m.len - 0.45, m.len, t));
      const d = m.f(t, e);
      for (const k in d) p[k] += d[k];
      if (look) { p.hy += 0.24 * e * look; p.hx -= 0.1 * e * look; }   // B: looks up at the cloud
      if (t > m.len) move = null;
    }
    if (now - blinkAt < 0.13) p.eyes = Math.min(p.eyes, 0.12);
    parts.dog.position.y = p.y; parts.dog.rotation.y = p.ry;
    parts.head.rotation.set(p.hx, p.hy, p.hz);
    parts.ears.forEach((e) => { e.rotation.x = p.ear; });
    parts.eyes.forEach((e) => { e.scale.set(p.wide, Math.max(0.08, p.eyes) * p.wide, p.wide); });
    renderer.render(sc, cam);
  };
  const frame = (ms) => {
    raf = 0;
    const now = ms / 1000, busy = move || now - blinkAt < 0.13;
    if (ms - last > 28 || !busy) { draw(now); last = ms; }
    if (busy) raf = requestAnimationFrame(frame);
  };
  const kick = () => { raf ||= requestAnimationFrame(frame); };
  const size = () => { renderer.setSize(canvas.clientWidth, canvas.clientHeight, false); kick(); };
  size();
  const blink = () => { setTimeout(blink, 3000 + Math.random() * 3500); blinkAt = performance.now() / 1000; kick(); };
  setTimeout(blink, 1500 + Math.random() * 2000);
  return {
    react(name, opts = {}) { move = calm ? null : name; look = opts.look || 0; t0 = performance.now() / 1000; kick(); },
    size,
  };
}

// ---------- themes: which particles each emoji gets, and how they move
const SVG = {
  heart: (c) => `<svg viewBox="0 0 24 22"><path fill="${c}" d="M12 21.2S2.6 15.5 2.6 8.9A5.1 5.1 0 0 1 12 6.1a5.1 5.1 0 0 1 9.4 2.8c0 6.6-9.4 12.3-9.4 12.3z"/></svg>`,
  spark: (c) => `<svg viewBox="0 0 24 24"><path fill="${c}" d="M12 0c.9 6.3 4.9 10.6 12 12-7.1 1.4-11.1 5.7-12 12-.9-6.3-4.9-10.6-12-12C7.1 10.6 11.1 6.3 12 0z"/></svg>`,
  flame: () => `<svg viewBox="0 0 24 30"><path fill="url(#gFlame)" d="M12 29.5c-6 0-9.5-4-9.5-9.3 0-5.6 4.8-8.4 5.3-14.7 3.6 2.4 4.9 5.3 4.8 8 1.2-1 2-2.4 2.3-4.4 3.5 3 6.6 6.9 6.6 11.1 0 5.3-3.5 9.3-9.5 9.3z"/><path fill="url(#gCore)" d="M12 29c-2.9 0-4.6-1.9-4.6-4.4 0-2.7 2.4-4 2.7-7.2 2.4 1.6 3.4 3.2 3.4 4.6.6-.5 1-1.2 1.2-2.2 1.7 1.5 2.1 3.2 2.1 4.8 0 2.5-1.8 4.4-4.8 4.4z"/></svg>`,
  drop: (c) => `<svg viewBox="0 0 16 22"><path fill="${c}" d="M8 1C5.6 6 2.5 9.4 2.5 13.6a5.5 5.5 0 0 0 11 0C13.5 9.4 10.4 6 8 1z"/><ellipse cx="6" cy="14" rx="1.4" ry="2.4" fill="#fff" opacity=".55"/></svg>`,
};
const PARTY = ['#d97757', '#f5b83d', '#6cc3a0', '#6a8cf0', '#e5484d', '#b98ce8'];
const THEMES = {
  love: { motion: 'float', glow: '#f06a7c', make: () => ({ svg: SVG.heart(pick(['#e5484d', '#f06a7c', '#f59aa8', '#d94a64'])), w: R(11, 18) }) },
  fire: { motion: 'float', glow: '#ff8a3d', hot: true,
    make: (i) => (i % 3 === 2 ? { cls: 'dot', bg: pick(['#ffb347', '#ffd25e', '#ff7a3d']), w: R(3, 5), ember: true } : { svg: SVG.flame(), w: R(12, 19), h: 1.25 }) },
  like: { motion: 'burst', glow: '#f5b83d', make: (i) => (i % 3 ? { svg: SVG.spark(pick(['#f5b83d', '#ffd36b', '#ffc54d'])), w: R(9, 15) } : { cls: 'dot', bg: '#d97757', w: R(4, 6) }) },
  laugh: { motion: 'spray', glow: '#58a6e8', make: () => ({ svg: SVG.drop(pick(['#58a6e8', '#7dbbf0', '#4a90d9'])), w: R(8, 12), h: 1.38 }) },
  wow: { motion: 'pop', glow: '#f5b83d', make: () => ({}) },
  party: { motion: 'burst', glow: '#b98ce8', confetti: true,
    make: (i) => ({ cls: 'confetti', bg: pick(PARTY), w: i % 2 ? R(5, 7) : R(3, 4), h: i % 2 ? 1.5 : 3.2 }) },
  pray: { motion: 'float', glow: '#ffd27a', slow: true,
    make: (i) => (i % 2 ? { cls: 'glow', bg: 'radial-gradient(circle,#fff6d8,#ffd27a 55%,rgba(255,210,122,0) 72%)', w: R(10, 16) } : { svg: SVG.spark(pick(['#f5c66b', '#ffe3a3'])), w: R(8, 12) }) },
  sad: { motion: 'fall', glow: '#7fa7cf', grey: true, make: () => ({ svg: SVG.drop(pick(['#7fa7cf', '#94b6d8', '#6b95c2'])), w: R(6, 9), h: 1.38 }) },
};
const EMOJI = [['❤️', 'love', 'Love you buddy'], ['🔥', 'fire', 'Shipped it tonight'], ['👍', 'like', 'Booked the flight'], ['😂', 'laugh', 'My cat ate my homework'],
  ['😮', 'wow', 'It snowed in October'], ['🎉', 'party', 'I got the offer!'], ['🙏', 'pray', 'Thanks for the help'], ['😢', 'sad', 'My flight got canceled']];

// Particles, in px at real size, from the cloud's center. `mode`: 'drift' (A, B: a few, gentle) or 'burst' (C).
function spawn(theme, mode) {
  const T = THEMES[theme], burst = mode === 'burst', out = [];
  const P = (o) => out.push({ x: 0, y: 0, vx: 0, vy: 0, g: 0, drag: 0, wob: 0, wf: R(2, 3.5), ph: R(0, 6), rot: 0, spin: 0, s0: 0.3, s1: 0.6, life: 1.4, delay: 0, ...o });
  if (T.motion === 'float') {
    const n = burst ? (T.slow ? 10 : 13) : 4;
    for (let i = 0; i < n; i++) {
      const look = T.make(i), sp = T.slow ? 0.6 : 1;
      if (burst) {
        const a = R(-170, -10) * DEG, v = R(60, 130) * sp;
        P({ ...look, x: Math.cos(a) * 20, y: Math.sin(a) * 12, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 25, g: look.ember ? -90 : -35, drag: 2.3,
          wob: R(3, 7), rot: R(-20, 20), spin: look.ember ? 0 : R(-30, 30), life: R(1.3, 1.9) / (T.slow ? 0.8 : 1), delay: i * 0.025, s1: look.ember ? 0.2 : 0.5 });
      } else {
        P({ ...look, x: R(-22, 22), y: -16, vx: R(-8, 8), vy: R(-40, -28) * sp, g: look.ember ? -30 : -6, drag: 0.3, wob: 5, rot: R(-15, 15),
          life: 1.7, delay: 0.1 + i * 0.3, s0: 0.2, s1: 0.5 });
      }
    }
  } else if (T.motion === 'burst') {
    const n = burst ? (T.confetti ? 22 : 15) : 5;
    for (let i = 0; i < n; i++) {
      const look = T.make(i);
      if (burst) {
        const a = R(-205, 25) * DEG, v = R(110, 200);
        P({ ...look, vx: Math.cos(a) * v, vy: Math.sin(a) * v - 40, g: T.confetti ? 240 : 200, drag: T.confetti ? 2.2 : 1.8, wob: T.confetti ? 6 : 0,
          rot: R(0, 360), spin: T.confetti ? R(-600, 600) : R(-180, 180), flutter: T.confetti ? R(7, 13) : 0, life: R(1.1, 1.7), delay: i * 0.01, s0: 0.5, s1: T.confetti ? 0.9 : 0.3 });
      } else {   // sparkles that twinkle on the cloud's edge
        const a = R(0, 360) * DEG;
        P({ ...look, x: Math.cos(a) * 42, y: Math.sin(a) * 30, vy: -8, life: 0.8, delay: 0.25 + i * 0.22, s0: 0, s1: 0, spin: 120 });
      }
    }
  } else if (T.motion === 'spray') {   // tears fly out of both sides, like laughing
    const n = burst ? 14 : 4;
    for (let i = 0; i < n; i++) {
      const side = i % 2 ? 1 : -1, a = (side > 0 ? R(-62, -22) : R(-158, -118)) * DEG, v = burst ? R(120, 180) : R(70, 100);
      P({ ...T.make(i), x: side * 30, y: 2, vx: Math.cos(a) * v, vy: Math.sin(a) * v, g: 380, drag: 0.6, rot: side * -35, spin: side * 90,
        life: burst ? R(0.9, 1.2) : 1, delay: burst ? Math.floor(i / 2) * 0.07 : 0.15 + Math.floor(i / 2) * 0.35, s0: 0.5, s1: 0.8 });
    }
  } else if (T.motion === 'pop') {   // surprise lines out of the cloud, and a ring or two
    const n = burst ? 12 : 7, wave = burst ? [0, 0.14] : [0];
    wave.forEach((d, w) => {
      for (let i = 0; i < n; i++) {
        const a = ((i + w * 0.5) / n * 360 - 90) * DEG, v = burst ? 260 : 170;
        P({ cls: 'line', bg: w ? '#f5b83d' : '#d97757', w: 3, h: burst ? 4 : 3.2, x: Math.cos(a) * 40, y: Math.sin(a) * 31, vx: Math.cos(a) * v, vy: Math.sin(a) * v,
          drag: 7, rot: a / DEG + 90, life: 0.55, delay: d, s0: 0.6, s1: 0.2 });
      }
    });
    for (const d of burst ? [0, 0.12] : [0.05]) P({ cls: 'ring', border: '#d97757', w: 50, life: 0.7, delay: d, s0: 0.5, s1: burst ? 2.2 : 1.6 });
  } else if (T.motion === 'fall') {   // rain from the cloud's underside
    const n = burst ? 16 : 7;
    for (let i = 0; i < n; i++) {
      P({ ...T.make(i), x: R(-28, 28), y: 18, vy: R(20, 50), g: 320, life: R(0.8, 1), delay: (burst ? 0.05 : 0.25) + i * (burst ? 0.08 : 0.2), s0: 0.6, s1: 0.9 });
    }
  }
  return out;
}

// Keyframes from a short simulation, so each particle moves like it has weight (or lift).
function track(p, K) {
  const N = 16, dt = 1 / 60, frames = [];
  let x = p.x, y = p.y, vx = p.vx, vy = p.vy, t = 0;
  for (let i = 0; i <= N; i++) {
    const until = p.life * i / N;
    while (t < until - 1e-6) { vx *= Math.exp(-p.drag * dt); vy = vy * Math.exp(-p.drag * dt) + p.g * dt; x += vx * dt; y += vy * dt; t += dt; }
    const u = i / N, sc = u < 0.18 ? p.s0 + (1 - p.s0) * ss(0, 0.18, u) : 1 + (p.s1 - 1) * ss(0.4, 1, u);
    const sx = p.flutter ? Math.cos(t * p.flutter) : 1, wx = p.wob * Math.sin(t * p.wf * 2 + p.ph);
    frames.push({ offset: u, opacity: u < 0.1 ? u / 0.1 : 1 - ss(0.6, 1, u),
      transform: `translate(${(x + wx) * K}px,${y * K}px) translate(-50%,-50%) rotate(${p.rot + p.spin * t}deg) scale(${sc * sx},${sc})` });
  }
  return frames;
}

// ---------- the three options
const CLOUD = `<svg viewBox="6 3 92 68"><g fill="url(#gCloud)"><circle cx="28" cy="44" r="20"/><circle cx="48" cy="30" r="25"/><circle cx="71" cy="34" r="20"/><circle cx="80" cy="50" r="15"/><ellipse cx="52" cy="52" rx="38" ry="17"/></g></svg>`;
// px from the avatar's center, at real size. The avatar is a 68px circle: the cloud sits on its rim, about half in and half out.
const AT = { cx: 25, cy: -25, head: [6, -12], puffs: [[9, -13, 3], [13, -17, 4.5]] };
const SP = 0.55, SW = 0.85;   // particle travel and size, relative to the first drafts

class Card {
  constructor(el) {
    this.el = el; this.opt = el.dataset.opt; this.stage = el.querySelector('.stage'); this.timers = [];
    this.stage.innerHTML = `<span class="mock-btn l"><svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round"><path d="M4 7h16M4 12h16M4 17h10"/></svg></span>
      <span class="mock-btn r"><svg viewBox="0 0 24 24" fill="currentColor"><circle cx="5" cy="12" r="1.8"/><circle cx="12" cy="12" r="1.8"/><circle cx="19" cy="12" r="1.8"/></svg></span>
      <div class="av"><span class="face"><canvas></canvas></span><span class="name">Milo</span></div>
      <div class="msg"><span class="text"></span><span class="chip" hidden></span></div><div class="fx"></div>`;
    this.fx = this.stage.querySelector('.fx'); this.chip = this.stage.querySelector('.chip');
    this.dog = makeAvatar(this.stage.querySelector('canvas'));
    el.querySelector('.replay').onclick = () => this.play();
  }
  at(sec, fn) { this.timers.push(setTimeout(fn, sec * 1000)); }
  add(cls, html = '') { const d = document.createElement('div'); d.className = cls; d.innerHTML = html; this.fx.append(d); return d; }
  addP(cls, html = '') { const d = this.add(cls, html); this.pl.append(d); return d; }
  pos(x, y, s = 1, extra = '') { return `translate(${x * K}px,${y * K}px) translate(-50%,-50%) scale(${s}) ${extra}`; }
  burst(theme, mode, x0, y0) {
    for (const p of spawn(theme, mode)) {
      for (const k of ['x', 'y', 'vx', 'vy', 'g', 'wob']) p[k] *= SP;
      if (mode === 'burst') { p.vx *= 0.7; p.vy *= 0.7; p.g *= 0.6; }   // a slower burst, so it plays out inside the disc
      p.w *= SW;
      const d = this.addP('p ' + (p.cls || ''), p.svg || '');
      d.style.width = `${p.w * K}px`; d.style.height = `${p.w * (p.h || 1) * K}px`;
      if (p.bg) d.style.background = p.bg;
      if (p.border) d.style.border = `${2 * K}px solid ${p.border}`;
      p.x += x0; p.y += y0;
      d.style.opacity = 0;
      d.animate(track(p, K), { duration: p.life * 1000, delay: p.delay * 1000, easing: 'linear', fill: 'both' }).finished.then(() => d.remove(), () => {});
    }
  }
  flash(theme, x, y) {
    const f = this.addP('flash');
    f.style.background = `radial-gradient(circle, ${THEMES[theme].glow}55, ${THEMES[theme].glow}00 65%)`;
    f.animate([{ transform: this.pos(x, y, 0.3), opacity: 0 }, { transform: this.pos(x, y, 1, ''), opacity: 1, offset: 0.35 }, { transform: this.pos(x, y, 1.5), opacity: 0 }],
      { duration: 800, easing: 'ease-out', fill: 'both' });
  }
  // the emoji leaves the cloud and lands as the chip on the message (the record of the reaction stays where it is today)
  land(em, x, y) {
    if (!LAND) {
      em.animate([{ transform: this.pos(x, y, 1), opacity: 1 }, { transform: this.pos(x, y - 5, 1.15), opacity: 0 }], { duration: 320, easing: 'ease-in', fill: 'forwards' });
      return;
    }
    const f = this.fx.getBoundingClientRect(), c = this.chip.getBoundingClientRect();
    const tx = (c.left + c.width / 2 - f.left) / K, ty = (c.top + c.height / 2 - f.top) / K, s = 15 / 16;
    const mx = (x + tx) / 2 + 10, my = Math.min(y, ty) - 6;
    em.animate([{ transform: this.pos(x, y, 1) }, { transform: this.pos(x, y, 1.12), offset: 0.15 }, { transform: this.pos(mx, my, 0.85), offset: 0.55 }, { transform: this.pos(tx, ty, s) }],
      { duration: 620, easing: 'cubic-bezier(.5,0,.3,1)', fill: 'forwards' }).finished.then(() => {
      em.remove(); this.chip.hidden = false;
      this.chip.animate([{ transform: 'scale(.6)' }, { transform: 'scale(1.18)', offset: 0.5 }, { transform: 'scale(1)' }], { duration: 320, easing: 'ease-out' });
    }, () => {});
  }
  vanish(el, ms = 360, to = 1.15) {
    el.animate([{ opacity: 1, filter: 'blur(0px)' }, { opacity: 0, filter: `blur(${3 * K}px)` }], { duration: ms, easing: 'ease-in', fill: 'forwards' });
    el.animate([{ scale: 1 }, { scale: to }], { duration: ms, easing: 'ease-out', fill: 'forwards' });
  }

  play() {
    this.timers.forEach(clearTimeout); this.timers = [];
    this.fx.getAnimations({ subtree: true }).forEach((a) => a.cancel());
    this.fx.innerHTML = ''; this.chip.hidden = true; this.pl = this.add('pl');
    const [emoji, theme, text] = CUR;
    this.chip.textContent = emoji; this.stage.querySelector('.text').textContent = text;
    this.fx.classList.toggle('sad', !!THEMES[theme].grey);
    const { cx, cy } = AT, cloud = this.add('cloud', CLOUD.replace('gCloud', THEMES[theme].grey ? 'gCloudSad' : 'gCloud'));
    const em = this.add('emoji', emoji);
    cloud.style.opacity = 0; em.style.opacity = 0;
    this[this.opt](cloud, em, theme, cx, cy);
  }

  // A, Puff: the cloud squeezes out of the head and swells into place; the emoji pops; a few bits drift up
  A(cloud, em, theme, cx, cy) {
    const [hx, hy] = AT.head;
    this.dog.react(theme);
    cloud.animate([{ transform: this.pos(hx, hy, 0.08), opacity: 0 }, { transform: this.pos(hx + 3, hy - 3, 0.3), opacity: 1, offset: 0.25 },
      { transform: this.pos(cx + 1, cy - 1, 1.08), offset: 0.75 }, { transform: this.pos(cx, cy, 1), opacity: 1 }], { duration: 560, easing: SOFT, fill: 'forwards' });
    this.at(0.32, () => {
      em.animate([{ transform: this.pos(cx, cy + 2, 0.2), opacity: 0 }, { transform: this.pos(cx, cy + 2, 1.25), opacity: 1, offset: 0.6 }, { transform: this.pos(cx, cy + 2, 1), opacity: 1 }],
        { duration: 420, easing: 'ease-out', fill: 'forwards' });
    });
    this.at(0.9, () => em.animate([{ scale: 1 }, { scale: 1.16 }, { scale: 1 }, { scale: 1.1 }, { scale: 1 }], { duration: 700, easing: 'ease-in-out' }));
    this.at(0.55, () => this.burst(theme, 'drift', cx, cy - 6));
    this.at(2.3, () => { this.vanish(cloud); this.land(em, cx, cy + 2); });
  }

  // B, Thought: Milo looks up; two bubbles rise from his head, then the cloud; the emoji fades in and the cloud bobs
  B(cloud, em, theme, cx, cy) {
    this.dog.react(theme, { look: 1 });
    const puffs = AT.puffs.map(([x, y, d], i) => {
      const p = this.add('puff'); p.style.width = p.style.height = `${d * K}px`; p.style.opacity = 0;
      p.animate([{ transform: this.pos(x - 3, y + 4, 0), opacity: 0 }, { transform: this.pos(x, y, 1.25), opacity: 1, offset: 0.6 }, { transform: this.pos(x, y, 1), opacity: 1 }],
        { duration: 300, delay: 120 + i * 140, easing: 'ease-out', fill: 'forwards' });
      return p;
    });
    cloud.animate([{ transform: this.pos(cx - 4, cy + 2, 0), opacity: 0 }, { transform: this.pos(cx, cy, 1), opacity: 1 }], { duration: 480, delay: 400, easing: SPRING, fill: 'forwards' });
    cloud.animate([{ translate: '0 0' }, { translate: `0 ${-2 * K}px` }, { translate: '0 0' }], { duration: 1800, delay: 900, iterations: Infinity, easing: 'ease-in-out' });
    em.animate([{ transform: this.pos(cx, cy + 6, 0.6), opacity: 0 }, { transform: this.pos(cx, cy + 2, 1), opacity: 1 }], { duration: 420, delay: 700, easing: SPRING, fill: 'forwards' });
    this.at(1.0, () => this.burst(theme, 'drift', cx, cy - 6));
    this.at(2.5, () => {
      puffs.forEach((p, i) => p.animate([{ scale: 1, opacity: 1 }, { scale: 0, opacity: 0 }], { duration: 220, delay: i * 90, easing: 'ease-in', fill: 'forwards' }));
      this.vanish(cloud, 320, 0.9);
      this.land(em, cx, cy + 2);
    });
  }

  // C, Burst: the cloud pops, squashes as the emoji punches in, and themed particles burst out
  C(cloud, em, theme, cx, cy) {
    this.dog.react(theme);
    cloud.animate([{ transform: this.pos(cx - 7, cy + 5, 0), opacity: 0 }, { transform: this.pos(cx, cy, 1), opacity: 1 }], { duration: 420, easing: SPRING, fill: 'forwards' });
    this.at(0.3, () => {
      cloud.animate([{ scale: '1 1' }, { scale: '1.1 0.92' }, { scale: '0.97 1.03' }, { scale: '1 1' }], { duration: 420, easing: 'ease-out' });
      em.animate([{ transform: this.pos(cx, cy + 2, 0.2), opacity: 0 }, { transform: this.pos(cx, cy + 2, 1.5), opacity: 1, offset: 0.45 }, { transform: this.pos(cx, cy + 2, 1), opacity: 1 }],
        { duration: 460, easing: 'ease-out', fill: 'forwards' });
      this.flash(theme, cx, cy);
      this.burst(theme, 'burst', cx * 0.6, cy * 0.6);   // from behind the cloud, toward the face, so the burst stays around Milo
    });
    this.at(2.2, () => { this.vanish(cloud); this.land(em, cx, cy + 2); });
  }
}

// ---------- page
let K = 1, LAND = true, CUR = EMOJI[0];
const cards = [...document.querySelectorAll('.card')].map((el) => new Card(el));
const playAll = () => cards.forEach((c, i) => setTimeout(() => c.play(), i * 120));
const picker = document.getElementById('picker');
for (const e of EMOJI) {
  const b = document.createElement('button'); b.textContent = e[0]; b.setAttribute('aria-label', e[1]);
  b.onclick = () => { CUR = e; [...picker.children].forEach((x) => x.classList.toggle('on', x === b)); playAll(); };
  picker.append(b);
}
picker.children[0].classList.add('on');
const seg = (id, fn) => {
  const el = document.getElementById(id);
  el.onclick = (ev) => {
    const b = ev.target.closest('button'); if (!b) return;
    [...el.children].forEach((x) => x.classList.toggle('on', x === b)); fn(b);
  };
};
const layout = () => {
  document.documentElement.style.setProperty('--k', K);
  document.documentElement.style.setProperty('--ax', K > 1 ? '30%' : '50%');
  document.querySelectorAll('.stage').forEach((s) => s.classList.toggle('zoom', K > 1));
  cards.forEach((c) => c.dog.size());
};
seg('size', (b) => { K = +b.dataset.k; layout(); playAll(); });
seg('land', (b) => { LAND = b.dataset.v === '1'; playAll(); });
document.getElementById('playAll').onclick = playAll;
layout();
setTimeout(playAll, 400);
window.__preview = { cards, playAll };   // for the screenshot check
