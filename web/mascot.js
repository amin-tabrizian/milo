// Milo the dog in 3D: the splash when the app opens. Built from simple shapes, so there is no model file to load.
// The user picked this look in previews: closed smile, folded ears; clay colors, felt, pink cheeks and no white
// glints (round 4); a chubby body, brown eyes and a smaller nose (round 5).
import * as THREE from './vendor/three/three.module.min.js';

const C = { fur: 0xebe3d6, light: 0xf8f4ec, ear: 0xd97757, ink: 0x5e4336, collar: 0xd97757, tag: 0xf2c8b6, blush: 0xefb19c };
const HEAD = { y: 2.58, z: 0.1, s: 1.12 };   // where the head sits on the chubby body

// Felt like Muse's buddy: fully rough, a soft sheen at the edges, and fine random fuzz as a bump map.
let fuzz = null, fade = null;
function feltBump() {
  if (fuzz) return fuzz;
  const c = document.createElement('canvas'); c.width = c.height = 256;
  const g = c.getContext('2d'), img = g.createImageData(256, 256);
  for (let i = 0; i < img.data.length; i += 4) { img.data[i] = img.data[i + 1] = img.data[i + 2] = 96 + Math.random() * 120; img.data[i + 3] = 255; }
  g.putImageData(img, 0, 0);
  fuzz = new THREE.CanvasTexture(c); fuzz.wrapS = fuzz.wrapT = THREE.RepeatWrapping; fuzz.repeat.set(6, 3);
  return fuzz;
}
function cheekFade() {   // a round fade, so the cheeks have no hard edge
  if (fade) return fade;
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const g = c.getContext('2d'), r = g.createRadialGradient(64, 64, 0, 64, 64, 64);
  r.addColorStop(0, 'rgba(255,255,255,1)'); r.addColorStop(0.55, 'rgba(255,255,255,.75)'); r.addColorStop(1, 'rgba(255,255,255,0)');
  g.fillStyle = r; g.fillRect(0, 0, 128, 128);
  fade = new THREE.CanvasTexture(c); fade.colorSpace = THREE.SRGBColorSpace;
  return fade;
}
const white = new THREE.Color(0xffffff);
const mat = (color) => new THREE.MeshPhysicalMaterial({ color, roughness: 1, sheen: 1, sheenRoughness: 0.6, sheenColor: new THREE.Color(color).lerp(white, 0.6), bumpMap: feltBump(), bumpScale: 2 });

function blob(m, r, [sx, sy, sz], [x, y, z], parent) {
  const mesh = new THREE.Mesh(new THREE.SphereGeometry(r, 48, 32), m);
  mesh.scale.set(sx, sy, sz); mesh.position.set(x, y, z);
  mesh.castShadow = true; parent.add(mesh);
  return mesh;
}
function add(geo, m, [x, y, z], parent, rot = [0, 0, 0]) {
  const mesh = new THREE.Mesh(geo, m);
  mesh.position.set(x, y, z); mesh.rotation.set(...rot); mesh.castShadow = true; parent.add(mesh);
  return mesh;
}

