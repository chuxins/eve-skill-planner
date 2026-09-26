/* 前端静态检查（Node 下运行，无需浏览器 / 无构建步骤）：
 *   1) static/util.js、static/app.js 语法可解析
 *   2) index.html 的 Vue 模板可编译（能抓出标签不闭合、v-else/v-else-if 断链等）
 *   3) index.html 的静态资源引用带自动版本占位 {{ASSET_VERSION}}（无硬编码 ?v=数字）
 * 用法：node tests/check_frontend.js   （退出码非 0 即失败）
 */
const fs = require('fs');
const vm = require('vm');
const path = require('path');

const STATIC = path.join(__dirname, '..', 'static');
const failures = [];

function check(name, fn) {
  try {
    fn();
    console.log('PASS ' + name);
  } catch (err) {
    failures.push(name + ': ' + err.message);
    console.log('FAIL ' + name + ': ' + err.message);
  }
}

const read = f => fs.readFileSync(path.join(STATIC, f), 'utf8');

for (const f of ['util.js', 'app.js']) {
  check('语法 ' + f, () => new vm.Script(read(f), { filename: f }));
}

check('Vue 模板可编译', () => {
  vm.runInThisContext(read('vendor/vue.global.prod.js'), { filename: 'vue.global.prod.js' });
  if (typeof Vue === 'undefined' || !Vue.compile) throw new Error('Vue 编译器不可用');
  const html = read('index.html');
  const tpl = html.slice(html.indexOf('<div id="app">'), html.lastIndexOf('</div>'));
  if (tpl.length < 1000) throw new Error('未取到 #app 模板');
  // decodeEntities 直通，避免依赖浏览器 DOM
  const out = Vue.compile(tpl, { decodeEntities: s => s, onError: e => { throw e; } });
  if (typeof out !== 'function' && !(out && typeof out.render === 'function'))
    throw new Error('编译未产出 render');
});

check('静态资源带自动版本占位', () => {
  const html = read('index.html');
  for (const f of ['util.js', 'app.js'])
    if (!html.includes('/static/' + f + '?v={{ASSET_VERSION}}'))
      throw new Error(f + ' 未使用 {{ASSET_VERSION}}');
  if (!/favicon\.svg\?v=\{\{ASSET_VERSION\}\}/.test(html))
    throw new Error('favicon 未使用 {{ASSET_VERSION}}');
  if (/\.js\?v=\d/.test(html)) throw new Error('仍有硬编码的 ?v=数字');
});

