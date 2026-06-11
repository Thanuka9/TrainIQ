/**
 * Reliable exam countdown — avoids fragile Date.parse on ISO strings.
 * Set window.__EXAM_TIMER__ = { startMs, durationSec } before loading.
 */
(function (global) {
  function cfg() {
    return global.__EXAM_TIMER__ || {};
  }

  function calcRemaining() {
    const c = cfg();
    const startMs = Number(c.startMs) || Date.now();
    const total = Math.max(Number(c.durationSec) || 3600, 60);
    const elapsed = Math.floor((Date.now() - startMs) / 1000);
    return Math.max(0, total - elapsed);
  }

  function formatTime(seconds) {
    const m = String(Math.floor(seconds / 60)).padStart(2, "0");
    const s = String(seconds % 60).padStart(2, "0");
    return `${m}:${s}`;
  }

  global.ExamTimer = {
    calcRemaining,
    formatTime,
    start(onTick, onExpire) {
      if (global.__examTimerInterval) {
        return global.__examTimerInterval;
      }
      const timerEl = document.getElementById("timer");
      const progressBar = document.getElementById("progressBar");
      const total = Math.max(Number(cfg().durationSec) || 3600, 60);

      function tick() {
        const remaining = calcRemaining();
        if (typeof onTick === "function") {
          onTick(remaining, total);
        }
        if (timerEl) {
          timerEl.innerHTML = `<i class="fas fa-clock"></i> Time Remaining: ${formatTime(remaining)}`;
          timerEl.className = "timer-display";
          if (remaining <= 60) timerEl.classList.add("danger");
          else if (remaining <= 300) timerEl.classList.add("warning");
        }
        if (progressBar) {
          const ratio = total > 0 ? (remaining / total) * 100 : 0;
          progressBar.style.width = `${Math.max(0, Math.min(100, ratio))}%`;
          progressBar.className = "timer-progress-bar";
          if (remaining <= 60) progressBar.classList.add("danger");
          else if (remaining <= 300) progressBar.classList.add("warning");
        }
        if (remaining <= 0) {
          clearInterval(global.__examTimerInterval);
          global.__examTimerInterval = null;
          if (typeof onExpire === "function") onExpire();
        }
        return remaining;
      }

      tick();
      global.__examTimerInterval = setInterval(tick, 1000);
      return global.__examTimerInterval;
    },
    stop() {
      if (global.__examTimerInterval) {
        clearInterval(global.__examTimerInterval);
        global.__examTimerInterval = null;
      }
    },
  };
})(window);
