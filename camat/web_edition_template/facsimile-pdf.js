// PDF facsimile adapter for the camat web-edition viewer. The pages are those
// of camat.pdf_facsimile's pages.json (schema 1), drawn from the visitor's own
// copy of the PDF with pdf.js, or from hosted page images, shown at once or
// after the visitor confirms a notice. The zones are in pixels of those page
// images, so each hosted image is checked against its hash first, and a PDF
// that differs from the one the pages were rendered from gets a warning.

// pdf.js 6 decodes fax-encoded scans with wasm/jbig2.wasm, which cdnjs does
// not carry; jsDelivr serves the whole npm package.
const PDFJS_URL = 'https://cdn.jsdelivr.net/npm/pdfjs-dist@6.3.289/';
const IMAGE_TYPES = { png: 'image/png', jpg: 'image/jpeg', jpeg: 'image/jpeg' };

const sha256 = async (bytes) => [...new Uint8Array(await crypto.subtle.digest('SHA-256', bytes))]
  .map((b) => b.toString(16).padStart(2, '0')).join('');

export function create(core) {
  const { config, $ } = core;
  const confirmedKey = core.storageKey('scan-confirmed');
  const STORE = { db: core.storageKey('viewer'), store: 'files', key: 'pdf' };
  let manifest = null;
  const manifestReady = fetch(config.pages).then(async (response) => {
    if (!response.ok) throw new Error(`${config.pages}: HTTP ${response.status}`);
    const data = await response.json();
    manifest = { ...data, byImage: new Map(data.pages.map((p) => [p.image.split('/').pop(), p])) };
    return manifest;
  });
  let pdf = null;
  let images = null; // file → Promise<ImageBitmap>, while the hosted images are shown
  let renderTask = null;

  async function pageOf(surface) {
    const page = (await manifestReady).byImage.get(surface.file);
    if (!page) throw new Error(`${surface.file} is not in ${config.pages}.`);
    return page;
  }

  // ------------------------------------------------------------ sources

  function showImages({ remember = true } = {}) {
    core.showError('');
    if (pdf) {
      pdf.loadingTask.destroy();
      pdf = null;
      forgetPdf();
    }
    images = new Map();
    if (remember && config.images.confirm) {
      try { localStorage.setItem(confirmedKey, '1'); } catch { /* not remembered */ }
    }
    $('facs-warning').hidden = true;
    core.show(true);
  }

  const forgetConfirmation = () => {
    try { localStorage.removeItem(confirmedKey); } catch { /* nothing stored */ }
  };

  function hostedImage(page) {
    const cache = images;
    const file = page.image.split('/').pop();
    if (!cache.has(file)) {
      cache.set(file, (async () => {
        const response = await fetch(config.images.url + file);
        if (!response.ok) throw new Error(`${file}: HTTP ${response.status}`);
        const bytes = await response.arrayBuffer();
        if (await sha256(bytes) !== page.sha256) throw new Error(`${file} differs from the page image the zones were measured on.`);
        const type = IMAGE_TYPES[file.split('.').pop().toLowerCase()] || '';
        return createImageBitmap(new Blob([bytes], { type }));
      })().catch((error) => {
        cache.delete(file);
        throw error;
      }));
    }
    return cache.get(file);
  }

  async function openPdf(bytes, name, { remember = true } = {}) {
    core.showError('');
    try {
      const pages = await manifestReady;
      const hash = await sha256(bytes);
      const pdfjs = await import(`${PDFJS_URL}build/pdf.min.mjs`);
      pdfjs.GlobalWorkerOptions.workerSrc = `${PDFJS_URL}build/pdf.worker.min.mjs`;
      // pdf.js transfers the buffer it is given to its worker; keep our copy.
      const doc = await pdfjs.getDocument({ data: bytes.slice(), wasmUrl: `${PDFJS_URL}wasm/` }).promise;
      if (doc.numPages !== pages.page_count) {
        doc.loadingTask.destroy();
        throw new Error(`“${name}” has ${doc.numPages} page${doc.numPages === 1 ? '' : 's'}; the PDF the zones were measured on has ${pages.page_count}. Is it the right PDF?`);
      }
      pdf?.loadingTask.destroy();
      pdf = doc;
      images = null;
      forgetConfirmation();
      const warning = $('facs-warning');
      warning.hidden = hash === pages.pdf_sha256;
      warning.textContent = `This PDF differs from the one the zones were measured on (SHA-256 ${hash.slice(0, 12)}…, expected ${String(pages.pdf_sha256).slice(0, 12)}…). The bar outlines may not line up.`;
      if (remember) storePdf(bytes, name);
      core.show(true);
    } catch (error) {
      core.showError(error.message);
    }
  }

  // ------------------------------------------------------------ drawing

  // Both return an off-screen canvas `pixels` wide, or null when a newer render has taken over.
  async function drawPdfPage(page, pixels, stale) {
    const pdfPage = await pdf.getPage(page.pdf_page_number);
    if (stale()) return null;
    const viewport = pdfPage.getViewport({ scale: pixels / pdfPage.getViewport({ scale: 1 }).width });
    renderTask?.cancel();
    const scratch = document.createElement('canvas');
    scratch.width = Math.round(viewport.width);
    scratch.height = Math.round(viewport.height);
    renderTask = pdfPage.render({ canvas: scratch, viewport });
    try {
      await renderTask.promise;
    } catch (error) {
      if (error?.name === 'RenderingCancelledException') return null;
      throw error;
    }
    return scratch;
  }

  async function drawHostedImage(page, pixels) {
    const image = await hostedImage(page);
    const scratch = document.createElement('canvas');
    scratch.width = Math.round(pixels);
    scratch.height = Math.round((image.height * pixels) / image.width);
    const context = scratch.getContext('2d');
    context.imageSmoothingQuality = 'high';
    context.drawImage(image, 0, 0, scratch.width, scratch.height);
    return scratch;
  }

  async function draw(surface, pixels, stale) {
    const page = await pageOf(surface);
    return images ? drawHostedImage(page, pixels) : drawPdfPage(page, pixels, stale);
  }

  function label(surface) {
    const page = manifest?.byImage.get(surface.file);
    const printed = surface.n || page?.printed_page;
    const where = printed ? `Printed page ${printed}` : `Page ${page?.pdf_page_number ?? '?'}`;
    return pdf ? `${where} (PDF page ${page?.pdf_page_number ?? '?'})` : where;
  }

  function close() {
    pdf?.loadingTask.destroy();
    pdf = null;
    images = null;
    forgetPdf();
    forgetConfirmation();
    $('facs-warning').hidden = true;
    if ($('pdf-input')) $('pdf-input').value = '';
  }

  // ------------------------------------------------------------ storage

  // The chosen PDF is kept in this browser's IndexedDB so a reload shows it again.
  function withStore(mode, action) {
    return new Promise((resolve, reject) => {
      const open = indexedDB.open(STORE.db, 1);
      open.onupgradeneeded = () => open.result.createObjectStore(STORE.store);
      open.onerror = () => reject(open.error);
      open.onsuccess = () => {
        const request = action(open.result.transaction(STORE.store, mode).objectStore(STORE.store));
        request.onsuccess = () => resolve(request.result);
        request.onerror = () => reject(request.error);
      };
    });
  }
  const storePdf = (bytes, name) => withStore('readwrite', (s) => s.put({ bytes, name }, STORE.key)).catch(() => {});
  const forgetPdf = () => (config.pdf ? withStore('readwrite', (s) => s.delete(STORE.key)).catch(() => {}) : Promise.resolve());

  // A stored PDF first; else the hosted images, if they need no confirmation or it was given.
  async function restore() {
    if (config.pdf) {
      try {
        const saved = await withStore('readonly', (s) => s.get(STORE.key));
        if (saved?.bytes) { await openPdf(saved.bytes, saved.name, { remember: false }); return; }
      } catch { /* storage unavailable: the visitor opens the file again */ }
    }
    if (!config.images) return;
    let confirmed = !config.images.confirm;
    try { confirmed ||= localStorage.getItem(confirmedKey) === '1'; } catch { /* storage blocked */ }
    if (confirmed) showImages({ remember: false });
  }

  // ------------------------------------------------------------ wiring

  if (config.images) $('scan-show').addEventListener('click', () => showImages());
  if (config.pdf) {
    const pickFile = async (file) => { if (file) await openPdf(await file.arrayBuffer(), file.name); };
    $('pdf-input').addEventListener('change', (e) => pickFile(e.target.files[0]));
    const facs = $('facs');
    facs.addEventListener('dragover', (e) => { e.preventDefault(); facs.classList.add('is-dragover'); });
    facs.addEventListener('dragleave', () => facs.classList.remove('is-dragover'));
    facs.addEventListener('drop', (e) => {
      e.preventDefault();
      facs.classList.remove('is-dragover');
      pickFile(e.dataTransfer.files[0]);
    });
  }

  return { active: () => Boolean(pdf || images), draw, label, close, restore };
}
