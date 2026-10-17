// Request details. The reviewer sees the recommendation, a decision form, correction controls
// and the brief. The employee sees their summary and what they can do next.
// The server enforces every rule; this file only shows and sends.

let criteria = [];
fetch('/api/review/criteria').then(reply => reply.json()).then(list => { criteria = list; }).catch(() => {});
let openedAt = Date.now();  // for the "reviewer time per request" measure

const DECISION_LABEL = {accept: 'Accept for discovery', ask: 'Ask the employee', decline: 'Decline', link: 'Link to another request',
  route: 'Leave with the routed team', triage: 'Human triage', none: 'No action'};
const OUTCOME_LABEL = {agreed: 'Agreed with screening', overrode: 'Overrode screening', overturned_auto: 'Overturned an automatic decline'};
const SUMMARY_FIELDS = {current_process: 'Today, and what should happen instead', frequency: 'How often',
  people_affected: 'Who, or which locations', impact: 'Time, cost, delay or risk', tried_already: 'Already tried', department: 'Department'};

function renderDetail(record) {
  if (!get('detail-dialog').open) openedAt = Date.now();
  const reviewer = currentView === 'reviewer';
  get('detail-decision').innerHTML = reviewer ? reviewerDecision(record) : employeePanel(record);
  get('detail-body').innerHTML = reviewer
    ? corrections(record) + solutionsHtml(record) + briefHtml(record)   // solutionsHtml: js/research.js
    : employeeSummary(record);
  queueMicrotask(() => {
    if (reviewer) { wireReviewer(record); wireResearch(record); } else { wireEmployee(record); }
  });
}

const list = items => items?.length ? `<ul>${items.map(item => `<li>${escapeText(item)}</li>`).join('')}</ul>` : '<p class="muted">None</p>';

// ── Reviewer ─────────────────────────────────────────────────────────────────

function reviewerDecision(record) {
  const recommendation = record.recommendation;
  const isOpen = OPEN_STATUSES.includes(record.status);
  let html = '';
  if (recommendation) {
    html += `<div class="rec rec-${recommendation.decision}">
      <p><strong>Screening recommends: ${DECISION_LABEL[recommendation.decision] ?? recommendation.decision}</strong>
      <span class="status">PROPOSED · ${escapeText(recommendation.confidence)} confidence</span></p>
      <p>${escapeText(recommendation.reason)}</p>
      ${recommendation.criterion ? `<p class="muted">Criterion: ${escapeText(recommendation.criterion)}</p>` : ''}
      ${recommendation.auto_applied ? '<p><strong>Applied automatically by policy.</strong> The employee was told why and can ask for a human review.</p>' : ''}
    </div>`;
  }
  if (record.innovation_track === 'employee_requested' && isOpen) {
    html += '<p class="notice">The employee requested an innovation review. It needs a human decision, even if it\'s also routed elsewhere. That guarantees consideration, not funding.</p>';
  }
  if (record.appealed && isOpen) html += '<p class="notice">The employee asked for a human review of an earlier decline.</p>';
  if (!isOpen) {
    return html + `<p class="decided"><strong>${escapeText(record.status)}</strong>${record.decided_by ? ` by ${escapeText(record.decided_by)}` : ''}
      ${record.review_outcome ? ` · ${escapeText(OUTCOME_LABEL[record.review_outcome] ?? record.review_outcome)}` : ''}</p>
      ${record.decision_message ? `<p class="muted">Told the employee: "${escapeText(record.decision_message)}"</p>` : ''}`;
  }
  const suggested = ['accept', 'ask', 'decline', 'link'].includes(recommendation?.decision) ? recommendation.decision : 'ask';
  const targets = submissions.filter(item => item.id !== record.id && item.status !== 'Linked');
  return html + `<form id="decision-form">
    <fieldset class="decision-choice"><legend>Your decision</legend>
      ${['accept', 'ask', 'decline', 'link'].map(decision => `<label><input type="radio" name="decision" value="${decision}"
        ${decision === suggested ? 'checked' : ''}> ${DECISION_LABEL[decision]}</label>`).join('')}
    </fieldset>
    <div id="reason-row"><label for="decision-reason">Reason</label><select id="decision-reason">${
      criteria.map(item => `<option value="${escapeText(item.code)}" ${item.code === recommendation?.reason_code ? 'selected' : ''}>${escapeText(item.name)}</option>`).join('')}</select></div>
    <div id="link-row"><label for="decision-link">Link to</label><select id="decision-link">${
      targets.map(item => `<option value="${item.id}" ${item.id === recommendation?.link_to ? 'selected' : ''}>${item.id} · ${escapeText(item.title)}</option>`).join('')}</select></div>
    <label for="decision-message" id="decision-message-label"></label>
    <textarea id="decision-message" rows="3" maxlength="1000"></textarea>
    <button class="primary" type="submit">Confirm decision</button>
    <p id="decision-error" class="error-text" role="alert"></p>
  </form>`;
}