export function makeDog() {
  const fur = mat(C.fur), light = mat(C.light), ear = mat(C.ear), ink = new THREE.MeshStandardMaterial({ color: C.ink, roughness: 0.95 });
  const dog = new THREE.Group();

  // sitting body, chubby: about as wide as the head
  const body = new THREE.Group(); dog.add(body);
  blob(fur, 1, [0.92, 0.82, 0.85], [0, 0.86, -0.05], body);
  blob(fur, 1, [1.05, 0.5, 0.92], [0, 0.42, -0.12], body);
  blob(light, 1, [0.5, 0.5, 0.3], [0, 0.86, 0.55], body);              // chest
  // front legs hang from a shoulder inside the chest, so the avatar can lift them; at rest they sit as before
  const arms = [];
  for (const s of [-1, 1]) {
    const arm = new THREE.Group(); arm.position.set(s * 0.36, 1.1, 0.62); body.add(arm);
    blob(fur, 1, [0.26, 0.36, 0.26], [0, -0.72, 0], arm);                // front leg
    const paw = blob(light, 1, [0.28, 0.16, 0.32], [s * 0.36, 0.13, 0.76], body);   // front paw
    paw.rotation.order = 'YXZ';
    blob(light, 1, [0.3, 0.15, 0.42], [s * 0.82, 0.12, 0.3], body);     // back foot
    arms.push({ arm, paw, s, rest: paw.position.clone() });
  }
  add(new THREE.TorusGeometry(0.56, 0.12, 20, 64), mat(C.collar), [0, 1.56, 0], body, [Math.PI / 2 - 0.2, 0, 0]);
  add(new THREE.CylinderGeometry(0.135, 0.135, 0.045, 40), mat(C.tag), [0, 1.32, 0.74], body, [Math.PI / 2 - 0.3, 0, 0]);   // in front of the chest

  // tail: pivots at its base, wags side to side
  const tail = new THREE.Group();
  tail.position.set(0, 0.6, -0.9); tail.rotation.x = -0.75; body.add(tail);
  blob(fur, 1, [0.13, 0.3, 0.13], [0, 0.27, 0], tail);
  blob(ear, 1, [0.156, 0.14, 0.156], [0, 0.53, 0], tail);

  // head, sitting on the collar
  const head = new THREE.Group();
  head.position.set(0, HEAD.y, HEAD.z); head.scale.setScalar(HEAD.s); dog.add(head);
  blob(fur, 1, [1.05, 0.9, 0.92], [0, 0, 0], head);
  blob(light, 0.46, [1.12, 0.84, 1], [0, -0.3, 0.66], head);          // snout
  for (const [x, y, r] of [[-0.18, -0.68, 0.13], [0, -0.73, 0.14], [0.18, -0.68, 0.13]]) blob(light, r, [1, 1.3, 1], [x, y, 0.62], head);   // beard
  for (const [x, y] of [[-0.14, 0.86], [0, 0.92], [0.14, 0.86]]) blob(fur, 0.14, [1, 1.4, 1], [x, y, 0.12], head);   // top tuft
  blob(ink, 0.1, [1.35, 0.92, 0.9], [0, -0.12, 1.09], head);          // nose, small so the face has less dark

  // closed smile under the nose
  const mouth = new THREE.Group();
  mouth.position.set(0, -0.44, 1.07); mouth.rotation.x = 0.4; mouth.scale.setScalar(1.3); head.add(mouth);
  add(new THREE.CapsuleGeometry(0.015, 0.06, 4, 8), ink, [0, 0.1, 0.02], mouth);
  for (const s of [-1, 1]) add(new THREE.TorusGeometry(0.065, 0.017, 8, 20, Math.PI), ink, [s * 0.065, 0.04, 0.02], mouth, [0, 0, Math.PI]);

  // small dot eyes and soft pink cheeks
  const eyes = [];
  const blush = new THREE.MeshBasicMaterial({ color: C.blush, map: cheekFade(), transparent: true, opacity: 0.7, depthWrite: false });
  for (const s of [-1, 1]) {
    const eye = new THREE.Group();
    eye.position.set(s * 0.34, 0.04, 0.85); head.add(eye); eyes.push(eye);
    blob(ink, 0.085, [1, 1.1, 0.55], [0, 0, 0], eye);
    // the cheek lies on the head's surface, turned along its normal
    const x = s * 0.6, y = -0.14, z = 0.92 * Math.sqrt(1 - (x / 1.05) ** 2 - (y / 0.9) ** 2);
    const n = new THREE.Vector3(x / 1.05 ** 2, y / 0.9 ** 2, z / 0.92 ** 2).normalize();
    const cheek = new THREE.Mesh(new THREE.CircleGeometry(0.16, 40), blush);
    cheek.position.set(x, y, z).addScaledVector(n, 0.025);
    cheek.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    cheek.scale.set(1.3, 0.85, 1); head.add(cheek);
  }

  // folded ears: soft flaps on the upper front of the head, hinged at the fold
  const sh = new THREE.Shape();
  sh.moveTo(-0.3, 0);
  sh.quadraticCurveTo(0, 0.08, 0.3, 0);
  sh.quadraticCurveTo(0.3, -0.38, 0.07, -0.6);
  sh.quadraticCurveTo(0, -0.67, -0.07, -0.58);
  sh.quadraticCurveTo(-0.27, -0.3, -0.3, 0);
  const earGeo = new THREE.ExtrudeGeometry(sh, { depth: 0.04, bevelThickness: 0.05, bevelSize: 0.05, bevelSegments: 4, curveSegments: 16 });
  earGeo.translate(0, 0, -0.02);
  const ears = [];
  for (const s of [-1, 1]) {
    const n = new THREE.Vector3(s * 0.55, 0.62, 0.56).normalize();
    const base = new THREE.Group();
    base.position.set(s * 0.6, 0.55, 0.5).addScaledVector(n, 0.03);
    base.quaternion.setFromUnitVectors(new THREE.Vector3(0, 0, 1), n);
    base.rotateZ(s * 0.3);   // tip points down and a little out
    head.add(base);
    const hinge = new THREE.Group(); base.add(hinge);
    const flap = add(earGeo, ear, [0, 0, 0], hinge); flap.scale.x = s;
    ears.push(hinge);
  }

  return { dog, body, head, tail, ears, eyes, arms };
}

const clamp = (x) => Math.max(0, Math.min(1, x));
const backOut = (x) => 1 + 2.7 * (x - 1) ** 3 + 1.7 * (x - 1) ** 2;

// Pose at time t (seconds): pop up, hop, head tilt, wag, blink.
export function pose(p, t) {
  const pop = backOut(clamp(t / 0.6));
  const hop = t > 0.95 && t < 1.3 ? Math.sin((t - 0.95) / 0.35 * Math.PI) * 0.28 : 0;
  p.dog.position.y = (pop - 1) * 1.6 + hop;
  p.dog.scale.setScalar(Math.max(0.01, 0.55 + 0.45 * pop));
  p.dog.rotation.y = -0.45 + 0.6 * Math.sin(t * 1.5);
  p.head.rotation.z = 0.24 * Math.sin((t - 0.4) * 3) * clamp(t - 0.4);
  p.head.rotation.x = -0.08 * Math.sin(t * 2.2);
  p.tail.rotation.z = 0.65 * Math.sin(t * 19);
  const flop = 0.3 * Math.sin(t * 10) * Math.exp(-2.5 * Math.max(0, t - 0.55)) * clamp(t / 0.55);
  p.ears.forEach((e) => { e.rotation.x = -0.25 + flop; });
  const blink = t > 1.45 && t < 1.57 ? 0.12 : 1;
  p.eyes.forEach((e) => { e.scale.y = blink; });
}

