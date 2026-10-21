// IIIF facsimile adapter for the camat web-edition viewer. Each surface's
// <graphic> is an IIIF Image API request (…/full/<size>/<rotation>/<quality>.<format>),
// as camat's IIIF integration writes it, and the zones are in pixels of that
// graphic. A page is requested at the width the pane needs, in steps of 500
// pixels and never wider than the graphic, then drawn at the graphic's shape,
// so the zones line up by width alone. Shown at once, or after the visitor
// confirms a notice.

const IIIF_TAIL = /\/full\/[^/]+\/([^/]+)\/([^/.]+)\.([A-Za-z0-9]+)$/;
const STEP = 500;

export function create(core) {
  const { config, $ } = core;
  const confirmedKey = core.storageKey('scan-confirmed');
  let shown = false;
  const loaded = new Map(); // surface id → { width, image: Promise<HTMLImageElement> }

  const requestWidth = (surface, pixels) => Math.min(surface.width, Math.ceil(pixels / STEP) * STEP);

  // The same request with another size: rotation, quality and format stay.
  function imageUrl(surface, width) {
    const match = IIIF_TAIL.exec(surface.target);
    if (!match) throw new Error(`${surface.target} is not an IIIF Image API request.`);
    return `${surface.target.slice(0, match.index)}/full/${width},/${match[1]}/${match[2]}.${match[3]}`;
  }

  // An image at least `width` pixels wide; a wider one already loaded serves too.
  function load(surface, width) {
    const cached = loaded.get(surface.id);
    if (cached && cached.width >= width) return cached.image;
    const url = imageUrl(surface, width);
    const image = new Image();
    image.src = url;
    const ready = image.decode().then(() => image, () => {
      if (loaded.get(surface.id)?.image === ready) loaded.delete(surface.id);
      throw new Error(`The facsimile page could not be loaded from the image server: ${url}`);
    });
    loaded.set(surface.id, { width, image: ready });
    return ready;
  }

  async function draw(surface, pixels) {
    const image = await load(surface, requestWidth(surface, pixels));
    const expected = surface.width / surface.height;
    const warning = $('facs-warning');
    warning.hidden = Math.abs(image.naturalWidth / image.naturalHeight - expected) <= 0.01 * expected;
    warning.textContent = `The image server sent a page of a different shape (${image.naturalWidth}×${image.naturalHeight}) from the one the zones were measured on (${surface.width}×${surface.height}). The bar outlines may not line up.`;
    const scratch = document.createElement('canvas');
    scratch.width = Math.round(pixels);
    scratch.height = Math.round((pixels * surface.height) / surface.width);
    const context = scratch.getContext('2d');
    context.imageSmoothingQuality = 'high';
    context.drawImage(image, 0, 0, scratch.width, scratch.height);
    return scratch;
  }

  // The next page, at the size it will be drawn.
  function prefetch(surface, pixels) {
    if (shown && surface) load(surface, requestWidth(surface, pixels)).catch(() => {});
  }

  function label(surface) {
    const full = document.createElement('a');
    full.href = surface.target;
    full.target = '_blank';
    full.rel = 'noopener';
    full.textContent = 'Full-size image';
    const fragment = document.createDocumentFragment();
    fragment.append(`${surface.n ? `Page ${surface.n}` : surface.file} · `, full);
    return fragment;
  }

  function show({ remember = true } = {}) {
    shown = true;
    if (remember && config.confirm) {
      try { localStorage.setItem(confirmedKey, '1'); } catch { /* not remembered */ }
    }
    core.show(true);
  }

  function close() {
    shown = false;
    try { localStorage.removeItem(confirmedKey); } catch { /* nothing stored */ }
    $('facs-warning').hidden = true;
  }

  // At once, unless the notice was never confirmed in this browser.
  function restore() {
    let confirmed = !config.confirm;
    try { confirmed ||= localStorage.getItem(confirmedKey) === '1'; } catch { /* storage blocked */ }
    if (confirmed) show({ remember: false });
  }

  $('scan-show').addEventListener('click', () => show());

  return { active: () => shown, draw, label, close, restore, prefetch };
}
