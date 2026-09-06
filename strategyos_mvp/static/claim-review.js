(function () {
  'use strict';
  window.StrategyOSClaimReview = function (record) {
    function element(tag, text) { var item=document.createElement(tag); if(text)item.textContent=text; return item; }
    var details=element('details'), summary=element('summary','Review this forecast for a specific scope');
    var form=element('form'); form.className='claim-query';
    var effectKey=null;
    function field(label,type,name) {
      var wrapper=element('label',label), input=element(type==='textarea'?'textarea':'input');
      if(type!=='textarea')input.type=type;
      input.name=name; wrapper.append(input); form.append(wrapper); return input;
    }
    var scope=field('Analysis scope','text','scope');scope.required=true;scope.maxLength=160;
    scope.value=(record.forecast_review||{}).scope_key||'';
    var due=field('Review again by (optional, your local time)','datetime-local','due');
    var choiceLabel=element('label','Decision'), choice=element('select');
    ['accepted','rejected'].forEach(function(value){var option=element('option',value==='accepted'?'Accept for this scope':'Reject for this scope');option.value=value;choice.append(option);});
    choiceLabel.append(choice);form.append(choiceLabel);
    var rationale=field('Reason for your decision','textarea','rationale');rationale.required=true;rationale.maxLength=2000;rationale.rows=3;
    var note=element('p','Records your review only; no assignment or message is sent. Without a review date, the forecast remains ineligible for accepted-only analysis.');note.className='claim-query-wide';form.append(note);
    var button=element('button','Record scoped review');button.type='submit';form.append(button);
    var status=element('p');status.setAttribute('role','status');status.setAttribute('aria-live','polite');
    form.addEventListener('input',function(){effectKey=null;});
    form.addEventListener('submit',async function(event){
      event.preventDefault(); if(!form.reportValidity())return;
      effectKey=effectKey||crypto.randomUUID();
      var payload={decision:choice.value,scope_key:scope.value.trim(),review_due_at:due.value?new Date(due.value).toISOString():null,rationale:rationale.value.trim(),effect_key:effectKey};
      var controls=Array.from(form.elements);controls.forEach(function(control){control.disabled=true;});
      status.textContent='Checking review authority and recording your decision…';
      var headers={'Content-Type':'application/json'};
      try { var token=localStorage.getItem('strategyos.ui.token');if(token)headers.Authorization='Bearer '+token; } catch(ignore) {}
      try {
        var response=await fetch('/api/claims/'+encodeURIComponent(record.claim_revision_id)+'/forecast-review',{method:'POST',credentials:'same-origin',cache:'no-store',headers:headers,body:JSON.stringify(payload)});
        var result=await response.json();
        if(!response.ok)throw new Error(typeof result.detail==='string'?result.detail:'This review could not be recorded.');
        status.textContent=(result.created?'Review recorded. ':'This review was already recorded. ')+result.notice+' Refresh the evidence query to see its current status.';
      } catch(error) {status.textContent='Not confirmed: '+error.message+' Retry unchanged inputs to check the same request.';}
      finally {controls.forEach(function(control){control.disabled=false;});}
    });
    details.append(summary,form,status);return details;
  };
}());
