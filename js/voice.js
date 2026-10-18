// Voice input: the browser's own speech recognition turns speech into text in the message box.
// The text is never sent by itself: the employee reads it, edits it, then presses Send.
// Note: in Chrome and Edge the audio is processed by Google's or Microsoft's speech service.

(function setUpVoice() {
  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return;                          // e.g. Firefox: the button stays hidden
  get('voice').hidden = false;
  let recognition = null;
  const button = get('voice-button');
  const stop = () => { recognition?.stop(); };
  button.onclick = () => {
    if (recognition) return stop();
    try {
      if (!localStorage.getItem('voice-notice')) {
        const ok = confirm('Speech is turned into text by your browser\'s speech service (in Chrome and Edge, that means '
          + 'Google or Microsoft). Don\'t say anything confidential. You\'ll see the text before anything is sent. Continue?');
        if (!ok) return;
        localStorage.setItem('voice-notice', 'seen');
      }
    } catch { /* storage blocked: ask again next time */ }
    recognition = new Recognition();
    recognition.lang = get('voice-lang').value;
    recognition.interimResults = true;
    recognition.continuous = false;
    const before = get('chat-input').value.trim();
    recognition.onresult = event => {
      const heard = [...event.results].map(result => result[0].transcript).join(' ');
      get('chat-input').value = (before ? before + ' ' : '') + heard;
    };
    recognition.onend = () => {
      recognition = null;
      button.textContent = '🎙 Speak';
      button.setAttribute('aria-pressed', 'false');
      get('chat-input').focus();                    // review, edit, then Send
    };
    recognition.onerror = event => {
      get('chat-input').placeholder = event.error === 'not-allowed'
        ? 'Microphone access was blocked. Allow it in the browser, or type instead.' : 'Didn\'t catch that. Try again, or type.';
    };
    recognition.start();
    button.textContent = '■ Stop';
    button.setAttribute('aria-pressed', 'true');
  };
})();
