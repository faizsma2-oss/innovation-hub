// Scale → roll out → hand over → track benefits → lessons learned.
// The money is calculated by the server from the pilot's measurements; the AI only writes the words around it.

const CASE_STYLE = {'AWAITING DECISION': 'rec-ask', APPROVED: 'rec-accept', REJECTED: 'rec-decline'};
const BENEFIT_STYLE = {held: 'rec-accept', 'partly held': 'rec-ask', eroded: 'rec-decline'};
const money = (value, currency) => value == null ? '–' : `${Math.round(value).toLocaleString()} ${currency}`;
let scaleImprovements = {};   // submission id → measured improvements, for the business case form

function scaleHtml(record) {
  if (!['Scaling', 'Rolling out', 'In operation', 'Stopped'].includes(record.status)) return '';
  const scale = record.research?.scale ?? {};
  let html = '<div class="scale-work">';
  if (record.status === 'Scaling' && scale.business_case?.status !== 'AWAITING DECISION') html += caseFormHtml(record);
  if (scale.business_case) html += caseHtml(record, scale.business_case);
  if (scale.rollout) html += rolloutHtml(record, scale.rollout);
  if (scale.checkins) html += checkinsHtml(record, scale);
  if (['In operation', 'Stopped'].includes(record.status)) html += lessonHtml(record);
  return html + '<p id="scale-error" class="error-text" role="alert"></p></div>';
}

// 1. Business case: costs typed by people, benefit from the pilot's measured improvement.
function caseFormHtml(record) {
  const lines = scaleImprovements[record.id];
  if (!lines) return '<div class="solutions-head"><div><p class="eyebrow">SCALE UP</p><h3>Business case</h3></div></div><p class="muted">Loading the pilot\'s measured improvements…</p>';
  const old = record.research.scale?.business_case?.inputs;
  const cost = (kind, rows) => (rows?.length ? rows : [{item: '', amount: ''}]).map(row => `<div class="inline-row cost-row" data-kind="${kind}">
    <input class="cost-item" placeholder="${kind === 'one_off' ? 'e.g. Setup and integration' : 'e.g. Licences'}" value="${escapeText(row.item)}">
    <input class="cost-amount" type="number" min="0" step="any" placeholder="Amount" value="${row.amount}"></div>`).join('');
  return `<div class="solutions-head"><div><p class="eyebrow">SCALE UP</p><h3>Business case for management</h3></div></div>
    <p class="muted">The benefit is the pilot's measured improvement × how often × how many sites or teams × what one unit is worth.
      Only metrics that actually improved can carry a benefit. The server does the maths.</p>
    <form id="case-form" class="supplier-form">
      <label>Currency <select id="case-currency">${['AED', 'USD', 'EUR', 'SAR'].map(c => `<option ${c === (old?.currency ?? 'AED') ? 'selected' : ''}>${c}</option>`).join('')}</select></label>
      <h4>Benefit from the pilot</h4>
      ${lines.length ? `<table class="scores"><thead><tr><th>Metric</th><th>Measured gain</th><th>Value of one unit</th><th>Periods / year</th><th>Sites or teams</th></tr></thead><tbody>
        ${lines.map(l => { const was = old?.benefits.find(b => b.metric_key === l.metric_key); return `<tr class="benefit-row" data-key="${l.metric_key}">
          <td>${escapeText(l.metric)}</td><td>${l.gain_per_period} ${escapeText(l.unit)} <span class="muted">(${l.baseline} → ${l.pilot})</span></td>
          <td><input class="b-value" type="number" min="0" step="any" placeholder="e.g. 150" value="${was?.value_per_unit ?? ''}"></td>
          <td><input class="b-periods" type="number" min="1" max="366" value="${was?.periods_per_year ?? 52}"></td>
          <td><input class="b-mult" type="number" min="1" max="1000" value="${was?.multiplier ?? 1}"></td></tr>`; }).join('')}</tbody></table>`
        : '<p class="notice">The pilot evaluation shows no metric that improved, so there is no measured benefit to put a value on.</p>'}
      <h4>One-off costs</h4><div id="one-off-rows">${cost('one_off', old?.one_off)}</div>
      <button type="button" class="link" data-add-cost="one_off">+ Add a one-off cost</button>
      <h4>Yearly costs</h4><div id="yearly-rows">${cost('yearly', old?.yearly)}</div>
      <button type="button" class="link" data-add-cost="yearly">+ Add a yearly cost</button>
      <div class="inline-row"><button type="submit" class="primary" ${lines.length ? '' : 'disabled'}>Calculate business case</button></div>
    </form>`;
}

