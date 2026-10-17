// Solution options and research: what the reviewer sees after accepting a request.
// The Research AI proposes and scores options; the server calculates the ranking; the team selects.

let researchCriteria = [];
fetch('/api/research/criteria').then(reply => reply.json()).then(list => { researchCriteria = list; }).catch(() => {});

function solutionsHtml(record) {
  if (['Research', 'Pilot planning', 'Pilot running', 'Scaling', 'Stopped'].includes(record.status)) return researchHtml(record);
  if (record.status !== 'Accepted') return '';
  const s = record.solutions;
  if (!s) {
    return `<section class="solutions">
      <div class="research-empty">
        <p class="eyebrow">RESEARCH AI</p>
        <h3>Compare solution approaches</h3>
        <p class="muted">The Research AI proposes 3–5 different approaches, including a simple baseline, and scores each on the
          same criteria. The ranking is calculated from those scores with visible weights. You choose, and then research starts.</p>
        <button class="primary" id="propose-button">Prepare solution options</button>
        <p id="propose-error" class="error-text" role="alert"></p>
      </div>
    </section>`;
  }
  return `<section class="solutions">
    <div class="solutions-head">
      <div><p class="eyebrow">RESEARCH AI</p><h3>Solution options <span class="status">PROPOSED</span></h3></div>
      <p class="muted">Round ${s.round} · ${escapeText(s.generated_by)}${s.feedback ? ` · after feedback: “${escapeText(s.feedback)}”` : ''}</p>
    </div>
    <p class="comparison-text">${escapeText(s.comparison)}</p>
    <div class="option-list">${s.options.map(optionCard).join('')}</div>
    ${matrixHtml(s.options)}
    <details class="ask-again"><summary>Ask for different options</summary>
      <label for="feedback-text">What should change? For example, “no new software this year”.</label>
      <textarea id="feedback-text" rows="2" maxlength="1000"></textarea>
      <button type="button" id="ask-again-button">Ask again</button>
    </details>
    <p id="propose-error" class="error-text" role="alert"></p>
  </section>`;
}

