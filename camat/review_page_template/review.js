// Marks and notes of a camat review page, kept in this browser's localStorage.
(() => {
  const DATA = JSON.parse(document.getElementById('review-data').textContent);
  const STORE = 'camat-review:' + DATA.storage_key;
  let state = { marks: {}, notes: {} };
  try {
    const saved = JSON.parse(localStorage.getItem(STORE));
    if (saved && typeof saved === 'object') state = { marks: saved.marks || {}, notes: saved.notes || {} };
  } catch (e) { /* no storage: marks last until the page is closed */ }

  function save() {
    try { localStorage.setItem(STORE, JSON.stringify(state)); } catch (e) { /* see above */ }
  }

  // A card with rows counts as marked once any row is, and as a problem if any row is.
  function cardMark(card) {
    if (!card.rows) return state.marks[card.key] || '';
    const marks = card.rows.map(row => state.marks[row.key]).filter(Boolean);
    return marks.includes('problem') ? 'problem' : marks.length ? 'ok' : '';
  }

  function paint() {
    document.querySelectorAll('.marks').forEach(marks => {
      const value = state.marks[marks.dataset.key] || '';
      marks.querySelectorAll('input').forEach(input => { input.checked = input.value === value; });
      const section = document.getElementById(marks.dataset.key);
      section.classList.toggle('is-ok', value === 'ok');
      section.classList.toggle('is-problem', value === 'problem');
    });
    DATA.cards.forEach(card => {
      const link = document.querySelector(`[data-nav="${CSS.escape(card.key)}"]`);
      const value = cardMark(card);
      link.classList.toggle('ok', value === 'ok');
      link.classList.toggle('problem', value === 'problem');
    });
    const done = DATA.cards.filter(card => cardMark(card)).length;
    const rows = DATA.cards.filter(card => card.rows)
      .map(card => `${card.label} ${card.rows.filter(row => state.marks[row.key]).length}/${card.rows.length}`);
    document.getElementById('count').textContent = [`${done}/${DATA.cards.length} cards`, ...rows].join(' · ');
  }

  function summary() {
    return DATA.cards.map(card => {
      let line;
      if (card.rows) {
        const marked = card.rows.filter(row => state.marks[row.key]);
        line = `${card.label}: ${marked.length}/${card.rows.length} marked`;
        if (marked.length) line += ' (' + marked.map(row => `${row.label} ${state.marks[row.key]}`).join(', ') + ')';
      } else {
        line = `${card.label}: ${state.marks[card.key] || '-'}`;
      }
      const note = (state.notes[card.key] || '').trim().replace(/\s+/g, ' ');
      return note ? `${line} — ${note}` : line;
    }).join('\n');
  }

  document.querySelectorAll('.note textarea').forEach(area => { area.value = state.notes[area.dataset.key] || ''; });
  document.addEventListener('change', event => {
    const marks = event.target.closest('.marks');
    if (marks) {
      if (event.target.value) state.marks[marks.dataset.key] = event.target.value;
      else delete state.marks[marks.dataset.key];
      save();
      paint();
    }
    if (event.target.id === 'show-before') document.body.classList.toggle('no-before', !event.target.checked);
  });
  document.addEventListener('input', event => {
    const area = event.target.closest('.note textarea');
    if (!area) return;
    if (area.value.trim()) state.notes[area.dataset.key] = area.value;
    else delete state.notes[area.dataset.key];
    save();
  });
  document.getElementById('copy').addEventListener('click', () => {
    const text = summary();
    const dialog = document.getElementById('summary');
    const status = document.getElementById('summary-status');
    dialog.querySelector('textarea').value = text;
    const show = message => { status.textContent = message; dialog.showModal(); };
    const fallback = () => {
      show('Select the text and copy it:');
      dialog.querySelector('textarea').select();
    };
    if (navigator.clipboard) navigator.clipboard.writeText(text).then(() => show('Copied to the clipboard:'), fallback);
    else fallback();
  });
  paint();
})();
