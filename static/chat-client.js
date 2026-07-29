/*
 * 小窝聊天公共客户端
 * 保持 /api/read/chat 与 chat.json 契约不变，供小窝、共读、深读共用。
 */
(function () {
  function escapeHtml(value) {
    return String(value == null ? '' : value)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;')
      .replace(/'/g, '&#039;');
  }

  function clientId() {
    return window.crypto && crypto.randomUUID
      ? crypto.randomUUID()
      : 'web-' + Date.now() + '-' + Math.random().toString(16).slice(2);
  }

  async function jsonRequest(url, options) {
    const response = await fetch(url, Object.assign({ cache: 'no-store' }, options));
    let data = {};
    try { data = await response.json(); } catch (_) {}
    if (!response.ok) {
      const error = new Error(data.error || 'request failed');
      error.status = response.status;
      error.data = data;
      throw error;
    }
    return data;
  }

  function create(options) {
    const opts = Object.assign({
      api: '/api/read',
      interval: 2500,
      filter: function () { return true; },
      onMessages: function () {},
      onError: function () {},
      onConnected: function () {},
    }, options || {});
    let since = 0;
    let timer = null;
    let busy = false;
    const seen = new Set();

    async function poll() {
      if (busy) return;
      busy = true;
      try {
        const messages = await jsonRequest(opts.api + '/chat?since=' + since);
        const accepted = [];
        for (const message of messages) {
          since = Math.max(since, Number(message.ts) || 0);
          if (!opts.filter(message) || seen.has(message.id)) continue;
          seen.add(message.id);
          accepted.push(message);
        }
        if (accepted.length) opts.onMessages(accepted);
        opts.onConnected();
      } catch (error) {
        opts.onError(error);
      } finally {
        busy = false;
      }
    }

    async function send(payload, fixedClientId) {
      const body = Object.assign({}, payload, {
        client_id: fixedClientId || payload.client_id || clientId(),
      });
      return jsonRequest(opts.api + '/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
    }

    function start() {
      stop();
      poll();
      timer = setInterval(poll, opts.interval);
    }

    function stop() {
      if (timer) clearInterval(timer);
      timer = null;
    }

    return { poll, send, start, stop, seen, clientId };
  }

  window.HomeChat = Object.freeze({ create, escapeHtml, clientId, jsonRequest });
})();
