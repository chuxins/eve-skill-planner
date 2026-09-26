/* 纯工具函数与 API 封装（无 Vue 依赖；在 app.js 之前加载）
 * 拆出本文件的目的是让「可复用/可单测的纯逻辑」与「Vue 组件状态机」分离，
 * 同时避免单个 app.js 过长；版本号由 webapp.py 注入到 ?v={{ASSET_VERSION}}。 */

// 统一 fetch：非 2xx 时抛出后端 error 字段，便于 UI 直接 alert
const API = (p, o) => fetch(p, o).then(async r => { const d = await r.json().catch(()=>({})); if(!r.ok) throw new Error(d.error||r.status); return d; });
// 物品图标（EVE 图片服务）
const icon = tid => `https://images.evetech.net/types/${tid}/icon?size=32`;

// localStorage 缓存（带 TTL，前缀 spl_）
function cacheGet(k,ttl){ try{ const v=JSON.parse(localStorage.getItem('spl_'+k)); return v&&Date.now()-v.ts<ttl?v.data:null; }catch(e){return null} }
function cacheSet(k,d){ try{ localStorage.setItem('spl_'+k, JSON.stringify({ts:Date.now(),data:d})); }catch(e){} }
function cacheDel(k){ try{ localStorage.removeItem('spl_'+k); }catch(e){} }
// 退出登录后清缓存：传 cid 只清该角色的 sk_/fits_/isk_；不传则清全部角色相关键
function clearCharCache(cid){ const keep=cid?String(cid):null;
 try{ Object.keys(localStorage).filter(k=>k.startsWith('spl_')).forEach(k=>{
  const s=k.slice(4);
  if(/^(sk|fits|isk)_/.test(s)){ if(!keep||s.endsWith('_'+keep)) localStorage.removeItem(k); }
  else if(!keep&&(s==='cid'||s==='cname'||s==='chars')) localStorage.removeItem(k); }); }catch(e){} }

// 数值/时间格式化
function n(v){ if(v==null||isNaN(v)) return '—'; let s=Math.ceil(v*10)/10; if(Math.abs(s)>=1e9) return (s/1e9).toFixed(2)+'B'; if(Math.abs(s)>=1e6) return (s/1e6).toFixed(1)+'M'; if(Math.abs(s)>=1e4) return (s/1e4).toFixed(1)+'万'; return String(Math.ceil(v*10)/10); }
function fmtT(s){ if(!s||s<0) return '—'; return `${String(Math.floor(s/3600)|0).padStart(2,'0')}:${String((Math.floor(s/60)%60)|0).padStart(2,'0')}:${String(Math.floor(s%60)|0).padStart(2,'0')}`; }
// 秒 → 「3天4小时」/「4小时12分」/「12分30秒」；技能训练时长展示用
function fmtDur(s){ if(s==null||isNaN(s)) return '—'; s=Math.max(0,Math.round(s)); const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);
 if(d) return `${d}天${h}小时`; if(h) return `${h}小时${m}分`; if(m) return `${m}分${s%60}秒`; return `${s}秒`; }
// ISO 时间 → 距现在秒数（负数=已过）
function remain(iso){ if(!iso) return null; const t=Date.parse(iso); return isNaN(t)?null:(t-Date.now())/1000; }

// ESI attributes 键 → 中文（技能规划面板）
const ATTR_CN={charisma:'魅力',intelligence:'智力',memory:'记忆',perception:'感知',willpower:'毅力'};
function attrName(k){ return ATTR_CN[k]||k; }
