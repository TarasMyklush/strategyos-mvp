(function(){"use strict";
const H=function(t){return document.getElementById(t);};
const $=function(t){return document.getElementById(t);};

// ── humanize ──
function humanizeToken(token){
  if(!token)return"--";
  const s=String(token);
  const m={published:"Published",draft:"Draft",pending:"Pending",approved:"Approved",
    rejected:"Rejected",blocked:"Blocked",needs_closure:"Needs closure",
    needs_reviewer_closure:"Needs closure",active:"Active",waiting:"Waiting",
    running:"Running",completed:"Completed",closed:"Closed",pre:"Pre-board",
    live:"Live",open:"Open",frozen:"Frozen",gated:"Gated",ready:"Ready",
    clear:"Clear",protected:"Protected",governed:"Governed",
    identity_provider:"IdP",langgraph:"LangGraph",hetzner_qa:"Hetzner QA",
    strategyos_live:"StrategyOS Live","strategyos-live":"StrategyOS Live"};
  if(m[s])return m[s];
  return s.replace(/_/g," ").replace(/-/g," ").split(" ").map(function(w){return w.charAt(0).toUpperCase()+w.slice(1);}).join(" ");
}
function formatCount(v){const n=Number(v);return Number.isFinite(n)?n:0;}
function escapeHtml(v){return String(v).replace(/&/g,"&amp;").replace(/</g,"&lt;").replace(/>/g,"&gt;").replace(/"/g,"&quot;");}

// ── state ──
let state={latestPacket:null,session:null,personas:[],activePersona:"ceo",activeDriver:null,boardState:"closed"};

// ── fetch ──
async function refresh(){
  try{
    const[packet,session]=await Promise.all([
      fetch("/public/runs/latest").then(function(r){return r.ok?r.json():null;}),
      fetch("/ui/session").then(function(r){return r.ok?r.json():null;})
    ]);
    state.latestPacket=packet;
    state.session=session;
    state.personas=(packet&&packet.executive_modes&&packet.executive_modes.personas)||[];
    state.activePersona=(packet&&packet.executive_modes&&packet.executive_modes.active_persona_id)||"ceo";
    state.activeDriver=(packet&&packet.executive_modes&&packet.executive_modes.driver_focus)?packet.executive_modes.driver_focus.find(function(d){return d.active;}):null;
    state.boardState=(packet&&packet.board_portal&&packet.board_portal.state)||"closed";

    renderTopbar();
    renderHero();
    renderDriverGrid();
    renderDrill();
    renderLower();
  }catch(e){console.warn("refresh failed",e);}
}

// ── topbar ──
function renderTopbar(){
  var s=state.session||{};
  var org=$( "tb-org-name");
  if(org)org.textContent=((s.tenant_context&&s.tenant_context.tenant_name)||"StrategyOS Live");
  var pList=$( "pm-list");
  if(!pList)return;
  pList.innerHTML="";
  (state.personas||[]).forEach(function(p){
    var active=p.persona_id===state.activePersona;
    var div=document.createElement("button");
    div.className="pm-item"+(active?" is-active":"");
    div.innerHTML='<span class="pm-item-role">'+escapeHtml(p.label)+'</span><span class="pm-item-tag">'+escapeHtml(p.persona_id)+'</span>';
    div.onclick=function(){state.activePersona=p.persona_id;refresh();pList.hidden=true;};
    pList.appendChild(div);
  });
  var label=$( "persona-label");
  var activeP=state.personas.find(function(p){return p.persona_id===state.activePersona;});
  if(label&&activeP)label.textContent=activeP.label;
  var btn=$( "persona-btn");
  if(btn)btn.onclick=function(){var l=$( "pm-list");if(l)l.hidden=!l.hidden;};
}

// ── hero ──
function renderHero(){
  var p=state.latestPacket;
  if(!p)return;
  var diag=(p.executive_diagnostics||{}).hero||{};
  var score=diag.score||92;
  $( "hero-eyebrow").textContent=(diag.persona_label||"Group CEO")+" diagnostics";
  $( "hero-head").textContent=diag.label||diag.status||"Plan health";
  $( "hero-body").textContent=diag.summary||p.plan_health&&p.plan_health.summary||"";
  $( "hero-score").textContent=score;
  $( "hero-cap").textContent=diag.status||"needs closure";
  // ring arc
  var arc=$( "hero-arc");
  if(arc){
    var circ=2*Math.PI*44;
    var dash=circ*(score/100);
    arc.setAttribute("stroke-dasharray",dash+" "+(circ-dash));
    arc.setAttribute("transform","rotate(-90 50 50)");
    arc.style.transformOrigin="50% 50%";
  }
}

// ── driver grid ──
function renderDriverGrid(){
  var grid=document.getElementById("driver-row");
  if(!grid)return;
  var drives=(state.latestPacket&&state.latestPacket.executive_modes&&state.latestPacket.executive_modes.driver_focus)||[];
  grid.innerHTML="";
  drives.slice(0,4).forEach(function(d){
    var tile=document.createElement("div");
    tile.className="driver-tile"+(d.active?" is-selected":"");
    tile.innerHTML='<span class="driver-ofplan">'+escapeHtml(d.label)+'</span>'+
      '<span class="driver-pct tone-up">'+escapeHtml(d.metric||"--")+'</span>'+
      '<div class="driver-name">'+escapeHtml(d.status||"--")+'</div>'+
      '<div class="driver-foot">'+escapeHtml(d.detail||"")+'</div>';
    tile.onclick=function(){state.activeDriver=d;renderDrill();};
    grid.appendChild(tile);
  });
}

// ── drill ──
function renderDrill(){
  var sec=$( "drill");
  if(!sec)return;
  var d=state.activeDriver||((state.latestPacket&&state.latestPacket.executive_modes&&state.latestPacket.executive_modes.driver_focus||[]).find(function(x){return x.active;}));
  if(!d){sec.hidden=true;return;}
  sec.hidden=false;
  $( "drill-name").textContent=d.label||"";
  $( "drill-metric").textContent=d.metric||"";
  $( "drill-foot").textContent=d.detail||"";
  $( "drill-story").textContent=(d.status==="published"?"Board packet is published with "+formatCount((state.latestPacket&&state.latestPacket.publication&&state.latestPacket.publication.report_count)||0)+" surfaced report artifacts. The room can now operate inside approved material.":d.status==="needs_closure"?"Evidence closure at "+(d.metric||"")+" keeps the room bounded to what the packet can support.":d.detail||d.status||"");
  // chips
  var chips=$( "drill-chips");
  if(chips){
    var pub=state.latestPacket&&state.latestPacket.publication||{};
    var board=pub.board_pack||{};
    chips.innerHTML='<span class="chips-label">Now:</span>'+
      '<span class="chip">'+escapeHtml(humanizeToken(board.status||pub.status||"pending"))+'</span>'+
      '<span class="chip">'+escapeHtml(humanizeToken(state.boardState))+'</span>'+
      '<span class="chip">'+formatCount(pub.report_count||0)+' reports</span>';
  }
  var route=$( "drill-route-btn");
  if(route&&d.route)route.onclick=function(){window.location.href=d.route;};
}

// ── lower: developments + week ahead ──
function renderLower(){
  var p=state.latestPacket;
  if(!p)return;
  // developments
  var devs=(p.lower_rail||{}).developments||(p.drilldown||{}).lower_rail||{developments:[]};
  var list=$( "feed-list");
  if(list){
    list.innerHTML="";
    (devs.developments||[]).forEach(function(d,i){
      var kind=d.title&&d.title.toLowerCase().indexOf("risk")>=0?"watch":"win";
      list.innerHTML+='<div class="feed-row"><div class="feed-main"><span class="dev-kind '+kind+'">'+(kind==="watch"?"Watch":"Win")+'</span>'+
        '<span class="feed-title">'+escapeHtml(d.title||(d.label||("Item "+(i+1))))+'</span>'+
        '<span class="feed-meta">'+(d.chips||[]).map(function(c){return escapeHtml(c);}).join(" · ")+'</span>'+
        '<span class="tag">'+escapeHtml(d.detail||"")+'</span></div></div>';
    });
  }
  // week ahead
  var week=(p.lower_rail||{}).week_ahead||(p.drilldown||{}).lower_rail||{week_ahead:[]};
  var wlist=$( "week-rail");
  if(wlist){
    wlist.innerHTML="";
    (week.week_ahead||[]).forEach(function(e,i){
      wlist.innerHTML+='<div class="event-chip"><span class="event-day">'+(e.label||("Day "+(i+1)))+'</span>'+
        '<span>'+escapeHtml(e.detail||"")+'</span><span class="tag">'+escapeHtml(e.label||"TBD")+'</span></div>';
    });
  }
}

// ── init ──
refresh();
setInterval(refresh,60000);
})();