function optionCard(option) {
  return `<article class="option-card${option.rank === 1 ? ' top' : ''}">
    <div class="option-head">
      <span class="rank" title="Rank ${option.rank}, option ${escapeText(option.id)}">#${option.rank}<small>${escapeText(option.id)}</small></span>
      <h4>${escapeText(option.title)}</h4>
      <span class="usefulness" title="Usefulness 0–100, calculated from the criteria scores">${option.usefulness}</span>
    </div>
    <div class="meter"><span style="width:${option.usefulness}%"></span></div>
    <p>${escapeText(option.summary)}</p>
    <p class="muted">${escapeText(option.how_it_helps)}</p>
    <div class="pros-cons">
      <div><h5>Pros</h5><ul class="pros">${option.pros.map(p => `<li>${escapeText(p)}</li>`).join('')}</ul></div>
      <div><h5>Cons</h5><ul class="cons">${option.cons.map(c => `<li>${escapeText(c)}</li>`).join('')}</ul></div>
    </div>
    <details><summary>Assumptions and open questions</summary>
      <h5>Must be true</h5>${list(option.assumptions)}<h5>Research must answer</h5>${list(option.open_questions)}
    </details>
    ${option.unverified_figures ? `<p class="warning">Contains figures the employee didn't give (${escapeText(option.unverified_figures.join(', '))}). Verify in research.</p>` : ''}
    <form class="select-form" data-option="${escapeText(option.id)}">
      <label for="reason-${option.id}" class="visually-hidden">Why this option?</label>
      <input id="reason-${option.id}" placeholder="Why this option? (required)" maxlength="1000" required>
      <button type="submit" class="${option.rank === 1 ? 'primary' : ''}">Select and start research</button>
    </form>
  </article>`;
}

function matrixHtml(options) {
  if (!researchCriteria.length) return '';
  const dots = value => `<span class="dots" aria-label="${value} out of 5">${'●'.repeat(value)}<span>${'●'.repeat(5 - value)}</span></span>`;
  return `<div class="matrix-wrap"><table class="matrix">
    <thead><tr><th>Criterion</th><th>Weight</th>${options.map(o => `<th>#${o.rank} ${escapeText(o.title)}</th>`).join('')}</tr></thead>
    <tbody>${researchCriteria.map(c => `<tr><td>${escapeText(c.name)}</td><td>${Math.round(c.weight * 100)}%</td>
      ${options.map(o => `<td title="${escapeText(o.scores[c.key].reason)}">${dots(o.scores[c.key].value)}</td>`).join('')}</tr>`).join('')}
      <tr class="total"><td>Usefulness</td><td></td>${options.map(o => `<td>${o.usefulness}</td>`).join('')}</tr>
    </tbody></table>
    <p class="muted">Hover a score for the reason. Usefulness = the weighted average of the scores, out of 100, calculated by the app.</p></div>`;
}

function researchHtml(record) {
  const r = record.research;
  const option = r.selected_option;
  const total = record.solutions?.options.length ?? '?';
  const plan = r.plan;
  return `<section class="solutions">
    <div class="research-started">
      <p class="eyebrow">RESEARCH STARTED</p>
      <h3>${escapeText(option.title)}</h3>
      <p>${escapeText(option.summary)}</p>
      <p class="muted">Ranked #${r.selected_rank} of ${total} (usefulness ${option.usefulness})${r.agreed_with_top_rank ? '' : ' · the team chose a different option from the top-ranked one'}.
        Selected by ${escapeText(r.selected_by)}: “${escapeText(r.reason)}”</p>
    </div>
    <h4>Research plan <span class="status">DRAFT</span></h4>
    <div class="plan-grid">
      <div><h5>Questions to answer</h5>${list(plan.research_questions)}</div>
      <div><h5>Evidence needed</h5>${list(plan.evidence_needed)}</div>
      <div><h5>Pilot success criteria</h5>${list(plan.pilot_success_criteria)}</div>
      <div><h5>Risks to check</h5>${list(plan.risks_to_check)}</div>
      <div><h5>Next steps</h5>${list(plan.next_steps)}</div>
    </div>
    <p class="muted">Drafted by ${escapeText(plan.generated_by)}. Nothing here is verified yet.</p>
    ${suppliersHtml(record)}
    ${evaluationHtml(record)}
    ${pilotHtml(record)}
  </section>`;
}

// Ask the Research AI for options (first time, or again with feedback). Takes 30–60 seconds with Claude.
async function proposeOptions(id, feedback) {
  const button = get('propose-button') || get('ask-again-button');
  if (button) { button.disabled = true; button.textContent = 'Comparing approaches… (up to a minute)'; }
  const ok = await sendReviewAction(`/api/submissions/${id}/solutions`, {feedback: feedback || null}, id, 'propose-error');
  if (!ok && button) { button.disabled = false; button.textContent = 'Try again'; }
}

function wireResearch(record) {
  wireSuppliers(record);
  wireEvaluation(record);
  wirePilot(record);
  if (get('propose-button')) get('propose-button').onclick = () => proposeOptions(record.id);
  if (get('ask-again-button')) get('ask-again-button').onclick = () => proposeOptions(record.id, get('feedback-text').value);
  for (const form of document.querySelectorAll('.select-form')) {
    form.onsubmit = async event => {
      event.preventDefault();
      const button = form.querySelector('button');
      button.disabled = true;
      button.textContent = 'Starting research…';
      const ok = await sendReviewAction(`/api/submissions/${record.id}/solutions/select`,
        {option_id: form.dataset.option, reason: form.querySelector('input').value}, record.id, 'propose-error');
      if (!ok) { button.disabled = false; button.textContent = 'Select and start research'; }
    };
  }
}

// ── Supplier research ────────────────────────────────────────────────────────
// Every run starts with setup questions (pre-filled with the last answers). The AI searches the
// web; the server keeps only findings with a retrieved source and calculates the ranking.

const IMPORTANCE_LABELS = {must: 'Must-have (pass/fail)', high: 'High', medium: 'Medium', low: 'Low'};
const EVIDENCE_LABELS = {'supplier-stated': 'Supplier says', independent: 'Independent source',
  'not found': 'Not found', 'not verified': 'Not verified'};
let supplierSetup = null;   // {library, geography, cost_policy, defaults} from the server
let setupFactors = [];      // the factor rows currently on screen

function suppliersHtml(record) {
  const result = record.research.suppliers;
  return `<div class="suppliers" id="suppliers">
    <div class="solutions-head">
      <div><p class="eyebrow">SUPPLIER RESEARCH</p><h3>Who could provide this?</h3></div>
      ${result ? `<p class="muted">Round ${result.round} · ${escapeText(result.generated_by)} · ${result.searches} web searches · ${result.sources_retrieved} sources · $${result.cost_usd}</p>` : ''}
    </div>
    <div id="supplier-setup"></div>
    ${result ? supplierResultsHtml(result) : `<div class="research-empty" id="supplier-start">
      <p class="muted">Answer a few questions first: which factors matter, how much, where to look and how to treat prices.
        The Research AI then searches the web, and every finding links to its source.</p>
      <button class="primary" id="find-suppliers">Find suppliers</button></div>`}
    <p id="supplier-error" class="error-text" role="alert"></p>
  </div>`;
}

function supplierResultsHtml(result) {
  const factors = result.setup.factors;
  const shortlisted = new Set(result.shortlist?.names ?? []);
  const eligibility = {eligible: ['rec-accept', 'Meets all must-haves'],
    must_have_unconfirmed: ['rec-ask', 'Must-have not confirmed'], fails_must_have: ['rec-decline', 'Fails a must-have']};
  const dots = value => value ? `<span class="dots">${'●'.repeat(value)}<span>${'●'.repeat(5 - value)}</span></span>` : '<span class="muted">unknown</span>';
  const cards = result.suppliers.map(s => {
    const [chip, label] = eligibility[s.eligibility];
    const cost = s.cost.price_is_published ? escapeText(s.cost.published_price)
      : s.cost.estimate ? `${escapeText(s.cost.estimate)} <span class="chip chip-rec-ask">AI estimate, not verified</span>`
      : s.cost.published_price ? escapeText(s.cost.published_price) : `Relative cost: ${escapeText(s.cost.relative)}`;
    return `<article class="option-card supplier-card${s.rank === 1 ? ' top' : ''}">
      <div class="option-head"><span class="rank">#${s.rank}</span><h4>${escapeText(s.name)}</h4>
        <span class="usefulness" title="Fit 0–100 from the factors you weighted">${s.fit_score ?? '–'}</span></div>
      <div class="meter"><span style="width:${s.fit_score ?? 0}%"></span></div>
      <div class="chips"><span class="chip chip-${chip}">${label}</span><span class="chip">${escapeText(s.confidence)} confidence</span></div>
      <p class="muted">${escapeText(s.headquarters)} · UAE: ${escapeText(s.uae_presence)}${s.website ? ` · <a href="${escapeText(s.website)}" target="_blank" rel="noopener noreferrer">website</a>` : ''}</p>
      <p>${escapeText(s.offering)}</p>
      <p><strong>Cost:</strong> ${cost}${s.cost.sources.map(url => ` <a href="${escapeText(url)}" target="_blank" rel="noopener noreferrer">source</a>`).join('')}</p>
      <details><summary>All ${factors.length} factors</summary><ul class="findings">${factors.map(f => {
        const item = s.findings[f.key];
        return `<li><strong>${escapeText(f.name)}</strong> ${dots(item.rating)} <span class="chip">${EVIDENCE_LABELS[item.evidence] ?? escapeText(item.evidence)}</span>
          <br>${escapeText(item.finding)} ${item.sources.map((url, i) => `<a href="${escapeText(url)}" target="_blank" rel="noopener noreferrer">[${i + 1}]</a>`).join(' ')}</li>`;
      }).join('')}</ul></details>
      ${s.questions_for_supplier.length ? `<details><summary>Questions to ask them</summary>${list(s.questions_for_supplier)}</details>` : ''}
      <label class="shortlist-pick"><input type="checkbox" value="${escapeText(s.name)}" ${shortlisted.has(s.name) ? 'checked' : ''}> Shortlist</label>
    </article>`;
  }).join('');
  const matrix = `<div class="matrix-wrap"><table class="matrix"><thead><tr><th>Factor</th><th>Importance</th>
      ${result.suppliers.map(s => `<th>#${s.rank} ${escapeText(s.name)}</th>`).join('')}</tr></thead><tbody>
      ${factors.map(f => `<tr><td>${escapeText(f.name)}</td><td>${IMPORTANCE_LABELS[f.importance]}</td>
        ${result.suppliers.map(s => { const item = s.findings[f.key];
          return `<td title="${escapeText(item.finding)}">${f.importance === 'must' ? escapeText(item.must_have_met) : dots(item.rating)}</td>`; }).join('')}</tr>`).join('')}
      <tr class="total"><td>Fit score</td><td></td>${result.suppliers.map(s => `<td>${s.fit_score ?? '–'}</td>`).join('')}</tr>
    </tbody></table><p class="muted">Unknown is left out of the fit score, not counted as zero; it lowers confidence instead.
      A supplier that fails a must-have is ranked last.</p></div>`;
  return `<p class="comparison-text">${escapeText(result.summary)}</p>
    ${result.gaps?.length ? `<details><summary>Gaps the research couldn't fill</summary>${list(result.gaps)}</details>` : ''}
    ${result.error ? `<p class="warning">Live research failed (${escapeText(result.error)}), so these are fictional examples.</p>` : ''}
    <div class="option-list">${cards}</div>${matrix}
    <div class="shortlist-bar">
      <input id="shortlist-note" placeholder="Note for the shortlist (optional)" maxlength="1000" value="${escapeText(result.shortlist?.note ?? '')}">
      <button type="button" id="shortlist-button" class="primary">Save shortlist</button>
      <button type="button" id="rerun-suppliers">Change the questions and search again</button>
    </div>
    ${result.shortlist ? `<p class="muted">Shortlisted by ${escapeText(result.shortlist.by)}: ${escapeText(result.shortlist.names.join(', '))}. Contacting suppliers needs a person to send it.</p>` : ''}`;
}

// The setup questions, shown before every search.
async function openSupplierSetup(record) {
  const box = get('supplier-setup');
  if (get('supplier-start')) get('supplier-start').hidden = true;
  box.innerHTML = '<p class="muted">Loading the questions…</p>';
  supplierSetup = await fetch('/api/research/supplier-setup').then(reply => reply.json());
  const previous = record.research.suppliers?.setup ?? supplierSetup.defaults;
  const chosen = new Map(previous.factors.map(f => [f.key, f]));
  // Library factors (on if they were used last time) plus any custom factors used last time.
  setupFactors = supplierSetup.library.map(f => ({...f, on: chosen.has(f.key), importance: chosen.get(f.key)?.importance ?? f.importance}))
    .concat(previous.factors.filter(f => !supplierSetup.library.some(l => l.key === f.key)).map(f => ({...f, on: true, custom: true})));
  box.innerHTML = `<form class="supplier-form" id="supplier-form">
    <h4>1. Which factors should suppliers be compared on, and how much does each matter?</h4>
    <div id="factor-rows"></div>
    <div class="suggest-row"><button type="button" id="suggest-factors">✨ Suggest factors for this option</button>
      <span class="muted" id="suggest-status"></span></div>
    <div class="add-factor">
      <input id="custom-name" placeholder="Add your own category, e.g. Arabic-language support" maxlength="80">
      <input id="custom-description" placeholder="What it means (optional)" maxlength="300">
      <select id="custom-importance">${Object.entries(IMPORTANCE_LABELS).map(([k, l]) => `<option value="${k}" ${k === 'medium' ? 'selected' : ''}>${l}</option>`).join('')}</select>
      <button type="button" id="add-factor">Add</button>
    </div>
    <h4>2. Where should we look?</h4>
    ${radios('geography', supplierSetup.geography, previous.geography)}
    <h4>3. How should prices be shown?</h4>
    ${radios('cost_policy', supplierSetup.cost_policy, previous.cost_policy)}
    <h4>4. How many suppliers?</h4>
    <select id="supplier-count">${[3, 4, 5, 6].map(n => `<option ${n === previous.supplier_count ? 'selected' : ''}>${n}</option>`).join('')}</select>
    <h4>5. Anything else the research should know? (optional)</h4>
    <textarea id="supplier-notes" rows="2" maxlength="1000" placeholder="For example: must work on-premises; budget approval is easier under a yearly subscription.">${escapeText(previous.notes ?? '')}</textarea>
    <button class="primary" type="submit" id="start-suppliers">Start supplier research</button>
    <p class="muted">Takes 2–4 minutes and searches the web. Your answers are remembered for next time.</p>
  </form>`;
  renderFactorRows();
  get('add-factor').onclick = () => {
    const name = get('custom-name').value.trim();
    if (!name) return;
    setupFactors.push({key: 'custom_' + name.toLowerCase().replace(/[^a-z0-9]+/g, '_').replace(/^_|_$/g, '').slice(0, 40),
      name, description: get('custom-description').value.trim(), importance: get('custom-importance').value, on: true, custom: true});
    get('custom-name').value = get('custom-description').value = '';
    renderFactorRows();
  };
  get('suggest-factors').onclick = async () => {
    get('suggest-factors').disabled = true;
    get('suggest-status').textContent = 'Thinking about what matters for this option…';
    const suggested = await fetch(`/api/submissions/${record.id}/suppliers/suggest-factors`, {method: 'POST'}).then(r => r.json()).catch(() => []);
    for (const f of suggested) {
      if (!setupFactors.some(existing => existing.key === f.key)) {
        setupFactors.push({key: f.key, name: f.name, description: f.description, why: f.why, importance: 'medium', on: true, custom: true, suggested: true});
      }
    }
    get('suggest-status').textContent = suggested.length ? `Added ${suggested.length} suggestions. Untick any you don't want.` : 'No suggestions.';
    renderFactorRows();
  };
  get('supplier-form').onsubmit = async event => {
    event.preventDefault();
    const body = {
      factors: setupFactors.filter(f => f.on).map(({key, name, description, importance}) => ({key, name, description: description ?? '', importance})),
      geography: document.querySelector('input[name=geography]:checked').value,
      cost_policy: document.querySelector('input[name=cost_policy]:checked').value,
      supplier_count: Number(get('supplier-count').value),
      notes: get('supplier-notes').value,
    };
    get('start-suppliers').disabled = true;
    get('start-suppliers').textContent = 'Searching the web and comparing suppliers… (2–4 minutes)';
    const ok = await sendReviewAction(`/api/submissions/${record.id}/suppliers`, body, record.id, 'supplier-error');
    if (!ok) { get('start-suppliers').disabled = false; get('start-suppliers').textContent = 'Start supplier research'; }
  };
  box.scrollIntoView({block: 'start', behavior: 'smooth'});
}

