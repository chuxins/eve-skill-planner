/* 模拟装配前端（Vue 3，setup() 重写版） */
const { createApp, ref, computed, watch, onMounted, reactive } = Vue;

const API = (p, o) => fetch(p, o).then(async r => { const d = await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.error||r.status); return d; });
const icon = tid => `https://images.evetech.net/types/${tid}/icon?size=32`;

function cacheGet(k,ttl){ try{ const v=JSON.parse(localStorage.getItem('spl_'+k)); return v&&Date.now()-v.ts<ttl?v.data:null; }catch(e){return null} }
function cacheSet(k,d){ try{ localStorage.setItem('spl_'+k, JSON.stringify({ts:Date.now(),data:d})); }catch(e){} }

function n(v){ if(v==null||isNaN(v)) return '—'; let s=Math.ceil(v*10)/10; if(Math.abs(s)>=1e9) return (s/1e9).toFixed(2)+'B'; if(Math.abs(s)>=1e6) return (s/1e6).toFixed(1)+'M'; if(Math.abs(s)>=1e4) return (s/1e4).toFixed(1)+'万'; return String(Math.ceil(v*10)/10); }
function fmtT(s){ if(!s||s<0) return '—'; return `${String(Math.floor(s/3600)|0).padStart(2,'0')}:${String((Math.floor(s/60)%60)|0).padStart(2,'0')}:${String(Math.floor(s%60)|0).padStart(2,'0')}`; }

