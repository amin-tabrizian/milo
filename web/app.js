'use strict';

// ---------- helpers ----------
const $ = (s, el = document) => el.querySelector(s);
const $$ = (s, el = document) => [...el.querySelectorAll(s)];
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));
const store = {
  get(k, d = null) { try { const v = localStorage.getItem(k); return v === null ? d : v; } catch { return d; } },
  set(k, v) { try { localStorage.setItem(k, v); } catch {} },
  del(k) { try { localStorage.removeItem(k); } catch {} },
};
const isIOS = /iP(hone|ad|od)/.test(navigator.userAgent) || (navigator.platform === 'MacIntel' && navigator.maxTouchPoints > 1);
const standalone = window.navigator.standalone || matchMedia('(display-mode: standalone)').matches;

const ICON = {
  x: '<svg viewBox="0 0 24 24"><path d="M6 6l12 12M18 6L6 18"/></svg>',
  mic: '<svg viewBox="0 0 24 24"><rect x="9" y="3" width="6" height="11" rx="3"/><path d="M5 11a7 7 0 0 0 14 0M12 18v3"/></svg>',
  speaker: '<svg viewBox="0 0 24 24"><path d="M4 9v6h4l5 4V5L8 9H4z"/><path d="M16 9a4 4 0 0 1 0 6"/></svg>',
  copy: '<svg viewBox="0 0 24 24"><rect x="9" y="9" width="11" height="11" rx="2"/><path d="M5 15V5a2 2 0 0 1 2-2h8"/></svg>',
  check: '<svg viewBox="0 0 24 24"><path d="M5 12l5 5L20 7"/></svg>',
  pencil: '<svg viewBox="0 0 24 24"><path d="M4 20h4L19 9l-4-4L4 16z"/><path d="M13.5 6.5l4 4"/></svg>',
  trash: '<svg viewBox="0 0 24 24"><path d="M4 7h16M10 11v6M14 11v6M6 7l1 12a2 2 0 0 0 2 2h6a2 2 0 0 0 2-2l1-12M9 7V4h6v3"/></svg>',
  play: '<svg viewBox="0 0 24 24"><path d="M7 5v14l11-7z"/></svg>',
  shield: '<svg viewBox="0 0 24 24"><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/><path d="M12 8v5M12 16v.5"/></svg>',
  brain: '<svg viewBox="0 0 24 24"><path d="M9 4a3 3 0 0 0-3 3 3 3 0 0 0-2 5 3 3 0 0 0 2 5 3 3 0 0 0 6 1V5a2 2 0 0 0-3-1zM15 4a3 3 0 0 1 3 3 3 3 0 0 1 2 5 3 3 0 0 1-2 5 3 3 0 0 1-6 1"/></svg>',
  clock: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 3"/></svg>',
  compact: '<svg viewBox="0 0 24 24"><path d="M4 14h6v6M20 10h-6V4M14 10l7-7M3 21l7-7"/></svg>',
  tool: '<svg viewBox="0 0 24 24"><path d="M14.7 6.3a4 4 0 0 0-5.4 5.4L3 18l3 3 6.3-6.3a4 4 0 0 0 5.4-5.4l-2.6 2.6-2.4-.6-.6-2.4z"/></svg>',
  file: '<svg viewBox="0 0 24 24"><path d="M14 3H7a2 2 0 0 0-2 2v14a2 2 0 0 0 2 2h10a2 2 0 0 0 2-2V8z"/><path d="M14 3v5h5"/></svg>',
  folder: '<svg viewBox="0 0 24 24"><path d="M4 5a2 2 0 0 1 2-2h4l2 3h6a2 2 0 0 1 2 2v10a2 2 0 0 1-2 2H6a2 2 0 0 1-2-2z"/></svg>',
  chevron: '<svg viewBox="0 0 24 24"><path d="M9 6l6 6-6 6"/></svg>',
  download: '<svg viewBox="0 0 24 24"><path d="M12 4v11M7 10l5 5 5-5M5 20h14"/></svg>',
  star: '<svg viewBox="0 0 24 24"><path d="M12 3.6l2.6 5.3 5.8.8-4.2 4.1 1 5.8L12 16.9l-5.2 2.7 1-5.8-4.2-4.1 5.8-.8z"/></svg>',
  stop: '<svg viewBox="0 0 24 24"><rect x="7" y="7" width="10" height="10" rx="2"/></svg>',
  chat: '<svg viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.8 7L4 20l1.1-4.6A8 8 0 1 1 21 12z"/></svg>',
  globe: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3a14 14 0 0 1 0 18M12 3a14 14 0 0 0 0 18"/></svg>',
  key: '<svg viewBox="0 0 24 24"><circle cx="8" cy="15" r="4"/><path d="M11 12l9-9M17 6l3 3M14 9l2 2"/></svg>',
};

const IDEAS = [
  ['Plan my day', 'Check my calendar and email, then tell me what matters today.'],
  ['Catch me up', 'Summarize my unread email and flag anything urgent.'],
  ['Morning brief', 'Every weekday at 8am, brief me on my calendar and important email.'],
  ['Get to know me', 'Ask me a few questions about myself and my preferences, then remember the answers.'],
  ['Make a document', 'Write a one-page PDF on the key ideas of a topic I give you, and save it to my Library.'],
  ['Tidy up', 'Find the largest files in my Downloads folder and suggest what I can delete.'],
];

// ---------- state ----------
const S = {
  token: null,
  ws: null, wsOpen: false, retry: 0,
  convs: [], current: null, conv: null,
  approvals: new Map(),
  settings: {}, modes: {}, vapidKey: null, voiceInput: true,
  tab: 'chat', thinking: false,
  dictating: false, transcribing: false, typedWhileBusy: false, sendAfter: false,   // push-to-talk
  pendingRef: null, myVoiceConvs: new Set(),
  speakPolicy: store.get('speak_policy', 'never'),   // replies are read aloud only with the speaker button
  browser: {},
  mainId: null, onMain: true,   // the main chat (like Muse); other chats are side chats
  nav: 0,   // counts chat switches: an answer that arrives after you moved on must not switch you back
  ranAt: {},   // schedule id -> when Run now was tapped
};

// ---------- API ----------
async function api(path, opts = {}) {
  const headers = { Authorization: `Bearer ${S.token}`, ...(opts.headers || {}) };
  let body = opts.body;
  if (body && !(body instanceof FormData) && typeof body !== 'string') { body = JSON.stringify(body); headers['Content-Type'] = 'application/json'; }
  const r = await fetch(path, { ...opts, headers, body });
  if (r.status === 401) { showPair('That token did not work.'); throw new Error('unauthorized'); }
  if (!r.ok) { let d = r.statusText; try { d = (await r.json()).detail || d; } catch {} throw Object.assign(new Error(d), { status: r.status }); }
  const ct = r.headers.get('content-type') || '';
  return ct.includes('json') ? r.json() : r;
}
const fileUrl = (p, dl) => `/api/library/file?path=${encodeURIComponent(p)}&token=${encodeURIComponent(S.token)}${dl ? '&download=1' : ''}`;

function toast(text, ms = 2600) {
  const t = $('#toast'); t.textContent = text; t.classList.remove('pill');
  showToast(t, ms);
}
let toastTimer = 0;
function showToast(t, ms) {
  t.hidden = false; t.classList.remove('out');
  clearTimeout(toastTimer); toastTimer = setTimeout(() => { t.classList.add('out'); toastTimer = setTimeout(() => (t.hidden = true), 200); }, ms);
}
// A wide pill at the bottom with an icon, a bold line and a detail (like Telegram's "176.7 MB freed"): a job that is done
function doneToast(text, detail = '', ms = 3200) {
  const t = $('#toast'), b = document.createElement('b'), d = document.createElement('span');
  b.textContent = text; d.textContent = detail;
  t.innerHTML = '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9.5"/><path d="M7.8 12.3l2.8 2.8 5.6-5.8"/></svg>';
  t.append(b);
  if (detail) t.append(d);
  t.classList.add('pill');
  showToast(t, ms);
}

const UndoStop = {
  id: null,
  show(ev) {
    const el = $('#undoStop'), n = ev.agents;
    this.id = ev.id;
    el.querySelector('span').textContent = `Stopping Milo and ${n} helper agent${n > 1 ? 's' : ''}`;
    $('#toast').hidden = true; el.hidden = false; el.classList.remove('out');
    clearTimeout(this.t); this.t = setTimeout(() => this.hide(), ev.grace * 1000);
  },
  hide() {
    const el = $('#undoStop');
    clearTimeout(this.t); this.id = null;
    if (el.hidden) return;
    el.classList.add('out'); this.t = setTimeout(() => (el.hidden = true), 200);
  },
};
$('#undoStop button').onclick = () => { if (UndoStop.id) send({ type: 'keep', id: UndoStop.id }); };

