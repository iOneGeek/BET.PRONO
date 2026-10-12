const $=id=>document.getElementById(id);
const SP={F:'Foot',M:'Mixte',T:'Tennis',B:'MLB',N:'NFL',H:'NHL'},TY={C:'Combiné',S:'Simple',F:'Combiné FUN',4:'Combiné x4',5:'Combiné x5'};
const SPORTS=['Foot','Mixte','Tennis','NBA','F1','MMA','MLB','NFL','NHL'];

let BETS=[], INIT=100;

async function api(path, opts={}){
  const r=await fetch(path,{credentials:'same-origin',headers:{'Content-Type':'application/json'},...opts});
  if(r.status===401){location.href='/login';throw new Error('unauthenticated')}
  const data=await r.json().catch(()=>({}));
  if(!r.ok) throw new Error(data.error||'Erreur serveur');
  return data;
}

const eur=n=>n.toLocaleString('fr-FR',{style:'currency',currency:'EUR'});
const pct=n=>n.toLocaleString('fr-FR',{maximumFractionDigits:2})+' %';
const LB={won:'Gagné',lost:'Perdu',void:'Remboursé',pending:'En cours',wd:'Retrait'};
let PER='all';
const cut=()=>{if(PER==='all')return'';const d=new Date();d.setDate(d.getDate()-({d:0,w:6,m:29})[PER]);return d.toISOString().slice(0,10)};
const pl=b=>b.r==='won'?b.s*(b.o-1)+(b.b||0):b.r==='lost'?-b.s:0;

function chart(L){
  let c=0;const pts=[0,...L.map(b=>c+=pl(b))];
  const lo=Math.min(...pts),hi=Math.max(...pts),rng=(hi-lo)||1;
  const st=[10,25,50,100,250,500,1000,2500,5000].find(s=>rng/s<=5)||10000;
  const a=Math.floor(lo/st)*st,z=Math.ceil(hi/st)*st||st;
  const X=i=>56+(pts.length>1?i/(pts.length-1):0)*568,Y=v=>276-(v-a)/(z-a)*252;
  let g='';
  for(let v=a;v<=z;v+=st)g+=`<line x1="56" x2="624" y1="${Y(v)}" y2="${Y(v)}" class="gl${v===0?' z':''}"/><text x="48" y="${Y(v)+4}" text-anchor="end">${v.toLocaleString('fr-FR')} €</text>`;
  const d=pts.map((v,i)=>(i?'L':'M')+X(i).toFixed(1)+' '+Y(v).toFixed(1)).join('');
  $('svg').innerHTML=g+(pts.length>1?`<path d="${d}" class="ln"/>`:`<text x="340" y="150" text-anchor="middle" class="hint">Aucun pari résolu pour l'instant</text>`);
}

const grp=(L,k)=>{const m={};L.forEach(b=>(m[b[k]]=m[b[k]]||[]).push(b));
  const rows=Object.entries(m).map(([n,a])=>{const p=a.reduce((x,b)=>x+pl(b),0),st=a.reduce((x,b)=>x+b.s,0);return{n,c:a.length,w:a.filter(b=>b.r==='won').length/a.length*100,p,r:p/st*100}}).sort((x,y)=>y.p-x.p);
  const cl=v=>v>0?'g':v<0?'l':'';
  return L.length?'<thead><tr><th>'+(k==='sp'?'Sport':'Type')+'</th><th>Paris</th><th>Réussite</th><th>Bénéfice</th><th>ROI</th></tr></thead><tbody>'+rows.map(r=>`<tr><td>${r.n}</td><td>${r.c}</td><td>${pct(r.w)}</td><td class="${cl(r.p)}">${eur(r.p)}</td><td class="${cl(r.p)}">${pct(r.r)}</td></tr>`).join('')+'</tbody>':'<tbody><tr><td>Aucun pari résolu sur la période</td></tr></tbody>'};

