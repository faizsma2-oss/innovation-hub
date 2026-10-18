// Supplier companies: one page per company, from shortlist to the last step.
// Emails are drafted here, approved by a person, then sent from their Outlook (or the demo mailbox).

const COMPANY_STAGES = ['Shortlisted', 'Contacted', 'Meeting held', 'Pilot partner', 'Scaling', 'In operation'];
const TAG_STYLE = {'Pilot needed': 'rec-accept', Risk: 'rec-decline', Security: 'rec-ask', Decision: 'innovation', Pricing: 'feasibility'};
let m365Mode = 'demo';
fetch('/api/m365/status').then(r => r.json()).then(s => { m365Mode = s.mode; }).catch(() => {});

async function loadCompanies() {
  try {
    const companies = await fetch('/api/companies').then(r => r.json());
    get('companies-list').innerHTML = companies.length ? companies.map(c => `<button class="company-card" data-company="${escapeText(c.id)}">
      <span class="muted">${escapeText(c.id)}${c.country ? ` · ${escapeText(c.country)}` : ''}</span>
      <strong>${escapeText(c.name)}</strong>
      <span class="chip chip-${['Not chosen', 'Stopped'].includes(c.stage) ? 'rec-decline' : 'rec-accept'}">${escapeText(c.stage)}</span>
      <span class="muted">${c.requests.map(r => escapeText(r.id)).join(', ')}${c.next_meeting ? ` · meeting ${escapeText(when(c.next_meeting))}` : ''}</span>
      <span class="muted">${c.last_contact ? `Last contact ${escapeText(c.last_contact.slice(0, 10))}` : 'Not contacted yet'}${c.waiting_for_reply ? ' · <span class="flag">waiting for reply</span>' : ''}${c.drafts ? ` · <span class="flag">${c.drafts} ${c.drafts === 1 ? 'email' : 'emails'} to approve</span>` : ''}${c.open_actions ? ` · ${c.open_actions} open actions` : ''}</span>
    </button>`).join('') : '<p class="muted">No companies yet. Shortlist suppliers in a request\'s research and they appear here.</p>';
  } catch { /* stays empty */ }
}

document.addEventListener('click', event => {
  const card = event.target.closest('[data-company]');
  if (card) openCompany(card.dataset.company);
});
get('close-company').onclick = () => get('company-dialog').close();

async function openCompany(id) {
  const company = await fetch(`/api/companies/${id}`).then(r => r.json());
  renderCompany(company);
  if (!get('company-dialog').open) get('company-dialog').showModal();
}