// ---------- markdown ----------
const DIRECTIVES = ['remember', 'schedule', 'suggest', 'goal', 'quiet', 'react', 'restart', 'say'];
function stripDirectives(t) {
  t = t.replace(/<(remember|schedule|suggest|goal|react)\b[^>]*>[\s\S]*?<\/\1>/g, '')
    .replace(/<(quiet|restart)\s*\/?>(\s*<\/\1>)?/g, '')   // no closing tag needed
    .replace(/<\/?say>/g, '')   // Siri's spoken part stays in the chat, as the start of the reply
    .replace(/<(remember|schedule|suggest|goal|quiet|react|restart)\b[\s\S]*$/, '');
  const m = t.match(/<\/?([a-z]*)$/);   // a tag still streaming in
  return m && DIRECTIVES.some((n) => n.startsWith(m[1])) ? t.slice(0, m.index) : t;
}
// LaTeX math: $..$ and \(..\) inline; $$..$$, \[..\], ```math and a bare \begin{align} (matrix, cases...) on its own line
// as a block. KaTeX (web/vendor/katex, no CDN: the phone may be offline on the tailnet) loads with the first reply that
// has math. A $ is math only if it closes on the same line, with no space inside either end and no digit right after
// the closing $, so "$5 and $10" and "$5-$10" stay prices. Bad LaTeX shows as written.
const MATH = { cache: new Map(), load: null };
const MATH_ENV = 'align|alignat|gather|equation|multline|split|[pbBvV]?matrix|smallmatrix|cases|dcases|rcases|array|aligned|gathered|alignedat|CD';
const MATH_WAIT = '<span class="math display pending"></span>';   // a block still streaming in: room for it, not raw LaTeX
function tex(src, display, raw) {   // raw: the math as written, with its delimiters
  const K = window.katex, cls = `math${display ? ' display' : ''}`;
  if (!K) { mathLoad(); return `<span class="${cls} wait" data-tex="${esc(src)}" data-raw="${esc(raw)}">${esc(raw)}</span>`; }
  const key = (display ? 'D' : 'I') + raw;
  let h = MATH.cache.get(key);
  if (h === undefined) {   // a streaming reply is rebuilt many times: draw each formula once
    try { h = `<span class="${cls}">${K.renderToString(src, { displayMode: display, throwOnError: true, strict: 'ignore', trust: false, maxSize: 50, maxExpand: 1000 })}</span>`; }
    catch (e) { h = `<span class="${cls} bad" title="${esc(e?.message || 'Bad LaTeX')}">${esc(raw)}</span>`; }
    if (MATH.cache.size > 500) MATH.cache.clear();
    MATH.cache.set(key, h);
  }
  return h;
}
function mathLoad() {   // the math already on screen is drawn in place when KaTeX arrives
  if (MATH.load || typeof document === 'undefined' || !document) return;
  const css = Object.assign(document.createElement('link'), { rel: 'stylesheet', href: '/vendor/katex/katex.min.css' });
  const js = Object.assign(document.createElement('script'), { src: '/vendor/katex/katex.min.js' });
  const ready = (el) => new Promise((ok, no) => { el.onload = ok; el.onerror = no; });
  MATH.load = Promise.all([ready(css), ready(js)]).then(() => {
    document.querySelectorAll('.math.wait').forEach((el) => { el.outerHTML = tex(el.dataset.tex, el.classList.contains('display'), el.dataset.raw); });
  }, () => { MATH.load = null; css.remove(); js.remove(); });   // not reached: try again with the next reply
  document.head.append(css, js);
}
// Block math that may span lines becomes one token before md() splits the text into lines, so the list, table and
// heading rules never see its insides. open: the text is still streaming, and a block not closed yet keeps its place.
function mathBlocks(s, open) {
  if (!/\$\$|\\\[|\\begin\{/.test(s)) return s;
  const codes = [], tok = (raw) => `\u0003${encodeURIComponent(raw)}\u0003`;
  s = s.replace(/(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g, (c) => `\u0005${codes.push(c) - 1}\u0005`);   // `$$` in code stays code
  s = s.replace(/\$\$(?!\$)([\s\S]*?)\$\$/g, (all, t) => t.trim() && !/\n\s*\n/.test(t) ? tok(all) : all)
    .replace(/\\\[([\s\S]+?)\\\]/g, (all, t) => /[\\^_=]/.test(t) && !/\n\s*\n/.test(t) ? tok(all) : all)   // not an escaped \[link\]
    .replace(new RegExp(`(^|\\n)([ \\t]*)(\\\\begin\\{(${MATH_ENV})(\\*?)\\}[\\s\\S]*?\\\\end\\{\\4\\5\\})`, 'g'), (_, nl, sp, all) => nl + sp + tok(all));
  if (open) {
    const at = [s.search(/\$\$(?!\$)/), s.search(/\\\[(?![\s\S]*\\\])/), s.search(new RegExp(`(^|\\n)[ \\t]*\\\\begin\\{(${MATH_ENV})\\*?\\}`))].filter((k) => k >= 0);
    if (at.length) { const k = Math.min(...at); s = s.slice(0, k) + (s[k] === '\n' ? '\n' : '') + '\u0003\u0003'; }
  }
  return s.replace(/\u0005(\d+)\u0005/g, (_, i) => codes[i]);
}
function inlineMath(s, put) {   // put(html) keeps the drawn math out of the escaping and the emphasis rules
  if (!/[$\u0003]|\\\(/.test(s)) return s;
  s = s.replace(/\n?\u0003([^\u0003]*)\u0003\n?/g, (_, r) => {   // a block from mathBlocks; its own line breaks go
    if (!r) return put(MATH_WAIT);
    const raw = decodeURIComponent(r);
    return put(tex(/^(\$\$|\\\[)/.test(raw) ? raw.slice(2, -2).trim() : raw, true, raw));
  });
  s = s.replace(/\\\(([\s\S]+?)\\\)/g, (all, t) => put(tex(t.trim(), false, all)));
  let out = '', k = 0;
  for (let i; (i = s.indexOf('$', k)) >= 0;) {
    let j = i + 1;
    while ((j = s.indexOf('$', j)) > 0 && s[j - 1] === '\\') j++;   // \$ inside the math
    const ok = j > i + 1 && s[i - 1] !== '\\' && !/\d/.test(s[i - 1] || '') && /[^\s$]/.test(s[i + 1])
      && !/\s/.test(s[j - 1]) && !/[\d$]/.test(s[j + 1] || '') && !s.slice(i, j).includes('\n');
    if (!ok) { out += s.slice(k, i + 1); k = i + 1; continue; }
    out += s.slice(k, i) + put(tex(s.slice(i + 1, j), false, s.slice(i, j + 1)));
    k = j + 1;
  }
  return out + s.slice(k);
}
// Bold, italics and strikethrough on escaped text. **a *b* c** nests; snake_case and 2 * 3 stay as they are.
function emph(s) {
  return s.replace(/~~(?=\S)([^~]*?\S)~~/g, '<del>$1</del>')
    .replace(/\*\*\*(?=[^\s*])([^*]*?[^\s*])\*\*\*/g, '<strong><em>$1</em></strong>')
    .replace(/\*\*(?=[^\s*])((?:[^*]|\*(?!\*))*?[^\s*])\*\*/g, '<strong>$1</strong>')
    .replace(/(^|[^\w])__(?=[^\s_])([^_]*?[^\s_])__(?!\w)/g, '$1<strong>$2</strong>')
    .replace(/(^|[^*])\*(?=[^\s*])([^*]*?[^\s*])\*(?!\*)/g, '$1<em>$2</em>')
    .replace(/(^|[^\w])_(?=[^\s_])([^_]*?[^\s_])_(?!\w)/g, '$1<em>$2</em>');
}
function inline(s) {
  const codes = [];
  s = s.replace(/(`+)(?!`)([\s\S]*?[^`])\1(?!`)/g, (_, f, c) => `\u0000${codes.push(c.replace(/^ ([\s\S]*) $/, '$1')) - 1}\u0000`);   // ``a ` b`` too
  const figs = [];   // ![alt](src "caption"): kept out of the escaping and the link rules
  // A path with spaces, as Milo writes a Library plot's name, also counts without the <> it needs in Markdown
  s = s.replace(/!\[([^\]]*)\]\(\s*(?:<([^>]+)>|([^)\s]+)|((?:\/|~\/)(?:[^()"\n]|\([^()"\n]*\))*?\.(?:png|jpe?g|gif|webp|svg|avif|bmp|heic)))(?:\s+"([^"]*)")?\s*\)/gi,
    (all, alt, a, b, c, cap) => imgSrc(a || b || c) ? `\u0002${figs.push(figHtml(a || b || c, alt, cap ?? alt)) - 1}\u0002` : all);
  // Links and \-escapes are kept out of the emphasis rules: a _ or * in a URL is not italics. Only http(s) and mailto
  // links; they open outside the app (noopener: the page can't reach back into Milo).
  const keep = [], put = (h) => `\u0006${keep.push(h) - 1}\u0006`;
  const a = (href, label) => put(`<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${label}</a>`);
  s = inlineMath(s, put);   // before the \-escapes: \( and \$ belong to the math
  s = s.replace(/\\([\\`*_~[\]()#+\-.!|>{}$])/g, (_, c) => put(esc(c)))
    .replace(/(^|[^!])\[([^\]\n]+)\]\(\s*<?((?:https?:\/\/|mailto:)[^\s()<>]+(?:\([^\s()<>]*\)[^\s()<>]*)*)>?(?:\s+"[^"]*")?\s*\)/g,
      (_, pre, label, href) => pre + a(href, emph(esc(label))))
    .replace(/(^|[\s(["'])(https?:\/\/[^\s<>"]*[^\s<>"'.,;:!?\]*_~])/g, (_, pre, href) => {
      let tail = '';   // "(see https://x.com)" keeps its ")", a wiki "Foo_(bar)" link keeps its own
      while (href.endsWith(')') && href.split(')').length > href.split('(').length) { href = href.slice(0, -1); tail = ')' + tail; }
      return pre + a(href, esc(href)) + esc(tail);
    });
  s = emph(esc(s)).replace(/\n/g, '<br>');
  while (/\u0006\d+\u0006/.test(s)) s = s.replace(/\u0006(\d+)\u0006/g, (_, i) => keep[i]);
  return s.replace(/\u0000(\d+)\u0000/g, (_, i) => `<code>${esc(codes[i])}</code>`).replace(/\u0002(\d+)\u0002/g, (_, i) => figs[i]);
}
// GFM tables. A pipe inside `code` or $math$, or written \|, stays in its cell ($5 | $10 is two prices, not math).
function tableCells(line) {
  const s = line.trim().replace(/^\|/, ''), cells = [];
  let cur = '';
  for (let k = 0; k < s.length; k++) {
    const c = s[k];
    if (c === '\\' && s[k + 1] === '|') { cur += '|'; k++; continue; }
    if (c === '`') {
      const run = s.slice(k).match(/^`+/)[0], end = s.indexOf(run, k + run.length);
      if (end > 0) { cur += s.slice(k, end + run.length).replace(/\\\|/g, '|'); k = end + run.length - 1; continue; }
    }
    if (c === '$' && s[k - 1] !== '\\') {
      let end = -1;
      if (s[k + 1] === '$') end = s.indexOf('$$', k + 2) + 1;
      else if (/\S/.test(s[k + 1] || '')) {
        for (let e = k + 2; e < s.length; e++) if (s[e] === '$' && /[^\s\\]/.test(s[e - 1]) && !/\d/.test(s[e + 1] || '')) { end = e; break; }
      }
      if (end > 0) { cur += s.slice(k, end + 1); k = end; continue; }
    }
    if (c === '|') { cells.push(cur.trim()); cur = ''; continue; }
    cur += c;
  }
  if (cur.trim() || !/\|\s*$/.test(s)) cells.push(cur.trim());
  return cells;
}
// A table starting at lines[j], or null: { html, end } with end its last line. open: the text is still streaming, so a
// header whose separator row has not arrived yet already shows as a table (no "| a | b |" line that jumps into a grid).
function mdTable(lines, j, open) {
  const line = lines[j], next = lines[j + 1], lead = /^\s*\|/.test(line);
  if (!line.includes('|')) return null;
  const full = next !== undefined && /^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$/.test(next) && (lead || next.includes('|'));
  const cut = open && lead && (j + 1 === lines.length || (j + 2 === lines.length && /^\s*\|?[\s:|-]*$/.test(next)));
  if (!full && !cut) return null;
  const head = tableCells(line);
  const aligns = full ? tableCells(next).map((a) => /^:-*:$/.test(a) ? 'c' : /-:$/.test(a) ? 'r' : '') : [];
  let end = j + (next === undefined ? 0 : 1);
  const rows = [];
  if (full) while (end + 1 < lines.length && lines[end + 1].includes('|')) rows.push(tableCells(lines[++end]));
  if (!head.length) return { html: '', end };   // a lone "|" streaming in
  const cell = (tag, c, k) => {   // long: a sentence gets a readable width, not one word per line
    const cls = [aligns[k], tag === 'td' && (c || '').length > 28 && 'long'].filter(Boolean).join(' ');
    return `<${tag}${cls ? ` class="${cls}"` : ''}>${inline(c || '')}</${tag}>`;
  };
  return { end, html: `<div class="table-wrap"><table><thead><tr>${head.map((h, k) => cell('th', h, k)).join('')}</tr></thead>${
    rows.length ? `<tbody>${rows.map((r) => `<tr>${head.map((_, k) => cell('td', r[k], k)).join('')}</tr>`).join('')}</tbody>` : ''}</table></div>` };
}
// Fenced code opens and closes only at the start of a line (``` inside a sentence stays text), with ``` or ~~~, also
// indented under a list item. Splits like text.split(/```/): text, code, text...; a code part is "info\ncode".
function fenceParts(text) {
  const parts = [], buf = [];
  let fence = null;
  for (const line of text.split('\n')) {
    let m;
    if (!fence && (m = line.match(/^(\s*)(`{3,}|~{3,})\s*([^`]*)$/))) {
      parts.push(buf.join('\n')); buf.length = 0; buf.push(m[3].trim());
      fence = { ind: new RegExp(`^ {0,${m[1].length}}`), end: new RegExp(`^\\s*${m[2][0]}{${m[2].length},}\\s*$`) };
    } else if (fence && fence.end.test(line)) { parts.push(buf.join('\n')); buf.length = 0; fence = null; }
    else buf.push(fence ? line.replace(fence.ind, '') : line);
  }
  parts.push(buf.join('\n'));
  return parts;
}
// While a reply streams in, its last line may stop inside a marker. Close what is open and drop a bare marker, so "**bo"
// is bold at once instead of raw stars that jump into bold a moment later.
function mdTail(t) {
  if (fenceParts(t).length % 2 === 0) return t;   // inside a code block: shown as it is
  const k = t.lastIndexOf('\n') + 1, last = t.slice(k);
  if (/^\s*(#{1,6}|[-*+_]{1,2}|\d{1,9}[.)]?|>|`{1,2}|~{1,2})\s*$/.test(last)) return t.slice(0, k);   // "##", "-", "1.", "``"
  const lead = last.match(/^\s*(?:(?:[-*+]|\d{1,9}[.)])\s+(?:\[[ xX]?\]?\s*)?|>\s?|#{1,6}\s+)*/)[0];
  let s = last.slice(lead.length).replace(/[\s*~`\\]+$/, '')   // a marker that just opened, or a closing one cut short
    .replace(/!?\[([^\]]*)\](\([^)]*)?$/, (all, label) => all[0] === '!' ? '' : label)   // a link still coming: its text
    .replace(/!?\[([^\]]*)$/, (all, label) => all[0] === '!' ? '' : label);
  if ((s.match(/`/g) || []).length % 2) s += '`';
  const bare = s.replace(/`[^`]*`/g, '').replace(/\$[^$]+\$|\\\([\s\S]*?\\\)/g, ''), dbl = (bare.match(/\*\*/g) || []).length;   // a * in $a * b$ is math
  if ((bare.replace(/\*\*/g, '').match(/\*/g) || []).length % 2) s += '*';
  if (dbl % 2) s += '**';
  if ((bare.match(/~~/g) || []).length % 2) s += '~~';
  return t.slice(0, k) + lead + s;
}
// Nested lists from their indents (2+ spaces deeper is a sub-list), numbered from where they start, with task boxes.
function listHtml(items) {
  let k = 0;
  const level = () => {
    const base = items[k].d;
    let h = '', t = null;
    while (k < items.length && items[k].d >= base) {
      const it = items[k++], task = it.x.match(/^\[([ xX])\](?:\s+|$)([\s\S]*)/);
      if (it.t !== t) { if (t) h += `</${t}>`; t = it.t; h += `<${t}${t === 'ol' && it.n !== 1 ? ` start="${it.n}"` : ''}>`; }
      h += task ? `<li class="task"><input type="checkbox" disabled${task[1] === ' ' ? '' : ' checked'}>${inline(task[2])}` : `<li>${inline(it.x)}`;
      if (k < items.length && items[k].d >= base + 2) h += level();
      h += '</li>';
    }
    return h + `</${t}>`;
  };
  let h = '';
  while (k < items.length) h += level();
  return h;
}
// A code block: its language and a copy button above, colored by highlight.js (web/vendor, loaded the first time it's needed).
function codeBlock(info, code) {
  const lang = (info || '').trim().split(/\s+/)[0].toLowerCase();
  let body = esc(code);
  if (lang && window.hljs) {
    if (hljs.getLanguage(lang)) try { body = hljs.highlight(code, { language: lang, ignoreIllegals: true }).value; } catch {}
  } else if (lang) loadHljs();
  return `<div class="code"><div class="code-bar"><span>${esc(lang)}</span><button class="code-copy" aria-label="Copy code">${COPY_SVG}</button></div><pre><code>${body}</code></pre></div>`;
}
const COPY_SVG = ICON.copy;
function loadHljs() {
  if (loadHljs.s || !globalThis.document) return;   // no page: the node tests
  const s = loadHljs.s = document.createElement('script');
  s.src = '/vendor/highlight/highlight.min.js';
  s.onload = () => { if (S.conv) renderMessages(); };   // the code already shown gets its colors
  s.onerror = () => { s.remove(); loadHljs.s = null; };
  document.head.append(s);
}
document.addEventListener('click', (e) => {
  const b = e.target.closest('.code-copy');
  if (b) navigator.clipboard?.writeText(b.closest('.code').querySelector('code').textContent).then(() => toast('Copied'), () => {});
});
function md(src, live) {   // live: the text is still streaming in, so its last lines may be cut off
  const text = live ? mdTail(stripDirectives(src || '')) : stripDirectives(src || '');
  const out = [];
  const parts = fenceParts(text);
  parts.forEach((part, i) => {
    if (i % 2 === 1) {
      const nl = part.indexOf('\n');
      if (nl >= 0 && part.slice(0, nl).trim().toLowerCase() === 'svg') { out.push(svgFig(part.slice(nl + 1), live && i === parts.length - 1)); return; }
      if (nl >= 0 && part.slice(0, nl).trim().toLowerCase() === 'mermaid') { out.push(mmdFig(part.slice(nl + 1), live && i === parts.length - 1)); return; }
      if (nl >= 0 && part.slice(0, nl).trim().toLowerCase() === 'weather') { out.push(weatherBlock(part.slice(nl + 1), live && i === parts.length - 1)); return; }
      if (nl >= 0 && part.slice(0, nl).trim().toLowerCase() === 'math') { out.push(`<p>${live && i === parts.length - 1 ? MATH_WAIT : tex(part.slice(nl + 1).trim(), true, part.slice(nl + 1).trim())}</p>`); return; }
      out.push(codeBlock(nl >= 0 ? part.slice(0, nl) : part, nl >= 0 ? part.slice(nl + 1).replace(/\n$/, '') : ''));
      return;
    }
    const lines = mathBlocks(part, live && i === parts.length - 1).split('\n');
    let para = [], list = null;
    const flushP = () => { if (para.length) { out.push(`<p>${inline(para.join('\n'))}</p>`); para = []; } };   // a new line stays one
    const flushL = () => { if (list) { out.push(listHtml(list)); list = null; } };
    for (let j = 0; j < lines.length; j++) {
      const line = lines[j];
      let m;
      if (!line.trim()) { flushP(); flushL(); continue; }
      if ((m = line.match(/^\s{0,3}(#{1,6})\s+(.*?)(?:\s+#+)?\s*$/))) { flushP(); flushL(); const h = Math.min(m[1].length + 1, 6); out.push(`<h${h}>${inline(m[2])}</h${h}>`); continue; }
      if (/^\s{0,3}([-*_])(\s*\1){2,}\s*$/.test(line)) { flushP(); flushL(); out.push('<hr>'); continue; }   // ---, ***, * * *
      if ((m = line.match(/^(\s*)([-*+]|\d{1,9}[.)])\s+(.*)/))) {   // nesting by indent, kept in listHtml
        flushP(); (list ||= []).push({ d: m[1].replace(/\t/g, '    ').length, t: /\d/.test(m[2]) ? 'ol' : 'ul', n: parseInt(m[2], 10), x: m[3] });
        continue;
      }
      const tb = mdTable(lines, j, live && i === parts.length - 1);
      if (tb) { flushP(); flushL(); out.push(tb.html); j = tb.end; continue; }
      if ((m = line.trim().match(IMG_LINE)) && imgSrc(m[1])) { flushP(); flushL(); out.push(figHtml(m[1], '', '')); continue; }   // a saved picture's path
      if (/^\s{0,3}>/.test(line)) {   // one quote for all its lines, with lists and headings inside
        flushP(); flushL(); const q = [];
        while (j < lines.length && /^\s{0,3}>/.test(lines[j])) q.push(lines[j++].replace(/^\s{0,3}>\s?/, ''));
        j--; out.push(`<blockquote>${md(q.join('\n'))}</blockquote>`); continue;
      }
      if (list && /^\s{2,}\S/.test(line)) { list[list.length - 1].x += '\n' + line.trim(); continue; }
      flushL(); para.push(line.trim());
    }
    flushP(); flushL();
  });
  return out.join('');
}

// ---------- weather cards ----------
// get_weather's data (on its step, or a ```weather block in a saved briefing) drawn as a card. WMO codes -> icons.
const WX_CLOUD = 'M7 19h10a4 4 0 0 0 .6-7.96A6 6 0 0 0 6.2 11.1 4 4 0 0 0 7 19z';
const WX_HIGH = 'M7 15h10a3.5 3.5 0 0 0 .5-6.96A5.5 5.5 0 0 0 6.6 8.6 3.2 3.2 0 0 0 7 15z';   // a cloud with room below
const WX_ICON = {
  sun: '<svg viewBox="0 0 24 24"><circle cx="12" cy="12" r="4"/><path d="M12 3v2M12 19v2M3 12h2M19 12h2M5.6 5.6l1.4 1.4M17 17l1.4 1.4M5.6 18.4L7 17M17 7l1.4-1.4"/></svg>',
  moon: '<svg viewBox="0 0 24 24"><path d="M19.5 14.5A7.5 7.5 0 0 1 9.5 4.5a7.5 7.5 0 1 0 10 10z"/></svg>',
  partly: `<svg viewBox="0 0 24 24"><path d="M8 3.5v1.2M3.5 8h1.2M4.8 4.8l.9.9M11.2 4.8l-.9.9"/><path d="M5.3 10.8A3.2 3.2 0 0 1 10.6 6"/><path d="${WX_CLOUD}"/></svg>`,
  cloud: `<svg viewBox="0 0 24 24"><path d="${WX_CLOUD}"/></svg>`,
  rain: `<svg viewBox="0 0 24 24"><path d="${WX_HIGH}"/><path d="M8.5 18l-1 2.5M12.5 18l-1 2.5M16.5 18l-1 2.5"/></svg>`,
  snow: `<svg viewBox="0 0 24 24"><path d="${WX_HIGH}"/><path d="M8 18.5h.01M12 20h.01M16 18.5h.01M10 21.5h.01M14 21.5h.01"/></svg>`,
  storm: `<svg viewBox="0 0 24 24"><path d="${WX_HIGH}"/><path d="M12.5 15l-2 3.5h3l-2 3.5"/></svg>`,
  fog: '<svg viewBox="0 0 24 24"><path d="M4 9h16M6 13h12M4 17h16"/></svg>',
  alert: '<svg viewBox="0 0 24 24"><path d="M12 4L2.8 19.5h18.4z"/><path d="M12 10v4.5M12 17.2h.01"/></svg>',
};
function wxKind(code, day = true) {
  const c = Number(code);
  if (c <= 1) return day ? 'sun' : 'moon';
  if (c === 2) return day ? 'partly' : 'cloud';
  if (c === 3) return 'cloud';
  if (c === 45 || c === 48) return 'fog';
  if ((c >= 71 && c <= 77) || c === 85 || c === 86) return 'snow';
  if (c >= 95) return 'storm';
  return c >= 51 ? 'rain' : 'cloud';
}
const wxIcon = (code, day) => { const k = wxKind(code, day); return `<span class="wx-i ${k}" aria-hidden="true">${WX_ICON[k]}</span>`; };
const wxDeg = (t) => (t == null || t === '' || isNaN(t) ? '–' : `${Math.round(t)}°`);
const wxRain = (p) => (Number(p) >= 20 ? `${Math.round(p)}%` : '');   // under 20%: noise, left out
function wxHour(iso) {   // "2026-10-26T14:00" -> "2 PM", the place's own clock
  const h = Number(String(iso).slice(11, 13));
  return isNaN(h) ? '' : `${h % 12 || 12} ${h < 12 ? 'AM' : 'PM'}`;
}
function wxDay(date, i) {
  if (i === 0) return 'Today';
  const d = new Date(`${date}T12:00`);
  return isNaN(d) ? String(date) : d.toLocaleDateString([], { weekday: 'short' });
}
function weatherCard(w) {
  if (!w || typeof w !== 'object' || !w.now) return '';
  const now = w.now, days = Array.isArray(w.days) ? w.days : [], today = days[0] || {};
  const hours = (Array.isArray(w.hours) ? w.hours : []).filter((h, i) => i % 2 === 0).slice(0, 6);   // every 2 hours
  const wet = hours.some((h) => wxRain(h.rain));   // a rain row only when some hour has one
  const sub = [now.feels != null && Math.abs(now.feels - now.temp) >= 3 ? `Feels like ${wxDeg(now.feels)}` : '',
    now.wind != null ? `Wind ${Math.round(now.wind)} ${esc(w.wind_unit || '')}` : '',
    today.rain != null ? `Rain ${Math.round(today.rain)}%` : ''].filter(Boolean).join(' · ');
  const lo = Math.min(...days.map((d) => d.low)), hi = Math.max(...days.map((d) => d.high)), span = hi - lo || 1;
  const dayRows = days.length > 1 ? `<div class="wx-days">${days.map((d, i) => `<div class="wx-day">
      <span class="wx-dname">${esc(wxDay(d.date, i))}</span>${wxIcon(d.code, true)}<span class="wx-drain">${wxRain(d.rain)}</span>
      <span class="wx-lo">${wxDeg(d.low)}</span><span class="wx-bar"><i style="left:${((d.low - lo) / span * 100).toFixed(1)}%;right:${((hi - d.high) / span * 100).toFixed(1)}%"></i></span><span class="wx-hi">${wxDeg(d.high)}</span>
    </div>`).join('')}</div>` : '';
  const alerts = (Array.isArray(w.alerts) ? w.alerts : []).map((a) => {
    const ends = a.ends && !isNaN(new Date(a.ends)) ? ` until ${new Date(a.ends).toLocaleString([], { weekday: 'short', hour: 'numeric', minute: '2-digit' })}` : '';
    return `<div class="wx-alert">${WX_ICON.alert}<span>${esc(a.event)}${esc(ends)}</span></div>`;
  }).join('');
  return `<div class="wx" role="group" aria-label="Weather for ${esc(w.location || '')}">
    <div class="wx-now">
      <div class="wx-left">
        <div class="wx-place">${esc(w.location || 'Weather')}${w.time ? `<span> · ${esc(wxHour(w.time))}</span>` : ''}</div>
        <div class="wx-temp">${wxDeg(now.temp)}</div>
        <div class="wx-cond">${esc(now.conditions || '')}${days.length ? ` <span>H ${wxDeg(today.high)} L ${wxDeg(today.low)}</span>` : ''}</div>
      </div>
      ${wxIcon(now.code, now.day !== false)}
    </div>
    ${sub ? `<div class="wx-sub">${sub}</div>` : ''}
    ${alerts}
    ${hours.length ? `<div class="wx-hours">${hours.map((h, i) => `<div class="wx-h"><span>${i ? esc(wxHour(h.time)) : 'Now'}</span>${wxIcon(h.code, h.day)}<b>${wxDeg(i ? h.temp : now.temp)}</b>${wet ? `<small>${wxRain(h.rain)}</small>` : ''}</div>`).join('')}</div>` : ''}
    ${dayRows}
  </div>`;
}
function weatherBlock(src, partial) {   // a ```weather block: the card, or the JSON as code if it is not ours
  if (partial) return '<div class="wx wx-wait" aria-hidden="true"></div>';
  try { const html = weatherCard(JSON.parse(src)); if (html) return html; } catch {}
  return codeBlock('weather', src.replace(/\n$/, ''));
}
const weatherCards = (tools) => (tools || []).filter((t) => t.weather).map((t) => weatherCard(t.weather)).join('');

// ---------- pictures in replies ----------
// From the web, the Library (a path) or a data URL. A ```svg block is cleaned and then shown as an <img>, which never
// runs scripts or loads anything, so nothing in it can reach the app or its token.
const IMG = { ok: new Set(), bad: new Set() };   // loads seen: a reply rebuilt while it streams shows them at once
const IMG_EXT = /\.(png|jpe?g|gif|webp|svg|avif|bmp|heic)$/i;
const IMG_LINE = /^`?((?:\/|~\/)[^`\n]*?\.(?:png|jpe?g|gif|webp|svg|avif|bmp|heic))`?$/i;   // a line that is only a picture's path
const IMG_BROKEN = '<svg viewBox="0 0 24 24"><rect x="3" y="4" width="18" height="16" rx="2"/><path d="M3 16l5-5 4 4M14 13l2-2 5 5M4 4l16 16"/></svg>';
function imgSrc(u) {
  u = String(u || '').trim();
  if (/^https?:\/\//i.test(u)) return u;
  if (/^data:image\/(png|jpe?g|gif|webp|svg\+xml);base64,[a-z0-9+/=\s]+$/i.test(u)) return u.replace(/\s+/g, '');
  if (/^file:\/\//i.test(u)) { try { u = decodeURIComponent(u.slice(7)); } catch { return null; } }
  u = u.replace(/^~\/Documents\/Milo\/Library\//i, '');   // the Library's usual place (the server resolves inside it)
  // ~/Documents/Milo/... may be Temp, where Milo keeps plots it only shows; the server takes a picture only from there
  // or the Library
  if (/^[a-z][a-z0-9+.-]*:/i.test(u) || (u.startsWith('~') && !/^~\/Documents\/Milo\//i.test(u)) || !IMG_EXT.test(u.split(/[?#]/)[0])) return null;
  return `/api/picture?path=${encodeURIComponent(u)}&token=${encodeURIComponent(S.token)}`;
}
function figHtml(src, alt, cap, cls = '') {
  const s = imgSrc(src);
  if (!s) return esc(alt || src);
  let name = alt || (/^data:/i.test(s) ? 'Image' : String(src).split(/[?#]/)[0].split('/').pop() || 'Image');
  try { name = decodeURIComponent(name); } catch {}
  const state = IMG.bad.has(s) ? ' broken' : IMG.ok.has(s) ? '' : ' loading';
  return `<span class="fig${cls}${state}"><img src="${esc(s)}" alt="${esc(alt || '')}" loading="lazy" decoding="async"${cap ? ` data-cap="${esc(cap)}"` : ''}>`
    + `<span class="fig-bad" role="img" aria-label="Image did not load">${IMG_BROKEN}<span>${esc(name)}</span></span>${cap ? `<span class="figcap">${esc(cap)}</span>` : ''}</span>`;
}
// Only drawing elements; no scripts, links, foreign HTML or animation (an <animate> can turn an href into a script).
const SVG_TAGS = new Set(('svg g path rect circle ellipse line polyline polygon text tspan textPath defs linearGradient radialGradient stop '
  + 'clipPath mask pattern marker symbol use title desc style image filter feGaussianBlur feOffset feBlend feFlood feComposite '
  + 'feMerge feMergeNode feColorMatrix feDropShadow').split(' '));
const SVG_NS = 'http://www.w3.org/2000/svg';
function cleanSvg(src) {
  if (!src || src.length > 2e6) return null;
  const doc = new DOMParser().parseFromString(src, 'image/svg+xml'), root = doc.documentElement;
  if (doc.getElementsByTagName('parsererror').length || root.localName !== 'svg' || root.namespaceURI !== SVG_NS) return null;
  const outside = /url\s*\(\s*['"]?\s*(?!#)|@import|expression\s*\(|javascript:|vbscript:/i;   // anything that leaves the picture
  for (const el of [...root.querySelectorAll('*')].reverse()) {
    if (!SVG_TAGS.has(el.localName) || el.namespaceURI !== SVG_NS || (el.localName === 'style' && outside.test(el.textContent))) el.remove();
  }
  for (const el of [root, ...root.querySelectorAll('*')]) {
    for (const a of [...el.attributes]) {
      const n = a.localName.toLowerCase(), v = a.value;
      const pic = el.localName === 'image' && /^data:image\/(png|jpe?g|gif|webp);base64,/i.test(v.trim());
      if (n.startsWith('on') || n === 'base' || outside.test(v) || (n === 'href' && !v.trim().startsWith('#') && !pic)) el.removeAttributeNode(a);
    }
  }
  const vb = (root.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
  if (!root.getAttribute('width') && vb.length === 4 && vb[2] > 0) { root.setAttribute('width', vb[2]); root.setAttribute('height', vb[3]); }
  const paper = doc.createElementNS(SVG_NS, 'rect');   // a plot drawn for a white page stays readable in dark mode and the viewer
  Object.entries(vb.length === 4 ? { x: vb[0], y: vb[1], width: vb[2], height: vb[3] } : { width: '100%', height: '100%' }).forEach(([k, v]) => paper.setAttribute(k, v));
  paper.setAttribute('fill', '#fff'); root.insertBefore(paper, root.firstChild);
  return new XMLSerializer().serializeToString(root);
}
function svgFig(code, open) {   // open: the block is still streaming in
  if (open) return '<span class="fig svg loading"><img alt=""></span>';
  const svg = cleanSvg(code.trim());
  if (!svg) return `<pre><code>${esc(code).replace(/\n$/, '')}</code></pre>`;
  const title = (code.match(/<title[^>]*>([^<]*)<\/title>/i) || [])[1]?.trim() || '';
  return figHtml(`data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(svg)))}`, title, title, ' svg');
}
// A picture loads or fails: drop its placeholder, or show the fallback. load and error don't bubble, so catch them.
document.addEventListener('load', (e) => {
  const f = e.target.parentElement;
  if (e.target.tagName !== 'IMG' || !f?.classList.contains('fig')) return;
  IMG.ok.add(e.target.getAttribute('src')); f.classList.remove('loading');
}, true);
document.addEventListener('error', (e) => {
  const f = e.target.parentElement;
  if (e.target.tagName !== 'IMG' || !f?.classList.contains('fig')) return;
  IMG.bad.add(e.target.getAttribute('src')); f.classList.remove('loading'); f.classList.add('broken');
}, true);
function openFigure(img) {   // full screen in the photo viewer: pinch, double tap and pull down to close work as in the feed
  $('#mediaStage').innerHTML = `<div class="media-zoom${img.parentElement.classList.contains('svg') ? ' svg' : ''}"><img src="${esc(img.getAttribute('src'))}" alt="${esc(img.alt)}"></div>`;
  MZ.zoom = 1;
  $('#mediaCount').textContent = '';
  $('#mediaFoot').innerHTML = img.dataset.cap ? `<p class="figcap">${esc(img.dataset.cap)}</p>` : '';
  const v = $('#mediaView'); v.hidden = false; v.dataset.pid = ''; v.dataset.fq = '';
  $('#mediaStage').onscroll = null; $('#mediaStage').scrollLeft = 0;
}
$('#messages').addEventListener('click', (e) => {
  const img = e.target.closest('.fig:not(.loading):not(.broken) > img');
  if (img) openFigure(img);
});

// ---------- diagrams in replies ----------
// A ```mermaid block is drawn by Mermaid (web/vendor/mermaid, loaded with the first one; no CDN, the phone may be
// offline) and shown as a picture: tap to enlarge and pinch work as for photos, and nothing in it runs. A block still
// streaming in is not drawn (half a diagram is a syntax error); a bad one shows its source with a short note.
const MMD = { lib: null, done: new Map(), ids: new Map(), queue: Promise.resolve() };   // done: theme + source -> { svg } or { err }
function darkTheme() {   // Dark picked in Settings, or System while the system is dark
  const t = typeof document !== 'undefined' && document.documentElement.dataset.theme;
  return t ? t === 'dark' : typeof matchMedia === 'function' && matchMedia('(prefers-color-scheme: dark)').matches;
}
function mmdTheme() { return darkTheme() ? 'dark' : 'light'; }
function mmdFig(code, open) {   // open: the block is still streaming in
  const src = code.replace(/\s+$/, ''), wait = (n) => `<span class="fig svg mermaid loading"${n ? ` data-mmd="${n}"` : ''}><img alt=""></span>`;
  if (open) return wait();
  const key = `${mmdTheme()}\n${src}`, r = MMD.done.get(key);
  if (r?.svg) return figHtml(r.svg, 'Diagram', '', ' svg mermaid');
  if (r || !src.trim()) return `<div class="mermaid-bad"><pre><code>${esc(src)}</code></pre><div class="mermaid-err"${r ? ` title="${esc(r.err)}"` : ''}>Diagram error</div></div>`;
  if (!MMD.ids.has(key)) { MMD.ids.set(key, MMD.ids.size + 1); mmdDraw(key, src); }
  return wait(MMD.ids.get(key));
}
function mmdDraw(key, src) {
  if (typeof document === 'undefined') return;
  const n = MMD.ids.get(key), dark = key.startsWith('dark');
  MMD.queue = MMD.queue.then(async () => {   // one at a time: Mermaid's render is not reentrant
    try {
      MMD.lib ||= import('/vendor/mermaid/mermaid.esm.min.mjs').then((m) => m.default);
      const mermaid = await MMD.lib.catch((e) => { MMD.lib = null; throw e; });   // offline: the next diagram tries again
      mermaid.initialize({ startOnLoad: false, securityLevel: 'strict', suppressErrorRendering: true, theme: dark ? 'dark' : 'neutral',
        fontFamily: '-apple-system, BlinkMacSystemFont, "Helvetica Neue", Arial, sans-serif', htmlLabels: false, flowchart: { htmlLabels: false } });
      await mermaid.parse(src);
      MMD.done.set(key, { svg: mmdImg((await mermaid.render(`mmd-${n}`, src)).svg, dark) });
    } catch (e) {
      MMD.done.set(key, { err: String(e?.message || e).split('\n')[0].slice(0, 200) });
    }
    document.getElementById(`dmmd-${n}`)?.remove(); document.getElementById(`mmd-${n}`)?.remove();   // left over after an error
    const sc = $('#chatScroll'), follow = Follow.on && sc.scrollHeight - sc.scrollTop - sc.clientHeight < 80;
    for (const el of document.querySelectorAll(`[data-mmd="${n}"]`)) {
      const t = document.createElement('template'); t.innerHTML = mmdFig(src, false); el.replaceWith(t.content);
    }
    if (follow) requestAnimationFrame(() => setTimeout(() => { if (Follow.on) sc.scrollTop = sc.scrollHeight; }, 60));
  });
}
function mmdImg(svg, dark) {   // Mermaid writes HTML; an <img> needs XML, a size of its own and a background
  const el = new DOMParser().parseFromString(svg, 'text/html').querySelector('svg');
  const vb = (el.getAttribute('viewBox') || '').trim().split(/[\s,]+/).map(Number);
  if (vb.length === 4 && vb[2] > 0) { el.setAttribute('width', Math.ceil(vb[2])); el.setAttribute('height', Math.ceil(vb[3])); }
  el.removeAttribute('style');
  el.setAttribute('style', `background-color:${dark ? '#30302e' : '#ffffff'}`);
  return `data:image/svg+xml;base64,${btoa(unescape(encodeURIComponent(new XMLSerializer().serializeToString(el))))}`;
}
if (typeof matchMedia === 'function') matchMedia('(prefers-color-scheme: dark)').addEventListener('change', () => renderMessages());   // redraw in the new theme

// ---------- audio out ----------
const player = new Audio();
player.playsInline = true;
const SILENT = 'data:audio/wav;base64,UklGRiQAAABXQVZFZm10IBAAAAABAAEARKwAAIhYAQACABAAZGF0YQAAAAA=';
let audioUnlocked = false;
function unlockAudio() {
  if (audioUnlocked) return;
  audioUnlocked = true;
  // A silent clip played inside a user gesture lets iOS play replies later without a tap.
  player.src = SILENT;
  player.play().catch(() => {});
}
let speakToken = 0;
async function speak(text) {
  const my = ++speakToken;
  stopSpeaking(false);
  if (!text || !text.trim()) return;
  try {
    // Speak part by part: the next part is made on the Mac while this one plays.
    const { parts } = await api('/api/tts', { method: 'POST', body: { text, parts: true } });
    const audio = (t) => api('/api/tts', { method: 'POST', body: { text: t, raw: true } }).then((r) => r.blob());
    let next = parts.length ? audio(parts[0]) : null;
    // the lock screen shows the reply, not the last feed post, and its Pause stops the reading
    const meta = { title: text.replace(/[*_#`>|[\]]/g, '').replace(/\s+/g, ' ').trim().slice(0, 90), artist: S.settings.assistant_name || 'Milo', artwork: APP_ART };
    for (let i = 0; i < parts.length; i++) {
      const blob = await next;
      if (my !== speakToken) return;
      next = i + 1 < parts.length ? audio(parts[i + 1]) : null;
      next?.catch(() => {});
      const url = URL.createObjectURL(blob);
      player.src = url;
      try {
        hushOthers(player);
        setNowPlaying(player, meta, { pause: () => stopSpeaking() });
        await player.play();
        const ended = await new Promise((res) => { player.onended = () => res(true); player.onpause = () => res(player.ended); player.onerror = () => res(false); });
        if (!ended || my !== speakToken) return;   // stopped or interrupted
      } finally { URL.revokeObjectURL(url); }
    }
  } catch (e) { if (my === speakToken) console.warn('tts', e); }
  finally { if (my === speakToken) clearNowPlaying(player); }   // a newer reading keeps its own
}
function stopSpeaking(bump = true) { if (bump) speakToken++; try { player.pause(); } catch {} clearNowPlaying(player); }

// ---------- audio in ----------
// The AudioContext is only for voice mode's level meter, and lives only while the mic is open: iOS starts a kept
// context again each time the app comes back, and that stops music in other apps.
let audioCtx = null;
function getAudioCtx() {
  if (!audioCtx) audioCtx = new (window.AudioContext || window.webkitAudioContext)();
  if (audioCtx.state === 'suspended') audioCtx.resume();
  return audioCtx;
}
function releaseAudioCtx() {
  const ctx = audioCtx;
  audioCtx = null;
  try { ctx?.close().catch(() => {}); } catch {}
}
class Recorder {
  async open(meter = true) {
    if (this.stream) return;
    if (meter) getAudioCtx();   // still inside your tap, so iOS lets it run
    try {
      this.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true, autoGainControl: true } });
      if (!meter) return;
      const ctx = getAudioCtx();
      this.src = ctx.createMediaStreamSource(this.stream);
      this.an = ctx.createAnalyser(); this.an.fftSize = 1024;
      this.src.connect(this.an);
      this.buf = new Float32Array(this.an.fftSize);
    } catch (e) { this.close(); if (meter) releaseAudioCtx(); throw e; }
  }
  start() {
    const type = ['audio/mp4', 'audio/webm;codecs=opus', 'audio/webm'].find((t) => window.MediaRecorder && MediaRecorder.isTypeSupported(t)) || '';
    this.chunks = [];
    this.mr = new MediaRecorder(this.stream, type ? { mimeType: type } : undefined);
    this.mr.ondataavailable = (e) => e.data.size && this.chunks.push(e.data);
    this.mr.start(250);
    this.started = performance.now();
  }
  snapshot() {   // all audio so far, as one playable file
    return this.chunks?.length ? new Blob(this.chunks, { type: this.mr.mimeType || 'audio/mp4' }) : null;
  }
  stop() {
    return new Promise((res) => {
      if (!this.mr || this.mr.state === 'inactive') return res(null);
      this.mr.onstop = () => res(new Blob(this.chunks, { type: this.mr.mimeType || 'audio/mp4' }));
      this.mr.stop();
    });
  }
  level() {
    if (!this.an) return 0;
    this.an.getFloatTimeDomainData(this.buf);
    let s = 0; for (const v of this.buf) s += v * v;
    return Math.sqrt(s / this.buf.length);
  }
  close() {
    try { this.mr && this.mr.state !== 'inactive' && this.mr.stop(); } catch {}
    this.stream?.getTracks().forEach((t) => t.stop());
    try { this.src?.disconnect(); } catch {}
    if (this.an) releaseAudioCtx();
    this.stream = this.src = this.an = this.mr = null;
  }
}
async function transcribe(blob) {
  const fd = new FormData();
  fd.append('file', blob, blob.type.includes('webm') ? 'speech.webm' : 'speech.m4a');
  const { text } = await api('/api/transcribe', { method: 'POST', body: fd });
  return (text || '').trim();
}

// ---------- websocket ----------
function connect() {
  const proto = location.protocol === 'https:' ? 'wss' : 'ws';
  const ws = new WebSocket(`${proto}://${location.host}/ws?token=${encodeURIComponent(S.token)}`);
  S.ws = ws;
  clearTimeout(connect._retry);
  ws.onopen = () => {
    S.wsOpen = true; S.retry = 0; S.heard = Date.now(); setStatus();
    ws.send(JSON.stringify({ type: 'visible', value: document.visibilityState === 'visible' }));
    if (connect.seen) {
      for (const c of Chats.values()) c.at = 0;   // events were lost while offline: each kept chat loads again when opened
      refresh().then(() => { Unsent.check(); Tap.retry(); });
    }
    connect.seen = true;
  };
  ws.onclose = (e) => {
    if (S.ws !== ws) return;   // replaced by reconnect()
    S.wsOpen = false; setStatus();
    if (e.code === 4401) return showPair('That token did not work.');
    connect._retry = setTimeout(connect, Math.min(8000, 500 * 2 ** S.retry++));
  };
  ws.onmessage = (e) => { if (S.ws === ws) { S.heard = Date.now(); handle(JSON.parse(e.data)); } };
  clearInterval(connect._ping);
  connect._ping = setInterval(() => {   // the Mac answers each ping: no answer since the last one means the socket died
    if (!S.wsOpen) return;
    if (S.heard < connect._pinged) return reconnect();
    connect._pinged = Date.now(); ws.send(JSON.stringify({ type: 'ping' }));
  }, 25000);
}
// A socket that died without closing (iOS after the background, a Wi-Fi change) still looks open and swallows what
// is sent on it. Drop it without waiting for its close, which can take minutes, and connect again.
function reconnect() {
  const old = S.ws;
  S.ws = null; S.wsOpen = false; setStatus();
  try { old?.close(); } catch {}
  connect();
}
// Back in the app: check that the socket still answers, or connect at once rather than after the retry's wait.
function wake() {
  clearTimeout(wake.timer);
  if (!S.token || !connect.seen) return;
  if (!S.wsOpen) { if (S.ws?.readyState !== WebSocket.CONNECTING) connect(); return; }
  if (Date.now() - S.heard > 40000) return reconnect();   // asleep past two pings: iOS dropped it, don't wait 4 s to see
  const asked = Date.now();
  S.ws.send(JSON.stringify({ type: 'ping' }));
  wake.timer = setTimeout(() => { if (S.wsOpen && S.heard < asked) reconnect(); }, 4000);
}
function send(obj) {
  if (!S.wsOpen) { toast('Not connected to your Mac'); return false; }
  S.ws.send(JSON.stringify(obj));
  return true;
}
document.addEventListener('visibilitychange', () => {
  const v = document.visibilityState === 'visible';
  if (S.wsOpen) S.ws.send(JSON.stringify({ type: 'visible', value: v }));
  if (v) resumed();
});
// Back in the app: the socket, the state and a tapped alert. iOS doesn't always say so: after a lock it may thaw the
// page with no visibilitychange (it never counted as hidden), so a clock that stalled for seconds counts too.
function resumed() {
  if (document.hidden || !S.token || !Tap.ready) return;
  if (Date.now() - (resumed.at || 0) < 1000) return;   // one return fires several of these at once
  resumed.at = Date.now();
  wake(); refresh(); Tap.watch();
}
resumed.tick = Date.now();
setInterval(() => { const now = Date.now(); if (now - resumed.tick > 5000) resumed(); resumed.tick = now; }, 1000);
addEventListener('pageshow', (e) => { if (e.persisted) resumed(); });

function upsertConv(c) {
  if (c.main) S.mainId = c.id;
  const i = S.convs.findIndex((x) => x.id === c.id);
  // an event sent before a read reached the Mac must not bring the dot back
  if (i >= 0) S.convs[i] = { ...S.convs[i], ...c, ...(S.convs[i].read > c.read ? { read: S.convs[i].read } : {}) };
  else S.convs.unshift(c);
  S.convs.sort((a, b) => b.updated - a.updated);
}
const curConv = () => S.convs.find((c) => c.id === S.current);
// A scheduled task works in a hidden chat of its own; its message comes to the main chat (the 'message' event)
const isTaskChat = (id) => !!S.convs.find((c) => c.id === id)?.schedule;
// The chat an approval shows in: a task's hidden chat asks in the main chat
const approvalChat = (a) => isTaskChat(a.conv) && S.mainId ? S.mainId : a.conv;
// The running turn's reply, placed as on the Mac: a message queued while it streams waits below it (the next turn
// gets its own reply). [its index or -1, where it goes]
function turnReply(m) {
  let q = m.findIndex((x) => x.role === 'user' && x.queued);
  if (q < 0) q = m.length;
  return [q && m[q - 1].role === 'assistant' ? q - 1 : -1, q];
}
function lastAssistant() {
  const m = S.conv.messages, [i, q] = turnReply(m);
  if (i >= 0) return m[i];
  m.splice(q, 0, { role: 'assistant', text: '', tools: [], notes: [] });
  return m[q];
}

// ---------- auto update ----------
// The Mac sends the version of the web files on connect ("hello") and when they change ("update").
// The app reloads at a safe moment: at once if idle, else when you leave the app or finish.
const Update = {
  version: document.querySelector('meta[name="milo-version"]')?.content || null, pending: false, timer: 0,
  seen(version) {
    if (!this.version) { this.version = version; return; }
    if (version === this.version || this.pending) return;
    this.pending = true;
    this.tryNow();
    this.timer = setInterval(() => this.tryNow(), 2000);
  },
  busy() {
    return ptt.active || Voice.on || BV.isOpen() || document.activeElement === input || !$('#fileView').hidden || !$('#mediaView').hidden || !$('#postView').hidden
      || [...document.querySelectorAll('.sheet')].some((el) => !el.hidden)
      || (S.tab === 'chat' && !!curConv()?.running);   // not under a reply you are watching
  },
  typing() {   // a sheet with a field you changed: a reload would lose it, also while you are away
    return $$('.sheet:not([hidden]) :is(input, textarea)').some((f) => f.type === 'checkbox' || f.type === 'radio'
      ? f.checked !== f.defaultChecked : f.type !== 'file' && f.value !== f.defaultValue);
  },
  tryNow(force) {   // never while something plays: a reload would cut it off, even with the screen off
    if (!this.pending || mediaPlaying() || this.typing() || (!force && document.visibilityState === 'visible' && this.busy())) return;
    clearInterval(this.timer);
    if (document.visibilityState === 'visible') toast('Updating Milo');
    keepView();
    navigator.serviceWorker?.getRegistration().then((r) => r?.update()).catch(() => {})
      .finally(() => setTimeout(() => location.reload(), 300));
  },
};
// The reload opens where you were: what you typed, the tab, the place in the chat and the Library folder.
function keepView() {
  const sc = $('#chatScroll');
  try {
    sessionStorage.setItem('draft', input.value);
    sessionStorage.setItem('view', JSON.stringify({ tab: S.tab, y: Follow.on ? null : sc.scrollTop, lib: [S.libView, S.libDir || ''] }));
  } catch {}
}
function restoreView() {
  let v = null;
  try { v = JSON.parse(sessionStorage.getItem('view')); sessionStorage.removeItem('view'); } catch {}
  if (!v) return;
  if (v.y != null) { Follow.on = false; $('#chatScroll').scrollTop = v.y; }
  if (v.tab && v.tab !== 'chat' && $(`#view-${v.tab}`)) {
    switchTab(v.tab);
    if (v.tab === 'library') { setLibView(v.lib[0]); S.libDir = v.lib[1]; }   // loadLibrary draws it when the files come
  }
}
document.addEventListener('visibilitychange', () => {
  if (document.visibilityState === 'hidden') Update.tryNow(true);
});

function handle(ev, replay) {
  if (!replay && LIVE.has(ev.t)) During.get(ev.id)?.push(ev);
  const mine = S.conv && ev.id === S.current;
  // a chat's events reach only the open chat: a kept copy of another chat that missed one loads again when opened
  if (!mine && ev.id && ['user', 'message', 'note', 'chunk', 'tool', 'done'].includes(ev.t) && Chats.has(ev.id)) Chats.get(ev.id).at = 0;
  switch (ev.t) {
    case 'hello':
    case 'update':
      Update.seen(ev.version);
      break;
    case 'conv': {
      const was = curConv()?.running, used = curConv()?.used;
      upsertConv(ev.conv);
      if (ev.conv.id === S.current && S.tab === 'chat' && document.visibilityState === 'visible') Seen.mark(ev.conv.id);
      renderDrawer(); setStatus();
      if (ev.conv.id === S.current) { renderComposer(); if (was !== ev.conv.running || used !== ev.conv.used) renderMessages(); }
      break;
    }
    case 'bound':   // the new chat of a first message has its id
      Unsent.bound(ev.ref, ev.id);
      if (ev.ref !== S.pendingRef) break;
      S.pendingRef = null;
      // the Mac takes seconds to make it: if you went to another chat meanwhile, it stays in the menu
      if (S.nav === S.pendingNav && !S.current) openConvLocal(ev.id);
      else if (sendPrompt.voiceRef) { S.myVoiceConvs.add(ev.id); sendPrompt.voiceRef = null; }
      break;
    case 'user':
      Unsent.heard(ev.text);
      if (mine && !(replay && S.conv.messages.some((m) => m.role === 'user' && m.ts === ev.ts))) {
        // a queued message waits below the reply that runs; one shown when you sent it (a new chat) is now on the Mac
        const msg = { role: 'user', text: ev.text, voice: ev.voice, queued: ev.queued, scheduled: ev.scheduled, task: ev.task, ts: ev.ts };
        const i = S.conv.messages.findIndex((m) => m.local && m.text === ev.text);
        if (i >= 0) S.conv.messages[i] = msg; else S.conv.messages.push(msg);
        S.thinking = true; renderMessages(true, true);
      }
      break;
    case 'note': {   // added after the reply
      const m = mine && [...S.conv.messages].reverse().find((x) => x.role === 'assistant');
      if (m && !(replay && m.notes?.some((n) => JSON.stringify(n) === JSON.stringify(ev.note)))) { (m.notes ||= []).push(ev.note); renderMessages(false, true); }
      break;
    }
    case 'message': {   // Milo's own message, from a scheduled task that ran out of sight
      if (mine && !S.conv.messages.some((x) => x.role === 'assistant' && x.ts === ev.message.ts)) {
        S.conv.messages.push(ev.message); renderMessages(false, true);
      }
      break;
    }
    case 'thinking':
      if (mine && !S.thinking) { S.thinking = true; renderMessages(false, true); setStatus(); }
      break;
    case 'chunk':
      if (mine) {
        const m = lastAssistant(); m.shown ??= m.text.length;
        // at: where the chunk starts in the Mac's copy, so one that a fetched copy already has is not added twice
        if (ev.at == null || ev.at >= m.text.length) m.text += ev.text;
        else if (ev.at + ev.text.length > m.text.length) m.text = m.text.slice(0, ev.at) + ev.text;
        Reveal.start(); setStatus();
      }
      if (!replay) Voice.onChunk(ev);
      break;
    case 'tool':
      if (mine) {
        const msg = lastAssistant();
        if (ev.replaces) msg.tools = msg.tools.filter((t) => t.id !== ev.replaces);   // a weather card moved to its step
        const i = msg.tools.findIndex((t) => t.id === ev.tool.id);
        if (i >= 0) msg.tools[i] = ev.tool; else msg.tools.push(ev.tool);
        setStatus();
        scheduleRender();
      }
      break;
    case 'reaction': {   // Milo tapped an emoji on one of your messages
      const m = mine && S.conv.messages.find((x) => x.role === 'user' && x.ts === ev.ts);
      if (m && m.reaction !== ev.emoji) {
        m.reaction = ev.emoji;
        if (!replay && reactFx()) { m.landing = true; landReaction(m); }   // only live: a loaded chat's reactions just show
        renderMessages(false, true);
      }
      break;
    }
    case 'title':
      upsertConv({ id: ev.id, title: ev.title }); renderDrawer(); setTitle();
      break;
    case 'read': {   // read on some device (this one too): the dot goes everywhere
      const c = S.convs.find((x) => x.id === ev.id);
      if (c && !(c.read >= ev.read)) { c.read = ev.read; renderDrawer(); }
      break;
    }
    case 'done': {
      const had = replay && mine ? S.conv.messages.findIndex((x) => x.role === 'assistant' && x.ts === ev.message.ts) : -1;
      if (mine && had >= 0) { S.conv.messages[had] = ev.message; renderMessages(false, true); }   // the copy has that reply
      else if (mine) {
        const m = S.conv.messages, [i, q] = turnReply(m);
        if (m[i]?.shown < ev.message.text.length) ev.message.shown = m[i].shown;   // finish the reveal
        if (i >= 0) m[i] = ev.message; else m.splice(q, 0, ev.message);
        // the first queued message runs next; none left waiting (Stop drops them): all of them are just sent
        if (ev.queued) delete m.find((x) => x.queued)?.queued; else m.forEach((x) => delete x.queued);
        S.thinking = false; renderMessages(false, true); Reveal.start();
      }
      if (replay) break;
      const fromHere = S.myVoiceConvs.has(ev.id);
      if (Voice.onDone(ev)) break;
      if (!ev.error && ev.stop !== 'cancelled' && document.visibilityState === 'visible' &&
          ((S.speakPolicy === 'voice' && ev.voice && fromHere) || (S.speakPolicy === 'always' && mine))) {
        speak(ev.message.text);
      }
      S.myVoiceConvs.delete(ev.id);
      break;
    }
    case 'approval':
      S.approvals.set(ev.approval.id, ev.approval);
      renderApprovals(); setStatus(); Voice.onApproval(ev.approval);
      if (navigator.vibrate) navigator.vibrate(60);
      break;
    case 'approval_done':
      S.approvals.delete(ev.id); renderApprovals(); setStatus();
      break;
    case 'goals':
      if (S.tab === 'goals') loadGoals();
      break;
    case 'feed':
      F.busy = ev.busy;
      if (S.tab === 'feed') { if (ev.busy) renderFeed(); else loadFeed(); } else if (!ev.busy) loadFeed();
      break;
    case 'ideas':
      S.ideasBusy = ev.busy;
      if (S.tab === 'ideas') loadIdeas(); else if (!ev.busy) fetchIdeas();
      break;
    case 'schedules':
      if (S.tab === 'upcoming') loadUpcoming().then(() => { if (!$('#taskSheet').hidden) showTask(S.taskId); });
      break;
    case 'browser':
      S.browser = { ...S.browser, ...ev.state }; renderBrowserBits(); BV.state(ev.state);
      break;
    case 'toast':
      if (ev.stop) UndoStop.hide();   // the Stop it offered Undo for went through
      toast(ev.text, 6000);
      break;
    case 'stopping':   // a Stop that would end helper agents waits a few seconds for Undo
      UndoStop.show(ev);
      break;
    case 'stop_undone':
      if (UndoStop.id === ev.id) { UndoStop.hide(); toast('Milo keeps going'); }
      break;
    case 'google':
      loadGoogle();
      break;
    case 'deleted':
      S.convs = S.convs.filter((c) => c.id !== ev.id); Chats.delete(ev.id); renderDrawer();
      if (ev.id === S.current) openMain(S.tab !== 'chat');   // from another tab's menu: stay on that tab
      Drafts.map.delete(ev.id);
      break;
    case 'error':
      toast(ev.message || 'Something went wrong');
      break;
  }
}

let renderQueued = false;
function scheduleRender() {
  if (renderQueued) return;
  renderQueued = true;
  requestAnimationFrame(() => { renderQueued = false; renderMessages(false, true); });
}
// A reply shows at a steady pace rather than in the bursts it arrives in: it catches up within about
// a third of a second, so it never lags far behind.
const calm = matchMedia('(prefers-reduced-motion: reduce)');
const Reveal = {
  raf: 0, at: 0, drawn: 0,
  start() { if (!this.raf) { this.at = performance.now(); this.raf = requestAnimationFrame((t) => this.tick(t)); } },
  tick(now) {
    this.raf = 0;
    // the reply being revealed is not always the last message (a queued one waits below it); one ending as the next starts goes on too
    const dt = Math.min(64, now - this.at);
    let more = false, ended = false;
    for (const m of S.conv?.messages || []) {
      if (m.shown === undefined) continue;
      if (!(m.shown < m.text.length)) { delete m.shown; continue; }
      const left = m.text.length - m.shown;
      m.shown = calm.matches ? m.text.length : Math.min(m.text.length, m.shown + Math.max(70, left / 0.3) * dt / 1000);
      more = true; ended ||= m.shown >= m.text.length;
    }
    this.at = now;
    if (!more) { renderMessages(false, true); return; }
    if (now - this.drawn > 30 || ended) { this.drawn = now; renderMessages(false, true); }
    this.raf = requestAnimationFrame((t) => this.tick(t));
  },
};
// Follow the end of the chat with a short glide while it grows, rather than jumping a line at a time.
// Not while a finger is down: on iOS, setting scrollTop undoes a drag. The streaming message is rebuilt under
// the finger, so its touchend may never arrive; a touch counts for 2 s at most.
const Finger = { at: 0 };
addEventListener('touchstart', () => { Finger.at = Date.now(); }, { capture: true, passive: true });
addEventListener('touchmove', () => { Finger.at = Date.now(); }, { capture: true, passive: true });
for (const t of ['touchend', 'touchcancel']) addEventListener(t, (e) => { if (!e.touches.length) Finger.at = 0; }, { capture: true, passive: true });
const Glide = {
  raf: 0, y: 0,
  start() {
    if (this.raf) return;
    const sc = $('#chatScroll');
    this.y = sc.scrollTop;
    const step = () => {
      const end = sc.scrollHeight - sc.clientHeight, d = end - sc.scrollTop;
      // stop when following ends, at the end, or when something else moved the chat (a scroll or a jump)
      if (!Follow.on || d < 1 || Math.abs(sc.scrollTop - this.y) > 2) { this.raf = 0; return; }
      if (Date.now() - Finger.at < 2000) { this.raf = requestAnimationFrame(step); return; }
      sc.scrollTop = d < 2 ? end : sc.scrollTop + Math.ceil(d * 0.22);
      this.y = sc.scrollTop;
      this.raf = requestAnimationFrame(step);
    };
    this.raf = requestAnimationFrame(step);
  },
};

// ---------- rendering: chat ----------
// The 3D dog in the header moves with what Milo is doing (mascot.js); face.svg shows until it loads.
const Ava = { dog: null, state: 'idle' };
import('./mascot.js').then((m) => {
  Ava.dog = m.avatar($('#avatarDog')); Ava.dog.set(Ava.state);
  $('.avatar-face').classList.add('live');
  lookAround();
}).catch(() => {});
// Milo's reaction comes out of the dog (reaction.js): a cloud on his circle, then the emoji lands as the chip, which
// waits hidden (m.landing). Only while the header shows him, one at a time, and never with reduced motion.
const Rx = { on: false };
function reactFx() {
  return !!Ava.dog && !Rx.on && !calm.matches && !document.hidden && S.tab === 'chat' && !$('.bar').classList.contains('side')
    && !document.documentElement.classList.contains('menu') && !$('.sheet.open, #voice:not([hidden]), #mediaView:not([hidden]), #pair:not([hidden])');
}
function landReaction(m) {
  Rx.on = true;
  const done = () => {
    Rx.on = false;
    if (!m.landing) return;
    delete m.landing;
    if (S.conv?.messages.includes(m)) renderMessages(false);   // the chip shows with its pop
  };
  const chip = () => {   // the chip, if it's still in view to land on
    const c = $(`#messages .reaction[data-land="${m.ts}"]`), sc = $('#chatScroll');
    if (!c || S.tab !== 'chat') return null;
    const r = c.getBoundingClientRect(), v = sc.getBoundingClientRect();
    return r.height && r.bottom > v.top && r.top < v.bottom ? c : null;
  };
  import('./reaction.js').then((x) => x.playReaction({ face: $('.avatar-face'), dog: Ava.dog, emoji: m.reaction, chip, done,
    side: Ava.state === 'thinking' ? -1 : 1 }))   // the 3D thinking bubble sits on the right
    .catch(done);
}
// While Milo is idle the dog looks at the user, from the phone's tilt or at a finger near it (mascot.js). Only while the
// header shows: no keyboard, menu, sheet or full-screen view, and the app on screen. Off, it drops the sensors.
function lookAround() {
  const root = document.documentElement;
  Ava.dog?.look(!document.hidden && !root.classList.contains('kb') && !root.classList.contains('menu') && !$('.bar').classList.contains('side')
    && !$('.sheet.open, #voice:not([hidden]), #mediaView:not([hidden]), #pair:not([hidden])'));
}
new MutationObserver(lookAround).observe(document.documentElement, { attributes: true, attributeFilter: ['class'] });
for (const el of [$('.bar'), ...$$('.sheet, #voice, #mediaView, #pair')]) new MutationObserver(lookAround).observe(el, { attributes: true, attributeFilter: ['class', 'hidden'] });
document.addEventListener('visibilitychange', lookAround);
// a missed change (back from the background, a bfcache restore) must not leave the dog still
for (const ev of ['pageshow', 'focus']) addEventListener(ev, lookAround);
// iOS gives the tilt only after the user allows it, and asks only from a tap. A Home Screen app forgets the answer
// at every launch (and reload), so the first tap of each launch asks; iOS shows no prompt if it kept the answer.
// A "Don't Allow" is not kept either: keeping it (store 'motion') left the tilt off for good after one Cancel.
// Without the tilt the dog still follows a finger (mascot.js).
if (typeof window.DeviceOrientationEvent?.requestPermission === 'function') {
  store.del('motion');   // an old kept "no"
  let asking = false;
  const ask = () => {   // the end of a scroll is no tap to iOS: then it refuses, and the next tap asks
    if (asking) return;
    asking = true;
    DeviceOrientationEvent.requestPermission().then(() => {
      removeEventListener('touchend', ask, true); removeEventListener('click', ask, true);
    }).catch(() => { asking = false; });
  };
  addEventListener('touchend', ask, true); addEventListener('click', ask, true);
}

// What the current chat is doing: [state for the dog, one word for the pill ('' shows the name)].
function activity() {
  const c = curConv();
  if (!S.wsOpen) return ['offline', 'Offline'];
  if (!c?.running) return ['idle', ''];
  if ([...S.approvals.values()].some((a) => approvalChat(a) === c.id)) return ['waiting', 'Needs you'];
  const m = S.conv?.messages || [], last = m[turnReply(m)[0]];   // S.conv is the current chat; its running reply
  const tool = last?.tools?.findLast((t) => t.status === 'pending' || t.status === 'in_progress');
  if (tool) return tool.browser ? ['browsing', 'Browsing'] : ['working', 'Working'];   // the dog's lid shows a globe
  return last?.text ? ['writing', 'Writing'] : ['thinking', 'Thinking'];
}
// The face and the pill hold each state at least 1.5 s, and quicker steps are skipped: a calm header beats an
// exact one.
const Shown = { key: '', at: 0, timer: 0 };
function setStatus() {
  clearTimeout(Shown.timer);
  const [state, label] = activity(), key = state + label, wait = Shown.at + 1500 - Date.now();
  if (key !== Shown.key && wait > 0) { Shown.timer = setTimeout(setStatus, wait); return; }
  if (key !== Shown.key) { Shown.key = key; Shown.at = Date.now(); }
  $('#status').className = 'status ' + (state === 'offline' ? 'offline' : state === 'idle' ? 'online' : 'busy');
  $('#title').textContent = label || S.settings.assistant_name || 'Milo';
  $('#barDot').className = $('#status').className;   // the side-chat header shows the same one word
  $('#barStatus').textContent = label;
  Ava.state = state; Ava.dog?.set(state);
}
function setTitle() {
  setStatus();
  const t = S.onMain ? '' : curConv()?.title;
  S.placeholder = t ? `Message in ${t}` : 'Message';   // fitEnd keeps it to one line
  const side = S.tab === 'chat' && !S.onMain;   // a side chat has its name in the header, like Muse
  $('.bar').classList.toggle('side', side);
  $('.bar').classList.toggle('over', S.tab === 'chat');   // the chat runs under the header
  $('#barTitle').hidden = !side;
  $('#barTitleText').textContent = t || 'New chat';
  renderGhost();
}

// The chat runs under the header, so it needs the header's height (side chats and the keyboard change it).
new ResizeObserver(() => document.documentElement.style.setProperty('--bar-h', `${$('.bar').offsetHeight}px`)).observe($('.bar'));

function toolsHtml(tools, running) {
  if (!tools?.length) return '';
  const active = running && tools.some((t) => t.status === 'pending' || t.status === 'in_progress');
  const failed = tools.filter((t) => t.status === 'failed').length;
  const label = active ? (tools[tools.length - 1].title || 'Working') : `${tools.length} step${tools.length > 1 ? 's' : ''}${failed ? ` · ${failed} failed` : ''}`;
  return `<details class="steps"><summary>${active ? '<span class="spin"></span>' : `<span class="check">${ICON.check}</span>`}<span>${esc(label)}</span></summary><ol>${tools.map((t) =>
    `<li class="${esc(t.status)}"><span class="st"></span><span>${esc(t.title)}${t.detail ? `<span class="d">${esc(t.detail)}</span>` : ''}</span></li>`).join('')}</ol></details>${
    tools.some((t) => t.browser) ? `<button class="watch" data-act="watch">${ICON.globe}${active ? 'Watch Milo browse' : 'Open the browser'}</button>` : ''}`;
}
function notesHtml(notes) {
  notes = notes?.filter((n) => n.kind !== 'compact');   // compaction is silent: old chats' compact notes don't show
  if (!notes?.length) return '';
  return `<div class="notes">${notes.map((n) => {
    if (n.kind === 'memory') return `<span class="note">${ICON.brain}Remembered: ${esc(n.text)}</span>`;
    if (n.kind === 'schedule') return `<span class="note">${ICON.clock}${esc(n.text)} · ${esc(n.cron ? cronLabel(n.cron) : fmtWhen(n.next))}</span>`;
    if (n.kind === 'stopped') return `<span class="note">Stopped</span>`;
    if (n.kind === 'goal') return `<span class="note">${ICON.check}${esc(n.text)}</span>`;
    if (n.kind === 'saved') return `<span class="note">${ICON.file}Saved in ${esc(n.text)}</span>`;
    return `<span class="note error">${esc(n.text)}</span>`;
  }).join('')}</div>`;
}
const APPROVAL_BUTTONS = [
  ['allow_once', 'Allow once', 'allow'], ['allow_site', 'Allow on this site', ''],
  ['allow_always', 'Always allow', ''], ['reject_once', 'Deny', 'deny'], ['reject_always', 'Always deny', 'deny'],
];
function approvalHtml(a, compact) {
  const why = a.title && a.command && a.title !== a.command ? a.title : '';
  return `<div class="approval" data-aid="${a.id}">
    <div class="ah"><span class="badge">${ICON.shield}</span><span>${esc(compact ? 'May I do this?' : (why || 'May I do this?'))}</span></div>
    ${compact && why ? `<p class="why">${esc(why)}</p>` : ''}
    ${a.command ? `<details ${compact ? '' : 'open'}><summary>Task details</summary><pre>${esc(a.command)}</pre></details>` : ''}
    <div class="ab">${APPROVAL_BUTTONS.filter(([o]) => a.options.includes(o)).map(([o, label, cls]) =>
      `<button class="${cls}" data-opt="${o}">${label}</button>`).join('')}</div></div>`;
}

// The chat follows a reply as it streams only until you scroll up, and again once you are back at the end. Each
// follow sets scrollTop, which on iOS undoes your drag, so a chat that followed within 120 px could not be scrolled
// up while Milo wrote. (No touch events here: the streaming message under your finger is rebuilt, so touchend is lost.)
const Follow = {
  on: true, top: 0, h: 0,
  // A list that got shorter pulls the chat down to its new end, and iOS reports that as a scroll up a frame later, when
  // the picture that left the gap may be back: the chat stopped following and the end of the reply stayed hidden (#71).
  // Where the chat moved by itself is where it is now.
  keep() {
    const sc = $('#chatScroll');
    if (this.on && sc.scrollTop < this.top && sc.scrollHeight - sc.scrollTop - sc.clientHeight < 1) this.top = sc.scrollTop;
  },
};
$('#chatScroll').addEventListener('scroll', (e) => {
  const sc = e.target, y = sc.scrollTop, gap = sc.scrollHeight - y - sc.clientHeight;
  if (y < Follow.top - 1 && gap > 2) Follow.on = false;   // moved up (a reply that got shorter only moves the end)
  else if (gap < 40) Follow.on = true;
  Follow.top = y;
}, { passive: true });
// A picture, diagram or formula takes its height only once it loads or draws, after the last follow: the end of the
// reply was left under the message box. Whenever the list grows after a render and the chat follows, go to the end
// again (#67).
new ResizeObserver(([e]) => {
  const h = e.target.offsetHeight, grew = h > Follow.h;   // offsetHeight: as renderMessages measures it
  Follow.h = h;
  Follow.keep();
  if (!grew || !h || !Follow.on || !S.conv?.messages?.length) return;
  const sc = $('#chatScroll');
  if (sc.scrollHeight - sc.scrollTop - sc.clientHeight < 1) return;
  if (calm.matches) sc.scrollTop = sc.scrollHeight; else Glide.start();
}).observe($('#messages'));

// Scrolled up: a button takes you back to the newest message (like Muse).
$('#chatScroll').addEventListener('scroll', (e) => {
  const sc = e.target;
  $('#toEnd').hidden = sc.scrollHeight - sc.scrollTop - sc.clientHeight < 400;
}, { passive: true });
$('#toEnd').onclick = () => {
  const sc = $('#chatScroll');
  Follow.on = true;
  sc.scrollTo({ top: sc.scrollHeight, behavior: calm.matches ? 'auto' : 'smooth' });
};
// Like Muse: the time shows above the first message and wherever an hour or more passed.
const stamp = (ts) => { const d = new Date(ts * 1000);
  return `${d.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })} at ${d.toLocaleTimeString('en-US', { hour: 'numeric', minute: '2-digit' })}`; };
function renderMessages(stick, live) {   // live: an event added this, so new items animate in
  const box = $('#messages'), scroller = $('#chatScroll');
  if (stick) Follow.on = true;
  const atBottom = stick || Follow.on;
  const msgs = S.conv?.messages || [];
  $('#home').hidden = msgs.length > 0;
  const running = !!curConv()?.running || (!S.current && !!S.pendingRef);   // pendingRef: the Mac is making this chat
  const parts = [];
  const lastReply = msgs.findLastIndex((x) => x.role === 'assistant');   // read aloud and copy: on the newest reply only
  const [reply, slot] = running ? turnReply(msgs) : [-1, -1];   // the reply that runs, or where it will show
  const dots = '<div class="msg assistant"><div class="thinking"><span></span><span></span><span></span></div></div>';
  msgs.forEach((m, i) => {
    if (i === slot && reply < 0 && i) parts.push(dots);   // above the messages queued meanwhile
    if (m.ts && !m.scheduled && !(msgs[i - 1]?.ts > m.ts - 3600)) parts.push(`<div class="msg-time">${esc(stamp(m.ts))}</div>`);
    if (m.role === 'user' && m.scheduled) {   // a scheduled task's run: the app sent it, not the user
      parts.push(`<div class="msg event">${ICON.clock}${esc(m.task || curConv()?.title || 'Scheduled task')} ran${m.ts ? ' · ' + esc(fmtWhen(m.ts)) : ''}${m.queued ? ' · Queued' : ''}</div>`);
    } else if (m.role === 'user') {
      const lines = m.text.split('\n'), files = lines.filter((l) => ATTACHED.test(l)).map((l) => l.match(ATTACHED)[1].split('/').pop());
      const said = files.length ? lines.filter((l) => !ATTACHED.test(l)).join('\n').trim() : m.text;
      parts.push(`<div class="msg user${m.reaction ? ' reacted' : ''}"><div class="bubble">${esc(said)}${files.map((f) => `<div class="file-chip">${ICON.file || ''}${esc(f)}</div>`).join('')}${m.reaction ? `<span class="reaction${m.landing ? ' later' : ''}" role="img" aria-label="Milo reacted ${esc(m.reaction)}"${m.landing ? ` data-land="${m.ts}"` : ''}>${esc(m.reaction)}</span>` : ''}</div>${m.voice || m.queued ? `<div class="meta">${m.voice ? ICON.mic + 'Spoken' : ''}${m.queued ? ' · Queued' : ''}</div>` : ''}</div>`);
    } else {
      const revealing = m.shown < m.text.length;
      const streaming = (running && i === reply) || revealing;
      const body = md(revealing ? m.text.slice(0, Math.floor(m.shown)) : m.text, streaming);
      parts.push(`<div class="msg assistant" data-i="${i}">${toolsHtml(m.tools, streaming)}${weatherCards(m.tools)}
        ${body ? `<div class="bubble md${streaming ? ' cursor' : ''}">${body}</div>` : streaming ? '<div class="thinking"><span></span><span></span><span></span></div>' : ''}
        ${m.error ? `<div class="error-line">Milo hit an error: ${esc(m.error)}</div>` : ''}
        ${notesHtml(m.notes)}
        ${!streaming && m.text && i === lastReply ? `<div class="msg-actions"><button data-act="speak" aria-label="Read aloud">${ICON.speaker}</button><button data-act="copy" aria-label="Copy">${ICON.copy}</button></div>` : ''}
      </div>`);
    }
  });
  if (running && reply < 0 && slot === msgs.length && msgs.length) parts.push(dots);
  for (const a of S.approvals.values()) if (approvalChat(a) === S.current) parts.push(approvalHtml(a, false));
  patchList(box, parts, live);
  Follow.h = box.offsetHeight;   // this render's own growth is followed below; later growth by the observer
  Follow.keep();
  if (!msgs.length) scroller.scrollTop = 0;
  else if (atBottom && live && !calm.matches) Glide.start();
  else if (atBottom) scroller.scrollTop = scroller.scrollHeight;
}
// Replace only the items that changed. While Milo streams, only the last message is rebuilt,
// so the chat does not flicker and step lists you opened stay open.
function patchList(box, parts, enter) {
  const tpl = document.createElement('template');
  parts.forEach((html, i) => {
    const old = box.children[i];
    if (old && old._html === html) return;
    tpl.innerHTML = html.trim();
    const el = tpl.content.firstElementChild;
    el._html = html;
    if (!old) { if (enter) el.classList.add('enter'); box.appendChild(el); return; }
    if (old.querySelector('details.steps[open]')) el.querySelector('details.steps')?.setAttribute('open', '');
    const sx = [...old.querySelectorAll('.table-wrap')].map((w) => w.scrollLeft);
    old.replaceWith(el);
    if (sx.some(Boolean)) el.querySelectorAll('.table-wrap').forEach((w, k) => { if (sx[k]) w.scrollLeft = sx[k]; });   // a wide table stays where you scrolled it
  });
  while (box.children.length > parts.length) box.lastElementChild.remove();
}

function renderApprovals() {
  const others = [...S.approvals.values()].filter((a) => approvalChat(a) !== S.current || S.tab !== 'chat');
  const b = $('#approvalBanner');
  b.hidden = !others.length;
  if (others.length) {
    const a = others[0];
    const name = S.convs.find((c) => c.id === a.conv)?.title || 'a task';
    b.innerHTML = `${ICON.shield}<span><b>Needs your OK</b> · ${esc(name)}</span>`;
    b.onclick = () => { switchTab('chat'); openConv(approvalChat(a)); };
  }
  const count = S.approvals.size;
  for (const chatTab of $$('[data-tab="chat"]')) {
    chatTab.querySelector('.count')?.remove();
    if (count) chatTab.insertAdjacentHTML('beforeend', `<span class="count">${count}</span>`);
  }
  renderMenuDot();
  if (S.tab === 'chat') renderMessages(false, true);
}

$('#messages').addEventListener('click', async (e) => {
  const opt = e.target.closest('[data-opt]');
  if (opt) return answerApproval(opt.closest('[data-aid]').dataset.aid, opt.dataset.opt);
  const act = e.target.closest('[data-act]');
  if (!act) return;
  if (act.dataset.act === 'watch') return BV.open();
  const m = S.conv.messages[+act.closest('[data-i]').dataset.i];
  if (act.dataset.act === 'speak') { unlockAudio(); speak(m.text); }
  if (act.dataset.act === 'copy') { await navigator.clipboard?.writeText(m.text).catch(() => {}); toast('Copied'); }
});
function answerApproval(id, option) {
  if (Voice.on || S.speakPolicy === 'always') unlockAudio();   // only for a reply read aloud: it stops music in other apps
  if (!send({ type: 'approve', approval: id, option })) return;
  S.approvals.delete(id); renderApprovals(); Voice.onApprovalAnswered();
}

// ---------- composer ----------
const input = $('#input');
// ---------- attachments (+) ----------
// Files go to the Mac (Library/Uploads); the message tells Milo where they are.
S.attachments = [];
const ATTACHED = /^\[Attached file: (.+)\]$/;
function renderAttachments() {
  const box = $('#attachments');
  box.hidden = !S.attachments.length;
  box.innerHTML = S.attachments.map((a, i) => `<span class="att ${a.abs ? '' : 'loading'}">${ICON.file || ''}<span>${esc(a.abs ? a.name : `Uploading ${a.name}`)}</span><button data-unattach="${i}" aria-label="Remove">${ICON.x}</button></span>`).join('');
  renderComposer();
}
$('#attachBtn').onclick = () => $('#fileInput').click();
$('#fileInput').addEventListener('change', (e) => {
  const files = [...e.target.files];
  e.target.value = '';
  attachFiles(files);
});
async function attachFiles(files) {   // + , a paste or a drop
  await Promise.all(files.map(async (f) => {
    const a = { name: f.name };
    S.attachments.push(a); renderAttachments();
    try {
      const fd = new FormData(); fd.append('file', f, f.name);
      Object.assign(a, await api('/api/upload', { method: 'POST', body: fd }));
    } catch (err) {   // the draft may belong to another chat by now
      for (const list of [S.attachments, ...[...Drafts.map.values()].map((d) => d.files)]) if (list.includes(a)) list.splice(list.indexOf(a), 1);
      toast(`Could not attach ${f.name}: ${err.message}`);
    }
    renderAttachments();
  }));
}
// A pasted picture or file (Cmd/Ctrl+V, or Paste on iOS) attaches like +; pasted text stays plain text.
const PASTE_EXT = { 'image/png': 'png', 'image/jpeg': 'jpg', 'image/gif': 'gif', 'image/webp': 'webp', 'image/heic': 'heic', 'application/pdf': 'pdf' };
function clipFiles(dt) {
  let files = [...(dt?.files || [])];
  if (!files.length) files = [...(dt?.items || [])].filter((i) => i.kind === 'file').map((i) => i.getAsFile()).filter(Boolean);
  // a screenshot comes as "image.png" each time: name it by the time, so a second one is told apart
  return files.map((f, i) => !f.name || /^image\.\w+$/.test(f.name)
    ? new File([f], `Pasted ${new Date().toISOString().slice(0, 19).replace('T', ' ').replace(/:/g, '.')}${i ? `-${i}` : ''}.${PASTE_EXT[f.type] || f.name?.split('.').pop() || 'bin'}`, { type: f.type })
    : f);
}
input.addEventListener('paste', (e) => {
  const files = clipFiles(e.clipboardData);
  if (!files.length) return;
  e.preventDefault();   // not the file's name or path as text
  attachFiles(files);
});
// Drop files on the chat (desktop)
const dropsFiles = (e) => [...(e.dataTransfer?.types || [])].includes('Files');
$('#view-chat').addEventListener('dragover', (e) => { if (dropsFiles(e)) { e.preventDefault(); e.dataTransfer.dropEffect = 'copy'; } });
$('#view-chat').addEventListener('drop', (e) => {
  if (!dropsFiles(e)) return;
  e.preventDefault();
  const files = clipFiles(e.dataTransfer);
  if (files.length) { attachFiles(files); input.focus({ preventScroll: true }); }
});
$('#attachments').addEventListener('click', (e) => {
  const b = e.target.closest('[data-unattach]');
  if (b) { S.attachments.splice(+b.dataset.unattach, 1); renderAttachments(); }
});

function renderComposer() {
  const has = input.value.trim().length > 0 || S.attachments.some((a) => a.abs);
  const running = !!curConv()?.running, recording = S.dictating && !S.transcribing;
  const sendable = has || S.transcribing;   // after recording, send shows while the last words come in
  $('#sendBtn').hidden = !sendable || recording;
  // the spinner shows from Stop until the last words are in (tapped, send waits for them), also when the live pass already
  // put words in the box; it goes once you type. Not tied to an empty box: live words are almost always there by Stop.
  // A real boolean: classList.toggle(name, undefined) flips the class, so a spinner came and went with each key.
  const spin = !!(S.transcribing && !S.typedWhileBusy);
  $('#sendBtn').classList.toggle('busy', spin); $('#sendBtn').ariaLabel = spin ? 'Processing' : 'Send';
  $('#micBtn').hidden = sendable && !recording;
  $('#stopBtn').hidden = !running || has || S.dictating;
  renderGhost();
  setStatus();
}
// Suggestion: a gray hint in the empty message box. The first space (or Tab on a keyboard) takes it as your text.
// It is Milo's <suggest> from the last reply, or one of its ideas in an empty chat.
function ghostText() {
  if (input.value || S.dictating || S.attachments.length) return '';
  const last = S.conv?.messages?.at(-1);
  if (last) return last.role === 'assistant' && last.suggest && !curConv()?.running ? fitLine(last.suggest) : '';
  const asks = (S.ideas || []).map((i) => i.ask || (i.prompt.length <= 32 ? i.prompt : '')).filter(Boolean);   // one line
  return asks.length ? fitLine(asks[(S.ghostTurn || 0) % asks.length]) : '';
}
// Whole words that fit the message box on one line. 32 characters can still wrap on a phone.
const measure = document.createElement('canvas').getContext('2d');
function lineRoom() {   // the message box's width for text, with measure set to its font
  const cs = getComputedStyle(input);
  measure.font = `${cs.fontStyle} ${cs.fontWeight} ${cs.fontSize} ${cs.fontFamily}`;
  return input.clientWidth - parseFloat(cs.paddingLeft) - parseFloat(cs.paddingRight) - 2;
}
function fitLine(text) {
  const room = lineRoom();
  if (room <= 0) return text;   // hidden: fit it when it shows
  const words = text.split(' ');
  while (words.length > 1 && measure.measureText(words.join(' ')).width > room) words.pop();
  return words.join(' ');
}
function fitEnd(text) {   // the placeholder: one line, cut with "…" (the box would grow to two lines)
  const room = lineRoom();
  if (room <= 0 || measure.measureText(text).width <= room) return text;
  let n = text.length;
  while (n > 1 && measure.measureText(text.slice(0, n).trimEnd() + '…').width > room) n--;
  return text.slice(0, n).trimEnd() + '…';
}
window.addEventListener('resize', () => renderGhost());
const fineKeys = matchMedia('(hover: hover) and (pointer: fine)');   // a desktop with a keyboard: show the Tab key
function renderGhost() {
  $('#tabHint').hidden = !(fineKeys.matches && ghostText());   // first, so the hint's room is left out of the line
  const g = ghostText();
  input.placeholder = g || fitEnd(S.placeholder || 'Message');
  input.classList.toggle('ghost', !!g);
  sizeInput(g);
}
function sizeInput(ghost = '') {
  input.style.height = 'auto';
  if (!input.value && ghost) { input.value = ghost; input.style.height = Math.min(input.scrollHeight, 140) + 'px'; input.value = ''; }
  else input.style.height = Math.min(input.scrollHeight, 140) + 'px';
}
function takeGhost(e) {
  const g = !input.value && ghostText();
  if (!g) return;
  e.preventDefault();
  input.value = g;
  input.setSelectionRange(g.length, g.length);
  input.dispatchEvent(new Event('input'));
}
input.addEventListener('input', () => {
  sizeInput();
  if (!input.value.trim()) S.dictated = false;
  renderComposer();
});
input.addEventListener('keydown', (e) => {
  if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); submitText(); }
  else if (e.key === ' ' && !e.isComposing) takeGhost(e);
  else if (e.key === 'Tab' && !e.shiftKey && !e.altKey && !e.ctrlKey && !e.metaKey && !e.isComposing) takeGhost(e);   // no hint: Tab moves on
});
input.addEventListener('beforeinput', (e) => {   // iOS keyboards may skip keydown
  if (S.transcribing && !S.typedWhileBusy) { S.typedWhileBusy = true; renderComposer(); }
  if (e.inputType === 'insertText' && e.data === ' ') takeGhost(e);
});
$('#sendBtn').onclick = submitText;
$('#stopBtn').onclick = () => { stopSpeaking(); S.current && send({ type: 'cancel', id: S.current }); };
function submitText() {
  if (S.transcribing) { S.sendAfter = true; return; }
  if (S.attachments.some((a) => !a.abs)) return toast('Still uploading');
  const files = S.attachments.map((a) => `[Attached file: ${a.abs}]`).join('\n');
  const typed = input.value.trim();
  const text = [typed || (files ? 'Here is a file.' : ''), files].filter(Boolean).join('\n\n');
  if (!text) return;
  if (sendPrompt(text, !!S.dictated)) { S.dictated = false; S.attachments = []; input.value = ''; renderAttachments(); }
}
// Prompts the Mac has not echoed yet. A socket can die unnoticed and swallow one: after the reconnect, a prompt the
// Mac does not have goes back in the message box.
const Unsent = {
  list: [],
  add(text, id, ref) { this.list.push({ text, id, ref }); },
  heard(text) { const i = this.list.findIndex((u) => u.text === text); if (i >= 0) this.list.splice(i, 1); },
  bound(ref, id) { for (const u of this.list) if (u.ref === ref) u.id = id; },
  async check() {
    const lost = [];
    for (const u of this.list.splice(0)) {
      const id = u.id === 'main' ? S.mainId : u.id;
      const c = !id ? null : id === S.current ? S.conv : await api(`/api/conversations/${id}`).catch(() => null);
      if (!c?.messages?.slice(-8).some((m) => m.role === 'user' && m.text === u.text)) lost.push(u.text);
    }
    if (!lost.length) return;
    input.value = [...lost, input.value].filter(Boolean).join('\n'); input.dispatchEvent(new Event('input'));
    toast('Not sent. Tap send again.');
  },
};
function sendPrompt(text, voice) {
  if (S.speakPolicy === 'always' || (voice && S.speakPolicy === 'voice')) unlockAudio();   // as in answerApproval
  const msg = { type: 'prompt', id: S.current || (S.onMain ? 'main' : null), text, voice };
  if (!S.current) {   // a new chat: the Mac makes it and answers "bound" with its id
    // a second message before that goes to the same new chat (same ref), not to a chat of its own
    if (!S.pendingRef || S.pendingNav !== S.nav) { S.pendingRef = Math.random().toString(36).slice(2); S.pendingNav = S.nav; }
    msg.ref = S.pendingRef;
  }
  if (!send(msg)) return false;
  Unsent.add(text.trim(), msg.id, msg.ref);
  if (voice) {
    if (S.current) S.myVoiceConvs.add(S.current); else sendPrompt.voiceRef = msg.ref;
  }
  if (!S.current) {   // shown at once (the Mac takes a moment to make the chat); a second one goes below the first
    if (S.conv?.ref !== msg.ref) S.conv = { messages: [], ref: msg.ref };
    S.conv.messages.push({ role: 'user', text: text.trim(), voice, ts: Date.now() / 1000, local: true });
    renderMessages(true, true);
  }
  return true;
}

// ---------- keyboard ----------
// iOS keeps a home-screen app at full height when the keyboard opens, which leaves a gap under the
// message box. Fit the app to the part of the screen above the keyboard instead, and move it with the
// keyboard: iOS reports the new size only once the keyboard is nearly up, so the move starts on focus,
// from the keyboard's last height, and the report corrects it.
const Kb = { h: +store.get('kbH') || 0, raf: 0, timer: 0, tap: 0 };
// iOS 27 Safari shrinks innerHeight with the keyboard too, so compare with the full page height
const fullHeight = () => Math.max(document.documentElement.clientHeight, window.innerHeight);
function moveApp(open, height, top = 0) {
  const root = document.documentElement, app = $('#app'), sc = $('#chatScroll'), was = root.classList.contains('kb');
  const to = open ? Math.round(height) : fullHeight();
  if (was === open && Math.abs(app.getBoundingClientRect().height - to) < 2 && (parseFloat(app.style.top) || 0) === top) return;
  if (!app.style.height) { app.style.height = `${app.getBoundingClientRect().height}px`; app.getBoundingClientRect(); }   // animate from px
  root.classList.add('kb-move');
  root.classList.toggle('kb', open);
  app.style.height = `${to}px`;
  app.style.top = top ? `${top}px` : '';
  // the newest message stays in view while the chat shrinks under it; scrolled up, what you read stays put. Also on a
  // later move while open: iOS's report comes mid-move, and this move's cancel stopped the first one's pin (#72)
  const pin = open && S.tab === 'chat' && document.activeElement === input && S.conv?.messages?.length && Follow.on;
  const end = performance.now() + 320;
  cancelAnimationFrame(Kb.raf);
  const step = () => {
    if (pin) sc.scrollTop = sc.scrollHeight;
    if (performance.now() < end) { Kb.raf = requestAnimationFrame(step); return; }
    root.classList.remove('kb-move');
    if (!root.classList.contains('kb')) app.style.height = '';
  };
  step();
}
// The keyboard is up only while a text field has focus: coming back to the app, iOS can report a short viewport for
// a moment with no keyboard, and the app stayed shrunk with no tab bar.
const typing = () => !!document.activeElement?.matches('input:not([type=checkbox]):not([type=radio]):not([type=range]):not([type=file]), textarea, select, [contenteditable]');
function fitViewport() {
  const vv = window.visualViewport;
  if (!vv) return;
  const full = fullHeight(), open = full - vv.height > 120 && typing();
  if (open && Math.abs(full - vv.height - Kb.h) > 1) { Kb.h = Math.round(full - vv.height); store.set('kbH', String(Kb.h)); }
  moveApp(open, vv.height, open ? vv.offsetTop : 0);
}
window.visualViewport?.addEventListener('resize', fitViewport);
window.visualViewport?.addEventListener('scroll', fitViewport);
// back in the app, the viewport may have changed while it was away (the keyboard went down with no resize)
document.addEventListener('visibilitychange', () => { if (!document.hidden) setTimeout(fitViewport, 350); });
addEventListener('pageshow', () => setTimeout(fitViewport, 350));
// Tapping the message box: focus it without iOS's scroll-into-view, which slides the whole page up and
// back while the keyboard opens. A long press or a drag keeps the default.
let boxTouch = null;
input.addEventListener('touchstart', (e) => { const t = e.touches[0]; boxTouch = { at: performance.now(), x: t.clientX, y: t.clientY }; }, { passive: true });
input.addEventListener('touchend', (e) => {
  const t = e.changedTouches[0], s = boxTouch; boxTouch = null;
  if (document.activeElement === input || !s || performance.now() - s.at > 400 || Math.hypot(t.clientX - s.x, t.clientY - s.y) > 10) return;
  e.preventDefault();
  Kb.tap = performance.now();
  input.focus({ preventScroll: true });
});
// Move early only for a tap on the box: a focus from code (a new chat) may bring no keyboard on iOS, and the app sat
// shrunk over a keyboard that never came until the 900 ms check.
input.addEventListener('focus', () => {
  if (!Kb.h || document.documentElement.classList.contains('kb') || performance.now() - Kb.tap > 500) return;   // else wait for iOS
  moveApp(true, fullHeight() - Kb.h);
  clearTimeout(Kb.timer); Kb.timer = setTimeout(fitViewport, 900);   // no keyboard came (a hardware one): undo
});
document.addEventListener('focusout', () => setTimeout(() => {   // the keyboard goes down unless focus moved to another field
  if (!typing()) moveApp(false);
}));
// A new chat puts the cursor in the box only with a real keyboard. On a phone, iOS shows no keyboard for a focus from
// code (after the drawer's slide it is outside the tap), so the box waits for the user's tap, as in Muse.
function focusBox() { if (fineKeys.matches) input.focus(); }
// Drag the chat to put the keyboard away; tapping send keeps it up for the next message.
$('#chatScroll').addEventListener('touchmove', () => { if (document.documentElement.classList.contains('kb')) input.blur(); }, { passive: true });
$('#sendBtn').addEventListener('pointerdown', (e) => { if (document.activeElement === input) e.preventDefault(); });

// ---------- conversations ----------
// Chats you have opened stay in memory, so opening one again shows it at once; the Mac's copy follows.
const Chats = new Map();
const fetching = new Map();
function fetchConv(id, fresh) {
  if (fresh && fetching.has(id)) return fetching.get(id).catch(() => {}).then(() => fetchConv(id, true));   // one sent now
  if (!fetching.has(id)) {
    const missed = [];   // events for this chat that arrive while it loads (replayMissed)
    During.set(id, missed);
    fetching.set(id, api(`/api/conversations/${id}`).then((c) => { c.at = Date.now(); c.missed = missed; Chats.set(id, c); return c; })
      .finally(() => { fetching.delete(id); if (During.get(id) === missed) During.delete(id); }));
  }
  return fetching.get(id);
}
// The Mac's copy of a chat is from when it was read: events that arrived while it loaded (a reply streaming in, its
// end) are played again on it. Each is safe to play twice: chunks know their place, the rest are matched.
const During = new Map();
const LIVE = new Set(['user', 'message', 'note', 'chunk', 'tool', 'done']);
function replayMissed(c) {
  const missed = c.missed || [];
  delete c.missed;
  for (const ev of missed) if (ev.id === S.current && S.conv === c) handle(ev, true);
}
// What you type stays with its chat: each chat keeps its own draft and attachments.
const Drafts = { key: null, map: new Map() };
const draftKey = () => S.current || (S.onMain ? 'main' : 'new');
function keepDraft() {   // before another chat opens
  const k = Drafts.key ?? draftKey();
  if (input.value || S.attachments.length) Drafts.map.set(k, { text: input.value, files: S.attachments }); else Drafts.map.delete(k);
}
function takeDraft() {   // after it opened
  const d = Drafts.map.get(Drafts.key = draftKey());
  Drafts.map.delete(Drafts.key);
  input.value = d?.text || ''; S.attachments = d?.files || [];
  if (!input.value.trim()) S.dictated = false;
  renderAttachments();
}
async function openConv(id, quiet) {   // quiet: a retry of a tapped chat (Tap.retry), no toast again
  const show = (c) => {
    if (Tap.want === id) Tap.done();   // the tapped chat is on screen
    keepDraft();
    S.current = id; S.conv = c; S.thinking = false; S.onMain = id === S.mainId;
    takeDraft();
    for (const m of c.messages) delete m.shown;
    replayMissed(c);
    // the list keeps the chat's title and state current from events: a copy kept from earlier would bring back old ones
    if (!S.convs.some((x) => x.id === id)) upsertConv(c);
    Seen.mark(id);
    history.replaceState(null, '', `#c=${id}`);
    renderAll();
    $('#chatScroll').scrollTop = 1e9;
  };
  const my = ++S.nav, had = Chats.get(id);
  if (had) show(had);
  if (had && Date.now() - had.at < 3000) return;
  try {
    const c = await fetchConv(id);
    if (!had) { if (my === S.nav) show(c); }   // not if you opened something else while it loaded
    else if (S.current === id && S.conv === had) { S.conv = c; replayMissed(c); upsertConv(c); setTitle(); renderMessages(); renderComposer(); }
  } catch (e) {
    if (e.message === 'unauthorized') return;
    if (e.status !== 404) {   // offline: a kept copy stays; a tapped chat is tried again until it opens
      if (!had && my === S.nav && !quiet) toast('Not connected to your Mac');
      Tap.failed(id, my);
      return;
    }
    Chats.delete(id);
    if (my === S.nav) { toast('That chat is gone'); newChat(); }
  }
}
function openConvLocal(id) {
  S.current = id; Drafts.key = id;
  if (S.onMain) S.mainId = id;
  if (!S.conv) S.conv = { messages: [] };
  if (sendPrompt.voiceRef) { S.myVoiceConvs.add(id); sendPrompt.voiceRef = null; }
  history.replaceState(null, '', `#c=${id}`);
  setTitle(); renderComposer(); renderDrawer();
}
function openMain(stay) {   // stay: on the tab you are on
  if (S.tab !== 'chat' && !stay) switchTab('chat');
  if (S.mainId) return openConv(S.mainId);
  S.nav++; keepDraft();
  S.current = null; S.conv = null; S.thinking = false; S.onMain = true;   // made on the first message
  takeDraft();
  history.replaceState(null, '', '#');
  renderAll();
}
function newChat() {   // a new side chat
  S.ghostTurn = (S.ghostTurn || 0) + 1;   // a different idea for each new chat
  S.nav++; keepDraft();
  S.current = null; S.conv = null; S.thinking = false; S.onMain = false;
  takeDraft();
  history.replaceState(null, '', '#');
  renderAll();
  if (S.tab !== 'chat') switchTab('chat');
}
// Unread: a chat changed after you last looked at it, on any device. The Mac keeps what was read (`read`, the
// newest `updated` seen) and tells every open app; a per-device copy left the laptop dotted after the phone read it.
const Seen = {
  mark(id) {
    const c = S.convs.find((x) => x.id === id);
    if (!c || c.read == null || c.read >= c.updated) return;   // no `read`: a bridge from before, not restarted yet
    c.read = c.updated;   // the dot goes now; the Mac tells the other devices
    api(`/api/conversations/${id}/read`, { method: 'POST', body: { at: c.updated } }).catch(() => {});
  },
  unread(c) { return c.read != null && c.id !== S.current && !c.running && c.updated > c.read; },
};
store.del('seen');   // the old per-device read state
function renderMenuDot() {
  $('.menu-dot').hidden = !(S.approvals.size || S.convs.some((c) => !c.schedule && Seen.unread(c)));
}
function renderDrawer() {
  const list = $('#convList');
  $('#drawerName').textContent = S.settings.assistant_name || 'Milo';
  const q = $('#convSearch').value.trim().toLowerCase();
  const match = (c) => !q || `${c.title} ${c.preview || ''}`.toLowerCase().includes(q);
  const convs = S.convs.filter((c) => !c.main && !c.schedule && match(c));   // a task's own chat is hidden
  const main = S.convs.find((c) => c.main);
  const mainBtn = $('#tabs [data-main]');
  mainBtn.classList.toggle('active', S.tab === 'chat' && S.onMain);
  mainBtn.querySelector('.unread-dot')?.remove();
  if (main && Seen.unread(main)) mainBtn.insertAdjacentHTML('beforeend', '<span class="unread-dot"></span>');
  renderMenuDot();
  if (!convs.length) { list.innerHTML = `<div class="empty-state">${q ? 'No chats match.' : 'No side chats yet. Tap the pencil to start one.'}</div>`; return; }
  const row = (c) => {
    const unread = Seen.unread(c);
    return `<div class="conv ${c.id === S.current && S.tab === 'chat' ? 'active' : ''} ${unread ? 'unread' : ''}" data-id="${c.id}">
    <div class="tx"><b>${esc(c.title)}</b></div>
    ${c.running ? '<span class="live"></span>' : unread ? '<span class="unread-dot"></span>' : ''}
    <button class="del" data-rename="${c.id}" aria-label="Rename">${ICON.pencil}</button>
    <button class="del" data-del="${c.id}" aria-label="Delete">${ICON.trash}</button></div>`;
  };
  list.innerHTML = convs.map(row).join('');
}
$('#convList').addEventListener('click', async (e) => {
  const ren = e.target.closest('[data-rename]');
  if (ren) { openRename(ren.dataset.rename); return; }
  const del = e.target.closest('[data-del]');
  if (del) {   // one tap: a side chat is cheap to lose, and the main chat has no delete button
    await api(`/api/conversations/${del.dataset.del}`, { method: 'DELETE' }).catch((err) => toast(err.message));
    return;
  }
  const row = e.target.closest('.conv');
  if (row) {
    const id = row.dataset.id, my = ++S.nav;
    if (!Chats.has(id)) await Promise.race([fetchConv(id).catch(() => {}), new Promise((r) => setTimeout(r, 400))]);
    if (my !== S.nav) return;   // another chat was tapped meanwhile
    closeSheet('drawer'); switchTab('chat'); openConv(id);
  }
});
// Start loading a chat as the finger lands on it.
$('#convList').addEventListener('pointerdown', (e) => {
  const row = e.target.closest('.conv');
  if (row && !e.target.closest('button') && !Chats.has(row.dataset.id)) fetchConv(row.dataset.id).catch(() => {});
});
function openRename(id) {
  const c = S.convs.find((x) => x.id === id);
  if (!c) return;
  const f = $('#renameForm');
  f.dataset.id = id; f.title.value = c.title; $('#renameErr').textContent = '';
  openSheet('renameSheet');
  setTimeout(() => { f.title.focus(); f.title.select(); }, 50);
}
$('#renameForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target, title = f.title.value.trim();
  try {
    await api(`/api/conversations/${f.dataset.id}`, { method: 'PATCH', body: { title } });
    upsertConv({ id: f.dataset.id, title }); renderDrawer(); setTitle();
    f.title.blur(); closeSheet('renameSheet');
  } catch (err) { $('#renameErr').textContent = err.message; }
});
function armed(btn, msg = 'Tap again to confirm') {
  // two-tap confirm instead of a modal dialog. A double tap is one tap: it must not confirm by itself.
  if (btn.dataset.armed) return Date.now() - btn.dataset.armed > 400;
  btn.dataset.armed = Date.now(); btn.style.color = 'var(--danger)';
  setTimeout(() => { delete btn.dataset.armed; btn.style.color = ''; }, 2500);
  toast(msg, 1500);
  return false;
}
// One request at a time from a form or button: a double tap (or Return twice) must not save or start a thing twice.
const pending = new WeakSet();
async function inFlight(el, fn) {
  if (pending.has(el)) return;
  pending.add(el);
  const btns = el.matches('form') ? $$('button[type=submit], button:not([type])', el) : [el];
  btns.forEach((b) => { b.disabled = true; });
  try { return await fn(); } finally { pending.delete(el); btns.forEach((b) => { b.disabled = false; }); }
}

