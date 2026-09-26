/* 退出登录行为验证（无需浏览器/jsdom）：用最小 Vue 桩执行 static/app.js 的 setup()，
 * 断言「退出登录 → 只注销当前角色 → 页头直接变「登录」按钮，不自动切换其它角色」，
 * 并覆盖最容易漏掉的回归：退出后刷新页面不得又自动登录成别的角色。
 * 运行：node tests/logoutflow.js   （tests/test_frontend.py 一并执行）
 */
const fs = require('fs');
const path = require('path');
const vm = require('vm');

const ROOT = path.join(__dirname, '..');
const read = f => fs.readFileSync(path.join(ROOT, 'static', f), 'utf8');

const done = [];
const ok = (cond, msg) => { if (!cond) throw new Error(msg); done.push(msg); };

// ---------- localStorage：以「自有键」形式保存，clearCharCache 的 Object.keys 才能看到 ----------
function makeLS(init) {
  const ls = { ...init };
  ls.getItem = k => (k in ls ? ls[k] : null);
  ls.setItem = (k, v) => { ls[k] = String(v); };
  ls.removeItem = k => { delete ls[k]; };
  return ls;
}
const wrap = (v, ts) => JSON.stringify({ ts: ts || Date.now(), data: v });

// ---------- 后端桩：只认这几个接口，其它（尤其 /api/characters/<cid>/*）一律记录并返回 {} ----------
function makeEnv(state) {
  const calls = [];
  const env = { calls, state, alerts: [], mounted: [] };
  env.fetch = async (url, opt) => {
    const body = opt && opt.body ? JSON.parse(opt.body) : null;
    calls.push({ url, method: (opt && opt.method) || 'GET', body });
    let data = {};
    if (url === '/api/ships') data = [];
    else if (url === '/api/local/fittings') data = [];
    else if (url === '/api/characters') data = state.loggedOut ? [{ id: 222, name: '小号乙' }] : [{ id: 111, name: '小号甲' }, { id: 222, name: '小号乙' }];
    else if (url === '/api/logout') { state.loggedOut = true; data = state.logoutResult; }
    else if (/^\/api\/characters\/\d+\/skills$/.test(url)) data = { Gunnery: 5 };
    else if (/^\/api\/characters\/\d+\/wallet$/.test(url)) data = { balance: 1e8 };
    else if (/^\/api\/characters\/\d+\/fittings$/.test(url)) data = [];
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
      // 像模板/公开实例那样自动解包 ref，便于按「UI 看到的」状态断言
      env.ctx = new Proxy(raw, { get: (t, k) => { const v = t[k]; return v && typeof v === 'object' && 'value' in v ? v.value : v; } });
      return { mount() { return env.ctx; } }; },
  };
  return env;
}

// ---------- 启动一「页」：执行 util.js + app.js，并触发 onMounted ----------
function boot(ls, state, search) {
  const env = makeEnv(state);
  const loc = { href: '', search: search || '', pathname: '/' };
  const sandbox = {
    Vue: env.Vue, localStorage: ls, fetch: env.fetch, location: loc,
    history: { replaceState: () => { env.replaced = true; loc.search = ''; } },
    alert: m => env.alerts.push(m), URLSearchParams, console,
    setTimeout: () => 0, clearTimeout: () => {},            // toast 定时器不实际触发，便于断言
    document: { addEventListener() {}, removeEventListener() {} },
  };
  sandbox.window = sandbox; sandbox.globalThis = sandbox;
  vm.runInContext(read('util.js') + '\n' + read('app.js'), vm.createContext(sandbox), { filename: 'static/app.js' });
  env.run = async () => { for (const f of env.mounted) await f(); };
  return env;
}

