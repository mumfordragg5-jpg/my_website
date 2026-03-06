document.addEventListener('DOMContentLoaded', () => {
  initThemeToggle();
  initReadingProgress();
  initScrollAnimations();
  initFilters();
  initSearch();
  initMobileMenu();
});

function initThemeToggle() {
  const btn = document.getElementById('themeToggle');
  if (!btn) return;

  const saved = localStorage.getItem('theme');
  if (saved === 'dark' || (!saved && window.matchMedia('(prefers-color-scheme: dark)').matches)) {
    document.documentElement.setAttribute('data-theme', 'dark');
    btn.textContent = '☀️';
  }

  btn.addEventListener('click', () => {
    const isDark = document.documentElement.getAttribute('data-theme') === 'dark';
    if (isDark) {
      document.documentElement.removeAttribute('data-theme');
      btn.textContent = '🌙';
      localStorage.setItem('theme', 'light');
    } else {
      document.documentElement.setAttribute('data-theme', 'dark');
      btn.textContent = '☀️';
      localStorage.setItem('theme', 'dark');
    }
  });
}

function initReadingProgress() {
  const bar = document.getElementById('readingProgress');
  if (!bar) return;

  window.addEventListener('scroll', () => {
    const scrollTop = window.scrollY;
    const docHeight = document.documentElement.scrollHeight - window.innerHeight;
    const progress = docHeight > 0 ? (scrollTop / docHeight) * 100 : 0;
    bar.style.width = Math.min(progress, 100) + '%';
  }, { passive: true });
}

function initScrollAnimations() {
  const items = document.querySelectorAll('.fade-in');
  if (!items.length) return;

  if (!('IntersectionObserver' in window)) {
    items.forEach(el => el.style.opacity = '1');
    return;
  }

  const observer = new IntersectionObserver((entries) => {
    entries.forEach(entry => {
      if (entry.isIntersecting) {
        entry.target.style.animationPlayState = 'running';
        observer.unobserve(entry.target);
      }
    });
  }, { threshold: 0.1 });

  items.forEach(el => {
    el.style.animationPlayState = 'paused';
    observer.observe(el);
  });
}

function initFilters() {
  const buttons = document.querySelectorAll('.filter-btn[data-tag]');
  if (!buttons.length) return;

  buttons.forEach(btn => {
    btn.addEventListener('click', () => {
      buttons.forEach(b => b.classList.remove('active'));
      btn.classList.add('active');

      const tag = btn.dataset.tag;
      filterArticles(tag, getSearchQuery());
    });
  });
}

function initSearch() {
  const input = document.getElementById('searchInput');
  if (!input) return;

  let debounceTimer;
  input.addEventListener('input', () => {
    clearTimeout(debounceTimer);
    debounceTimer = setTimeout(() => {
      filterArticles(getActiveTag(), input.value.trim().toLowerCase());
    }, 200);
  });
}

function getActiveTag() {
  const active = document.querySelector('.filter-btn.active');
  return active ? active.dataset.tag : 'all';
}

function getSearchQuery() {
  const input = document.getElementById('searchInput');
  return input ? input.value.trim().toLowerCase() : '';
}

function filterArticles(tag, query) {
  const cards = document.querySelectorAll('.article-card');
  const noResults = document.getElementById('noResults');
  let visibleCount = 0;

  cards.forEach(card => {
    const tags = card.dataset.tags || '';
    const title = (card.dataset.title || '').toLowerCase();
    const search = (card.dataset.search || '').toLowerCase();

    const tagMatch = tag === 'all' || tags.includes(tag);
    const queryMatch = !query || title.includes(query) || search.includes(query);

    if (tagMatch && queryMatch) {
      card.classList.remove('hidden');
      visibleCount++;
    } else {
      card.classList.add('hidden');
    }
  });

  if (noResults) {
    noResults.style.display = visibleCount === 0 ? 'block' : 'none';
  }
}

function resetFilters() {
  const buttons = document.querySelectorAll('.filter-btn[data-tag]');
  buttons.forEach(b => b.classList.remove('active'));
  const allBtn = document.querySelector('.filter-btn[data-tag="all"]');
  if (allBtn) allBtn.classList.add('active');

  const input = document.getElementById('searchInput');
  if (input) input.value = '';

  filterArticles('all', '');
}

function initMobileMenu() {
  const toggle = document.getElementById('menuToggle');
  const nav = document.getElementById('navLinks');
  if (!toggle || !nav) return;

  toggle.addEventListener('click', () => {
    toggle.classList.toggle('active');
    nav.classList.toggle('show');
  });

  nav.querySelectorAll('a').forEach(link => {
    link.addEventListener('click', () => {
      toggle.classList.remove('active');
      nav.classList.remove('show');
    });
  });
}
