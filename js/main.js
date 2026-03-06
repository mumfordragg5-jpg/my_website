document.addEventListener('DOMContentLoaded', () => {
  initThemeToggle();
  initReadingProgress();
  initScrollAnimations();
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
  const cards = document.querySelectorAll('.fade-in');
  if (!cards.length) return;

  if (!('IntersectionObserver' in window)) {
    cards.forEach(c => c.style.opacity = '1');
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

  cards.forEach(card => {
    card.style.animationPlayState = 'paused';
    observer.observe(card);
  });
}