function caseHtml(record, c) {
  const calc = c.calc, cur = calc.currency;
  return `<div class="solutions-head"><div><p class="eyebrow">BUSINESS CASE</p><h3>${escapeText(calc.verdict)}</h3></div>
      <span class="status">${escapeText(c.status)}</span></div>
    <div class="case-figures">
      <div><strong>${money(calc.annual_benefit, cur)}</strong><span>Benefit per year</span></div>
      <div><strong>${money(calc.one_off_total, cur)}</strong><span>One-off cost</span></div>
      <div><strong>${money(calc.yearly_cost_total, cur)}</strong><span>Yearly cost</span></div>
      <div><strong>${calc.payback_months == null ? 'Never' : `${calc.payback_months} months`}</strong><span>Payback</span></div>
      <div><strong>${money(calc.three_year_net, cur)}</strong><span>Net over 3 years</span></div>
    </div>
    <table class="scores"><thead><tr><th>Benefit line</th><th>Calculation</th><th>Per year</th></tr></thead><tbody>
      ${calc.benefit_lines.map(l => `<tr><td>${escapeText(l.metric)}</td>
        <td class="muted">${l.gain_per_period} ${escapeText(l.unit)} × ${l.periods_per_year} × ${l.multiplier} × ${l.value_per_unit} ${cur}</td>
        <td>${money(l.annual_value, cur)}</td></tr>`).join('')}</tbody></table>
    <div class="plan-grid"><div><h5>Summary</h5><p>${escapeText(c.narrative.summary)}</p></div>
      <div><h5>Assumptions</h5>${list(c.narrative.assumptions)}</div><div><h5>Risks</h5>${list(c.narrative.risks)}</div></div>
    <p class="muted">Narrative by ${escapeText(c.narrative.generated_by)}. It can't add or change figures.</p>
    ${c.status === 'AWAITING DECISION' ? `<form id="case-decision" class="supplier-form"><h4>Management decision</h4>
        <div class="inline-row"><label><input type="radio" name="case-decision" value="approve" checked> Approve and roll out</label>
          <label><input type="radio" name="case-decision" value="reject"> Reject and stop</label></div>
        <input id="case-why" required maxlength="1000" placeholder="Why? (required, e.g. the budget line it comes from)">
        <div class="inline-row"><button type="submit" class="primary">Record decision</button>
          <button type="button" id="redo-case">Change the figures</button></div></form>`
      : c.decision ? `<p class="decided"><strong>${c.status === 'APPROVED' ? 'Approved' : 'Rejected'}</strong> by ${escapeText(c.decision.by)} · “${escapeText(c.decision.reason)}”</p>` : ''}`;
}

// 2. Rollout plan and the handover gate: a named business owner and a finished checklist.
function rolloutHtml(record, r) {
  const rolling = record.status === 'Rolling out';
  const done = r.handover.filter(i => i.done).length;
  return `<div class="solutions-head"><div><p class="eyebrow">ROLL OUT AND HAND OVER</p>
      <h3>${rolling ? 'Rolling out' : `Handed over to ${escapeText(r.business_owner)}`}</h3></div><span class="status">${escapeText(r.status)}</span></div>
    <div class="plan-grid">
      <div><h5>Phases</h5>${list(r.plan.phases.map(p => `${p.name}: ${p.detail}`))}</div>
      <div><h5>Training</h5>${list(r.plan.training)}</div><div><h5>Procurement</h5>${list(r.plan.procurement)}</div>
    </div>
    <p class="muted">Drafted by ${escapeText(r.plan.generated_by)}.</p>
    <h4>Handover checklist (${done}/${r.handover.length})</h4>
    <ul class="checklist">${r.handover.map((item, index) => `<li><label><input type="checkbox" data-handover="${index}" ${item.done ? 'checked' : ''}
      ${rolling ? '' : 'disabled'}> ${escapeText(item.item)}</label></li>`).join('')}</ul>
    ${rolling ? `<div class="gate ${done === r.handover.length ? 'ready' : ''}">
      <p>${done === r.handover.length ? '<strong>Ready to hand over.</strong> Name who owns it in operations.'
        : '<strong>Finish the checklist first.</strong> Operations only takes over a finished rollout.'}</p>
      <form id="handover-form" class="inline-row"><input id="business-owner" required placeholder="Business owner (a named person)" maxlength="80">
        <label>From <input id="handover-date" type="date" required value="${new Date().toISOString().slice(0, 10)}"></label>
        <button type="submit" class="primary" ${done === r.handover.length ? '' : 'disabled'}>Hand over</button></form></div>`
      : `<p class="muted">In operation since ${escapeText(r.handover_date)}.</p>`}`;
}