function radios(name, options, selected) {
  return `<div class="radio-cards">${Object.entries(options).map(([key, text]) => `<label class="radio-card">
    <input type="radio" name="${name}" value="${key}" ${key === selected ? 'checked' : ''}><span>${escapeText(text)}</span></label>`).join('')}</div>`;
}

function renderFactorRows() {
  get('factor-rows').innerHTML = setupFactors.map((f, i) => `<div class="factor-row${f.on ? '' : ' off'}">
    <label class="factor-name"><input type="checkbox" data-i="${i}" ${f.on ? 'checked' : ''}>
      <span><strong>${escapeText(f.name)}</strong>${f.suggested ? ' <span class="chip chip-requested">suggested</span>' : f.custom ? ' <span class="chip">your category</span>' : ''}
      <br><span class="muted">${escapeText(f.why ? `${f.description} Why: ${f.why}` : f.description ?? '')}</span></span></label>
    <select data-i="${i}" aria-label="Importance of ${escapeText(f.name)}">${Object.entries(IMPORTANCE_LABELS).map(([k, l]) =>
      `<option value="${k}" ${k === f.importance ? 'selected' : ''}>${l}</option>`).join('')}</select>
  </div>`).join('');
  for (const box of get('factor-rows').querySelectorAll('input[type=checkbox]')) {
    box.onchange = () => { setupFactors[box.dataset.i].on = box.checked; box.closest('.factor-row').classList.toggle('off', !box.checked); };
  }
  for (const select of get('factor-rows').querySelectorAll('select')) {
    select.onchange = () => { setupFactors[select.dataset.i].importance = select.value; };
  }
}

