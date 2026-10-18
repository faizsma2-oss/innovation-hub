// The library: everything that already exists (tools, guidance, active projects, earlier pilots and
// lessons from the Hub), searchable by everyone. Search runs on the server with word stems and relevance.

let libraryKind = '';
let librarySearchTimer;

let librarySequence = 0;   // only the newest search may update the page (answers can arrive out of order)

async function loadLibrary() {
  const mine = ++librarySequence;
  const q = get('library-search').value.trim();
  const params = new URLSearchParams({q, kind: libraryKind, team: String(currentView === 'reviewer' || libraryFromTeam)});
  try {
    const data = await fetch(`/api/library?${params}`).then(r => r.json());
    if (mine !== librarySequence) return;
    const tabs = {'': 'Everything', tool: 'Tools', guidance: 'Guidance', active_project: 'Active projects', previous_pilot: 'Earlier pilots'};
    get('library-kinds').innerHTML = Object.entries(tabs).map(([key, label]) =>
      `<button type="button" role="tab" data-kind="${key}" aria-selected="${key === libraryKind}">${label}</button>`).join('');
    get('library-results').innerHTML = data.results.length ? data.results.map(libraryCard).join('')
      : `<div class="library-empty"><p><strong>Nothing found for “${escapeText(q)}”.</strong></p>
         <p class="muted">That may be a problem nobody has solved yet. Tell the innovation team about it.</p>
         <button type="button" class="primary" id="library-raise">Describe the problem →</button></div>`;
    get('library-count').textContent = !q ? `${data.count} entries` : !data.count ? 'No results'
      : `${data.count} ${data.count === 1 ? 'result' : 'results'}, best match first`;
    if (get('library-raise')) get('library-raise').onclick = () => { location.hash = 'my-requests'; get('new-problem').click(); };
  } catch (error) {
    get('library-results').innerHTML = `<p class="error-text">Could not load the library. ${escapeText(error.message)}</p>`;
  }
}

// Matched words come back wrapped in \u0002…\u0003; everything else is escaped first, so no HTML can get in.
const marked = (text, plain) => text ? escapeText(text).replace(/\u0002/g, '<mark>').replace(/\u0003/g, '</mark>') : escapeText(plain);

function libraryCard(entry) {
  return `<article class="card library-card">
    <div class="card-top"><span>${escapeText(entry.id)} · ${escapeText(entry.lesson ? 'Lesson from the Hub' : entry.kind_label)}</span>
      <span class="chip chip-${entry.kind === 'previous_pilot' ? 'rec-ask' : entry.kind === 'active_project' ? 'innovation' : 'rec-accept'}">${escapeText(entry.kind_label)}</span></div>
    <h3>${marked(entry.title_marked, entry.title)}</h3>
    <p>${marked(entry.summary_marked, entry.summary)}</p>
    <p class="muted"><strong>${entry.kind === 'tool' || entry.kind === 'guidance' ? 'How to use it' : 'More'}:</strong> ${escapeText(entry.how_to)}</p>
    <p class="muted">Source: ${escapeText(entry.source)}${entry.request ? ` · <button class="link" data-library-record="${escapeText(entry.request)}">open ${escapeText(entry.request)}</button>` : ''}</p>
  </article>`;
}

let libraryFromTeam = false;
document.addEventListener('click', event => {
  const link = event.target.closest('[data-library-record]');
  if (link) { location.hash = 'requests'; openDetail(link.dataset.libraryRecord); }   // the request opens in the team view
});
get('library-nav').onclick = () => { libraryFromTeam = currentView === 'reviewer'; location.hash = 'library'; get('library-search').focus(); };
get('library-search').oninput = () => { clearTimeout(librarySearchTimer); librarySearchTimer = setTimeout(loadLibrary, 300); };
get('library-kinds').addEventListener('click', event => {
  const tab = event.target.closest('[data-kind]');
  if (!tab) return;
  libraryKind = tab.dataset.kind;
  loadLibrary();
});
if (location.hash === '#library') loadLibrary();
