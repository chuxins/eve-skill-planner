/* 逐门武器弹药下拉框行为验证（无需浏览器/jsdom）：用最小 Vue 桩执行 static/app.js 的
 * setup()，断言「下拉框列出该武器**全部兼容弹药**（来自 /api/weapon/<tid>/charges），
 * 不只列货舱里已有的；货舱里有的标注『货舱』；选中货舱外的弹药也会发给后端」。
 * 运行：node tests/ammoselect.js   （tests/test_frontend.py 一并执行）
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const read = f => fs.readFileSync(path.join(ROOT, 'static', f), 'utf8');

const done = [];
const ok = (cond, msg) => { if (!cond) throw new Error(msg); done.push(msg); };

const WEAPON = 3520;                       // 重型脉冲激光器 II（装填尺寸 2）
const CARGO_AMMO = 254;                    // 多频晶体 M（装配里已放进货舱）
const PICKED = 20010;                      // 萨沙射频晶体 M（**不在货舱**，只能在列表里选）
const LAUNCHER = 499;                      // 轻型导弹发射器 I（无装填尺寸，只有弹药组 384/394）
const LAUNCHER_AMMO = 210;                 // 鞭挞轻型导弹（同样不在货舱）
const CHARGES = [
  { tid: CARGO_AMMO, name: '多频晶体 M', group: '频率晶体', group_id: 86, meta: 1, meta_label: 'T1', size: 2, damage: [14.0, 0.0, 0.0, 0.0] },
  { tid: PICKED, name: '萨沙射频晶体 M', group: '频率晶体', group_id: 86, meta: 4, meta_label: '势力', size: 2, damage: [18.0, 0.0, 0.0, 0.0] },
  { tid: 247, name: '射频晶体 M', group: '高级脉冲激光晶体', group_id: 375, meta: 2, meta_label: 'T2', size: 2, damage: [8.0, 0.0, 0.0, 0.0] },
];
const LAUNCHER_CHARGES = [
  { tid: LAUNCHER_AMMO, name: '鞭挞轻型导弹', group: '轻型导弹', group_id: 384, meta: 1, meta_label: 'T1', size: null, damage: [0.0, 0.0, 83.0, 0.0] },
  { tid: 211, name: '炼狱轻型导弹', group: '轻型导弹', group_id: 384, meta: 1, meta_label: 'T1', size: null, damage: [0.0, 0.0, 0.0, 83.0] },
  { tid: 27353, name: '古斯塔斯鞭挞轻型导弹', group: '自动锁定轻型导弹', group_id: 394, meta: 4, meta_label: '势力', size: null, damage: [0.0, 0.0, 90.0, 0.0] },
];

// ---------- localStorage / Vue / fetch 桩 ----------
function makeLS(init) {
  const ls = { ...init };
  ls.getItem = k => (k in ls ? ls[k] : null);
  ls.setItem = (k, v) => { ls[k] = String(v); };
  ls.removeItem = k => { delete ls[k]; };
  return ls;
}

function makeEnv() {
  const calls = [];
  const env = { calls, alerts: [], mounted: [] };
  env.fetch = async (url, opt) => {
    const body = opt && opt.body ? JSON.parse(opt.body) : null;
    calls.push({ url, method: (opt && opt.method) || 'GET', body });
    let data = {};
    if (url === '/api/ships') data = [];
    else if (url === '/api/characters') data = [];
    else if (url === '/api/local/fittings') data = [];
    else if (/^\/api\/weapon\/\d+\/charges$/.test(url))
      data = url.includes('/' + LAUNCHER + '/') ? LAUNCHER_CHARGES : CHARGES;
    else if (url === '/api/simulate') data = {
      ship: { tid: 16233, name: '先知级' },
      items: [{ tid: WEAPON, name: '重型脉冲激光器 II', qty: 1, slot: 'high', attrs: {} },
              { tid: LAUNCHER, name: '轻型导弹发射器 I', qty: 2, slot: 'high', attrs: {} }],
      slots: { high: [{ tid: WEAPON, name: '重型脉冲激光器 II', qty: 1, slot: 'high', attrs: {} },
                      { tid: LAUNCHER, name: '轻型导弹发射器 I', qty: 2, slot: 'high', attrs: {} }],
               med: [], low: [], rig: [], sub: [] },
      other: { charge: [{ tid: CARGO_AMMO, name: '多频晶体 M', qty: 100, attrs: { 128: 2 } }], drone: [], implant: [], booster: [], cargo: [] },
      resources: {},
      firepower: { weapons: [
        { tid: WEAPON, name: '重型脉冲激光器 II', qty: 1, charge: '多频晶体 M', charge_tid: CARGO_AMMO, charge_size: 2, explicit_charge: false },
        { tid: LAUNCHER, name: '轻型导弹发射器 I', qty: 2, charge: null, charge_tid: null, charge_size: null, explicit_charge: false },
      ] },
    };
    return { ok: true, status: 200, json: async () => data };
  };
  env.Vue = {
    ref: v => ({ value: v }),
    reactive: o => o,
    computed: f => ({ get value() { return f(); } }),
    watch: () => {},
    nextTick: f => Promise.resolve().then(f),
    onMounted: f => env.mounted.push(f),
    createApp: o => { const raw = o.setup(); env.raw = raw;
      env.ctx = new Proxy(raw, { get: (t, k) => { const v = t[k]; return v && typeof v === 'object' && 'value' in v ? v.value : v; } });
      return { mount() { return env.ctx; } }; },
  };
  return env;
}

(async () => {
  const env = makeEnv();
  const loc = { href: '', search: '', pathname: '/' };
  const sandbox = {
    Vue: env.Vue, localStorage: makeLS({}), fetch: env.fetch, location: loc,
    history: { replaceState: () => {} }, alert: m => env.alerts.push(m), URLSearchParams, console,
    setTimeout: () => 0, clearTimeout: () => {},
    document: { addEventListener() {}, removeEventListener() {} },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  vm.runInContext(read('util.js') + '\n' + read('app.js'), vm.createContext(sandbox), { filename: 'static/app.js' });
  for (const f of env.mounted) await f();

  // 模拟一次装配（1 门脉冲激光器 + 货舱里的多频晶体 M）
  env.raw.shipTid.value = 16233;
  env.raw.buildList.value = [{ tid: WEAPON, name: '重型脉冲激光器 II', qty: 1 }, { tid: CARGO_AMMO, name: '多频晶体 M', qty: 100 }];
  await env.raw.doSim();
  await new Promise(r => setImmediate(r));         // 等 loadAmmoAll 的请求落地

  ok(env.calls.some(c => c.url === `/api/weapon/${WEAPON}/charges`),
    '模拟后请求了 /api/weapon/<武器tid>/charges（该武器全部兼容弹药）');
  const w = env.raw.weaponMap.value[WEAPON];
  const list = env.raw.ammoFor(w);
  ok(list.length === CHARGES.length, `下拉框列出全部兼容弹药（${list.length}/${CHARGES.length}）`);
  ok(list.some(c => c.tid === CARGO_AMMO) && list.some(c => c.tid === PICKED),
    '货舱里没有的弹药（萨沙射频晶体 M）同样在列表里');
  const groups = env.raw.ammoGroupsFor(w).map(g => g.label);
  ok(groups.includes('频率晶体') && groups.includes('高级脉冲激光晶体'),
    '按弹药组分组：' + groups.join(' / '));
  const label = env.raw.ammoLabel(list.find(c => c.tid === CARGO_AMMO));
  ok(/货舱/.test(label) && /T1/.test(label), '货舱里已有的弹药标注「货舱」与 T1：' + label);
  ok(!/货舱/.test(env.raw.ammoLabel(list.find(c => c.tid === PICKED))), '货舱外的弹药不标注「货舱」');

  // 发射架（无装填尺寸，只有弹药组 384/394）同样出现在火力面板 → 同样有行内下拉框
  ok(env.calls.some(c => c.url === `/api/weapon/${LAUNCHER}/charges`),
    '发射架也请求了自己的全部兼容弹药表（无装填尺寸 → 只按弹药组匹配）');
  const lw = env.raw.weaponMap.value[LAUNCHER];
  ok(!!lw, '发射架出现在火力明细里（否则行内不会有下拉框）');
  ok(env.raw.ammoFor(lw).length === LAUNCHER_CHARGES.length,
    `发射架下拉框列出全部兼容导弹（${env.raw.ammoFor(lw).length}/${LAUNCHER_CHARGES.length}）`);
  const lg = env.raw.ammoGroupsFor(lw).map(g => g.label);
  ok(lg.includes('轻型导弹') && lg.includes('自动锁定轻型导弹'), '发射架弹药按弹药组分组：' + lg.join(' / '));
  ok(lw.charge === null, '发射架未配到弹药时 charge 为 null（模板据此提示「无弹药」）');

  // 选中货舱外的弹药 → 必须原样发给后端（引擎按 SDE 数据算伤害）
  env.raw.charges[WEAPON] = PICKED;
  await env.raw.doSim();
  const post = env.calls.filter(c => c.url === '/api/simulate').pop();
  ok(post.body.charges[WEAPON] === PICKED, '选中货舱外的弹药也会提交给后端：' + JSON.stringify(post.body.charges));
  ok(env.calls.filter(c => c.url === `/api/weapon/${WEAPON}/charges`).length === 1,
    '弹药表按武器缓存，重复模拟不重复请求');
  env.raw.charges[LAUNCHER] = LAUNCHER_AMMO;
  await env.raw.doSim();
  const post2 = env.calls.filter(c => c.url === '/api/simulate').pop();
  ok(post2.body.charges[LAUNCHER] === LAUNCHER_AMMO, '发射架选中的导弹同样提交给后端');
  ok(env.calls.filter(c => c.url === `/api/weapon/${LAUNCHER}/charges`).length === 1,
    '发射架弹药表同样按武器缓存');

  console.log('PASS ' + done.length + ' 项：' + done.join('\n     '));
  console.log('\n弹药下拉框行为验证通过（共 ' + done.length + ' 项）');
})().catch(err => { console.error('FAIL ' + err.message); process.exit(1); });