// Renderer, lights and dog. `shadows` adds the floor shadow (the splash shows the floor; the avatar does not).
function setup(canvas, shadows, dpr = 2) {
  const renderer = new THREE.WebGLRenderer({ canvas, antialias: true, alpha: true });
  renderer.setPixelRatio(Math.min(devicePixelRatio, dpr));
  renderer.toneMapping = THREE.NeutralToneMapping;
  const sc = new THREE.Scene();
  sc.add(new THREE.HemisphereLight(0xffffff, 0xeee9df, 2.0));   // soft light, so the felt has no hot spots
  const key = new THREE.DirectionalLight(0xffffff, 1.8);
  key.position.set(-3, 6, 5); sc.add(key);
  const rim = new THREE.DirectionalLight(0xffffff, 0.9);
  rim.position.set(4, 3, -4); sc.add(rim);
  if (shadows) {
    renderer.shadowMap.enabled = true; renderer.shadowMap.type = THREE.PCFSoftShadowMap;
    key.castShadow = true; key.shadow.mapSize.set(1024, 1024); key.shadow.radius = 6;
    Object.assign(key.shadow.camera, { left: -3, right: 3, top: 4.5, bottom: -2 });
    const floor = new THREE.Mesh(new THREE.CircleGeometry(3, 48), new THREE.ShadowMaterial({ opacity: 0.14 }));
    floor.rotation.x = -Math.PI / 2; floor.receiveShadow = true; sc.add(floor);
  }
  const parts = makeDog(); sc.add(parts.dog);
  const dispose = () => { renderer.dispose(); renderer.forceContextLoss(); };
  return { renderer, sc, parts, dispose };
}

export function scene(canvas) {
  const { renderer, sc, parts, dispose } = setup(canvas, true);
  const cam = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  const resize = () => {
    const w = canvas.clientWidth, h = canvas.clientHeight;
    renderer.setSize(w, h, false); cam.aspect = w / h;
    // the dog (about 3.8 tall, 3.2 wide with its sway) fills at most 60% of the height, in the upper part,
    // so the name fits under it on any screen
    const seen = Math.max(6, 3.2 / cam.aspect), aim = 1.8 - 0.08 * seen;
    cam.position.set(0, aim + 0.5, seen / (2 * Math.tan(THREE.MathUtils.degToRad(cam.fov / 2))));
    cam.lookAt(0, aim, 0); cam.updateProjectionMatrix();
  };
  resize();
  const draw = (t) => { pose(parts, t); renderer.render(sc, cam); };
  return { draw, resize, dispose };
}

// Runs the splash in `el` and removes it when done or tapped.
export function playSplash(el, len = 1.9) {
  const canvas = el.querySelector('canvas');
  const s = scene(canvas);
  let start = 0, raf = 0, done = false;
  const finish = () => {
    if (done) return; done = true;
    el.classList.add('out');
    removeEventListener('resize', s.resize);
    setTimeout(() => { cancelAnimationFrame(raf); s.dispose(); el.remove(); }, 400);
  };
  const frame = (now) => {
    start ||= now;
    const t = (now - start) / 1000;
    s.draw(t);
    if (t > len) finish(); else raf = requestAnimationFrame(frame);
  };
  raf = requestAnimationFrame(frame);
  el.addEventListener('pointerdown', finish);   // tap to skip
  addEventListener('resize', s.resize);
}

// The dog in the header, head and collar filling the circle like Muse's avatar. Each of Milo's states has its
// own face, and the dog blends from one face into the next over about a second, so a change never jumps.
// While Milo works, a clay laptop rises into its paws (the user picked this in drafts: "A, laptop in the paws");
// while it thinks, a thought bubble fills with dots. It draws only while it moves (and for a blink now and then),
// so it costs nothing while Milo is idle and the phone is still.
const BUSY = new Set(['thinking', 'working', 'browsing', 'writing', 'waiting']);
const WORK = ['working', 'browsing', 'writing'];   // the states with the laptop out
const calm = matchMedia('(prefers-reduced-motion: reduce)').matches, M = calm ? 0.4 : 1, SPEED = calm ? 0.6 : 1;
const S = (a, f) => M * a * Math.sin(f);
// pose at time T: head nod (hx), turn (hy) and tilt (hz), body turn (ry), bounce (y), ears and how they differ
// (ear, earD), eyes open, and where the eyes look (ex, ey)
const FACE = { hx: 0, hy: 0, hz: 0.06, ry: -0.2, y: 0, ear: -0.25, earD: 0, eyes: 1, ex: 0, ey: 0 };
const FACES = {
  idle: () => FACE,
  thinking: (T) => ({ ...FACE, hx: -0.17 + S(0.025, T * 1.3), hy: 0.26 + S(0.05, T * 0.6), hz: -0.06 + S(0.05, T * 0.9), ry: -0.14, ear: -0.28, earD: 0.06, ex: 0.055, ey: 0.05 }),   // looks up at the bubble
  // at the laptop: the head dips to peek over the lid
  working: (T) => ({ ...FACE, hx: 0.3, hy: S(0.04, T * 0.7), hz: 0.04, ry: -0.1, ey: -0.045 }),
  browsing: (T) => ({ ...FACE, hx: 0.27, hy: S(0.1, T * 0.8), hz: 0.08, ry: -0.1, ear: -0.3, ex: S(0.03, T * 0.8), ey: -0.04 }),   // reads side to side
  writing: (T) => ({ ...FACE, hx: 0.28, hy: S(0.07, T * 1.3), hz: 0.02, ry: -0.1, ex: S(0.025, T * 1.3), ey: -0.045 }),
  waiting: (T) => ({ ...FACE, hx: -0.06, hz: 0.26, y: 0.035 * M * Math.max(0, Math.sin(T * 3)), ear: -0.42, ey: 0.015 }),   // head cocked, ears up: needs your OK
  offline: () => ({ ...FACE, hx: 0.18, eyes: 0.1 }),   // asleep
};
// Milo's move when it reacts to a message with an emoji (reaction.js shows the emoji in a cloud). Offsets on top of
// the face it has, `e` eases in, holds and out; `wide` opens the eyes. Picked by the user from drafts ("option B").
const hop = (t, at, len) => (t > at && t < at + len ? Math.sin((t - at) / len * Math.PI) : 0);
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

