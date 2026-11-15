'use strict';
// Display only escaped text. Model output never becomes HTML.
for (const form of document.querySelectorAll('form[data-run-url]')) {
  form.addEventListener('submit', async event => {
    event.preventDefault();
    const buttons=[...form.querySelectorAll('button')]; buttons.forEach(b=>b.disabled=true);
    try {
      const response=await fetch(form.dataset.runUrl,{method:'POST',body:new URLSearchParams(new FormData(form)),headers:{Accept:'application/json'}});
      if(!response.ok) { let data={};try{data=await response.json();}catch(error){}let note=form.querySelector('[role=alert]');if(!note){note=document.createElement('p');note.setAttribute('role','alert');form.append(note);}note.textContent=data.error||'Could not queue this test. Refresh the page and check the saved business settings.';buttons.forEach(b=>b.disabled=false);return; }
      const run=await response.json();window.location.assign(run.url);
    } catch(error) { alert('The local app could not be reached. Keep Start.cmd open and try again.');buttons.forEach(b=>b.disabled=false); }
  });
}
const panel=document.getElementById('run-panel');
if(panel) {
  let previous=-1;
  const text=(tag,value)=>{const node=document.createElement(tag);node.textContent=String(value??'');return node;};
  async function poll(){
    try {
      const response=await fetch(panel.dataset.statusUrl,{cache:'no-store'});
      if(!response.ok)throw new Error('status');
      const run=await response.json();
      document.getElementById('run-state').textContent=run.status;
      document.getElementById('run-progress').value=run.completed;
      document.getElementById('run-summary').textContent=`${run.completed} / ${run.total} completed · ${run.matches} / ${run.checked} expected routes matched · ${run.errors} generation errors · ${run.blocked} blocked drafts`;
      document.getElementById('run-error').textContent=run.error||'';
      const active=['queued','running'].includes(run.status);
      document.getElementById('cancel-run').hidden=!active;
      document.getElementById('resume-run').hidden=!['interrupted','cancelled','failed'].includes(run.status);
      document.getElementById('run-current').textContent=run.status==='running'?`Processing case ${Math.min(run.completed+1,run.total)}. A slow model may take up to three minutes per request. ${run.cancel_requested?'Cancellation requested; waiting for this case.':''}`:'No result is automatically published or approved.';
      if(previous!==run.completed){
        const results=document.getElementById('lab-results');results.replaceChildren();
        for(const row of run.results){const article=text('article','');article.className='review';article.append(text('strong',`${row.id} · ${row.rating} / 5`),text('p',row.text||'Rating only'),text('small',`${row.status} · ${row.risk||'No classification'}`));if(row.reply)article.append(text('blockquote',row.reply));article.append(text('p',row.reason),text('p',row.handoff||'Handoff preview unavailable for this older run.'),text('p',row.error),text('small',`${row.elapsed}s · expected ${row.expected||'not scored'} · routing match ${row.route_match??'not scored'}`));results.append(article);}previous=run.completed;
      }
      if(active)setTimeout(poll,1500);
    }catch(error){document.getElementById('run-error').textContent='Cannot reach the local app. Keep Start.cmd open. This page will retry; completed cases remain saved.';setTimeout(poll,4000);}
  }
  poll();
}
