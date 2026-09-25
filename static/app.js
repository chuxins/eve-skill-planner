/* 模拟装配前端（Vue 3，buildless） */
const { createApp } = Vue;

const API = {
  search: (q, cat, limit) => `/api/search?q=${encodeURIComponent(q)}&cat=${cat}&limit=${limit || 50}`,
  ships: '/api/ships',
  characters: '/api/characters',
  skills: (cid) => `/api/characters/${cid}/skills`,
  wallet: (cid) => `/api/characters/${cid}/wallet`,
  fittings: (cid) => `/api/characters/${cid}/fittings`,
  sim: '/api/simulate',
  eftSim: '/api/eft/simulate',
  local: '/api/local/fittings',
  saveEsi: (cid) => `/api/characters/${cid}/fittings/save`,
  authStart: '/api/auth/start',
};

function fmtNum(n) {
  if (n === null || n === undefined || isNaN(n)) return '—';
  if (Math.abs(n) >= 1e9) return (n / 1e9).toFixed(2) + 'B';
  if (Math.abs(n) >= 1e6) return (n / 1e6).toFixed(1) + 'M';
  if (Math.abs(n) >= 1e4) return (n / 1e4).toFixed(1) + '万';
  if (Math.abs(n) >= 1000) return (n / 1000).toFixed(1) + 'k';
  return String(Math.round(n * 10) / 10);
}

const icon = (tid) => `https://images.evetech.net/types/${tid}/icon?size=32`;