(async () => {
  // 初始：已登录 111 小号甲，另有已授权角色 222；含缓存/布局键
  const ls = makeLS({
    spl_cid: wrap(111), spl_cname: wrap('小号甲'), spl_chars: wrap([{ id: 111, name: '小号甲' }, { id: 222, name: '小号乙' }]),
    spl_sk_111: wrap({ Gunnery: 4 }), spl_sk_222: wrap({ Gunnery: 5 }),
    spl_fits_111: wrap([]), spl_isk_111: wrap('1亿'), spl_lw: '360', spl_rw: '355',
  });
  const state = { loggedOut: false, logoutResult: {
    ok: true, removed: [{ id: 111, name: '小号甲', removed: true, revoked: true, note: null }], skipped: [],
    characters: [{ id: 222, name: '小号乙' }] } };

  const p1 = boot(ls, state);
  await p1.run();
  ok(p1.ctx.charId === 111, '初始为已登录状态（页头显示「退出登录」）');

  // —— 点「退出登录」——
  await p1.ctx.logout();
  const out = p1.calls.find(c => c.url === '/api/logout');
  ok(JSON.stringify(out.body) === '{"cid":111}', '只注销当前角色：POST /api/logout {"cid":111}');
  ok(p1.calls.filter(c => c.url === '/api/logout').length === 1, '只发一次注销请求');
  ok(p1.alerts.length === 0, '注销成功不弹错误框');
  ok(p1.ctx.charId === null, '退出后 charId 为空 → 页头显示「登录」按钮（v-if="!charId"）');
  ok(p1.ctx.charName === '', '退出后清空页头角色名');
  ok(p1.ctx.toast === '已退出 小号甲', '轻提示「已退出 小号甲」');
  ok(Object.keys(p1.ctx.sk).length === 0 && p1.ctx.isk === '—' && p1.ctx.plan === null,
     '退出后清空技能/ISK/技能计划等角色态');
  ok(!p1.calls.some(c => /^\/api\/characters\/222\//.test(c.url)), '未自动切换到 222（无任何 222 的数据请求）');
  ok(p1.ctx.chars.map(c => c.id).join() === '222', '服务端其余已授权角色仍保留在列表中，只是未被选中');
  ok(ls.spl_cid === undefined && ls.spl_cname === undefined, '清除缓存的 cid/cname（避免下次访问自动登录）');
  ok(ls.spl_sk_111 === undefined && ls.spl_fits_111 === undefined && ls.spl_isk_111 === undefined, '清除当前角色的 sk/fits/isk 缓存');
  ok(ls.spl_sk_222 !== undefined, '保留其它角色的缓存（未被注销）');
  ok(ls.spl_lw === '360' && ls.spl_rw === '355', '布局缓存（页面宽度）不受影响');

  // —— 刷新页面（回归防线：不得自动登录成 222）——
  const p2 = boot(ls, state);
  await p2.run();
  ok(p2.ctx.charId === null && p2.ctx.charName === '', '退出后刷新仍是未登录态（不会自动选中列表中第一个角色）');
  ok(!p2.calls.some(c => /^\/api\/characters\/\d+\//.test(c.url)), '未登录时不请求任何角色数据');

  // —— 点「登录」重新授权：回调带 ?ok=1&cid=222 → 选中刚授权的角色 ——
  ls.spl_sk_222 = wrap({ Gunnery: 5 });
  const p3 = boot(ls, state, '?ok=1&cid=222');
  await p3.run();
  ok(p3.ctx.charId === 222 && p3.ctx.charName === '小号乙', '重新授权后选中回调里的 ?cid=222（多账号不误选）');
  ok(JSON.parse(ls.spl_cid).data === 222, '登录成功后写回 cid 缓存');
  ok(p3.replaced === true, '消费完回调参数后清掉地址栏 query（刷新不会重复选中）');

  console.log(done.map(m => 'PASS ' + m).join('\n'));
  console.log('\n退出登录行为验证通过（共 ' + done.length + ' 项）');
})().catch(e => { console.error('FAIL ' + e.message); process.exit(1); });
