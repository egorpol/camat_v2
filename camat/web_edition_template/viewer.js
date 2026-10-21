// camat web-edition viewer: the MEI of each work rendered by Verovio with its
// encoded page and system breaks, the editorial notes, and, when the site has
// one, a facsimile beside it with a zone for every bar. Built by
// camat.web_edition from a site config (the JSON in index.html) and works.json;
// the facsimile comes from an adapter module, facsimile-<type>.js.

const VEROVIO_URL = 'https://cdn.jsdelivr.net/npm/verovio@6.3.0/dist/verovio-toolkit-wasm.js';
const VEROVIO_SRI = 'sha384-7oICD/hf52uWdE8X0lMFqe7iIspaUj3aQjeZUnBQZpxjrZcHtqlRd3C78cje2e19';
const XML_NS = 'http://www.w3.org/XML/1998/namespace';
const SVG_NS = 'http://www.w3.org/2000/svg';

const CONFIG = JSON.parse(document.getElementById('site-config').textContent);
const LABELS = CONFIG.labels;
// Every site under one github.io user shares an origin: keys carry the site's prefix.
const storageKey = (name) => `${CONFIG.prefix}-${name}`;
const SETTINGS = { markNotes: storageKey('mark-notes'), measureBoxes: storageKey('measure-boxes') };

const $ = (id) => document.getElementById(id);
const xmlId = (el) => el.getAttributeNS(XML_NS, 'id');
const refs = (value) => (value || '').split(/\s+/).filter(Boolean).map((v) => v.replace(/^#/, ''));

const state = { work: null, model: null, page: 1, pinned: null, annot: null };
const settings = { markNotes: false, measureBoxes: false };
const models = new Map();
let works = [];
let toolkit = null;
let facs = null; // the facsimile adapter, when the site has a facsimile
let workToken = 0;
let facsToken = 0;

// ---------------------------------------------------------------- loading

function loadVerovio() {
  return new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = VEROVIO_URL;
    script.integrity = VEROVIO_SRI;
    script.crossOrigin = 'anonymous';
    // The load event fires right after the script ran, before the wasm is ready.
    script.onload = () => { verovio.module.onRuntimeInitialized = () => resolve(new verovio.toolkit()); };
    script.onerror = () => reject(new Error('Verovio could not be loaded from jsDelivr.'));
    document.head.append(script);
  });
}

async function fetchJson(file) {
  const response = await fetch(file);
  if (!response.ok) throw new Error(`${file}: HTTP ${response.status}`);
  return response.json();
}

function getModel(work) {
  if (!models.has(work.id)) {
    models.set(work.id, fetch(work.mei).then(async (response) => {
      if (!response.ok) throw new Error(`${work.mei}: HTTP ${response.status}`);
      return readModel(work, await response.text(), new URL(work.mei, location.href));
    }));
  }
  return models.get(work.id);
}

function enclosingMeasure(el) {
  for (let node = el; node; node = node.parentElement) {
    if (node.localName === 'measure') return xmlId(node);
  }
  return null;
}

