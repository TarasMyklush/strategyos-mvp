(function () {
  'use strict';
  var form = document.getElementById('claim-query');
  var status = document.getElementById('claim-status');
  var results = document.getElementById('claim-results');
  var requestVersion = 0;
  var initialQuery=new URLSearchParams(location.search);
  ['metric_key','claim_kind','business_unit','scenario_key','purpose'].forEach(function(key){if(initialQuery.has(key))form.elements.namedItem(key).value=initialQuery.get(key);});
  function node(tag, text, className) { var item = document.createElement(tag); item.textContent = text; if(className) item.className = className; return item; }
  function fields(values) { var dl = document.createElement('dl'); Object.entries(values).forEach(function(pair){dl.append(node('dt',pair[0]),node('dd',pair[1] == null || pair[1] === '' ? 'Not supplied' : String(pair[1])));}); return dl; }
  function renderClaim(record) {
    var article = node('article','','card claim-record');
    article.append(node('h2', record.metric_key));
    article.append(node('p', record.label || record.claim_kind, 'claim-kind--' + record.claim_kind));
    if(record.superseded_since_analysis) article.append(node('p','Historical result — this claim or its inputs have since been revised. Recalculate before using it for a current decision.','claim-stale'));
    if(record.recalculation_allowed){var recalculate=node('a','Preview recalculation →');recalculate.href='/claims/recalculate?revision='+encodeURIComponent(record.claim_revision_id);article.append(recalculate);}
    if(record.claim_kind === 'forecast' || record.claim_kind === 'assumption') article.append(node('p','This is not an actual. It may change and must not be used as a realized result.'));
    if(record.forecast_review) article.append(fields({'Scoped review':record.forecast_review.status.replaceAll('_',' '),'Review scope':record.forecast_review.scope_key,'Review due':record.forecast_review.review_due_at}));
    article.append(fields({'Value (source scale)':record.value,'Unit':record.unit,'Scale':record.scale,'Currency':record.currency,'Period':(record.period || {}).start && (record.period || {}).end ? record.period.start + ' to ' + record.period.end : null,'Business unit':record.business_unit || 'Group / unspecified','Author':record.author,'Valid until':record.valid_until || (record.period || {}).valid_until,'Revision':record.claim_revision_id}));
    var origins = {internal_system:'Internal source',public_web:'Public web · untrusted',licensed_external:'Licensed external source',correspondence:'Correspondence · reported by author',unknown:'Unclassified source'};
    (record.sources || []).forEach(function(source){var section=node('section','','claim-source');section.append(node('span',origins[source.origin_category] || origins.unknown,'claim-origin claim-origin--' + source.origin_category));section.append(fields({'Source':source.display_name || source.source_key,'Capture channel':source.capture_method,'Provider':source.provider_name,'License reference':source.license_policy_ref,'Original reference':source.original_uri,'Native version':source.source_native_version,'Locator':source.locator}));article.append(section);});
    if(record.forecast_review_allowed && window.StrategyOSClaimReview) article.append(window.StrategyOSClaimReview(record));
    var details=node('details','');details.append(node('summary','Lineage and assessments'));details.append(node('pre',JSON.stringify({formula:record.formula,interpretation:record.interpretation,assumptions:record.assumptions,assessments:record.assessments,traceability:record.traceability},null,2)));article.append(details);
    return article;
  }
  form.addEventListener('submit',async function(event){
    event.preventDefault(); var version=++requestVersion; results.replaceChildren(); status.textContent='Checking current source permissions…';
    var params=new URLSearchParams();new FormData(form).forEach(function(value,key){if(String(value).trim()) params.set(key,String(value).trim());});
    var headers={};try{var token=localStorage.getItem('strategyos.ui.token');if(token)headers.Authorization='Bearer '+token;}catch(ignore){}
    var path=params.has('text')?'/api/claims/search':'/api/claims';
try{var response=await fetch(path+'?'+params.toString(),{headers:headers,cache:'no-store'});if(!response.ok)throw new Error(response.status===401?'Please sign in again.':response.status===403?'Your source permissions do not allow this view.':response.status===422?'Check the query, including a timezone on any historical timestamp.':'Evidence is unavailable. No cached values are being shown.');var payload=await response.json();if(version!==requestVersion)return;var records=payload.records || [];records.forEach(function(record){results.append(renderClaim(record));});status.textContent=records.length?(params.has('as_of')?'Historical authorized claims: ':'Current authorized claims: ')+records.length+' · as of '+payload.analysis_as_of:'No eligible claims match this selection. No other claim type was substituted.';}catch(error){if(version!==requestVersion)return;results.replaceChildren();status.textContent=error instanceof TypeError?'Evidence is unavailable. No cached values are being shown.':error.message;}
  });
})();