function renderIdeas() {
  $('#ideas').innerHTML = IDEAS.map(([t, p]) => `<button class="idea" data-p="${esc(p)}"><b>${esc(t)}</b><span>${esc(p)}</span></button>`).join('');
}
$('#ideas').addEventListener('click', (e) => {
  const b = e.target.closest('[data-p]');
  if (!b) return;
  input.value = b.dataset.p; input.dispatchEvent(new Event('input')); input.focus();
});

// ---------- push-to-talk: dictate into the message box ----------
// Hold the mic and talk: your words appear in the box as you speak. Release to stop, then tap send.
// A short tap also works: tap to start, tap again to stop.
const ptt = { rec: new Recorder(), down: false, active: false, held: false, finishing: false, t0: 0, session: 0, partial: null, base: '' };
function setDictation(text) {
  input.value = ptt.base + text;
  input.dispatchEvent(new Event('input'));
  input.scrollTop = input.scrollHeight;   // the box is capped: follow the newest words
}
$('#micBtn').addEventListener('pointerdown', async (e) => {
  e.preventDefault();
  if (ptt.finishing) return;
  if (ptt.active) return finishPtt();
  ptt.down = true;
  stopSpeaking();
  if (!S.voiceInput) return toast('Voice input is off on the Mac (whisper not running)');
  // No audio meter and no sound playback before recording: on iOS either one can make the mic record silence.
  try { await ptt.rec.open(false); } catch { return toast('Microphone access was blocked'); }
  ptt.rec.start();
  ptt.active = S.dictating = true; ptt.held = ptt.down; ptt.t0 = performance.now();
  const before = input.value.trim();
  ptt.base = before ? before + ' ' : '';
  $('#micBtn').classList.add('rec'); $('#micBtn').ariaLabel = 'Stop recording';
  renderComposer();
  livePtt(++ptt.session);
});
function releasePtt() {
  ptt.down = false;
  if (!ptt.active || !ptt.held) return;
  ptt.held = false;
  if (performance.now() - ptt.t0 > 400) finishPtt();   // a short tap keeps recording until the next tap
}
window.addEventListener('pointerup', releasePtt);
window.addEventListener('pointercancel', releasePtt);
$('#micBtn').addEventListener('contextmenu', (e) => e.preventDefault());
// While recording, transcribe the audio so far again and again (one request at a time).
async function livePtt(session) {
  const live = () => ptt.active && ptt.session === session;
  let done = 0;
  while (live()) {
    await new Promise((r) => setTimeout(r, 300));
    const n = ptt.rec.chunks.length;
    if (!live() || n === done || performance.now() - ptt.t0 < 1000) continue;
    done = n;
    ptt.partial = transcribe(ptt.rec.snapshot())
      .then((text) => { if (live() && text) setDictation(text); })
      .catch(() => {});
    await ptt.partial;
  }
}
async function finishPtt() {
  if (!ptt.active) return;
  ptt.active = false; ptt.finishing = S.transcribing = true;
  $('#micBtn').classList.remove('rec'); $('#micBtn').ariaLabel = 'Hold to talk';
  renderComposer();   // a spinner shows at once, not the mic, while the last words come in
  const stopping = ptt.rec.stop();
  if (S.speakPolicy !== 'never') unlockAudio();   // still inside your tap: lets Milo read the reply aloud later
  // each wait has a limit: iOS can drop the recorder's stop event, and a live pass can hang, which left the spinner on
  const within = (p, ms) => Promise.race([p, new Promise((r) => setTimeout(r, ms))]);
  try {
    const blob = await within(stopping, 3000) || ptt.rec.snapshot?.();
    ptt.rec.close();
    if (blob && blob.size >= 1500) {
      await within(ptt.partial, 5000);   // let a live update finish first, so the final pass does not wait behind it
      const text = await Promise.race([transcribe(blob), new Promise((_, no) => setTimeout(() => no(new Error('timed out')), 20000))]);
      if (text && !S.typedWhileBusy) { setDictation(text); S.dictated = true; } else if (!text && !input.value.trim()) toast("I didn't catch that");
    }
  } catch (e) { toast('Transcription failed: ' + e.message); }
  ptt.finishing = S.dictating = S.transcribing = S.typedWhileBusy = false;
  renderComposer();
  if (S.sendAfter) { S.sendAfter = false; submitText(); }   // send was tapped while the last words came in
}