function wireSuppliers(record) {
  if (record.status !== 'Research') {   // after a pilot partner is chosen, the comparison is read-only
    for (const id of ['find-suppliers', 'rerun-suppliers', 'shortlist-button']) if (get(id)) get(id).hidden = true;
    return;
  }
  if (get('find-suppliers')) get('find-suppliers').onclick = () => openSupplierSetup(record);
  if (get('rerun-suppliers')) get('rerun-suppliers').onclick = () => openSupplierSetup(record);
  if (get('shortlist-button')) {
    get('shortlist-button').onclick = () => {
      const names = [...document.querySelectorAll('.shortlist-pick input:checked')].map(box => box.value);
      if (!names.length) { get('supplier-error').textContent = 'Tick at least one supplier to shortlist.'; return; }
      sendReviewAction(`/api/submissions/${record.id}/suppliers/shortlist`, {names, note: get('shortlist-note').value}, record.id, 'supplier-error');
    };
  }
}

// ── Supplier evaluation: from shortlist to pilot partner ─────────────────────
// Per shortlisted supplier: prepare (AI draft) → contact (a person) → meeting notes (AI extracts)
// → due diligence checklist. The server only lets a supplier become pilot partner once its
// required checks have passed.

const OUTREACH_LABELS = {not_contacted: 'Not contacted', contacted: 'Contacted', meeting_booked: 'Meeting booked',
  meeting_held: 'Meeting held', declined_by_supplier: 'Supplier declined'};
const CHECK_LABELS = {not_started: 'Not started', in_progress: 'In progress', passed: 'Passed', failed: 'Failed',
  not_applicable: 'Not applicable'};

function gateStatus(track) {
  const failed = track.checklist.filter(i => i.status === 'failed').map(i => i.name);
  const waiting = track.checklist.filter(i => i.required && !['passed', 'not_applicable'].includes(i.status)).map(i => i.name);
  return {ready: !failed.length && !waiting.length, failed, waiting};
}

function emptyTrack() {
  return {outreach: 'not_contacted', prep: null, meetings: [], checklist: []};
}

function evaluationHtml(record) {
  const shortlist = record.research.suppliers?.shortlist?.names;
  if (!shortlist?.length) return '';
  const editable = record.status === 'Research';
  return `<div class="evaluation" id="evaluation">
    <div class="solutions-head"><div><p class="eyebrow">SUPPLIER EVALUATION</p><h3>Meet, check, then choose a pilot partner</h3></div>
      <p class="muted">Drafts are never sent by the app. A person sends them and records what happened.</p></div>
    ${shortlist.map((name, index) => trackHtml(record, name, index, editable)).join('')}
    <p id="evaluation-error" class="error-text" role="alert"></p>
  </div>`;
}

