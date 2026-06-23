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
    _positionMenu(trigger, target) {
      target.classList.remove('drop-up', 'drop-fixed');
      target.style.top = '';
      target.style.left = '';
      target.style.right = '';
      target.style.bottom = '';

      const tr = trigger.closest('td, .tiq-dept-dropdown-wrap, .admin-actions-wrap');
      if (tr && tr.closest('.tiq-table-wrapper')) {
        const rect = trigger.getBoundingClientRect();
        target.classList.add('drop-fixed');
        const menuW = target.offsetWidth || 220;
        let left = rect.right - menuW;
        left = Math.max(8, Math.min(left, window.innerWidth - menuW - 8));
        target.style.left = `${left}px`;
        const below = rect.bottom + 8;
        const menuH = target.offsetHeight || 200;
        if (below + menuH > window.innerHeight - 8) {
          target.style.top = `${Math.max(8, rect.top - menuH - 8)}px`;
        } else {
          target.style.top = `${below}px`;
        }
        return;
      }

      const rect = target.getBoundingClientRect();
      if (rect.bottom > window.innerHeight - 8) {
        target.classList.add('drop-up');
      }
    },

    init() {
      document.querySelectorAll('[data-tiq-dropdown]').forEach(trigger => {
        const targetId = trigger.getAttribute('data-tiq-dropdown');
        const target = document.getElementById(targetId);
        if (!target) return;

        trigger.addEventListener('click', (e) => {
          e.stopPropagation();
          const isOpen = target.classList.contains('show');
          document.querySelectorAll('.tiq-dropdown.show').forEach(d => {
            d.classList.remove('show', 'drop-up', 'drop-fixed');
            d.style.top = d.style.left = d.style.right = d.style.bottom = '';
          });
          document.querySelectorAll('[data-tiq-dropdown]').forEach(t => t.classList.remove('open'));
          if (!isOpen) {
            target.classList.add('show');
            trigger.classList.add('open');
            requestAnimationFrame(() => this._positionMenu(trigger, target));
          }
        });
      });

      document.addEventListener('click', () => {
        document.querySelectorAll('.tiq-dropdown.show').forEach(d => {
          d.classList.remove('show', 'drop-up', 'drop-fixed');
          d.style.top = d.style.left = d.style.right = d.style.bottom = '';
        });
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

  /* ─── In-app Notifications Bell ─────────────────────────── */
  const Notifications = {
    listEl: null,
    badgeEl: null,
    pollMs: 90000,
    _timer: null,

    csrf() {
      return document.querySelector('meta[name="csrf-token"]')?.content || '';
    },

    init() {
      const bell = document.getElementById('tiqNotifBell');
      this.listEl = document.getElementById('tiqNotifList');
      this.badgeEl = document.getElementById('tiqNotifBadge');
      if (!bell || !this.listEl) return;

      document.getElementById('tiqNotifMarkAll')?.addEventListener('click', (e) => {
        e.preventDefault();
        e.stopPropagation();
        this.markAllRead();
      });

      bell.addEventListener('click', () => {
        setTimeout(() => this.load(), 50);
      });

      this.load();
      this._timer = setInterval(() => this.load(true), this.pollMs);
    },

    async load(quiet) {
      try {
        const res = await fetch('/notifications/api', { credentials: 'same-origin' });
        if (!res.ok) return;
        const data = await res.json();
        this.render(data);
      } catch (_) {
        if (!quiet && this.listEl) {
          this.listEl.innerHTML = '<div class="tiq-notif-empty">Could not load notifications</div>';
        }
      }
    },

    render(data) {
      const count = data.unread_count || 0;
      const markAllBtn = document.getElementById('tiqNotifMarkAll');
      if (markAllBtn) {
        markAllBtn.disabled = count === 0;
        markAllBtn.style.opacity = count === 0 ? '0.45' : '1';
        markAllBtn.style.cursor = count === 0 ? 'not-allowed' : 'pointer';
      }
      if (this.badgeEl) {
        if (count > 0) {
          this.badgeEl.hidden = false;
          this.badgeEl.textContent = count > 99 ? '99+' : String(count);
        } else {
          this.badgeEl.hidden = true;
        }
      }

      const items = data.items || [];
      if (!items.length) {
        this.listEl.innerHTML = '<div class="tiq-notif-empty"><i class="fas fa-bell-slash" style="opacity:0.3;display:block;font-size:1.5rem;margin-bottom:0.5rem;"></i>All caught up — no notifications</div>';
        return;
      }

      this.listEl.innerHTML = items.map((n) => {
        const cat = n.category || 'info';
        const catLabel = { exam: 'Exam', task: 'Task', support: 'Support', billing: 'Billing', announcement: 'News', info: 'Alert' }[cat] || cat;
        const unread = n.is_read ? '' : ' unread';
        const body = this.escape(n.body || '');
        const title = this.escape(n.title || '');
        const time = this.escape(n.time_ago || '');
        const icon = n.icon || 'bell';
        return `<a href="${n.link_url || '#'}" class="tiq-notif-item${unread}" data-id="${n.id}" data-link="${n.link_url || ''}">
          <div class="tiq-notif-item-icon ${cat}"><i class="fas fa-${icon}"></i></div>
          <div class="tiq-notif-item-body">
            <div class="tiq-notif-item-title">${title} <span class="tiq-badge tiq-badge-neutral" style="font-size:0.65rem;vertical-align:middle;margin-left:4px;">${this.escape(catLabel)}</span></div>
            ${body ? `<div class="tiq-notif-item-text">${body}</div>` : ''}
            <div class="tiq-notif-item-time">${time}</div>
          </div>
        </a>`;
      }).join('');

      this.listEl.querySelectorAll('.tiq-notif-item').forEach((el) => {
        el.addEventListener('click', (e) => this.onItemClick(e, el));
      });
    },

    async onItemClick(e, el) {
      const id = el.dataset.id;
      const link = el.dataset.link;
      if (id) {
        e.preventDefault();
        await this.markRead(id);
        if (link) window.location.href = link;
        else this.load(true);
      }
    },

    async markRead(id) {
      const res = await fetch(`/notifications/${id}/read`, {
        method: 'POST',
        credentials: 'same-origin',
        headers: {
          'X-CSRFToken': this.csrf(),
          'Content-Type': 'application/json',
        },
      });
      if (!res.ok) return;
      const el = this.listEl?.querySelector(`.tiq-notif-item[data-id="${id}"]`);
      if (el) el.classList.remove('unread');
      const data = await res.json();
      if (this.badgeEl) {
        const c = data.unread_count || 0;
        if (c > 0) {
          this.badgeEl.hidden = false;
          this.badgeEl.textContent = c > 99 ? '99+' : String(c);
        } else {
          this.badgeEl.hidden = true;
        }
      }
      const markAllBtn = document.getElementById('tiqNotifMarkAll');
      if (markAllBtn) markAllBtn.disabled = (data.unread_count || 0) === 0;
    },

    async markAllRead() {
      const markAllBtn = document.getElementById('tiqNotifMarkAll');
      if (markAllBtn?.disabled) return;
      if (markAllBtn) markAllBtn.disabled = true;
      try {
        const res = await fetch('/notifications/read-all', {
          method: 'POST',
          credentials: 'same-origin',
          headers: {
            'X-CSRFToken': this.csrf(),
            'Content-Type': 'application/json',
          },
        });
        if (!res.ok) {
          window.TrainIQ?.Toast?.show('error', '', 'Could not mark notifications as read');
          return;
        }
        const data = await res.json();
        this.render(data);
      } finally {
        const markAllBtn = document.getElementById('tiqNotifMarkAll');
        if (markAllBtn && (this.badgeEl?.hidden !== false)) {
          markAllBtn.disabled = true;
        }
      }
    },

    escape(s) {
      const d = document.createElement('div');
      d.textContent = s;
      return d.innerHTML;
    },
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
  window.TrainIQ = { Theme, Sidebar, Toast, Modal, Session, Notifications };

  /* ─── Init ─────────────────────────────────────────────── */
  document.addEventListener('DOMContentLoaded', () => {
    Theme.init();
    Sidebar.init();
    Dropdowns.init();
    Toast.init();
    Modal.init();
    Session.init();
    Notifications.init();
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