function renderCompany(c) {
  get('company-title').textContent = c.name;
  const reached = COMPANY_STAGES.indexOf(c.stage);
  const emailContacts = c.contacts.filter(x => isEmail(x.value));
  const requestOptions = c.requests.map(r => `<option value="${escapeText(r.id)}">${escapeText(r.id)} · ${escapeText(r.title)}</option>`).join('');
  const f = c.facts;
  const drafts = c.emails.filter(e => e.status === 'DRAFT');
  const thread = c.emails.filter(e => e.status !== 'DRAFT');

  get('company-body').innerHTML = `
    <p class="muted">${c.website ? `<a href="${escapeText(c.website)}" target="_blank" rel="noopener noreferrer">${escapeText(c.website)}</a> · ` : ''}${escapeText(c.country ?? '')}</p>
    ${['Not chosen', 'Stopped'].includes(c.stage) ? `<p class="warning">${escapeText(c.stage)}</p>`
      : `<ol class="stepper">${COMPANY_STAGES.map((s, i) => `<li class="${i <= reached ? 'done' : ''}">${s}</li>`).join('')}</ol>`}
    <p class="notice">${m365Mode === 'graph' ? 'Emails go from your own Outlook after you approve them; meetings are booked in your Outlook calendar with a Teams link.'
      : '<strong>Demo mailbox:</strong> emails, replies, Teams links and transcripts here are fictional. With Microsoft 365 connected, the same buttons use your Outlook and Teams.'}</p>

    <div class="plan-grid">
      <div><h5>Requests</h5>${c.requests.map(r => `<p><button class="link" data-record="${escapeText(r.id)}">${escapeText(r.id)}</button> ${escapeText(r.title)}<br>
        <span class="muted">${escapeText(r.status)} · ${escapeText(r.stage)}</span></p>`).join('') || '<p class="muted">None</p>'}</div>
      <div><h5>What research found</h5>${f ? `<p>${escapeText(f.offering ?? '')}</p><p class="muted">Rank #${f.rank ?? '–'}${f.fit_score != null ? ` · fit ${f.fit_score}/100` : ''}
        ${f.eligibility ? ` · ${escapeText(f.eligibility)}` : ''}</p>${f.cost ? `<p class="muted">Cost: ${escapeText(typeof f.cost === 'string' ? f.cost
          : [f.cost.published_price, f.cost.estimate && `estimate ${f.cost.estimate}`, f.cost.relative && `${f.cost.relative} relative to others`].filter(Boolean).join(' · '))}</p>` : ''}` : '<p class="muted">Not researched</p>'}</div>
      <div><h5>Open actions</h5>${c.actions.length ? `<ul>${c.actions.map(a => `<li>${escapeText(a.action)} <span class="muted">· ${a.owner === 'UNASSIGNED'
        ? '<span class="flag">no owner</span>' : escapeText(a.owner)}${a.due ? ` · due ${escapeText(a.due)}` : ''}</span></li>`).join('')}</ul>` : '<p class="muted">None</p>'}</div>
    </div>

    <h4>Official contacts</h4>
    ${c.contacts.length ? `<ul class="contact-list">${c.contacts.map(x => `<li><span class="chip ${x.best ? 'chip-rec-accept' : ''}">${x.best ? 'Best route · ' : ''}${escapeText(x.label)}</span>
      ${escapeText(x.value)} <span class="muted">${x.region && x.region !== 'unknown' ? escapeText(x.region) : x.added_by && x.added_by !== 'research-ai' ? 'added by the team' : ''}${x.note ? ` · ${escapeText(x.note)}` : ''}</span>
      ${isEmail(x.value) ? `<button type="button" class="link" data-write="${escapeText(x.value)}">Write</button>` : ''}</li>`).join('')}</ul>`
      : '<p class="muted">No contacts yet. Open the request and use "Find official contacts" under the supplier.</p>'}

    <h4>Email</h4>
    ${emailContacts.length ? `<form id="co-compose" class="supplier-form">
      <div class="inline-row"><label>To <select id="co-to">${emailContacts.map(x => `<option>${escapeText(x.value)}</option>`).join('')}</select></label>
        ${c.requests.length ? `<label>About <select id="co-request">${requestOptions}</select></label>` : ''}</div>
      <input id="co-subject" required maxlength="200" placeholder="Subject">
      <textarea id="co-body" required rows="6" maxlength="10000" placeholder="Write the email. It stays a draft until someone approves it."></textarea>
      <button type="submit">Save as draft</button></form>` : '<p class="muted">Add an official email contact first. Emails can only go to contacts on this page.</p>'}
    ${drafts.map(e => `<div class="draft-email" data-email="${e.id}"><p><span class="status">DRAFT</span> to ${escapeText(e.address)}${e.submission_id ? ` · ${escapeText(e.submission_id)}` : ''}</p>
      <input class="de-subject" value="${escapeText(e.subject)}" maxlength="200" aria-label="Subject">
      <textarea class="de-body" rows="6" maxlength="10000" aria-label="Email">${escapeText(e.body)}</textarea>
      <label class="approve"><input type="checkbox" class="de-approve"> I've read this and approve sending it ${m365Mode === 'graph' ? 'from my Outlook' : '(demo mailbox)'}</label>
      <button type="button" class="primary de-send" disabled>Approve &amp; send</button></div>`).join('')}
    ${thread.length ? `<ul class="email-thread">${thread.map(e => `<li class="${e.direction}">
      <p class="muted">${e.direction === 'out' ? `Sent to ${escapeText(e.address)} · approved by ${escapeText(e.approved_by)}` : `Reply from ${escapeText(e.address)}`} · ${escapeText((e.at ?? '').slice(0, 16).replace('T', ' '))}</p>
      <strong>${escapeText(e.subject)}</strong><p class="email-text">${escapeText(e.body)}</p>
      ${e.offered?.times?.length ? `<p class="muted">Times offered: ${e.offered.times.map(t => t.ok ? escapeText(t.start.replace('T', ' '))
        : `<s>${escapeText(t.quote)}</s> (${escapeText(t.problem)})`).join(' · ')}${e.meeting_pk ? ` · <button type="button" class="link" data-open-meeting="${e.meeting_pk}">book on the meeting</button>` : ''}</p>` : ''}</li>`).join('')}</ul>` : ''}
    ${thread.some(e => e.direction === 'out') ? `<div class="inline-row"><button type="button" id="co-replies">Check for replies</button><span class="muted" id="co-replies-status"></span></div>` : ''}

    <h4>Meetings</h4>
    ${c.meetings.length ? `<ul class="contact-list">${c.meetings.map(m => `<li><button type="button" class="link" data-open-meeting="${m.id}">${escapeText(m.title)}</button>
      <span class="muted"> · ${escapeText(STATUS_LABELS[m.status] ?? m.status)}${m.start_at ? ` · ${escapeText(when(m.start_at))}` : ''}${m.booked_in_outlook ? ' · in Outlook' : ''}</span>
      ${m.summary ? `<br><span class="muted">${escapeText(m.summary)}</span>` : ''}</li>`).join('')}</ul>` : '<p class="muted">No meetings yet. Plan one from the request, under this supplier.</p>'}

    <h4>Notes</h4>
    <form id="co-note" class="supplier-form">
      <div class="inline-row"><label>Topic <select id="co-tag">${c.tags.map(t => `<option>${escapeText(t)}</option>`).join('')}</select></label>
        ${c.requests.length ? `<label>Request <select id="co-note-request">${requestOptions}</select></label>` : ''}</div>
      <textarea id="co-note-text" required rows="2" maxlength="3000" placeholder="e.g. They need two weeks with our own data before a pilot; quote expected Thursday"></textarea>
      <button type="submit">Add note</button></form>
    ${c.notes.length ? `<ul class="notes-list">${c.notes.map(n => `<li><span class="chip chip-${TAG_STYLE[n.tag] ?? ''}">${escapeText(n.tag)}</span>
      <span class="muted">${escapeText(n.stage)}${n.submission_id ? ` · ${escapeText(n.submission_id)}` : ''} · ${escapeText(n.created_at.slice(0, 10))}</span>
      <p>${escapeText(n.text)}</p>${noteFactsHtml(n)}</li>`).join('')}</ul>` : ''}

    <details class="copilot-box"><summary>What Copilot sees about ${escapeText(c.name)}</summary>
      <p class="muted">The Innovation Hub Copilot agent reads exactly this, through <code>/api/copilot/companies/${escapeText(c.id)}</code>.
        Ask it in Teams or Outlook: “Where are we with ${escapeText(c.name)}?”</p>
      <pre id="co-copilot">Loading…</pre></details>

    <h4>Timeline</h4>
    <ul class="timeline">${c.timeline.map(t => `<li><span class="muted">${escapeText((t.at ?? '').slice(0, 10))}</span> ${escapeText(t.text)}</li>`).join('') || '<li class="muted">Nothing yet</li>'}</ul>
    <p id="company-error" class="error-text" role="alert"></p>`;
  wireCompany(c);
}