function trackHtml(record, name, index, editable) {
  const track = record.research.evaluation?.[name] ?? emptyTrack();
  const checklist = track.checklist.length ? track.checklist : (window.checklistTemplate ?? []).map(item =>
    ({...item, status: 'not_started', owner: 'UNASSIGNED', note: ''}));
  const gate = gateStatus({...track, checklist});
  const steps = [['Prepared', !!track.prep], ['Contacted', track.outreach !== 'not_contacted'],
    ['Met', track.meetings.length > 0], ['Checks passed', gate.ready]];
  const prep = track.prep;
  return `<article class="track" data-supplier="${escapeText(name)}" data-index="${index}">
    <div class="track-head"><h4>${escapeText(name)}</h4>
      <ol class="stepper">${steps.map(([label, done]) => `<li class="${done ? 'done' : ''}">${label}</li>`).join('')}</ol></div>

    <details ${!prep && editable ? 'open' : ''}><summary>1. Prepare the meeting${prep ? ' ✓' : ''}</summary>
      ${prep ? `<p><strong>Goal:</strong> ${escapeText(prep.meeting_goal)}</p>
        <h5>Questions, in priority order</h5><ol class="questions">${prep.questions.map(q =>
          `<li><span class="chip ${q.priority === 'must' ? 'chip-rec-decline' : ''}">${q.priority}</span> ${escapeText(q.question)}<br><span class="muted">${escapeText(q.why)}</span></li>`).join('')}</ol>
        ${prep.demo_requests.length ? `<h5>Ask them to demo</h5>${list(prep.demo_requests)}` : ''}
        <h5>Outreach email <span class="status">DRAFT, not sent</span></h5>
        ${prep.flags.map(f => `<p class="warning">${escapeText(f)}</p>`).join('')}
        <input readonly value="${escapeText(prep.email_subject)}" aria-label="Email subject">
        <textarea readonly rows="7" aria-label="Email draft">${escapeText(prep.email_body)}</textarea>
        <button type="button" class="copy-email">Copy email</button>`
      : editable ? `<p class="muted">The AI drafts a meeting goal, prioritised questions (from research gaps and unconfirmed must-haves) and an outreach email for you to review and send.</p>
        <button type="button" class="primary prepare-button">Prepare meeting</button>` : '<p class="muted">Not prepared.</p>'}
    </details>

    <details><summary>2. Contact · ${OUTREACH_LABELS[track.outreach]}</summary>
      ${editable ? `<div class="inline-row"><select class="outreach-select" aria-label="Outreach status">${Object.entries(OUTREACH_LABELS).map(([k, l]) =>
        `<option value="${k}" ${k === track.outreach ? 'selected' : ''}>${l}</option>`).join('')}</select>
        <button type="button" class="outreach-button">Save</button></div>` : ''}
    </details>

    <details><summary>3. Meetings · ${track.meetings.length}</summary>
      ${track.meetings.map(m => meetingHtml(m)).join('')}
      ${editable ? `<form class="meeting-form">
        <label>Meeting date <input type="date" class="meeting-date" required value="${new Date().toISOString().slice(0, 10)}"></label>
        <label>Paste the meeting notes or transcript
          <textarea class="meeting-notes" rows="5" required minlength="20" placeholder="Who attended, what they said, what was agreed…"></textarea></label>
        <button type="submit" class="primary">Extract follow-up</button></form>` : ''}
    </details>

    <details ${track.meetings.length && editable ? 'open' : ''}><summary>4. Due diligence · ${gate.ready ? 'ready for a pilot' : `${gate.waiting.length} required open${gate.failed.length ? `, ${gate.failed.length} failed` : ''}`}</summary>
      <div class="checklist">${checklist.map(item => `<div class="check-row" data-item="${item.key}">
        <span class="check-name">${escapeText(item.name)}${item.required ? ' <span class="chip">required</span>' : ''}</span>
        <select ${editable ? '' : 'disabled'} aria-label="Status">${Object.entries(CHECK_LABELS).map(([k, l]) => `<option value="${k}" ${k === item.status ? 'selected' : ''}>${l}</option>`).join('')}</select>
        <input ${editable ? '' : 'disabled'} class="check-owner" value="${escapeText(item.owner)}" aria-label="Owner" placeholder="Owner">
        <input ${editable ? '' : 'disabled'} class="check-note" value="${escapeText(item.note)}" aria-label="Note" placeholder="Evidence or note">
        ${editable ? '<button type="button" class="check-save">Save</button>' : ''}</div>`).join('')}</div>
    </details>

    ${editable ? `<div class="gate ${gate.ready ? 'ready' : ''}">
      ${gate.ready ? '<p><strong>All required checks passed.</strong></p>'
        : `<p><strong>Not ready for a pilot.</strong> ${gate.failed.length ? `Failed: ${escapeText(gate.failed.join(', '))}. ` : ''}${gate.waiting.length ? `Still open: ${escapeText(gate.waiting.join(', '))}.` : ''}</p>`}
      <div class="inline-row"><input class="partner-reason" placeholder="Why this supplier for the pilot? (required)" maxlength="1000" ${gate.ready ? '' : 'disabled'}>
        <button type="button" class="primary partner-button" ${gate.ready ? '' : 'disabled'}>Choose as pilot partner</button></div>
    </div>` : ''}
  </article>`;
}