function render(){
  const all=[...BETS].sort((a,b)=>a.d.localeCompare(b.d)||a.id-b.id);
  const c0=cut(),bets=all.filter(b=>b.d>=c0&&b.r!=='wd'),done=bets.filter(b=>b.r==='won'||b.r==='lost');
  const profit=bets.reduce((a,b)=>a+pl(b),0),staked=done.reduce((a,b)=>a+b.s,0);
  const wd=all.filter(b=>b.r==='wd').reduce((a,b)=>a+b.s,0),bk=INIT+all.reduce((a,b)=>a+pl(b),0)-wd,wins=done.filter(b=>b.r==='won').length;
  const cells=[['Paris',bets.length],['Bénéfice',eur(profit),profit],['ROI',staked?pct(profit/staked*100):'–',profit],['Progression',INIT?pct(profit/INIT*100):'–',profit],['Réussite',done.length?pct(wins/done.length*100):'–'],['Bankroll',eur(bk)]];
  $('stats').innerHTML=cells.map(c=>`<div class="card"><span>${c[0]}</span><b class="${c[2]>0?'g':c[2]<0?'l':''}">${c[1]}</b></div>`).join('');
  window.BK=bk;
  $('bs').innerHTML=grp(done,'sp');$('bt').innerHTML=grp(done,'ty');
  $('plan').innerHTML=[['FUN',1],['Prudente',5],['Confiance',7],['Maximum',10]].map(p=>`<div><span>${p[0]} (${p[1]} %)</span><b>${eur(bk*p[1]/100)}</b></div>`).join('');
  [...$('per').children].forEach(x=>x.setAttribute('aria-pressed',x.dataset.p===PER));
  chart(bets.filter(b=>b.r!=='pending'));
  $('t').innerHTML='<thead><tr><th>Date</th><th>Sport</th><th>Type</th><th>Mise</th><th>Cote</th><th>Résultat</th><th>Gain</th><th></th></tr></thead><tbody>'+[...all].reverse().map(b=>{const p=pl(b),w=b.r==='wd';
    return `<tr><td>${b.d.slice(8)}/${b.d.slice(5,7)}</td><td>${b.sp}</td><td>${b.ty}</td><td>${eur(b.s)}</td><td>${w?'–':b.o}</td><td>${w?LB[b.r]:`<span class="v">${LB[b.r]}</span><select class="x" data-i="${b.id}" aria-label="Résultat">${['won','lost','void','pending'].map(k=>`<option value="${k}"${k===b.r?' selected':''}>${LB[k]}</option>`).join('')}</select>`}</td><td class="${p>0?'g':p<0?'l':''}">${w||b.r==='pending'?'–':eur(p)}</td><td><button class="x" data-x="${b.id}" aria-label="Supprimer">✕</button></td></tr>`}).join('')+'</tbody>';
  $('initBk').value=INIT;
  renderPendingPicker();
}

function renderPendingPicker(){
  const pending=BETS.filter(b=>b.r==='pending');
  const sel=$('pendingPicker'),prev=sel.value;
  sel.innerHTML='<option value="">— choisir —</option>'+pending.map(b=>`<option value="${b.id}">${b.d.slice(8)}/${b.d.slice(5,7)} · ${b.sp} · ${b.ty} · cote ${b.o}</option>`).join('');
  if(pending.some(b=>String(b.id)===prev))sel.value=prev;
}

async function loadBets(){
  const data=await api('/api/bets');
  BETS=data.bets;
  INIT=data.initial_bankroll;
  render();
}

$('f').addEventListener('submit', async ev=>{
  ev.preventDefault();
  const r=$('r').value,w=r==='wd',btn=$('addBtn');
  if(!w&&!(+$('o').value>1)){$('o').focus();return}
  const payload={d:$('d').value,sp:w?'-':$('sp').value,ty:w?'Retrait':$('ty').value,s:+$('s').value,o:w?0:+$('o').value,r,b:+$('bo').value||0};
  btn.disabled=true;
  try{
    await api('/api/bets',{method:'POST',body:JSON.stringify(payload)});
    await loadBets();
    $('s').value=$('o').value=$('bo').value='';
  }catch(e){$('msg').textContent=e.message}
  btn.disabled=false;
});

