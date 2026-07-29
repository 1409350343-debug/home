(function () {
  const items = [
    ['memory', '/memory.html', 'brain', 'Memory'],
    ['calendar', '/calendar.html', 'calendar-days', 'calendar'],
    ['home', '/', 'home', 'Home'],
    ['study', '/shelf.html', 'book-open', 'Study'],
    ['settings', '/settings.html', 'settings-2', 'Settings'],
  ];
  window.renderCoreNav = function (active) {
    const old = document.querySelector('.core-nav');
    if (old) old.remove();
    const nav = document.createElement('nav');
    nav.className = 'core-nav';
    nav.setAttribute('aria-label', '主导航');
    const activeIndex = Math.max(0, items.findIndex(item => item[0] === active));
    nav.style.setProperty('--active-index', activeIndex);
    nav.innerHTML = '<i class="core-nav-indicator" aria-hidden="true"></i>' + items.map(([key, href, icon, label]) =>
      `<a data-key="${key}" class="${key === active ? 'active ' : ''}${key === 'home' ? 'home' : ''}" href="${href}" aria-label="${label}">
        <i data-lucide="${icon}"></i><span>${label}</span>
      </a>`).join('');
    nav.querySelectorAll('a').forEach((link, index) => {
      link.addEventListener('click', event => {
        if (event.metaKey || event.ctrlKey || event.shiftKey) return;
        event.preventDefault();
        nav.style.setProperty('--active-index', index);
        nav.querySelectorAll('a').forEach(item => item.classList.remove('active', 'pressed'));
        link.classList.add('active', 'pressed');
        setTimeout(() => { location.href = link.href; }, 210);
      });
    });
    document.body.classList.add('has-core-nav');
    document.body.appendChild(nav);
    if (window.lucide) window.lucide.createIcons();
  };
})();