// ---------- voice mode (hands-free loop) ----------
const Voice = {
  on: false, rec: new Recorder(), raf: 0, state: 'idle', waitingFor: null, reply: '', paused: false,
  async enter() {
    unlockAudio();
    if (!S.voiceInput) return toast('Voice input is off on the Mac (whisper not running)');
    try { await this.rec.open(); } catch { return toast('Microphone access was blocked'); }
    this.on = true; this.paused = false;
    $('#voice').hidden = false; $('#voiceText').textContent = '';
    this.listen();
  },
  exit() {
    this.on = false; cancelAnimationFrame(this.raf); stopSpeaking();
    this.rec.close(); $('#voice').hidden = true; this.waitingFor = null;
  },
  set(state, label, hint) {
    this.state = state;
    $('#voice').className = `voice ${state}`;
    $('#voiceState').textContent = label;
    if (hint !== undefined) $('#voiceHint').textContent = hint;
    $('#voiceMute').classList.toggle('off', this.paused);
  },
  listen() {
    if (!this.on) return;
    if (this.paused) return this.set('idle', 'Paused', 'Tap the mic to listen again.');
    this.set('listening', 'Listening', 'Speak naturally. I send when you pause.');
    this.rec.start();
    const t0 = performance.now();
    let floor = 0.006, heard = false, lastVoice = 0, n = 0;
    const orb = $('#voiceOrb');
    const tick = () => {
      if (!this.on || this.state !== 'listening') return;
      const lvl = this.rec.level(), now = performance.now();
      if (now - t0 < 350) { floor = Math.max(floor, (floor * n + lvl) / ++n); }
      const thresh = Math.max(0.018, floor * 3);
      if (lvl > thresh) { heard = true; lastVoice = now; }
      orb.style.transform = `scale(${1 + Math.min(0.35, lvl * 5)})`;
      if (heard && now - lastVoice > 1200) return this.finish();
      if (!heard && now - t0 > 12000) { this.rec.stop(); this.paused = true; return this.listen(); }
      if (now - t0 > 90000) return this.finish();
      this.raf = requestAnimationFrame(tick);
    };
    tick();
  },
  async finish() {
    cancelAnimationFrame(this.raf);
    $('#voiceOrb').style.transform = '';
    this.set('thinking', 'Transcribing');
    const blob = await this.rec.stop();
    if (!this.on) return;
    let text = '';
    try { text = blob && blob.size > 1500 ? await transcribe(blob) : ''; } catch (e) { toast('Transcription failed'); }
    if (!this.on) return;
    if (!text) return this.listen();
    $('#voiceText').textContent = `“${text}”`;
    this.set('thinking', 'Thinking', 'Tap stop to interrupt.');
    this.reply = '';
    this.waitingFor = S.current || 'pending';
    if (!sendPrompt(text, true)) { this.waitingFor = null; return this.listen(); }
  },
  matches(id) { return this.on && this.waitingFor && (this.waitingFor === id || (this.waitingFor === 'pending' && S.current === id)); },
  onChunk(ev) {
    if (!this.matches(ev.id)) return;
    this.waitingFor = ev.id;
    this.reply += ev.text;
    const clean = stripDirectives(this.reply).replace(/[#*`_>|]/g, '').trim();
    if (clean) $('#voiceText').textContent = clean.slice(-400);
  },
  onDone(ev) {
    if (!this.matches(ev.id)) return false;
    this.waitingFor = null;
    S.myVoiceConvs.delete(ev.id);
    if (ev.error) { $('#voiceText').textContent = 'Something went wrong. Check the chat.'; this.listen(); return true; }
    if (ev.stop === 'cancelled') { this.listen(); return true; }
    const text = ev.message.text || 'Done.';
    $('#voiceText').textContent = text.replace(/[#*`_>|]/g, '').slice(0, 600);
    this.set('speaking', 'Speaking', 'Tap stop to interrupt.');
    speak(text).then(() => { if (this.on && this.state === 'speaking') this.listen(); });
    return true;
  },
  onApproval(a) {
    if (!this.on || !(this.waitingFor === a.conv || (this.waitingFor === 'pending' && S.current === a.conv))) return;
    this.set('idle', 'Needs your OK', '');
    $('#voiceText').innerHTML = approvalHtml(a, true);
    speak(`I need your OK first. ${a.title}`);
  },
  onApprovalAnswered() {
    if (this.on && this.waitingFor) { $('#voiceText').textContent = ''; this.set('thinking', 'Working', 'Tap stop to interrupt.'); }
  },
};
$('#avatarBtn').onclick = () => Voice.enter();   // tap the avatar to talk
$('#voiceClose').onclick = () => Voice.exit();
$('#voiceText').addEventListener('click', (e) => {
  const opt = e.target.closest('[data-opt]');
  if (opt) answerApproval(opt.closest('[data-aid]').dataset.aid, opt.dataset.opt);
});
$('#voiceMute').onclick = () => {
  unlockAudio();
  if (Voice.paused) { Voice.paused = false; stopSpeaking(); if (Voice.state !== 'thinking') Voice.listen(); }
  else { Voice.paused = true; if (Voice.state === 'listening') { cancelAnimationFrame(Voice.raf); Voice.rec.stop(); } Voice.set('idle', 'Paused', 'Tap the mic to listen again.'); }
};
$('#voiceInterrupt').onclick = () => {
  stopSpeaking();
  if (Voice.waitingFor && S.current) send({ type: 'cancel', id: S.current, now: true });
  Voice.waitingFor = null;
  if (Voice.state === 'listening') { cancelAnimationFrame(Voice.raf); Voice.rec.stop(); }
  Voice.paused = false; Voice.listen();
};
$('#voiceOrb').onclick = () => { if (Voice.paused || Voice.state === 'idle') { Voice.paused = false; Voice.listen(); } else if (Voice.state === 'listening') Voice.finish(); };

// ---------- tabs ----------
function switchTab(tab) {
  S.tab = tab;
  closeSheet('drawer');
  $$('[data-tab]').forEach((b) => b.classList.toggle('active', b.dataset.tab === tab && (b.dataset.main === undefined || S.onMain)));
  for (const v of ['chat', 'feed', 'ideas', 'goals', 'library', 'upcoming', 'activity', 'permissions']) $(`#view-${v}`).hidden = v !== tab;
  placeTabPill(true);
  if (tab === 'chat') {   // iOS: rebuild the chat's scroller when it comes back, so the finger reaches it
    const sc = $('#chatScroll');
    sc.style.overflowY = 'hidden';
    requestAnimationFrame(() => { sc.style.overflowY = ''; });
  }
  setTitle(); renderApprovals(); renderDrawer();
  if (tab === 'feed') renderFeed();
  if (tab === 'library') setLibView('today');   // the Library opens on Today
  loadTab(tab);
}
function loadTab(tab) {   // the tab's data, again from the Mac
  if (tab === 'feed') loadFeed();
  if (tab === 'ideas') loadIdeas();
  if (tab === 'goals') loadGoals();
  if (tab === 'library') loadLibrary();
  if (tab === 'upcoming') loadUpcoming();
  if (tab === 'activity') loadActivity();
  if (tab === 'permissions') loadPermissions();
}
// The tab bar's highlight is one pill that slides to the active tab (like Muse), rather than a fade per tab.
function placeTabPill(animate) {
  const bar = $('#tabbar'), pill = bar.querySelector('.tab-pill'), b = bar.querySelector('button.active');
  if (!bar.offsetWidth) return;   // folded away under the keyboard
  pill.classList.toggle('still', !animate || pill.style.opacity === '0' || !pill.style.width);
  pill.style.opacity = b ? '1' : '0';
  if (b) { pill.style.width = `${b.offsetWidth}px`; pill.style.transform = `translateX(${b.offsetLeft}px)`; }
}
window.addEventListener('resize', () => placeTabPill(false));
for (const nav of ['#tabs', '#tabbar']) $(nav).addEventListener('click', (e) => {
  const b = e.target.closest('[data-tab]');
  if (b?.dataset.main !== undefined) { closeSheet('drawer'); openMain(); }
  else if (b?.dataset.tab === 'chat' && S.tab === 'chat' && !S.onMain) openMain();   // tapped again in a side chat: the main chat, as iOS tabs go back to their start
  else if (b) switchTab(b.dataset.tab);
});

// ---------- ideas ----------
// Things Milo offers to do. The Mac makes new ones in the background when they are old.
async function fetchIdeas() {   // for the suggestion in the message box
  try { S.ideas = (await api('/api/ideas')).items; renderComposer(); } catch {}
}
async function loadIdeas() {
  const box = $('#ideasList');
  try {
    const r = await api('/api/ideas');
    S.ideas = r.items; S.ideasBusy = r.busy || S.ideasBusy;
    $('#ideasRefresh').disabled = S.ideasBusy;
    const thinking = S.ideasBusy ? `<div class="thinking-row"><span class="spin"></span>${esc(S.settings.assistant_name || 'Milo')} is thinking of ideas…</div>` : '';
    if (!r.items.length) { box.innerHTML = thinking || '<div class="empty-state">No ideas right now. Tap New ideas.</div>'; return; }
    box.innerHTML = thinking + r.items.map((it) => `<button class="idea-row" data-idea="${esc(it.id)}">
      <div class="idea-emoji">${esc(it.emoji)}</div><div><b>${esc(it.title)}</b><span>${esc(it.detail)}</span></div></button>`).join('');
  } catch (e) { box.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; }
}
$('#ideasRefresh').onclick = async () => {
  S.ideasBusy = true;
  // not started: no "thinking" row that never ends
  await api('/api/ideas/refresh', { method: 'POST' }).catch((e) => { S.ideasBusy = false; toast(e.message); });
  loadIdeas();
};
$('#ideasList').addEventListener('click', (e) => {
  const b = e.target.closest('[data-idea]');
  const it = b && S.ideas.find((x) => x.id === b.dataset.idea);
  if (!it) return;
  S.idea = it;
  $('#ideaEmoji').textContent = it.emoji; $('#ideaTitle').textContent = it.title; $('#ideaDetail').textContent = it.detail;
  openSheet('ideaSheet');
});
async function dropIdea(it) { await api(`/api/ideas/${it.id}/dismiss`, { method: 'POST' }).catch(() => {}); }
$('#ideaDo').onclick = async () => {   // do it in a new side chat
  const it = S.idea; closeSheet('ideaSheet');
  switchTab('chat'); newChat(); sendPrompt(it.prompt, false);
  dropIdea(it);
};
$('#ideaSkip').onclick = async () => { closeSheet('ideaSheet'); await dropIdea(S.idea); loadIdeas(); };

// ---------- feed ----------
// Politics and AI from your X For you timeline, key posts from Following. The Mac reads them in Milo's browser and
// writes the briefs (feed.py).
const FI = {
  posts: '<svg viewBox="0 0 24 24"><path d="M4 6h16M4 12h16M4 18h10"/></svg>',
  out: '<svg viewBox="0 0 24 24"><path d="M14 4h6v6M20 4l-9 9M18 14v5a1 1 0 0 1-1 1H5a1 1 0 0 1-1-1V7a1 1 0 0 1 1-1h5"/></svg>',
  spark: '<svg viewBox="0 0 24 24"><path d="M12 3l1.8 5.2L19 10l-5.2 1.8L12 17l-1.8-5.2L5 10l5.2-1.8z"/></svg>',
  more: '<svg viewBox="0 0 24 24"><circle cx="6" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="18" cy="12" r="1.3" fill="currentColor"/></svg>',
  reply: '<svg viewBox="0 0 24 24"><path d="M21 12a8 8 0 0 1-11.8 7L4 20l1.1-4.6A8 8 0 1 1 21 12z"/></svg>',
  rt: '<svg viewBox="0 0 24 24"><path d="M7 7h11l-3-3M17 17H6l3 3"/><path d="M18 7v5M6 17v-5"/></svg>',
  like: '<svg viewBox="0 0 24 24"><path d="M12 20s-7-4.4-7-10a4 4 0 0 1 7-2.6A4 4 0 0 1 19 10c0 5.6-7 10-7 10z"/></svg>',
  views: '<svg viewBox="0 0 24 24"><path d="M5 20V11M10 20V5M15 20v-7M20 20v-4"/></svg>',
  mark: '<svg viewBox="0 0 24 24"><path d="M6 4h12v16l-6-4-6 4z"/></svg>',
  refresh: '<svg viewBox="0 0 24 24"><path d="M20 11a8 8 0 0 0-14.5-4.5L4 8M4 4v4h4M4 13a8 8 0 0 0 14.5 4.5L20 16M20 20v-4h-4"/></svg>',
  tri: '<svg viewBox="0 0 24 24"><path d="M7 4l13 8-13 8z"/></svg>',
  link: '<svg viewBox="0 0 24 24"><path d="M10 14a4 4 0 0 0 5.7 0l3-3a4 4 0 0 0-5.7-5.7l-1 1"/><path d="M14 10a4 4 0 0 0-5.7 0l-3 3a4 4 0 0 0 5.7 5.7l1-1"/></svg>',
  up: '<svg viewBox="0 0 24 24"><path d="M7 10v11M15 5.9L14 10h5.8a2 2 0 0 1 1.9 2.6l-2.3 8a2 2 0 0 1-1.9 1.4H4a2 2 0 0 1-2-2v-8a2 2 0 0 1 2-2h2.8a2 2 0 0 0 1.8-1.1L12 2a3.1 3.1 0 0 1 3 3.9z"/></svg>',
  down: '<svg viewBox="0 0 24 24"><path d="M17 14V3M9 18.1l1-4.1H4.2a2 2 0 0 1-1.9-2.6l2.3-8A2 2 0 0 1 6.5 2H20a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2h-2.8a2 2 0 0 0-1.8 1.1L12 22a3.1 3.1 0 0 1-3-3.9z"/></svg>',
};
const F = { data: null, busy: false, tab: store.get('feedTab', 'politics'), speaking: false, menu: null, lastY: 0 };
const TAB_NAMES = { politics: 'Politics', foryou: 'AI', following: 'Following' };   // foryou is the AI tab (its id from before)
const FEED_PROMPTS = ['politics_prompt', 'prompt', 'following_prompt'];
// Images come through the Mac (cached there); X serves smaller sizes with ?name=
function mediaSrc(url, size) {
  if (!url) return '';
  if (size && /\/media\/|video_thumb\//.test(url) && !url.includes('?')) url += `?name=${size}`;
  if (url.includes('/profile_images/')) url = url.replace('_normal.', '_200x200.');
  return `/api/feed/media?u=${encodeURIComponent(url)}&token=${encodeURIComponent(S.token)}`;
}
const fmtCount = (n) => n >= 1e6 ? `${(n / 1e6).toFixed(1)}M` : n >= 1e4 ? `${Math.round(n / 1e3)}k` : n >= 1e3 ? `${(n / 1e3).toFixed(1)}k` : String(n || 0);
function ago(ts) {
  const s = Math.max(0, Date.now() / 1000 - ts);
  return s < 3600 ? `${Math.max(1, Math.floor(s / 60))}m` : s < 86400 ? `${Math.floor(s / 3600)}h` : `${Math.floor(s / 86400)}d`;
}
function linkify(text) {   // links are shown short, like on X
  return esc(text).replace(/https?:\/\/[^\s<]+/g, (u) => {
    const short = u.replace(/^https?:\/\/(www\.)?/, '');
    return `<a href="${u}" target="_blank" rel="noopener">${short.length > 32 ? short.slice(0, 31) + '…' : short}</a>`;
  });
}
function feedPost(id) {
  const tabs = F.data?.tabs || {};
  return tabs[F.tab]?.posts?.[id] || Object.values(tabs).map((t) => t.posts?.[id]).find(Boolean);
}
const muted = (p) => (F.data?.settings.muted || []).some((h) => h.toLowerCase() === p.handle.toLowerCase());
const plural = (n, w) => `${n} ${w}${n === 1 ? '' : 's'}`;

const ratioOf = (m, lo, hi) => (m.w && m.h ? Math.min(Math.max(m.w / m.h, lo), hi) : 16 / 9);
// One photo or video as X shows it: under the text, full width. Videos play in place (GIFs loop, muted); a photo opens
// full screen. A chart keeps its whole picture.
// A quoted post's media (p.quoted) carries data-fq, so it opens and plays as that post, not the one quoting it.
function mediaItem(p, n, fit) {
  const m = p.media[n], fq = p.quoted ? ' data-fq' : '';
  if (m.type !== 'photo' && m.video) return `<div class="feed-media" style="aspect-ratio:${ratioOf(m, 0.8, 2)}"><video src="${esc(m.video)}"
    poster="${mediaSrc(m.url, 'medium')}" playsinline ${m.type === 'gif' ? 'autoplay loop muted' : `controls preload="none" data-vpid="${esc(p.id)}"${fq}`}></video></div>`;
  return `<button class="feed-media${fit ? ' fit' : ''}" style="aspect-ratio:${fit ? ratioOf(m, 0.6, 3) : ratioOf(m, 0.75, 2)}" data-fmedia="${esc(p.id)}"
    data-n="${n}"${fq} aria-label="Open photo"><img src="${mediaSrc(m.url, 'medium')}" alt="${esc(m.alt)}" loading="lazy"></button>`;
}
const shownPost = (id, q) => (q ? feedPost(id)?.quote : feedPost(id));
// A lock pauses the video; Play on the lock screen goes on with the sound. iOS pauses a <video> when the app hides but
// lets an <audio> play on (Home Screen apps since iOS 15.4). So bgAudio plays along, muted and in step with the video,
// and the lock screen's Play unmutes it. Back in the app, the picture catches up with the sound, muted, then takes it back.
const bgAudio = new Audio();
bgAudio.playsInline = true;
// v: the video it follows. going: you want it to play. on: bgAudio has the sound.
// back: the picture is catching up. lead, vlead: how far ahead a jump of bgAudio or the video aims (a jump takes a moment).
const BG = { v: null, going: false, on: false, back: 0, timer: 0, unlocked: false, lead: 0.1, vlead: 0.3, jumped: false, jumps: 0 };
// paused stays false after an error (a silent clip that won't decode), so an error means it doesn't play
const sounding = (m) => !m.paused && !m.ended && !m.error;
const playingVideo = () => $$('#feedBody video[data-vpid]').find(sounding);
// iOS pauses the video a moment before the page hides: a video you still want to play counts
function mediaPlaying() {
  return !!playingVideo() || BG.on || (BG.going && !!BG.v?.isConnected) || (player.src.startsWith('blob:') && sounding(player))
    || $$('#fvBody audio, #fvBody video, #mediaStage video').some(sounding);   // a Library file plays on with the screen off
}
// A tap on a feed video lets bgAudio play sound later without one (from this play() on, even if the clip fails).
// Only that tap: any play(), even of a silent clip, stops music in other apps.
function unlockBg(e) {
  if (BG.unlocked || BG.v || mediaPlaying() || !feedVideo(e.target)) return;   // not while something plays, or iOS would pause it
  BG.unlocked = true;
  bgAudio.src = SILENT;
  bgAudio.play().catch((e) => { if (e.name === 'NotAllowedError') BG.unlocked = false; });
}
document.addEventListener('touchend', unlockBg, { capture: true, passive: true });
document.addEventListener('click', unlockBg, true);
function link(v) {   // bgAudio comes along, muted. It starts after the video does: started first, iOS would pause it.
  if (BG.v !== v) { settle(); BG.v = v; bgAudio.src = `${v.currentSrc || v.src}#t=${v.currentTime.toFixed(2)}`; }
  BG.going = true;   // it plays (iOS pausing the last video for this one cleared it)
  bgAudio.muted = true;
  bgAudio.play().catch(() => {});
}
// iOS can freeze a player whose speed goes back to 1 while it plays, so the two keep in step by jumping, never by
// changing speed. bgAudio's jumps are muted, so nobody hears them.
function keepInStep(v) {   // within a few hundredths of a second of the video, so the switch at the lock is clean
  if (BG.on || v.paused || v.seeking || bgAudio.ended || bgAudio.error) return;
  if (bgAudio.paused) return link(v);   // iOS pauses it when the video starts again
  if (bgAudio.seeking || bgAudio.readyState < 3) return;
  const d = bgAudio.currentTime - v.currentTime;
  if (BG.jumped) { BG.jumped = false; BG.lead = Math.min(0.5, Math.max(0, BG.lead - d)); }   // how long a jump takes
  if (Math.abs(d) > 0.05) { bgAudio.currentTime = v.currentTime + BG.lead; BG.jumped = true; }
}
function takeOver() {   // Play on the lock screen: bgAudio, already in step, goes on from where the video stopped
  const v = BG.v;
  if (!v || !BG.going || (!BG.on && v.muted)) return;
  if (!BG.on) {
    BG.on = true;
    v.muted = true;   // in case iOS hasn't paused it yet
    bgAudio.muted = false;
    // Started muted, bgAudio isn't what iOS shows on the lock screen (it shows the paused video). Started again with
    // sound, it is. Costs a few hundredths of a second.
    bgAudio.pause();
  }
  if (bgAudio.paused) {   // it hadn't come along, or iOS paused it as the app hid
    if (Math.abs(bgAudio.currentTime - v.currentTime) > 1) bgAudio.currentTime = v.currentTime;
    bgAudio.play().catch(() => {});
  }
}
function giveBack() {   // back in the app: the picture catches up with the sound, muted, then takes the sound back
  const v = BG.v;
  clearTimeout(BG.timer);
  if (!v?.isConnected || !sounding(bgAudio)) {   // paused from the lock screen: the video waits at that second
    if (v && bgAudio.currentTime) v.currentTime = bgAudio.currentTime;
    BG.going = sounding(bgAudio) && BG.going;
    return settle();
  }
  v.currentTime = bgAudio.currentTime + BG.vlead;   // it takes a moment to get going
  v.play().catch(() => {});
  BG.back = Date.now(); BG.jumps = 0;
  BG.timer = setTimeout(swap, 3000);   // in step or not, the video gets its sound back
}
function catchUp(v) {   // the picture jumps until it is within a few hundredths of the sound
  if (v.paused || v.seeking || v.readyState < 3) return;
  const d = v.currentTime - bgAudio.currentTime;
  if (Math.abs(d) < 0.06 || BG.jumps >= 3) return swap();
  BG.vlead = Math.min(1, Math.max(0, BG.vlead - d));
  BG.jumps++;
  v.currentTime = bgAudio.currentTime + BG.vlead;
}
function swap() {
  if (!BG.on) return;
  clearTimeout(BG.timer);
  BG.on = false; BG.back = 0;
  BG.v.muted = false;
  bgAudio.muted = true;
}
function settle() {   // the sound stops with the video
  clearTimeout(BG.timer);
  if (BG.on && BG.v) BG.v.muted = false;
  BG.on = false; BG.back = 0;
  bgAudio.pause();
  bgAudio.muted = true;
}
const bgMedia = () => (BG.on ? bgAudio : BG.v);   // what the lock screen controls
// ---------- Now Playing ----------
// The lock screen, Control Center and the Dynamic Island show one navigator.mediaSession for the whole app. What starts
// playing with sound puts its own title, picture and buttons there, and takes them off when it goes away: else a
// Library file played under the last feed post's title and picture, and its buttons played that video.
const NP = { el: null };   // the player the lock screen shows (for the feed: its video, standing for bgAudio too)
const NP_ACTS = ['play', 'pause', 'seekto', 'seekbackward', 'seekforward'];
const APP_ART = [{ src: '/icon-512.png?v=7', sizes: '512x512', type: 'image/png' }];
function setNowPlaying(el, meta, acts) {
  NP.el = el;
  const ms = navigator.mediaSession;
  if (!ms) return;
  try { ms.metadata = window.MediaMetadata ? new MediaMetadata(meta) : null; } catch {}
  for (const k of NP_ACTS) try { ms.setActionHandler(k, acts[k] || null); } catch {}   // older iOS lacks some
  try { ms.setPositionState?.(); } catch {}   // not the last player's progress bar; position() sets this one's
}
function clearNowPlaying(el) {   // only its own: another player may have it by now
  if (!el || NP.el !== el) return;
  NP.el = null;
  const ms = navigator.mediaSession;
  if (!ms) return;
  ms.metadata = null;
  for (const k of NP_ACTS) try { ms.setActionHandler(k, null); } catch {}
  try { ms.setPositionState?.(); } catch {}
}
// One sound at a time, as iOS does between apps: what starts with sound pauses the rest (WebKit on a Mac plays both).
function hushOthers(el) {
  // the feed's video, also while bgAudio has its sound (it plays muted then, catching up)
  if (BG.v && el !== BG.v && (BG.on || sounding(BG.v))) { BG.going = false; BG.v.pause(); settle(); }
  $$('audio, video').forEach((m) => { if (m !== el && !m.muted && sounding(m)) m.pause(); });
  if (el !== player && player.src.startsWith('blob:') && sounding(player)) stopSpeaking();
}
function position(m) {   // the lock screen's progress bar
  const ms = navigator.mediaSession;
  if (!m || !ms?.setPositionState || !(m.duration > 0 && m.duration < Infinity)) return;
  try { ms.setPositionState({ duration: m.duration, playbackRate: m.playbackRate || 1, position: Math.min(m.currentTime, m.duration) }); } catch {}
}
function seekIn(m, t) {
  if (!m) return;
  m.currentTime = Math.max(0, m.duration ? Math.min(t, m.duration - 0.1) : t);
  position(m);
}
const seekActs = (get) => ({   // a progress bar you can drag and 10 s skips, on what get() returns
  seekto: (e) => seekIn(get(), e.seekTime),
  seekbackward: (e) => seekIn(get(), (get()?.currentTime || 0) - (e.seekOffset || 10)),
  seekforward: (e) => seekIn(get(), (get()?.currentTime || 0) + (e.seekOffset || 10)),
});
const postMeta = (p, v) => ({ title: p?.text.slice(0, 90) || 'Video', artist: p ? `@${p.handle}` : '', artwork: v.poster ? [{ src: v.poster }] : [] });
function nowPlaying(v) {   // the post on the lock screen; its buttons work the video, or bgAudio once it has the sound
  setNowPlaying(v, postMeta(shownPost(v.dataset.vpid, 'fq' in v.dataset), v), {
    play: () => { BG.going = true; if (document.hidden && !BG.on) takeOver(); else bgMedia()?.play().catch(() => {}); },
    pause: () => { BG.going = false; bgMedia()?.pause(); },
    ...seekActs(bgMedia),
  });
}
const feedVideo = (t) => t instanceof HTMLVideoElement && !!t.dataset.vpid;
// A Library file shows its name, a full-screen feed video its post. Muted players (GIFs, a video catching up) don't count.
document.addEventListener('play', (e) => {
  const m = e.target;
  if (!(m instanceof HTMLMediaElement) || m.muted) return;
  hushOthers(m);
  if (feedVideo(m)) return;   // nowPlaying
  const meta = m.closest('#fvBody') ? { title: FV.file?.name || 'File', artist: S.settings.assistant_name || 'Milo', album: 'Library', artwork: APP_ART }
    : m.closest('#mediaStage') ? postMeta(shownPost($('#mediaView').dataset.pid, !!$('#mediaView').dataset.fq), m) : null;
  if (!meta) return;
  setNowPlaying(m, meta, { play: () => m.play().catch(() => {}), pause: () => m.pause(), ...seekActs(() => m) });
  position(m);
}, true);
document.addEventListener('play', (e) => { if (feedVideo(e.target)) { BG.going = true; nowPlaying(e.target); } }, true);
document.addEventListener('playing', (e) => { if (feedVideo(e.target) && (e.target !== BG.v || !BG.on)) link(e.target); }, true);
document.addEventListener('timeupdate', (e) => { if (e.target === BG.v) (BG.back ? catchUp : keepInStep)(e.target); }, true);
document.addEventListener('seeking', (e) => { if (e.target === BG.v && !BG.on) bgAudio.currentTime = e.target.currentTime; }, true);
document.addEventListener('ended', (e) => { if (e.target === BG.v) BG.going = false; }, true);
document.addEventListener('ratechange', (e) => {   // your speed. bgAudio changes it while paused (see keepInStep).
  const v = e.target;
  if (v !== BG.v || BG.on || bgAudio.playbackRate === v.playbackRate) return;
  const going = !bgAudio.paused;
  bgAudio.pause();
  bgAudio.playbackRate = v.playbackRate;
  if (going) bgAudio.play().catch(() => {});
}, true);
document.addEventListener('pause', (e) => {   // you, a scroll or the lock paused it: the sound stops with it
  if (e.target !== BG.v || e.target.ended || (BG.on && !BG.back)) return;   // locked, and bgAudio has the sound
  BG.going = false;
  settle();
}, true);
// A video you scroll past (or leave the Feed from) pauses, like on X
const offscreen = new IntersectionObserver((es) => es.forEach((e) => {
  if (e.intersectionRatio < 0.25 && !e.target.paused) e.target.pause();
}), { threshold: [0, 0.25] });
for (const e of ['play', 'playing', 'pause', 'seeked', 'ratechange', 'durationchange']) {
  document.addEventListener(e, (ev) => { if (ev.target === NP.el && !BG.on) position(ev.target); }, true);
  bgAudio.addEventListener(e, () => { if (BG.on && NP.el === BG.v) position(bgAudio); });
}
document.addEventListener('visibilitychange', () => {
  if (document.hidden) {   // the lock pauses it (iOS may not have yet); Play on the lock screen goes on
    if (BG.back) { clearTimeout(BG.timer); BG.back = 0; }
    BG.going = false;
    BG.v?.pause();
    settle();
  } else if (BG.on) giveBack();
});
function postMedia(p) {   // 2 to 4 photos sit in a grid, as on X
  const photos = p.media.slice(0, 4);
  if (photos.length < 2 || photos.some((m) => m.type !== 'photo')) return p.media.length ? mediaItem(p, 0) : '';
  return `<div class="feed-media feed-grid n${photos.length}">${photos.map((m, n) => `<button data-fmedia="${esc(p.id)}" data-n="${n}"${p.quoted ? ' data-fq' : ''}
    aria-label="Open photo"><img src="${mediaSrc(m.url, 'small')}" alt="${esc(m.alt)}" loading="lazy"></button>`).join('')}</div>`;
}
function linkCard(l) {   // X's link card: a big picture with the title on it, or a small card without one
  const title = esc(l.title || l.url.replace(/^https?:\/\//, ''));
  if (l.image) return `<a class="feed-card" href="${esc(l.url)}" target="_blank" rel="noopener"><img src="${mediaSrc(l.image)}" alt="" loading="lazy">
    <span class="t">${title}</span></a><div class="feed-from">From ${esc(l.domain)}</div>`;
  return `<a class="feed-link" href="${esc(l.url)}" target="_blank" rel="noopener"><span class="ico">${FI.link}</span>
    <div><small>${esc(l.domain)}</small><b>${title}</b></div></a>`;
}
// A quoted or linked post, shown in place: author, text and media. A tap opens it on its own page in Milo, as on X
// (openPostView); a photo opens full screen, a video plays here.
function quoteCard(q, pid) {
  return `<div class="feed-quote" data-fquote>
    <div class="qb"><div class="qh">${q.avatar ? `<img class="feed-av xs" src="${mediaSrc(q.avatar)}" alt="" loading="lazy">` : ''}<b>${esc(q.name)}</b> @${esc(q.handle)}</div>
      ${q.text ? `<p class="clamp" dir="auto">${esc(q.text)}</p>` : ''}</div>
    ${postMedia({ ...q, id: pid, media: q.media || [], quoted: true })}</div>`;
}
const quoteUrl = (q) => q.url || `https://x.com/${q.handle}/status/${q.id}`;
// The quoted post of post pid on its own page: who, all its text and media, when, and the same counts row as a post
// in the feed. Posts read before quotes kept their time and counts show without them.
// from: the post that quotes it. Back lands on that post where it was on screen (backToPost).
function openPostView(pid, from) {
  const q = feedPost(pid)?.quote;
  if (!q) return;
  playingVideo()?.pause();
  const sc = from && scrollerOf(from);
  F.pv = sc ? { pid, el: from, sc, n: $$(`[data-pid="${CSS.escape(pid)}"]`, sc).indexOf(from), y: sc.scrollTop,
    top: from.getBoundingClientRect().top - sc.getBoundingClientRect().top } : { pid };
  // a history entry, so the browser's back (and Safari's edge swipe) closes it too
  if (!history.state?.pv) history.pushState({ pv: 1 }, '', location.href);
  const when = q.created ? new Date(q.created * 1000) : null;
  const time = when ? `${when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} · ${when.toLocaleDateString([], { month: 'short', day: 'numeric', year: 'numeric' })}` : '';
  $('#pvBody').innerHTML = `<article class="pv-post" data-pid="${esc(pid)}">
    <div class="pv-who">${q.avatar ? `<img class="feed-av" src="${mediaSrc(q.avatar)}" alt="">` : ''}<div><b>${esc(q.name)}</b><span>@${esc(q.handle)}${q.created ? ` · ${ago(q.created)}` : ''}</span></div></div>
    ${q.text ? `<p class="pv-text" dir="auto">${linkify(q.text)}</p>` : ''}
    ${postMedia({ ...q, id: pid, media: q.media || [], quoted: true })}
    ${time ? `<div class="pv-time">${time}</div>` : ''}
    ${feedStats(q, true)}
    <div class="feed-actions"><a class="feed-btn" href="${esc(quoteUrl(q))}" target="_blank" rel="noopener">${FI.out}Open in X</a>
      <button class="feed-btn ask" data-fask-quote="${esc(pid)}">${FI.spark}Ask Milo</button></div></article>`;
  const v = $('#postView');
  v.classList.remove('out'); v.style.translate = ''; v.hidden = false; $('#pvBody').scrollTop = 0;
}
// how: 'back' (the button, a swipe, Escape) also takes its history entry; 'pop' came from the history itself;
// anything else (a tap on an alert, Ask Milo) leaves the entry, as the page moves on to a chat at once.
function closePostView(how) {
  const v = $('#postView');
  if (v.hidden || v.classList.contains('out')) return;
  if (history.state?.pv) { if (how === 'back') history.back(); else if (how !== 'pop') history.replaceState(null, '', location.href); }
  $$('#pvBody video').forEach((m) => m.pause());
  // the feed comes back under the sliding page already in place, on the post that quotes it
  const pv = F.pv; F.pv = null;
  if (F.stale) { F.stale = false; renderFeed(); }
  backToPost(pv);
  v.style.translate = ''; v.classList.remove('dragging'); v.classList.add('out');
  setTimeout(() => { v.hidden = true; v.classList.remove('out'); $('#pvBody').innerHTML = ''; }, 220);
}
addEventListener('popstate', () => { if (!history.state?.pv) closePostView('pop'); });
addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#postView').hidden && $('#mediaView').hidden) closePostView('back'); });
// Milo's own pages (a preview Milo links in a chat, like /reaction-preview.html) open over the app in a frame.
// A link took the whole app to that page, and its Back loaded the app again, splash and all (2026-10-21).
// Now the app stays alive under it: back (the page's own button, a swipe, Escape) is instant and keeps the chat.
function appPage(href) {
  let u; try { u = new URL(href, location.href); } catch { return null; }
  if (u.origin !== location.origin || !/\.html?$/i.test(u.pathname) || /^\/(api|preview)\//.test(u.pathname) || /^\/(index\.html)?$/.test(u.pathname)) return null;
  return u.href;
}
function openPageView(url) {
  if (!history.state?.web) history.pushState({ web: 1 }, '', location.href);   // the browser's back closes it too
  const v = $('#pageView');
  $('#pageFrame').src = url;
  v.classList.remove('out'); v.hidden = false;
}
function closePageView(how) {   // how: as closePostView
  const v = $('#pageView');
  if (v.hidden || v.classList.contains('out')) return;
  if (history.state?.web) { if (how === 'back') history.back(); else if (how !== 'pop') history.replaceState(null, '', location.href); }
  v.classList.add('out');
  setTimeout(() => { v.hidden = true; v.classList.remove('out'); $('#pageFrame').src = 'about:blank'; }, 220);
}
document.addEventListener('click', (e) => {
  const a = e.target.closest?.('a[href]');
  if (!a || e.defaultPrevented || e.metaKey || e.ctrlKey || e.shiftKey || e.altKey || a.hasAttribute('download')) return;
  const url = appPage(a.getAttribute('href'));
  if (!url) return;
  e.preventDefault();
  openPageView(url);
}, true);
addEventListener('message', (e) => {   // the page's own Back button
  if (e.origin === location.origin && e.data === 'milo:back' && e.source === $('#pageFrame').contentWindow) closePageView('back');
});
addEventListener('popstate', () => { if (!history.state?.web) closePageView('pop'); });
addEventListener('keydown', (e) => { if (e.key === 'Escape' && !$('#pageView').hidden) closePageView('back'); });
function scrollerOf(el) {
  for (let e = el.parentElement; e; e = e.parentElement) if (/auto|scroll/.test(getComputedStyle(e).overflowY)) return e;
  return null;
}
// The post keeps its place on screen. A redraw while the page was open has a new element for it (the same
// one of its copies: a post can be in the brief and in Top posts); with no post left, the old offset.
function backToPost(pv) {
  if (!pv?.sc?.isConnected) return;
  const sc = pv.sc, el = pv.el.isConnected ? pv.el : $$(`[data-pid="${CSS.escape(pv.pid)}"]`, sc)[Math.max(0, pv.n)];
  const y = el ? sc.scrollTop + el.getBoundingClientRect().top - sc.getBoundingClientRect().top - pv.top : pv.y;
  if (Math.abs(sc.scrollTop - y) > 1) sc.scrollTop = y;   // set only when it moved: on iOS a set stops a fling
}
{   // back with a swipe right, from the edge or anywhere on the page, as on X. Up and down still scroll it;
  // a video's controls and anything that scrolls sideways keep their own swipes.
  let drag = null;
  const v = $('#postView');
  const sideways = (el) => {
    for (let e = el; e && e !== v; e = e.parentElement)
      if (e.scrollWidth > e.clientWidth + 1 && /auto|scroll/.test(getComputedStyle(e).overflowX)) return true;
    return false;
  };
  v.addEventListener('touchstart', (e) => {
    const t = e.touches[0];
    drag = e.touches.length === 1 && !v.classList.contains('out') && !e.target.closest('video, audio, input, textarea')
      && !sideways(e.target) ? { x: t.clientX, y: t.clientY, dx: 0, at: performance.now(), moving: false } : null;
  }, { passive: true });
  v.addEventListener('touchmove', (e) => {
    if (!drag) return;
    const t = e.touches[0], dx = t.clientX - drag.x, dy = t.clientY - drag.y;
    if (!drag.moving) {
      if (Math.abs(dx) < 10 && Math.abs(dy) < 10) return;
      if (dx <= 0 || Math.abs(dx) < Math.abs(dy) * 1.2) { drag = null; return; }   // a scroll, or a swipe left
      drag.moving = true; v.classList.add('dragging');
    }
    e.preventDefault();   // the page doesn't scroll while it slides
    drag.dx = Math.max(0, dx); drag.v = drag.dx / Math.max(1, performance.now() - drag.at);
    v.style.translate = `${drag.dx}px 0`;
  }, { passive: false });
  const end = () => {
    if (!drag) return;
    const d = drag; drag = null;
    if (!d.moving) return;
    v.classList.remove('dragging');
    if (d.dx > Math.min(120, innerWidth / 3) || (d.dx > 40 && d.v > 0.5)) closePostView('back'); else v.style.translate = '';
  };
  v.addEventListener('touchend', end);
  v.addEventListener('touchcancel', end);
}
function voteBtns(pid) {   // quiet like and dislike, kept to tune the feed later
  const v = F.data?.votes?.[pid];
  return `<span class="feed-vote">${[['like', 'Like', FI.up], ['dislike', 'Dislike', FI.down]].map(([k, label, icon]) =>
    `<button data-fvote="${k}" class="${v === k ? 'on' : ''}" aria-label="${label}" aria-pressed="${v === k}">${icon}</button>`).join('')}</span>`;
}
async function votePost(b) {   // a second tap takes the vote back
  const pid = b.closest('[data-pid]').dataset.pid, votes = (F.data.votes ||= {}), was = votes[pid] || '';
  const v = was === b.dataset.fvote ? '' : b.dataset.fvote;
  const show = (x) => {
    if (x) votes[pid] = x; else delete votes[pid];
    $$(`[data-pid="${CSS.escape(pid)}"] [data-fvote]`).forEach((e) => { e.classList.toggle('on', e.dataset.fvote === x); e.setAttribute('aria-pressed', e.dataset.fvote === x); });
  };
  show(v);
  try { await api('/api/feed/vote', { method: 'POST', body: { post: pid, vote: v, tab: F.tab } }); }
  catch (e) { show(was); toast(e.message); }
}
// Replies, reposts, likes, views and bookmarks, as a post shows them on X. Bookmarks only when X sent them.
// known: a quoted post's page, where a count it lacks (read before quotes kept them, or from X's embed data) is left out.
function feedStats(p, known) {
  const s = [['replies', 'reply'], ['reposts', 'rt'], ['likes', 'like'], ['views', 'views'], ['bookmarks', 'mark']]
    .filter(([k]) => p[k] || (!known && k !== 'bookmarks'))
    .map(([k, i]) => `<span data-stat="${k}">${FI[i]}${fmtCount(p[k])}</span>`).join('');
  return s ? `<div class="feed-stats">${s}</div>` : '';
}
function postCard(p) {
  return `<article class="feed-post" data-pid="${esc(p.id)}">
    ${p.reposted_by ? `<div class="feed-rt"><span class="g">${FI.rt}</span>@${esc(p.reposted_by)} reposted</div>` : ''}
    <div class="fp"><img class="feed-av" src="${mediaSrc(p.avatar)}" alt="" loading="lazy"><div class="fp-body">
      <div class="feed-who"><b>${esc(p.name)}</b><span class="h">@${esc(p.handle)}</span><span class="d">· ${ago(p.created)}</span>
        <button class="feed-more" data-fmore="${esc(p.id)}" aria-label="More">${FI.more}</button></div>
      ${p.text ? `<p class="feed-text clamp" dir="auto" data-fclamp>${linkify(p.text)}</p>` : ''}
      ${postMedia(p)}
      ${p.link && !p.media.length ? linkCard(p.link) : ''}
      ${p.quote ? quoteCard(p.quote, p.id) : ''}
      ${feedStats(p)}
      <div class="feed-actions"><a class="feed-btn" href="${esc(p.url)}" target="_blank" rel="noopener">${FI.out}Open in X</a>
        <button class="feed-btn ask" data-fask="${esc(p.id)}">${FI.spark}Ask Milo</button>${voteBtns(p.id)}</div>
    </div></div>
  </article>`;
}
function briefLine(b, i, posts) {   // headline, summary, then its photo or video under them, as in a post on X
  const p = b.media && posts[b.media.post], m = p && p.media[b.media.n];
  const note = m ? `${m.type !== 'photo' ? 'Video' : b.media.chart ? 'Chart' : 'Photo'} from @${esc(p.handle)}` : '';
  return `<li>${b.title ? `<b class="feed-hl">${esc(b.title)}</b>` : ''}${b.text ? `<p>${esc(b.text)}</p>` : ''}
    ${m ? mediaItem(p, b.media.n, b.media.chart && m.type === 'photo') : ''}
    <div class="meta"><button class="feed-src" data-fsrc="${i}">${FI.posts}${plural(b.posts.length, 'post')}</button>${note ? `<span>${note}</span>` : ''}</div></li>`;
}
function renderFeedDot() {
  const unread = !!F.data?.generated && F.data.generated > +store.get('feedSeen', 0) && S.tab !== 'feed';
  $('#tabbar [data-tab=feed] .tab-dot').hidden = !unread;
  const b = $('#tabs [data-tab=feed]');
  b.querySelector('.unread-dot')?.remove();
  if (unread) b.insertAdjacentHTML('beforeend', '<span class="unread-dot"></span>');
}
function renderFeed() {
  if (F.pv) { F.stale = true; return; }   // not under an open post: back must find the feed as it was (closePostView draws it)
  $$('#feedSeg button').forEach((b) => b.classList.toggle('on', b.dataset.ftab === F.tab));
  const box = $('#feedBody'), d = F.data, name = esc(S.settings.assistant_name || 'Milo');
  if (!d) { box.innerHTML = '<div class="thinking-row"><span class="spin"></span>Loading</div>'; return; }
  const st = d.status, tab = d.tabs[F.tab];
  let html = '';
  if (F.busy) html += `<div class="thinking-row"><span class="spin"></span>${name} is reading your X feed…</div>`;
  else if (st.state === 'signed_out') html += `<div class="feed-alert"><b>${name} is not logged in to X</b><p>Log in once in ${name}'s browser. Then ${name} can read your feed.</p>
    <div class="btns"><button class="small-btn dark" data-flogin>Log in to X</button><button class="small-btn" data-frefresh>Try again</button></div></div>`;
  else if (st.state === 'error' || st.state === 'waiting') html += `<div class="feed-alert"><b>${st.state === 'waiting' ? 'Not read yet' : 'Could not read your feed'}</b><p>${esc(st.detail)}</p>
    <div class="btns"><button class="small-btn" data-frefresh>Try again</button></div></div>`;
  if (!d.settings[F.tab]) { box.innerHTML = html + `<div class="empty-state">${TAB_NAMES[F.tab]} is off. Turn it on in Edit.</div>`; return; }
  if (!tab) { box.innerHTML = html + (F.busy || st.state === 'signed_out' ? '' : '<div class="empty-state">No brief yet. Tap Refresh.<br><button class="small-btn" data-frefresh style="margin-top:12px">Refresh</button></div>'); return; }
  const when = new Date(tab.generated * 1000);
  const day = when.toDateString() === new Date().toDateString() ? '' : `${when.toLocaleDateString([], { month: 'short', day: 'numeric' })}, `;
  html += `<div class="feed-meta"><span class="st"><i></i>Updated ${day}${when.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })} · ${tab.read} posts read</span>
    <button class="icon-btn" data-frefresh aria-label="Refresh"${F.busy ? ' disabled' : ''}>${FI.refresh}</button></div>`;
  html += `<div class="feed-brief"><div class="feed-brief-head"><span>Brief</span>${tab.brief.length ? `<button class="icon-btn ${F.speaking ? 'on' : ''}" data-flisten aria-label="Listen">${ICON.speaker}</button>` : ''}</div>
    ${tab.brief.length ? `<ul>${tab.brief.map((b, i) => briefLine(b, i, tab.posts)).join('')}</ul>` : '<div class="none">Nothing in this feed matched what you want to see.</div>'}</div>`;
  const top = tab.top.filter((t) => tab.posts[t.post] && !muted(tab.posts[t.post]));
  if (top.length) html += `<div class="feed-label">Top posts<span>${top.length}</span></div>` + top.map((t) => postCard(tab.posts[t.post])).join('');
  // a video that plays, or that a lock paused, stays through the redraw (in the same task, so it never pauses)
  // A post can show the same video twice (in the brief and in Top posts): it goes back to its own place, not the first.
  const keep = playingVideo() || BG.v, twins = () => $$('#feedBody video[data-vpid]').filter((v) => v.src === keep.src);
  const at = keep ? twins().indexOf(keep) : -1;
  box.innerHTML = html;
  if (keep) twins()[Math.max(0, at)]?.replaceWith(keep);
  offscreen.disconnect();
  $$('#feedBody video[data-vpid]').forEach((v) => offscreen.observe(v));
  if (BG.v && !BG.v.isConnected) {   // its post is gone: so are its sound and its lock-screen buttons
    BG.going = false; settle();
    clearNowPlaying(BG.v); BG.v = null;
  }
}
async function loadFeed() {
  try {
    const r = await api('/api/feed');
    F.data = r; F.busy = r.busy || false;
  } catch (e) {   // a failed reload leaves the feed you are reading on screen
    if (S.tab === 'feed' && !F.data) $('#feedBody').innerHTML = `<div class="empty-state">${esc(e.message)}</div>`;
    return;
  }
  if (S.tab === 'feed') { store.set('feedSeen', String(F.data.generated)); renderFeed(); }
  renderFeedDot();
}
async function refreshFeed() {
  F.busy = true; renderFeed();
  // not started: the Mac sends no "done", so stop the spinner here
  await api('/api/feed/refresh', { method: 'POST' }).catch((e) => { F.busy = false; if (S.tab === 'feed') renderFeed(); toast(e.message); });
}
function askAbout(text) { switchTab('chat'); newChat(); sendPrompt(text, false); }
// AI: why it matters for the user's work. Politics: the background, from more than one side. Following: any topic.
const ASK_WHY = { politics: ': the background, and what each side says', foryou: ', and why it matters for my work', following: ', and why it matters to me' };
const askLead = (what) => `Tell me more about this ${what} from my X feed${ASK_WHY[F.tab] || ''}.`;
function askPost(p) {
  askAbout(`${askLead('post')}\n\n@${p.handle} (${p.name}): "${p.text}"${p.quote ? `\nQuoting @${p.quote.handle}: "${p.quote.text}"` : ''}${p.link ? `\nLink: ${p.link.url}` : ''}\n${p.url}`);
}
// The posts behind a brief line. A post is not a link: a tap on its text (to read or select it) opened X
// (2026-10-26). Only its Open in X button goes there; with one post it sits next to Ask Milo.
function openSources(i) {
  const tab = F.data.tabs[F.tab], b = tab.brief[i];
  F.line = b;
  const posts = b.posts.map((id) => tab.posts[id]).filter(Boolean), one = posts.length === 1;
  const openX = (p) => `<a class="feed-btn" href="${esc(p.url)}" target="_blank" rel="noopener">${FI.out}Open in X</a>`;
  $('#feedSourcesTitle').textContent = `From ${plural(b.posts.length, 'post')}`;
  $('#feedSourcesBody').innerHTML = `<div class="feed-sheet-text">${b.title ? `<b class="feed-hl">${esc(b.title)}</b>` : ''}${esc(b.text)}</div>` + posts.map((p) =>
    `<div class="feed-row"><img class="feed-av" src="${mediaSrc(p.avatar)}" alt="" loading="lazy">
      <div class="tx"><div class="h"><b>${esc(p.name)}</b> @${esc(p.handle)} · ${ago(p.created)}</div>${esc(p.text.length > 280 ? p.text.slice(0, 279) + '…' : p.text)}
      <div class="s">${fmtCount(p.likes)} likes${p.media.length ? ` · ${p.media[0].type === 'photo' ? 'photo' : 'video'}` : ''}</div>${one ? '' : `<div class="feed-actions">${openX(p)}</div>`}</div></div>`).join('') +
    `<div class="feed-actions" style="margin:12px 0 6px">${one ? openX(posts[0]) : ''}<button class="feed-btn ask" data-fask-line>${FI.spark}Ask Milo about this</button></div>`;
  openSheet('feedSources');
}
function openMedia(id, n, q) {   // q: the media of the post it quotes
  const p = shownPost(id, q);
  if (!p) return;
  $('#mediaStage').innerHTML = p.media.map((m) => m.type !== 'photo' && m.video
    ? `<video src="${esc(m.video)}" poster="${mediaSrc(m.url, 'medium')}" controls playsinline preload="metadata"></video>`
    : `<div class="media-zoom"><img src="${mediaSrc(m.url, 'large')}" alt="${esc(m.alt)}"></div>`).join('');
  MZ.zoom = 1;
  $('#mediaFoot').innerHTML = `<div class="h">${p.avatar ? `<img class="feed-av sm" src="${mediaSrc(p.avatar)}" alt="">` : ''}<b>${esc(p.name)}</b><span>@${esc(p.handle)}${p.created ? ` · ${ago(p.created)}` : ''}</span></div>
    ${p.text ? `<p>${esc(p.text)}</p>` : ''}
    <div class="feed-actions">${q ? '' : `<a class="feed-btn" href="${esc(p.url)}" target="_blank" rel="noopener">${FI.out}Open in X</a>`}<button class="feed-btn" data-fask="${esc(id)}">${FI.spark}Ask Milo</button></div>`;
  const count = () => {
    const i = Math.round($('#mediaStage').scrollLeft / ($('#mediaStage').clientWidth || 1));
    $('#mediaCount').textContent = p.media.length > 1 ? `${i + 1} of ${p.media.length}` : '';
    // a video you swipe away from pauses, as one you scroll past in the feed
    [...$('#mediaStage').children].forEach((el, k) => { if (k !== i && el.tagName === 'VIDEO' && !el.paused) el.pause(); });
  };
  $('#mediaView').hidden = false;
  $('#mediaView').dataset.pid = id;   // for the lock screen
  $('#mediaView').dataset.fq = q ? '1' : '';
  $('#mediaStage').scrollLeft = n * $('#mediaStage').clientWidth;
  $('#mediaStage').onscroll = count; count();
  const shown = $('#mediaStage').children[n];
  if (shown?.tagName === 'VIDEO') shown.play().catch(() => {});
}
function closeMedia() {
  $$('#mediaStage video').forEach((v) => { v.pause(); clearNowPlaying(v); });
  const view = $('#mediaView'), stage = $('#mediaStage');
  view.hidden = true; stage.innerHTML = '';
  view.classList.remove('zoomed', 'pulling'); view.style.background = ''; stage.style.transform = stage.style.transition = '';
}
$('#mediaClose').onclick = closeMedia;
// Pinch or double-tap a photo to zoom, as in Photos. Zoomed, one finger moves around the photo instead of to the next.
const MZ = { zoom: 1, pinch: 0, tap: 0 };
function mzZoomTo(box, z, cx, cy) {   // keeps the point at (cx, cy) under your fingers
  z = Math.min(5, Math.max(1, z));
  const r = box.getBoundingClientRect(), old = MZ.zoom;
  const fx = (cx ?? r.left + r.width / 2) - r.left, fy = (cy ?? r.top + r.height / 2) - r.top;
  const x = box.scrollLeft + fx, y = box.scrollTop + fy;
  MZ.zoom = z;
  box.firstElementChild.style.width = box.firstElementChild.style.height = `${z * 100}%`;
  $('#mediaView').classList.toggle('zoomed', z > 1);
  box.scrollLeft = x * z / old - fx; box.scrollTop = y * z / old - fy;
}
$('#mediaStage').addEventListener('click', (e) => {
  const box = e.target.closest('.media-zoom');
  if (!box) return;
  if (Date.now() - MZ.tap > 320) { MZ.tap = Date.now(); return; }
  MZ.tap = 0;
  mzZoomTo(box, MZ.zoom > 1 ? 1 : 2.5, e.clientX, e.clientY);
});
$('#mediaStage').addEventListener('touchmove', (e) => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false });   // a pinch doesn't swipe
// Pull the picture down (or up) to close it, as on X. Sideways goes to the next one.
(() => {
  const view = $('#mediaView'), stage = $('#mediaStage');
  let d = null;
  view.addEventListener('touchstart', (e) => {
    if (d?.moving) return;   // another finger during a pull
    const t = e.touches[0];
    d = MZ.zoom > 1 || e.touches.length > 1 ? null : { x: t.clientX, y: t.clientY, dy: 0, v: 0, at: performance.now(), moving: false };
  }, { passive: true });
  view.addEventListener('touchmove', (e) => {
    if (!d) return;
    const t = e.touches[0], dx = t.clientX - d.x, dy = t.clientY - d.y, now = performance.now();
    if (!d.moving) {   // decided on the first move: iOS won't let a scroll that started be stopped
      if (e.touches.length > 1 || Math.abs(dy) <= Math.abs(dx)) { d = null; return; }
      d.moving = true; view.classList.add('pulling');
    }
    e.preventDefault();
    d.v = (dy - d.dy) / Math.max(1, now - d.at); d.dy = dy; d.at = now;
    stage.style.transform = `translateY(${dy}px)`;
    view.style.background = `rgba(0,0,0,${Math.max(0.2, 1 - Math.abs(dy) / 500)})`;
  }, { passive: false });
  const end = () => {
    const g = d; d = null;
    if (!g?.moving) return;
    stage.style.transition = 'transform .22s ease-out';
    view.style.transition = 'background .22s';
    if (Math.abs(g.dy) > 110 || Math.abs(g.v) > 0.6) {   // far or fast enough: it goes on off the screen
      stage.style.transform = `translateY(${Math.sign(g.dy || g.v) * innerHeight}px)`;
      view.style.background = 'rgba(0,0,0,0)';
      setTimeout(() => { view.style.transition = ''; closeMedia(); }, 220);
    } else {
      stage.style.transform = ''; view.style.background = ''; view.classList.remove('pulling');
      setTimeout(() => { stage.style.transition = view.style.transition = ''; }, 220);
    }
  };
  view.addEventListener('touchend', end);
  view.addEventListener('touchcancel', end);
})();
// Like X: the For you / Following switch stays on top, slides away while you scroll down and comes back when you scroll up
$('#feedScroll').addEventListener('scroll', (e) => {
  const box = e.target, y = box.scrollTop, seg = $('#feedSegBar'), head = $('#view-feed .view-head');
  if (y < 0 || y > box.scrollHeight - box.clientHeight) return;   // iOS bounce at either end
  const stuck = y > head.offsetTop + head.offsetHeight;
  if (!stuck) { seg.classList.remove('away'); F.lastY = y; return; }
  if (Math.abs(y - F.lastY) < 6) return;   // small moves are finger jitter
  seg.classList.toggle('away', y > F.lastY);
  F.lastY = y;
}, { passive: true });
$('#feedSeg').addEventListener('click', (e) => {
  const b = e.target.closest('[data-ftab]');
  if (b) { F.tab = b.dataset.ftab; store.set('feedTab', F.tab); renderFeed(); $('#feedScroll').scrollTop = 0; }
});
document.addEventListener('click', (e) => {
  const t = e.target;
  if (!t.closest('#view-feed, #feedSources, #mediaView, #postView')) return;
  if (t.closest('a')) return;   // links open in X or the browser
  const media = t.closest('[data-fmedia]');
  if (media) return openMedia(media.dataset.fmedia, +media.dataset.n, 'fq' in media.dataset);
  const ask = t.closest('[data-fask]');
  if (ask) { const p = feedPost(ask.dataset.fask); closeMedia(); return p && askPost(p); }
  const vote = t.closest('[data-fvote]');
  if (vote) return votePost(vote);
  if (t.closest('[data-fask-line]')) {
    const tab = F.data.tabs[F.tab], b = F.line; closeSheet('feedSources');
    return askAbout(`${askLead('story')}\n\n${[b.title, b.text].filter(Boolean).join('\n')}\n\nPosts:\n${b.posts.map((id) => tab.posts[id]).filter(Boolean).map((p) => `- @${p.handle}: ${p.url}`).join('\n')}`);
  }
  const src = t.closest('[data-fsrc]');
  if (src) return openSources(+src.dataset.fsrc);
  const more = t.closest('[data-fmore]');
  if (more) {
    const p = feedPost(more.dataset.fmore); F.menu = p;
    $('#feedPostMenuTitle').textContent = `@${p.handle}`; $('#feedMuteBtn').textContent = `Mute @${p.handle}`;
    return openSheet('feedPostMenu');
  }
  if (t.closest('[data-frefresh]')) return refreshFeed();
  if (t.closest('[data-flogin]')) return openX();
  if (t.closest('#pvBack')) return closePostView('back');
  const askq = t.closest('[data-fask-quote]');
  if (askq) {
    const q = feedPost(askq.dataset.faskQuote)?.quote; closePostView();
    return q && askAbout(`${askLead('post')}\n\n@${q.handle} (${q.name}): "${q.text}"\n${quoteUrl(q)}`);
  }
  const quote = t.closest('[data-fquote]');
  if (quote && !t.closest('video')) { const post = quote.closest('[data-pid]'); return openPostView(post.dataset.pid, post); }
  const clamp = t.closest('[data-fclamp]');
  if (clamp) return clamp.classList.toggle('clamp');
  if (t.closest('[data-flisten]')) {
    if (F.speaking) { F.speaking = false; stopSpeaking(); return renderFeed(); }
    F.speaking = true; renderFeed(); unlockAudio();
    const tab = F.data.tabs[F.tab];
    speak(`Your ${TAB_NAMES[F.tab]} brief.\n\n` + tab.brief.map((b) => [b.title, b.text].filter(Boolean).join('. ')).join('\n\n')).finally(() => { F.speaking = false; if (S.tab === 'feed') renderFeed(); });
  }
});
$('#feedPostMenu').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-fact]'), p = F.menu;
  if (!b || !p) return;
  closeSheet('feedPostMenu');
  if (b.dataset.fact === 'copy') { navigator.clipboard?.writeText(p.url).then(() => toast('Link copied'), () => toast(p.url)); return; }
  try {
    await api('/api/feed/feedback', { method: 'POST', body: { post: p.id, kind: b.dataset.fact, tab: F.tab } });
    if (b.dataset.fact === 'mute') { F.data.settings.muted = [...F.data.settings.muted, p.handle]; renderFeed(); toast(`Muted @${p.handle}`); }
    else toast('Got it. The next brief will have fewer posts like this.');
  } catch (err) { toast(err.message); }
});
async function openX() {   // log in to X in Milo's browser: the user types it in the live view
  closeSheet('feedEdit');
  try {
    await api('/api/browser/control', { method: 'POST', body: { action: 'take' } });
    await api('/api/browser/navigate', { method: 'POST', body: { url: 'https://x.com/login' } });
  } catch (e) { toast(e.message); }
  BV.open();
}
function setFeedTop(v) { $$('#feedTopSeg button').forEach((b) => b.classList.toggle('on', +b.dataset.v === v)); $('#feedForm').dataset.top = v; }
$('#feedEditBtn').onclick = () => {
  const d = F.data;
  if (!d) return;
  const f = $('#feedForm'), s = d.settings, signedOut = d.status.state === 'signed_out';
  FEED_PROMPTS.forEach((k) => { f[k].value = s[k] || ''; }); $('#feedErr').textContent = '';
  $$('[data-ftoggle]').forEach((t) => { t.classList.toggle('on', !!s[t.dataset.ftoggle]); t.setAttribute('aria-checked', !!s[t.dataset.ftoggle]); });
  setFeedTop(s.top);
  $('#feedXState').textContent = signedOut ? 'Not logged in' : d.status.state === 'new' ? "In Milo's browser" : "Logged in, in Milo's browser";
  $('#feedXBtn').textContent = signedOut ? 'Log in' : 'Open browser';
  $('#feedMutedRow').hidden = !s.muted.length;
  $('#feedMuted').textContent = s.muted.map((h) => '@' + h).join(', ');
  openSheet('feedEdit');
};
$('#feedForm').addEventListener('click', (e) => {
  const t = e.target.closest('[data-ftoggle]');
  if (t) { t.classList.toggle('on'); t.setAttribute('aria-checked', t.classList.contains('on')); }
  const v = e.target.closest('#feedTopSeg [data-v]');
  if (v) setFeedTop(+v.dataset.v);
});
$('#feedXBtn').onclick = openX;
$('#feedUnmute').onclick = async () => {
  try { await api('/api/feed/settings', { method: 'PUT', body: { muted: [] } }); F.data.settings.muted = []; $('#feedMutedRow').hidden = true; renderFeed(); }
  catch (err) { toast(err.message); }
};
$('#feedForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target, old = F.data.settings;
  const body = { top: +f.dataset.top };
  FEED_PROMPTS.forEach((k) => { body[k] = f[k].value; });
  $$('[data-ftoggle]').forEach((t) => { body[t.dataset.ftoggle] = t.classList.contains('on'); });
  await inFlight(f, async () => {
    try {
      const s = await api('/api/feed/settings', { method: 'PUT', body });
      F.data.settings = { ...old, ...s };
      document.activeElement?.blur(); closeSheet('feedEdit');
      // a new prompt, source or size needs a new brief
      if (FEED_PROMPTS.some((k) => s[k] !== old[k]) || s.top !== old.top || Object.keys(TAB_NAMES).some((k) => s[k] && !old[k])) refreshFeed(); else renderFeed();
    } catch (err) { $('#feedErr').textContent = err.message; }
  });
});

// ---------- goals ----------
const GOAL_SECTIONS = [['tracking', 'Tracking'], ['goal', 'Goals']];
async function loadGoals() {
  const box = $('#goalsList');
  try {
    S.goals = await api('/api/goals');
    if (!S.goals.length) { box.innerHTML = `<div class="empty-state">${ICON.check}<br>No goals yet. Tap New, or tell Milo what you are working toward.</div>`; return; }
    const row = (g) => `<div class="goal-row ${g.done ? 'done' : ''}" data-gid="${esc(g.id)}">
      <button class="goal-check" data-gtoggle aria-label="${g.done ? 'Mark not done' : 'Mark done'}">${g.done ? ICON.check : ''}</button>
      <div class="tx"><b>${esc(g.title)}</b>${g.note ? `<span>${esc(g.note)}</span>` : ''}</div>
      <button class="goal-more" data-gmore aria-label="More"><svg viewBox="0 0 24 24"><circle cx="12" cy="6" r="1.3" fill="currentColor"/><circle cx="12" cy="12" r="1.3" fill="currentColor"/><circle cx="12" cy="18" r="1.3" fill="currentColor"/></svg></button></div>`;
    let html = '';
    for (const [sec, label] of GOAL_SECTIONS) {
      const items = S.goals.filter((g) => g.section === sec && !g.done);
      if (items.length) html += `<div class="goal-section ${sec}"><i></i>${label}</div>` + items.map(row).join('');
    }
    const done = S.goals.filter((g) => g.done);
    if (done.length) html += '<div class="goal-section done"><i></i>Done</div>' + done.map(row).join('');
    box.innerHTML = html;
  } catch (e) { box.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; }
}
const goalOf = (el) => S.goals.find((g) => g.id === el.closest('[data-gid]').dataset.gid);
$('#goalsList').addEventListener('click', async (e) => {
  if (e.target.closest('[data-gtoggle]')) {
    const g = goalOf(e.target);
    await api(`/api/goals/${g.id}`, { method: 'PATCH', body: { done: !g.done } }).catch((err) => toast(err.message));
    return loadGoals();
  }
  if (e.target.closest('[data-gmore]')) {
    S.goal = goalOf(e.target);
    $('#goalActionsTitle').textContent = S.goal.title;
    $('[data-gact=move]').textContent = S.goal.section === 'goal' ? 'Move to Tracking' : 'Move to Goals';
    $('[data-gact=delete]').textContent = 'Delete'; delete $('[data-gact=delete]').dataset.armed;
    openSheet('goalActions');
  }
});
function openGoalForm(g) {
  const f = $('#goalForm');
  f.reset(); $('#goalErr').textContent = '';
  S.goalEdit = g || null;
  $('#goalSheetTitle').textContent = g ? 'Edit goal' : 'New goal';
  f.title.value = g?.title || ''; f.note.value = g?.note || '';
  setGoalSection(g?.section || 'goal');
  openSheet('goalSheet');
}
function setGoalSection(v) { $$('#goalSeg button').forEach((b) => b.classList.toggle('on', b.dataset.v === v)); $('#goalForm').dataset.section = v; }
$('#goalSeg').addEventListener('click', (e) => { const b = e.target.closest('[data-v]'); if (b) setGoalSection(b.dataset.v); });
$('#addGoalBtn').onclick = () => openGoalForm();
$('#goalForm').addEventListener('submit', async (e) => {
  e.preventDefault();
  const f = e.target, body = { title: f.title.value, note: f.note.value, section: f.dataset.section };
  await inFlight(f, async () => {
    try {
      if (S.goalEdit) await api(`/api/goals/${S.goalEdit.id}`, { method: 'PATCH', body }); else await api('/api/goals', { method: 'POST', body });
      document.activeElement?.blur(); closeSheet('goalSheet'); loadGoals();   // no keyboard Return into the closing form
    } catch (err) { $('#goalErr').textContent = err.message; }
  });
});
$('#goalActions').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-gact]');
  if (!b) return;
  const g = S.goal, act = b.dataset.gact;
  if (act === 'delete' && !(Date.now() - b.dataset.armed > 400)) {   // a double tap is not the second tap
    if (!b.dataset.armed) { b.dataset.armed = Date.now(); b.textContent = 'Tap again to delete'; }
    return;
  }
  closeSheet('goalActions');
  if (act === 'discuss') {   // a side chat about the goal, with the first words ready to send
    switchTab('chat'); newChat();
    input.value = `Let's talk about my goal "${g.title}".${g.note ? ` Where it stands: ${g.note}.` : ''} `;
    input.dispatchEvent(new Event('input')); setTimeout(focusBox, 320);
  } else if (act === 'edit') {
    openGoalForm(g);
  } else {
    if (act === 'move') await api(`/api/goals/${g.id}`, { method: 'PATCH', body: { section: g.section === 'goal' ? 'tracking' : 'goal' } }).catch((err) => toast(err.message));
    if (act === 'delete') await api(`/api/goals/${g.id}`, { method: 'DELETE' }).catch((err) => toast(err.message));
    loadGoals();
  }
});
$('#goalActions [data-gact=delete]').removeAttribute('data-armed');