check('退出登录按钮接线完整', () => {
  const html = read('index.html'), app = read('app.js');
  if (!/@click="logout"/.test(html)) throw new Error('index.html 缺少「退出登录」按钮');
  if (!/v-if="charId"[^>]*>退出登录|退出登录<\/button>/.test(html))
    throw new Error('「退出登录」按钮未按登录态显示');
  if (!/body:JSON\.stringify\(\{cid:/.test(app))
    throw new Error('logout 未指定当前角色（应传 cid）');
  if (/\{all:\s*true\}/.test(app))
    throw new Error('logout 不应注销全部角色（用户要求只注销当前账号）');
  if (/\{\{toast\}\}/.test(html) && !/[,\s{]toast[,\s}]/.test(app.slice(app.lastIndexOf('return {'))))
    throw new Error('模板用到 {{toast}} 但 setup() 未返回 toast');
});

check('模板事件处理器均在 setup() 返回', () => {
  // 抓 @click/@change/... 里的方法名，确认都出现在 return {...} 中
  // （否则运行时 template 调用 undefined，且不会在语法/编译期暴露）
  const html = read('index.html'), app = read('app.js');
  const names = new Set();
  for (const m of html.matchAll(/@[\w.]+(?:\.\w+)*="([A-Za-z_$][\w$]*)\s*\(?/g)) names.add(m[1]);
  const ret = app.slice(app.lastIndexOf('return {'));
  const missing = [...names].filter(h => !new RegExp('[,\\s{]' + h + '[,\\s}(]').test(ret));
  if (missing.length) throw new Error('未在 setup() 返回：' + missing.join(', '));
  console.log('  模板处理器 ' + names.size + ' 个：' + [...names].join(', '));
});

// 模拟浏览器 Storage：键是「自身的可枚举属性」，方法在原型/目标上（Object.keys 只返回键）
function makeStorage(init) {
  const data = Object.assign({}, init);
  const api = {
    getItem: k => (k in data ? data[k] : null),
    setItem: (k, v) => { data[k] = String(v); },
    removeItem: k => { delete data[k]; },
    clear: () => { Object.keys(data).forEach(k => { delete data[k]; }); },
  };
  return new Proxy(api, {
    get: (t, k) => (k in t ? t[k] : (k in data ? data[k] : undefined)),
    set: (t, k, v) => { data[k] = String(v); return true; },
    deleteProperty: (t, k) => { delete data[k]; return true; },
    ownKeys: () => Object.keys(data),
    getOwnPropertyDescriptor: (t, k) => (k in data
      ? { value: data[k], enumerable: true, configurable: true } : undefined),
  });
}

check('clearCharCache 只清角色缓存', () => {
  const ls = makeStorage({ spl_cid: '1', spl_cname: '甲', spl_chars: '[]', spl_sk_1: '{}',
    spl_fits_1: '[]', spl_isk_1: '1', spl_lw: '360', other: 'x' });
  vm.runInNewContext(read('util.js') + '\nclearCharCache();', { localStorage: ls, window: {} });
  const left = Object.keys(ls).sort().join(',');
  if (left !== 'other,spl_lw') throw new Error('剩余键异常：' + left);
  if (ls.getItem('spl_lw') !== '360') throw new Error('布局缓存被误删');
});

check('clearCharCache(cid) 不影响其它角色', () => {
  const ls = makeStorage({ spl_sk_1: 'a', spl_fits_1: 'b', spl_isk_1: 'c',
    spl_cid: '2', spl_sk_2: 'd', spl_fits_2: 'e', spl_isk_2: 'f', spl_lw: '360' });
  vm.runInNewContext(read('util.js') + '\nclearCharCache(1);', { localStorage: ls, window: {} });
  const left = Object.keys(ls).sort().join(',');
  if (left !== 'spl_cid,spl_fits_2,spl_isk_2,spl_lw,spl_sk_2')
    throw new Error('剩余键异常（应保留角色 2 与当前 cid）：' + left);
});

// 取 app.js 内某个函数的源码（到下一个函数定义或顶层注释为止）
function fnBody(name) {
  const app = read('app.js');
  const m = new RegExp('\\n (?:async )?function ' + name + '\\b').exec(app);
  if (!m) throw new Error('未找到函数 ' + name);
  const rest = app.slice(m.index + 1);
  const nxt = rest.search(/\n (?:async )?function |\n \/\//);
  return rest.slice(0, nxt < 0 ? rest.length : nxt);
}

check('退出登录后停在未登录态（不自动切换角色）', () => {
  const body = fnBody('logout');
  for (const bad of [/onChar\(/, /chars\.value\[0\]/, /const nxt/])
    if (bad.test(body)) throw new Error('logout 仍会自动切换角色：' + body.match(bad)[0]);
  if (!/charId\.value=null/.test(body)) throw new Error('logout 未把 charId 置空');
  if (!/cacheDel\('cid'\)/.test(body)) throw new Error('logout 未清除缓存的 cid（刷新会又登录）');
});

check('loadChars 不自动选中角色', () => {
  const body = fnBody('loadChars');
  if (/chars\.value\[0\]/.test(body)) throw new Error('loadChars 仍会自动选中第一个角色');
  if (!/consumeLoginParam\(\)/.test(read('app.js'))) throw new Error('未消费登录回调的 ?cid');
});

check('弹药下拉框列出全部兼容弹药（不限货舱）', () => {
  const app = read('app.js'), html = read('index.html');
  const body = fnBody('ammoFor');
  if (/other\??\.\s*charge/.test(body))
    throw new Error('ammoFor 仍只取货舱/装配里的弹药：' + body);
  if (!/ammoMap/.test(body)) throw new Error('ammoFor 未使用后端全量兼容弹药表 ammoMap');
  if (!/\/api\/weapon\/\$\{tid\}\/charges/.test(app))
    throw new Error('未请求 /api/weapon/<tid>/charges（该武器全部兼容弹药）');
  if (!/function loadAmmoAll\(/.test(app)) throw new Error('缺少 loadAmmoAll');
  if (!/loadAmmoAll\(\)/.test(app.replace(/function loadAmmoAll\(\)[^\n]*/, '')))
    throw new Error('loadAmmoAll 未在模拟后被调用（下拉框会一直空）');
  if (!/optgroup/.test(html)) throw new Error('下拉框未按弹药组分组（optgroup）');
  if (!/ammoLabel\(c\)/.test(html)) throw new Error('下拉选项未标注 T1/T2/势力/货舱');
  const ret = app.slice(app.lastIndexOf('return {'));
  for (const name of ['ammoFor', 'ammoGroupsFor', 'ammoLabel', 'ammoLoading'])
    if (!new RegExp('[,\\s{]' + name + '[,\\s}]').test(ret))
      throw new Error('setup() 未返回 ' + name);
});

if (failures.length) {
  console.log('\n' + failures.length + ' 项失败');
  process.exit(1);
}
console.log('\n前端静态检查全部通过');