function corrections(record) {
  if (!OPEN_STATUSES.includes(record.status) || !record.brief?.priority) return '';
  const criteriaNames = record.brief.priority.criteria;
  return `<details class="corrections"><summary>Correct the screening</summary>
    <div class="fix-row"><label for="fix-route">Route</label>
      <select id="fix-route">${Object.entries(ROUTE_LABELS).filter(([key]) => key !== 'incident').map(([key, label]) =>
        `<option value="${key}" ${key === record.route ? 'selected' : ''}>${label}</option>`).join('')}</select>
      <input id="fix-route-reason" placeholder="Why? (required)" maxlength="500">
      <button type="button" id="fix-route-button">Re-route</button></div>
    <div class="fix-row"><label for="fix-criterion">Score</label>
      <select id="fix-criterion">${Object.entries(criteriaNames).map(([key, c]) => `<option value="${key}">${escapeText(c.name)}</option>`).join('')}</select>
      <select id="fix-value"><option value="">Unknown</option>${[0, 1, 2, 3, 4, 5].map(n => `<option>${n}</option>`).join('')}</select>
      <input id="fix-score-reason" placeholder="Why? (required)" maxlength="500">
      <button type="button" id="fix-score-button">Correct score</button></div>
    <div class="fix-row"><label for="fix-feasibility">Feasibility</label>
      <select id="fix-feasibility">${Object.entries(FEASIBILITY_LABELS).map(([key, label]) =>
        `<option value="${key}" ${key === record.feasibility ? 'selected' : ''}>${label}</option>`).join('')}</select></div>
    <p id="fix-error" class="error-text" role="alert"></p>
  </details>`;
}

function briefHtml(record) {
  const b = record.brief;
  if (!b) return '';
  const p = b.priority ?? {};
  const routing = b.routing ?? {};
  const rows = Object.values(p.criteria ?? {}).map(c => `<tr><th>${escapeText(c.name)}${c.corrected_by ? ' <span class="chip chip-requested">corrected</span>' : ''}</th>
    <td>${Math.round(c.weight * 100)}%</td><td>${c.value ?? '–'}</td><td>${escapeText(c.reason)}</td></tr>`).join('');
  const block = (title, body) => `<div class="brief-block"><h4>${title}</h4>${body}</div>`;
  return `<section class="brief">
    <h3>Brief <span class="status">PROPOSED</span></h3>
    <div class="brief-grid">
      ${block('Problem and desired outcome', `<p>${escapeText(b.problem)}</p>${b.today_and_desired ? `<p class="muted">Today, and instead: ${escapeText(b.today_and_desired)}</p>` : ''}`)}
      ${block('Affected users, process and locations', `<p>${escapeText(b.affected ?? 'Unknown')}</p>`)}
      ${block('Frequency and reported impact', `<p>How often: ${escapeText(b.frequency ?? 'unknown')}<br>Impact: ${escapeText(b.impact ?? 'unknown')}</p>`)}
      ${block('Existing solutions checked', list(b.existing_solutions_checked))}
      ${block('Previous attempts', list(b.previous_attempts))}
      ${block('Related submissions or projects', list([...(b.related ?? []), ...(record.supporters ? [`${record.supporters} linked request(s)`] : [])]))}
    </div>
    <div class="evidence">
      ${block('Facts', list(b.evidence?.facts))}${block('Estimates', list(b.evidence?.estimates))}${block('Missing evidence', list(b.evidence?.missing))}
    </div>
    <h4>Routing and priority rationale</h4>
    <p><strong>${escapeText(routing.label ?? '')}</strong>: ${escapeText(routing.reason ?? '')}${routing.signals?.length ? ` · Signals: ${escapeText(routing.signals.join(', '))}` : ''}</p>
    <p><strong>Priority ${p.score ?? '–'}/100</strong> · ${escapeText(p.confidence ?? '')} confidence (${Math.round((p.known_weight ?? 0) * 100)}% of the rubric known). Unknown criteria are left out, not scored as zero.</p>
    <table class="scores"><thead><tr><th>Criterion</th><th>Weight</th><th>Score</th><th>Why</th></tr></thead><tbody>${rows}</tbody></table>
    <div class="brief-grid">
      ${block('Feasibility', `<p>${escapeText(FEASIBILITY_LABELS[b.feasibility] ?? '–')}</p>`)}
      ${block('Proposed next step', `<p>${escapeText(b.next_step ?? '')}</p>`)}
      ${block('Suggested business owner', `<p>${escapeText(b.suggested_owner ?? '')}</p>`)}
    </div>
    ${b.notes?.length ? block('Notes', list(b.notes)) : ''}${b.flags?.length ? block('Flags', list(b.flags)) : ''}
    <p class="muted">Generated by ${escapeText(b.generated_by)}. Everything comes from what the employee said; nothing is verified yet.</p>
  </section>`;
}