// ---------- library ----------
function fmtSize(n) { return n < 1024 ? `${n} B` : n < 1048576 ? `${(n / 1024).toFixed(0)} KB` : `${(n / 1048576).toFixed(1)} MB`; }
async function loadLibrary() {
  const midnight = new Date().setHours(0, 0, 0, 0) / 1000;   // the phone's day, which can differ from the Mac's
  try {
    [S.libItems, S.libFavs, S.libToday] = await Promise.all([api('/api/library'), api('/api/library/favorites').catch(() => S.libFavs || []),
      api(`/api/library/today?since=${midnight}`)]);
    renderLibrary();
  } catch (e) { $('#libraryList').innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; }
}
// Folders like the Files app: the server sends every file with its path, and the open folder shows
// its subfolders first (newest first), then its files.
function renderLibrary() {
  if (S.libView === 'today') return renderToday();
  if (S.libView === 'fav') return renderFavorites();
  const box = $('#libraryList'), items = S.libItems || [];
  if (!items.length) { box.innerHTML = `<div class="empty-state">${ICON.file}<br>Nothing here yet. Ask Milo to make a document, a spreadsheet or an image.</div>`; return; }
  let dir = S.libDir || '';
  while (dir && !items.some((f) => f.path.startsWith(dir + '/'))) dir = dir.includes('/') ? dir.slice(0, dir.lastIndexOf('/')) : '';   // emptied
  S.libDir = dir;
  const prefix = dir ? dir + '/' : '', folders = new Map(), files = [];
  for (const f of items) {
    if (!f.path.startsWith(prefix)) continue;
    const rest = f.path.slice(prefix.length);
    if (!rest.includes('/')) { files.push(f); continue; }
    const name = rest.slice(0, rest.indexOf('/')), d = folders.get(name) || { name, count: 0, modified: 0 };
    d.count++; d.modified = Math.max(d.modified, f.modified); folders.set(name, d);
  }
  const parts = dir ? dir.split('/') : [];
  const crumbs = dir ? `<nav class="crumbs"><button data-dir="">Library</button>${parts.map((p, i) => `${ICON.chevron}${i === parts.length - 1
    ? `<b>${esc(p)}</b>` : `<button data-dir="${esc(parts.slice(0, i + 1).join('/'))}">${esc(p)}</button>`}`).join('')}</nav>` : '';
  box.innerHTML = crumbs + [...folders.values()].sort((a, b) => b.modified - a.modified).map((d) =>
    `<div class="item" data-dir="${esc(prefix + d.name)}"><div class="ic">${ICON.folder}</div>
      <div class="tx"><b>${esc(d.name)}</b><span>${d.count} ${d.count === 1 ? 'file' : 'files'} · ${esc(relTime(d.modified))}</span></div>
      <div class="acts lib-acts">${dlBtn(prefix + d.name, 'folder')}${starBtn(prefix + d.name, 'folder')}${ICON.chevron}</div></div>`).join('') + files.map((f) => {
    return `<div class="item" data-path="${esc(f.path)}"><div class="ic">${esc(extOf(f.name)) || ICON.file}</div>
      <div class="tx"><b>${esc(f.name)}</b><span>${esc(relTime(f.modified))} · ${fmtSize(f.size)}</span></div>
      <div class="acts">${dlBtn(f.path, 'file')}${starBtn(f.path, 'file')}<button data-del aria-label="Delete">${ICON.trash}</button></div></div>`;
  }).join('');
}
// Favorites: starred folders, then starred files, newest star first. The Mac keeps the list (/api/library/favorites),
// so it is the same on every device. A folder opens in place, in All files.
const extOf = (name) => (name.split('.').pop() || '').slice(0, 4).toUpperCase();
const libFolder = (p) => p.includes('/') ? p.slice(0, p.lastIndexOf('/')) : 'Library';
const isFav = (path, kind) => (S.libFavs || []).some((f) => f.path === path && f.kind === kind);
const dlBtn = (path, kind) => `<button data-dl="${kind}" data-dl-path="${esc(path)}" aria-label="Download">${ICON.download}</button>`;
// A file as it is, a folder as <folder>.zip. In a browser it is a link (the token rides in the URL, as for every Library
// file), so a big folder streams to disk. In the Home Screen app iOS opens such a link in its viewer in place of Milo,
// with no way back: there the file is fetched and handed to the share menu (Save to Files), and only one too big to
// hold in memory opens in a new window, which leaves Milo where it was.
const DL_MEM_MAX = 300 * 1048576;
const DL = { path: null, file: null, busy: null };   // the last one fetched: a second tap shares it at once
async function downloadItem(btn) {
  const { dlPath: path, dl: kind } = btn.dataset, q = `path=${encodeURIComponent(path)}`;
  let url = fileUrl(path, true), size = null;
  if (kind === 'folder') {
    try { size = (await api(`/api/library/zip?${q}&check=1`)).size; } catch (e) { return toast(e.message); }   // too large, empty or gone
    url = `/api/library/zip?${q}&token=${encodeURIComponent(S.token)}`;
  }
  if (!(isIOS && standalone)) {
    const a = Object.assign(document.createElement('a'), { href: url, download: '' });
    document.body.append(a); a.click(); a.remove();
    return;
  }
  const name = kind === 'folder' ? `${path.split('/').pop()}.zip` : path.split('/').pop();
  if (size > DL_MEM_MAX) return window.open(url, '_blank');
  let file = DL.path === `${kind}:${path}` ? DL.file : null;
  if (!file) {
    if (DL.busy) return toast('Still getting the last one…');
    DL.busy = path;
    try {
      // the file as the viewer gets it, so it keeps its type (a PDF stays a PDF in the share menu)
      const r = await fetch(kind === 'folder' ? `/api/library/zip?${q}` : `/api/library/file?${q}`, { headers: { Authorization: `Bearer ${S.token}` } });
      if (!r.ok) throw new Error(r.status === 413 ? 'The folder is too large to download.' : 'Could not get the file.');
      const total = +r.headers.get('content-length') || size;
      if (total > DL_MEM_MAX) { r.body?.cancel(); return window.open(url, '_blank'); }
      const parts = [], reader = r.body.getReader();
      let got = 0;
      for (;;) {
        const { done, value } = await reader.read();
        if (done) break;
        parts.push(value); got += value.length;
        if (got > DL_MEM_MAX) { reader.cancel(); return window.open(url, '_blank'); }
        if (total > 2 * 1048576) toast(`Getting ${name}… ${Math.min(99, Math.round(got / total * 100))}%`, 4000);
      }
      const type = kind === 'folder' ? 'application/zip' : (r.headers.get('content-type') || '').split(';')[0] || 'application/octet-stream';
      file = new File(parts, name, { type });
      Object.assign(DL, { path: `${kind}:${path}`, file });
    } catch (e) {
      return toast(e.message);
    } finally { DL.busy = null; }
  }
  try {
    if (navigator.canShare?.({ files: [file] })) { await navigator.share({ files: [file] }); return; }
  } catch (e) {
    if (e.name === 'AbortError') return;   // the menu was closed
    if (e.name === 'NotAllowedError') return toast('The file is ready now. Tap again.');   // it took too long to load
  }
  if ('download' in HTMLAnchorElement.prototype) {   // no share menu for files: save the copy
    const href = URL.createObjectURL(file);
    const a = Object.assign(document.createElement('a'), { href, download: name });
    document.body.append(a); a.click(); a.remove();
    setTimeout(() => URL.revokeObjectURL(href), 60000);
    return;
  }
  window.open(url, '_blank');
}
const starBtn = (path, kind) => `<button data-star="${kind}" data-star-path="${esc(path)}"${isFav(path, kind) ? ' class="on"' : ''} aria-label="Favorite">${ICON.star}</button>`;
function renderFavorites() {
  const box = $('#libraryList'), favs = S.libFavs || [];
  if (!favs.length) { box.innerHTML = `<div class="empty-state">${ICON.star}<br>No favorites yet. Tap the star on a file or folder to keep it here.</div>`; return; }
  box.innerHTML = [...favs.filter((f) => f.kind === 'folder'), ...favs.filter((f) => f.kind === 'file')].map((f) => f.kind === 'folder'
    ? `<div class="item" data-dir="${esc(f.path)}"><div class="ic">${ICON.folder}</div>
      <div class="tx"><b>${esc(f.name)}</b><span>${esc(libFolder(f.path))} · ${f.count} ${f.count === 1 ? 'file' : 'files'}</span></div>
      <div class="acts lib-acts">${dlBtn(f.path, 'folder')}${starBtn(f.path, 'folder')}${ICON.chevron}</div></div>`
    : `<div class="item" data-path="${esc(f.path)}"><div class="ic">${esc(extOf(f.name)) || ICON.file}</div>
      <div class="tx"><b>${esc(f.name)}</b><span>${esc(libFolder(f.path))} · ${esc(relTime(f.modified))}</span></div>
      <div class="acts">${dlBtn(f.path, 'file')}${starBtn(f.path, 'file')}</div></div>`).join('');
}
// Today: files added or changed since midnight, from every folder. The Mac sorts them by when they were added,
// not by the last change, so an old file edited today sits below the new ones.
function renderToday() {
  const box = $('#libraryList'), items = S.libToday || [];
  if (!items.length) { box.innerHTML = `<div class="empty-state">${ICON.clock}<br>Nothing new today.</div>`; return; }
  box.innerHTML = items.map((f) => `<div class="item" data-path="${esc(f.path)}"><div class="ic">${esc(extOf(f.name)) || ICON.file}</div>
      <div class="tx"><b>${esc(f.name)}</b><span>${esc(libFolder(f.path))} · ${esc(relTime(f.created))}</span></div>
      <div class="acts">${dlBtn(f.path, 'file')}${starBtn(f.path, 'file')}<button data-del aria-label="Delete">${ICON.trash}</button></div></div>`).join('');
}
async function toggleFav(btn) {   // the star fills at once; the list comes back from the Mac
  const { starPath: path, star: kind } = btn.dataset, on = !btn.classList.contains('on');
  btn.classList.toggle('on', on);
  try { S.libFavs = await api('/api/library/favorites', { method: 'PUT', body: { path, kind, on } }); } catch (e) { toast(e.message); }
  renderLibrary(); fvStarSync();
}
function setLibView(v) {
  S.libView = v;
  $$('#libSeg button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
}
setLibView('today');
$('#libSeg').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-v]');
  if (!b) return;
  setLibView(b.dataset.v); renderLibrary(); $('#view-library .scroll').scrollTop = 0;
});
$('#libraryList').addEventListener('click', async (e) => {
  const dl = e.target.closest('[data-dl]');
  if (dl) { e.stopPropagation(); return downloadItem(dl); }   // the row under it doesn't open
  const star = e.target.closest('[data-star]');
  if (star) return toggleFav(star);
  const to = e.target.closest('[data-dir]');
  if (to) { setLibView('all'); S.libDir = to.dataset.dir; renderLibrary(); $('#view-library .scroll').scrollTop = 0; return; }
  const row = e.target.closest('[data-path]');
  if (!row) return;
  if (e.target.closest('[data-del]')) {
    if (!armed(e.target.closest('[data-del]'))) return;
    await api(`/api/library/file?path=${encodeURIComponent(row.dataset.path)}`, { method: 'DELETE' }).catch((err) => toast(err.message));
    return loadLibrary();
  }
  const path = row.dataset.path;   // a starred or new file can be outside the newest 500 that the Library lists
  openFile(S.libItems?.find((f) => f.path === path) || S.libToday?.find((f) => f.path === path)
    || S.libFavs?.find((f) => f.kind === 'file' && f.path === path));
});

