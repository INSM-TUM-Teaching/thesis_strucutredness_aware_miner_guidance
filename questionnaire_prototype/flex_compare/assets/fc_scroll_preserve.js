/* Preserve per-pane scroll position across full body re-renders.
 *
 * The questionnaire tab rebuilds the whole `#fc-fb-body` subtree on every
 * interaction (render_body is the single source of UI state). That destroys and
 * recreates the scrollable `.fc-survey-2col-pane` containers, so the browser
 * resets them to scrollTop = 0 — the pane jumps to the top after every click.
 *
 * Fix: remember each pane's scrollTop keyed by a stable `data-fc-scroll-key`
 * (content identity, e.g. the log stem) and re-apply it right after the rebuild.
 * Navigation to a new log/item produces a fresh key with no stored value, so it
 * naturally starts at the top — no reset gymnastics needed.
 */
(function () {
  "use strict";

  var ATTR = "data-fc-scroll-key";
  var store = {}; // scrollKey -> scrollTop
  var isRestoring = false; // guard: ignore scroll events we fire ourselves

  // scroll events do not bubble, so capture them on the way down. Only record
  // genuine user scrolls — a programmatic restore re-fires scroll, and if it
  // gets clamped (content not laid out yet) it would otherwise poison the store
  // with a too-small value.
  document.addEventListener(
    "scroll",
    function (e) {
      if (isRestoring) {
        return;
      }
      var el = e.target;
      if (el && el.nodeType === 1 && el.hasAttribute && el.hasAttribute(ATTR)) {
        store[el.getAttribute(ATTR)] = el.scrollTop;
      }
    },
    true
  );

  function restore() {
    isRestoring = true;
    var panes = document.querySelectorAll("[" + ATTR + "]");
    for (var i = 0; i < panes.length; i++) {
      var key = panes[i].getAttribute(ATTR);
      if (Object.prototype.hasOwnProperty.call(store, key)) {
        panes[i].scrollTop = store[key];
      }
    }
    isRestoring = false;
  }

  function attach() {
    var body = document.getElementById("fc-fb-body");
    if (!body) {
      return false;
    }
    var observer = new MutationObserver(function () {
      // Body subtree was replaced by render_body; re-apply remembered offsets.
      // Restore synchronously (before paint, so no visible jump) and again on
      // the next frames in case a heavy pane (model SVGs) is still growing and
      // would otherwise clamp the synchronous attempt.
      restore();
      window.requestAnimationFrame(function () {
        restore();
        window.requestAnimationFrame(restore);
      });
    });
    observer.observe(body, { childList: true, subtree: true });
    return true;
  }

  // #fc-fb-body may not exist yet when this asset loads; poll briefly until it
  // mounts, then stop.
  if (!attach()) {
    var tries = 0;
    var iv = setInterval(function () {
      if (attach() || ++tries > 50) {
        clearInterval(iv);
      }
    }, 100);
  }
})();
