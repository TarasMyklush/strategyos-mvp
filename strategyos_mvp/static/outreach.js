(function () {
  "use strict";
  var state = { catalog: null, filter: "all" };
  var statuses = ["all", "drafted", "awaiting_approval", "sent", "replied", "flagged"];
  function $(id) { return document.getElementById(id); }
  function safe(value) { return String(value == null ? "" : value).replace(/[&<>"']/g, function (c) { return {"&":"&amp;","<":"&lt;",">":"&gt;",'"':"&quot;","'":"&#39;"}[c]; }); }
  function label(value) { return String(value || "").replace(/_/g, " ").replace(/\b\w/g, function (c) { return c.toUpperCase(); }); }
  function time(value) { var d = new Date(value); return Number.isNaN(d.valueOf()) ? "" : d.toLocaleString([], {month:"short", day:"numeric", hour:"2-digit", minute:"2-digit"}); }
  async function get(path) {
    var response = await fetch(path, {headers:{Accept:"application/json"}, credentials:"same-origin"});
    if (response.status === 401) { location.assign("/login?next=%2Foutreach"); throw new Error("Sign-in required"); }
    if (!response.ok) { var body = await response.json().catch(function(){ return {}; }); throw new Error(body.detail || "Unable to load outreach data."); }
    return response.json();
  }
  function providers() { return new Map((state.catalog.providers || []).map(function (item) { return [item.provider_id, item]; })); }
  function renderCoverage() {
    var c = state.catalog.coverage || {};
    var items = [["named_provider_count","named providers"],["connected_count","connected"],["contacted_count","contacted"],["responding_count","responding"],["flagged_count","flagged for review"]];
    $("coverage").innerHTML = items.map(function(item){ return '<article class="stat"><strong>'+safe(c[item[0]] || 0)+'</strong><span>'+safe(item[1])+'</span></article>'; }).join("");
  }
  function renderPeople() {
    var threads = state.catalog.threads || [];
    $("people").innerHTML = (state.catalog.providers || []).map(function(person){
      var related = threads.filter(function(item){ return item.provider_id === person.provider_id; });
      var stateLabel = related.length ? label(related[related.length - 1].current_status) : "No thread";
      return '<article class="person"><span class="avatar">'+safe(person.name.slice(0,1))+'</span><div><strong>'+safe(person.name)+'</strong><span>'+safe(person.role)+' · '+safe(stateLabel)+'</span></div><i class="connection '+safe(person.connection_status)+'" title="'+safe(label(person.connection_status))+'"></i></article>';
    }).join("");
  }
  function renderFilters() {
    var counts = (state.catalog.coverage || {}).status_counts || {};
    $("filters").innerHTML = statuses.map(function(status){ var count = status === "all" ? (state.catalog.threads || []).length : (counts[status] || 0); return '<button class="filter '+(state.filter === status ? 'active' : '')+'" data-filter="'+safe(status)+'">'+safe(label(status))+' · '+safe(count)+'</button>'; }).join("");
    $("filters").querySelectorAll("[data-filter]").forEach(function(button){ button.onclick=function(){ state.filter=button.dataset.filter; renderFilters(); renderThreads(); }; });
  }
  function renderThreads() {
    var people = providers();
    var rows = (state.catalog.threads || []).filter(function(item){ return state.filter === "all" || item.current_status === state.filter; });
    var requested = (state.catalog.data_requests || []).filter(function (item) { return state.filter === "all" || state.filter === "drafted"; });
    var requestMarkup = requested.map(function (item) {
      return '<article class="thread drafted" data-request-id="'+safe(item.request_id)+'"><div class="thread-head"><div><h3>'+safe(item.kpi_label)+' data request</h3><div class="thread-meta">Created by '+safe(label(item.created_by))+' → '+safe(item.provider)+'</div></div><span class="status drafted">Drafted</span></div><blockquote class="question">Request '+safe((item.missing_inputs || []).join('; '))+'</blockquote><div class="facts"><div class="fact"><span>Calculation</span><strong>'+safe(item.formula)+'</strong></div><div class="fact"><span>Provider</span><strong>'+safe(item.provider)+'</strong></div><div class="fact reason"><span>Governance</span><strong>Approval is required before any external message can be sent.</strong></div></div></article>';
    }).join('');
    var threadMarkup = rows.length ? rows.map(function(thread){
      var person = people.get(thread.provider_id) || {};
      var trail = (thread.lifecycle || []).map(function(event){ return '<div class="step"><strong>'+safe(label(event.action))+'</strong><span>'+safe(time(event.occurred_at))+'</span>'+(event.approved_by ? '<span>Approved by '+safe(event.approved_by)+'</span>' : '')+'</div>'; }).join("");
      var outcome = thread.outcome ? '<div class="outcome"><div><strong>'+safe(label(thread.outcome.kind))+'</strong><div>'+safe(thread.outcome.summary)+'</div></div><button data-entry="'+safe(thread.outcome.knowledge_entry.entry_id)+'">Open structured entry</button></div>' : '';
      return '<article class="thread '+safe(thread.current_status)+'"><div class="thread-head"><div><h3>'+safe(thread.title)+'</h3><div class="thread-meta">'+safe(thread.agent.name)+' · '+safe(thread.agent.accountable_role)+' → '+safe(person.name)+' · '+safe(person.role)+'</div></div><span class="status '+safe(thread.current_status)+'">'+safe(label(thread.current_status))+'</span></div><blockquote class="question">'+safe(thread.question)+'</blockquote><div class="facts"><div class="fact"><span>Triggered by</span><strong>'+safe(thread.trigger.label)+'</strong></div><div class="fact"><span>Governed source</span><strong>'+safe(label(thread.trigger.kind))+'</strong></div><div class="fact reason"><span>Why this outreach exists</span><strong>'+safe(thread.trigger.reason)+'</strong></div></div><div class="trail">'+trail+'</div>'+outcome+'</article>';
    }).join("") : '';
    $("threads").innerHTML = requestMarkup + threadMarkup || '<div class="empty">No threads have this status.</div>';
    $("threads").querySelectorAll("[data-entry]").forEach(function(button){ button.onclick=function(){ openProjection(button.dataset.entry); }; });
  }
  async function openProjection(entryId) {
    try {
      var detail = await get("/api/outreach/synthetic/knowledge/" + encodeURIComponent(entryId));
      var e = detail.entry || {}, source = detail.source_thread || {}, trigger = source.trigger || {};
      $("drawer-title").textContent = label(e.kind);
      $("drawer-body").innerHTML = '<div class="projection"><div><span>Subject</span><strong>'+safe(e.subject_ref)+'</strong></div><div><span>Structured predicate</span><strong>'+safe(e.predicate)+'</strong></div><div><span>Structured value</span><strong>'+safe(e.value)+(e.unit ? ' · '+safe(e.unit) : '')+'</strong></div><div><span>Source thread</span><strong>'+safe(source.title)+'</strong></div><div><span>Trigger</span><strong>'+safe(trigger.label)+'</strong></div><div><span>Disposition</span><strong>'+safe(label(e.disposition))+'</strong></div></div><p class="boundary">Synthetic projection · no authority effect. Only the structured result and its lineage are present; source reply text is not stored.</p>';
      $("drawer").hidden=false; $("drawer-scrim").hidden=false;
    } catch (error) { $("threads").insertAdjacentHTML("afterbegin", '<div class="error">'+safe(error.message)+'</div>'); }
  }
  function closeDrawer(){ $("drawer").hidden=true; $("drawer-scrim").hidden=true; }
  async function init(){
    $("drawer-close").onclick=closeDrawer; $("drawer-scrim").onclick=closeDrawer;
    try {
      var persona = window.KyvernPersonaContext ? window.KyvernPersonaContext.read() : "";
      document.querySelectorAll('a[href^="/app"]').forEach(function (link) {
        if (persona) link.href = '/app?persona=' + encodeURIComponent(persona) + (link.href.indexOf('view=agents') >= 0 ? '&view=agents' : '');
      });
      state.catalog=await get("/api/outreach/synthetic"); renderCoverage(); renderPeople(); renderFilters(); renderThreads();
      var requestId = new URL(location.href).searchParams.get('request');
      if (requestId) {
        var requestCard = document.querySelector('[data-request-id="' + requestId.replace(/"/g, '') + '"]');
        if (requestCard) requestCard.scrollIntoView({block:'center'});
      }
    }
    catch(error){ $("threads").innerHTML='<div class="error">'+safe(error.message)+'</div>'; }
  }
  document.addEventListener("DOMContentLoaded", init);
}());