// ---------- file viewer ----------
// A Library file, full screen in the app. Photos, videos, PDFs (PDF.js, in web/vendor) and text show here. Word, Excel,
// PowerPoint, Pages and Numbers come as previews that Quick Look makes on the Mac. The share button hands the file to
// another app (Excel, Word, Files ...) through the iPhone's share menu.
const FV = { file: null, blob: null, blobP: null, zoom: 1, pinch: null, pdf: null, pdfTask: null, io: null, tap: 0 };
const TEXT_TYPES = /^(text\/|application\/(json|xml|yaml|x-yaml|toml|x-sh|javascript))/;
function fileKind(f) {
  const t = f.type || '';
  if (t === 'text/html' || t === 'application/xhtml+xml') return 'html';
  if (t.startsWith('image/')) return 'image';
  if (t.startsWith('video/')) return 'video';
  if (t.startsWith('audio/')) return 'audio';
  if (t === 'application/pdf') return 'pdf';
  if (TEXT_TYPES.test(t) || /\.(md|txt|log|csv|tsv|ya?ml|toml|ini|conf)$/i.test(f.name)) return 'text';
  return 'preview';
}
function fileBlob(f) {   // loaded once: the viewer and the share menu use the same copy
  return FV.blobP ||= fetch(fileUrl(f.path)).then((r) => { if (!r.ok) throw new Error('Could not load the file.'); return r.blob(); })
    .then((b) => { if (FV.file === f) FV.blob = b; return b; });
}
async function openFile(f) {
  closeFile();
  FV.file = f;
  const box = $('#fvBody'), kind = fileKind(f), url = fileUrl(f.path);
  $('#fvName').textContent = f.name;
  $('#fvMeta').textContent = `${relTime(f.modified)} · ${fmtSize(f.size)}`;
  $('#fvStar').dataset.starPath = f.path; fvStarSync();
  box.innerHTML = '<div class="fv-none"><span class="spin"></span></div>';
  $('#fileView').hidden = false;
  if (kind !== 'video' && kind !== 'audio' && f.size <= 40e6) fileBlob(f).catch(() => {});   // ready before you tap share
  try {
    if (kind === 'image') box.innerHTML = `<div class="fv-zoom fv-img"><img src="${url}" alt="${esc(f.name)}"></div>`;
    else if (kind === 'video') box.innerHTML = `<video class="fv-video" src="${url}" controls playsinline autoplay></video>`;
    else if (kind === 'audio') box.innerHTML = `<div class="fv-none"><div class="ic">${ICON.speaker}</div><b>${esc(f.name)}</b><audio src="${url}" controls autoplay></audio></div>`;
    else if (kind === 'html') box.innerHTML = `<iframe class="fv-frame" sandbox src="${url}"></iframe>`;   // no scripts
    else if (kind === 'pdf') await showPdf(f, await (await fileBlob(f)).arrayBuffer());
    else if (kind === 'text') {
      const text = await (await fileBlob(f)).text();
      if (FV.file === f) showText(f, text);   // not over the file you opened while this one loaded
    } else {
      box.innerHTML = '<div class="fv-none"><span class="spin"></span><p>Making a preview on your Mac</p></div>';
      const r = await api(`/api/library/preview?path=${encodeURIComponent(f.path)}`);
      if (FV.file !== f) return;
      if (r.type === 'text/html') box.innerHTML = `<iframe class="fv-frame" sandbox="allow-scripts" src="${esc(r.url)}"></iframe>`;
      else if (r.type === 'application/pdf') await showPdf(f, await (await fetch(r.url)).arrayBuffer());
      else if (r.type?.startsWith('image/')) box.innerHTML = `<div class="fv-zoom fv-img"><img src="${esc(r.url)}" alt=""></div>`;
      else noPreview(f);
    }
    // gone from the Mac (or unreadable): say so, rather than a blank screen
    if (FV.file === f) box.querySelector('img, video, audio')?.addEventListener('error', () => { if (FV.file === f) noPreview(f, 'Could not load the file.'); }, { once: true });
  } catch (e) { if (FV.file === f) noPreview(f, e.message); }
}
function noPreview(f, why) {
  const ext = (f.name.split('.').pop() || '').slice(0, 4).toUpperCase();
  $('#fvBody').innerHTML = `<div class="fv-none"><div class="ic">${esc(ext) || ICON.file}</div><b>${esc(f.name)}</b>
    <p>${esc(why || 'There is no preview for this file.')} You can open it in another app.</p>
    <button class="small-btn dark" data-fv-share>Open in another app</button></div>`;
}
function showText(f, text) {
  const cut = text.length > 2e6;
  if (cut) text = text.slice(0, 2e6);
  let html;
  if (/\.(md|markdown)$/i.test(f.name)) html = `<div class="fv-text md">${md(text)}</div>`;
  else if (/\.(csv|tsv)$/i.test(f.name)) html = `<div class="fv-text">${csvTable(text, /\.tsv$/i.test(f.name) ? '\t' : ',')}</div>`;
  else {
    if (f.type === 'application/json') try { text = JSON.stringify(JSON.parse(text), null, 2); } catch {}
    html = `<div class="fv-text"><pre>${esc(text)}</pre></div>`;
  }
  $('#fvBody').innerHTML = html + (cut ? '<p class="fv-more">This file is long. Only its start is shown.</p>' : '');
}
function csvTable(text, sep) {   // quoted cells may hold the separator, quotes and line breaks, as Excel writes them
  const rows = [[]];
  let cell = '', quoted = false;
  for (let i = 0; i < text.length; i++) {
    const c = text[i];
    if (quoted) { if (c !== '"') cell += c; else if (text[i + 1] === '"') { cell += '"'; i++; } else quoted = false; }
    else if (c === '"') quoted = true;
    else if (c === sep) { rows.at(-1).push(cell); cell = ''; }
    else if (c === '\n' || c === '\r') { if (c === '\r' && text[i + 1] === '\n') i++; rows.at(-1).push(cell); cell = ''; rows.push([]); }
    else cell += c;
  }
  rows.at(-1).push(cell);
  if (rows.length > 1 && rows.at(-1).join('') === '') rows.pop();
  const [head = [], ...body] = rows.slice(0, 5000);
  return `<table class="fv-table"><thead><tr>${head.map((c) => `<th>${esc(c)}</th>`).join('')}</tr></thead>
    <tbody>${body.map((r) => `<tr>${r.map((c) => `<td>${esc(c)}</td>`).join('')}</tr>`).join('')}</tbody></table>`;
}
async function showPdf(f, data) {
  const pdfjs = await import('/vendor/pdfjs/pdf.min.mjs');
  pdfjs.GlobalWorkerOptions.workerSrc = '/vendor/pdfjs/pdf.worker.min.mjs';
  const task = pdfjs.getDocument({ data }), doc = await task.promise;
  if (FV.file !== f) return task.destroy();
  FV.pdf = doc; FV.pdfTask = task;
  const v = (await doc.getPage(1)).getViewport({ scale: 1 }), box = $('#fvBody');
  if (FV.file !== f) return;
  box.innerHTML = `<div class="fv-zoom"><div class="fv-pages">${Array.from({ length: doc.numPages }, (_, i) =>
    `<div class="fv-page" data-page="${i + 1}" style="aspect-ratio:${v.width / v.height}"></div>`).join('')}</div></div>`;
  $('#fvMeta').textContent += ` · ${plural(doc.numPages, 'page')}`;
  // draw pages near the screen only, and drop the far ones: a phone runs out of memory for canvases
  FV.io = new IntersectionObserver((es) => es.forEach((e) => {
    if (e.isIntersecting) drawPage(e.target); else { fvFree(e.target); e.target.replaceChildren(); delete e.target.dataset.drawn; }
  }), { root: box, rootMargin: '150% 0px' });
  $$('.fv-page', box).forEach((el) => FV.io.observe(el));
}
async function drawPage(el) {
  const doc = FV.pdf, at = String(FV.zoom);
  if (!doc || FV.pinch || el.dataset.drawn === at) return;   // mid-pinch, fvPinchEnd draws
  el.dataset.drawn = at;
  const page = await doc.getPage(+el.dataset.page), v1 = page.getViewport({ scale: 1 });
  el.style.aspectRatio = v1.width / v1.height;
  // as sharp as the screen, up to 10M pixels: iOS draws nothing on a canvas over 16.7M and runs out of canvas memory
  const v = page.getViewport({ scale: Math.min(Math.sqrt(1e7 / (v1.width * v1.height)), el.clientWidth * devicePixelRatio / v1.width) });
  const c = document.createElement('canvas');
  c.width = Math.floor(v.width); c.height = Math.floor(v.height);
  await page.render({ canvas: c, viewport: v }).promise;
  el.fvLinks ||= await pageLinks(page, v1).catch(() => document.createElement('div'));   // no links beats no page
  if (FV.pdf === doc && el.dataset.drawn === at) { fvFree(el); el.replaceChildren(c, el.fvLinks); } else c.width = c.height = 0;
}
function fvFree(el) { $$('canvas', el).forEach((c) => { c.width = c.height = 0; }); }   // iOS holds a canvas's memory until it is collected
async function pageLinks(page, v1) {   // the PDF's links, as boxes over the page picture, sized in % so they fit any zoom
  const layer = document.createElement('div');
  layer.className = 'fv-links';
  for (const a of await page.getAnnotations()) {
    if (a.subtype !== 'Link' || !(a.url || a.dest)) continue;   // PDF.js only gives a url for http, https, mailto and tel
    const [x1, y1] = v1.convertToViewportPoint(a.rect[0], a.rect[1]), [x2, y2] = v1.convertToViewportPoint(a.rect[2], a.rect[3]);
    const link = document.createElement('a');
    Object.assign(link.style, { left: `${Math.min(x1, x2) / v1.width * 100}%`, top: `${Math.min(y1, y2) / v1.height * 100}%`,
      width: `${Math.abs(x2 - x1) / v1.width * 100}%`, height: `${Math.abs(y2 - y1) / v1.height * 100}%` });
    if (a.url) Object.assign(link, { href: a.url, target: '_blank', rel: 'noopener' });
    else { link.href = '#'; link.fvDest = a.dest; }
    layer.append(link);
  }
  return layer;
}
async function fvGoTo(dest) {   // a link to another place in the same PDF: the contents page, a footnote ...
  const doc = FV.pdf, d = typeof dest === 'string' ? await doc.getDestination(dest) : dest;
  if (!Array.isArray(d) || FV.pdf !== doc) return;
  const n = typeof d[0] === 'number' ? d[0] : await doc.getPageIndex(d[0]), el = $(`#fvBody .fv-page[data-page="${n + 1}"]`);
  if (!el) return;
  const v1 = (await doc.getPage(n + 1)).getViewport({ scale: 1 }), top = { XYZ: d[3], FitH: d[2], FitBH: d[2] }[d[1]?.name];
  const y = top == null ? 0 : Math.max(0, v1.convertToViewportPoint(0, top)[1] / v1.height), box = $('#fvBody');
  box.scrollTop += el.getBoundingClientRect().top - box.getBoundingClientRect().top + y * el.offsetHeight - 8;
}
function fvRedraw() {   // sharp again after a zoom: the pages on and near the screen, nearest first
  if (!FV.pdf) return;
  const r = $('#fvBody').getBoundingClientRect(), mid = (r.top + r.bottom) / 2;
  $$('#fvBody .fv-page').map((el) => [el, el.getBoundingClientRect()])
    .filter(([, b]) => b.bottom > r.top - 1.5 * r.height && b.top < r.bottom + 1.5 * r.height)   // the observer's margin
    .sort(([, a], [, b]) => Math.abs((a.top + a.bottom) / 2 - mid) - Math.abs((b.top + b.bottom) / 2 - mid))
    .forEach(([el]) => drawPage(el));
}
// Zoom a photo or PDF. While the fingers move, only a transform scales the picture: no layout, so nothing jitters.
// When they lift, the new size is laid out with the same point still under the fingers, and the pages are drawn sharp.
function fvPinchStart(cx, cy) {
  const box = $('#fvBody'), inner = $('.fv-zoom', box)?.firstElementChild;
  if (!inner) return false;
  const r = inner.getBoundingClientRect();
  inner.style.transformOrigin = `${cx - r.left}px ${cy - r.top}px`;
  FV.pinch = { zoom: FV.zoom, inner, x: cx, y: cy, ox: cx - r.left, oy: cy - r.top, w: r.width, sl: box.scrollLeft, st: box.scrollTop, s: 1, dx: 0, dy: 0 };
  return true;
}
function fvPinchMove(scale, cx, cy) {
  const p = FV.pinch, box = $('#fvBody');
  if (!p) return;
  p.s = Math.min(5, Math.max(1, p.zoom * scale)) / p.zoom; p.dx = cx - p.x; p.dy = cy - p.y;
  // a scroll that slips in during the pinch would move the picture twice: take it back out
  p.inner.style.transform = `translate3d(${p.dx + box.scrollLeft - p.sl}px, ${p.dy + box.scrollTop - p.st}px, 0) scale(${p.s})`;
}
function fvPinchEnd() {
  const p = FV.pinch, box = $('#fvBody'), wrap = $('.fv-zoom', box);
  FV.pinch = null;
  if (!p || !wrap) return;
  FV.zoom = Math.round(p.zoom * p.s * 100) / 100; wrap.style.width = `${FV.zoom * 100}%`;
  p.inner.style.transform = '';
  const r = p.inner.getBoundingClientRect(), k = r.width / p.w;
  box.scrollLeft += r.left + p.ox * k - (p.x + p.dx);
  box.scrollTop += r.top + p.oy * k - (p.y + p.dy);
  fvRedraw();
}
function fvZoomTo(z, cx, cy) { if (fvPinchStart(cx, cy)) { fvPinchMove(z / FV.zoom, cx, cy); fvPinchEnd(); } }
$('#fvBody').addEventListener('touchmove', (e) => { if (e.touches.length > 1) e.preventDefault(); }, { passive: false });   // two fingers pinch, they don't scroll too
$('#fvBody').addEventListener('click', (e) => {
  if (e.target.closest('[data-fv-share]')) return shareFile();
  const link = e.target.closest('.fv-links a');
  if (link) { FV.tap = 0; if (link.fvDest) { e.preventDefault(); fvGoTo(link.fvDest).catch(() => {}); } return; }
  if (!$('.fv-zoom', e.currentTarget)) return;
  if (Date.now() - FV.tap > 320) { FV.tap = Date.now(); return; }
  FV.tap = 0;   // a double tap zooms in, or back out
  fvZoomTo(FV.zoom > 1 ? 1 : 2.5, e.clientX, e.clientY);
});
function fvStarSync() { const b = $('#fvStar'); b.classList.toggle('on', !!FV.file && isFav(FV.file.path, 'file')); }
$('#fvStar').onclick = (e) => toggleFav(e.currentTarget);
function closeFile() {
  $('#fileView').hidden = true;   // first: nothing below can keep it on screen
  $$('#fvBody video, #fvBody audio').forEach((m) => { m.pause(); clearNowPlaying(m); });
  FV.io?.disconnect();
  FV.pdfTask?.destroy().catch(() => {});
  fvFree($('#fvBody'));
  Object.assign(FV, { file: null, blob: null, blobP: null, zoom: 1, pinch: null, pdf: null, pdfTask: null, io: null });
  $('#fvBody').innerHTML = '';
}
async function shareFile() {   // the share menu: Open in Excel, Word, Numbers, Save to Files ...
  const f = FV.file;
  if (!f) return;
  try {
    const blob = FV.blob || await fileBlob(f);
    const file = new File([blob], f.name, { type: f.type || blob.type });
    if (navigator.canShare?.({ files: [file] })) return await navigator.share({ files: [file] });
  } catch (e) {
    if (e.name === 'AbortError') return;   // the menu was closed
    return toast(e.name === 'NotAllowedError' ? 'The file is ready now. Tap again.' : e.message);   // it took too long to load
  }
  window.open(fileUrl(f.path, true), '_blank');   // no share menu (a Mac browser): download it
}
$('#fvClose').onclick = closeFile;
// Pull the file down to close it, like a photo in the Feed: from the top of the file and not zoomed in, so a scroll or
// a pan inside it stays a scroll. Videos and audio keep their own controls.
(() => {
  const view = $('#fileView'), box = $('#fvBody');
  let d = null;
  view.addEventListener('touchstart', (e) => {
    if (d?.moving) return;
    const t = e.touches[0];
    d = e.touches.length > 1 || FV.zoom > 1 || box.scrollTop > 0 || e.target.closest('video, audio, button, a, .fv-top') ? null
      : { x: t.clientX, y: t.clientY, dy: 0, v: 0, at: performance.now(), moving: false };
  }, { passive: true });
  view.addEventListener('touchmove', (e) => {
    if (!d) return;
    const t = e.touches[0], dx = t.clientX - d.x, dy = t.clientY - d.y, now = performance.now();
    if (!d.moving) {   // decided on the first move: iOS won't let a scroll that started be stopped
      if (e.touches.length > 1 || dy <= 0 || Math.abs(dx) >= dy || box.scrollTop > 0) { d = null; return; }
      d.moving = true; view.style.transition = 'none';
    }
    e.preventDefault();
    const y = Math.max(0, dy);
    d.v = (y - d.dy) / Math.max(1, now - d.at); d.dy = y; d.at = now;
    view.style.transform = `translateY(${y}px)`;
  }, { passive: false });
  const end = () => {
    const g = d; d = null;
    if (!g?.moving) return;
    view.style.transition = 'transform .22s ease-out';
    const away = g.dy > 110 || g.v > 0.6;   // far or fast enough: it goes on off the screen
    view.style.transform = away ? `translateY(${innerHeight}px)` : '';
    setTimeout(() => { if (away) closeFile(); view.style.transition = view.style.transform = ''; }, 220);
  };
  view.addEventListener('touchend', end);
  view.addEventListener('touchcancel', end);
})();
$('#fvShare').onclick = shareFile;