function meetingHtml(m) {
  const x = m.extracted;
  const answered = x.answers.filter(a => a.status === 'answered').length;
  return `<div class="meeting">
    <p><strong>${escapeText(m.date)}</strong> · ${escapeText(x.summary)}</p>
    ${x.answers.length ? `<p class="muted">${answered} of ${x.answers.length} prepared questions answered</p>
      <ul class="answers">${x.answers.filter(a => a.answer).map(a => `<li><span class="chip">${a.status}</span> ${escapeText(a.question)}<br>${escapeText(a.answer)}</li>`).join('')}</ul>` : ''}
    ${x.factor_updates.length ? `<h5>Comparison updated (verbal claims, still need written evidence)</h5>${list(x.factor_updates.map(u => u.finding))}` : ''}
    ${x.risks.length ? `<h5>Risks</h5>${list(x.risks)}` : ''}
    ${x.actions.length ? `<h5>Actions</h5><table class="scores"><tbody>${x.actions.map(a => `<tr><td>${escapeText(a.action)}</td>
      <td class="${a.owner === 'UNASSIGNED' ? 'flag' : ''}">${escapeText(a.owner)}</td><td class="${a.deadline === 'NO DATE AGREED' ? 'flag' : ''}">${escapeText(a.deadline)}</td></tr>`).join('')}</tbody></table>` : ''}
    <p class="muted">Extracted by ${escapeText(x.generated_by)}.</p>
  </div>`;
}

function pilotHtml(record) {
  const pilot = record.research.pilot;
  if (!pilot) return '';
  const p = pilot.plan;
  return `<div class="pilot">
    <div class="research-started"><p class="eyebrow">PILOT PLANNING</p><h3>Pilot with ${escapeText(pilot.partner)}</h3>
      <p>${escapeText(p.objective)}</p>
      <p class="muted">Chosen by ${escapeText(pilot.chosen_by)}: “${escapeText(pilot.reason)}”</p></div>
    <h4>Pilot plan <span class="status">DRAFT</span></h4>
    <div class="plan-grid">
      <div><h5>Scope</h5><p>${escapeText(p.scope)}</p><h5>Duration</h5><p>${escapeText(p.duration)}</p></div>
      <div><h5>Measure first (baseline)</h5>${list(p.baseline_metrics.map(m => `${m.metric}: ${m.how_measured}`))}</div>
      <div><h5>Success criteria</h5>${list(p.success_criteria.map(c => `${c.metric}: ${c.target}`))}</div>
      <div><h5>Stop early if</h5>${list(p.exit_criteria)}</div>
      <div><h5>Risks</h5>${list(p.risks)}</div>
      <div><h5>Costs to confirm</h5>${list(p.costs_to_confirm)}</div>
      <div><h5>Roles</h5>${list(p.roles.map(r => `${r.role}: ${r.responsibility}`))}</div>
    </div>
    <p class="muted">Drafted by ${escapeText(p.generated_by)}. Targets the facts didn't support are left "to be agreed".</p>
    ${pilotWorkHtml(record)}
  </div>`;
}

fetch('/api/evaluation/checklist').then(r => r.json()).then(data => { window.checklistTemplate = data.items; }).catch(() => {});

function wireEvaluation(record) {
  if (record.status !== 'Research') return;
  for (const track of document.querySelectorAll('.track')) {
    const supplier = track.dataset.supplier;
    const call = (path, body, button, busyText) => {
      if (button) { button.disabled = true; if (busyText) button.textContent = busyText; }
      return sendReviewAction(`/api/submissions/${record.id}/evaluation/${path}`, {supplier, ...body}, record.id, 'evaluation-error')
        .then(ok => { if (!ok && button) button.disabled = false; });
    };
    const prepare = track.querySelector('.prepare-button');
    if (prepare) prepare.onclick = () => call('prepare', {}, prepare, 'Preparing… (about 30 seconds)');
    const copy = track.querySelector('.copy-email');
    if (copy) copy.onclick = async () => {
      const [subject, body] = [track.querySelector('input[readonly]').value, track.querySelector('textarea[readonly]').value];
      await navigator.clipboard.writeText(`Subject: ${subject}\n\n${body}`).catch(() => {});
      copy.textContent = 'Copied. Review it, then send it yourself';
    };
    const outreach = track.querySelector('.outreach-button');
    if (outreach) outreach.onclick = () => call('outreach', {status: track.querySelector('.outreach-select').value}, outreach);
    const meeting = track.querySelector('.meeting-form');
    if (meeting) meeting.onsubmit = event => {
      event.preventDefault();
      call('meeting', {date: meeting.querySelector('.meeting-date').value, notes: meeting.querySelector('.meeting-notes').value},
        meeting.querySelector('button'), 'Extracting answers, risks and actions…');
    };
    for (const row of track.querySelectorAll('.check-row')) {
      row.querySelector('.check-save').onclick = () => call('checklist', {item: row.dataset.item, status: row.querySelector('select').value,
        owner: row.querySelector('.check-owner').value, note: row.querySelector('.check-note').value}, row.querySelector('.check-save'));
    }
    const partner = track.querySelector('.partner-button');
    if (partner) partner.onclick = () => call('pilot-partner', {reason: track.querySelector('.partner-reason').value}, partner,
      'Drafting the pilot plan…');
  }
}

// ── Pilot run and evaluation ─────────────────────────────────────────────────
// Agree the setup (numeric targets, named owner) → measure the baseline → start → log pilot data
// → evaluate (verdict calculated by the server) → the team decides scale / extend / revise / stop.

const DIRECTION_LABELS = {lower_better: 'Lower is better', higher_better: 'Higher is better'};
const VERDICT_STYLE = {success: 'rec-accept', partial: 'rec-ask', inconclusive: 'rec-triage', 'no improvement': 'rec-decline'};
const DECISION_TEXT = {scale: 'Scale it up', extend: 'Extend the pilot', revise: 'Revise and pilot again', stop: 'Stop'};
let editingSetup = false;

