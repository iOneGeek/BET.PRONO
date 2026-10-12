const NEED=["mainNav","viewHome","viewBankroll","viewProfile","goProfile","picksList","f","t","d"];
const MISSING=NEED.filter(i=>!document.getElementById(i));

function __heal(){
  if(navigator.serviceWorker){navigator.serviceWorker.getRegistrations().then(rs=>rs.forEach(r=>r.unregister())).catch(()=>{});}
  if(window.caches&&caches.keys){caches.keys().then(ks=>ks.forEach(k=>caches.delete(k))).catch(()=>{});}
  setTimeout(()=>location.replace("/app?r="+Date.now()),400);
}

function __fatal(msg){
  const box=document.getElementById("jsError");
  if(box){box.hidden=false;const t=document.getElementById("jsErrMsg");if(t)t.textContent=" "+msg;return;}
  const d=document.createElement("div");
  d.style.cssText="position:fixed;top:8px;left:8px;right:8px;z-index:9999;background:#d1415a;color:#fff;padding:14px 16px;border-radius:12px;font:14px/1.5 system-ui";
  d.innerHTML="<b>Version p\u00e9rim\u00e9e sur ce t\u00e9l\u00e9phone.</b> "+msg+"<br><button style=\"margin-top:8px;background:#fff;color:#d1415a;border:none;border-radius:8px;padding:8px 14px;font-weight:700\">Recharger proprement</button>";
  d.querySelector("button").onclick=()=>location.replace("/app?r="+Date.now());
  document.body?(document.body.prepend(d)):document.addEventListener("DOMContentLoaded",()=>document.body.prepend(d));
}

function nulEl(id){
  const el={id,dataset:{},style:{},children:[],files:[],options:[],value:"",textContent:"",innerHTML:"",hidden:true,disabled:false};
  el.classList={add(){},remove(){},toggle(){},contains(){return false}};
  el.addEventListener=()=>{};el.setAttribute=()=>{};el.removeAttribute=()=>{};el.appendChild=()=>{};
  el.select=()=>{};el.focus=()=>{};el.click=()=>{};el.remove=()=>{};el.getBoundingClientRect=()=>({top:0,left:0,width:0,height:0});
  return el;
}

// Un element manquant ne doit plus jamais casser toute la page (clics morts).
const $=id=>document.getElementById(id)||nulEl(id);
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
  const sel=$('pendingPicker');
  if(!sel) return;                    /* élément absent : rien à rendre */
  const pending=BETS.filter(b=>b.r==='pending');
  const prev=sel.value;
  sel.innerHTML='<option value="">— choisir —</option>'+pending.map(b=>`<option value="${b.id}">${b.d.slice(8)}/${b.d.slice(5,7)} · ${b.sp} · ${b.ty} · cote ${b.o}</option>`).join('');
  if(pending.some(b=>String(b.id)===prev))sel.value=prev;
}

async function loadBets(){
  const data=await api('/api/bets');
  BETS=data.bets;
  INIT=data.initial_bankroll;
  render();
  renderAdvice();
  if(Array.isArray(PICKS)&&PICKS.length&&(!document.activeElement||!document.activeElement.id||!/^stake-|^sport-/.test(document.activeElement.id))) renderPicks();
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
  showView(v);
});

function showView(v){
  [...$('mainNav').children].forEach(b=>b.setAttribute('aria-pressed',b.dataset.view===v));
  $('viewHome').classList.toggle('active',v==='home');
  $('viewBankroll').classList.toggle('active',v==='bankroll');
  $('viewProfile').classList.toggle('active',v==='profile');
}

let IS_ADMIN=false;

// ---------- Profil ----------
$('goProfile').addEventListener('click',()=>showView('profile'));