// Facts a note suggests for each supplier comparison it's relevant to. Apply changes the comparison; nothing else does.
function noteFactsHtml(n) {
  const entries = Object.entries(n.facts ?? {});
  if (!entries.length) return '';
  const must = {yes: 'must-have met', no: 'must-have NOT met', unknown: ''};
  return entries.map(([sid, f]) => `<div class="note-facts"><p class="muted">For the supplier comparison in ${escapeText(sid)}:</p>
    ${f.suggestions.map(s => `<div class="note-fact">
      <p><strong>${escapeText(s.factor)}</strong>: ${escapeText(s.finding)}${s.rating ? ` · ${'●'.repeat(s.rating)}` : ''}
        ${must[s.must_have_met] ? ` · <span class="${s.must_have_met === 'no' ? 'flag' : ''}">${must[s.must_have_met]}</span>` : ''}</p>
      <p class="muted">Comparison says now: ${escapeText(s.now ?? 'nothing')}</p>
      ${s.status === 'SUGGESTED' ? `<div class="inline-row"><button type="button" class="primary" data-fact="apply" data-note="${n.pk}" data-sid="${escapeText(sid)}" data-key="${escapeText(s.factor_key)}">Apply to comparison</button>
        <button type="button" data-fact="dismiss" data-note="${n.pk}" data-sid="${escapeText(sid)}" data-key="${escapeText(s.factor_key)}">Dismiss</button></div>`
        : `<span class="status">${escapeText(s.status)}</span>`}</div>`).join('')}
    <p class="muted">Suggested by ${escapeText(f.generated_by)} from the note's own words.</p></div>`).join('');
}

