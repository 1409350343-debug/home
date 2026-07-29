/*
 * 全站无依赖工具函数。
 * 保持文件轻量，页面可在自己的脚本中直接复用。
 */
(function () {
  const pageName = (location.pathname.split('/').pop() || 'index.html')
    .replace(/\.html$/i, '')
    .replace(/[^a-z0-9-]/gi, '-');
  const visuallyStandalone = new Set([
    'index',
    'memory',
    'memory-cat',
    'memory-archive',
    'brain',
  ]);

  if (!visuallyStandalone.has(pageName)) {
    document.documentElement.classList.add('app-shell', `app-${pageName}`);
    document.addEventListener('DOMContentLoaded', function () {
      document.body.classList.add('app-page');

      if (!document.querySelector('link[data-home-app-ui]')) {
        const stylesheet = document.createElement('link');
        stylesheet.rel = 'stylesheet';
        stylesheet.href = '/static/app-ui.css?v=1';
        stylesheet.dataset.homeAppUi = '';
        document.head.appendChild(stylesheet);
      }
    }, { once: true });
  }

  function escapeHtml(value) {
    const element = document.createElement('div');
    element.textContent = value == null ? '' : String(value);
    return element.innerHTML;
  }

  window.HomeCommon = Object.freeze({
    escapeHtml,
  });
})();
