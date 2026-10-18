// Earned autonomy: how often people agree with the AI's recommendations, per decision area.
// A fixed rule shows whether there's evidence to propose more autonomy. Nothing here switches anything on.

const AUTONOMY_STATUS = {
  ready: ['rec-accept', 'Ready to propose more autonomy'], keep: ['rec-decline', 'Keep human review'],
  too_few: ['rec-ask', 'Not enough decisions yet'], always_human: ['innovation', 'Always a person'],
  automated: ['feasibility', 'Automatic, monitored'],
};

async function loadAutonomy() {
  try {
    const data = await fetch('/api/autonomy').then(r => r.json());
    const t = data.thresholds;
    const pct = v => v == null ? '–' : `${Math.round(v * 100)}%`;
    get('autonomy-note').textContent = `Ready means ${t.min_decisions}+ decisions, ${pct(t.agreement)}+ agreement and no override in the last ${t.recent}. `
      + 'It is evidence for management; nothing changes automatically.';
    get('autonomy').innerHTML = data.areas.map(a => {
      const [chip, label] = AUTONOMY_STATUS[a.status];
      return `<article class="autonomy-card ${a.status}">
        <div class="card-top"><span>${escapeText(a.name)}</span><span class="chip chip-${chip}">${label}</span></div>
        <div class="autonomy-figure"><strong>${pct(a.agreement)}</strong><span>agreed with the AI · ${a.decisions} ${a.decisions === 1 ? 'decision' : 'decisions'}
          ${a.recent_agreement != null && a.decisions > t.recent ? ` · last ${t.recent}: ${pct(a.recent_agreement)}` : ''}</span></div>
        <div class="meter"><span style="width:${Math.round((a.agreement ?? 0) * 100)}%"></span></div>
        <p class="muted">${escapeText(a.what)}</p>
        <p>${escapeText(a.why)}</p>
        ${['always_human', 'automated'].includes(a.status) ? '' : `<p class="muted"><strong>More autonomy would mean:</strong> ${escapeText(a.more_autonomy)}</p>`}
        ${a.overrides.length ? `<details><summary>Recent overrides (${a.decisions - a.agreed})</summary><ul>${a.overrides.map(o => `<li>${escapeText(o)}</li>`).join('')}</ul></details>` : ''}
      </article>`;
    }).join('');
  } catch { /* the section simply stays empty */ }
}

// Routing rules learned from corrections: suggested with evidence, approved by a person, removable.
const ROUTE_NAMES = {incident: 'Incident channel', it_support: 'IT support', hr: 'HR',
  facilities_procurement: 'Facilities, maintenance or procurement', process_owner_innovation: 'Process owner + innovation',
  innovation_screening: 'Innovation screening', human_triage: 'Human triage'};

async function loadRoutingRules(data) {
  data = data ?? await fetch('/api/routing/suggestions').then(r => r.json()).catch(() => null);
  if (!data) return;
  const box = get('routing-rules');
  if (!data.suggestions.length && !data.rules.length) { box.innerHTML = ''; return; }
  box.innerHTML = `<div class="section-title small"><h3>Routing rules learned from corrections</h3>
      <span>Suggested only after ${data.min_support}+ matching corrections and a replay that misroutes nothing.</span></div>
    ${data.suggestions.map(s => `<article class="rule-card">
      <p><strong>Requests mentioning “${escapeText(s.word)}” → ${escapeText(ROUTE_NAMES[s.route] ?? s.route)}</strong>
        <span class="muted"> (they were going to ${escapeText(ROUTE_NAMES[s.from] ?? s.from)})</span></p>
      <p class="muted">Replay on ${s.replayed_on} past requests: would fix ${s.fixes}, would misroute ${s.breaks}.</p>
      <details><summary>The ${s.requests.length} corrections behind it</summary><ul>${s.requests.map(r => `<li>
        <button type="button" class="link" data-record="${escapeText(r.id)}">${escapeText(r.id)}</button> ${escapeText(r.title)}
        ${r.reason ? `<br><span class="muted">${escapeText(r.reason)}</span>` : ''}</li>`).join('')}</ul></details>
      <div class="inline-row"><button type="button" class="primary" data-rule-approve="${escapeText(s.key)}">Approve rule</button>
        <button type="button" data-rule-dismiss="${escapeText(s.key)}">Dismiss</button></div></article>`).join('')}
    ${data.rules.length ? `<h4>Active learned rules</h4><ul class="rule-list">${data.rules.map(r => `<li>
      “${escapeText(r.word)}” → ${escapeText(ROUTE_NAMES[r.route] ?? r.route)}
      <span class="muted">· approved by ${escapeText(r.approved_by)} on ${escapeText(r.approved_at.slice(0, 10))} · from ${r.evidence.length} corrections</span>
      <button type="button" class="link" data-rule-remove="${escapeText(r.term)}">Remove</button></li>`).join('')}</ul>
      <p class="muted">Incidents are always checked first; learned rules come next, then the built-in rules.</p>` : ''}
    <p id="rules-error" class="error-text" role="alert"></p>`;
}

document.addEventListener('click', async event => {
  const approve = event.target.closest('[data-rule-approve]'), dismiss = event.target.closest('[data-rule-dismiss]');
  const remove = event.target.closest('[data-rule-remove]');
  if (!approve && !dismiss && !remove) return;
  const button = approve || dismiss || remove;
  button.disabled = true;
  const reply = remove
    ? await fetch(`/api/routing/rules/${encodeURIComponent(remove.dataset.ruleRemove)}`, {method: 'DELETE'}).then(r => r.ok ? r.json() : null)
    : await postJson(approve ? '/api/routing/rules' : '/api/routing/suggestions/dismiss',
                     {key: (approve || dismiss).dataset[approve ? 'ruleApprove' : 'ruleDismiss']}, 'rules-error');
  if (reply) loadRoutingRules(reply); else button.disabled = false;
});
