// gaia.js — "Ask Gaia" chat panel.
//
// Stateless on the backend by design (see backend/services/gaia_agent.py)
// — conversation history lives here, in memory, and gets resent with
// every turn. Refreshing the page clears it; that's an intentional v1
// scope choice, not an oversight (no persistent chat-session store
// exists yet).

class GaiaChat {
    constructor() {
        this.history = []; // [{role, content}, ...] — mirrors what's rendered
        this.isSending = false;

        // Ask Gaia used to be a floating button+bubble with its own
        // open/close toggle, independent of the tab system — it's now
        // the "gaia" tab's content instead (see ui.js's switchTab()),
        // so show/hide and focus-on-entry are handled there. Only the
        // chat internals (panel content, form, messages) are wired up
        // here now.
        this.panel = document.getElementById('gaia-panel');
        this.messagesEl = document.getElementById('gaia-messages');
        this.form = document.getElementById('gaia-input-form');
        this.input = document.getElementById('gaia-input');

        if (!this.panel) return; // markup not present — nothing to wire up

        this.form?.addEventListener('submit', (e) => {
            e.preventDefault();
            this.sendMessage();
        });

        document.getElementById('gaia-suggestions')?.addEventListener('click', (e) => {
            const chip = e.target.closest('.gaia-suggestion-chip');
            if (!chip) return;
            this.input.value = chip.textContent;
            this.sendMessage();
        });
    }

    async sendMessage() {
        const text = this.input.value.trim();
        if (!text || this.isSending) return;

        this.isSending = true;
        this.input.value = '';
        document.getElementById('gaia-suggestions')?.remove(); // starter prompts only make sense before the first real message
        this.appendMessage('user', text);
        const typingEl = this.appendTypingIndicator();

        // Current map selection, if any — lets Gaia answer "here"/"this
        // location" questions without the user having to name a place.
        const context = (typeof AppState !== 'undefined' && AppState.selectedLocation)
            ? { lat: AppState.selectedLocation.lat, lon: AppState.selectedLocation.lon }
            : null;

        const result = await api.askGaia(text, this.history, context);
        typingEl.remove();

        if (!result) {
            this.appendMessage('assistant', "I couldn't reach the backend just now — check that it's running and try again.", true);
            this.isSending = false;
            return;
        }

        this.appendMessage('assistant', result.reply, result.status !== 'ok');

        // Keep history in sync with what actually got sent/received —
        // NOT the error-path messages above, so a transient network hiccup
        // doesn't pollute the conversation the backend sees next turn.
        if (result.status === 'ok' || result.status === 'not_configured') {
            this.history.push({ role: 'user', content: text });
            this.history.push({ role: 'assistant', content: result.reply });
        }

        // If Gaia resolved/used a location (e.g. geocoded a place name),
        // reflect that on the dashboard itself — this is the "Gaia can
        // act, not just talk" behavior from the product walkthrough.
        if (result.location && result.location.lat !== undefined && window.globeManager) {
            window.globeManager.loadLocationAnalytics(result.location.lat, result.location.lon);
        }

        this.isSending = false;
    }

    appendMessage(role, text, isError = false) {
        const el = document.createElement('div');
        el.className = `gaia-message gaia-message-${role}` + (isError ? ' gaia-message-error' : '');

        // Gaia's replies come back as markdown (**bold** headers, "- "
        // bullet lists, etc.) since that's what the underlying LLM
        // naturally produces — rendering it beats showing raw asterisks.
        // User messages are never parsed as markdown (plain textContent),
        // since there's no reason to interpret formatting in what the
        // person themselves typed.
        if (role === 'assistant') {
            el.innerHTML = this._renderMarkdown(text);
        } else {
            el.textContent = text;
        }

        this.messagesEl.appendChild(el);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        return el;
    }

    // Deliberately minimal, not a full markdown library — this only
    // needs to handle what a short chat reply actually produces (bold,
    // simple bullet lists, paragraph breaks). HTML-escapes FIRST, then
    // applies formatting, so nothing in the LLM's output (or, indirectly,
    // in anything a user typed that gets echoed back) can inject markup.
    _renderMarkdown(text) {
        const escape = (s) => s
            .replace(/&/g, '&amp;')
            .replace(/</g, '&lt;')
            .replace(/>/g, '&gt;');

        let html = escape(text);

        html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
        html = html.replace(/(^|\n)[-*] (.+)/g, '$1<span class="gaia-bullet">• $2</span>');
        html = html.replace(/\n/g, '<br>');

        return html;
    }

    appendTypingIndicator() {
        const el = document.createElement('div');
        el.className = 'gaia-message gaia-message-assistant gaia-typing';
        el.innerHTML = '<span></span><span></span><span></span>';
        this.messagesEl.appendChild(el);
        this.messagesEl.scrollTop = this.messagesEl.scrollHeight;
        return el;
    }
}

let gaiaChat;
document.addEventListener('DOMContentLoaded', () => {
    gaiaChat = new GaiaChat();
});