function wireReviewer(record) {
  const form = get('decision-form');
  if (form) {
    const update = () => {
      const decision = form.querySelector('input[name=decision]:checked').value;
      const recommendation = record.recommendation ?? {};
      const code = get('decision-reason').value;
      get('reason-row').hidden = decision !== 'decline';
      get('link-row').hidden = decision !== 'link';
      get('decision-message-label').textContent = {accept: 'Note to the employee (optional)', ask: 'Question for the employee',
        decline: 'Why it was declined (sent to the employee)', link: 'Note (optional)'}[decision];
      get('decision-message').value = decision === 'ask'
        ? (recommendation.suggested_question ?? '')
        : decision === 'decline'
          ? (code === recommendation.reason_code ? recommendation.suggested_message
            : (criteria.find(item => item.code === code)?.message ?? '').replace('{ref}', '[request ID]').replace('{team}', '[team]'))
          : '';
    };
    form.addEventListener('change', event => { if (event.target.id !== 'decision-message') update(); });
    form.onsubmit = async event => {
      event.preventDefault();
      const decision = form.querySelector('input[name=decision]:checked').value;
      const body = {decision, message: get('decision-message').value, review_seconds: Math.round((Date.now() - openedAt) / 1000)};
      if (decision === 'decline') body.reason_code = get('decision-reason').value;
      if (decision === 'link') body.link_to = get('decision-link').value;
      const ok = await sendReviewAction(`/api/submissions/${record.id}/review`, body, record.id, 'decision-error');
      // Accepting hands over to the Research AI straight away.
      if (ok && decision === 'accept') proposeOptions(record.id);
    };
    update();
  }
  if (get('fix-route-button')) {
    get('fix-route-button').onclick = () => sendReviewAction(`/api/submissions/${record.id}/reroute`,
      {route: get('fix-route').value, reason: get('fix-route-reason').value}, record.id, 'fix-error');
    get('fix-score-button').onclick = () => sendReviewAction(`/api/submissions/${record.id}/scores`,
      {criterion: get('fix-criterion').value, value: get('fix-value').value === '' ? null : Number(get('fix-value').value),
       reason: get('fix-score-reason').value}, record.id, 'fix-error');
    get('fix-feasibility').onchange = () => sendReviewAction(`/api/submissions/${record.id}/feasibility`,
      {label: get('fix-feasibility').value}, record.id, 'fix-error');
  }
}

// ── Employee ─────────────────────────────────────────────────────────────────