function readModel(work, text, url) {
  const doc = new DOMParser().parseFromString(text, 'application/xml');
  if (doc.getElementsByTagName('parsererror').length) throw new Error(`${workName(work)}: the MEI is not well-formed.`);
  const model = {
    work, text, url, ids: new Map(), measures: new Map(), byN: new Map(), pages: [],
    surfaces: new Map(), zones: new Map(), annots: [], noted: new Set(), svg: new Map(), pageCount: 0,
  };
  const edition = doc.querySelector('editionStmt > edition');
  const version = edition?.getAttribute('n');
  model.edition = edition ? `${edition.textContent.trim()}${version ? ` (version ${version})` : ''}` : '';

  for (const surface of doc.getElementsByTagName('surface')) {
    const graphic = surface.getElementsByTagName('graphic')[0];
    if (!graphic) continue;
    model.surfaces.set(xmlId(surface), {
      id: xmlId(surface),
      file: (graphic.getAttribute('target') || '').split('/').pop(),
      width: Number(graphic.getAttribute('width')),
      height: Number(graphic.getAttribute('height')),
      n: surface.getAttribute('n'),
    });
    for (const zone of surface.getElementsByTagName('zone')) {
      const [ulx, uly, lrx, lry] = ['ulx', 'uly', 'lrx', 'lry'].map((a) => Number(zone.getAttribute(a)));
      model.zones.set(xmlId(zone), { id: xmlId(zone), surface: xmlId(surface), x: ulx, y: uly, w: lrx - ulx, h: lry - uly, measure: null });
    }
  }

  const annots = [];
  for (const el of doc.getElementsByTagName('music')[0].getElementsByTagName('*')) {
    const id = xmlId(el);
    if (el.localName === 'pb') model.pages.push({ n: el.getAttribute('n'), surface: refs(el.getAttribute('facs'))[0] });
    if (el.localName === 'measure' && id) {
      // Bars before the first page break are on Verovio's first page.
      if (!model.pages.length) model.pages.push({ n: null, surface: null });
      const n = el.getAttribute('n');
      // A bar split across systems or pages has a zone on each.
      const zones = refs(el.getAttribute('facs')).filter((z) => model.zones.has(z));
      model.measures.set(id, { id, n, zones, index: model.measures.size, page: model.pages.length });
      if (n && !model.byN.has(n)) model.byN.set(n, id);
      zones.forEach((z) => { model.zones.get(z).measure = id; });
    }
    if (el.localName === 'annot') annots.push(el);
    if (id) model.ids.set(id, { name: el.localName, measure: enclosingMeasure(el) });
  }
  model.annots = annots.map((el) => {
    const targets = refs(el.getAttribute('plist'));
    const bars = [...new Set([xmlId(el), ...targets].map((t) => model.ids.get(t)?.measure).filter(Boolean))]
      .map((m) => model.measures.get(m))
      .filter(Boolean)
      .sort((a, b) => a.index - b.index);
    bars.forEach((bar) => model.noted.add(bar.id));
    return { id: xmlId(el), label: el.getAttribute('label') || el.getAttribute('type') || '', targets, bars, paras: [...el.getElementsByTagName('p')] };
  });
  return model;
}

// ---------------------------------------------------------------- score

const current = () => state.model;
const workName = (work) => work.title || `${LABELS.work} ${work.label}`;

function scoreMessage(text) {
  const p = document.createElement('p');
  p.className = 'message';
  p.textContent = text;
  $('score').replaceChildren(p);
}

function setStatus(text, id = '') {
  const code = document.createElement('code');
  code.textContent = id;
  $('status').replaceChildren(id ? `${text} · ` : text, code);
}

function fillWorkTabs() {
  const tabs = $('works');
  tabs.replaceChildren(...works.map((work) => {
    const button = document.createElement('button');
    button.type = 'button';
    button.setAttribute('role', 'tab');
    button.setAttribute('aria-selected', 'false');
    button.dataset.work = work.id;
    button.textContent = work.label;
    if (work.title) button.title = work.title;
    return button;
  }));
  tabs.hidden = works.length < 2;
}

async function showWork(id) {
  if (state.work === id) return;
  const work = works.find((w) => w.id === id);
  const token = ++workToken;
  scoreMessage(`Loading ${workName(work)}…`);
  const model = await getModel(work);
  if (token !== workToken) return;
  toolkit.loadData(model.text);
  model.pageCount = toolkit.getPageCount();
  Object.assign(state, { work: id, model, pinned: null, annot: null });
  document.querySelectorAll('#works button').forEach((b) => b.setAttribute('aria-selected', String(b.dataset.work === id)));
  $('edition').textContent = model.edition;
  $('edition').hidden = !model.edition;
  renderAnnots(model);
  showPage(1);
}

function showPage(page) {
  const model = current();
  page = Math.min(Math.max(page, 1), model.pageCount);
  if (!model.svg.has(page)) model.svg.set(page, toolkit.renderToSVG(page));
  $('score').innerHTML = model.svg.get(page);
  state.page = page;
  decorate();
  const printed = model.pages[page - 1]?.n;
  $('page-label').textContent = `${printed ? `p. ${printed}` : 'page'} (${page}/${model.pageCount})`;
  $('prev').disabled = page <= 1;
  $('next').disabled = page >= model.pageCount;
  applyHighlights();
  renderFacsimile();
}

function svgElement(name, attributes = {}) {
  const el = document.createElementNS(SVG_NS, name);
  Object.entries(attributes).forEach(([k, v]) => el.setAttribute(k, v));
  return el;
}