$('t').addEventListener('click', async ev=>{
  const x=ev.target.dataset.x;if(!x)return;
  if(!confirm('Supprimer ce pari ?'))return;
  await api('/api/bets/'+x,{method:'DELETE'});
  await loadBets();
});
$('t').addEventListener('change', async ev=>{
  const i=ev.target.dataset.i;if(!i)return;
  await api('/api/bets/'+i,{method:'PATCH',body:JSON.stringify({r:ev.target.value})});
  await loadBets();
});
$('per').addEventListener('click',ev=>{if(ev.target.dataset.p){PER=ev.target.dataset.p;render()}});
$('s').addEventListener('input',()=>{const w=$('warn'),lim=(window.BK||0)*0.1;w.hidden=!(+$('s').value>lim&&$('r').value!=='wd');w.textContent=`Cette mise dépasse 10 % de votre bankroll (maximum conseillé : ${eur(lim)}).`});
$('r').addEventListener('change',()=>$('s').dispatchEvent(new Event('input')));

$('saveInit').onclick=async()=>{
  try{await api('/api/settings',{method:'PATCH',body:JSON.stringify({initial_bankroll:+$('initBk').value})});await loadBets();$('msg').textContent='Bankroll de départ mise à jour.'}
  catch(e){$('msg').textContent=e.message}
};

$('im').onclick=async()=>{
  const o=$('out'),m=$('msg');
  if(o.hidden||!o.value.trim()){o.hidden=false;o.value='';m.textContent='Collez vos données exportées, puis cliquez de nouveau sur Importer.';o.focus();return}
  try{
    const a=JSON.parse(o.value);
    if(!Array.isArray(a))throw 0;
    await api('/api/bets/import',{method:'POST',body:JSON.stringify({bets:a})});
    await loadBets();o.hidden=true;m.textContent='Données importées.'
  }catch(e){m.textContent=e.message||"Données non valides : collez le texte tel qu'il a été exporté."}
};
$('ed').addEventListener('toggle',e=>document.body.classList.toggle('edit',e.target.open));
$('ex').onclick=()=>{const o=$('out');o.hidden=false;o.value=JSON.stringify(BETS);o.select()};
$('rs').onclick=async()=>{
  if(!confirm('Effacer définitivement tous vos paris ? Cette action est irréversible.'))return;
  await api('/api/bets/reset',{method:'POST'});
  await loadBets();
};
$('logout').onclick=async()=>{await api('/api/logout',{method:'POST'});location.href='/login'};

$('d').value=new Date().toISOString().slice(0,10);

$('mainNav').addEventListener('click',ev=>{
  const v=ev.target.dataset.view;if(!v)return;
  [...$('mainNav').children].forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===v));
  $('viewHome').classList.toggle('active',v==='home');
  $('viewBankroll').classList.toggle('active',v==='bankroll');
});

let IS_ADMIN=false;

(async()=>{
  try{
    const me=await api('/api/me');
    $('whoami').textContent=me.username;
    IS_ADMIN=!!me.is_admin;
    $('adminPanel').hidden=!IS_ADMIN;
    await loadBets();
    await loadPicks();
    $('loading').hidden=true;
    $('mainNav').hidden=false;
    $('viewHome').classList.add('active');
    window.__ready=true;
  }catch(e){ /* redirect already handled by api() on 401 */ }
})();

if('serviceWorker' in navigator){navigator.serviceWorker.register('/sw.js').catch(()=>{})}

// ---------- Pronostics (admin + suivi) ----------
const MAX_PICK_BETS=6;
let pickBets=[{match:'',pick:'',odds:''}];
let PICKS=[];

function parseOddsP(str){const n=parseFloat(String(str).replace(',','.').trim());return isNaN(n)?0:n}
function fmtOddsP(n){return n.toFixed(2).replace('.',',')}