function wireCompany(c) {
  const send = async (url, body, button) => {
    if (button) button.disabled = true;
    const result = await postJson(url, body, 'company-error');   // postJson: js/meetings.js
    if (result) { renderCompany(result); loadCompanies(); loadSubmissions(); } else if (button) button.disabled = false;
    return result;
  };
  for (const link of document.querySelectorAll('[data-write]')) {
    link.onclick = () => { get('co-to').value = link.dataset.write; get('co-subject').focus(); };
  }
  if (get('co-compose')) get('co-compose').onsubmit = event => {
    event.preventDefault();
    send(`/api/companies/${c.id}/emails`, {to: get('co-to').value, subject: get('co-subject').value, body: get('co-body').value,
      submission_id: get('co-request')?.value || null}, submitButton(event));
  };
  for (const box of document.querySelectorAll('.draft-email')) {
    const button = box.querySelector('.de-send');
    box.querySelector('.de-approve').onchange = event => { button.disabled = !event.target.checked; };
    button.onclick = () => {
      button.textContent = 'Sending…';
      send(`/api/emails/${box.dataset.email}/send`, {confirm: box.querySelector('.de-approve').checked,
        subject: box.querySelector('.de-subject').value, body: box.querySelector('.de-body').value}, button);
    };
  }
  if (get('co-replies')) get('co-replies').onclick = async () => {
    const result = await send(`/api/companies/${c.id}/check-replies`, {}, get('co-replies'));
    if (result) get('co-replies-status').textContent = result.new_replies ? `${result.new_replies} new` : 'No new replies';
  };
  for (const button of document.querySelectorAll('[data-fact]')) {
    button.onclick = () => send(`/api/notes/${button.dataset.note}/facts`,
      {submission_id: button.dataset.sid, factor_key: button.dataset.key, action: button.dataset.fact}, button);
  }
  get('co-note').onsubmit = event => {
    event.preventDefault();
    send(`/api/companies/${c.id}/notes`, {text: get('co-note-text').value, tag: get('co-tag').value,
      submission_id: get('co-note-request')?.value || null}, submitButton(event));
  };
  fetch(`/api/copilot/companies/${c.id}`).then(r => r.json()).then(view => { get('co-copilot').textContent = JSON.stringify(view, null, 2); })
    .catch(() => { get('co-copilot').textContent = 'Not available'; });
}
