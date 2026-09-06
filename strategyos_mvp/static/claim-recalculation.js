(function () {
  'use strict';
  const form=document.getElementById('recalculation-form'),apply=document.getElementById('recalculation-apply');
  const status=document.getElementById('recalculation-status'),results=document.getElementById('recalculation-results');
  let preview=null,busy=false,generation=0;
  const value=name=>form.elements.namedItem(name).value.trim();
  const supplied=new URLSearchParams(location.search).get('revision');
  if(supplied)form.elements.namedItem('revision_id').value=supplied;
  form.addEventListener('input',()=>{generation++;preview=null;apply.disabled=true;results.replaceChildren();});
  function node(tag,text){const item=document.createElement(tag);item.textContent=text;return item;}
  const queueButton=document.getElementById('recalculation-queue-load'),queueStatus=document.getElementById('recalculation-queue-status');
  let queueCursor=null;
  queueButton.addEventListener('click',async()=>{
    queueButton.disabled=true;queueStatus.textContent='Checking authorized calculation families…';
    try{
      const response=await fetch('/api/claims/recalculation-queue'+(queueCursor?'?after='+encodeURIComponent(queueCursor):''),{credentials:'same-origin',cache:'no-store'});
      const payload=await response.json();
      if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'Queue unavailable.');
      const queue=document.getElementById('recalculation-queue');queue.replaceChildren();
      for(const item of payload.items || []){
        const card=node('article',''),link=node('a',item.metric_key+' · '+item.claim_kind+' · '+(item.business_unit || 'Group'));
        link.href='/claims/recalculate?revision='+encodeURIComponent(item.claim_revision_id);
        card.append(link,node('p',(item.period_start || 'Period not supplied')+(item.period_end?' — '+item.period_end:'')));queue.append(card);
      }
      queueCursor=payload.next_cursor;
      queueStatus.textContent=payload.items.length+' authorized '+(payload.items.length===1?'candidate':'candidates')+' in this scan.'+(queueCursor?' More families remain to be checked.':' Scan complete.');
      queueButton.textContent=queueCursor?'Check next families':'Refresh from beginning';
    }catch(error){queueStatus.textContent=error instanceof TypeError?'Queue unavailable. Retry.':error.message;}
    finally{queueButton.disabled=false;}
  });
  async function run(record){
    if(busy || !form.reportValidity() || (record && !preview))return;
    const ticket=generation,revision=value('revision_id'),body={rationale:value('rationale')};
    if(record)body.expected_preview=preview.preview_key;
    busy=true;apply.disabled=true;form.querySelector('[type="submit"]').disabled=true;
    status.textContent=record?'Recording the exact preview…':'Checking current inputs and source rights…';
    try{
      const response=await fetch('/api/claims/'+encodeURIComponent(revision)+'/recalculate',{
        method:'POST',credentials:'same-origin',cache:'no-store',headers:{'Content-Type':'application/json'},body:JSON.stringify(body)});
      const payload=await response.json();
      if(!response.ok)throw new Error(typeof payload.detail==='string'?payload.detail:'Recalculation was not accepted.');
      if(ticket!==generation){status.textContent=record?'The previous preview was recorded. Your edited inputs have not been processed.':'Inputs changed; preview again.';return;}
      results.replaceChildren();
      for(const change of payload.changes || []){
        const card=node('article','');card.className='card claim-record';card.append(node('h2',change.metric_key));
        card.append(node('p',change.claim_kind+' · '+change.previous_value+' → '+change.proposed_value+' '+change.unit+' · scale '+change.scale));
        const details=node('details','');details.append(node('summary','Formula and prior revision'));
        details.append(node('pre',JSON.stringify(change,null,2)));card.append(details);results.append(card);
      }
      if(record){preview=null;status.textContent=payload.replayed?'Already recorded. No duplicate calculations were created.':'Recorded '+payload.created_count+' unreviewed '+(payload.created_count===1?'calculation':'calculations')+'. The briefing and approvals were not changed.';
        const link=node('a','Inspect the current governed evidence →'),query=new URLSearchParams();
        for(const [key,value] of Object.entries(payload.query || {})){if(value)query.set(key,value);}
        link.href='/claims?'+query.toString();results.append(link);
      }
      else{preview=payload;status.textContent=payload.changes.length?'Preview only. Review the changes before recording.':'No recalculation is needed for these input revisions.';}
    }catch(error){status.textContent=error instanceof TypeError?'No result confirmed. Retry the same preview to check its receipt.':error.message;}
    finally{busy=false;form.querySelector('[type="submit"]').disabled=false;apply.disabled=!preview || !preview.changes.length;}
  }
  form.addEventListener('submit',event=>{event.preventDefault();run(false);});
  apply.addEventListener('click',()=>run(true));
}());
