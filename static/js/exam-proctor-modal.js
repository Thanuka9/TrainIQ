/**
 * Shared focus-loss proctor modal for exam templates.
 * Expects: form, warnOverlay, submitted, totalDuration, remainingSeconds,
 *          timeInp, focusLossCount, syncProctorEvents (optional).
 */
function examProctorTriggerWarning() {
  if (typeof submitted !== "undefined" && submitted) return;
  focusLossCount = (focusLossCount || 0) + 1;
  if (typeof syncProctorEvents === "function") syncProctorEvents();
  if (typeof reportViolation === "function") reportViolation("focus_losses");

  if (focusLossCount >= 2) {
    submitted = true;
    if (timeInp) timeInp.value = totalDuration - remainingSeconds;
    if (typeof form !== "undefined" && form) form.submit();
  } else if (warnOverlay) {
    warnOverlay.style.display = "flex";
  }
}

function examProctorSubmitAndExit() {
  submitted = true;
  if (timeInp) timeInp.value = totalDuration - remainingSeconds;
  if (typeof syncProctorEvents === "function") syncProctorEvents();
  if (typeof form !== "undefined" && form) form.submit();
}

function examProctorDismissWarning() {
  if (warnOverlay) warnOverlay.style.display = "none";
  if (typeof toggleFullScreen === "function") toggleFullScreen();
}

function examProctorBindFocusHandlers() {
  document.addEventListener("visibilitychange", () => {
    if (document.hidden && !submitted) examProctorTriggerWarning();
  });
  window.addEventListener("blur", () => {
    if (!submitted) examProctorTriggerWarning();
  });
}
