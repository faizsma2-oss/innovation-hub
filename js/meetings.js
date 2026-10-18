// Meetings: supplier contacts, each meeting from draft invitation to debrief, and the Today panel.
// Nothing is sent by the app. "Open in Outlook" fills a new email that a person reviews and sends,
// and "Add to calendar" downloads a standard .ics invite that opens in Outlook or Teams.

const STATUS_LABELS = {planned: 'Draft ready', invite_sent: 'Waiting for reply', scheduled: 'Scheduled',
  held: 'Held', cancelled: 'Cancelled'};
const REMINDER_ICONS = {follow_up: '✉️', needs_notes: '📝', upcoming: '📅', overdue: '⏰', due_soon: '⏳',
  no_owner: '👤', pilot_ended: '🧪', decision: '⚖️', checkin: '📈', report: '📊', replied: '📨'};
let contactTypes = [];
fetch('/api/meetings/contact-types').then(r => r.json()).then(list => { contactTypes = list; }).catch(() => {});

const mailto = (to, subject, body) =>
  `mailto:${encodeURIComponent(to || '')}?subject=${encodeURIComponent(subject || '')}&body=${encodeURIComponent(body || '')}`;
const when = iso => iso ? new Date(iso).toLocaleString([], {weekday: 'short', day: 'numeric', month: 'short', hour: '2-digit', minute: '2-digit'}) : '–';
const isEmail = value => /^[^@\s]+@[^@\s]+\.[^@\s]+$/.test(value || '');

// ── Contacts on each shortlisted supplier ────────────────────────────────────