function renderPickBets(){
  const list=$('pickBetsList');
  list.innerHTML='';
  pickBets.forEach((bet,idx)=>{
    const item=document.createElement('div');
    item.className='bet-item';
    item.innerHTML=`
      <div class="grid3">
        <label>Match<input type="text" data-pf="match" data-pi="${idx}" value="${bet.match.replace(/"/g,'&quot;')}" placeholder="Équipe A – Équipe B"></label>
        <label>Pari<input type="text" data-pf="pick" data-pi="${idx}" value="${bet.pick.replace(/"/g,'&quot;')}" placeholder="Équipe A gagne"></label>
        <label>Cote<input type="text" inputmode="decimal" data-pf="odds" data-pi="${idx}" value="${bet.odds}" placeholder="1,70"></label>
      </div>
      <button type="button" class="remove-bet" data-premove="${idx}" ${pickBets.length<=1?'disabled':''}>Retirer ce pari</button>
    `;
    list.appendChild(item);
  });
  $('addPickBet').disabled=pickBets.length>=MAX_PICK_BETS;
  updatePickTotal();
}
function updatePickTotal(){
  let total=1;
  pickBets.forEach(b=>{const o=parseOddsP(b.odds);if(o>0)total*=o});
  $('pickTotalOdds').textContent=fmtOddsP(total);
}
{
  $('pickBetsList').addEventListener('input',ev=>{
    const f=ev.target.dataset.pf,i=ev.target.dataset.pi;
    if(!f)return;
    pickBets[i][f]=ev.target.value;
    updatePickTotal();
  });
  $('pickBetsList').addEventListener('click',ev=>{
    const i=ev.target.dataset.premove;
    if(i===undefined)return;
    if(pickBets.length<=1)return;
    pickBets.splice(i,1);
    renderPickBets();
  });
  $('addPickBet').addEventListener('click',()=>{
    if(pickBets.length>=MAX_PICK_BETS)return;
    pickBets.push({match:'',pick:'',odds:''});
    renderPickBets();
  });
  $('pickImage').addEventListener('change',()=>{
    const file=$('pickImage').files[0],prev=$('pickImagePreview');
    if(!file){prev.hidden=true;prev.src='';return}
    prev.src=URL.createObjectURL(file);
    prev.hidden=false;
  });
  $('publishPickBtn').addEventListener('click',async()=>{
    const msg=$('pickMsg');
    const legs=pickBets.filter(b=>b.match||b.pick||b.odds).map(b=>({match:b.match,pick:b.pick,odds:parseOddsP(b.odds)}));
    const imageFile=$('pickImage').files[0];
    if(!legs.length&&!imageFile){msg.textContent='Ajoute au moins un pari ou une image.';return}
    try{
      const fd=new FormData();
      fd.append('title',$('pickTitle').value);
      fd.append('sport',$('pickSport').value);
      fd.append('legs',JSON.stringify(legs));
      if(imageFile)fd.append('image',imageFile);
      const r=await fetch('/api/admin/picks',{method:'POST',credentials:'same-origin',body:fd});
      if(r.status===401){location.href='/login';return}
      const resData=await r.json().catch(()=>({}));
      if(!r.ok)throw new Error(resData.error||'Erreur serveur');
      pickBets=[{match:'',pick:'',odds:''}];
      renderPickBets();
      $('pickImage').value='';
      $('pickImagePreview').hidden=true;
      msg.textContent='Prono publié !';
      await loadPicks();
    }catch(e){msg.textContent=e.message}
  });
}
renderPickBets();

const PICK_LB={pending:'En cours',won:'Gagné',lost:'Perdu',void:'Remboursé'};

async function loadPicks(){
  const data=await api('/api/picks');
  PICKS=data.picks;
  renderPicks();
}