// ---------- upcoming ----------
const DOW = ['Sunday', 'Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday'];
function hm(h, m) { const d = new Date(); d.setHours(+h, +m, 0, 0); return d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' }); }
function cronLabel(c) {
  const p = (c || '').trim().split(/\s+/);
  const every = (c || '').trim().match(/^\*\/(\d+) \* \* \* \*$/);
  if (every) return `Every ${every[1]} minutes`;
  const hourly = (c || '').trim().match(/^(\d+) (?:\*|\*\/(\d+)) \* \* \*$/);
  if (hourly) return `Every ${hourly[2] ? `${hourly[2]} hours` : 'hour'}${+hourly[1] ? ` at :${hourly[1].padStart(2, '0')}` : ''}`;
  if (p.length !== 5 || !/^\d+$/.test(p[0]) || !/^\d+$/.test(p[1]) || p[2] !== '*' || p[3] !== '*') return `Custom (${c})`;
  const t = hm(p[1], p[0]);
  if (p[4] === '*') return `Every day at ${t}`;
  if (p[4] === '1-5') return `Weekdays at ${t}`;
  if (p[4] === '0,6' || p[4] === '6,0') return `Weekends at ${t}`;
  if (/^\d$/.test(p[4])) return `Every ${DOW[+p[4] % 7]} at ${t}`;
  return `Custom (${c})`;
}
function fmtWhen(ts) {
  if (!ts) return '';
  const d = new Date(ts * 1000), now = new Date();
  const tom = new Date(now); tom.setDate(now.getDate() + 1);
  const t = d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' });
  if (d.toDateString() === now.toDateString()) return `Today ${t}`;
  if (d.toDateString() === tom.toDateString()) return `Tomorrow ${t}`;
  return d.toLocaleDateString([], { weekday: 'short', month: 'short', day: 'numeric' }) + ` ${t}`;
}
function relTime(ts) {
  const s = Date.now() / 1000 - ts;
  if (s < 60) return 'just now';
  if (s < 3600) return `${Math.floor(s / 60)}m ago`;
  if (s < 86400) return `${Math.floor(s / 3600)}h ago`;
  return new Date(ts * 1000).toLocaleDateString([], { month: 'short', day: 'numeric' });
}
// Active: switched on. Inactive: paused, or a one-time item that is done. The switch moves an item across.
let upView = store.get('upcomingTab') === 'inactive' ? 'inactive' : 'active';
function setUpView(v) {
  upView = v; store.set('upcomingTab', v);
  $$('#upSeg button').forEach((b) => b.classList.toggle('on', b.dataset.v === v));
}
setUpView(upView);
$('#upSeg').addEventListener('click', (e) => {
  const b = e.target.closest('button[data-v]');
  if (!b || b.dataset.v === upView) return;
  setUpView(b.dataset.v); renderUpcoming(); $('#view-upcoming .scroll').scrollTop = 0;
});
async function loadUpcoming() {
  try { S.schedules = await api('/api/schedules'); renderUpcoming(); }
  catch (e) { $('#scheduleList').innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; }
}
function renderUpcoming() {
  const box = $('#scheduleList'), items = (S.schedules || []).filter((s) => !!s.enabled === (upView === 'active'));
  if (!items.length) {
    box.innerHTML = `<div class="empty-state">${ICON.clock}<br>${upView === 'active' ? 'Nothing scheduled.' : 'Nothing paused or done.'}</div>`;
    return;
  }
  box.innerHTML = items.map((s) => `<div class="item sched ${s.enabled ? '' : 'off'}" data-sid="${s.id}">
      <div class="ic">${ICON.tool}</div>
      <div class="tx"><b>${esc(s.title)}</b><span>${esc(s.cron ? cronLabel(s.cron) : s.enabled ? fmtWhen(s.next) : s.last_run ? `Done ${relTime(s.last_run)}` : `Paused · ${fmtWhen(s.next)}`)}${s.cron && s.enabled ? ' · next ' + esc(fmtWhen(s.next)) : ''}</span></div>
      <div class="acts">
        <button data-run aria-label="Run now">${ICON.play}</button>
        <button data-del aria-label="Delete">${ICON.trash}</button>
        <span class="switch ${s.enabled ? 'on' : ''}" data-toggle role="switch" aria-checked="${s.enabled}"></span>
      </div></div>`).join('');
}
$('#scheduleList').addEventListener('click', async (e) => {
  const row = e.target.closest('[data-sid]');
  if (!row) return;
  const id = row.dataset.sid;
  try {
    if (e.target.closest('[data-toggle]')) await api(`/api/schedules/${id}`, { method: 'PATCH', body: { enabled: !row.querySelector('.switch').classList.contains('on') } });
    else if (e.target.closest('[data-run]')) {   // a double tap starts it once (a one-time task makes a chat per run)
      if (Date.now() - (S.ranAt[id] || 0) < 2000) return;
      S.ranAt[id] = Date.now();
      await api(`/api/schedules/${id}/run`, { method: 'POST' }); toast('Started');
    }
    else if (e.target.closest('[data-del]')) { if (!armed(e.target.closest('[data-del]'))) return; await api(`/api/schedules/${id}`, { method: 'DELETE' }); }
    else return openTask(id);
    loadUpcoming();
  } catch (err) { toast(err.message); }
});
// A task's runs: every time it ran, with the result. Tap a run to open its chat.
const RUN_LABEL = { running: 'Running', queued: 'Waiting', done: 'Done', quiet: 'Nothing new', error: 'Error',
  stopped: 'Stopped', interrupted: 'Interrupted' };
function openTask(id) {
  $('#taskSheetBody').innerHTML = '<div class="empty-state"><span class="spin"></span></div>';
  openSheet('taskSheet');
  showTask(id);
}
async function showTask(id) {
  const s = (S.schedules || []).find((x) => x.id === id);
  if (!s) return closeSheet('taskSheet');
  S.taskId = id;
  $('#taskSheetTitle').textContent = s.title;
  const body = $('#taskSheetBody');
  try {
    const runs = await api(`/api/schedules/${id}/history`);
    if (S.taskId !== id) return;
    const when = s.cron ? cronLabel(s.cron) : fmtWhen(s.next);
    body.innerHTML = `<div class="task-info"><span>${esc(when)}${s.enabled ? '' : ' · Paused'}</span></div>`
      + (runs.length ? `<div class="runs">${runs.map((r) => {
        const sum = stripDirectives(r.summary || '').replace(/[#*`_>|]/g, '').trim();
        return `<div class="run ${esc(r.status)}"><div class="run-top"><b>${esc(RUN_LABEL[r.status] || r.status)}</b><span>${esc(fmtWhen(r.ts))}</span></div>${sum ? `<p>${esc(sum)}</p>` : ''}</div>`;
      }).join('')}</div>` : '<div class="empty-state">No runs yet. Each run will show here.</div>');
  } catch (e) { body.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; }
}
$('#addScheduleBtn').onclick = () => {
  const f = $('#scheduleForm'), day = new Date();
  if (day.getHours() >= 9) day.setDate(day.getDate() + 1);   // the next 9:00, so the form never starts in the past
  // the phone's own date: toISOString is in UTC, which is already tomorrow on a US evening
  f.reset(); f.date.value = `${day.getFullYear()}-${String(day.getMonth() + 1).padStart(2, '0')}-${String(day.getDate()).padStart(2, '0')}`; f.time.value = '09:00';
  $('#scheduleErr').textContent = ''; syncRepeat();
  openSheet('scheduleSheet');
};
function syncRepeat() { const r = $('#scheduleForm').repeat.value; $('#dateField').hidden = r !== 'once'; $('#dowField').hidden = r !== 'weekly'; }
$('#scheduleForm').repeat.onchange = syncRepeat;
$('#scheduleForm').onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target, [h, m] = f.time.value.split(':').map(Number);
  const body = { text: f.text.value.trim(), title: f.text.value.trim().split('\n')[0].slice(0, 60) };
  const r = f.repeat.value;
  if (r === 'once') body.when = `${f.date.value}T${f.time.value}`;
  else body.cron = `${m} ${h} * * ${r === 'daily' ? '*' : r === 'weekdays' ? '1-5' : f.dow.value}`;
  // a time that has passed would go off at once (and a task would run)
  if (r === 'once' && !(new Date(body.when) > Date.now())) { $('#scheduleErr').textContent = f.date.value ? 'That time has passed.' : 'Pick a date.'; return; }
  await inFlight(f, async () => {
    try { await api('/api/schedules', { method: 'POST', body }); document.activeElement?.blur(); closeSheet('scheduleSheet'); loadUpcoming(); toast('Scheduled'); }
    catch (err) { $('#scheduleErr').textContent = err.message; }
  });
};

// ---------- activity ----------
const EV_ICON = { feed: FI.posts, compact: ICON.compact, goal: ICON.check, tool: ICON.tool, approval: ICON.shield, memory: ICON.brain, schedule: ICON.clock, browser: ICON.globe, google: ICON.key };
async function loadActivity() {
  const box = $('#activityList');
  try {
    const items = await api('/api/activity');
    if (!items.length) { box.innerHTML = `<div class="empty-state">No activity yet.</div>`; return; }
    let day = '', html = '';
    for (const e of items) {
      const d = new Date(e.ts * 1000);
      const label = d.toDateString() === new Date().toDateString() ? 'Today' : d.toLocaleDateString([], { weekday: 'long', month: 'short', day: 'numeric' });
      if (label !== day) { html += `<div class="day">${esc(label)}</div>`; day = label; }
      html += `<div class="ev"><div class="ic ${esc(e.kind)}">${EV_ICON[e.kind] || ICON.tool}</div>
        <div class="tx"><b>${esc(e.title)}</b>${e.detail ? `<div class="d">${esc(e.detail)}</div>` : ''}
        <div class="m">${esc(e.status || '')}${e.conv && e.convTitle ? ` · <a href="#" data-conv="${esc(e.conv)}">${esc(e.convTitle)}</a>` : ''}</div></div>
        <div class="when">${d.toLocaleTimeString([], { hour: 'numeric', minute: '2-digit' })}</div></div>`;
    }
    box.innerHTML = html;
  } catch (err) { box.innerHTML = `<div class="empty-state">${esc(err.message)}</div>`; }
}
$('#activityList').addEventListener('click', (e) => {
  const a = e.target.closest('[data-conv]');
  if (a) { e.preventDefault(); switchTab('chat'); openConv(a.dataset.conv); }
});

// ---------- settings ----------
const MODE_HELP = {
  approve: 'Milo asks before every action.',
  smart_approve: 'Asks before it changes, sends or runs something. Reading is automatic.',
  auto: 'Milo acts on its own. Fastest, least safe.',
};
async function openSettings() {
  closeSheet('drawer');
  openSheet('settings');
  const st = S.settings;
  const body = $('#settingsBody');
  body.innerHTML = `
    <div class="group"><h3>Permissions</h3><div class="card">
      <div class="row"><div class="tx"><b>${esc(S.modes[st.permission_mode] || '')}</b><span>Rules, reading and approvals are in the Permissions tab.</span></div><button class="small-btn" id="openPerms">Open</button></div>
    </div></div>

    <div class="group"><h3>Activity</h3><div class="card">
      <div class="row"><div class="tx"><b>Everything Milo did</b><span>Its actions and what you approved.</span></div><button class="small-btn" id="openActivity">Open</button></div>
    </div></div>

    <div class="group"><h3>Claude usage</h3><div class="card" id="usageBox" aria-busy="true" aria-label="Loading usage"><div class="row limit skel"><div class="tx"><div class="limit-top"><b>&nbsp;</b></div><div class="meter"><i></i></div><span>&nbsp;</span></div></div><div class="row limit skel"><div class="tx"><div class="limit-top"><b>&nbsp;</b></div><div class="meter"><i></i></div><span>&nbsp;</span></div></div></div>
      <p class="view-sub" style="margin:8px 4px 0">Limits count all use of this Claude account, including Claude Code and claude.ai. Claude shows them as a share used, not a token count.</p></div>

    <div class="group"><h3>Assistant</h3><div class="card">
      <div class="row"><div class="tx"><b>Name</b></div><input type="text" data-set="assistant_name" maxlength="40" value="${esc(st.assistant_name)}"></div>
      <div class="row"><div class="tx"><b>Tone</b></div><input type="text" data-set="tone" value="${esc(st.tone)}"></div>
      <div class="row"><div class="tx"><b>Answer length</b></div><input type="text" data-set="length" value="${esc(st.length)}"></div>
    </div></div>

    <div class="group"><h3>Appearance</h3><div class="card">
      <div class="row"><div class="tx"><b>Theme</b><span>On this device.</span></div><select id="themeSel">
        <option value="">System</option><option value="light">Light</option><option value="dark">Dark</option></select></div>
    </div></div>

    <div class="group"><h3>Voice</h3><div class="card">
      <div class="row"><div class="tx"><b>Speak replies</b></div><select id="speakPolicy">
        <option value="voice">When I talk</option><option value="always">Always</option><option value="never">Never</option></select></div>
      <div class="row"><div class="tx"><b>Voice</b></div><select data-set="voice" id="voiceSel"><option>${esc(st.voice)}</option></select></div>
      <div class="row"><div class="tx" style="flex:none"><b>Speed</b></div><input type="range" min="140" max="260" step="5" data-set="voice_rate" value="${st.voice_rate}"></div>
      <div class="row"><button class="small-btn" id="previewVoice">Preview</button><span class="tx"><span>On-device Whisper on your Mac turns speech into text.</span></span></div>
    </div></div>

    <div class="group"><h3>Memory</h3><div class="card">
      <textarea class="memo" id="memoryText" placeholder="Milo adds facts here when you tell it about yourself. You can edit them."></textarea>
      <div class="btn-row"><button class="small-btn dark" id="saveMemory">Save memory</button></div>
    </div></div>

    <div class="group"><h3>Google accounts</h3><div class="card" id="googleBox"><div class="row"><div class="tx"><span>Loading</span></div></div></div></div>

    <div class="group"><h3>Accounts</h3><div class="card" id="acctList"><div class="row"><div class="tx"><span>Loading</span></div></div></div>
      <div class="btn-row" style="padding:10px 0 0"><button class="small-btn dark" id="addAccount">Add account</button></div>
      <p class="view-sub" style="margin:8px 4px 0">Passwords stay in your Mac's Keychain. Milo types them on the matching site only.</p></div>

    <div class="group"><h3>Browser</h3><div class="card">
      <div class="row"><div class="tx"><b>Milo's browser</b><span id="browserStatus"></span></div><button class="small-btn" id="openBrowser">Open</button></div>
      <div class="row"><div class="tx"><b>Restart</b><span>Reopen the Chrome window on your Mac.</span></div><button class="small-btn" id="restartBrowser">Restart</button></div>
      <div class="row"><div class="tx"><b>Clear browser data</b><span>Logs Milo out of every site.</span></div><button class="small-btn" id="resetBrowser">Clear</button></div>
    </div></div>

    <div class="group"><h3>Connectors</h3><div class="card" id="connList"><div class="row"><div class="tx"><span>Loading</span></div></div></div>
      <p class="view-sub" style="margin:8px 4px 0">Goose extensions on your Mac. Add Gmail, Calendar and others with <code>goose configure</code>.</p></div>

    <div class="group"><h3>Notifications</h3><div class="card">
      <div class="row"><div class="tx"><b>Alerts</b><span id="pushState"></span></div><button class="small-btn dark" id="pushBtn">Turn on</button></div>
      <div class="row"><div class="tx"><span>Get an alert when Milo finishes or needs your OK.</span></div><button class="small-btn" id="pushTest">Test</button></div>
    </div></div>

    <div class="group"><h3>Hey Siri</h3><div class="card">
      <ol class="steps-list">
        <li>Open <b>Shortcuts</b>, tap <b>+</b>, and name it <b>Ask Milo</b>.</li>
        <li>Add <b>Dictate Text</b>.</li>
        <li>Add <b>Get Contents of URL</b>. URL: <span class="mono">${esc(location.origin)}/api/ask</span>. Method <b>POST</b>. Header <b>Authorization</b> = <span class="mono">Bearer &lt;token&gt;</span>. Request Body <b>JSON</b>, key <b>text</b> = Dictated Text.</li>
        <li>Add <b>Speak Text</b> with Contents of URL.</li>
        <li>Say <b>"Hey Siri, Ask Milo"</b>.</li>
      </ol>
      <div class="btn-row"><button class="small-btn" id="copyUrl">Copy URL</button><button class="small-btn" id="copyToken">Copy token</button></div>
    </div></div>

    <div class="group"><h3>This device</h3><div class="card">
      <div class="row"><div class="tx"><b>Disconnect</b><span>Remove the access token from this phone.</span></div><button class="small-btn" id="logout">Disconnect</button></div>
    </div></div>`;

  $('#themeSel').value = store.get('theme', '');
  $('#themeSel').onchange = (e) => {   // index.html's setTheme: also used before the first paint
    const t = e.target.value;
    if (t) store.set('theme', t); else store.del('theme');
    setTheme(t); renderMessages();   // diagrams are drawn for one theme
  };
  $('#speakPolicy').value = S.speakPolicy;
  $('#speakPolicy').onchange = (e) => { S.speakPolicy = e.target.value; store.set('speak_policy', e.target.value); };
  $('#openPerms').onclick = () => { closeSheet('settings'); switchTab('permissions'); };
  $('#openActivity').onclick = () => { closeSheet('settings'); switchTab('activity'); };
  body.querySelectorAll('[data-set]').forEach((el) => el.addEventListener('change', async () => {
    try {
      S.settings = await api('/api/settings', { method: 'PUT', body: { [el.dataset.set]: el.type === 'range' ? +el.value : el.value } });
      if (el.type === 'text') el.value = S.settings[el.dataset.set];   // as saved: trimmed, or the default for a blank one
      setTitle(); toast('Saved', 1200);
    }
    catch (err) { toast(err.message); }
  }));
  $('#previewVoice').onclick = () => { unlockAudio(); speak(`Hi, I'm ${S.settings.assistant_name}. What can I do for you?`); };
  $('#saveMemory').onclick = (e) => inFlight(e.currentTarget, async () => {   // a failed save says so: the edit is not kept
    try { await api('/api/memory', { method: 'PUT', body: { text: $('#memoryText').value } }); toast('Memory saved'); } catch (err) { toast(err.message); }
  });
  $('#copyUrl').onclick = () => navigator.clipboard?.writeText(`${location.origin}/api/ask`).then(() => toast('URL copied'));
  $('#copyToken').onclick = () => navigator.clipboard?.writeText(S.token).then(() => toast('Token copied'));
  $('#logout').onclick = () => { store.del('token'); location.reload(); };
  $('#pushBtn').onclick = enablePush;
  $('#addAccount').onclick = () => { $('#accountForm').reset(); $('#accountErr').textContent = ''; openSheet('accountSheet'); };
  $('#openBrowser').onclick = () => BV.open();   // over Settings: closing the browser comes back here
  $('#restartBrowser').onclick = async () => { toast('Restarting the browser'); try { S.browser = await api('/api/browser/restart', { method: 'POST' }); renderBrowserBits(); toast('Browser ready'); } catch (err) { toast(err.message); } };
  $('#resetBrowser').onclick = async (e) => { if (!armed(e.currentTarget)) return; try { await api('/api/browser/reset', { method: 'POST' }); toast('Browser data cleared'); } catch (err) { toast(err.message); } };
  renderBrowserBits(); loadAccounts(); loadGoogle(); loadUsage();
  $('#pushTest').onclick = async () => {
    try { const r = await api('/api/push/test', { method: 'POST' }); toast(r.devices ? 'Sent' : 'No devices yet: turn alerts on first'); } catch (err) { toast(err.message); }
  };
  renderPushState();

  api('/api/voices').then((voices) => {
    const sel = $('#voiceSel');
    if (sel) sel.innerHTML = voices.map((v) => `<option value="${esc(v.name)}" ${v.name === S.settings.voice ? 'selected' : ''}>${esc(v.label || v.name)}</option>`).join('');
  }).catch(() => {});
  api('/api/memory').then((m) => { const t = $('#memoryText'); if (t) t.value = m.text; }).catch(() => {});
  api('/api/connectors').then((list) => {
    const box = $('#connList');
    if (box) box.innerHTML = list.map((c) => `<div class="row"><div class="tx"><b>${esc(c.name)}</b><span>${esc(c.description)}</span></div><span class="switch ${c.enabled ? 'on' : ''}" aria-label="${c.enabled ? 'On' : 'Off'}"></span></div>`).join('') || '<div class="row"><div class="tx"><span>No extensions found.</span></div></div>';
  }).catch(() => {});
}
function untilText(ms) {
  const m = Math.max(1, Math.round(ms / 60000)), h = Math.floor(m / 60);
  return m < 60 ? `${m} min` : h < 24 ? `${h} hr${m % 60 ? ` ${m % 60} min` : ''}` : `${Math.round(h / 24)} days`;
}
async function loadUsage() {
  const box = $('#usageBox'); if (!box) return;
  try {
    const u = await api('/api/usage');
    const resets = (l) => {
      const t = Date.parse(l.resets || '');
      if (isNaN(t)) return l.resets_text ? `Resets ${l.resets_text}` : '';
      return `Resets ${fmtWhen(t / 1000)}${t > Date.now() ? ` · in ${untilText(t - Date.now())}` : ''}`;
    };
    const level = (used) => used >= 90 ? 'danger' : used >= 70 ? 'warn' : 'ok';
    const head = u.plan || u.email ? `<div class="row"><div class="tx"><b>${esc(u.plan ? `${u.plan} plan` : 'Claude')}</b><span>${esc(u.email)}</span></div></div>` : '';
    const limits = u.limits.map((l) => `<div class="row limit"><div class="tx">
        <div class="limit-top"><b>${esc(l.label)}</b><em>${Math.max(0, Math.round(100 - l.used))}% left</em></div>
        <div class="meter ${level(l.used)}"><i style="width:${Math.min(100, l.used)}%"></i></div>
        <span>${esc(resets(l))}</span></div></div>`).join('')
      || `<div class="row"><div class="tx"><span>Claude Code didn't report any limits.</span></div></div>`;
    // the 7-day notes often repeat the 24-hour ones: then only their title line is new
    const notes = u.notes.map((n, i) => {
      const same = i && JSON.stringify(n.lines) === JSON.stringify(u.notes[i - 1].lines);
      return `<div class="row"><div class="tx"><b>${esc(n.title)}</b>${same ? '' : n.lines.map((x) => `<span>${esc(x)}</span>`).join('')}</div></div>`;
    }).join('');
    box.innerHTML = head + limits + notes;
  } catch (err) {
    box.innerHTML = `<div class="row"><div class="tx"><b>Couldn't read usage</b><span>${esc(err.message)}</span></div></div>`;
  }
}
$('#settingsBtn').onclick = openSettings;

// ---------- push ----------
function renderPushState() {
  const el = $('#pushState'); if (!el) return;
  if (!('serviceWorker' in navigator) || !('PushManager' in window)) {
    el.textContent = isIOS && !standalone ? 'First add Milo to your Home Screen (Share, then Add to Home Screen).' : 'Not supported in this browser.';
    $('#pushBtn').hidden = true; return;
  }
  el.textContent = Notification.permission === 'granted' ? 'On for this device' : Notification.permission === 'denied' ? 'Blocked in system settings' : 'Off';
  $('#pushBtn').textContent = Notification.permission === 'granted' ? 'Refresh' : 'Turn on';
}
async function enablePush() {
  try {
    const perm = await Notification.requestPermission();
    if (perm !== 'granted') { renderPushState(); return toast('Notifications were not allowed'); }
    const reg = await navigator.serviceWorker.ready;
    const key = Uint8Array.from(atob(S.vapidKey.replace(/-/g, '+').replace(/_/g, '/') + '='.repeat((4 - S.vapidKey.length % 4) % 4)), (c) => c.charCodeAt(0));
    const sub = (await reg.pushManager.getSubscription()) || (await reg.pushManager.subscribe({ userVisibleOnly: true, applicationServerKey: key }));
    await api('/api/push/subscribe', { method: 'POST', body: sub.toJSON() });
    renderPushState(); toast('Alerts are on');
  } catch (e) { toast('Could not turn on alerts: ' + e.message); }
}


// ---------- browser: header, banner, accounts ----------
function renderBrowserBits() {
  const b = S.browser || {};
  for (const dot of $$('#moreBtn .live-dot, #moreMenu .live-dot')) dot.hidden = !(b.busy || b.controller === 'user');
  const banner = $('#browserBanner');
  const waiting = b.controller === 'user' && b.reason;
  banner.hidden = !waiting || BV.isOpen();
  if (waiting) {
    banner.innerHTML = `${ICON.globe}<span><b>Milo needs you in the browser</b> · ${esc(b.reason)}</span>`;
    banner.onclick = () => BV.open();
  }
  const st = $('#browserStatus');
  if (st) st.textContent = !b.enabled ? 'Off' : !b.ready ? 'Starting or unavailable' : b.controller === 'user' ? 'You have control' : b.busy ? 'Milo is browsing' : 'Ready';
}

async function loadAccounts() {
  const box = $('#acctList'); if (!box) return;
  try {
    const list = await api('/api/accounts');
    box.innerHTML = list.length ? list.map((a) => `<div class="row" data-acct="${a.id}">
        <div class="ic acct-ic">${ICON.key}</div>
        <div class="tx"><b>${esc(a.label)}</b><span>${esc(a.username)} · ${esc(a.domain)}${a.has_totp ? ' · 2FA' : ''}</span></div>
        <span class="mini-label">Ask</span><span class="switch ${a.policy === 'ask' ? 'on' : ''}" data-policy role="switch" aria-checked="${a.policy === 'ask'}" aria-label="Ask before use"></span>
        <button class="small-btn" data-delacct aria-label="Delete">${ICON.trash}</button></div>`).join('')
      : '<div class="row"><div class="tx"><span>No accounts yet. Add one so Milo can log in for you.</span></div></div>';
  } catch (e) { box.innerHTML = `<div class="row"><div class="tx"><span>${esc(e.message)}</span></div></div>`; }
}
document.addEventListener('click', async (e) => {
  const row = e.target.closest('[data-acct]'); if (!row) return;
  const id = row.dataset.acct;
  try {
    if (e.target.closest('[data-policy]')) {
      const ask = !row.querySelector('[data-policy]').classList.contains('on');
      await api(`/api/accounts/${id}`, { method: 'PATCH', body: { policy: ask ? 'ask' : 'auto' } });
      toast(ask ? 'Milo will ask first' : 'Milo will log in without asking'); loadAccounts();
    } else if (e.target.closest('[data-delacct]')) {
      if (!armed(e.target.closest('[data-delacct]'))) return;
      await api(`/api/accounts/${id}`, { method: 'DELETE' }); toast('Account deleted'); loadAccounts();
    }
  } catch (err) { toast(err.message); }
});
$('#accountForm').onsubmit = async (e) => {
  e.preventDefault();
  const f = e.target;
  const body = { domain: f.domain.value, username: f.username.value, password: f.password.value, totp: f.totp.value,
                 label: f.label.value, policy: f.ask.checked ? 'ask' : 'auto' };
  await inFlight(f, async () => {
    try { await api('/api/accounts', { method: 'POST', body }); document.activeElement?.blur(); f.reset(); closeSheet('accountSheet'); toast('Account saved'); loadAccounts(); }
    catch (err) { $('#accountErr').textContent = err.message; }
  });
};

