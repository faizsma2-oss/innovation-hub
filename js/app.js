// 1. Small helpers keep DOM lookup and safe text rendering readable.
const get = id => document.getElementById(id);
const escapeText = value => String(value ?? '').replace(/[&<>"']/g, character => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[character]));

// The single demo user. The server decides who submitted; this only filters the employee view.
const DEMO_USER = 'demo-employee';

// Mirrors ROUTES in backend/models.py.
const ROUTE_LABELS = {
  incident: 'Incident channel',
  it_support: 'IT support',
  hr: 'HR',
  facilities_procurement: 'Facilities, maintenance or procurement',
  process_owner_innovation: 'Process owner + innovation screening',
  innovation_screening: 'Innovation screening',
  human_triage: 'Human triage',
};
const ROUTINE_ROUTES = ['it_support', 'hr', 'facilities_procurement'];
const OPEN_STATUSES = ['Submitted', 'Routed', 'Needs clarification', 'Under review'];
const FEASIBILITY_LABELS = {ready_to_investigate: 'Ready to investigate', needs_discovery: 'Needs discovery', blocked: 'Blocked'};

// Submissions and measures as last received from the server, and which demo view is showing.
let submissions = [];
let currentView = 'employee';
let currentQueue = 'innovation';

// 2. This is navigation ONLY. It does not enforce real user permissions.
function switchView(view) {
  currentView = view;
  for (const name of ['employee', 'reviewer']) {
    get(`${name}-view`).hidden = name !== view;
    get(`${name}-nav`).setAttribute('aria-pressed', String(name === view));
  }
}
get('employee-nav').onclick = () => switchView('employee');
get('reviewer-nav').onclick = () => switchView('reviewer');

// 3. Ask the server for the data. fetch() sends a request and waits for the reply.
async function loadSubmissions() {
  try {
    const response = await fetch('/api/submissions');
    if (!response.ok) throw new Error(`The server replied with status ${response.status}.`);
    submissions = await response.json();
    get('load-error').hidden = true;
    renderAll();
    renderMeasures(await fetch('/api/metrics').then(reply => reply.json()));
    if (typeof loadMeetings === 'function') loadMeetings();   // js/meetings.js
    if (typeof loadPortfolio === 'function') loadPortfolio(); // js/portfolio.js
  } catch (error) {
    const message = location.protocol === 'file:'
      ? 'This page needs the server. In the terminal run: fastapi dev backend/main.py — then open http://127.0.0.1:8000'
      : `Could not load submissions. ${error.message}`;
    get('load-error').textContent = message;
    get('load-error').hidden = false;
  }
}

// 4. The success measures. Confirmed resolutions count; fewer escalations alone don't.
function renderMeasures(m) {
  const seconds = value => value == null ? '–' : value < 90 ? `${Math.round(value)}s` : `${Math.round(value / 60)} min`;
  const percent = value => value == null ? '–' : `${Math.round(value * 100)}%`;
  const tiles = [
    [seconds(m.submission_time_seconds), 'Median time to submit'],
    [percent(m.routing_accuracy), `Routing accuracy (${m.routing_corrections} corrected)`],
    [seconds(m.reviewer_time_seconds), 'Median reviewer time per request'],
    [m.missed_opportunities, 'Missed opportunities caught'],
    [m.satisfaction == null ? '–' : `${m.satisfaction} / 5`, `Employee ease rating (${m.satisfaction_responses})`],
    [m.confirmed_resolutions, 'Confirmed resolutions'],
    [m.in_operation, 'Improvements in operation'],
    [Object.entries(m.benefits_realised ?? {}).map(([cur, v]) => `${Math.round(v).toLocaleString()} ${cur}`).join(' + ') || '–', 'Benefits realised per year (measured)'],
    [m.lessons_published, 'Lessons published back to intake'],
  ];
  get('measures').innerHTML = tiles.map(([value, label]) =>
    `<div><strong>${escapeText(value)}</strong><span>${escapeText(label)}</span></div>`).join('');
  get('measures-note').textContent = `Agreement with screening: ${percent(m.agreement_rate)} of ${m.decisions} ${m.decisions === 1 ? 'decision' : 'decisions'} · `
    + `${m.auto_declined} auto-declined, ${m.auto_declines_overturned} overturned on appeal · `
    + `${m.employee_requested_open} employee-requested reviews waiting. Fewer escalations alone are not counted as success.`;
}

// 5. Cards. Use escaped text, not raw user-supplied HTML.
function chips(record, forReviewer) {
  const list = [];
  if (record.innovation_track === 'employee_requested') list.push(['requested', 'Innovation review requested']);
  else if (record.innovation_track === 'screening') list.push(['innovation', 'Innovation screening']);
  if (record.linked_to) list.push(['linked', `Linked to ${record.linked_to}`]);
  if (record.status === 'Accepted') list.push(['innovation', record.solutions ? `${record.solutions.options.length} solution options ready` : 'Needs solution options']);
  if (record.status === 'Research') list.push(['rec-accept', `Research: ${record.research.selected_option.title}`]);
  if (record.status === 'Pilot planning') list.push(['rec-accept', `Pilot with ${record.research.pilot.partner}`]);
  if (record.status === 'Pilot running') list.push(['rec-accept', `Pilot running with ${record.research.pilot.partner}`]);
  if (record.status === 'Scaling') list.push(['rec-accept', record.research?.scale?.business_case?.status === 'AWAITING DECISION'
    ? 'Business case awaiting decision' : 'Scaling: business case needed']);
  if (record.status === 'Rolling out') list.push(['rec-accept', 'Rolling out']);
  if (record.status === 'In operation') {
    const result = record.research?.scale?.checkins?.filter(c => c.result).at(-1)?.result;
    list.push(['rec-accept', result ? `In operation · benefit ${result.verdict}` : `In operation · owner ${record.research.scale.rollout.business_owner}`]);
  }
  if (record.status === 'Stopped') list.push(['rec-decline', 'Stopped']);
  if (record.research?.lesson) list.push(['innovation', `Lesson ${record.research.lesson.id} published`]);
  if (forReviewer && record.feasibility && record.innovation_track !== 'none') list.push(['feasibility', FEASIBILITY_LABELS[record.feasibility]]);
  const recommendation = record.recommendation;
  if (forReviewer && recommendation && OPEN_STATUSES.includes(record.status) && !['none', 'route'].includes(recommendation.decision)) {
    list.push([`rec-${recommendation.decision}`, `Recommends: ${recommendation.decision}`]);
  }
  if (forReviewer && recommendation?.auto_applied) list.push(['rec-decline', 'Auto-declined by policy']);
  return list.map(([kind, text]) => `<span class="chip chip-${kind}">${escapeText(text)}</span>`).join('');
}

function renderCards(container, records, forReviewer = false) {
  container.innerHTML = records.length ? records.map(record => `
    <article class="card">
      <div class="card-top"><span>${escapeText(record.id)} · ${escapeText(ROUTE_LABELS[record.route] ?? 'Linked')}</span>
        <span>${forReviewer && record.score != null && record.innovation_track !== 'none'
          ? `<span class="score" title="Priority 0–100; unknown criteria excluded">${record.score}/100</span> ` : ''}<span class="status">${escapeText(record.status)}</span></span></div>
      <h3>${escapeText(record.title)}</h3><p>${escapeText(record.description)}</p>
      <div class="chips">${chips(record, forReviewer)}</div>
      ${record.supporters ? `<p class="supporters">+${record.supporters} linked ${record.supporters === 1 ? 'request' : 'requests'}</p>` : ''}
      <button data-record="${escapeText(record.id)}">View details ↗</button>
    </article>`).join('') : '<p class="muted">Nothing in this queue.</p>';
}

// 6. Reviewer queues. Urgency and innovation potential are separate, so they get separate queues.
const QUEUES = {
  innovation: ['Innovation queue', record => record.innovation_track !== 'none' && OPEN_STATUSES.includes(record.status)],
  requested: ['Employee-requested reviews', record => record.innovation_track === 'employee_requested' && OPEN_STATUSES.includes(record.status)],
  triage: ['Human triage', record => record.route === 'human_triage' && record.innovation_track === 'none' && OPEN_STATUSES.includes(record.status)],
  routed: ['Routed to departments', record => ROUTINE_ROUTES.includes(record.route) && ['Routed', 'Resolved'].includes(record.status)],
  linked: ['Linked', record => record.status === 'Linked'],
  solutions: ['Choose a solution', record => record.status === 'Accepted'],
  research: ['In research', record => record.status === 'Research'],
  pilot: ['Pilots', record => ['Pilot planning', 'Pilot running'].includes(record.status)],
  scaling: ['Scaling and rollout', record => ['Scaling', 'Rolling out'].includes(record.status)],
  operation: ['In operation', record => record.status === 'In operation'],
  stopped: ['Stopped', record => record.status === 'Stopped'],
  declined: ['Declined', record => record.status === 'Declined'],
  all: ['All', () => true],
};
function renderQueues() {
  get('queue-tabs').innerHTML = Object.entries(QUEUES).map(([key, [label, test]]) =>
    `<button role="tab" data-queue="${key}" aria-selected="${key === currentQueue}">${label} <span>${submissions.filter(test).length}</span></button>`).join('');
  const records = submissions.filter(QUEUES[currentQueue][1]);
  if (currentQueue === 'innovation' || currentQueue === 'requested') records.sort((a, b) => (b.score ?? -1) - (a.score ?? -1));
  renderCards(get('review-list'), records, true);
}
get('queue-tabs').addEventListener('click', event => {
  const tab = event.target.closest('[data-queue]');
  if (!tab) return;
  currentQueue = tab.dataset.queue;
  renderQueues();
});

function renderAll() {
  renderCards(get('employee-list'), submissions.filter(record => record.submitted_by === DEMO_USER));
  renderQueues();
}

// 7. Dialogs. Native dialogs provide keyboard focus handling and Escape-to-close.
get('close-form').onclick = () => get('problem-dialog').close();
get('close-detail').onclick = () => get('detail-dialog').close();
document.addEventListener('click', event => {
  const button = event.target.closest('[data-record]');
  if (button) openDetail(button.dataset.record);
});
function openDetail(id) {
  const record = submissions.find(item => item.id === id);
  if (!record) return;
  get('detail-title').textContent = record.title;
  get('detail-meta').textContent = `${record.id} · ${ROUTE_LABELS[record.route] ?? 'Linked'} · ${record.status} · ${new Date(record.created_at).toLocaleDateString()}`;
  renderDetail(record);       // js/review.js
  renderHistory(record.id);   // js/review.js
  if (!get('detail-dialog').open) get('detail-dialog').showModal();
}

// 8. The fallback form. It's routed and screened like a chat request.
get('problem-form').onsubmit = async event => {
  event.preventDefault();
  const form = event.currentTarget;
  const result = get('form-result');
  result.hidden = false;
  result.textContent = 'Saving…';
  try {
    const response = await fetch('/api/submissions', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify(Object.fromEntries(new FormData(form))),
    });
    const reply = await response.json();
    if (!response.ok) {
      const reasons = Array.isArray(reply.detail) ? reply.detail.map(problem => `${problem.loc.at(-1)}: ${problem.msg}`).join('\n') : reply.detail;
      result.textContent = `Not saved.\n${reasons}`;
      return;
    }
    form.reset();
    result.textContent = `Saved as ${reply.id} and sent to ${ROUTE_LABELS[reply.route] ?? 'review'}.`;
    await loadSubmissions();
  } catch (error) {
    result.textContent = `Not saved: could not reach the server. ${error.message}`;
  }
};
get('problem-form').oninput = () => { get('form-result').hidden = true; };

// Which brain is answering: Claude, or the scripted rules.
fetch('/api/health').then(reply => reply.json()).then(health => {
  const claude = health.brain !== 'mock-brain';
  const capped = health.budget?.blocked;
  const ai = claude
    ? `The assistant uses Claude (${health.brain}), checked by plain-code rules, with a scripted fallback.`
    : capped ? `${capped} The scripted assistant is answering instead.`
    : 'The assistant is running on scripted rules: no AI key is configured.';
  get('mode-notice').textContent = health.public_demo
    ? `Public demo: your entries are private to your browser and reset after 24 hours. ${ai}`
    : ai;
  get('assistant-mode').textContent = claude ? 'Powered by Claude, checked by rules.' : 'Scripted rules (no AI key).';
}).catch(() => {});

loadSubmissions();