// ---- the props: built only for the avatar (the splash has none)
const lerp = (a, b, t) => a + (b - a) * t;
const ss = (a, b, x) => { const t = clamp((x - a) / (b - a)); return t * t * (3 - 2 * t); };
const easeOut = (x) => 1 - (1 - x) ** 3;
const inOut = (x) => (x < 0.5 ? 4 * x * x * x : 1 - (-2 * x + 2) ** 3 / 2);
const settle = (x) => 1 + 2.3 * (x - 1) ** 3 + 1.3 * (x - 1) ** 2;   // a small overshoot, softer than the splash's
const TAU = Math.PI * 2;
// a prop's way in or out (0..1 over `len` seconds): it speeds up and slows down softly, and turns back without a jump
function travel(len) {
  const top = 1 / len, acc = top * 4;
  return {
    x: 0, v: 0, to: 0,
    step(dt) {
      const d = this.to - this.x, dist = Math.abs(d), want = Math.sign(d) * Math.min(top, Math.sqrt(2 * acc * dist));
      this.v += Math.max(-acc * dt, Math.min(acc * dt, want - this.v));
      let x = this.x + this.v * dt;
      if (dist < 1e-4 || (this.to - x) * d < 0) { x = this.to; this.v = 0; }
      this.x = clamp(x);
    },
    still() { return this.x === this.to && this.v === 0; },
  };
}
// a soft rounded slab: x across, z deep, y from 0 to h
function slab(w, d, h, r) {
  const b = Math.min(0.022, h * 0.35), x = w / 2 - b, y = d / 2 - b, k = Math.max(0.005, Math.min(r - b, x, y));
  const s = new THREE.Shape();
  s.moveTo(-x + k, -y); s.lineTo(x - k, -y); s.quadraticCurveTo(x, -y, x, -y + k); s.lineTo(x, y - k);
  s.quadraticCurveTo(x, y, x - k, y); s.lineTo(-x + k, y); s.quadraticCurveTo(-x, y, -x, y - k); s.lineTo(-x, -y + k);
  s.quadraticCurveTo(-x, -y, -x + k, -y);
  const g = new THREE.ExtrudeGeometry(s, { depth: Math.max(0.001, h - 2 * b), bevelEnabled: true, bevelThickness: b, bevelSize: b, bevelSegments: 3, curveSegments: 6 });
  g.rotateX(-Math.PI / 2); g.translate(0, b, 0);
  return g;
}
// a terracotta laptop; its origin is the middle of the base, the hinge at -z. The back of the lid carries a sign
// that says what Milo does: dots (working), a globe (browsing), lines (writing).
function makeLaptop() {
  const W = 1.1, D = 0.72, H = 0.075, T = 0.06, shell = mat(C.ear);
  const g = new THREE.Group(); g.visible = false;
  add(slab(W, D, H, 0.09), shell, [0, 0, 0], g);
  add(new THREE.PlaneGeometry(W - 0.12, D - 0.12), mat(C.tag), [0, H + 0.003, 0], g, [-Math.PI / 2, 0, 0]);   // the keys
  const hinge = new THREE.Group(); hinge.position.set(0, H, -D / 2); g.add(hinge);
  add(slab(W, D, T, 0.09), shell, [0, 0.008, D / 2], hinge);
  const c = document.createElement('canvas'); c.width = c.height = 128;
  const tex = new THREE.CanvasTexture(c); tex.colorSpace = THREE.SRGBColorSpace;
  const sign = new THREE.MeshBasicMaterial({ map: tex, transparent: true, depthWrite: false, toneMapped: false });
  add(new THREE.PlaneGeometry(0.44, 0.44), sign, [0, 0.008 + T + 0.004, D / 2 + 0.02], hinge, [-Math.PI / 2, 0, Math.PI]);
  return { g, hinge, H, sign: { g: c.getContext('2d'), tex } };
}
function rr(g, x, y, w, h, r) {
  if (w <= 0) return;
  r = Math.min(r, w / 2, h / 2);
  g.beginPath(); g.moveTo(x + r, y); g.arcTo(x + w, y, x + w, y + h, r); g.arcTo(x + w, y + h, x, y + h, r);
  g.arcTo(x, y + h, x, y, r); g.arcTo(x, y, x + w, y, r); g.closePath(); g.fill();
}
function drawSign({ g, tex }, mix, T, wt) {
  g.clearRect(0, 0, 128, 128);
  g.fillStyle = g.strokeStyle = '#fbf1e6';
  if (mix.working > 0.01) {   // three dots that pulse in turn
    g.globalAlpha = mix.working;
    for (let i = 0; i < 3; i++) {
      const k = 0.5 + 0.5 * Math.sin(T * 5 - i * 0.9);
      g.beginPath(); g.arc(34 + i * 30, 64 - 6 * k, 9 + 4 * k, 0, TAU); g.fill();
    }
  }
  if (mix.browsing > 0.01) {   // a turning globe
    g.globalAlpha = mix.browsing; g.lineWidth = 8;
    const w = Math.abs(Math.cos(T * 1.2)) * 34;
    g.beginPath(); g.arc(64, 64, 34, 0, TAU); g.stroke();
    g.beginPath(); g.ellipse(64, 64, Math.max(0.5, w), 34, 0, 0, TAU); g.stroke();
    g.beginPath(); g.moveTo(30, 64); g.lineTo(98, 64); g.stroke();
  }
  if (mix.writing > 0.01) {   // lines that grow one by one, then fade and start again
    const k = (wt * 0.9) % 3.6;
    g.globalAlpha = mix.writing * (1 - ss(3.1, 3.5, k));
    for (let i = 0; i < 3; i++) rr(g, 24, 34 + i * 26, 80 * ss(i, i + 0.85, k) * [1, 0.8, 0.6][i], 13, 6.5);
  }
  g.globalAlpha = 1; tex.needsUpdate = true;
}
// a thought bubble beside the head: two small puffs and a cloud with three dots
function makeBubble() {
  const g = new THREE.Group(), light = mat(C.light), ink = new THREE.MeshStandardMaterial({ color: C.ink, roughness: 0.95 });
  g.visible = false;
  const t1 = blob(light, 0.075, [1, 1, 1], [-0.46, -0.52, -0.08], g);
  const t2 = blob(light, 0.11, [1, 1, 1], [-0.3, -0.33, -0.04], g);
  const cloud = new THREE.Group(); g.add(cloud);
  blob(light, 0.3, [1.3, 0.82, 0.6], [0, 0, 0], cloud);
  blob(light, 0.19, [1, 1, 0.75], [-0.22, 0.07, -0.02], cloud);
  blob(light, 0.21, [1, 1, 0.75], [0.2, 0.09, -0.02], cloud);
  blob(light, 0.2, [1, 1, 0.75], [0, 0.17, -0.04], cloud);
  const dots = [-0.15, 0, 0.15].map((x) => blob(ink, 0.058, [1, 1, 0.8], [x, 0.02, 0.17], cloud));
  for (const m of [t1, t2, cloud]) m.scale.setScalar(0.001);   // they grow in when it shows
  return { g, t1, t2, cloud, dots };
}
const BUBBLE = { x: 0.85, y: 3.25, z: 0.9, s: 0.75 };   // over the right ear, inside the header circle with a margin