createApp({ setup() {
 const lt=ref('hull'), rt=ref('res'), ehp=ref('e');
 const shipTid=ref(null), shipName=ref(''), fitName=ref('');
 const builds=ref([]), sim=ref(null);
 const sq=ref(''), sq2=ref(''), iq=ref('');
 const ships=ref([]), iResults=ref([]);
 const chars=ref(cacheGet('chars',6e5)||[]), charId=ref(cacheGet('cid',864e5)||null), charName=ref(cacheGet('cname',864e5)||''), sk=ref({}), isk=ref(cacheGet('isk_'+String(cacheGet('cid',864e5)||0),6e4)||'—');
 const fitList=ref([]), esiFits=ref({});
 const eftText=ref(''), saveName=ref('');
 const slotTab=ref(null), ammoTab=ref('t1'), raceTab=ref(null);
 const modShip=ref(false), modEft=ref(false), modSave=ref(false);
 const expanded=reactive({});
 const leftW=ref(parseInt(localStorage.getItem('spl_lw'))||360), rightW=ref(parseInt(localStorage.getItem('spl_rw'))||355);
 const dragL=ref(false), dragR=ref(false); let dragSide=null, dragX=0, dragW0=0;
 const hasSkills=computed(()=>Object.keys(sk.value).length>0);
 const fittingsByShip=computed(()=>{ const m={}; fitList.value.forEach(f=>{ const s=f.ship||''; (m[s]=m[s]||[]).push(f); });
  Object.values(esiFits.value).forEach(f=>{ const s=f.ship||''; (m[s]=m[s]||[]).push({k:'e'+f.fitting_id,name:f.name,ship:f.ship,esi:true,data:f}); });
  return m; });
 const res=computed(()=>sim.value?.resources||{});
 const slots=computed(()=>sim.value?.slots||{high:[],med:[],low:[],rig:[]});
 const cap=s=>sim.value?.resources?.slots_cap?.[s]||0;
 const emp=s=>Math.max(0,cap(s)-slots.value[s].length);
 const pct=r=>r?.cap?Math.min(100,r.used/r.cap*100):0;
 const over=k=>res.value[k]?.used>res.value[k]?.cap?'over':'';

 // 舰船：舰种 → 种族 → 舰船（两级分组，逻辑同装备标签）
 const RACE_ORDER=['艾玛','加达里','盖伦特','米玛塔尔'];
 const shipRaces=computed(()=>{ const s=new Set(ships.value.map(x=>x.race||'其他'));
  return [...RACE_ORDER.filter(r=>s.has(r)), ...[...s].filter(r=>!RACE_ORDER.includes(r)).sort((a,b)=>a.localeCompare(b,'zh'))]; });
 const shipTree=computed(()=>{ const q=sq.value.trim().toLowerCase();
  const list=q?ships.value.filter(s=>s.name.toLowerCase().includes(q)||(s.name_en||'').toLowerCase().includes(q)):ships.value;
  const gm={}; list.forEach(s=>{ const g=s.group||'其他', r=s.race||'其他'; const sub=(gm[g]=gm[g]||{})[r]||(gm[g][r]=[]); sub.push(s); });
  return Object.keys(gm).sort((a,b)=>a.localeCompare(b,'zh')).map(g=>{ const rm=gm[g];
   const subs=shipRaces.value.filter(r=>rm[r]).map(r=>({key:r,items:rm[r]}));
   return {key:g,count:subs.reduce((n,s)=>n+s.items.length,0),subs}; }); });
 const shownShips=computed(()=>{ const t=raceTab.value; if(!t||t==='all') return shipTree.value;
  return shipTree.value.map(g=>{ const subs=g.subs.filter(s=>s.key===t);
   return subs.length?{key:g.key,count:subs.reduce((n,s)=>n+s.items.length,0),subs}:null; }).filter(Boolean); });
 const shipCount=computed(()=>shownShips.value.reduce((n,g)=>n+g.count,0));
 const filterShips2=computed(()=>{ const q=sq2.value.trim().toLowerCase(); return q?ships.value.filter(s=>s.name.toLowerCase().includes(q)):ships.value; });
 const expandedEq=reactive({});
 const eqGroups=computed(()=>{ const m={}; const kf=lt.value==='ammo'?'family':'group'; iResults.value.forEach(r=>{ const k=r[kf]||'其他'; (m[k]=m[k]||[]).push(r); }); return Object.keys(m).sort((a,b)=>a.localeCompare(b,'zh')).map(k=>{ const items=m[k]; let subs=null; if(lt.value==='ammo'){ const sm={}; items.forEach(r=>{ const sg=r.group||'其他'; (sm[sg]=sm[sg]||[]).push(r); }); subs={}; Object.keys(sm).sort((a,b)=>a.localeCompare(b,'zh')).forEach(sk=>subs[sk]=sm[sk]); } return {key:k,items,subs}; }); });
 const shownGroups=computed(()=>{ if(lt.value!=='ammo'||!ammoTab.value||ammoTab.value==='all') return eqGroups.value; const meta=ammoTab.value==='t1'?1:ammoTab.value==='t2'?2:4; return eqGroups.value.map(g=>({key:g.key,items:g.items.filter(r=>r.meta===meta),subs:g.subs?Object.fromEntries(Object.entries(g.subs).map(([k,v])=>[k,v.filter(r=>r.meta===meta)]).filter(([,v])=>v.length)):null})).filter(g=>g.items.length); });

 async function j(p,o){ return API(p,o); }

 // 角色
 async function loadChars(){ chars.value=cacheGet('chars',6e5)||[]; try{chars.value=await j('/api/characters'); cacheSet('chars',chars.value)}catch(e){} let cid=charId.value; if(!cid){ cid=cacheGet('cid',864e5)||(chars.value[0]?.id||null); if(cid) charId.value=cid; } charName.value=cacheGet('cname',864e5)||''; const c=chars.value.find(x=>x.id===cid); if(c)charName.value=c.name; if(cid) await onChar(); }
 async function onChar(){ sk.value={}; isk.value='—'; esiFits.value={}; if(!charId.value)return; cacheSet('cid',charId.value);
  const c=chars.value.find(x=>x.id===charId.value); if(c){ charName.value=c.name; cacheSet('cname',c.name); }
  const cid=String(charId.value);
  const cached_sk=cacheGet('sk_'+cid,3e5); const cached_fits=cacheGet('fits_'+cid,3e5); const cached_isk=cacheGet('isk_'+cid,6e4);
  if(cached_sk){ sk.value=cached_sk; }else{ try{sk.value=await j(`/api/characters/${charId.value}/skills`); cacheSet('sk_'+cid,sk.value)}catch(e){} }
  if(cached_fits){ const m={}; cached_fits.forEach(x=>m[x.fitting_id]=x); esiFits.value=m; }else{ try{const f=await j(`/api/characters/${charId.value}/fittings`); const m={}; f.forEach(x=>m[x.fitting_id]=x); esiFits.value=m; cacheSet('fits_'+cid,f)}catch(e){} }
  if(cached_isk!=null){ isk.value=cached_isk; }else{ try{isk.value=n(await j(`/api/characters/${charId.value}/wallet`).then(d=>d.balance)); cacheSet('isk_'+cid,isk.value)}catch(e){} }
  if(sim.value)doSim(); }
 function authStart(){ location.href='/api/auth/start?target=fitting'; }

 // 拖拽
 function dragStart(s,e){ dragSide=s; dragX=e.clientX; dragW0=s==='l'?leftW.value:rightW.value; if(s==='l')dragL.value=true; else dragR.value=true;
  document.addEventListener('mousemove',dragMove); document.addEventListener('mouseup',dragEnd); }
 function dragMove(e){ if(!dragSide)return; const d=e.clientX-dragX; const w=Math.max(200,Math.min(600,dragW0+(dragSide==='l'?d:-d)));
  if(dragSide==='l')leftW.value=w; else rightW.value=w; }
 function dragEnd(){ dragL.value=dragR.value=false; dragSide=null; localStorage.setItem('spl_lw',leftW.value); localStorage.setItem('spl_rw',rightW.value);
  document.removeEventListener('mousemove',dragMove); document.removeEventListener('mouseup',dragEnd); }

 // 舰船
 onMounted(async()=>{ ships.value=await j('/api/ships'); loadChars(); try{const l=await j('/api/local/fittings');fitList.value=l.map(f=>({k:'l'+f.id,name:f.name,ship:f.ship_name,data:f.eft}));}catch(e){} });
 watch(lt,v=>{ if(v==='mod'||v==='ammo'){ iq.value=''; slotTab.value=null; ammoTab.value='t1'; searchItems(); } });
 function pickShip(tid){ shipTid.value=tid; const s=ships.value.find(x=>x.tid===tid); shipName.value=s?s.name:''; fitName.value=''; builds.value=[]; doSim(); }

 // 搜索
 async function searchItems(){ let ps=[]; const st=slotTab.value; if(lt.value==='ammo'){ps.push('cat=8')}else if(st==='drone'){ps.push('cat=18')}else if(st){ps.push('cat=7');ps.push('slot='+st)}else{ps.push('cat=7,18')} if(!iq.value.trim())ps.push('limit=1000'); iResults.value=await j(`/api/search?q=${encodeURIComponent(iq.value.trim())}`+(ps.length?'&'+ps.join('&'):'')); }
 function setSlotTab(v){ slotTab.value=v; searchItems(); }
 function setAmmoTab(v){ ammoTab.value=v; }
 function setRaceTab(v){ raceTab.value=v; }
 function addItem(r){ const hit=builds.value.find(b=>b.tid===r.tid); if(hit)hit.qty++; else builds.value.push({tid:r.tid,name:r.name,qty:1,pg:r.pg,cpu:r.cpu}); doSim(); }
 function rmItem(it){ builds.value=builds.value.filter(b=>!(b.tid===it.tid&&b.qty===it.qty)); doSim(); }

 // 模拟
 async function doSim(){ if(!shipTid.value)return; try{
  sim.value=await j('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ship_tid:shipTid.value,items:builds.value.map(b=>[b.tid,b.qty]),skills:sk.value})});
  builds.value=sim.value.items.map(it=>({tid:it.tid,name:it.name,qty:it.qty}));
 }catch(e){alert(e.message)}}
 async function doEft(){ modEft.value=false; try{
  const r=await j('/api/eft/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({eft:eftText.value,skills:sk.value})});
  shipTid.value=r.ship.tid; shipName.value=ships.value.find(s=>s.tid===r.ship.tid)?.name||r.ship.name; fitName.value=r.fit_name||''; sim.value=r;
  builds.value=r.items.map(it=>({tid:it.tid,name:it.name,qty:it.qty}));
 }catch(e){alert(e.message)} eftText.value=''; }

 // 装配
 async function loadFit(f){
  if(f.esi){ shipTid.value=f.data.ship_tid; shipName.value=f.data.ship; fitName.value=f.data.name;
   builds.value=[]; doSimFor(f.data.items.map(it=>[it.tid,it.qty])); return; }
  eftText.value=f.data; await doEft(); }
 async function doSimFor(items){ try{
  sim.value=await j('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ship_tid:shipTid.value,items,skills:sk.value})});
  builds.value=sim.value.items.map(it=>({tid:it.tid,name:it.name,qty:it.qty}));
 }catch(e){alert(e.message)}}

 // 保存
 function eftOut(){ if(!sim.value)return''; const lines=sim.value.items.map(it=>it.qty>1?`${it.name} x${it.qty}`:it.name); return `[${sim.value.ship.name}, ${fitName.value||'未命名'}]\n${lines.join('\n')}`; }
 async function saveLocal(){ const nm=saveName.value.trim()||fitName.value||'未命名'; const e=eftOut(); if(!e)return; await j('/api/local/fittings',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:nm,eft:e,ship_name:sim.value.ship.name})}); modSave.value=false; }
 async function saveEsi(){ if(!charId.value||!sim.value)return;
  const flagOrder=['hiSlot','medSlot','loSlot','rigSlot']; const items=[];
  for(const it of sim.value.items){ const sidx=it.slot?slots.value[it.slot]?.findIndex(x=>x.tid===it.tid&&x.qty===it.qty):-1;
   const flag=it.slot&&sidx>=0?`${flagOrder[['high','med','low','rig'].indexOf(it.slot)]}${sidx}`:'cargo';
   items.push({type_id:it.tid,quantity:it.qty,flag}); }
  try{await j(`/api/characters/${charId.value}/fittings/save`,{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({name:saveName.value.trim()||'模拟装配',items,ship_tid:sim.value.ship.tid})}); modSave.value=false; alert('已保存');}
  catch(e){alert('保存失败: '+e.message)}}

 return {lt,rt,ehp,shipTid,shipName,fitName,buildList:builds,sim,sq,sq2,iq,ships,iResults,chars,charId,charName,sk,isk,fitList,esiFits,eftText,saveName,slotTab,ammoTab,raceTab,modShip,modEft,modSave,expanded,expandedEq,eqGroups,shownGroups,leftW,rightW,dragL,dragR,
  hasSkills,res,slots,cap,emp,pct,over,shipRaces,shipTree,shownShips,shipCount,fittingsByShip,filterShips2,setRaceTab,
  onChar,authStart,dragStart,pickShip,searchItems,setSlotTab,setAmmoTab,addItem,rmItem,doSim,doEft,loadFit,saveLocal,saveEsi,icon,n,fmtT};
}}).mount('#app');