function pilotWorkHtml(record) {
  const pilot = record.research.pilot;
  const round = pilot.round ?? 1;
  const setup = pilot.setup;
  const planning = record.status === 'Pilot planning';
  const runningNow = record.status === 'Pilot running';
  const measurements = (pilot.measurements ?? []).filter(m => (m.round ?? 1) === round);
  const evaluation = (pilot.evaluations ?? []).filter(e => e.round === round).at(-1);
  let html = `<div class="pilot-work"><div class="solutions-head"><div><p class="eyebrow">PILOT${round > 1 ? ` · ROUND ${round}` : ''}</p>
    <h3>${{'Pilot planning': 'Agree, measure, then start', 'Pilot running': 'Running: measure, then evaluate',
      Scaling: 'Decided: scale it up', Stopped: 'Decided: stop'}[record.status]}</h3></div></div>`;

  // 1. Setup
  if (planning && (!setup || editingSetup)) html += setupFormHtml(pilot);
  else if (setup) {
    html += `<table class="scores"><thead><tr><th>Success criterion</th><th>Better when</th><th>Target</th><th>Min. data points</th></tr></thead><tbody>
      ${setup.criteria.map(c => `<tr><td>${escapeText(c.metric)}</td><td>${DIRECTION_LABELS[c.direction]}</td><td>${c.target} ${escapeText(c.unit)}</td><td>${c.min_points}</td></tr>`).join('')}
      </tbody></table><p class="muted">Owner ${escapeText(setup.owner)} · ${escapeText(setup.start_date)} to ${escapeText(setup.end_date)}
      ${planning ? ' · <button type="button" class="link" id="edit-setup">Change setup</button>' : ''}</p>`;
  }

  // 2. Measurements and observations
  if (setup) {
    html += `<h4>Measurements</h4><div class="measure-grid">${setup.criteria.map(c => {
      const values = phase => measurements.filter(m => m.metric === c.key && m.phase === phase).map(m => m.value);
      return `<div class="measure-card"><strong>${escapeText(c.metric)}</strong>
        <p class="muted">Baseline (${values('baseline').length}/${c.min_points}): ${values('baseline').join(', ') || '–'}</p>
        <p class="muted">Pilot (${values('pilot').length}/${c.min_points}): ${values('pilot').join(', ') || '–'}</p></div>`;
    }).join('')}</div>
    ${planning || runningNow ? `<form class="inline-row measure-form" id="measure-form">
      <select id="m-metric" aria-label="Metric">${setup.criteria.map(c => `<option value="${c.key}">${escapeText(c.metric)}</option>`).join('')}</select>
      <select id="m-phase" aria-label="Phase"><option value="baseline">Baseline</option>${runningNow ? '<option value="pilot" selected>Pilot</option>' : ''}</select>
      <input id="m-value" type="number" step="any" required placeholder="Value" aria-label="Value">
      <input id="m-date" type="date" required value="${new Date().toISOString().slice(0, 10)}" aria-label="Date">
      <button type="submit">Log</button></form>` : ''}
    <h4>Observations</h4>${list((pilot.observations ?? []).map(o => o.text))}
    ${planning || runningNow ? `<div class="inline-row"><input id="observation-text" placeholder="What happened? e.g. the export failed on Tuesday" maxlength="2000">
      <button type="button" id="add-observation">Add</button></div>` : ''}`;
  }

  // 3. Start, evaluate, decide
  if (planning && setup && !editingSetup) {
    const missing = setup.criteria.filter(c => !measurements.some(m => m.metric === c.key && m.phase === 'baseline')).map(c => c.metric);
    html += `<div class="gate ${missing.length ? '' : 'ready'}"><p>${missing.length ? `<strong>Measure the baseline first</strong> for: ${escapeText(missing.join(', '))}.`
      : '<strong>Ready to start.</strong> Baseline measured for every criterion.'}</p>
      <div class="inline-row"><button type="button" class="primary" id="start-pilot" ${missing.length ? 'disabled' : ''}>Start pilot</button></div></div>`;
  }
  if (runningNow) html += `<div class="inline-row"><button type="button" class="primary" id="evaluate-pilot">Evaluate the pilot</button>
    <span class="muted">The verdict is calculated from the measurements; too little data means "inconclusive".</span></div>`;
  if (evaluation) html += evaluationResultHtml(evaluation);
  if (runningNow && evaluation) html += decisionFormHtml(evaluation);
  for (const d of pilot.decisions ?? []) {
    html += `<p class="decided"><strong>Round ${d.round}: ${DECISION_TEXT[d.decision]}</strong> by ${escapeText(d.by)} · “${escapeText(d.reason)}”
      ${d.agreed_with_recommendation ? '· agreed with the recommendation' : `· recommendation was ${escapeText(d.recommended)}`}</p>`;
  }
  return html + '<p id="pilot-error" class="error-text" role="alert"></p></div>';
}

function setupFormHtml(pilot) {
  const fromPlan = pilot.setup?.criteria ?? (pilot.plan.success_criteria ?? []).map(c =>
    ({metric: c.metric, unit: '', direction: 'lower_better', target: '', min_points: 3}));
  const rows = (fromPlan.length ? fromPlan : [{metric: '', unit: '', direction: 'lower_better', target: '', min_points: 3}]);
  return `<form id="setup-form" class="supplier-form">
    <h4>Agree the success criteria: numbers, not hopes</h4>
    <div id="criteria-rows">${rows.map(criterionRowHtml).join('')}</div>
    <button type="button" id="add-criterion">Add a criterion</button>
    <div class="inline-row"><input id="pilot-owner" required placeholder="Pilot owner (a named person)" value="${escapeText(pilot.setup?.owner ?? '')}">
      <label>Start <input id="pilot-start" type="date" required value="${pilot.setup?.start_date ?? ''}"></label>
      <label>End <input id="pilot-end" type="date" required value="${pilot.setup?.end_date ?? ''}"></label></div>
    <button type="submit" class="primary">Agree setup</button></form>`;
}