function renderPicks(){
  const el=$('picksList');
  if(!PICKS.length){el.innerHTML='<p class="empty">Aucun prono publié pour l\'instant.</p>';return}
  el.innerHTML=PICKS.map(p=>{
    const legsHtml=p.legs.map(l=>`<div class="pick-leg"><div><div class="m">${l.match}</div><div class="p">${l.pick}</div></div><div class="o">${fmtOddsP(l.odds)}</div></div>`).join('');
    let footHtml;
    if(p.followed){
      footHtml=`<span class="followed-badge">✓ Suivi · mise ${eur(p.follow_stake)}</span>`;
      if(p.result==='pending') footHtml+=`<button type="button" data-unfollow="${p.id}">Ne plus suivre</button>`;
    }else if(p.result==='pending'){
      footHtml=`<div class="follow-form"><input type="number" min="1" step="0.5" value="10" id="stake-${p.id}" aria-label="Mise"><select id="sport-${p.id}" aria-label="Sport">${SPORTS.map(s=>`<option${s===p.sport?' selected':''}>${s}</option>`).join('')}</select><button class="primary" type="button" data-follow="${p.id}">Suivre ce prono</button></div>`;
    }else{
      footHtml='<span class="sub">Ce prono est clos.</span>';
    }
    const adminActions=IS_ADMIN?`<div class="admin-actions">
      <button type="button" data-settle="${p.id}" data-result="won">Gagné</button>
      <button type="button" data-settle="${p.id}" data-result="lost">Perdu</button>
      <button type="button" data-settle="${p.id}" data-result="void">Remboursé</button>
      <button type="button" data-delpick="${p.id}">Supprimer</button>
    </div>`:'';
    const imageHtml=p.image_url?`<img class="pick-image" src="${p.image_url}" alt="Image du prono">`:'';
    const oddsHtml=p.legs.length?`<div class="total-pill"><span>Cote totale</span><b>${fmtOddsP(p.total_odds)}</b></div>`:'';
    return `<div class="pick-card">
      <div class="pick-head">
        <div><h3>${p.title}${p.sport?` <span class="sport-badge">${p.sport}</span>`:''}</h3><p class="sub">Par ${p.author}</p></div>
        <span class="result-badge ${p.result}">${PICK_LB[p.result]}</span>
      </div>
      ${imageHtml}
      <div class="pick-legs">${legsHtml}</div>
      ${oddsHtml}
      <div class="pick-foot">${footHtml}</div>
      ${adminActions}
    </div>`;
  }).join('');
}

$('picksList').addEventListener('click',async ev=>{
  const follow=ev.target.dataset.follow;
  const unfollow=ev.target.dataset.unfollow;
  const settle=ev.target.dataset.settle;
  const del=ev.target.dataset.delpick;
  try{
    if(follow){
      const stake=+$('stake-'+follow).value;
      if(!(stake>0)){alert('Indique une mise valide.');return}
      const sportEl=$('sport-'+follow);
      const sport=sportEl?$('sport-'+follow).value:'Pronostic';
      await api('/api/picks/'+follow+'/follow',{method:'POST',body:JSON.stringify({stake,sport})});
      await loadPicks();await loadBets();
    }else if(unfollow){
      if(!confirm('Retirer ce prono de ta bankroll ?'))return;
      await api('/api/picks/'+unfollow+'/follow',{method:'DELETE'});
      await loadPicks();await loadBets();
    }else if(settle){
      await api('/api/admin/picks/'+settle,{method:'PATCH',body:JSON.stringify({result:ev.target.dataset.result})});
      await loadPicks();await loadBets();
    }else if(del){
      if(!confirm('Supprimer ce prono publié ?'))return;
      await api('/api/admin/picks/'+del,{method:'DELETE'});
      await loadPicks();
    }
  }catch(e){alert(e.message)}
});

// Version de l'application (affichée dans le pied de page)
(function(){
  const v='1.0.1', date='2026-10-12';
  const el=document.getElementById('appVersionDate');
  if(el) el.textContent = 'mise à jour le ' + date;
})();

// Rafraîchit automatiquement les pronos publiés (partage entre comptes)
setInterval(async()=>{
  if(!window.__ready) return;
  try{
    const r=await fetch('/api/picks',{credentials:'same-origin',headers:{'Content-Type':'application/json'}});
    if(r.status===401) return;
    const d=await r.json();
    if(d&&Array.isArray(d.picks)){
      PICKS=data_normalize_picks(d.picks);
      renderPicks();
    }
  }catch(e){/* silencieux */}
}, 20000);

function data_normalize_picks(p){
  return p.map(x=>({...x}));
}

