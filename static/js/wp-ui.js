/**
 * Плотность интерфейса (main): comfortable | compact — localStorage wp-density
 */
(function () {
  var KEY = 'wp-density';
  var root = document.documentElement;

  function getDensity() {
    var a = root.getAttribute('data-wp-density');
    return a === 'compact' || a === 'comfortable' ? a : 'comfortable';
  }

  function setDensity(mode) {
    if (mode !== 'compact' && mode !== 'comfortable') return;
    root.setAttribute('data-wp-density', mode);
    try {
      localStorage.setItem(KEY, mode);
    } catch (e) {}
    syncButtons();
  }

  function syncButtons() {
    var d = getDensity();
    document.querySelectorAll('[data-wp-density-set]').forEach(function (btn) {
      var m = btn.getAttribute('data-wp-density-set');
      var active = m === d;
      btn.classList.toggle('active', active);
      btn.setAttribute('aria-pressed', active ? 'true' : 'false');
    });
  }

  document.addEventListener('DOMContentLoaded', function () {
    syncButtons();
    document.querySelectorAll('[data-wp-density-set]').forEach(function (btn) {
      btn.addEventListener('click', function () {
        setDensity(btn.getAttribute('data-wp-density-set'));
      });
    });
  });
})();

/**
 * Тема интерфейса: light | dark — localStorage wp-theme, data-wp-theme и data-bs-theme на <html>
 */
(function () {
  var KEY = 'wp-theme';
  var root = document.documentElement;

  function getTheme() {
    var a = root.getAttribute('data-wp-theme');
    return a === 'dark' || a === 'light' ? a : 'light';
  }

  function setTheme(mode) {
    if (mode !== 'dark' && mode !== 'light') return;
    root.setAttribute('data-wp-theme', mode);
    root.setAttribute('data-bs-theme', mode);
    try {
      localStorage.setItem(KEY, mode);
    } catch (e) {}
    syncThemeToggle();
  }

  function syncThemeToggle() {
    var t = getTheme();
    var dark = t === 'dark';
    var btn = document.getElementById('wp-theme-toggle');
    if (!btn) return;
    btn.classList.toggle('is-dark', dark);
    btn.classList.toggle('is-light', !dark);
    btn.setAttribute('data-active-theme', t);
    btn.setAttribute('title', dark ? 'Светлая тема' : 'Тёмная тема');
    btn.setAttribute('aria-label', dark ? 'Включить светлую тему' : 'Включить тёмную тему');
    if (!btn.classList.contains('eavc-topbar__theme-pill')) {
      var icon = btn.querySelector('i');
      if (icon) {
        icon.className = dark ? 'bi bi-brightness-high fs-5' : 'bi bi-moon-stars fs-5';
      }
    }
  }

  document.addEventListener('DOMContentLoaded', function () {
    syncThemeToggle();
    var btn = document.getElementById('wp-theme-toggle');
    if (btn) {
      btn.addEventListener('click', function () {
        setTheme(getTheme() === 'dark' ? 'light' : 'dark');
      });
    }
  });
})();
