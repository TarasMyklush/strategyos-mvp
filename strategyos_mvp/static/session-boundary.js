(function () {
  'use strict';
  var tokenKey = 'strategyos.ui.token';
  var leaving = false;
  function cookieEpoch() {
    return String(document.cookie || '').split(';').map(function (part) { return part.trim(); })
      .filter(function (part) { return part.indexOf('strategyos_session_epoch=') === 0; }).join('');
  }
  var initialEpoch = cookieEpoch();
  function checkCookieSession() {
    var current = cookieEpoch();
    if (current !== initialEpoch) replaceView(!current);
  }
  function replaceView(signedOut) {
    if (leaving) return;
    leaving = true;
    // Remove already-rendered private content immediately. This does not
    // delete server history, submit drafts, or transfer the old identity.
    var message = document.createElement('p');
    message.textContent = 'Session changed. Reloading your authorized view…';
    message.setAttribute('role', 'status');
    document.documentElement.replaceChildren(message);
    if (signedOut) window.location.replace('/login');
    else window.location.reload();
  }
  window.addEventListener('storage', function (event) {
    if (event.key === 'strategyos.ui.session-change' && event.oldValue !== event.newValue) {
      var signedOut = false;
      try { signedOut = JSON.parse(event.newValue).signedOut === true; } catch (ignore) {}
      replaceView(signedOut);
      return;
    }
    if ((event.key === tokenKey && event.oldValue !== event.newValue) || event.key === null) {
      replaceView(!event.newValue);
    }
  });
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) replaceView(false);
    else checkCookieSession();
  });
  window.addEventListener('focus', checkCookieSession);
  document.addEventListener('visibilitychange', checkCookieSession);
  // Cookie changes do not emit storage events. Also covers API-based login,
  // logout, cookie expiry, and browsers where storage notifications are delayed.
  window.setInterval(checkCookieSession, 1000);
})();
