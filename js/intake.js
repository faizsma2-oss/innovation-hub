// The intake chat. It talks to /api/intake and keeps the summary panel in sync.
// The server decides everything; this file only shows what it says and sends what the employee does.

const DRAFT_FIELDS = {
  title: 'Short title',
  description: 'What is making your work difficult',
  current_process: 'Today, and what should happen instead',
  frequency: 'How often',
  people_affected: 'Who, or which locations',
  impact: 'Time, cost, delay or risk',
  tried_already: 'Already tried',
  department: 'Your department (optional)',
};
const DEPARTMENT_NAMES = ['Not specified', 'Operations', 'Engineering', 'Facilities', 'Finance', 'Human resources',
  'IT', 'Procurement', 'Security', 'Other'];
const LONG_FIELDS = ['description', 'current_process', 'impact', 'tried_already'];

// Three labelled example cases for the demo. Illustrative, not claims about real operations.
const EXAMPLES = [
  ['Routine support request', 'I cannot access the reporting system.'],
  ['Recurring reporting problem', 'Every week, we manually combine reports from several systems.'],
  ['Linked to an existing opportunity', 'Several sites repeat the same inspection paperwork: handwritten inspection notes are copied into shared reports by hand.'],
];

const intake = {sessionId: null, closed: false, busy: false, edited: new Set()};

// 1. Build the summary panel once: one input per field.
function buildDraftPanel() {
  get('draft-fields').innerHTML = Object.entries(DRAFT_FIELDS).map(([key, label]) => {
    const id = `draft-${key}`;
    if (key === 'department') {
      return `<label for="${id}">${label}</label><select id="${id}" data-field="${key}">${
        DEPARTMENT_NAMES.map(name => `<option>${name}</option>`).join('')}</select>`;
    }
    return LONG_FIELDS.includes(key)
      ? `<label for="${id}">${label}</label><textarea id="${id}" data-field="${key}" rows="2"></textarea>`
      : `<label for="${id}">${label}</label><input id="${id}" data-field="${key}">`;
  }).join('');
}
buildDraftPanel();
// Remember which fields the employee changed, so they're sent with the next message.
get('draft-fields').addEventListener('input', event => intake.edited.add(event.target.dataset.field));

// 2. Show the server's draft, without overwriting what the employee is typing.
function showDraft(draft, unknown) {
  for (const key of Object.keys(DRAFT_FIELDS)) {
    const element = get(`draft-${key}`);
    if (!intake.edited.has(key) && document.activeElement !== element) {
      element.value = draft[key] ?? (key === 'department' ? 'Not specified' : '');
    }
    element.placeholder = unknown.includes(key) ? 'Unknown' : '';
    element.dir = 'auto';            // Arabic summaries read right to left
    element.classList.toggle('filled', Boolean(draft[key]) && key !== 'department');
  }
}

function addChatLine(role, text) {
  const line = document.createElement('li');
  line.className = `bubble ${role}`;
  line.dir = 'auto';                 // Arabic lines read right to left, English left to right
  line.textContent = text;
  get('chat-log').append(line);
  line.scrollIntoView({block: 'end', behavior: 'smooth'});
}

function showOptions(options) {
  get('chat-options').innerHTML = options.map(choice =>
    `<button type="button" data-action="${escapeText(choice.action)}">${escapeText(choice.label)}</button>`).join('');
}

function setBusy(busy) {
  intake.busy = busy;
  get('chat-send').disabled = busy || intake.closed;
  get('chat-input').disabled = intake.closed;
  for (const button of document.querySelectorAll('#chat-options button, #chat-persistent button, #chat-examples button')) {
    button.disabled = busy;
  }
}

// 3. One round trip: send what the employee did, then show the assistant's reply.
async function sendToIntake(payload) {
  if (intake.busy || intake.closed) return;
  const edits = Object.fromEntries([...intake.edited].map(key => [key, get(`draft-${key}`).value]));
  setBusy(true);
  try {
    const response = await fetch(`/api/intake/sessions/${intake.sessionId}/messages`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({...payload, edits}),
    });
    const reply = await response.json();
    if (!response.ok) throw new Error(typeof reply.detail === 'string' ? reply.detail : `status ${response.status}`);
    intake.edited.clear();
    showReply(reply);
  } catch (error) {
    addChatLine('system', `Something went wrong: ${error.message}`);
  } finally {
    setBusy(false);
  }
}

