/* ============================================================
   TrainIQ Unified JavaScript v1.0
   ============================================================ */

(function () {
  'use strict';

  /* ─── Theme Management ─────────────────────────────────── */
  const Theme = {
    key: 'tiq-theme',
    get() {
      return localStorage.getItem(this.key) ||
        (window.matchMedia('(prefers-color-scheme: dark)').matches ? 'dark' : 'light');
    },
    set(theme) {
      document.documentElement.setAttribute('data-theme', theme);
      localStorage.setItem(this.key, theme);
      document.querySelectorAll('.tiq-theme-icon').forEach(el => {
        el.className = `tiq-theme-icon fas fa-${theme === 'dark' ? 'sun' : 'moon'}`;
      });
      window.dispatchEvent(new CustomEvent('tiqThemeChanged', { detail: { theme } }));
    },
    toggle() { this.set(this.get() === 'dark' ? 'light' : 'dark'); },
    init() { this.set(this.get()); }
  };

  /* ─── Sidebar Management ───────────────────────────────── */
  const Sidebar = {
    key: 'tiq-sidebar-collapsed',
    sidebar: null,
    main: null,
    init() {
      this.sidebar = document.getElementById('tiqSidebar');
      this.main = document.getElementById('tiqMain');
      if (!this.sidebar) return;

      const isCollapsed = localStorage.getItem(this.key) === 'true';
      // Restore collapsed state
      if (isCollapsed) {
        this.sidebar.classList.add('collapsed');
        this.main?.classList.add('sidebar-collapsed');
      }
      this.updateChevron(isCollapsed);

      // Toggle button
      const toggle = document.getElementById('sidebarToggle');
      toggle?.addEventListener('click', () => this.toggle());

      // Mobile overlay
      const overlay = document.getElementById('sidebarOverlay');
      overlay?.addEventListener('click', () => this.closeMobile());

      // Mobile menu button
      const mobileBtn = document.getElementById('mobileSidebarBtn');
      mobileBtn?.addEventListener('click', () => this.openMobile());
    },
    toggle() {
      const collapsed = this.sidebar.classList.toggle('collapsed');
      this.main?.classList.toggle('sidebar-collapsed', collapsed);
      localStorage.setItem(this.key, collapsed);
      this.updateChevron(collapsed);
    },
    updateChevron(collapsed) {
      // Chevron rotation is handled dynamically via CSS transitions on .tiq-sidebar.collapsed
    },
    openMobile() {
      this.sidebar.classList.add('mobile-open');
      document.getElementById('sidebarOverlay')?.classList.add('show');
      document.body.style.overflow = 'hidden';
    },
    closeMobile() {
      this.sidebar.classList.remove('mobile-open');
      document.getElementById('sidebarOverlay')?.classList.remove('show');
      document.body.style.overflow = '';
    }
  };

  /* ─── Dropdown Management ──────────────────────────────── */
  const Dropdowns = {
    init() {
      document.querySelectorAll('[data-tiq-dropdown]').forEach(trigger => {
        const targetId = trigger.getAttribute('data-tiq-dropdown');
        const target = document.getElementById(targetId);
        if (!target) return;

        trigger.addEventListener('click', (e) => {
          e.stopPropagation();
          const isOpen = target.classList.contains('show');
          // Close all dropdowns
          document.querySelectorAll('.tiq-dropdown.show').forEach(d => d.classList.remove('show'));
          document.querySelectorAll('[data-tiq-dropdown]').forEach(t => t.classList.remove('open'));
          if (!isOpen) {
            target.classList.add('show');
            trigger.classList.add('open');
          }
        });
      });

      document.addEventListener('click', () => {
        document.querySelectorAll('.tiq-dropdown.show').forEach(d => d.classList.remove('show'));
        document.querySelectorAll('[data-tiq-dropdown]').forEach(t => t.classList.remove('open'));
      });
    }
  };

  /* ─── Toast Notifications ──────────────────────────────── */
  const Toast = {
    container: null,
    icons: { success: 'fa-check-circle', error: 'fa-times-circle', warning: 'fa-exclamation-triangle', info: 'fa-info-circle' },
    init() {
      this.container = document.querySelector('.tiq-toast-container');
      if (!this.container) {
        this.container = document.createElement('div');
        this.container.className = 'tiq-toast-container';
        document.body.appendChild(this.container);
      }
      // Auto-show flashed messages
      document.querySelectorAll('[data-toast]').forEach(el => {
        this.show(el.dataset.type || 'info', el.dataset.title || '', el.textContent.trim());
      });
    },
    show(type = 'info', title = '', message = '', duration = 4500) {
      const icon = this.icons[type] || this.icons.info;
      const toast = document.createElement('div');
      toast.className = `tiq-toast ${type}`;
      toast.innerHTML = `
        <i class="fas ${icon} tiq-toast-icon"></i>
        <div class="tiq-toast-content">
          ${title ? `<div class="tiq-toast-title">${title}</div>` : ''}
          ${message ? `<div class="tiq-toast-msg">${message}</div>` : ''}
        </div>
        <button class="tiq-toast-close" onclick="this.closest('.tiq-toast').remove()">
          <i class="fas fa-times"></i>
        </button>`;
      this.container.appendChild(toast);
      if (duration > 0) {
        setTimeout(() => {
          toast.classList.add('hiding');
          setTimeout(() => toast.remove(), 300);
        }, duration);
      }
      return toast;
    }
  };

  /* ─── Modal Management ─────────────────────────────────── */
  const Modal = {
    init() {
      document.querySelectorAll('[data-tiq-modal]').forEach(btn => {
        const target = document.getElementById(btn.dataset.tiqModal);
        btn.addEventListener('click', () => Modal.open(target));
      });
      document.querySelectorAll('[data-tiq-modal-close]').forEach(btn => {
        const backdrop = btn.closest('.tiq-modal-backdrop');
        btn.addEventListener('click', () => Modal.close(backdrop));
      });
      document.querySelectorAll('.tiq-modal-backdrop').forEach(backdrop => {
        backdrop.addEventListener('click', (e) => {
          if (e.target === backdrop) Modal.close(backdrop);
        });
      });
    },
    open(backdrop) {
      if (!backdrop) return;
      backdrop.classList.add('show');
      document.body.style.overflow = 'hidden';
    },
    close(backdrop) {
      if (!backdrop) return;
      backdrop.classList.remove('show');
      document.body.style.overflow = '';
    }
  };

  /* ─── Session Keepalive + AFK Warning ──────────────────── */
  const Session = {
    WARN_MS: 14 * 60 * 1000,
    PING_MS: 5 * 60 * 1000,
    idleMs: 0,
    warned: false,
    warnTimer: null,
    pingTimer: null,

    init() {
      const csrfToken = document.querySelector('meta[name="csrf-token"]')?.content;
      if (!csrfToken) return;

      const resetIdle = () => {
        this.idleMs = 0;
        if (this.warned) this.hideAfkModal();
      };
      ['mousemove', 'keydown', 'click', 'scroll', 'touchstart'].forEach(ev =>
        document.addEventListener(ev, resetIdle, { passive: true })
      );

      setInterval(() => {
        this.idleMs += 1000;
        if (this.idleMs >= this.WARN_MS && !this.warned) this.showAfkModal();
      }, 1000);

      this.pingTimer = setInterval(() => {
        fetch('/ping', {
          method: 'POST',
          headers: {
            'Content-Type': 'application/json',
            'X-CSRFToken': csrfToken,
            'X-Requested-With': 'XMLHttpRequest',
          },
        }).catch(() => {});
      }, this.PING_MS);
    },

    showAfkModal() {
      this.warned = true;
      let el = document.getElementById('tiq-afk-modal');
      if (!el) {
        el = document.createElement('div');
        el.id = 'tiq-afk-modal';
        el.innerHTML = `<div class="tiq-modal-backdrop show" style="z-index:99999">
          <div class="tiq-modal" style="max-width:420px;text-align:center">
            <div class="tiq-modal-body">
              <h3 style="margin-bottom:0.75rem">Still there?</h3>
              <p style="color:var(--tiq-text-2);font-size:0.9rem">Your session will expire soon due to inactivity. Move your mouse or press a key to stay signed in.</p>
              <button class="tiq-btn tiq-btn-primary tiq-btn-sm" id="tiq-afk-dismiss">I'm here</button>
            </div>
          </div></div>`;
        document.body.appendChild(el);
        el.querySelector('#tiq-afk-dismiss').onclick = () => this.hideAfkModal();
      }
      el.style.display = 'block';
    },

    hideAfkModal() {
      this.warned = false;
      this.idleMs = 0;
      const el = document.getElementById('tiq-afk-modal');
      if (el) el.style.display = 'none';
    },
  };

  /* ─── Progress Bar Animations ──────────────────────────── */
  const Animations = {
    init() {
      // Animate progress bars on scroll
      const observer = new IntersectionObserver((entries) => {
        entries.forEach(entry => {
          if (entry.isIntersecting) {
            const bar = entry.target;
            const width = bar.dataset.width || bar.style.width;
            bar.style.width = '0%';
            requestAnimationFrame(() => { bar.style.width = width; });
            observer.unobserve(bar);
          }
        });
      }, { threshold: 0.1 });

      document.querySelectorAll('.tiq-progress-bar[data-width]').forEach(bar => observer.observe(bar));

      // Scroll-triggered reveal animations
      if (!window.matchMedia('(prefers-reduced-motion: reduce)').matches) {
        const revealObs = new IntersectionObserver((entries) => {
          entries.forEach(entry => {
            if (entry.isIntersecting) {
              entry.target.classList.add('tiq-revealed');
              revealObs.unobserve(entry.target);
            }
          });
        }, { threshold: 0.08, rootMargin: '0px 0px -40px 0px' });
        document.querySelectorAll('.tiq-reveal').forEach(el => revealObs.observe(el));
      } else {
        document.querySelectorAll('.tiq-reveal').forEach(el => el.classList.add('tiq-revealed'));
      }

      // Animate stat numbers
      document.querySelectorAll('[data-count]').forEach(el => {
        const target = parseInt(el.dataset.count);
        const duration = 1500;
        const step = target / (duration / 16);
        let current = 0;
        const timer = setInterval(() => {
          current = Math.min(current + step, target);
          el.textContent = Math.floor(current).toLocaleString();
          if (current >= target) clearInterval(timer);
        }, 16);
      });
    }
  };

  /* ─── Scroll To Top ────────────────────────────────────── */
  const ScrollTop = {
    init() {
      const btn = document.querySelector('.tiq-scroll-top');
      if (!btn) return;
      window.addEventListener('scroll', () => {
        btn.classList.toggle('visible', window.scrollY > 300);
      });
      btn.addEventListener('click', () => window.scrollTo({ top: 0, behavior: 'smooth' }));
    }
  };

  /* ─── Password Visibility Toggle ───────────────────────── */
  const PasswordToggle = {
    init() {
      document.querySelectorAll('[data-password-toggle]').forEach(btn => {
        const targetId = btn.dataset.passwordToggle;
        const input = document.getElementById(targetId);
        const icon = btn.querySelector('i');
        if (!input || !icon) return;
        btn.addEventListener('click', () => {
          const isPassword = input.type === 'password';
          input.type = isPassword ? 'text' : 'password';
          icon.className = `fas fa-${isPassword ? 'eye-slash' : 'eye'}`;
        });
      });
    }
  };

  /* ─── Admin Table Search ───────────────────────────────── */
  const TableSearch = {
    init() {
      document.querySelectorAll('[data-table-search]').forEach(input => {
        const table = document.getElementById(input.dataset.tableSearch);
        if (!table) return;
        const tbody = table.querySelector('tbody');
        if (!tbody) return;
        input.addEventListener('input', () => {
          const q = input.value.trim().toLowerCase();
          tbody.querySelectorAll('tr').forEach(row => {
            const text = row.textContent.toLowerCase();
            row.style.display = !q || text.includes(q) ? '' : 'none';
          });
        });
      });
    }
  };

  /* ─── Flash Messages → Toasts ──────────────────────────── */
  const FlashToasts = {
    init() {
      document.querySelectorAll('.tiq-flash-data').forEach(el => {
        const type = el.dataset.category === 'error' ? 'error'
          : el.dataset.category === 'success' ? 'success'
          : el.dataset.category === 'warning' ? 'warning' : 'info';
        Toast.show(type, '', el.textContent.trim());
        el.remove();
      });
    }
  };

  /* ─── Confirm Dialogs ──────────────────────────────────── */
  window.tiqConfirm = function(message, onConfirm) {
    const backdrop = document.createElement('div');
    backdrop.className = 'tiq-modal-backdrop show';
    backdrop.innerHTML = `
      <div class="tiq-modal" style="max-width:400px">
        <div class="tiq-modal-header">
          <h3 style="font-size:1rem">Confirm Action</h3>
        </div>
        <div class="tiq-modal-body">
          <p style="color:var(--tiq-text-2);font-size:0.9rem">${message}</p>
        </div>
        <div class="tiq-modal-footer">
          <button class="tiq-btn tiq-btn-secondary tiq-btn-sm" id="_tiqCancel">Cancel</button>
          <button class="tiq-btn tiq-btn-danger tiq-btn-sm" id="_tiqConfirm">Confirm</button>
        </div>
      </div>`;
    document.body.appendChild(backdrop);
    backdrop.querySelector('#_tiqCancel').onclick = () => backdrop.remove();
    backdrop.querySelector('#_tiqConfirm').onclick = () => { backdrop.remove(); onConfirm(); };
    backdrop.addEventListener('click', e => { if (e.target === backdrop) backdrop.remove(); });
  };

  /* ─── Global Expose ────────────────────────────────────── */
  window.TrainIQ = { Theme, Sidebar, Toast, Modal, Session };

  /* ─── Init ─────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', () => {
    Theme.init();
    Sidebar.init();
    Dropdowns.init();
    Toast.init();
    Modal.init();
    Session.init();
    Animations.init();
    TableSearch.init();
    ScrollTop.init();
    PasswordToggle.init();
    FlashToasts.init();
  });

  /* ─── Chart.js Theme Sync ──────────────────────────────── */
  window.addEventListener('tiqThemeChanged', (e) => {
    if (window.Chart && window.Chart.instances) {
      const isDark = e.detail.theme === 'dark';
      const textColor = isDark ? '#94A3B8' : '#475569';
      const gridColor = isDark ? '#1F2937' : '#E2E8F0';

      Chart.defaults.color = textColor;
      if (Chart.defaults.plugins && Chart.defaults.plugins.legend && Chart.defaults.plugins.legend.labels) {
        Chart.defaults.plugins.legend.labels.color = textColor;
      }

      Object.values(Chart.instances).forEach(chart => {
        // Handle datasets with original CSS variables
        if (chart.data && chart.data.datasets) {
          chart.data.datasets.forEach(dataset => {
            if (!dataset._originalBgColor) {
              dataset._originalBgColor = dataset.backgroundColor;
            }
            if (!dataset._originalBorderColor) {
              dataset._originalBorderColor = dataset.borderColor;
            }

            const resolveColor = (c) => {
              if (typeof c === 'string' && c.startsWith('var(')) {
                const varName = c.match(/var\(([^)]+)\)/)[1];
                return getComputedStyle(document.documentElement).getPropertyValue(varName).trim();
              }
              return c;
            };

            if (Array.isArray(dataset._originalBgColor)) {
              dataset.backgroundColor = dataset._originalBgColor.map(resolveColor);
            } else {
              dataset.backgroundColor = resolveColor(dataset._originalBgColor);
            }

            if (Array.isArray(dataset._originalBorderColor)) {
              dataset.borderColor = dataset._originalBorderColor.map(resolveColor);
            } else {
              dataset.borderColor = resolveColor(dataset._originalBorderColor);
            }
          });
        }

        // Handle scales
        if (chart.options.scales) {
          Object.keys(chart.options.scales).forEach(scaleKey => {
            const scale = chart.options.scales[scaleKey];
            if (scale) {
              if (!scale.ticks) scale.ticks = {};
              scale.ticks.color = textColor;
              
              if (!scale.grid) scale.grid = {};
              if (scale.grid.display !== false) {
                scale.grid.color = gridColor;
              }
              
              if (scale.angleLines) scale.angleLines.color = gridColor;
              if (scale.pointLabels) scale.pointLabels.color = textColor;
              if (scale.title) scale.title.color = textColor;
            }
          });
        }

        // Handle legend labels
        if (!chart.options.plugins) chart.options.plugins = {};
        if (!chart.options.plugins.legend) chart.options.plugins.legend = {};
        if (!chart.options.plugins.legend.labels) chart.options.plugins.legend.labels = {};
        chart.options.plugins.legend.labels.color = textColor;

        chart.update();
      });
    }
  });

})();