// A box behind every rendered bar, shown by the display settings. It covers
// the bar's staves only: Verovio draws a spanner in the bar where it starts,
// so a tie, a slur or a beam across the barline would stretch a box of the
// whole g.measure over the next bars. An empty text draws nothing, but Chrome
// counts it as a point at (0, 0) in getBBox and stretches the box to the page
// corner; hide it first.
function decorate() {
  const model = current();
  for (const text of $('score').querySelectorAll('g.measure text')) {
    if (!text.textContent.trim()) text.setAttribute('display', 'none');
  }
  for (const g of $('score').querySelectorAll('g.measure')) {
    const staves = [...g.querySelectorAll(':scope > g.staff')].map((s) => s.getBBox());
    if (!model.measures.has(g.id) || !staves.length) continue;
    const x = Math.min(...staves.map((b) => b.x));
    const y = Math.min(...staves.map((b) => b.y));
    const width = Math.max(...staves.map((b) => b.x + b.width)) - x;
    const height = Math.max(...staves.map((b) => b.y + b.height)) - y;
    const rect = svgElement('rect', { x, y, width, height, class: 'measure-box' });
    if (model.noted.has(g.id)) rect.classList.add('has-note');
    g.prepend(rect);
  }
}

// Every rendered fragment of an element: the element itself and the
// continuations Verovio draws after a system break (class "id-<xml:id>").
function svgNodes(id) {
  return $('score').querySelectorAll(`[id="${CSS.escape(id)}"], .id-${CSS.escape(id)}`);
}

function zoneRects() {
  return $('zones') ? [...$('zones').children] : [];
}

function applyHighlights() {
  const model = current();
  document.querySelectorAll('.is-pinned, .is-annot, .is-noted').forEach((n) => n.classList.remove('is-pinned', 'is-annot', 'is-noted'));
  if (!model) return;
  if (state.pinned) svgNodes(state.pinned).forEach((n) => n.classList.add('is-pinned'));
  if (settings.markNotes) model.annots.forEach((a) => a.targets.forEach((t) => svgNodes(t).forEach((n) => n.classList.add('is-noted'))));
  const annot = state.annot && model.annots.find((a) => a.id === state.annot);
  annot?.targets.forEach((t) => svgNodes(t).forEach((n) => n.classList.add('is-annot')));
  for (const rect of zoneRects()) rect.classList.toggle('is-pinned', rect.dataset.measure === state.pinned);
  document.querySelectorAll('.notes li > button').forEach((b) => b.setAttribute('aria-pressed', String(b.dataset.annot === state.annot)));
}

function applySettings() {
  for (const el of [$('score'), document.querySelector('.facs-page')].filter(Boolean)) {
    el.classList.toggle('mark-notes', settings.markNotes);
    el.classList.toggle('show-boxes', settings.measureBoxes);
  }
  applyHighlights();
}

function pin(measureId, { hash = true } = {}) {
  const model = current();
  const measure = model.measures.get(measureId);
  if (!measure) return;
  state.pinned = measureId;
  if (hash && measure.n) history.replaceState(null, '', `#${encodeURIComponent(model.work.id)}/${encodeURIComponent(measure.n)}`);
  if (measure.page !== state.page) showPage(measure.page);
  else applyHighlights();
  setStatus(`${workName(model.work)}, ${LABELS.bar} ${measure.n ?? '?'}`, measureId);
}

// Hover colours one element in the score (a note, or the bar from a zone)
// and outlines its bar's zones on the facsimile.
function hover(id, measureId) {
  document.querySelectorAll('.is-hover').forEach((n) => n.classList.remove('is-hover'));
  if (id) svgNodes(id).forEach((n) => n.classList.add('is-hover'));
  for (const rect of zoneRects()) rect.classList.toggle('is-hover', Boolean(measureId) && rect.dataset.measure === measureId);
}

// The nearest rendered ancestor that carries an xml:id from the MEI.
function sourceElement(target) {
  const model = current();
  for (let node = target; node && node !== $('score'); node = node.parentElement) {
    if (model.ids.has(node.id)) return node.id;
    const token = [...node.classList].find((c) => c.startsWith('id-') && model.ids.has(c.slice(3)));
    if (token) return token.slice(3);
  }
  return null;
}

function inspect(target) {
  const model = current();
  const id = model && sourceElement(target);
  if (!id) { hover(null); return; }
  const info = model.ids.get(id);
  const measure = model.measures.get(info.measure);
  hover(id, info.measure);
  setStatus(measure ? `${LABELS.bar} ${measure.n ?? '?'}, ${info.name}` : info.name, id);
}

