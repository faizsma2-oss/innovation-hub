// Portfolio board (every opportunity by stage) and the weekly management report.
// The report's facts are collected by the server from the records; the AI writes only the summary at the top.

async function loadPortfolio() {
  try {
    const board = await fetch('/api/portfolio').then(reply => reply.json());
    get('portfolio-board').innerHTML = board.stages.map(stage => `<div class="stage">
      <h5>${escapeText(stage.name)} <span>${stage.cards.length}</span></h5>
      ${stage.cards.map(card => `<button class="stage-card" data-record="${escapeText(card.id)}">
        <span class="muted">${escapeText(card.id)}${card.score != null ? ` · ${card.score}/100` : ''}${card.requested ? ' · requested' : ''}</span>
        <strong>${escapeText(card.title)}</strong>
        ${card.approach ? `<span class="muted">${escapeText(card.approach)}${card.partner ? ` · ${escapeText(card.partner)}` : ''}</span>` : ''}
        <span class="muted">${card.status === stage.name ? '' : `${escapeText(card.status)} · `}${card.days_in_stage} ${card.days_in_stage === 1 ? 'day' : 'days'}
          · ${card.owner === 'UNASSIGNED' ? '<span class="flag">no owner</span>' : escapeText(card.owner)}</span></button>`).join('')
        || '<p class="muted">Empty</p>'}</div>`).join('');
    const reports = await fetch('/api/reports').then(reply => reply.json());
    if (reports.length && !get('weekly-report').innerHTML) renderReport(reports[0]);
  } catch (error) {
    get('portfolio-board').innerHTML = `<p class="error-text">Could not load the portfolio. ${escapeText(error.message)}</p>`;
  }
}

function renderReport(r) {
  const rows = (items, line) => items.length ? `<ul>${items.map(item => `<li>${line(item)}</li>`).join('')}</ul>` : '<p class="muted">None</p>';
  const ref = item => `<button class="link" data-record="${escapeText(item.id)}">${escapeText(item.id)}</button> ${escapeText(item.title ?? '')}`;
  get('weekly-report').innerHTML = `<article class="report">
    <div class="solutions-head"><div><p class="eyebrow">WEEKLY REPORT · ${escapeText(r.period)}</p><h3>Innovation portfolio update</h3></div>
      <span class="status">${escapeText(r.status)}</span></div>
    <p class="report-summary">${escapeText(r.summary)}</p>
    <p class="muted">Summary by ${escapeText(r.generated_by)}. Every line below comes straight from the records.</p>
    <div class="plan-grid">
      <div><h5>Pipeline</h5>${rows(r.pipeline, p => `${escapeText(p.stage)}: ${p.count}`)}</div>
      <div><h5>Decisions needed</h5>${rows(r.decisions_needed, d => `${ref(d)}: <strong>${escapeText(d.decision)}</strong> <span class="muted">${escapeText(d.detail)}</span>`)}</div>
      <div><h5>Moved this week</h5>${rows(r.moved, m => `${ref(m)}: ${escapeText(m.from)} → <strong>${escapeText(m.to)}</strong>${m.steps > 1 ? ` <span class="muted">(${m.steps} steps)</span>` : ''}`)}</div>
      <div><h5>Results</h5>${rows(r.results, x => `${ref(x)}: ${escapeText(x.what)} <span class="muted">${escapeText(x.detail)}</span>`)}</div>
      <div><h5>Budgets approved</h5>${rows(r.budgets_approved, b => `${ref(b)}: ${money(b.one_off, b.currency)} one-off, ${money(b.yearly, b.currency)}/year`)}</div>
      <div><h5>Benefits realised</h5>${rows(r.benefits_realised, b => `${ref(b)}: ${escapeText(b.verdict)}, about ${money(b.annual, b.currency)}/year`)}</div>
      <div><h5>Supplier meetings held</h5>${rows(r.meetings_held, m => `${escapeText(m.id)} ${escapeText(m.supplier)} (${escapeText(m.date)})`)}</div>
      <div><h5>Overdue actions</h5>${rows(r.overdue_actions, a => `${escapeText(a.id)} ${escapeText(a.action)} · ${escapeText(a.owner)} · due ${escapeText(a.due)}`)}</div>
      <div><h5>Blockers</h5>${rows(r.blockers, b => escapeText(b))}</div>
    </div>
    <p class="muted">AI spend this week: $${r.ai_spend_usd.toFixed(2)}</p>
    <div class="inline-row"><button type="button" id="copy-report">Copy as text for email</button><span id="copy-status" class="muted"></span></div>
  </article>`;
  get('copy-report').onclick = async () => {
    try {
      await navigator.clipboard.writeText(reportText(r));
      get('copy-status').textContent = 'Copied. Paste it into Outlook, check it, and send it yourself.';
    } catch {
      get('copy-status').textContent = 'Copy was blocked by the browser.';
    }
  };
}

function reportText(r) {
  const section = (title, items, line) => `${title}\n${items.length ? items.map(item => `- ${line(item)}`).join('\n') : '- None'}\n`;
  return [`Innovation portfolio update, ${r.period}`, '', r.summary, '',
    section('Pipeline', r.pipeline, p => `${p.stage}: ${p.count}`),
    section('Decisions needed', r.decisions_needed, d => `${d.id} ${d.title}: ${d.decision} (${d.detail})`),
    section('Moved this week', r.moved, m => `${m.id} ${m.title}: ${m.from} → ${m.to}`),
    section('Results', r.results, x => `${x.id} ${x.title}: ${x.what}. ${x.detail}`),
    section('Budgets approved', r.budgets_approved, b => `${b.id} ${b.title}: ${money(b.one_off, b.currency)} one-off, ${money(b.yearly, b.currency)}/year`),
    section('Benefits realised', r.benefits_realised, b => `${b.id} ${b.title}: ${b.verdict}, about ${money(b.annual, b.currency)}/year`),
    section('Overdue actions', r.overdue_actions, a => `${a.id} ${a.action} (${a.owner}, due ${a.due})`),
    section('Blockers', r.blockers, b => b),
    'Fictional demo data. Prepared with the Innovation Hub.'].join('\n');
}

get('weekly-button').onclick = async () => {
  const button = get('weekly-button');
  button.disabled = true;
  button.textContent = 'Collecting this week…';
  try {
    const reply = await fetch('/api/reports/weekly', {method: 'POST'});
    if (!reply.ok) throw new Error(`status ${reply.status}`);
    renderReport(await reply.json());
  } catch (error) {
    get('weekly-report').innerHTML = `<p class="error-text">Could not prepare the report. ${escapeText(error.message)}</p>`;
  }
  button.disabled = false;
  button.textContent = 'Prepare this week\'s report';
};
