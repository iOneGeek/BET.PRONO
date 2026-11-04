// A reconciliation patches existing IDs; it never calls the replacement importer.
(()=>{
  const file=document.getElementById('reconcileFile');
  if(!file)return;
  const status=$('reconcileStatus'), preview=$('reconcilePreview');
  const backup=$('reconcileBackup'), apply=$('reconcileApply');
  let plan=null, report=null, generation=0;
  function reset(){plan=null;report=null;preview.replaceChildren();backup.hidden=true;apply.hidden=true;apply.disabled=true;}
  function line(text){const p=document.createElement('p');p.textContent=text;preview.append(p);}
  file.addEventListener('change',async()=>{
    const version=++generation;reset();status.textContent='';
    const selected=file.files[0];if(!selected)return;
    try{
      if(selected.size>240*1024)throw new Error('Fichier trop volumineux (240 Ko maximum).');
      const candidate=JSON.parse(await selected.text());
      if(!candidate||typeof candidate!=='object'||Array.isArray(candidate))throw new Error('Fichier invalide.');
      const result=await api('/api/bets/reconcile',{method:'POST',body:JSON.stringify({...candidate,apply:false})});
      if(version!==generation)return;
      plan=candidate;report=result;
      status.textContent=`${result.updated} corrections et ${result.added} ajouts. Solde calculé : ${eur(result.balance_before)} → ${eur(result.balance_after)}. Aucune modification effectuée.`;
      result.changes.forEach(({before:a,after:b})=>line(`#${a.id} · ${a.d} · ${a.sp} : mise ${eur(a.s)} → ${eur(b.s)} ; crédit ${a.p==null?'calculé avec la cote':eur(a.p)} → ${b.p==null?'calculé avec la cote':eur(b.p)}.`));
      result.additions.forEach(b=>line(`Ajout · ${b.d} · ${b.sp} · ${LB[b.r]} · mise ${eur(b.s)}${b.p==null?'':` · crédit ${eur(b.p)}`}.`));
      backup.hidden=false;apply.hidden=false;
    }catch(error){if(version===generation){reset();status.textContent=error.message;}}
  });
  backup.addEventListener('click',()=>{
    if(!report)return;
    const url=URL.createObjectURL(new Blob([JSON.stringify(report.backup,null,2)],{type:'application/json'}));
    const a=document.createElement('a');a.href=url;a.download='bet-prono-sauvegarde-'+new Date().toISOString().replace(/[:.]/g,'-')+'.json';
    document.body.append(a);a.click();a.remove();setTimeout(()=>URL.revokeObjectURL(url),1000);
    apply.disabled=false;
    status.textContent+=' Sauvegarde proposée au téléchargement : conserve ce fichier avant d’appliquer.';
  });
  apply.addEventListener('click',async()=>{
    if(!plan||!report||apply.disabled)return;
    apply.disabled=true;file.disabled=true;backup.disabled=true;
    try{
      const result=await api('/api/bets/reconcile',{method:'POST',body:JSON.stringify({...plan,apply:true})});
      reset();status.textContent=`Corrections appliquées : ${result.updated} mises à jour, ${result.added} ajouts. Solde calculé : ${eur(result.balance_after)}.`;
      await loadBets();
    }catch(error){reset();status.textContent=error.message+' Recharge le fichier pour vérifier l’état actuel avant toute nouvelle tentative.';}
    finally{file.disabled=false;file.value='';backup.disabled=false;}
  });
})();