// The look: while Milo is idle, the dog keeps its face to the user's face, not to the screen. The face is taken to
// be where the screen pointed a moment ago: a baseline that slowly follows the phone, so a tilt held for a while
// becomes the new normal and the dog drifts back to center. The dog turns against the phone's turn away from that
// baseline (phone turned left, the dog turns to its right). A finger near the dog wins: it watches the finger.
const DEG = Math.PI / 180;
const LIM = { yaw: 0.5, pitch: 0.3, roll: 0.3 };   // radians; past these a sitting dog would look strained
const soft = (x, lim) => lim * Math.tanh(x / lim);   // gives way near the limit instead of stopping hard
function spring(w, z) {   // damped: a little lag and overshoot read as alive, not mechanical
  return {
    x: 0, v: 0, to: 0,
    step(dt) { for (let n = Math.ceil(dt / 0.008), h = dt / n; n--;) { this.v += (w * w * (this.to - this.x) - 2 * z * w * this.v) * h; this.x += this.v * h; } },
    still() { return Math.abs(this.to - this.x) < 0.002 && Math.abs(this.v) < 0.01; },
  };
}
const screenAngle = () => screen.orientation?.angle ?? (typeof window.orientation === 'number' ? window.orientation : 0);
function gaze(canvas, kick, face) {
  const calm = matchMedia('(prefers-reduced-motion: reduce)').matches, k = calm ? 0.3 : 1, z = calm ? 1 : 0.62;
  // the eyes lead, the head follows, the body comes last
  const sp = { yaw: spring(7, z), pitch: spring(7, z), roll: spring(6, z), body: spring(3, 0.9), ex: spring(16, 0.8), ey: spring(16, 0.8) };
  const q = new THREE.Quaternion(), base = new THREE.Quaternion(), prev = new THREE.Quaternion(), turn = new THREE.Quaternion(), e = new THREE.Euler(), zee = new THREE.Vector3(0, 0, 1);
  const tilt = { yaw: 0, pitch: 0, roll: 0 };
  let on = false, idle = true, heard = false, live = false, angle = null, last = 0, began = 0, finger = null;

  const aim = () => {
    let y = 0, p = 0, r = 0, see = false;
    if (finger) {
      const b = canvas.getBoundingClientRect(), dx = finger.x - b.left - b.width / 2, dy = finger.y - b.top - b.height / 2;
      // with the tilt, only a finger near him wins over it; without (denied, a desktop), any finger does
      if (!live || Math.hypot(dx, dy) < 200) { y = Math.atan2(dx, 260); p = Math.atan2(dy, 260); see = true; }
    }
    if (!see && live) { y = tilt.yaw; p = tilt.pitch; r = tilt.roll; see = true; }
    const go = on && idle && see, Y = go ? soft(y, LIM.yaw) * k : 0, P = go ? soft(p, LIM.pitch) * k : 0, R = go ? soft(r, LIM.roll) * k : 0;
    sp.yaw.to = (go ? face : 0) + 0.75 * Y;   // `face` undoes the body's turn, so the face is square to the user
    sp.body.to = 0.25 * Y;
    sp.pitch.to = 0.8 * P;
    sp.roll.to = 0.7 * R;
    sp.ex.to = 0.05 * Y / LIM.yaw;
    sp.ey.to = -0.035 * P / LIM.pitch;
    if (!still()) kick();
  };
  const still = () => Object.values(sp).every((s) => s.still());

  const orient = (ev) => {
    if (ev.beta == null || ev.gamma == null) return;   // a desktop sends one empty event
    const t = ev.timeStamp / 1000, gap = t - last, dt = live ? Math.min(0.5, Math.max(0, gap)) : 0, a = screenAngle();
    last = t;
    e.set(ev.beta * DEG, ev.gamma * DEG, (ev.alpha || 0) * DEG, 'ZXY');   // the spec's Z-X'-Y'' angles
    q.setFromEuler(e).multiply(turn.setFromAxisAngle(zee, -a * DEG));     // in landscape, the screen's axes, not the phone's
    // iOS restarts the sensor after a pause, with alpha from 0 again wherever the phone points, and may first repeat an
    // old reading. A gap or a jump no hand makes (30 degrees in one reading) is a new start, and the readings of a start's
    // first 0.3 s only set the normal: otherwise the dog swings away and takes seconds to come back.
    if (!live || gap > 0.5 || 2 * Math.acos(Math.min(1, Math.abs(q.dot(prev)))) > 0.5) began = t;
    if (t - began < 0.3 || a !== angle) base.copy(q);   // a new start or a turn to landscape: here is the normal
    prev.copy(q);
    live = true; angle = a;
    turn.copy(q).invert().multiply(base);     // the user's face, seen from the screen now
    const off = 2 * Math.acos(Math.min(1, Math.abs(turn.w)));
    base.slerp(q, 1 - Math.exp(-dt / (off > 1.2 ? 0.5 : 3)));   // a big change (the phone laid down) is the normal sooner
    e.setFromQuaternion(turn, 'YXZ');
    tilt.yaw = e.y; tilt.pitch = e.x; tilt.roll = e.z;
    aim();
  };
  const touch = (ev) => {
    finger = ev.type === 'pointerup' || ev.type === 'pointercancel' || (ev.type === 'pointermove' && !finger) ? null : { x: ev.clientX, y: ev.clientY };
    aim();
  };
  const TOUCH = ['pointerdown', 'pointermove', 'pointerup', 'pointercancel'];
  const listen = () => {   // the sensors run only while the dog can look
    const want = on && idle;
    if (want === heard) return;
    heard = want;
    const f = want ? 'addEventListener' : 'removeEventListener';
    window[f]('deviceorientation', orient);
    TOUCH.forEach((t) => window[f](t, touch, { passive: true }));
    if (!want) { live = false; finger = null; }
  };
  return {
    look(v) { if (v !== on) { on = v; listen(); aim(); } },
    idle(v) { if (v !== idle) { idle = v; listen(); aim(); } },
    step(dt) { for (const s of Object.values(sp)) s.step(dt); return sp; },
    still,
  };
}

