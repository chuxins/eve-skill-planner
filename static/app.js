/* 模拟装配前端（Vue 3，setup() 重写版）
 * 纯工具函数（API/icon/cacheGet/n/fmtT/fmtDur/remain/attrName）见 static/util.js，需先于本文件加载 */
const { createApp, ref, computed, watch, onMounted, reactive } = Vue;

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
 // 技能规划（右栏「技能」标签：需求技能缺口 + 训练时间 + 当前训练队列）
 const plan=ref(null), planErr=ref(''), planLoading=ref(false);
 let planTimer=null;
 // 每门武器的显式弹药选择 {武器 tid: 弹药 tid}；空值=按装填尺寸自动配
 const charges=reactive({});
 function clearCharges(){ Object.keys(charges).forEach(k=>delete charges[k]); }
 // 轻提示（退出登录等操作反馈，4 秒自动消失）
 const toast=ref(''); let toastTimer=null;
 function say(msg){ toast.value=msg; clearTimeout(toastTimer); toastTimer=setTimeout(()=>{toast.value='';},4000); }
 const leftW=ref(parseInt(localStorage.getItem('spl_lw'))||360), rightW=ref(parseInt(localStorage.getItem('spl_rw'))||355);
 const dragL=ref(false), dragR=ref(false); let dragSide=null, dragX=0, dragW0=0;
 const hasSkills=computed(()=>Object.keys(sk.value).length>0);
 const fittingsByShip=computed(()=>{ const m={}; fitList.value.forEach(f=>{ const s=f.ship||''; (m[s]=m[s]||[]).push(f); });
  Object.values(esiFits.value).forEach(f=>{ const s=f.ship||''; (m[s]=m[s]||[]).push({k:'e'+f.fitting_id,name:f.name,ship:f.ship,esi:true,data:f}); });
  return m; });
 const res=computed(()=>sim.value?.resources||{});
 const slots=computed(()=>sim.value?.slots||{high:[],med:[],low:[],rig:[]});
 // 武器 tid → 火力明细（含装填尺寸/当前弹药），高槽行内弹药下拉框用
 const weaponMap=computed(()=>{ const m={}; (sim.value?.firepower?.weapons||[]).forEach(w=>{ m[w.tid]=w; }); return m; });
 // 该武器可选的弹药：后端按 SDE 算出的**全部兼容弹药**（装填尺寸 + 允许弹药组），
 // 不限于货舱/机库已有的；按武器 tid 缓存，避免重复请求
 const ammoMap=ref({}), ammoLoading=reactive({});
 async function loadAmmoFor(tid){ if(tid==null||ammoMap.value[tid]||ammoLoading[tid])return; ammoLoading[tid]=true;
  try{ const list=await j(`/api/weapon/${tid}/charges`); ammoMap.value={...ammoMap.value,[tid]:list}; }
  catch(e){ ammoMap.value={...ammoMap.value,[tid]:[]}; }
  ammoLoading[tid]=false; }
 function loadAmmoAll(){ (sim.value?.firepower?.weapons||[]).forEach(w=>loadAmmoFor(w.tid)); }
 function ammoFor(w){ return (w&&ammoMap.value[w.tid])||[]; }
 // 下拉选项按弹药组（频率晶体/混合弹药/轻型导弹…）分组，便于在同组内比较
 function ammoGroupsFor(w){ const m={}; ammoFor(w).forEach(c=>{ const k=c.group||'其他'; (m[k]=m[k]||[]).push(c); });
  return Object.keys(m).sort((a,b)=>a.localeCompare(b,'zh')).map(k=>({label:k,items:m[k]})); }
 // 货舱里已有的弹药（在选项里标注「货舱」，其余选中后按 SDE 数据算，不需先装进货舱）
 const cargoAmmo=computed(()=>new Set((sim.value?.other?.charge||[]).map(c=>c.tid)));
 function ammoLabel(c){ return c.name+(c.meta_label?`（${c.meta_label}）`:'')+(cargoAmmo.value.has(c.tid)?' · 货舱':''); }
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
 // 角色列表：**不自动选中**任何角色（退出登录后保持未登录态，需用户点「登录」授权）
 async function loadChars(){ chars.value=cacheGet('chars',6e5)||[]; let fresh=false;
  try{chars.value=await j('/api/characters'); cacheSet('chars',chars.value); fresh=true;}catch(e){}
  // 当前角色已不在服务端（token 被删/换设备）→ 回到未登录态；请求失败时不改动
  if(fresh&&charId.value&&!chars.value.some(x=>x.id===charId.value)){ charId.value=null; cacheDel('cid'); cacheDel('cname'); }
  charName.value=charId.value?(cacheGet('cname',864e5)||''):'';
  const c=chars.value.find(x=>x.id===charId.value); if(c)charName.value=c.name;
  if(charId.value) await onChar(); }
 async function onChar(){ sk.value={}; isk.value='—'; esiFits.value={}; if(!charId.value)return; cacheSet('cid',charId.value);
  const c=chars.value.find(x=>x.id===charId.value); if(c){ charName.value=c.name; cacheSet('cname',c.name); }
  const cid=String(charId.value);
  const cached_sk=cacheGet('sk_'+cid,3e5); const cached_fits=cacheGet('fits_'+cid,3e5); const cached_isk=cacheGet('isk_'+cid,6e4);
  if(cached_sk){ sk.value=cached_sk; }else{ try{sk.value=await j(`/api/characters/${charId.value}/skills`); cacheSet('sk_'+cid,sk.value)}catch(e){} }
  if(cached_fits){ const m={}; cached_fits.forEach(x=>m[x.fitting_id]=x); esiFits.value=m; }else{ try{const f=await j(`/api/characters/${charId.value}/fittings`); const m={}; f.forEach(x=>m[x.fitting_id]=x); esiFits.value=m; cacheSet('fits_'+cid,f)}catch(e){} }
  if(cached_isk!=null){ isk.value=cached_isk; }else{ try{isk.value=n(await j(`/api/characters/${charId.value}/wallet`).then(d=>d.balance)); cacheSet('isk_'+cid,isk.value)}catch(e){} }
  if(sim.value)doSim();
  if(rt.value==='skill')loadPlan(); }
 function authStart(){ location.href='/api/auth/start?target=fitting'; }
 // 退出登录：只注销「当前角色」（后端删其 token 并尽力在 EVE 侧吊销）
 // 其它已授权角色的 token 仍留在服务端，但**不自动切换**，页面直接回到未登录态
 async function logout(){ const gone=charId.value; if(!gone) return;
   const goneName=charName.value||String(gone);
   let res; try{ res=await j('/api/logout',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cid:gone})}); }
   catch(e){ alert('退出登录失败：'+e.message); return; }
   const skipped=(res.skipped||[])[0];
   if(skipped){ say(`无法注销 ${skipped.name}：${skipped.note}`); return; }
   clearCharCache(gone);
   chars.value=res.characters||[]; cacheSet('chars',chars.value);   // 仅记录，供将来角色切换用
   charId.value=null; charName.value=''; sk.value={}; isk.value='—'; esiFits.value={};
   plan.value=null; planErr.value=''; clearCharges();
   cacheDel('cid'); cacheDel('cname');
   if(sim.value)doSim(); loadPlan();
   say(`已退出 ${goneName}`); }
 // OAuth 回调带的 ?cid=<刚授权角色>：选中它并清掉 query，避免刷新时重复选中
 function consumeLoginParam(){ const q=new URLSearchParams(location.search); const cid=parseInt(q.get('cid'))||null;
   if(cid){ charId.value=cid; cacheSet('cid',cid); }
   if(cid||q.get('ok')) history.replaceState(null,'',location.pathname); }

 // 技能规划：按当前角色技能算「当前舰船+装配」的需求技能缺口与训练时间
 async function loadPlan(){ if(!charId.value){ plan.value=null; planErr.value=''; return; }
   planLoading.value=true; planErr.value='';
   try{
     if(!shipTid.value){   // 未选舰船：只取训练队列
       const q=await j(`/api/characters/${charId.value}/skillqueue`);
       plan.value={ship:null,attributes:{},attributes_error:null,requirements:[],missing:[],total_seconds:0,queue:q.queue||[],queue_error:q.error||null};
     }else{
       plan.value=await j('/api/skillplan',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({cid:charId.value,ship_tid:shipTid.value,items:builds.value.map(b=>[b.tid,b.qty]),skills:hasSkills.value?sk.value:undefined})});
     }
   }catch(e){ planErr.value=e.message; plan.value=null; }
   planLoading.value=false; }
 function queuePlan(){ clearTimeout(planTimer); planTimer=setTimeout(loadPlan,400); }

 // 拖拽
 function dragStart(s,e){ dragSide=s; dragX=e.clientX; dragW0=s==='l'?leftW.value:rightW.value; if(s==='l')dragL.value=true; else dragR.value=true;
  document.addEventListener('mousemove',dragMove); document.addEventListener('mouseup',dragEnd); }
 function dragMove(e){ if(!dragSide)return; const d=e.clientX-dragX; const w=Math.max(200,Math.min(600,dragW0+(dragSide==='l'?d:-d)));
  if(dragSide==='l')leftW.value=w; else rightW.value=w; }
 function dragEnd(){ dragL.value=dragR.value=false; dragSide=null; localStorage.setItem('spl_lw',leftW.value); localStorage.setItem('spl_rw',rightW.value);
  document.removeEventListener('mousemove',dragMove); document.removeEventListener('mouseup',dragEnd); }

 // 舰船
 onMounted(async()=>{ ships.value=await j('/api/ships'); consumeLoginParam(); loadChars(); try{const l=await j('/api/local/fittings');fitList.value=l.map(f=>({k:'l'+f.id,name:f.name,ship:f.ship_name,data:f.eft}));}catch(e){} });
 watch(lt,v=>{ if(v==='mod'||v==='ammo'){ iq.value=''; slotTab.value=null; ammoTab.value='t1'; searchItems(); } });
 // 切到「技能」标签时按需拉取计划（避免无谓的 ESI 请求）
 watch(rt,v=>{ if(v==='skill')loadPlan(); });
 function pickShip(tid){ shipTid.value=tid; const s=ships.value.find(x=>x.tid===tid); shipName.value=s?s.name:''; fitName.value=''; builds.value=[]; clearCharges(); doSim(); }

 // 搜索
 async function searchItems(){ let ps=[]; const st=slotTab.value; if(lt.value==='ammo'){ps.push('cat=8')}else if(st==='drone'){ps.push('cat=18')}else if(st){ps.push('cat=7');ps.push('slot='+st)}else{ps.push('cat=7,18')} if(!iq.value.trim())ps.push('limit=1000'); iResults.value=await j(`/api/search?q=${encodeURIComponent(iq.value.trim())}`+(ps.length?'&'+ps.join('&'):'')); }
 function setSlotTab(v){ slotTab.value=v; searchItems(); }
 function setAmmoTab(v){ ammoTab.value=v; }
 function setRaceTab(v){ raceTab.value=v; }
 function addItem(r){ const hit=builds.value.find(b=>b.tid===r.tid); if(hit)hit.qty++; else builds.value.push({tid:r.tid,name:r.name,qty:1,pg:r.pg,cpu:r.cpu}); doSim(); }
 function rmItem(it){ builds.value=builds.value.filter(b=>!(b.tid===it.tid&&b.qty===it.qty)); doSim(); }

 // 模拟
 function chargePayload(){ const out={}; Object.keys(charges).forEach(k=>{ if(charges[k])out[k]=charges[k]; }); return out; }
 async function doSim(){ if(!shipTid.value)return; try{
  sim.value=await j('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ship_tid:shipTid.value,items:builds.value.map(b=>[b.tid,b.qty]),skills:sk.value,charges:chargePayload()})});
  builds.value=sim.value.items.map(it=>({tid:it.tid,name:it.name,qty:it.qty}));
  loadAmmoAll();
  if(rt.value==='skill')queuePlan();
 }catch(e){alert(e.message)}}
 async function doEft(){ modEft.value=false; clearCharges(); try{
  const r=await j('/api/eft/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({eft:eftText.value,skills:sk.value})});
  shipTid.value=r.ship.tid; shipName.value=ships.value.find(s=>s.tid===r.ship.tid)?.name||r.ship.name; fitName.value=r.fit_name||''; sim.value=r;
  builds.value=r.items.map(it=>({tid:it.tid,name:it.name,qty:it.qty}));
  loadAmmoAll();
 }catch(e){alert(e.message)} eftText.value=''; }

 // 装配
 async function loadFit(f){
  clearCharges();
  if(f.esi){ shipTid.value=f.data.ship_tid; shipName.value=f.data.ship; fitName.value=f.data.name;
   builds.value=[]; doSimFor(f.data.items.map(it=>[it.tid,it.qty])); return; }
  eftText.value=f.data; await doEft(); }
 async function doSimFor(items){ try{
  sim.value=await j('/api/simulate',{method:'POST',headers:{'Content-Type':'application/json'},body:JSON.stringify({ship_tid:shipTid.value,items,skills:sk.value,charges:chargePayload()})});
  builds.value=sim.value.items.map(it=>({tid:it.tid,name:it.name,qty:it.qty}));
  loadAmmoAll();
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

 return {lt,rt,ehp,shipTid,shipName,fitName,buildList:builds,sim,sq,sq2,iq,ships,iResults,chars,charId,charName,sk,isk,fitList,esiFits,eftText,saveName,slotTab,ammoTab,raceTab,modShip,modEft,modSave,expanded,expandedEq,eqGroups,shownGroups,leftW,rightW,dragL,dragR,plan,planErr,planLoading,charges,weaponMap,ammoFor,ammoMap,ammoLoading,ammoGroupsFor,ammoLabel,
  hasSkills,res,slots,cap,emp,pct,over,shipRaces,shipTree,shownShips,shipCount,fittingsByShip,filterShips2,setRaceTab,
  onChar,authStart,logout,toast,consumeLoginParam,dragStart,pickShip,searchItems,setSlotTab,setAmmoTab,addItem,rmItem,doSim,doEft,loadFit,saveLocal,saveEsi,icon,n,fmtT,fmtDur,remain,attrName,loadPlan};
}}).mount('#app');