function contactsHtml(record, supplier) {
  if (!['Research', 'Pilot planning', 'Pilot running'].includes(record.status)) return '';
  const book = record.research.contacts?.[supplier];
  const contacts = book?.contacts ?? [];
  const link = c => c.type === 'phone' ? `tel:${c.value.replace(/[^+0-9]/g, '')}` : isEmail(c.value) ? `mailto:${c.value}` : c.value;
  return `<details class="contacts-box" ${contacts.length ? '' : 'open'}><summary>Contacts and meetings${contacts.length ? ` · ${contacts.length} contacts` : ''}</summary>
    ${book?.notice ? `<p class="notice-inline">${escapeText(book.notice)}</p>`
      : book?.summary ? `<p class="muted">${escapeText(book.summary)}</p>` : ''}
    ${book?.error ? `<p class="warning">The live search didn't work (${escapeText(book.error)}), so these are example contacts. Try “Search again”, or add a contact you already have.</p>` : ''}
    ${contacts.length ? `<ul class="contact-list">${contacts.map(c => `<li>
        <span class="chip ${c.best ? 'chip-rec-accept' : ''}">${c.best ? 'Best route · ' : ''}${escapeText(c.label)}</span>
        <a href="${escapeText(link(c))}" target="_blank" rel="noopener noreferrer">${escapeText(c.value)}</a>
        <span class="muted">${escapeText(c.region)}${c.note ? ` · ${escapeText(c.note)}` : ''}${c.source_url ? ` · <a href="${escapeText(c.source_url)}" target="_blank" rel="noopener noreferrer">source</a>` : ' · added by the team'}</span>
        ${c.flags.map(f => `<br><span class="warning-inline">${escapeText(f)}</span>`).join('')}</li>`).join('')}</ul>`
      : '<p class="muted">The Research AI looks only for official business channels (sales, partnerships, demo booking, UAE office, local partner), each with its source page. No personal details.</p>'}
    <div class="inline-row">
      <button type="button" class="find-contacts" data-fresh="${contacts.length ? 1 : 0}">${contacts.length ? 'Search again' : 'Find official contacts'}</button>
      <button type="button" class="primary plan-meeting">Plan a meeting</button>
    </div>
    <details class="add-contact"><summary>Add a contact you already have</summary>
      <div class="inline-row"><select class="ac-type">${contactTypes.map(t => `<option value="${t.type}">${escapeText(t.label)}</option>`).join('')}</select>
        <input class="ac-value" placeholder="e.g. uae.sales@company.com" maxlength="200">
        <input class="ac-note" placeholder="Where it came from" maxlength="200">
        <button type="button" class="ac-save">Add</button></div>
    </details>
  </details>`;
}

function wireContacts(record) {
  for (const track of document.querySelectorAll('.track')) {
    const supplier = track.dataset.supplier;
    const find = track.querySelector('.find-contacts');
    if (!find) continue;
    find.onclick = async () => {
      find.disabled = true;
      const fresh = find.dataset.fresh === '1';
      find.textContent = fresh ? 'Searching official channels… (about a minute)' : 'Checking contacts on file, then searching…';
      await postJson(`/api/submissions/${record.id}/contacts/find`, {supplier, fresh}, 'evaluation-error');
      await loadSubmissions(); openDetail(record.id);
    };
    track.querySelector('.ac-save').onclick = async () => {
      await postJson(`/api/submissions/${record.id}/contacts/add`, {supplier, type: track.querySelector('.ac-type').value,
        value: track.querySelector('.ac-value').value, note: track.querySelector('.ac-note').value}, 'evaluation-error');
      await loadSubmissions(); openDetail(record.id);
    };
    track.querySelector('.plan-meeting').onclick = () => openPlanner(record, supplier);
  }
}

// The button that submitted a form (also when it was submitted with Enter or by a script).
const submitButton = event => event.submitter || event.target.querySelector('[type=submit]');

async function postJson(url, body, errorId) {
  const response = await fetch(url, {method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify(body)});
  const reply = await response.json().catch(() => ({}));
  if (!response.ok) {
    const detail = Array.isArray(reply.detail) ? reply.detail.map(p => p.msg.replace('Value error, ', '')).join('; ') : reply.detail;
    if (errorId && get(errorId)) get(errorId).textContent = detail || `Error ${response.status}`;
    return null;
  }
  return reply;
}

// ── Planning a meeting ───────────────────────────────────────────────────────

function openPlanner(record, supplier) {
  const contacts = (record.research.contacts?.[supplier]?.contacts ?? []).filter(c => isEmail(c.value));
  get('meeting-title').textContent = `Plan a meeting with ${supplier}`;
  get('meeting-body').innerHTML = `<form id="planner" class="supplier-form">
    <h4>Who do we write to?</h4>
    <select id="pl-contact">${contacts.map(c => `<option value="${escapeText(c.value)}">${escapeText(c.value)} (${escapeText(c.label)})</option>`).join('')}
      <option value="">I'll add the address in Outlook</option></select>
    <h4>When could we meet? (UAE time, up to 3 options)</h4>
    <div class="inline-row">${[0, 1, 2].map(i => `<input type="datetime-local" class="pl-slot" aria-label="Option ${i + 1}">`).join('')}</div>
    <h4>Or share a booking link (optional)</h4>
    <input id="pl-booking" placeholder="https://outlook.office.com/bookwithme/… (Microsoft Bookings) or Calendly" maxlength="300">
    <div class="inline-row"><label>Length <select id="pl-duration"><option>30</option><option selected>45</option><option>60</option></select> minutes</label>
      <input id="pl-attendees" placeholder="Our attendees, e.g. Sara (Ops), Omar (IT)" maxlength="300"></div>
    <button type="submit" class="primary">Draft agenda and invitation</button>
    <p class="muted">The AI drafts an agenda (blocking questions first) and an invitation. You review it and send it from Outlook.</p>
    <p id="meeting-error" class="error-text" role="alert"></p></form>`;
  get('planner').onsubmit = async event => {
    event.preventDefault();
    const button = submitButton(event);
    button.disabled = true; button.textContent = 'Drafting…';
    const meeting = await postJson('/api/meetings', {
      submission_id: record.id, supplier, contact: get('pl-contact').value || null,
      proposed_slots: [...document.querySelectorAll('.pl-slot')].map(i => i.value).filter(Boolean),
      booking_link: get('pl-booking').value.trim() || null, duration_min: Number(get('pl-duration').value),
      internal_attendees: get('pl-attendees').value}, 'meeting-error');
    if (meeting) { renderMeeting(meeting); loadMeetings(); } else { button.disabled = false; button.textContent = 'Try again'; }
  };
  if (!get('meeting-dialog').open) get('meeting-dialog').showModal();
}

// ── One meeting, stage by stage ──────────────────────────────────────────────

async function openMeeting(id) {
  const meeting = await fetch(`/api/meetings/${id}`).then(r => r.json());
  renderMeeting(meeting);
  if (!get('meeting-dialog').open) get('meeting-dialog').showModal();
}

function renderMeeting(m) {
  get('meeting-title').textContent = m.supplier;
  const stages = ['planned', 'invite_sent', 'scheduled', 'held'];
  const reached = stages.indexOf(m.status);
  const plan = m.plan ?? {agenda: []};
  let html = `<p class="muted">${escapeText(m.title)} · ${escapeText(m.submission_id)}</p>
    ${m.status === 'cancelled' ? `<p class="warning">Cancelled: ${escapeText(m.cancelled_reason)}</p>` :
    `<ol class="stepper">${stages.map((s, i) => `<li class="${i <= reached ? 'done' : ''}">${STATUS_LABELS[s]}</li>`).join('')}</ol>`}
    <h4>Agenda</h4><ol class="agenda">${plan.agenda.map(a => `<li>${escapeText(a.item)} <span class="muted">${a.minutes} min</span></li>`).join('')}</ol>`;

  if (m.status === 'planned') {
    html += `<h4>Invitation <span class="status">DRAFT, not sent</span></h4>
      ${(plan.flags ?? []).map(f => `<p class="warning">${escapeText(f)}</p>`).join('')}
      <input id="mt-subject" value="${escapeText(plan.email_subject)}" aria-label="Subject">
      <textarea id="mt-body" rows="9" aria-label="Email">${escapeText(plan.email_body)}</textarea>
      ${isEmail(m.contact) ? `<label class="approve"><input type="checkbox" id="mt-approve"> I've read this and approve sending it to ${escapeText(m.contact)}
          ${typeof m365Mode !== 'undefined' && m365Mode === 'graph' ? 'from my Outlook' : '(demo mailbox)'}</label>
        <div class="inline-row"><button type="button" class="primary" id="mt-send" disabled>Approve &amp; send</button></div>
        <p class="muted">Or do it yourself: <a href="#" id="mt-outlook">open in Outlook</a>, send it, then <button type="button" class="link" id="mt-sent">mark as sent</button>.</p>`
      : `<div class="inline-row">
        <a class="button primary" id="mt-outlook" href="#">Open in Outlook</a>
        <button type="button" id="mt-sent">I've sent it</button>
      </div>
      <p class="muted">No official email contact was chosen, so the Hub can't send it. Opens a new email in Outlook; add the address and send it yourself.</p>`}`;
  }
  if (m.status === 'invite_sent') {
    const followUp = `Dear ${m.supplier} team,\n\nI wanted to follow up on my note about an introductory call. Would any time next week suit you?\n\nKind regards,\n[Your name]`;
    html += m.replies.length ? m.replies.map(replyHtml).join('')
      : `<p>Sent ${escapeText(m.sent_at?.slice(0, 10))}. <strong>Follow up by ${escapeText(m.reply_due)}</strong> if there's no reply.</p>
      <div class="inline-row"><button type="button" id="mt-replies">Check for replies</button>
        <a class="button" href="${escapeText(mailto(m.contact, `Re: ${plan.email_subject}`, followUp))}">Draft a follow-up in Outlook</a>
        <span class="muted" id="mt-replies-status"></span></div>`;
  }
  if (['planned', 'invite_sent', 'scheduled'].includes(m.status)) {
    html += `<h4>${m.status === 'scheduled' ? 'Change the time' : 'They replied: confirm the time'}</h4>
      <form id="mt-schedule" class="inline-row">
        <input type="datetime-local" id="mt-start" required value="${escapeText(m.start_at ?? '')}" aria-label="Start (UAE time)">
        <select id="mt-duration">${[30, 45, 60, 90].map(n => `<option ${n === (m.duration_min ?? 45) ? 'selected' : ''}>${n}</option>`).join('')}</select>
        <input id="mt-teams" placeholder="Teams join link (create it in Outlook: New Teams meeting)" value="${escapeText(m.teams_link ?? '')}">
        <button type="submit">${m.status === 'scheduled' ? 'Update' : 'Confirm'}</button>
        <button type="button" class="primary" id="mt-book">Book in Outlook with Teams</button></form>
      <p class="muted">"Book" creates the Outlook calendar event with a Teams link and invites the supplier contact${typeof m365Mode !== 'undefined' && m365Mode === 'graph' ? '' : ' (demo: a fictional Teams link)'}. "Confirm" just records a time you booked yourself.</p>`;
  }
  if (m.status === 'scheduled') {
    html += `<div class="gate ready"><p><strong>${escapeText(when(m.start_at))}</strong> (UAE time), ${m.duration_min} minutes
        ${m.teams_link ? ` · <a href="${escapeText(m.teams_link)}" target="_blank" rel="noopener noreferrer">Teams link</a>` : ''}</p>
      <div class="inline-row"><a class="button primary" href="/api/meetings/${m.id}/invite.ics" download>Add to calendar (.ics)</a></div>
      <p class="muted">Opens in Outlook or Teams with the agenda and a 15-minute reminder.</p></div>`;
  }
  if (['scheduled', 'invite_sent', 'held'].includes(m.status)) {
    html += `<h4>${m.status === 'held' ? 'Update the debrief' : 'After the meeting'}</h4>
      ${m.teams_link ? '<div class="inline-row"><button type="button" id="mt-transcript">Fetch the Teams transcript</button><span class="muted" id="mt-transcript-status"></span></div>' : ''}
      <form id="mt-debrief"><textarea id="mt-notes" rows="6" minlength="20" required
        placeholder="Paste the Teams Copilot recap, a transcript, or your notes: who attended, what was said, what was agreed…">${escapeText(m.notes ?? '')}</textarea>
      <button type="submit" class="primary">Summarise, find actions and next steps</button></form>`;
  }
  if (m.debrief) html += debriefHtml(m);
  if (['planned', 'invite_sent', 'scheduled'].includes(m.status)) {
    html += `<details class="ask-again"><summary>Cancel this meeting</summary><div class="inline-row">
      <input id="mt-cancel-reason" placeholder="Why? (required)" maxlength="500"><button type="button" id="mt-cancel">Cancel meeting</button></div></details>`;
  }
  get('meeting-body').innerHTML = html + '<p id="meeting-error" class="error-text" role="alert"></p>';
  wireMeeting(m);
}

// A supplier's reply, with the times it offers as buttons that fill in the booking form below.
function replyHtml(r) {
  const offered = r.offered ?? {times: [], vague: []};
  const label = t => new Date(`${t.start}:00+04:00`).toLocaleString([], {weekday: 'short', day: 'numeric', month: 'short',
    hour: '2-digit', minute: '2-digit', timeZone: 'Asia/Dubai'});
  return `<div class="reply-box"><p class="muted">Reply from ${escapeText(r.from)} · ${escapeText((r.at ?? '').slice(0, 16).replace('T', ' '))}</p>
    <p class="email-text">${escapeText(r.body)}</p>
    ${offered.times.length ? `<h5>Times offered</h5><div class="offered-times">${offered.times.map(t => t.ok
      ? `<button type="button" class="offered" data-start="${escapeText(t.start)}" title="From: “${escapeText(t.quote)}”">${escapeText(label(t))}
          ${t.timezone ? `<small>(${escapeText(t.original.slice(11))} ${escapeText(t.timezone)})</small>` : ''}${t.warning ? ` <small class="flag">${escapeText(t.warning)}</small>` : ''}</button>`
      : `<span class="offered-bad" title="From: “${escapeText(t.quote)}”">${escapeText(t.quote)}: <span class="flag">${escapeText(t.problem)}</span></span>`).join('')}</div>
      <p class="muted">Pick one to fill in the booking below, then book it. Read by ${escapeText(offered.generated_by)}; each time is checked against the email.</p>` : ''}
    ${offered.vague.length ? `<p class="muted">Also suggested, needs an answer from you: ${escapeText(offered.vague.join('; '))}</p>` : ''}
    ${!offered.times.length && !offered.vague.length ? '<p class="muted">No specific time found in this reply.</p>' : ''}</div>`;
}

function debriefHtml(m) {
  const d = m.debrief;
  return `<div class="debrief"><h4>Debrief <span class="status">DRAFT</span></h4>
    <p>${escapeText(d.summary)}</p>
    ${d.decisions.length ? `<h5>Decisions</h5>${list(d.decisions)}` : ''}
    <h5>Actions</h5>${m.actions.length ? `<table class="scores actions-table"><tbody>${m.actions.map(a => `<tr data-action="${a.pk}">
      <td><input type="checkbox" class="ax-done" ${a.status === 'done' ? 'checked' : ''} aria-label="Done"></td>
      <td class="${a.status === 'done' ? 'muted' : ''}">${escapeText(a.action)}</td>
      <td><input class="ax-owner ${a.owner === 'UNASSIGNED' ? 'flag' : ''}" value="${escapeText(a.owner)}" aria-label="Owner"></td>
      <td><input type="date" class="ax-due" value="${escapeText(a.due ?? '')}" aria-label="Due"><br><span class="muted">${escapeText(a.due_text ?? '')}</span></td>
      <td><button type="button" class="ax-save">Save</button></td></tr>`).join('')}</tbody></table>` : '<p class="muted">None recorded.</p>'}
    <h5>Suggested next steps</h5><ol>${d.next_steps.map(s => `<li><strong>${escapeText(s.step)}</strong><br><span class="muted">${escapeText(s.why)}</span></li>`).join('')}</ol>
    ${d.risks.length ? `<h5>Risks</h5>${list(d.risks)}` : ''}
    ${d.answers.filter(a => a.answer).length ? `<h5>Answers</h5>${list(d.answers.filter(a => a.answer).map(a => `${a.question}: ${a.answer}`))}` : ''}
    ${d.factor_updates.length ? '<p class="muted">The supplier comparison was updated (labelled as verbal claims until confirmed in writing).</p>' : ''}
    <h5>Follow-up email <span class="status">DRAFT</span></h5>
    ${(d.flags ?? []).map(f => `<p class="warning">${escapeText(f)}</p>`).join('')}
    <div class="inline-row"><a class="button" href="${escapeText(mailto(m.contact, d.follow_up_subject, d.follow_up_body))}">Open follow-up in Outlook</a></div>
    <p class="muted">By ${escapeText(d.generated_by)}. Owners and dates come only from the notes; anything else stays UNASSIGNED / NO DATE AGREED.</p></div>`;
}

function wireMeeting(m) {
  const act = async (path, body, button) => {
    if (button) button.disabled = true;
    const updated = await postJson(`/api/meetings/${m.id}/${path}`, body ?? {}, 'meeting-error');
    if (updated) { renderMeeting(updated); loadSubmissions(); } else if (button) button.disabled = false;
  };
  if (get('mt-outlook')) {
    get('mt-outlook').onclick = event => { event.currentTarget.href = mailto(m.contact, get('mt-subject').value, get('mt-body').value); };
  }
  if (get('mt-sent')) get('mt-sent').onclick = () => act('sent', {}, get('mt-sent'));
  if (get('mt-replies')) get('mt-replies').onclick = async () => {
    get('mt-replies').disabled = true;
    const updated = await postJson(`/api/meetings/${m.id}/check-replies`, {}, 'meeting-error');
    if (updated) {
      renderMeeting(updated);
      if (!updated.new_replies && get('mt-replies-status')) get('mt-replies-status').textContent = 'No reply yet.';
      loadMeetings();
    } else get('mt-replies').disabled = false;
  };
  for (const pick of document.querySelectorAll('.offered')) {
    pick.onclick = () => {
      document.querySelectorAll('.offered').forEach(b => b.classList.toggle('picked', b === pick));
      get('mt-start').value = pick.dataset.start;
      get('mt-book').classList.add('primary');
      get('mt-start').scrollIntoView({behavior: 'smooth', block: 'center'});
    };
  }
  if (get('mt-approve')) get('mt-approve').onchange = event => { get('mt-send').disabled = !event.target.checked; };
  if (get('mt-send')) get('mt-send').onclick = () => {
    get('mt-send').textContent = 'Sending…';
    act('send-invite', {confirm: get('mt-approve').checked, subject: get('mt-subject').value, body: get('mt-body').value}, get('mt-send'));
  };
  if (get('mt-book')) get('mt-book').onclick = () => {
    if (!get('mt-start').value) { get('meeting-error').textContent = 'Pick the date and time first.'; return; }
    get('mt-book').textContent = 'Booking…';
    act('book', {start_at: get('mt-start').value, duration_min: Number(get('mt-duration').value)}, get('mt-book'));
  };
  if (get('mt-transcript')) get('mt-transcript').onclick = async () => {
    get('mt-transcript').disabled = true;
    const result = await postJson(`/api/meetings/${m.id}/transcript`, {}, 'meeting-error');
    get('mt-transcript').disabled = false;
    if (result) {
      get('mt-notes').value = result.text;
      get('mt-transcript-status').textContent = `${result.source} pasted below. Check it, then summarise.`;
    }
  };
  if (get('mt-schedule')) get('mt-schedule').onsubmit = event => {
    event.preventDefault();
    act('schedule', {start_at: get('mt-start').value, duration_min: Number(get('mt-duration').value),
      teams_link: get('mt-teams').value.trim() || null}, submitButton(event));
  };
  if (get('mt-debrief')) get('mt-debrief').onsubmit = event => {
    event.preventDefault();
    const button = submitButton(event);
    button.textContent = 'Reading the notes…';
    act('debrief', {notes: get('mt-notes').value}, button);
  };
  if (get('mt-cancel')) get('mt-cancel').onclick = () => act('cancel', {reason: get('mt-cancel-reason').value}, get('mt-cancel'));
  for (const row of document.querySelectorAll('.actions-table tr')) {
    const save = async () => {
      await postJson(`/api/actions/${row.dataset.action}`, {status: row.querySelector('.ax-done').checked ? 'done' : 'open',
        owner: row.querySelector('.ax-owner').value, due: row.querySelector('.ax-due').value || null}, 'meeting-error');
      openMeeting(m.id); loadMeetings();
    };
    row.querySelector('.ax-save').onclick = save;
    row.querySelector('.ax-done').onchange = save;
  }
}

get('close-meeting').onclick = () => get('meeting-dialog').close();

// ── Today panel and meetings list ────────────────────────────────────────────

async function loadMeetings() {
  try {
    const [reminders, meetings] = await Promise.all([fetch('/api/reminders').then(r => r.json()),
      fetch('/api/meetings').then(r => r.json())]);
    renderToday(reminders);
    renderMeetingsList(meetings);
    const urgent = reminders.items.filter(i => i.severity === 'high').length;
    get('reviewer-nav').dataset.badge = urgent || '';
  } catch { /* the panels simply stay empty */ }
}

function renderToday(reminders) {
  get('today-date').textContent = new Date(reminders.today).toLocaleDateString([], {weekday: 'long', day: 'numeric', month: 'long'});
  get('today').innerHTML = reminders.items.length ? `<ul class="reminders">${reminders.items.map(item => `<li class="reminder ${item.severity}">
      <span class="reminder-icon" aria-hidden="true">${REMINDER_ICONS[item.kind] ?? '•'}</span>
      <span>${escapeText(item.text)}</span>
      ${item.meeting_id ? `<button type="button" data-open-meeting="${item.meeting_id}">Open</button>`
        : item.report_id ? `<button type="button" data-open-report>Open</button>`
        : `<button type="button" data-record="${escapeText(item.submission_id)}">Open</button>`}
      ${item.action_id ? `<button type="button" data-done-action="${item.action_id}">Done</button>` : ''}</li>`).join('')}</ul>`
    : '<p class="muted">Nothing needs attention today.</p>';
}

function renderMeetingsList(meetings) {
  const now = new Date();
  const groups = [
    ['Upcoming', m => m.status === 'scheduled' && new Date(m.start_at) >= now],
    ['Needs notes', m => m.status === 'scheduled' && new Date(m.start_at) < now],
    ['Waiting for reply', m => m.status === 'invite_sent'],
    ['Drafts', m => m.status === 'planned'],
    ['Held', m => m.status === 'held'],
  ];
  const html = groups.map(([label, test]) => {
    const items = meetings.filter(test);
    return items.length ? `<div class="meeting-group"><h5>${label} · ${items.length}</h5>${items.map(m => `
      <button type="button" class="meeting-row" data-open-meeting="${m.id}"><strong>${escapeText(m.supplier)}</strong>
        <span class="muted">${m.start_at ? escapeText(when(m.start_at)) : escapeText(STATUS_LABELS[m.status])} · ${escapeText(m.submission_id)}</span>
        ${m.actions.filter(a => a.status === 'open').length ? `<span class="chip">${m.actions.filter(a => a.status === 'open').length} open actions</span>` : ''}</button>`).join('')}</div>` : '';
  }).join('');
  get('meetings-list').innerHTML = html || '<p class="muted">No meetings yet. Plan one from a shortlisted supplier, under "Contacts and meetings".</p>';
}

document.addEventListener('click', async event => {
  const open = event.target.closest('[data-open-meeting]');
  if (open) return openMeeting(open.dataset.openMeeting);
  const done = event.target.closest('[data-done-action]');
  if (done) {
    await postJson(`/api/actions/${done.dataset.doneAction}`, {status: 'done'});
    loadMeetings();
  }
});