// 3. Benefits check-ins: did the pilot's improvement hold once it was everyone's normal way of working?
function checkinsHtml(record, scale) {
  const lines = scale.business_case.calc.benefit_lines;
  const next = scale.checkins.findIndex(c => !c.result);
  return `<h4>Benefits check-ins</h4>
    <p class="muted">Held = at least 80% of the pilot's improvement is still there · partly held = 30–80% · eroded = less.</p>
    <div class="measure-grid">${scale.checkins.map((c, index) => `<div class="measure-card">
      <strong>${escapeText(c.label)}</strong> <span class="muted">due ${escapeText(c.due)}</span>
      ${c.result ? `<p><span class="chip chip-${BENEFIT_STYLE[c.result.verdict]}">${escapeText(c.result.verdict)}</span>
          ${Math.round(c.result.overall_fraction * 100)}% of the improvement · about ${money(c.result.realised_annual_value, c.result.currency)}/year</p>
        ${c.result.metrics.map(m => `<p class="muted">${escapeText(m.metric)}: ${m.baseline} → pilot ${m.pilot} → now ${m.now}</p>`).join('')}
        ${c.note ? `<p class="muted">“${escapeText(c.note)}”</p>` : ''}`
      : index === next && record.status === 'In operation' ? `<form class="checkin-form" data-checkin="${index}">
          ${lines.map(l => `<label>${escapeText(l.metric)} now (${escapeText(l.unit)})
            <input type="number" step="any" data-metric="${l.metric_key}" placeholder="pilot was ${l.pilot}"></label>`).join('')}
          <input class="checkin-note" maxlength="1000" placeholder="Note (optional)">
          <button type="submit">Log check-in</button></form>` : '<p class="muted">Not yet</p>'}</div>`).join('')}</div>`;
}

// 4. Lessons learned, published to the catalog the intake assistant checks for every new request.
function lessonHtml(record) {
  const r = record.research, draft = r.lesson_draft, published = r.lesson;
  const kindText = record.status === 'In operation'
    ? 'an existing tool: future employees with a similar problem are pointed to it'
    : 'a previous pilot: future briefs on similar problems include what was learned';
  let html = `<div class="solutions-head"><div><p class="eyebrow">CLOSE THE LOOP</p><h3>Lessons learned</h3></div>
    ${published ? `<span class="status">PUBLISHED · ${escapeText(published.id)}</span>` : ''}</div>
    <p class="muted">Publishing adds this to the intake catalog as ${kindText}.</p>`;
  if (published) html += `<p class="decided"><strong>${escapeText(published.title)}</strong> · keywords: ${escapeText(published.keywords.join(', '))}
    · published by ${escapeText(published.published_by)}</p>`;
  if (!draft) return html + `<button type="button" id="draft-lesson">${published ? 'Draft again' : 'Draft the lesson'}</button>`;
  const summary = [draft.what_we_tried && `We tried: ${draft.what_we_tried}.`, draft.result].filter(Boolean).join(' ');
  return html + `<form id="lesson-form" class="supplier-form">
    <label>Title <input id="lesson-title" required maxlength="120" value="${escapeText(published?.title ?? draft.title)}"></label>
    <label>Summary employees will see <textarea id="lesson-summary" rows="3" maxlength="600" required>${escapeText(summary)}</textarea></label>
    <label>How to use it or learn more <input id="lesson-how" maxlength="400" value="${escapeText(draft.how_to)}"></label>
    <label>Keyword phrases that should find it (comma-separated, 2–3 words each)
      <input id="lesson-keywords" required value="${escapeText((published?.keywords ?? draft.keywords).join(', '))}"></label>
    ${draft.advice?.length ? `<h5>Advice for next time</h5>${list(draft.advice)}` : ''}
    <p class="muted">Drafted by ${escapeText(draft.generated_by)}. Edit before publishing.</p>
    <button type="submit" class="primary">${published ? 'Publish changes' : 'Publish to the intake catalog'}</button></form>`;
}

