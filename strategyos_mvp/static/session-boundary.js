(function () {
  'use strict';
  var tokenKey = 'strategyos.ui.token';
  var leaving = false;
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
    if ((event.key === tokenKey && event.oldValue !== event.newValue) || event.key === null) {
      replaceView(!event.newValue);
    }
  });
  window.addEventListener('pageshow', function (event) {
    if (event.persisted) replaceView(false);
  });
})();