function loadProfileForm(){
  const me=window.__me;
  if(!me)return;
  $('pfUsername').value=me.username||'';
  $('pfEmail').value=me.email||'';
  $('pfPassword').value='';
  $('pfMsg').textContent='';
}
$('profileForm').addEventListener('submit',async ev=>{
  ev.preventDefault();
  const msg=$('pfMsg');
  const body={};
  const un=$('pfUsername').value.trim(), em=$('pfEmail').value.trim(), pw=$('pfPassword').value;
  if(un&&un!==(window.__me&&window.__me.username))body.username=un;
  if(em&&em!==(window.__me&&window.__me.email))body.email=em;
  if(pw)body.password=pw;
  if(!Object.keys(body).length){msg.textContent='Aucune modification.';return;}
  try{
    const r=await api('/api/profile',{method:'PATCH',body:JSON.stringify(body)});
    if(window.__me)window.__me.username=r.username||window.__me.username;
    $('whoami').textContent=r.username||window.__me.username;
    $('pfPassword').value='';
    msg.textContent='Profil mis à jour ✅';
    loadProfileForm();
  }catch(e){msg.textContent=e.message}
});

(async()=>{
  showView("home");
  $('mainNav').hidden=false;   /* navigable meme si une API echoue ensuite */
  if(MISSING.length){ __fatal("l\u2019interface en cache est p\u00e9rim\u00e9e ("+MISSING.slice(0,3).join(", ")+") \u2014 r\u00e9paration automatique\u2026"); __heal(); return; }
  try{
    const me=await api('/api/me');
    window.__me=me;
    $('whoami').textContent=me.username;
    IS_ADMIN=!!me.is_admin;
    $('adminPanel').hidden=!IS_ADMIN;
    loadProfileForm();
    await loadBets();
    await loadPicks();
    $('mainNav').hidden=false;
    $('viewHome').classList.add('active');
    window.__ready=true;
  }catch(e){ /* redirect already handled by api() on 401 */ }
})();

if('serviceWorker' in navigator){
  navigator.serviceWorker.register('/sw.js',{updateViaCache:'none'})
    .then(reg=>{ if(reg&&reg.update) reg.update(); })
    .catch(()=>{});
  navigator.serviceWorker.addEventListener('controllerchange',()=>{
    if(window.__swHanded) return; window.__swHanded=true;
    location.reload();
  });
}