function wireScale(record) {
  if (!['Scaling', 'Rolling out', 'In operation', 'Stopped'].includes(record.status)) return;
  const id = record.id;
  const send = (path, body, button) => {
    if (button) button.disabled = true;
    return sendReviewAction(`/api/submissions/${id}/${path}`, body, id, 'scale-error').then(ok => {
      if (!ok && button) button.disabled = false; return ok; });
  };
  const scale = record.research.scale ?? {};

  if (record.status === 'Scaling' && !scaleImprovements[id]) {
    fetch(`/api/submissions/${id}/scale/improvements`).then(reply => reply.json()).then(lines => {
      scaleImprovements[id] = Array.isArray(lines) ? lines : [];
      if (get('detail-dialog').open) renderDetail(record);
    });
  }
  for (const button of document.querySelectorAll('[data-add-cost]')) {
    button.onclick = () => {
      const kind = button.dataset.addCost;
      get(kind === 'one_off' ? 'one-off-rows' : 'yearly-rows').insertAdjacentHTML('beforeend', `<div class="inline-row cost-row" data-kind="${kind}">
        <input class="cost-item" placeholder="Item"><input class="cost-amount" type="number" min="0" step="any" placeholder="Amount"></div>`);
    };
  }
  if (get('case-form')) get('case-form').onsubmit = event => {
    event.preventDefault();
    const costs = kind => [...document.querySelectorAll(`.cost-row[data-kind=${kind}]`)]
      .map(row => ({item: row.querySelector('.cost-item').value.trim(), amount: Number(row.querySelector('.cost-amount').value)}))
      .filter(row => row.item && row.amount >= 0);
    const benefits = [...document.querySelectorAll('.benefit-row')].filter(row => row.querySelector('.b-value').value !== '')
      .map(row => ({metric_key: row.dataset.key, value_per_unit: Number(row.querySelector('.b-value').value),
        periods_per_year: Number(row.querySelector('.b-periods').value), multiplier: Number(row.querySelector('.b-mult').value)}));
    if (!benefits.length) { get('scale-error').textContent = 'Put a value on at least one improved metric.'; return; }
    send('scale/business-case', {currency: get('case-currency').value, one_off: costs('one_off'), yearly: costs('yearly'), benefits},
      submitButton(event));   // submitButton: js/meetings.js
  };
  if (get('redo-case')) get('redo-case').onclick = () => {
    scale.business_case.status = 'EDITING';   // local only: shows the form again, prefilled
    renderDetail(record);
  };
  if (get('case-decision')) get('case-decision').onsubmit = event => {
    event.preventDefault();
    send('scale/decision', {decision: document.querySelector('input[name=case-decision]:checked').value,
      reason: get('case-why').value}, submitButton(event));
  };
  for (const box of document.querySelectorAll('[data-handover]')) {
    box.onchange = () => send('scale/handover-item', {index: Number(box.dataset.handover), done: box.checked}, box);
  }
  if (get('handover-form')) get('handover-form').onsubmit = event => {
    event.preventDefault();
    send('scale/handover', {business_owner: get('business-owner').value, handover_date: get('handover-date').value}, submitButton(event));
  };
  for (const form of document.querySelectorAll('.checkin-form')) {
    form.onsubmit = event => {
      event.preventDefault();
      const values = Object.fromEntries([...form.querySelectorAll('[data-metric]')].filter(i => i.value !== '')
        .map(i => [i.dataset.metric, Number(i.value)]));
      send('scale/checkin', {index: Number(form.dataset.checkin), values, note: form.querySelector('.checkin-note').value},
        submitButton(event));
    };
  }
  if (get('draft-lesson')) get('draft-lesson').onclick = () => {
    get('draft-lesson').textContent = 'Drafting…';
    send('lessons/draft', undefined, get('draft-lesson'));
  };
  if (get('lesson-form')) get('lesson-form').onsubmit = event => {
    event.preventDefault();
    send('lessons/publish', {title: get('lesson-title').value, summary: get('lesson-summary').value, how_to: get('lesson-how').value,
      keywords: get('lesson-keywords').value.split(',').map(k => k.trim()).filter(Boolean)}, submitButton(event));
  };
}