function employeePanel(record) {
  const owner = ROUTE_LABELS[record.route] ?? 'the innovation team';
  const requested = record.innovation_track === 'employee_requested';
  const canRequest = OPEN_STATUSES.includes(record.status) && !requested;
  const requestForm = canRequest ? employeeForm('request-review', 'Is this part of a bigger, recurring problem? (optional)', 'Request innovation review', false) : '';
  const requestedNote = requested ? '<p class="muted">You requested an innovation review. The team will give you an answer. That guarantees consideration, not funding.</p>' : '';

  if (record.status === 'Routed') {
    return `<div class="rec rec-route"><p><strong>Sent to ${escapeText(owner)}.</strong> They handle requests like this today.</p>
      <button type="button" id="resolve-button" class="primary">It's resolved</button> <span id="resolve-error" class="error-text"></span>
      ${requestedNote}${requestForm}</div>`;
  }
  if (record.status === 'Linked') {
    return `<div class="rec rec-link"><p><strong>Linked to ${escapeText(record.linked_to)}.</strong> Your own details are kept, and the team sees that more people are affected.</p></div>`;
  }
  if (record.status === 'Needs clarification') {
    return `<div class="rec rec-ask"><p><strong>The innovation team asked:</strong> ${escapeText(record.review_question)}</p>
      ${employeeForm('reply', 'Your answer', 'Send answer', true)}</div>`;
  }
  if (record.status === 'Declined') {
    return `<div class="rec rec-decline"><p><strong>Declined.</strong> ${escapeText(record.decision_message)}</p>
      ${record.appealed ? '<p class="muted">You already asked for a human review. This is the final decision.</p>'
        : employeeForm('appeal', 'Why should a person look at this again?', 'Ask for a human review', true)}</div>`;
  }
  if (record.status === 'Accepted') {
    return `<div class="rec rec-accept"><p><strong>Accepted for discovery.</strong> The innovation team is comparing possible solutions. ${escapeText(record.decision_message ?? '')}</p></div>`;
  }
  if (record.status === 'Pilot running') {
    return `<div class="rec rec-accept"><p><strong>A pilot is running</strong> with ${escapeText(record.research.pilot.partner)}. Thank you for raising this.</p></div>`;
  }
  if (record.status === 'Scaling') {
    return `<div class="rec rec-accept"><p><strong>The pilot worked and is being scaled up.</strong> Your request led to a real improvement. Thank you.</p></div>`;
  }
  if (record.status === 'Stopped') {
    return `<div class="rec rec-decline"><p><strong>The pilot was stopped.</strong> ${escapeText(record.research.pilot.decisions?.at(-1)?.reason ?? '')} The lessons are recorded for future ideas.</p></div>`;
  }
  if (record.status === 'Pilot planning') {
    return `<div class="rec rec-accept"><p><strong>A pilot is being planned</strong> with ${escapeText(record.research.pilot.partner)}. The innovation team will keep you updated.</p></div>`;
  }
  if (record.status === 'Research') {
    return `<div class="rec rec-accept"><p><strong>Research has started</strong> on “${escapeText(record.research.selected_option.title)}”. The innovation team will keep you updated.</p></div>`;
  }
  if (record.status === 'Resolved') return '<div class="rec rec-accept"><p><strong>Resolved.</strong> You confirmed this was fixed.</p></div>';
  return `<div class="rec"><p>With ${escapeText(owner)}${record.appealed ? ' for a human review' : ''}.</p>${requestedNote}${requestForm}</div>`;
}

function employeeForm(kind, label, buttonText, required) {
  return `<form id="${kind}-form" class="employee-form"><label for="${kind}-text">${label}</label>
    <textarea id="${kind}-text" rows="2" ${required ? 'required' : ''} maxlength="2000"></textarea>
    <button class="primary" type="submit">${buttonText}</button>
    <p id="${kind}-error" class="error-text" role="alert"></p></form>`;
}

function employeeSummary(record) {
  return `<p>${escapeText(record.description)}</p><dl class="summary-list">${Object.entries(SUMMARY_FIELDS).map(([key, label]) =>
    `<dt>${label}</dt><dd>${escapeText(record[key] ?? 'Unknown')}</dd>`).join('')}</dl>`;
}

function wireEmployee(record) {
  for (const kind of ['reply', 'appeal', 'request-review']) {
    const form = get(`${kind}-form`);
    if (form) form.onsubmit = async event => {
      event.preventDefault();
      await sendReviewAction(`/api/submissions/${record.id}/${kind}`, {text: get(`${kind}-text`).value || null}, record.id, `${kind}-error`);
    };
  }
  if (get('resolve-button')) {
    get('resolve-button').onclick = () => sendReviewAction(`/api/submissions/${record.id}/resolve`, undefined, record.id, 'resolve-error');
  }
}

// ── Shared ───────────────────────────────────────────────────────────────────

// Send an action, then refresh the lists and re-open the same request.
async function sendReviewAction(url, body, id, errorId) {
  try {
    const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'},
      body: body === undefined ? undefined : JSON.stringify(body)});
    const reply = await response.json();
    if (!response.ok) {
      const detail = Array.isArray(reply.detail)
        ? reply.detail.map(problem => `${problem.loc.at(-1)}: ${problem.msg.replace('Value error, ', '')}`).join('; ')
        : reply.detail;
      get(errorId).textContent = detail;
      return false;
    }
    await loadSubmissions();
    openDetail(id);
    return true;
  } catch (error) {
    get(errorId).textContent = `Could not reach the server. ${error.message}`;
    return false;
  }
}

// History: every change, who made it and when.
async function renderHistory(id) {
  const section = get('detail-history');
  section.innerHTML = '';
  try {
    const events = await fetch(`/api/submissions/${id}/history`).then(reply => reply.json());
    if (!events.length) return;
    section.innerHTML = `<h3>History</h3><ol class="history">${events.map(event => `
      <li><span class="muted">${new Date(event.created_at).toLocaleString()} · ${escapeText(event.actor)}</span>
      <strong>${escapeText(event.event.replaceAll('_', ' '))}</strong>${event.to_status && event.to_status !== event.from_status ? ` → ${escapeText(event.to_status)}` : ''}
      ${event.details ? `<br><span>${escapeText(event.details)}</span>` : ''}</li>`).join('')}</ol>`;
  } catch {
    section.innerHTML = '';
  }
}