function showReply(reply) {
  addChatLine('assistant', reply.message);
  showDraft(reply.draft, reply.unknown);
  intake.closed = reply.stage === 'closed';
  get('chat-examples').hidden = reply.stage !== 'listening';
  // "Submit now" and "Request innovation review" stay available throughout.
  get('chat-persistent').hidden = !reply.can_submit;
  get('request-review').hidden = reply.review_requested;
  if (intake.closed) {
    showOptions([{label: 'Start a new conversation', action: 'restart'}]);
    showRating();
    loadSubmissions();
  } else {
    showOptions(reply.options);
  }
}

// 4. A one-click ease rating at the end: one of the success measures.
function showRating() {
  const rating = get('chat-rating');
  rating.hidden = false;
  rating.innerHTML = `<span>How easy was that?</span>${[1, 2, 3, 4, 5].map(score =>
    `<button type="button" data-score="${score}" aria-label="${score} out of 5">${score}</button>`).join('')}<span class="muted">1 hard · 5 easy</span>`;
}
get('chat-rating').addEventListener('click', async event => {
  const button = event.target.closest('[data-score]');
  if (!button) return;
  await fetch(`/api/intake/sessions/${intake.sessionId}/rating`, {
    method: 'POST', headers: {'Content-Type': 'application/json'}, body: JSON.stringify({score: Number(button.dataset.score)}),
  });
  get('chat-rating').innerHTML = '<span>Thanks for the feedback.</span>';
  loadSubmissions();
});

async function startIntake() {
  get('chat-log').innerHTML = '';
  get('chat-rating').hidden = true;
  intake.closed = false;
  intake.edited.clear();
  setBusy(true);
  try {
    const response = await fetch('/api/intake/sessions', {method: 'POST'});
    const reply = await response.json();
    intake.sessionId = reply.session_id;
    showReply(reply);
  } catch (error) {
    addChatLine('system', `Could not reach the assistant: ${error.message}`);
  } finally {
    setBusy(false);
  }
  get('chat-input').focus();
}

// 5. Wiring: examples, buttons, typing, opening and closing.
get('chat-examples').insertAdjacentHTML('beforeend', EXAMPLES.map(([label, text]) =>
  `<button type="button" data-example="${escapeText(text)}"><strong>${escapeText(label)}</strong><span>${escapeText(text)}</span></button>`).join(''));
get('chat-examples').addEventListener('click', event => {
  const button = event.target.closest('[data-example]');
  if (!button) return;
  addChatLine('employee', button.dataset.example);
  sendToIntake({text: button.dataset.example});
});

get('chat-options').addEventListener('click', event => {
  const button = event.target.closest('[data-action]');
  if (!button) return;
  if (button.dataset.action === 'restart') return startIntake();
  addChatLine('employee', button.textContent);
  sendToIntake({action: button.dataset.action});
});
get('submit-now').onclick = () => { addChatLine('employee', 'Submit now'); sendToIntake({action: 'submit'}); };
get('request-review').onclick = () => { addChatLine('employee', 'Request innovation review'); sendToIntake({action: 'request_review'}); };

get('chat-form').onsubmit = event => {
  event.preventDefault();
  const text = get('chat-input').value.trim();
  if (!text || intake.busy) return;
  get('chat-input').value = '';
  addChatLine('employee', text);
  sendToIntake({text});
};
// Enter sends; Shift+Enter makes a new line.
get('chat-input').addEventListener('keydown', event => {
  if (event.key === 'Enter' && !event.shiftKey) {
    event.preventDefault();
    get('chat-form').requestSubmit();
  }
});

get('new-problem').onclick = () => {
  get('intake-dialog').showModal();
  if (!intake.sessionId || intake.closed) startIntake();
};
get('close-intake').onclick = () => get('intake-dialog').close();
get('open-form').onclick = () => {
  get('intake-dialog').close();
  get('problem-dialog').showModal();
};
