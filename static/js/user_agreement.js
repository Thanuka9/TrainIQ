/**
 * User Agreement gate — scroll progress, TOC, scroll-to-end requirement.
 */
(function () {
  const scrollEl = document.getElementById('legalDocument');
  const progressBar = document.getElementById('legalProgressBar');
  const checkbox = document.getElementById('agreementCheckbox');
  const agreeBtn = document.getElementById('agreeBtn');
  const scrollHint = document.getElementById('legalScrollHint');
  const tocLinks = document.querySelectorAll('.legal-toc a[data-section]');
  const sidebar = document.getElementById('legalSidebar');
  const tocToggle = document.getElementById('legalTocToggle');

  let scrolledToEnd = false;

  function updateProgress() {
    const el = scrollEl || document.documentElement;
    const scrollTop = window.scrollY || el.scrollTop;
    const scrollHeight = (document.documentElement.scrollHeight - window.innerHeight) || 1;
    const pct = Math.min(100, (scrollTop / scrollHeight) * 100);
    if (progressBar) progressBar.style.width = pct + '%';

    const endMarker = document.getElementById('legalEndMarker');
    if (endMarker && !scrolledToEnd) {
      const rect = endMarker.getBoundingClientRect();
      if (rect.top < window.innerHeight * 0.92) {
        scrolledToEnd = true;
        if (scrollHint) {
          scrollHint.classList.add('is-done');
          scrollHint.innerHTML = '<i class="fas fa-circle-check"></i> You have reached the end of the Agreement';
        }
        if (checkbox) checkbox.disabled = false;
      }
    }
    updateActiveToc();
  }

  function updateActiveToc() {
    if (!tocLinks.length) return;
    let current = null;
    tocLinks.forEach((link) => {
      const id = link.getAttribute('data-section');
      const section = document.getElementById(id);
      if (section && section.getBoundingClientRect().top <= 120) {
        current = link;
      }
    });
    tocLinks.forEach((l) => l.classList.remove('is-active'));
    if (current) current.classList.add('is-active');
  }

  if (checkbox && agreeBtn) {
    checkbox.addEventListener('change', () => {
      agreeBtn.disabled = !checkbox.checked || checkbox.disabled;
    });
  }

  window.addEventListener('scroll', updateProgress, { passive: true });
  updateProgress();

  tocLinks.forEach((link) => {
    link.addEventListener('click', (e) => {
      e.preventDefault();
      const id = link.getAttribute('data-section');
      const target = document.getElementById(id);
      if (target) target.scrollIntoView({ behavior: 'smooth', block: 'start' });
      sidebar?.classList.remove('is-open');
    });
  });

  tocToggle?.addEventListener('click', () => {
    sidebar?.classList.toggle('is-open');
  });

  document.getElementById('disagreeBtn')?.addEventListener('click', () => {
    window.location.href = disagreeUrl;
  });

  agreeBtn?.addEventListener('click', async () => {
    if (!checkbox?.checked || checkbox.disabled) return;
    agreeBtn.disabled = true;
    const token = document.getElementById('csrfToken')?.value;
    try {
      const res = await fetch(acceptUrl, {
        method: 'POST',
        headers: { 'X-CSRFToken': token, 'Content-Type': 'application/json' },
        credentials: 'include',
      });
      if (res.ok) {
        window.location.href = nextUrl;
      } else {
        agreeBtn.disabled = false;
        alert('Could not record your acceptance. Please try again or contact support.');
      }
    } catch (_) {
      agreeBtn.disabled = false;
      alert('Network error. Please try again.');
    }
  });
})();