export function avatar(canvas) {
  const { renderer, sc, parts, dispose } = setup(canvas, false, 3);
  const cam = new THREE.PerspectiveCamera(30, 1, 0.1, 50);
  renderer.setSize(canvas.clientWidth, canvas.clientHeight, false);
  const far = 3.5 / (2 * Math.tan(THREE.MathUtils.degToRad(15)));
  const aimCam = (drop, zoom) => {   // eases down and back a little while a prop is out, so it fits the circle
    cam.position.set(0, HEAD.y + 0.25 - drop, far * (1 + zoom));
    cam.lookAt(0, HEAD.y - 0.12 - drop, 0);
  };
  aimCam(0, 0);
  let state = 'idle', doneAt = -9, blinkAt = -9, raf = 0, last = 0, now = 0, fresh = true;
  let lapWant = 0, hopWait = false, phase = 0, wclock = 0, lastWork = 'working', signAt = -9;
  let rx = null;   // a reaction playing: { name, at, side }
  const look = gaze(canvas, () => kick(), -FACES.idle().ry);
  parts.head.rotation.order = 'YXZ';   // turn, then nod, then tilt, like a neck
  const lap = makeLaptop(), bub = makeBubble();
  parts.dog.add(lap.g, bub.g);
  bub.g.position.set(BUBBLE.x, BUBBLE.y, BUBBLE.z); bub.g.scale.setScalar(BUBBLE.s);
  const P = { lap: travel(1.15), bub: travel(0.9) };
  // the eyes glance ahead of the head: each slides on the head's surface at its own depth, turned with the surface,
  // so it never sinks in
  const surf = (x, y, out = new THREE.Vector3()) => {
    out.set(x, y, 0.92 * Math.sqrt(Math.max(0, 1 - (x / 1.05) ** 2 - (y / 0.9) ** 2)));
    return out;
  };
  const normal = (p, out = new THREE.Vector3()) => out.set(p.x / 1.05 ** 2, p.y / 0.9 ** 2, p.z / 0.92 ** 2).normalize();
  const eyeAt = parts.eyes.map((e) => {
    const s = surf(e.position.x, e.position.y), n = normal(s);
    return { at: e.position.clone(), n, depth: s.sub(e.position).dot(n) };
  });
  const eyeS = new THREE.Vector3(), eyeN = new THREE.Vector3();
  // a front leg points from its shoulder to its paw and stretches a little; rest is the pose makeDog built
  const legs = parts.arms.map((a) => {
    const d = a.rest.clone().sub(a.arm.position);
    return { dir: d.clone().normalize(), len: d.length(), to: new THREE.Vector3(), r: [0, 0, 0] };
  });
  const v1 = new THREE.Vector3();
  const weight = Object.fromEntries(Object.keys(FACES).map((f) => [f, f === 'idle' ? 1 : 0]));
  const mix = () => {   // which sign the lid shows; between jobs it keeps the last one
    const s = weight.working + weight.browsing + weight.writing;
    return s < 0.001 ? Object.fromEntries(WORK.map((w) => [w, +(w === lastWork)])) : Object.fromEntries(WORK.map((w) => [w, weight[w] / s]));
  };
  const glance = (T, period = 3.7) => { const k = T % period; return ss(period - 1, period - 0.75, k) * (1 - ss(period - 0.35, period - 0.1, k)); };

  const poseAt = (T, dt) => {
    const ease = 1 - Math.exp(-dt / 0.35);
    const pose = { ...FACE };
    for (const c in pose) pose[c] = 0;
    let sum = 0;
    for (const f in weight) {
      weight[f] += ((f === state ? 1 : 0) - weight[f]) * ease;
      if (weight[f] < 0.001) continue;
      const q = FACES[f](T);
      for (const c in pose) pose[c] += q[c] * weight[f];
      sum += weight[f];
    }
    for (const c in pose) pose[c] /= sum;
    const W = weight, work = W.working + W.browsing + W.writing;

    // the laptop rises in front and settles in the paws (0..0.55), then the lid opens (0.52..0.97); out, the reverse
    P.lap.to = lapWant; P.lap.step(dt);
    P.bub.to = state === 'thinking' ? 1 : 0; P.bub.step(dt);
    const L = P.lap.x, up = settle(clamp(L / 0.55)), open = inOut(clamp((L - 0.52) / 0.45));
    lap.g.visible = L > 0.001;
    lap.g.position.set(0, lerp(-1.9, 1.03, up), 1.3 + 0.95 * (1 - easeOut(clamp(L / 0.55))) ** 2);
    lap.g.rotation.set(0.35 * (1 - up), Math.PI, 0.12 * (1 - up));
    lap.hinge.rotation.x = -1.8 * open;
    lap.g.updateMatrix();
    if (hopWait && L < 0.04) { hopWait = false; doneAt = T; }   // the hop comes once the laptop is away
    look.idle(state === 'idle' && L < 0.04);                    // and so does the look: never while busy

    // paws tap beside the lid: quick for work, steady for writing, with pauses to read a page
    const typing = work * ss(0.8, 1, L), rate = (W.working * 12 + W.browsing * 6 + W.writing * 8.5 + 0.001) / (work + 0.001);
    phase += dt * rate * SPEED;
    const pause = W.browsing / (work + 0.001) * (1 - ss(-0.3, 0.5, Math.sin(T * 1.25))), amp = typing * (1 - 0.8 * pause);
    const gl = glance(T) * work * ss(0.8, 1, L);   // looks up from the screen now and then
    pose.hx += -0.32 * gl + 0.025 * M * amp * Math.sin(phase * 2);
    pose.ey += 0.075 * gl;
    pose.earD += 0.06 * M * amp * Math.sin(phase);
    if (W.writing > 0.3) wclock += dt * SPEED; else if (L === 0) wclock = 0;   // a pause for an OK keeps the lines
    const hold = ss(0.25, 0.55, L), keys = ss(0.78, 0.95, L), chin = W.thinking * (1 - hold);
    parts.arms.forEach((a, i) => {
      const s = a.s, leg = legs[i], t = leg.to.copy(a.rest), r = leg.r.fill(0);
      if (hold > 0) {   // hold the sides while the lid opens, then rest on the outer keys
        t.lerp(v1.set(-s * 0.72, 0.06, 0.04).applyMatrix4(lap.g.matrix), hold); r[2] = s * 1.25 * hold;
        const tap = 0.075 * M * amp * Math.max(0, Math.sin(phase + (i ? Math.PI : 0)));
        t.lerp(v1.set(-s * 0.46, lap.H + 0.17 + tap, 0.05 + 0.03 * Math.sin(phase * 0.5 + i)).applyMatrix4(lap.g.matrix), keys);
        r[0] = lerp(r[0], 0.12 - tap * 2, keys); r[2] = lerp(r[2], 0, keys);
      }
      if (s < 0 && chin > 0.001) {   // thinking: the right paw at the chin, tapping slowly
        t.lerp(v1.set(-0.08, 1.68 + 0.035 * M * Math.max(0, Math.sin(T * 2.6)), 1.12), chin);
        r[0] = lerp(r[0], -1.15, chin); r[1] = lerp(r[1], 0.2, chin); r[2] = lerp(r[2], -0.25, chin);
      }
      v1.subVectors(t, a.arm.position);
      a.arm.scale.y = Math.max(0.5, Math.min(1.5, v1.length() / leg.len));
      a.arm.quaternion.setFromUnitVectors(leg.dir, v1.normalize());
      a.paw.position.copy(t); a.paw.rotation.set(...r);
    });
    if (open > 0.02 && T - signAt > 1 / 15) { signAt = T; drawSign(lap.sign, mix(), T * SPEED, wclock); }   // 15 fps is enough

    // the bubble: the puffs grow in turn, then the cloud; its dots fill one by one
    const B = P.bub.x;
    bub.g.visible = B > 0.001;
    if (bub.g.visible) {
      bub.t1.scale.setScalar(Math.max(0.001, settle(clamp(B * 2.6))));
      bub.t2.scale.setScalar(Math.max(0.001, settle(clamp(B * 2.6 - 0.7))));
      bub.cloud.scale.setScalar(Math.max(0.001, settle(clamp((B - 0.4) / 0.6))));
      bub.g.position.y = BUBBLE.y + 0.03 * M * Math.sin(T * 1.6 * SPEED);
      const c = (T * 0.75 * SPEED) % 1;
      bub.dots.forEach((m, i) => {
        const k = Math.max(0.001, ss(0.08 + i * 0.16, 0.2 + i * 0.16, c) * (1 - ss(0.84, 0.96, c)));
        m.scale.set(k, k, 0.8 * k); m.position.y = 0.02 + 0.025 * M * Math.sin(T * 4 * SPEED - i * 0.9) * k;
      });
    }
    aimCam(0.3 * L + 0.15 * B, 0.14 * L + 0.1 * B);

    const d = T - doneAt;                // a happy hop when a task finishes
    if (d < 0.8) { pose.y += 0.28 * Math.max(0, Math.sin(Math.min(1, d / 0.5) * Math.PI)); pose.ear += 0.25 * Math.sin(d * 14) * (1 - d / 0.8); }
    let wide = 1;
    if (rx) {                            // a reaction: its move, looking up at the cloud on its side
      const t = T - rx.at, m = MOVES[rx.name], e = ss(0, 0.25, t) * (1 - ss(m.len - 0.45, m.len, t));
      if (t > m.len) rx = null;
      else {
        const o = m.f(Math.max(0, t), e);
        for (const c in o) if (c in pose) pose[c] += o[c];
        wide += o.wide || 0;
        pose.hy += 0.24 * e * rx.side; pose.hx -= 0.1 * e;
      }
    }
    if (T - blinkAt < 0.13) pose.eyes = Math.min(pose.eyes, 0.12);
    const g = look.step(dt);
    parts.dog.position.y = pose.y; parts.dog.rotation.y = pose.ry + g.body.x;
    parts.head.rotation.set(pose.hx + g.pitch.x, pose.hy + g.yaw.x, pose.hz + g.roll.x);
    parts.ears.forEach((e, i) => { e.rotation.x = pose.ear + (i ? -pose.earD : pose.earD); });
    parts.eyes.forEach((e, i) => {
      const { at, n, depth } = eyeAt[i];
      surf(at.x + pose.ex + g.ex.x, at.y + pose.ey + g.ey.x, eyeS); normal(eyeS, eyeN);
      e.position.copy(eyeS).addScaledVector(eyeN, -depth);
      e.quaternion.setFromUnitVectors(n, eyeN);
      e.scale.set(wide, pose.eyes * wide, wide);
    });
  };
  const moving = () => BUSY.has(state) || weight[state] < 0.995 || !P.lap.still() || !P.bub.still() || hopWait
    || now - doneAt < 0.8 || now - blinkAt < 0.13 || !look.still() || !!rx;
  const frame = (ms) => {
    raf = 0; now = ms / 1000;
    const go = moving();
    if (!go || ms - last > 30) {         // about 30 fps is plenty here
      poseAt(now, fresh ? 1 / 30 : Math.min(0.1, (ms - last) / 1000));
      last = ms; fresh = false; renderer.render(sc, cam);
    }
    if (go) raf ||= requestAnimationFrame(frame); else if (!raf) fresh = true;   // ||=: a kick during the frame already asked
  };
  const kick = () => { raf ||= requestAnimationFrame(frame); };
  let timer = 0;
  const blink = () => {
    timer = setTimeout(blink, 3500 + Math.random() * 3500);
    if (state !== 'offline' && !document.hidden) { blinkAt = performance.now() / 1000; kick(); }
  };
  blink(); kick();
  return {
    set(next) {
      if (next === state || !FACES[next]) return;
      if (WORK.includes(next)) { lapWant = 1; lastWork = next; } else if (next !== 'waiting') lapWant = 0;   // an OK mid-task keeps the laptop
      hopWait = next === 'idle' && BUSY.has(state);
      state = next; look.idle(next === 'idle' && P.lap.x < 0.04); kick();
    },
    // a reaction's move (MOVES); side: 1 looks up to the right, -1 to the left (where the cloud is). Reduced motion: none.
    react(name, side = 1) { if (calm || !MOVES[name]) return; rx = { name, at: performance.now() / 1000, side }; kick(); },
    look: look.look,   // the app says when the dog may look around (header in view, no keyboard)
    parts, props: { lap, bub, P },
    dispose() { look.look(false); clearTimeout(timer); cancelAnimationFrame(raf); dispose(); },
  };
}