// ---------- Pronostics (admin + suivi) ----------
const MAX_PICK_BETS=6;
let pickBets=[{home:'',away:'',pick:'',odds:''}];
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
      <div class="match-row">
        <label>Équipe A<input type="text" data-pf="home" data-pi="${idx}" value="${(bet.home||'').replace(/"/g,'&quot;')}" placeholder="Real Madrid"></label>
        <span class="vs">VS</span>
        <label>Équipe B<input type="text" data-pf="away" data-pi="${idx}" value="${(bet.away||'').replace(/"/g,'&quot;')}" placeholder="PSG"></label>
      </div>
      <div class="match-row pick-line">
        <label>Pari<input type="text" data-pf="pick" data-pi="${idx}" value="${(bet.pick||'').replace(/"/g,'&quot;')}" placeholder="Real Madrid gagne"></label>
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
    pickBets.push({home:'',away:'',pick:'',odds:''});
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
    const legs=pickBets
      .filter(b=>(b.match||b.home||b.away||b.pick||b.odds))
      .map(b=>{
        const home=(b.home||'').trim(), away=(b.away||'').trim();
        const match = (home||away) ? (home+' ⚔ '+(away||'—')) : (b.match||'');
        return {match, pick:b.pick, odds:parseOddsP(b.odds)};
      });
    const imageFile=$('pickImage').files[0];
    if(!legs.length&&!imageFile){msg.textContent='Ajoute au moins un pari ou une image.';return}
    try{
      const fd=new FormData();
      fd.append('title',$('pickTitle').value);
      fd.append('sport',$('pickSport').value);
      fd.append('legs',JSON.stringify(legs));
      fd.append('advice_profile', currentProfile || 'prudent');
      const linkVal=($('pickLink').value||'').trim();
      if(linkVal){fd.append('link_url',linkVal);}
      if(imageFile)fd.append('image',imageFile);
      const r=await fetch('/api/admin/picks',{method:'POST',credentials:'same-origin',body:fd});
      if(r.status===401){location.href='/login';return}
      const resData=await r.json().catch(()=>({}));
      if(!r.ok)throw new Error(resData.error||'Erreur serveur');
      pickBets=[{home:'',away:'',pick:'',odds:''}];
      renderPickBets();
      $('pickImage').value='';
      $('pickImagePreview').hidden=true;
      $('pickLink').value='';
      currentProfile='prudent';
      const sel=$('profileSelect');
      if(sel) [...sel.children].forEach(b=>b.setAttribute('aria-pressed',b.dataset.prof==='prudent'));
      renderAdvice();
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

function escAttr(s){return String(s==null?'':s).replace(/&/g,'&amp;').replace(/</g,'&lt;').replace(/>/g,'&gt;').replace(/"/g,'&quot;').replace(/'/g,'&#39;')}
function bookmakerLabel(url){
  try{const h=new URL(url).hostname.replace(/^www\./,'').toLowerCase();
    if(h.includes('winamax'))return'🎯 Placer sur Winamax';
    if(h.includes('betclic'))return'🎯 Placer sur Betclic';
    if(h.includes('unibet'))return'🎯 Placer sur Unibet';
    if(h.includes('vbet'))return'🎯 Placer sur Vbet';
    if(h.includes('zebet'))return'🎯 Placer sur Zebet';
    if(h.includes('pmu'))return'🎯 Placer sur PMU';
    return'🎯 Ouvrir le pari';
  }catch(e){return'🎯 Ouvrir le pari'}
}
const SPORT_ICON={Foot:'⚽',NBA:'🏀',Tennis:'🎾',F1:'🏎️',MMA:'🥊',MLB:'⚾',NFL:'🏈',NHL:'🏒',Mixte:'🎯'};
const TICKET_STATUS={pending:['En cours','⏱'],won:['Gagné','✓'],lost:['Perdu','✕'],void:['Remboursé','↩']};
function renderPicks(){
  const el=$('picksList');
  if(!PICKS.length){el.innerHTML='<p class="empty">Aucun prono publié pour l\'instant.</p>';return}
  const userBk=(window.BK&&window.BK>0)?window.BK:INIT;
  el.innerHTML=PICKS.map(p=>{
    const profKey=(p.advice_profile&&PROFILES[p.advice_profile])?p.advice_profile:'prudent';
    const prof=PROFILES[profKey]||PROFILES.prudent;
    const advisedStake=Math.max(1,+(userBk*prof.pct/100).toFixed(2));
    const linkHtml=p.link_url?`<a class="pick-link" href="${escAttr(p.link_url)}" target="_blank" rel="noopener noreferrer nofollow">${escAttr(bookmakerLabel(p.link_url))} ↗</a>`:'';
    const ball=SPORT_ICON[p.sport]||'🎯';
    const legsHtml=p.legs.map(l=>{
      // Separateur "Equipe A <sep> Equipe B". Le tiret simple est place en
      // premier et echappe : ailleurs il formait une plage Unicode invalide
      // (U+2013 -> U+003D) qui faisait rejeter tout le fichier JS.
      const parts=String(l.match||'').split(/\s*[\-=\u2694\u2013\u2014]\s*|\s+vs\.?\s+/i).map(s=>s.trim()).filter(Boolean);
      const teamsHtml=parts.length>=2
        ? `<span>${parts[0]}</span><span style="color:var(--mute);font-weight:400">vs</span><span>${parts.slice(1).join(' – ')}</span>`
        : `<span>${l.match||''}</span>`;
      return `<div class="ticket-leg">
        <div class="ticket-teams"><span class="ball">${ball}</span>${teamsHtml}</div>
        <div class="ticket-pickline"><span class="lbl">Résultat</span><span class="val">${l.pick}</span><span class="od">${fmtOddsP(l.odds)}</span></div>
      </div>`;
    }).join('');
    let footHtml;
    if(p.followed){
      footHtml=`<span class="followed-badge">✓ Suivi · mise ${eur(p.follow_stake)}</span>`;
      if(p.result==='pending') footHtml+=`<button type="button" data-unfollow="${p.id}">Annule le pari</button>`;
    }else if(p.result==='pending'){
      footHtml=`<div class="follow-form"><input type="number" min="0.5" step="0.5" value="${advisedStake}" id="stake-${p.id}" aria-label="Mise"><select id="sport-${p.id}" aria-label="Sport">${SPORTS.map(s=>`<option value="${s}"${s===p.sport?' selected':''}>${SPORT_ICON[s]||''} ${s}</option>`).join('')}</select><button class="primary" type="button" data-follow="${p.id}">Suivre ce prono</button></div>`;
    }else{
      footHtml='<span class="sub">Ce prono est clos.</span>';
    }
    const adminActions=IS_ADMIN?`<div class="admin-actions">
      <button type="button" data-settle="${p.id}" data-result="won">Gagné</button>
      <button type="button" data-settle="${p.id}" data-result="lost">Perdu</button>
      <button type="button" data-settle="${p.id}" data-result="void">Remboursé</button>
    </div>`:'';
    const imageHtml=p.image_url?`<img class="pick-image" src="${p.image_url}" alt="Image du prono">`:'';
    const stakeForGain=p.followed?p.follow_stake:advisedStake;
    const potentialGain=+(stakeForGain*p.total_odds).toFixed(2);
    const ticketTotalsHtml=p.legs.length?`
      <div class="ticket-row total"><span class="lbl">Cote totale</span><span class="sep"></span><span class="val">${fmtOddsP(p.total_odds)}</span></div>
      <div class="ticket-row"><span class="lbl">Mise${p.followed?'':' (indicative)'}</span><span class="sep"></span><span class="val">${eur(stakeForGain)}</span></div>
      <div class="ticket-gains"><span class="lbl">Gains potentiels</span><span class="val">${eur(potentialGain)}</span></div>`:'';
    const [stLabel,stIcon]=TICKET_STATUS[p.result]||TICKET_STATUS.pending;
    const adviceHtml=`<div class="pick-advice-box">
      <div class="pick-advice-tag"><span>${prof.emoji} Mise conseillée : <b>${prof.label} (${prof.pct} %)</b></span></div>
      <div class="pick-advice-eur">soit <b>${eur(advisedStake)}</b> selon ta bankroll</div>
    </div>`;
    const collapsedClass=p.result==='won'?' won-collapsed':'';
    const delBtn=IS_ADMIN?`<button type="button" class="pick-del" data-delpick="${p.id}" aria-label="Supprimer ce prono" title="Supprimer ce prono">✕</button>`:'';
    return `<div class="pick-card${collapsedClass}" ${p.result==='won'?'data-toggle="1"':''}>
      <div class="pick-head">
        <div><h3>${p.title}${p.sport?` <span class="sport-badge">${p.sport}</span>`:''}</h3><p class="sub">Par ${p.author}</p></div>
        <div class="pick-head-right">${delBtn}<span class="ticket-status ${p.result}"><i>${stIcon}</i>${stLabel}</span></div>
      </div>
      <div class="pick-body">
      ${imageHtml}
      <div class="ticket-legs">${legsHtml}</div>
      ${ticketTotalsHtml}
      ${adviceHtml}
      ${linkHtml}
      <div class="pick-foot">${footHtml}</div>
      ${adminActions}
      </div>
    </div>`;
  }).join('');
}

$('picksList').addEventListener('click',async ev=>{
  const follow=ev.target.dataset.follow;
  const unfollow=ev.target.dataset.unfollow;
  const settle=ev.target.dataset.settle;
  const del=ev.target.dataset.delpick;
  const toggleEl=ev.target.closest('.won-collapsed');
  try{
    if(del){
      if(!confirm('Supprimer ce prono publié ?'))return;
      await api('/api/admin/picks/'+del,{method:'DELETE'});
      await loadPicks();
    }else if(toggleEl){
      toggleEl.classList.toggle('open');
    }else if(follow){
      const stakeEl=$('stake-'+follow);
      const sportEl=$('sport-'+follow);
      if(!stakeEl||!sportEl){alert('Ce prono a été mis à jour, recharge un instant.');return}
      const stake=+stakeEl.value;
      if(!(stake>0)){alert('Indique une mise valide.');return}
      const sport=sportEl.value||'Pronostic';
      await api('/api/picks/'+follow+'/follow',{method:'POST',body:JSON.stringify({stake,sport})});
      await loadPicks();await loadBets();
    }else if(unfollow){
      if(!confirm('Annuler ce pari ? Sa mise sera retirée de ta bankroll.'))return;
      await api('/api/picks/'+unfollow+'/follow',{method:'DELETE'});
      await loadPicks();await loadBets();
    }else if(settle){
      await api('/api/admin/picks/'+settle,{method:'PATCH',body:JSON.stringify({result:ev.target.dataset.result})});
      await loadPicks();await loadBets();
    }
  }catch(e){alert(e.message)}
});

// Version de l'application (affichée dans le pied de page)
(function(){
  const v='1.0.14', date='2026-10-12';
  const el=document.getElementById('appVersionDate');
  if(el) el.textContent = 'v' + v + ' · ' + date;
})();

// Boutons "?" d'aide : affiche/masque le texte d'explication de chaque bloc
document.addEventListener('click', ev=>{
  const btn=ev.target.closest('.info-btn');
  if(!btn) return;
  const key=btn.dataset.help;
  const help=key?document.getElementById('help-'+key):null;
  if(!help) return;
  const hidden=help.hasAttribute('hidden');
  if(hidden) help.removeAttribute('hidden'); else help.setAttribute('hidden','');
});

// Rafraîchit automatiquement les pronos publiés (partage entre comptes)
setInterval(async()=>{
  if(!window.__ready) return;
  // Ne pas écraser le DOM pendant qu'on saisit une mise dans "Suivre ce prono"
  if(document.activeElement && document.activeElement.id && /^stake-|^sport-/.test(document.activeElement.id)) return;
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

// ---------- Mise conseillée (accueil) ----------
const PROFILES={
  fun:{pct:1, emoji:'🎉', label:'Fun',
    text:'Tu joues pour le plaisir, sans prise de tête. Une petite mise de '},
  prudent:{pct:5, emoji:'🛡️', label:'Prudent',
    text:'Une approche responsable qui protège ta bankroll sur la durée. Mise conseillée '},
  confiance:{pct:7, emoji:'🤝', label:'Confiance',
    text:'Tu suis ce prono avec une vraie conviction. Mise '},
  maxi:{pct:10, emoji:'💪', label:'Maxi',
    text:'Gros appétit, gros risque. Ne dépasse jamais ce montant, ta bankroll te remerciera. Mise '}
};
let currentProfile='prudent';
function renderAdvice(){
  const bk=(window.BK&&window.BK>0)?window.BK:INIT;
  const prof=PROFILES[currentProfile];
  const mise=Math.max(1,+(bk*prof.pct/100).toFixed(2));
  const amt=document.getElementById('adviceAmount');
  const txt=document.getElementById('adviceText');
  if(amt) amt.textContent = eur(mise);
  if(txt) txt.textContent = prof.text + eur(mise) + ' (soit ' + prof.pct + ' % de ta bankroll de ' + eur(bk) + ').';
}
function initProfileSelect(){
  const sel=document.getElementById('profileSelect');
  if(!sel || sel.__init) return;
  sel.__init = true;
  sel.addEventListener('click',ev=>{
    const btn=ev.target.closest('button');
    if(!btn) return;
    const k=btn.dataset&&btn.dataset.prof; if(!k||!PROFILES[k])return;
    currentProfile=k;
    [...sel.children].forEach(b=>b.setAttribute('aria-pressed',b.dataset.prof===k));
    renderAdvice();
  });
}
initProfileSelect();
document.addEventListener('DOMContentLoaded', initProfileSelect);
// mise à jour après chaque render de la bankroll
setInterval(()=>{ if(window.__ready) renderAdvice(); }, 1000);