// ---------------------------------------------------------------- notes

// Links in notes resolve against ref_base, or else against the MEI file; only
// http(s) targets become links.
function inlineText(node, parent, model) {
  for (const child of node.childNodes) {
    if (child.nodeType === Node.TEXT_NODE) parent.append(child.textContent.replace(/\s+/g, ' '));
    else if (child.localName === 'ref' && child.getAttribute('target')) {
      const url = new URL(child.getAttribute('target'), CONFIG.ref_base || model.url);
      const a = document.createElement(['http:', 'https:'].includes(url.protocol) ? 'a' : 'span');
      if (a.localName === 'a') a.href = url.href;
      inlineText(child, a, model);
      parent.append(a);
    } else if (child.nodeType === Node.ELEMENT_NODE) inlineText(child, parent, model);
  }
}

function renderAnnots(model) {
  const list = $('annots');
  list.replaceChildren();
  for (const annot of model.annots) {
    const li = document.createElement('li');
    const button = document.createElement('button');
    button.type = 'button';
    button.dataset.annot = annot.id;
    const first = annot.bars[0]?.n;
    const last = annot.bars.at(-1)?.n;
    const where = document.createElement('span');
    where.className = 'where';
    where.textContent = !annot.bars.length ? '–' : first === last ? `${LABELS.bar} ${first}` : `${LABELS.bars} ${first}–${last}`;
    const label = document.createElement('span');
    label.className = 'label';
    label.textContent = annot.label.replace(/-/g, ' ');
    button.append(where, label);
    li.append(button);
    for (const para of annot.paras) {
      const p = document.createElement('p');
      inlineText(para, p, model);
      li.append(p);
    }
    list.append(li);
  }
  $('notes-heading').textContent = `${LABELS.notes} (${model.annots.length})`;
  $('notes').hidden = !model.annots.length;
}

function selectAnnot(id) {
  const annot = current().annots.find((a) => a.id === id);
  state.annot = state.annot === id ? null : id;
  if (state.annot && annot.bars.length) pin(annot.bars[0].id);
  else applyHighlights();
}

// ---------------------------------------------------------------- facsimile

function showFacsError(text) {
  $('facs-error').textContent = text;
  $('facs-error').hidden = !text;
}

// The adapter calls this when it has a source to draw from (true) or none.
function showFacsView(shown) {
  $('facs-view').hidden = !shown;
  $('facs-intro').hidden = shown;
  if (shown) renderFacsimile();
}

async function renderFacsimile() {
  const model = current();
  if (!facs?.active() || !model) return;
  const token = ++facsToken;
  const canvas = $('facs-canvas');
  const zones = $('zones');
  const surface = model.surfaces.get(model.pages[state.page - 1]?.surface);
  if (!surface) {
    canvas.width = 0;
    zones.replaceChildren();
    $('facs-label').textContent = 'No facsimile page is linked to this page.';
    return;
  }
  const pixels = (canvas.parentElement.clientWidth || 600) * (window.devicePixelRatio || 1);
  let image;
  try {
    image = await facs.draw(surface, pixels, () => token !== facsToken);
  } catch (error) {
    if (token === facsToken) showFacsError(error.message);
    return;
  }
  if (!image || token !== facsToken) return;
  showFacsError('');
  canvas.width = image.width;
  canvas.height = image.height;
  canvas.getContext('2d').drawImage(image, 0, 0);
  // Zones are in pixels of the surface's graphic; the viewBox scales them by width.
  zones.setAttribute('viewBox', `0 0 ${surface.width} ${surface.height}`);
  zones.replaceChildren(...[...model.zones.values()]
    .filter((z) => z.surface === surface.id && z.measure)
    .map((z) => {
      const rect = svgElement('rect', { x: z.x, y: z.y, width: z.w, height: z.h });
      rect.dataset.measure = z.measure;
      rect.dataset.zone = z.id;
      if (model.noted.has(z.measure)) rect.classList.add('has-note');
      return rect;
    }));
  $('facs-label').textContent = facs.label(surface);
  applyHighlights();
}

async function loadFacsimile() {
  const adapter = await import(`./facsimile-${CONFIG.facsimile.type}.js`);
  return adapter.create({
    config: CONFIG.facsimile, labels: LABELS, $, storageKey,
    showError: showFacsError, show: showFacsView, render: renderFacsimile,
  });
}

