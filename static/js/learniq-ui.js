/**
 * LearnIQ UI helpers — markdown formatting, panel state, AI request retries.
 */
window.LearnIQUI = (function () {
  'use strict';

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  /** Lightweight markdown → safe HTML for chat bubbles */
  function formatMarkdown(text) {
    if (!text) return '';
    let html = escapeHtml(text);
    html = html.replace(/^### (.+)$/gm, '<h4 class="liq-h">$1</h4>');
    html = html.replace(/^## (.+)$/gm, '<h3 class="liq-h">$1</h3>');
    html = html.replace(/\*\*(.+?)\*\*/g, '<strong>$1</strong>');
    html = html.replace(/^\* (.+)$/gm, '<li>$1</li>');
    html = html.replace(/(<li>.*<\/li>\n?)+/g, m => `<ul class="liq-ul">${m}</ul>`);
    html = html.replace(/\n/g, '<br>');
    return html;
  }

  function setBubbleContent(el, text, asMarkdown) {
    if (!el) return;
    if (asMarkdown) {
      el.classList.add('learniq-msg-formatted');
      el.innerHTML = formatMarkdown(text);
    } else {
      el.classList.remove('learniq-msg-formatted');
      el.textContent = text;
    }
  }

  async function aiCall(fn, payloadBuilder, opts) {
    opts = opts || {};
    try {
      return await fn(payloadBuilder({}));
    } catch (e) {
      const msg = (e && e.message) || '';
      if (opts.allowVisionRetry !== false && (
        msg.includes('No extractable text') ||
        msg.includes('vision') ||
        msg.includes('503')
      )) {
        return await fn(payloadBuilder({ use_vision: true }));
      }
      throw e;
    }
  }

  return { formatMarkdown, setBubbleContent, aiCall, escapeHtml };
})();
