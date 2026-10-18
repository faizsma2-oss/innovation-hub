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