// ---------------------------------------------------------------- wiring

// #<work>/<bar>: the bar is its @n; a number also matches without leading zeros.
function parseHash() {
  const match = /^#([^/]+)(?:\/(.+))?$/.exec(location.hash);
  if (!match) return {};
  try {
    return { work: decodeURIComponent(match[1]), bar: match[2] === undefined ? undefined : decodeURIComponent(match[2]) };
  } catch {
    return {};
  }
}

async function applyHash() {
  const { work, bar } = parseHash();
  await showWork(works.some((w) => w.id === work) ? work : state.work || works[0].id);
  if (bar === undefined) return;
  const model = current();
  const id = model.byN.get(bar) ?? (/^\d+$/.test(bar) ? model.byN.get(String(Number(bar))) : undefined);
  if (id) pin(id, { hash: false });
  else setStatus(`${LABELS.bar} ${bar} is not in ${workName(model.work)}.`);
}

function readSettings() {
  for (const [name, key] of Object.entries(SETTINGS)) {
    try { settings[name] = localStorage.getItem(key) === '1'; } catch { /* storage blocked: defaults */ }
  }
  $('mark-notes').checked = settings.markNotes;
  $('measure-boxes').checked = settings.measureBoxes;
}

function changeSetting(name, value) {
  settings[name] = value;
  try { localStorage.setItem(SETTINGS[name], value ? '1' : '0'); } catch { /* not remembered */ }
  applySettings();
}

function bindUi() {
  $('works').addEventListener('click', (e) => {
    const button = e.target.closest('button[data-work]');
    if (button) location.hash = `#${encodeURIComponent(button.dataset.work)}`;
  });
  $('prev').addEventListener('click', () => showPage(state.page - 1));
  $('next').addEventListener('click', () => showPage(state.page + 1));
  $('mark-notes').addEventListener('change', (e) => changeSetting('markNotes', e.target.checked));
  $('measure-boxes').addEventListener('change', (e) => changeSetting('measureBoxes', e.target.checked));
  document.addEventListener('keydown', (e) => {
    if (!current() || e.altKey || e.ctrlKey || e.metaKey || e.target.closest('input, textarea, select')) return;
    if (e.key === 'ArrowLeft') showPage(state.page - 1);
    if (e.key === 'ArrowRight') showPage(state.page + 1);
  });
  window.addEventListener('hashchange', () => applyHash().catch((e) => scoreMessage(e.message)));

  const score = $('score');
  score.addEventListener('mouseover', (e) => inspect(e.target));
  score.addEventListener('mouseleave', () => hover(null));
  score.addEventListener('click', (e) => {
    const id = current() && sourceElement(e.target);
    const measure = id && current().ids.get(id).measure;
    if (measure) pin(measure);
  });

  $('annots').addEventListener('click', (e) => {
    const button = e.target.closest('button[data-annot]');
    if (button) selectAnnot(button.dataset.annot);
  });

  if (!$('facs')) return;
  const zones = $('zones');
  zones.addEventListener('mouseover', (e) => {
    const measure = current()?.measures.get(e.target.dataset?.measure);
    if (!measure) return;
    hover(measure.id, measure.id);
    setStatus(`${LABELS.bar} ${measure.n ?? '?'}, zone`, e.target.dataset.zone);
  });
  zones.addEventListener('mouseleave', () => hover(null));
  zones.addEventListener('click', (e) => { if (e.target.dataset?.measure) pin(e.target.dataset.measure); });
  $('facs-close').addEventListener('click', () => {
    facs?.close();
    showFacsView(false);
  });
  let lastWidth = 0;
  new ResizeObserver(([entry]) => {
    const width = Math.round(entry.contentRect.width);
    if (width !== lastWidth) { lastWidth = width; renderFacsimile(); }
  }).observe($('facs'));
}

async function main() {
  readSettings();
  bindUi();
  applySettings();
  try {
    works = (await fetchJson('works.json')).works;
    fillWorkTabs();
    if (CONFIG.facsimile) facs = await loadFacsimile();
    toolkit = await loadVerovio();
    toolkit.setOptions(CONFIG.verovio);
    $('verovio-version').textContent = toolkit.getVersion();
    await applyHash();
  } catch (error) {
    scoreMessage(error.message);
    return;
  }
  facs?.restore();
}

main();
