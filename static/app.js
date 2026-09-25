/* 模拟装配前端（Vue 3，setup() 重写版） */
const { createApp, ref, computed, watch, onMounted, reactive } = Vue;

const API = (p, o) => fetch(p, o).then(async r => { const d = await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.error||r.status); return d; });
const icon = tid => `https://images.evetech.net/types/${tid}/icon?size=32`;

function n(v){ if(v==null||isNaN(v)) return '—'; if(Math.abs(v)>=1e9) return (v/1e9).toFixed(2)+'B'; if(Math.abs(v)>=1e6) return (v/1e6).toFixed(1)+'M'; if(Math.abs(v)>=1e4) return (v/1e4).toFixed(1)+'万'; return String(Math.round(v*10)/10); }
function fmtT(s){ if(!s||s<0) return '—'; return `${String(Math.floor(s/3600)|0).padStart(2,'0')}:${String((Math.floor(s/60)%60)|0).padStart(2,'0')}:${String(Math.floor(s%60)|0).padStart(2,'0')}`; }

createApp({ setup() {
 const lt=ref('hull'), rt=ref('res'), ehp=ref('e');
 const shipTid=ref(null), shipName=ref(''), fitName=ref('');
 const builds=ref([]), sim=ref(null);
 const sq=ref(''), sq2=ref(''), iq=ref('');
 const ships=ref([]), iResults=ref([]);
 const chars=ref([]), charId=ref(null), sk=ref({}), isk=ref('—');
 const fitList=ref([]), esiFits=ref({});
 const eftText=ref(''), saveName=ref('');
 const modShip=ref(false), modEft=ref(false), modSave=ref(false);
 const expanded=reactive({});
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

 const shipGroups=computed(()=>[...new Set(ships.value.map(s=>s.group))].sort((a,b)=>a.localeCompare(b,'zh')));
 const fShips=computed(()=>{ const q=sq.value.trim().toLowerCase(); return q?ships.value.filter(s=>s.name.toLowerCase().includes(q)||(s.name_en||'').toLowerCase().includes(q)):ships.value; });
 const filterShips2=computed(()=>{ const q=sq2.value.trim().toLowerCase(); return q?ships.value.filter(s=>s.name.toLowerCase().includes(q)):ships.value; });
 function shipsByGroup(g){ const q=sq.value.trim().toLowerCase(); return fShips.value.filter(s=>s.group===g); }

 async function j(p,o){ return API(p,o); }

 // 角色
 async function loadChars(){ chars.value=await j('/api/characters'); if(chars.value.length&&!charId.value){ charId.value=chars.value[0].id; await onChar(); } }
 async function onChar(){ sk.value={}; isk.value='—'; esiFits.value={}; if(!charId.value)return; try{sk.value=await j(`/api/characters/${charId.value}/skills`)}catch(e){} try{isk.value=n(await j(`/api/characters/${charId.value}/wallet`).then(d=>d.balance))}catch(e){} try{const f=await j(`/api/characters/${charId.value}/fittings`); const m={}; f.forEach(x=>{m[x.fitting_id]=x}); esiFits.value=m;}catch(e){} if(sim.value)doSim(); }
 function authStart(){ location.href='/api/auth/start?target=fitting'; }

 // 舰船
 onMounted(async()=>{ ships.value=await j('/api/ships'); loadChars(); try{const l=await j('/api/local/fittings');fitList.value=l.map(f=>({k:'l'+f.id,name:f.name,ship:f.ship_name,data:f.eft}));}catch(e){} });
 function pickShip(tid){ shipTid.value=tid; const s=ships.value.find(x=>x.tid===tid); shipName.value=s?s.name:''; fitName.value=''; doSim(); }

 // 搜索
 async function searchItems(){ const q=iq.value.trim(); if(!q)return; const cat=lt.value==='mod'?7:8; iResults.value=await j(`/api/search?q=${encodeURIComponent(q)}&cat=${cat}`); }
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

 return {lt,rt,ehp,shipTid,shipName,fitName,buildList:builds,sim,sq,sq2,iq,ships,iResults,chars,charId,sk,isk,fitList,esiFits,eftText,saveName,modShip,modEft,modSave,expanded,
  hasSkills,res,slots,cap,emp,pct,over,shipGroups,fittingsByShip,fShips,filterShips2,shipsByGroup,
  onChar,authStart,pickShip,searchItems,addItem,rmItem,doSim,doEft,loadFit,saveLocal,saveEsi,icon,n,fmtT};
}}).mount('#app');