function criterionRowHtml(c) {
  return `<div class="criterion-row">
    <input class="c-metric" required placeholder="Metric, e.g. Hours per week" value="${escapeText(c.metric ?? '')}">
    <input class="c-unit" required placeholder="Unit" value="${escapeText(c.unit ?? '')}">
    <select class="c-direction">${Object.entries(DIRECTION_LABELS).map(([k, l]) => `<option value="${k}" ${k === c.direction ? 'selected' : ''}>${l}</option>`).join('')}</select>
    <input class="c-target" type="number" step="any" required placeholder="Target" value="${c.target ?? ''}">
    <input class="c-min" type="number" min="2" max="20" required title="Minimum measurements per phase" value="${c.min_points ?? 3}"></div>`;
}

function evaluationResultHtml(e) {
  const fmt = v => v == null ? '–' : v;
  return `<div class="rec ${VERDICT_STYLE[e.verdict]}">
    <p><strong>Verdict: ${escapeText(e.verdict)}</strong> <span class="status">recommends ${escapeText(e.recommendation)} · ${escapeText(e.evidence_strength)} evidence</span></p>
    <p>${escapeText(e.reason)}</p></div>
    <div class="matrix-wrap"><table class="matrix"><thead><tr><th>Criterion</th><th>Baseline</th><th>Pilot</th><th>Change</th><th>Target</th><th>Result</th></tr></thead><tbody>
    ${e.metrics.map(m => `<tr title="${escapeText(m.explanation)}"><td>${escapeText(m.metric)}</td>
      <td>${fmt(m.baseline_mean)} <span class="muted">(n=${m.baseline_points})</span></td><td>${fmt(m.pilot_mean)} <span class="muted">(n=${m.pilot_points})</span></td>
      <td>${m.change == null ? '–' : `${m.change > 0 ? '+' : ''}${m.change}${m.change_percent == null ? '' : ` (${m.change_percent}%)`}`}</td>
      <td>${m.target} ${escapeText(m.unit)}</td><td>${escapeText(m.status)}</td></tr>`).join('')}</tbody></table>
    <p class="muted">Hover a row for the explanation. A change within the baseline's normal variation counts as "no clear change".</p></div>
    <div class="plan-grid"><div><h5>Summary</h5><p>${escapeText(e.narrative.summary)}</p></div>
      <div><h5>Lessons</h5>${list(e.narrative.lessons)}</div><div><h5>Risks if scaled</h5>${list(e.narrative.risks_if_scaled)}</div>
      <div><h5>Next steps</h5>${list(e.narrative.next_steps)}</div></div>
    <p class="muted">Narrative by ${escapeText(e.narrative.generated_by)}. It can't change the calculated verdict.</p>`;
}

function decisionFormHtml(e) {
  return `<form id="pilot-decision" class="supplier-form"><h4>Your decision</h4>
    <div class="radio-cards">${Object.entries(DECISION_TEXT).map(([k, l]) => `<label class="radio-card"><input type="radio" name="pilot-decision" value="${k}" ${k === e.recommendation ? 'checked' : ''}>
      <span><strong>${l}</strong>${k === e.recommendation ? ' <span class="chip chip-rec-accept">recommended</span>' : ''}</span></label>`).join('')}</div>
    <div class="inline-row"><label id="extend-row">New end date <input id="new-end" type="date"></label>
      <input id="decision-why" required placeholder="Why? (required)" maxlength="1000"></div>
    <button type="submit" class="primary">Confirm decision</button></form>`;
}

function wirePilot(record) {
  const id = record.id;
  const send = (path, body, button) => {
    if (button) button.disabled = true;
    return sendReviewAction(`/api/submissions/${id}/pilot/${path}`, body, id, 'pilot-error').then(ok => {
      if (!ok && button) button.disabled = false; return ok; });
  };
  if (get('edit-setup')) get('edit-setup').onclick = () => { editingSetup = true; renderDetail(record); };
  if (get('add-criterion')) get('add-criterion').onclick = () =>
    get('criteria-rows').insertAdjacentHTML('beforeend', criterionRowHtml({direction: 'lower_better', min_points: 3}));
  if (get('setup-form')) get('setup-form').onsubmit = async event => {
    event.preventDefault();
    const criteria = [...document.querySelectorAll('.criterion-row')].map(row => ({
      metric: row.querySelector('.c-metric').value, unit: row.querySelector('.c-unit').value,
      direction: row.querySelector('.c-direction').value, target: Number(row.querySelector('.c-target').value),
      min_points: Number(row.querySelector('.c-min').value)}));
    if (await send('setup', {criteria, owner: get('pilot-owner').value, start_date: get('pilot-start').value,
      end_date: get('pilot-end').value}, event.submitter)) editingSetup = false;
  };
  if (get('measure-form')) get('measure-form').onsubmit = event => {
    event.preventDefault();
    send('measurements', {metric: get('m-metric').value, phase: get('m-phase').value, value: Number(get('m-value').value),
      date: get('m-date').value}, event.submitter);
  };
  if (get('add-observation')) get('add-observation').onclick = () =>
    send('observations', {text: get('observation-text').value}, get('add-observation'));
  if (get('start-pilot')) get('start-pilot').onclick = () => send('start', {}, get('start-pilot'));
  if (get('evaluate-pilot')) get('evaluate-pilot').onclick = () => {
    get('evaluate-pilot').textContent = 'Evaluating…';
    send('evaluate', {}, get('evaluate-pilot'));
  };
  if (get('pilot-decision')) {
    const toggle = () => { get('extend-row').hidden = document.querySelector('input[name=pilot-decision]:checked')?.value !== 'extend'; };
    get('pilot-decision').onchange = toggle; toggle();
    get('pilot-decision').onsubmit = event => {
      event.preventDefault();
      const decision = document.querySelector('input[name=pilot-decision]:checked').value;
      send('decide', {decision, reason: get('decision-why').value,
        ...(decision === 'extend' ? {new_end_date: get('new-end').value || null} : {})}, event.submitter);
    };
  }
}
