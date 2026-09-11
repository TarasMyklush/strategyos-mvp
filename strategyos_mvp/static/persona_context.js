(function (global) {
  "use strict";

  var STORAGE_KEY = "strategyos.executive.persona";
  var PERSONA_ALIASES = { pharma: "gm", distribution: "bucfo" };
  var KNOWN_PERSONAS = ["ceo", "cfo", "gm", "bucfo", "board"];
  // Only released workspaces may be restored implicitly across product pages.
  // A direct URL may still show an unreleased persona's explicit lock screen,
  // but it must not replace the user's last usable executive workspace.
  var RESTORABLE_PERSONAS = ["ceo", "board"];

  function normalize(value) {
    var normalized = String(value || "").trim().toLowerCase();
    normalized = PERSONA_ALIASES[normalized] || normalized;
    return KNOWN_PERSONAS.indexOf(normalized) >= 0 ? normalized : "";
  }

  function read() {
    var raw = "";
    try { raw = String(global.localStorage.getItem(STORAGE_KEY) || ""); } catch (_error) { return ""; }
    var normalized = normalize(raw);
    if (RESTORABLE_PERSONAS.indexOf(normalized) < 0) normalized = "";
    try {
      if (!normalized && raw) global.localStorage.removeItem(STORAGE_KEY);
      else if (normalized && normalized !== raw) global.localStorage.setItem(STORAGE_KEY, normalized);
    } catch (_error) {}
    return normalized;
  }

  function write(value) {
    var normalized = normalize(value);
    if (RESTORABLE_PERSONAS.indexOf(normalized) < 0) return read();
    try { global.localStorage.setItem(STORAGE_KEY, normalized); } catch (_error) {}
    return normalized;
  }

  global.KyvernPersonaContext = {
    normalize: normalize,
    read: read,
    write: write,
    storageKey: STORAGE_KEY
  };
}(window));