createApp({
  data() {
    return {
      ltab: 'hull', rtab: 'res', ehpMode: 'ehp',
      shipTid: null, shipName: '', fitName: '',
      shipQ: '', shipQ2: '', ships: [], itemQ: '', buildList: [], itemResults: [],
      characters: [], charId: null, skills: {}, isk: '—',
      fittingList: [], fittingsLoading: false, activeFitKey: null,
      sim: null, unknowns: [],
      eftText: '', saveName: '',
      openShipModal: false, openEft: false, openSaveModal: false, openHistory: false,
      history: JSON.parse(localStorage.getItem('sim_history') || '[]'),
      fitCache: {},      // 角色装配原始数据缓存 {fitting_id: {ship_tid, items}}
    };
  },
  computed: {
    hasSkills() { return Object.keys(this.skills).length > 0; },
    res() { return this.sim ? this.sim.resources : {}; },
    resists() { return this.sim ? this.sim.resists : {shield:[],armor:[],hull:[]}; },
    ehp() { return this.sim ? this.sim.ehp : {layers:{},total:0}; },
    fw() { return this.sim ? this.sim.firepower : {turret:{},drone:{},total:0,weapons:[]}; },
    tgt() { return this.sim ? this.sim.targeting : {}; },
    nav() { return this.sim ? this.sim.nav : {}; },
    repair() { return this.sim ? this.sim.repair : {armor:0,shield:0}; },
    cap() { return () => this.sim ? this.sim.capacitor : {stable:true,deplete:null}; },
    capTimeLeft() {
      const c = this.sim && this.sim.capacitor;
      if (!c || c.stable || !c.deplete) return '';
      const s = Math.round(c.deplete);
      return `${String(Math.floor(s / 3600)).padStart(2, '0')}:${String(Math.floor((s % 3600) / 60)).padStart(2, '0')}:${String(s % 60).padStart(2, '0')}`;
    },
    slots() { return this.sim ? this.sim.slots : {high:[],med:[],low:[],rig:[]}; },
    other() { return this.sim ? this.sim.other : {charge:[],drone:[]}; },
    maxRigs() { return (this.res.slots_cap && this.res.slots_cap.rig) || 0; },
    shipGroups() {
      const g = new Set(this.ships.map((s) => s.group));
      return [...g].sort((a, b) => a.localeCompare(b, 'zh'));
    },
    shipResults2() {
      const q = this.shipQ2.trim().toLowerCase();
      if (!q) return this.ships.slice(0, 60);
      return this.ships.filter((s) => s.name.toLowerCase().includes(q) || s.name_en?.toLowerCase().includes(q)).slice(0, 60);
    },
  },
  methods: {
    icon,
    fmtNum,
    layerName(l) { return { shield: '护盾', armor: '装甲', hull: '结构' }[l]; },
    pct(r) { return r && r.cap ? Math.min(100, r.used / r.cap * 100) : 0; },
    over(key) { const r = this.res[key]; return r && r.used > r.cap ? 'over' : ''; },
    emptySlots(slot) {
      const cap = (this.res.slots_cap && this.res.slots_cap[slot]) || 0;
      return Math.max(0, cap - this.slots[slot].length);
    },
    async j(url, opt) {
      const r = await fetch(url, opt);
      const data = await r.json().catch(() => ({}));
      if (!r.ok) throw new Error(data.error || r.status);
      return data;
    },

    // ---------- 角色 ----------
    async loadCharacters() {
      this.characters = await this.j(API.characters);
      if (this.characters.length && this.charId === null) {
        this.charId = this.characters[0].id;
        await this.onCharChange();
      }
      if (location.search.includes('ok=1')) {
        history.replaceState(null, '', location.pathname + location.hash);
      }
    },
    async onCharChange() {
      this.skills = {};
      if (!this.charId) { this.isk = '—'; return; }
      try { this.skills = await this.j(API.skills(this.charId)); } catch (e) { console.warn(e); }
      try { this.isk = fmtNum(await this.j(API.wallet(this.charId)).then((d) => d.balance)); } catch (e) { this.isk = '—'; }
      if (this.sim) this.simulate();
    },
    authStart() { location.href = API.authStart + '?target=fitting'; },

    // ---------- 左栏 ----------
    async searchShips() {
      if (!this.ships.length) this.ships = await this.j(API.ships);
      // 客户端过滤
    },
    shipsByGroup(g) {
      const q = this.shipQ.trim().toLowerCase();
      return this.ships.filter((s) => s.group === g && (!q || s.name.toLowerCase().includes(q)));
    },
    chooseShip(tid) {
      this.shipTid = tid;
      const s = this.ships.find((x) => x.tid === tid);
      this.shipName = s ? s.name : '';
      this.fitName = '';
      this.simulate();
    },
    async searchItems() {
      const q = this.itemQ.trim();
      if (!q) return;
      const cat = this.ltab === 'mod' ? 7 : 8;
      this.itemResults = await this.j(API.search(q, cat));
    },
    addItem(r) {
      const hit = this.buildList.find((b) => b.tid === r.tid);
      if (hit) hit.qty += 1; else this.buildList.push({ tid: r.tid, name: r.name, qty: 1 });
    },
    removeItem(it) {
      this.buildList = this.sim ? this.sim.items.filter((x) => !(x.tid === it.tid && x.qty === it.qty)) : [];
      this.simulate();
    },

    // ---------- 装配列表 ----------
    async loadFittings() {
      this.fittingsLoading = true;
      this.fittingList = [];
      await this.searchShips();
      try {
        const local = await this.j(API.local);
        local.forEach((f) => this.fittingList.push({ key: 'l' + f.id, name: f.name, ship: f.ship_name || '', kind: 'local', data: f.eft }));
      } catch (e) { /* 忽略 */ }
      if (this.charId) {
        try {
          const fits = await this.j(API.fittings(this.charId));
          fits.forEach((f) => {
            this.fitCache[f.fitting_id] = f;
            this.fittingList.push({ key: 'c' + f.fitting_id, name: f.name, ship: f.ship, kind: 'char', data: f.fitting_id });
          });
        } catch (e) { console.warn(e); }
      }
      this.fittingsLoading = false;
    },
    async loadFit(f) {
      this.activeFitKey = f.key;
      if (f.kind === 'local') return this.importEftText(f.data);
      const fit = this.fitCache[f.data];
      if (!fit) return;
      this.shipTid = fit.ship_tid;
      this.shipName = fit.ship;
      this.fitName = fit.name;
      await this.simulateFor(fit.items.map((it) => [it.tid, it.qty]));
    },

    // ---------- 模拟 ----------
    async simulateFor(items) {
      if (!this.shipTid) return;
      try {
        this.sim = await this.j(API.sim, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ ship_tid: this.shipTid, items, skills: this.skills }),
        });
        this.buildList = this.sim.items.map((it) => ({ tid: it.tid, name: it.name, qty: it.qty }));
        this.unknowns = this.sim.unknowns || [];
      } catch (e) { alert(e.message); }
    },
    async simulate() {
      await this.simulateFor(this.buildList.map((b) => [b.tid, b.qty]));
    },

    // ---------- EFT ----------
    async importEft() {
      this.openEft = false;
      await this.importEftText(this.eftText);
      this.eftText = '';
    },
    async importEftText(eft) {
      try {
        const r = await this.j(API.eftSim, {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ eft, skills: this.skills }),
        });
        this.shipTid = r.ship.tid;
        const s = this.ships.find((x) => x.tid === r.ship.tid);
        this.shipName = s ? s.name : r.ship.name;
        this.fitName = r.fit_name || '';
        this.sim = r;
        this.buildList = r.items.map((it) => ({ tid: it.tid, name: it.name, qty: it.qty }));
        this.unknowns = r.unknowns || [];
      } catch (e) { alert(e.message); }
    },

    // ---------- 保存 / 历史 ----------
    buildEft() {
      if (!this.sim) return '';
      const ship = this.sim.ship.name;
      const lines = this.sim.items.map((it) => (it.qty > 1 ? `${it.name} x${it.qty}` : it.name));
      return `[${ship}, ${this.fitName || '未命名'}]\n${lines.join('\n')}`;
    },
    async saveLocal() {
      const name = this.saveName.trim() || (this.fitName || '未命名');
      const eft = this.buildEft();
      if (!eft) return;
      await this.j(API.local, {
        method: 'POST', headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ name, eft, ship_name: this.sim.ship.name }),
      });
      this.openSaveModal = false;
      this.loadFittings();
    },
    async saveEsi() {
      if (!this.charId || !this.sim) return;
      const flagOrder = ['hiSlot', 'medSlot', 'loSlot', 'rigSlot'];
      const items = [];
      for (const it of this.sim.items) {
        const slots = it.slot ? this.sim.slots[it.slot] : [];
        const idx = slots.findIndex((x) => x.tid === it.tid && x.qty === it.qty);
        const flag = it.slot && idx >= 0 ? `${flagOrder[['high','med','low','rig'].indexOf(it.slot)]}${idx}` : 'cargo';
        items.push({ type_id: it.tid, quantity: it.qty, flag });
      }
      try {
        await this.j(API.saveEsi(this.charId), {
          method: 'POST', headers: { 'Content-Type': 'application/json' },
          body: JSON.stringify({ name: this.saveName.trim() || '模拟装配', items, ship_tid: this.sim.ship.tid }),
        });
        this.openSaveModal = false;
        alert('已保存到 EVE');
      } catch (e) { alert('保存失败：' + e.message); }
    },
    saveState() {
      if (!this.sim) return;
      this.history.unshift({
        name: `${this.shipName}${this.fitName ? ' · ' + this.fitName : ''}`,
        time: new Date().toLocaleString('zh-CN', { hour12: false }),
        ship_tid: this.shipTid,
        items: this.buildList.map((b) => [b.tid, b.qty]),
      });
      this.history = this.history.slice(0, 24);
      localStorage.setItem('sim_history', JSON.stringify(this.history));
    },
    showHistory() { this.openHistory = true; },
    closeHistory() { this.openHistory = false; },
    restoreHistory(h) {
      if (!h || !Array.isArray(h.items)) return;
      this.shipTid = h.ship_tid;
      const s = this.ships.find((x) => x.tid === h.ship_tid);
      this.shipName = s ? s.name : '';
      this.buildList = h.items.filter((p) => Array.isArray(p))
        .map(([tid, qty]) => ({ tid, qty: qty || 1 }));
      this.simulate();
    },
  },
  mounted() {
    this.searchShips();
    this.loadCharacters();
  },
}).mount('#app');