// ---------- browser viewer (live view + takeover) ----------
const BV = {
  ws: null, open_: false, meta: { w: 1280, h: 800 }, st: {}, zoom: 1, url: null, drag: null,
  isOpen() { return this.open_; },
  open() {
    if (this.open_) return;
    this.open_ = true; $('#bview').hidden = false; $('#bvEmpty').hidden = false; $('#bvImg').removeAttribute('src');
    renderBrowserBits(); this.state(S.browser || {}); this.connect();
  },
  close() {
    this.open_ = false; $('#bview').hidden = true;
    try { this.ws && this.ws.close(); } catch {}
    this.ws = null; renderBrowserBits();
    if (!$('#settings').hidden) loadGoogle();   // back in Settings after a sign-in: show the account as connected
  },
  connect() {
    const proto = location.protocol === 'https:' ? 'wss' : 'ws';
    const ws = new WebSocket(`${proto}://${location.host}/ws/browser?token=${encodeURIComponent(S.token)}`);
    ws.binaryType = 'blob'; this.ws = ws;
    ws.onmessage = (e) => {
      if (typeof e.data !== 'string') {
        const url = URL.createObjectURL(e.data), img = $('#bvImg');
        img.onload = () => { if (this.url && this.url !== url) URL.revokeObjectURL(this.url); this.url = url; };
        img.src = url; $('#bvEmpty').hidden = true;
        return;
      }
      const m = JSON.parse(e.data);
      if (m.t === 'state') { S.browser = { ...S.browser, ...m.state }; this.state(m.state); renderBrowserBits(); }
      else if (m.t === 'meta') { this.meta = { w: m.w, h: m.h }; }
      else if (m.t === 'error') toast(m.message);
    };
    ws.onclose = () => { if (this.open_ && this.ws === ws) setTimeout(() => this.open_ && this.connect(), 1500); };
  },
  send(obj) { if (this.ws && this.ws.readyState === 1) this.ws.send(JSON.stringify(obj)); },
  mine() { return (this.st.controller || S.browser.controller) === 'user'; },
  state(st) {
    this.st = { ...this.st, ...st };
    if (st.w && st.h) this.meta = { w: st.w, h: st.h };
    if (!this.open_) return;
    const mine = this.mine();
    const url = $('#bvUrl'); if (document.activeElement !== url) url.value = this.st.url || '';
    $('#bvTabCount').textContent = (this.st.tabs || []).length || 1;
    const status = $('#bvStatus');
    status.className = 'bv-status ' + (mine ? 'user' : this.st.busy ? 'busy' : 'idle');
    $('#bvStatusText').textContent = mine ? (this.st.reason ? `Your turn: ${this.st.reason}` : 'You have control')
      : this.st.busy ? 'Milo is browsing' : 'Milo is not using the browser';
    const btn = $('#bvControl');
    btn.textContent = mine ? 'Give back to Milo' : 'Take control';
    btn.classList.toggle('mine', mine);
    $('#bview').classList.toggle('control', mine);
    ['#bvBack', '#bvReload', '#bvUp', '#bvDown', '#bvKeys'].forEach((sel) => { $(sel).disabled = !mine; });
  },
  async toggleControl() {
    try {
      const st = await api('/api/browser/control', { method: 'POST', body: { action: this.mine() ? 'release' : 'take' } });
      S.browser = { ...S.browser, ...st }; this.state(st); renderBrowserBits();
    } catch (e) { toast(e.message); }
  },
  point(e) {
    const r = $('#bvImg').getBoundingClientRect();
    return { x: ((e.clientX - r.left) / r.width) * this.meta.w, y: ((e.clientY - r.top) / r.height) * this.meta.h };
  },
};
$('#bvClose').onclick = () => BV.close();
$('#bvControl').onclick = () => BV.toggleControl();
$('#bvBack').onclick = () => BV.send({ type: 'back' });
$('#bvReload').onclick = () => BV.send({ type: 'reload' });
$('#bvUp').onclick = () => BV.send({ type: 'wheel', x: BV.meta.w / 2, y: BV.meta.h / 2, dy: -500 });
$('#bvDown').onclick = () => BV.send({ type: 'wheel', x: BV.meta.w / 2, y: BV.meta.h / 2, dy: 500 });
$('#bvZoom').onclick = () => bvZoomTo(BV.zoom >= 2.4 ? 1 : BV.zoom >= 1.6 ? 2.4 : 1.6);
// Zoom the browser picture, keeping the point at (cx, cy) under your fingers.
function bvZoomTo(z, cx, cy) {
  const box = $('#bvScreen'), r = box.getBoundingClientRect(), old = BV.zoom;
  z = Math.min(4, Math.max(1, z));
  const fx = (cx ?? r.left + r.width / 2) - r.left, fy = (cy ?? r.top + r.height / 2) - r.top;
  const x = box.scrollLeft + fx, y = box.scrollTop + fy;
  BV.zoom = z;
  $('#bvImg').style.width = `${z * 100}%`; $('#bview').classList.toggle('zoomed', z > 1);
  box.scrollLeft = x * z / old - fx; box.scrollTop = y * z / old - fy;
}
// Pinch zoom: only the browser picture, an open file and a feed photo zoom. The rest of the app stays at its size (iOS
// gesture events).
for (const t of ['gesturestart', 'gesturechange', 'gestureend']) {
  document.addEventListener(t, (e) => {
    e.preventDefault();
    const mz = e.target.closest?.('#mediaStage .media-zoom');
    if (mz) {
      if (t === 'gesturestart') MZ.pinch = MZ.zoom;
      else if (t === 'gesturechange' && MZ.pinch) mzZoomTo(mz, MZ.pinch * e.scale, e.clientX, e.clientY);
      else { MZ.pinch = 0; if (MZ.zoom < 1.1) mzZoomTo(mz, 1); }   // nearly back: all the way
      return;
    }
    if (e.target.closest?.('#fvBody')) {
      if (t === 'gesturestart') fvPinchStart(e.clientX, e.clientY);
      else if (t === 'gesturechange') fvPinchMove(e.scale, e.clientX, e.clientY);
      else fvPinchEnd();
      return;
    }
    if (!e.target.closest?.('#bvScreen')) return;
    if (t === 'gesturestart') { BV.pinch = BV.zoom; BV.drag = null; }
    else if (t === 'gesturechange' && BV.pinch) bvZoomTo(BV.pinch * e.scale, e.clientX, e.clientY);
    else BV.pinch = null;
  }, { passive: false });
}
$('#bvForm').onsubmit = (e) => {
  e.preventDefault();
  if (!BV.mine()) return toast('Take control first');
  BV.send({ type: 'nav', url: $('#bvUrl').value.trim() }); $('#bvUrl').blur();
};
$('#bvTabsBtn').onclick = () => {
  const tabs = BV.st.tabs || [];
  $('#bvTabList').innerHTML = tabs.map((t) => `<button class="item tab-item ${t.active ? 'active' : ''}" data-tab-id="${t.id}">
    <div class="ic">${ICON.globe}</div><div class="tx"><b>${esc((t.url || 'about:blank').replace(/^https?:\/\//, ''))}</b><span>${t.active ? 'Showing' : 'Tap to show'}</span></div></button>`).join('')
    || '<div class="empty-state">No tabs</div>';
  openSheet('bvTabsSheet');
};
$('#bvTabList').addEventListener('click', async (e) => {
  const b = e.target.closest('[data-tab-id]'); if (!b) return;
  try { await api('/api/browser/tab', { method: 'POST', body: { id: b.dataset.tabId } }); closeSheet('bvTabsSheet'); }
  catch (err) { toast(err.message); }
});
// taps and drags on the live picture (only while you have control)
const bvImg = $('#bvImg');
BV.fingers = new Set();
bvImg.addEventListener('pointerdown', (e) => {
  BV.fingers.add(e.pointerId);
  if (!BV.mine() || BV.fingers.size > 1) { BV.drag = null; return; }   // two fingers: a pinch, not a tap
  BV.drag = { x: e.clientX, y: e.clientY, last: e.clientY, moved: false };
});
for (const t of ['pointerup', 'pointercancel']) bvImg.addEventListener(t, (e) => BV.fingers.delete(e.pointerId));
bvImg.addEventListener('pointermove', (e) => {
  const d = BV.drag; if (!d) return;
  if (Math.abs(e.clientY - d.y) > 8 || Math.abs(e.clientX - d.x) > 8) d.moved = true;
  if (d.moved && BV.zoom === 1 && !BV.pinch) {
    e.preventDefault();
    const scale = BV.meta.h / bvImg.getBoundingClientRect().height;
    const dy = (d.last - e.clientY) * scale; d.last = e.clientY;
    if (Math.abs(dy) > 2) { const p = BV.point(e); BV.send({ type: 'wheel', x: p.x, y: p.y, dy }); }
  }
});
bvImg.addEventListener('pointerup', (e) => {
  const d = BV.drag; BV.drag = null;
  if (!d || d.moved || !BV.mine()) return;
  const p = BV.point(e); BV.send({ type: 'tap', x: p.x, y: p.y });
});
bvImg.addEventListener('pointercancel', () => { BV.drag = null; });
// keyboard: a hidden input forwards what you type. It always holds one invisible character:
// iOS sends no delete from an empty field, so Backspace would never reach the page.
function padBvInput() { const i = $('#bvInput'); i.value = '​'; i.setSelectionRange(1, 1); }
$('#bvKeys').onclick = () => { $('#bvInput').focus(); padBvInput(); };
$('#bvInput').addEventListener('beforeinput', (e) => {
  e.preventDefault();
  if (e.inputType === 'insertText' && e.data) BV.send({ type: 'text', text: e.data });
  else if (/^delete.*Backward$/.test(e.inputType)) BV.send({ type: 'key', key: 'Backspace' });   // held key: word by word
  else if (e.inputType === 'insertLineBreak') BV.send({ type: 'key', key: 'Enter' });
});
$('#bvInput').addEventListener('input', padBvInput);   // text that iOS inserts anyway (it cannot be stopped)
$('#bvInput').addEventListener('keydown', (e) => {
  if (['Enter', 'Tab', 'Escape', 'ArrowUp', 'ArrowDown', 'ArrowLeft', 'ArrowRight'].includes(e.key)) {
    e.preventDefault(); BV.send({ type: 'key', key: e.key });
  }
});


// ---------- permissions tab ----------
const RULE_LABEL = { ask: 'Ask', allow: 'Allow', deny: 'Deny' };
async function loadPermissions() {
  const box = $('#permBody');
  try {
    const p = await api('/api/permissions');
    const rules = p.rules.length ? p.rules.map((r) => `<div class="row rule" data-key="${esc(r.key)}">
        <div class="tx"><b>${esc(r.label)}</b><span>${esc(r.server)}${r.read_only ? ' · reads only' : ' · makes changes'}${r.count ? ` · used ${r.count}×` : ''}</span></div>
        <div class="seg mini">${['ask', 'allow', 'deny'].map((k) => `<button data-rule="${k}" class="${r.rule === k ? 'on' : ''}">${RULE_LABEL[k]}</button>`).join('')}</div>
      </div>`).join('') : '<div class="row"><div class="tx"><span>Tools show up here after Milo uses them. Tap "Always allow" or "Always deny" on a card to make a rule.</span></div></div>';
    box.innerHTML = `
      <div class="group"><h3>How much Milo asks</h3><div class="card">${Object.entries(p.modes).map(([k, v]) =>
        `<div class="row" data-mode="${k}"><span class="radio ${p.mode === k ? 'on' : ''}"></span><div class="tx"><b>${esc(v)}</b><span>${esc(MODE_HELP[k] || '')}</span></div></div>`).join('')}</div></div>
      <div class="group"><h3>Reading</h3><div class="card">
        <div class="row"><div class="tx"><b>Read without asking</b><span>Searching email, reading calendars, files and Slack, listing things, and safe commands such as ls or git status.</span></div>
        <span class="switch ${p.auto_read ? 'on' : ''}" id="autoRead" role="switch" aria-checked="${p.auto_read}"></span></div>
      </div></div>
      <div class="group"><h3>Your rules</h3><div class="card" id="ruleList">${rules}</div>
        ${p.rules.length ? '<div class="btn-row" style="padding:10px 0 0"><button class="small-btn" id="resetRules">Reset all rules</button></div>' : ''}</div>
      <div class="group"><h3>Always asks first</h3><div class="card">
        <div class="row"><div class="tx"><b>Risky browser actions</b><span>Buying, sending, posting, deleting, uploading files. You can allow a site for one task.</span></div></div>
        <div class="row"><div class="tx"><b>Saved passwords</b><span>${p.accounts.length ? p.accounts.map((a) => `${esc(a.label)}: ${a.policy === 'ask' ? 'asks' : 'automatic'}`).join(' · ') : 'No saved accounts yet.'}</span></div><button class="small-btn" id="permAccounts">Accounts</button></div>
      </div></div>`;
  } catch (e) { box.innerHTML = `<div class="empty-state">${esc(e.message)}</div>`; }
}
$('#permBody').addEventListener('click', async (e) => {
  try {
    const mode = e.target.closest('[data-mode]');
    if (mode) {
      if (mode.querySelector('.radio.on')) return;
      return await inFlight(mode.parentElement, async () => {   // each change restarts goose: a double tap does it once
        S.settings = await api('/api/settings', { method: 'PUT', body: { permission_mode: mode.dataset.mode } });
        toast('Permissions updated'); await loadPermissions();
      });
    }
    if (e.target.closest('#autoRead')) {
      const on = !e.target.closest('#autoRead').classList.contains('on');
      await api('/api/permissions', { method: 'PUT', body: { auto_read: on } });
      toast(on ? 'Milo reads without asking' : 'Milo asks before reading too'); return loadPermissions();
    }
    const rule = e.target.closest('[data-rule]');
    if (rule) {
      await api('/api/permissions/rules', { method: 'PUT', body: { key: rule.closest('[data-key]').dataset.key, rule: rule.dataset.rule } });
      return loadPermissions();
    }
    if (e.target.closest('#resetRules')) {
      if (!armed(e.target.closest('#resetRules'))) return;
      await api('/api/permissions/rules', { method: 'DELETE' }); toast('Rules reset'); return loadPermissions();
    }
    if (e.target.closest('#permAccounts')) openSettings();
  } catch (err) { toast(err.message); }
});


// ---------- Google accounts ----------
async function loadGoogle() {
  const box = $('#googleBox'); if (!box) return;
  try {
    const g = await api('/api/google');
    if (!g.configured) {
      box.innerHTML = `<ol class="steps-list">
          <li>Open <b>console.cloud.google.com</b> and create a project named <b>Milo</b>.</li>
          <li>APIs &amp; Services &gt; Library: enable <b>Gmail API</b>, <b>Google Calendar API</b> and <b>Google Drive API</b>.</li>
          <li>OAuth consent screen: <b>External</b>. Add each Google email you want in Milo as a <b>test user</b>.</li>
          <li>Credentials &gt; Create credentials &gt; <b>OAuth client ID</b> &gt; <b>Desktop app</b>. Copy the ID and secret here.</li>
        </ol>
        <form class="form gform" id="gClientForm">
          <input name="client_id" placeholder="Client ID (…apps.googleusercontent.com)" autocapitalize="off" autocomplete="off">
          <input name="client_secret" type="password" placeholder="Client secret" autocomplete="off">
          <button class="small-btn dark" type="submit">Save</button>
        </form>`;
      $('#gClientForm').onsubmit = async (e) => {
        e.preventDefault();
        try { await api('/api/google/client', { method: 'PUT', body: { client_id: e.target.client_id.value, client_secret: e.target.client_secret.value } }); toast('Google API client saved'); loadGoogle(); }
        catch (err) { toast(err.message); }
      };
      return;
    }
    box.innerHTML = (g.accounts.length ? g.accounts.map((a) => `<div class="row" data-gmail="${esc(a.email)}">
        <div class="ic acct-ic">${ICON.key}</div>
        <div class="tx"><b>${esc(a.label)}${a.connected ? '<i class="chip ok-chip">Connected</i>' : a.status === 'expired' ? '<i class="chip ok-chip warn-chip">Expired</i>' : ''}</b><span>${esc(a.email)}</span></div>
        ${a.connected ? '' : '<button class="small-btn dark" data-gsignin>Sign in</button>'}
        <button class="small-btn" data-gremove aria-label="Remove">${ICON.trash}</button></div>`).join('')
      : '<div class="row"><div class="tx"><span>No Google accounts yet. Connect each Gmail you want Milo to use.</span></div></div>')
      + `<div class="btn-row" style="padding:12px 14px"><button class="small-btn dark" id="gConnect">Connect account</button>
         <button class="small-btn" id="gClient">Change API client</button></div>`;
  } catch (e) { box.innerHTML = `<div class="row"><div class="tx"><span>${esc(e.message)}</span></div></div>`; }
}
// Settings stays open under the browser (it sits above the sheets): closing the browser after a sign-in went back
// to the chat, not Settings (BEHAVIOR #91).
function afterGoogleStart(r) {
  if (r.connected) { toast('Already connected'); return loadGoogle(); }
  if (r.where === 'mac') toast('Sign in on your Mac, in the page that just opened', 6000);
  else { BV.open(); toast('Sign in to Google here, allow access, then tap Give back', 7000); }
}
document.addEventListener('click', async (e) => {
  try {
    if (e.target.closest('#gConnect')) { $('#googleForm').reset(); $('#googleErr').textContent = ''; return openSheet('googleSheet'); }
    if (e.target.closest('#gClient')) {
      // one form: a second one had no submit handler, so Save sent the secret in the page's URL
      if ($('#gClientForm')) return $('#gClientForm').client_id.focus();
      const box = $('#googleBox');
      box.insertAdjacentHTML('beforeend', `<form class="form gform" id="gClientForm"><input name="client_id" placeholder="New Client ID" autocapitalize="off">
        <input name="client_secret" type="password" placeholder="New Client secret"><button class="small-btn dark" type="submit">Save</button></form>`);
      $('#gClientForm').onsubmit = async (ev) => {
        ev.preventDefault();
        try { await api('/api/google/client', { method: 'PUT', body: { client_id: ev.target.client_id.value, client_secret: ev.target.client_secret.value } }); toast('Saved'); loadGoogle(); }
        catch (err) { toast(err.message); }
      };
      return;
    }
    const row = e.target.closest('[data-gmail]'); if (!row) return;
    const email = row.dataset.gmail;
    if (e.target.closest('[data-gsignin]')) afterGoogleStart(await api(`/api/google/accounts/${encodeURIComponent(email)}/signin`, { method: 'POST', body: {} }));
    if (e.target.closest('[data-gremove]')) {
      if (!armed(e.target.closest('[data-gremove]'), 'Tap again to remove')) return;
      await api(`/api/google/accounts/${encodeURIComponent(email)}`, { method: 'DELETE' }); toast('Removed'); loadGoogle();
    }
  } catch (err) { toast(err.message); }
});
$('#googleForm').onsubmit = async (e) => {
  e.preventDefault();
  await inFlight(e.target, async () => {
    try {
      const r = await api('/api/google/accounts', { method: 'POST', body: { email: e.target.email.value, label: e.target.label.value } });
      document.activeElement?.blur(); closeSheet('googleSheet'); afterGoogleStart(r);
    } catch (err) { $('#googleErr').textContent = err.message; }
  });
};

// ---------- sheets and menu ----------
// Sheets slide up and the menu slides in from the left. Both animate out before they hide.
function openSheet(id) {
  const el = $(`#${id}`);
  clearTimeout(el._hide);
  if (document.activeElement === input) input.blur();
  el.hidden = false;
  el.getBoundingClientRect();   // start the transition from the hidden position
  el.classList.add('open');
  if (id === 'drawer') document.documentElement.classList.add('menu');
}
function closeSheet(id) {
  const el = $(`#${id}`);
  if (el.hidden) return;
  el.classList.remove('open', 'dragging');
  el.querySelector('.drawer-panel, .sheet-panel').style.transform = '';
  el.style.background = '';
  if (id === 'drawer') { document.documentElement.classList.remove('menu'); $('#app').style.translate = ''; }
  clearTimeout(el._hide);
  el._hide = setTimeout(() => { el.hidden = true; }, 300);
}
document.addEventListener('click', (e) => {
  const c = e.target.closest('[data-close]');
  if (c) return closeSheet(c.dataset.close);
  if (e.target.classList.contains('sheet') || e.target.classList.contains('drawer')) closeSheet(e.target.id);
});
// Pull a sheet down to close it, as on iOS: by its header, or by its content when that is scrolled to the top
// (On each sheet, not the document: a touchmove listener that can cancel makes every scroll wait for it.)
$$('.sheet').forEach((sheet) => {
  let d = null;
  sheet.addEventListener('touchstart', (e) => {
    if (d?.moving) return;
    const panel = e.target.closest('.sheet.open .sheet-panel'), body = e.target.closest('.sheet-body');
    const t = e.touches[0];
    d = !panel || e.touches.length > 1 || (body && body.scrollTop > 0) || e.target.closest('input, textarea, select, [contenteditable]') ? null
      : { panel, sheet, x: t.clientX, y: t.clientY, dy: 0, v: 0, at: performance.now(), moving: false };
  }, { passive: true });
  sheet.addEventListener('touchmove', (e) => {
    if (!d) return;
    const t = e.touches[0], dx = t.clientX - d.x, dy = t.clientY - d.y, now = performance.now();
    if (!d.moving) {   // decided on the first move: iOS won't let a scroll that started be stopped
      if (e.touches.length > 1 || dy <= 0 || Math.abs(dx) >= dy) { d = null; return; }
      d.moving = true; d.sheet.classList.add('dragging');
    }
    e.preventDefault();
    const y = Math.max(0, dy);
    d.v = (y - d.dy) / Math.max(1, now - d.at); d.dy = y; d.at = now;
    d.panel.style.transform = `translateY(${y}px)`;
  }, { passive: false });
  const end = () => {
    const g = d; d = null;
    if (!g?.moving) return;
    g.sheet.classList.remove('dragging');
    if (g.dy > Math.min(140, g.panel.offsetHeight / 3) || g.v > 0.6) closeSheet(g.sheet.id);   // it slides on down
    else g.panel.style.transform = '';
  };
  sheet.addEventListener('touchend', end);
  sheet.addEventListener('touchcancel', end);
});
function openMenu() { $('#convSearch').value = ''; renderDrawer(); openSheet('drawer'); }
$('#menuBtn').onclick = openMenu;
// "..." menu
function closeMore() {
  const m = $('#moreMenu');
  if (m.hidden || m.classList.contains('closing')) return;
  m.classList.add('closing');
  setTimeout(() => { m.hidden = true; m.classList.remove('closing'); }, 140);
}
$('#moreBtn').onclick = (e) => {
  e.stopPropagation();
  $('#moreRename').hidden = !(S.tab === 'chat' && !S.onMain && curConv());   // side chats only
  if ($('#moreMenu').hidden) $('#moreMenu').hidden = false; else closeMore();
};
document.addEventListener('pointerdown', (e) => { if (!$('#moreMenu').hidden && !e.target.closest('#moreMenu, #moreBtn')) closeMore(); });
$('#moreMenu').addEventListener('click', (e) => {
  const b = e.target.closest('[data-more]');
  if (!b) return;
  closeMore();
  ({ new: () => { newChat(); focusBox(); }, rename: () => openRename(S.current), voice: () => Voice.enter(), browser: () => BV.open(), settings: openSettings })[b.dataset.more]();
});
$('#drawerNew').onclick = () => { closeSheet('drawer'); newChat(); setTimeout(focusBox, 320); };
$('#convSearch').addEventListener('input', renderDrawer);

// Swipe right from the left edge to open the menu; swipe left to close it.
(() => {
  let drag = null;
  const W = () => $('.drawer-panel').offsetWidth || 320;
  document.addEventListener('touchstart', (e) => {
    const t = e.touches[0], open = !$('#drawer').hidden && $('#drawer').classList.contains('open');
    if (e.touches.length !== 1) return;
    // not under a full-screen view: the menu would open unseen behind it
    if (!open && t.clientX < 28 && !document.querySelector('.sheet.open, #voice:not([hidden]), #bview:not([hidden]), #fileView:not([hidden]), #mediaView:not([hidden]), #postView:not([hidden]), #pair:not([hidden])')) drag = { x: t.clientX, y: t.clientY, open: false, dx: 0 };
    else if (open) drag = { x: t.clientX, y: t.clientY, open: true, dx: 0 };
  }, { passive: true });
  document.addEventListener('touchmove', (e) => {
    if (!drag) return;
    const t = e.touches[0], dx = t.clientX - drag.x, dy = t.clientY - drag.y;
    if (!drag.moving) {
      if (Math.abs(dy) > Math.abs(dx) || Math.abs(dx) < 10) { if (Math.abs(dy) > 10) drag = null; return; }
      drag.moving = true;
      if (!drag.open) { renderDrawer(); $('#drawer').hidden = false; if (document.activeElement === input) input.blur(); }   // as openSheet: the keyboard goes down
      clearTimeout($('#drawer')._hide);   // a menu still sliding shut would hide under the finger, leaving the app pushed aside
      $('#drawer').classList.add('dragging'); document.documentElement.classList.add('dragging');
    }
    const w = W(), pos = Math.max(0, Math.min(w, (drag.open ? w : 0) + dx));
    drag.dx = dx;
    $('.drawer-panel').style.transform = `translateX(${pos - w}px)`;
    $('#drawer').style.background = `rgba(0,0,0,${0.25 * pos / w})`;
    $('#app').style.translate = `${pos}px 0`;
  }, { passive: true });
  document.addEventListener('touchend', () => {
    if (!drag) return;
    const d = drag; drag = null;
    if (!d.moving) return;
    const el = $('#drawer');
    el.classList.remove('dragging'); document.documentElement.classList.remove('dragging');
    $('.drawer-panel').style.transform = ''; el.style.background = ''; $('#app').style.translate = '';
    const keep = d.open ? d.dx > -W() / 3 : d.dx > W() / 3;
    if (keep) { el.classList.add('open'); document.documentElement.classList.add('menu'); } else { el.classList.add('open'); closeSheet('drawer'); }
  });
})();

// ---------- splash ----------
// three.js is cached after the first launch. If the 3D hello is slow or fails, fade out rather than hold up the app.
function startSplash() {
  const el = $('#splash'); if (!el) return;
  const skip = () => { el.classList.add('out'); setTimeout(() => el.remove(), 400); };
  const late = setTimeout(skip, 2500);
  import('./mascot.js').then((m) => { clearTimeout(late); if (el.isConnected) m.playSplash(el); }).catch(skip);
}
startSplash();

// ---------- pairing and boot ----------
function showPair(err) {
  $('#pair').hidden = false;
  $('#pairErr').textContent = err || '';
  store.del('token');
}
$('#tokenSave').onclick = () => {
  const t = $('#tokenInput').value.trim();
  if (!t) return;
  store.set('token', t); location.reload();
};

function renderAll() {
  setTitle(); renderMessages(true); renderComposer(); renderDrawer(); renderApprovals();
}

async function refresh() {
  try {
    const st = await api('/api/state');
    S.convs = st.conversations; S.mainId = st.mainId; S.settings = st.settings; S.modes = st.modes; S.vapidKey = st.vapidKey; S.voiceInput = st.voiceInput;
    S.approvals = new Map(st.approvals.map((a) => [a.id, a]));
    S.browser = st.browser || {}; renderBrowserBits();
    if (S.current && document.visibilityState === 'visible') Seen.mark(S.current);
    const id = S.current;
    if (id && S.convs.some((c) => c.id === id)) {
      const c = await fetchConv(id, true);
      if (S.current === id) { S.conv = c; replayMissed(c); }   // you may have opened another chat while it loaded
    } else if (id) {   // deleted while the app was away: its "deleted" event never came, and a message would go nowhere
      Chats.delete(id);
      if (S.tab !== 'chat') loadTab(S.tab);
      return openMain(S.tab !== 'chat');
    }
    // Coming back keeps what you were reading: the chat stays where you scrolled (it follows only at the end), and
    // the tab keeps its folder and the menu stays open.
    setTitle(); renderMessages(); renderComposer(); renderDrawer(); renderApprovals();
    if (S.tab !== 'chat') loadTab(S.tab);
  } catch (e) { console.warn('refresh', e); }
}

// A tapped notification opens its chat. The service worker says which three ways (sw.js), as iOS drops one or another:
// a note in the cache, a message, and the #c= link of a window it opens. iOS brings the app back (or starts it, or
// reloads a page it had put away, on the link of the chat that was open) before or after the worker runs, so the
// note is read on start and for a few seconds after each return, and a tap always beats the link the page loaded on.
const Tap = {
  seen: new Set(), pending: null, ready: false,
  async note() {   // the worker's note: a fresh tap that was not opened yet
    try {
      const cache = await caches.open('milo-open'), r = await cache.match('/__open');
      if (!r) return null;
      let t = null;
      try { t = JSON.parse(await r.clone().text()); } catch {   // an old worker's note: the link, its time in the header
        t = { url: await r.text(), at: +new Date(r.headers.get('date') || 0) };
        t.n = `${t.at}`;
      }
      await cache.delete('/__open');
      if (!t || Date.now() - (t.at || 0) > 120000) return null;
      return t;
    } catch { return null; }
  },
  chatOf(t) { return t?.chat || new URLSearchParams((t?.url || '').split('#')[1] || '').get('c') || null; },
  take(t) {   // each tap once: the note and the message are the same tap
    const id = this.chatOf(t);
    if (!id || (t.n && this.seen.has(t.n))) return;
    if (t.n) this.seen.add(t.n);
    if (!this.ready) { this.pending = id; return; }   // boot opens it
    this.go(id);
  },
  go(id) {
    for (const el of $$('.sheet:not([hidden])')) closeSheet(el.id);
    if (!$('#fileView').hidden) closeFile();
    if (!$('#mediaView').hidden) closeMedia();
    closePostView();
    if (S.tab !== 'chat') switchTab('chat'); else closeSheet('drawer');
    if (id !== S.current || !S.conv) this.open(id);
  },
  // A tap is kept until its chat is on screen (openConv's show): iOS often brings the app back before its network
  // (Tailscale) is up, so the first load fails. It is tried again with a growing wait, when the browser is back online
  // and after the socket reconnects, until it opens or you go somewhere else (another chat or tab).
  want: null, nav: 0, wait: 500,
  open(id) {
    this.done(); this.want = id;
    const p = openConv(id);
    this.nav = S.nav;   // openConv counts its navigation before it waits
    return p;
  },
  done() { this.want = null; clearTimeout(this.again); this.wait = 500; },
  failed(id, my) {
    if (id !== this.want || my !== this.nav) return;
    clearTimeout(this.again);
    this.again = setTimeout(() => this.retry(), this.wait);
    this.wait = Math.min(this.wait * 2, 30000);
  },
  retry() {
    if (!this.want) return;
    clearTimeout(this.again);
    if (S.nav !== this.nav || S.tab !== 'chat') return this.done();   // you moved on
    openConv(this.want, true);
    this.nav = S.nav;
  },
  async check() { const t = await this.note(); if (t) this.take(t); },
  watch() {   // the worker may write its note a moment after the app is back
    clearInterval(this.timer);
    let n = 0;
    this.check();
    this.timer = setInterval(() => { if (++n > 20 || document.hidden) clearInterval(this.timer); else this.check(); }, 250);
  },
};
navigator.serviceWorker?.addEventListener('message', (e) => { if (e.data?.type === 'open') Tap.take(e.data); });
navigator.serviceWorker?.startMessages?.();   // messages sent while the app starts wait here, not get lost
// a return (visibilitychange, pageshow, a thaw after a lock) watches for the note: resumed() near the socket code
addEventListener('focus', () => { if (S.token && Tap.ready) { wake(); Tap.check(); refreshList(); } });
// A desktop window that never hid gets no return: on focus it takes the chat list again, with what was read elsewhere
// (the socket's events cover the rest).
async function refreshList() {
  if (Date.now() - (refreshList.at || 0) < 3000) return;
  refreshList.at = Date.now();
  try {
    const st = await api('/api/state');
    const have = new Set(S.convs.map((c) => c.id));   // new and deleted chats come as events; a reconnect takes all
    for (const c of st.conversations) if (have.has(c.id)) upsertConv(c);
    if (S.current && document.visibilityState === 'visible' && S.tab === 'chat') Seen.mark(S.current);
    renderDrawer();
  } catch {}
}
addEventListener('online', () => { if (S.token && Tap.ready) wake(); Tap.retry(); });
// A link to a chat in an open window (a worker's navigate, or a #c= link): open it. #token= is kept as on start.
addEventListener('hashchange', () => {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get('token')) { store.set('token', hash.get('token')); hash.delete('token'); history.replaceState(null, '', '#' + hash.toString()); }
  const id = hash.get('c');
  if (id && Tap.ready && S.token) Tap.go(id);
});

async function boot() {
  const hash = new URLSearchParams(location.hash.slice(1));
  if (hash.get('token')) { store.set('token', hash.get('token')); hash.delete('token'); history.replaceState(null, '', '#' + hash.toString()); }
  S.token = store.get('token');
  renderIdeas();
  let draft = '';
  try { draft = sessionStorage.getItem('draft') || ''; sessionStorage.removeItem('draft'); } catch {}
  if (!S.token) return showPair();
  await refresh();
  fetchIdeas();
  loadFeed();   // for the dot on the tab
  // a tap beats the link: after a reload or a restart iOS loads the link of the chat that was open, not the tapped one
  const t = await Tap.note();
  if (t) Tap.take(t);
  const tapped = Tap.pending, c = tapped || hash.get('c');
  Tap.ready = true; Tap.pending = null;
  if (tapped) await Tap.open(tapped); else if (c) await openConv(c); else await openMain();
  if (draft) { input.value = draft; input.dispatchEvent(new Event('input')); }   // after the chat opened: drafts go with chats
  if (tapped) { try { sessionStorage.removeItem('view'); } catch {} } else restoreView();   // the tapped chat, at its end
  Tap.watch();
  $('#greeting').textContent = greeting();
  placeTabPill(false);
  connect();
  if ('serviceWorker' in navigator) navigator.serviceWorker.register('/sw.js').catch(() => {});
}
function greeting() {
  const h = new Date().getHours();
  return h < 5 ? 'Up late? How can I help?' : h < 12 ? 'Good morning. What can I take off your plate?' : h < 18 ? 'Good afternoon. What can I take off your plate?' : 'Good evening. What can I take off your plate?';
}
boot();
