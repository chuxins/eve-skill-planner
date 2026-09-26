# eve-skill-planner（模拟装配，从零新写版）

pyfa 风格的单页 Web 装配模拟器，全离线 SDE 引擎（数值锚定 pyfa/游戏实测）。

## 运行

```bash
cd /root/eve-skill-planner
nohup python3 webapp.py --port 8090 --host 0.0.0.0 > data/webapp.log 2>&1 &
# 浏览器访问 http://8.138.203.48:8090/ （必须 --host 0.0.0.0，否则公网连不上 ERR_CONNECTION_RESET）
```

前置数据（自动准备）：
- `python3 build_index.py` —— 从 SDE zip 构建 `data/staticdata.db`（默认复用 `/root/eve_esi/sde.zip`）
- 角色 token：复用 `~/.eve-skill-planner/tokens/<cid>.json`；无 token 时点页头「登录」走 EVE SSO，
  已授权后页头显示角色名、ISK 与「退出登录」（**只注销当前角色**：删其 token 并尽力在 EVE 侧吊销）。
  退出后直接回到未登录态（「登录」按钮），**不会自动切到其它角色**——其余角色的 token 仍留在服务端，
  点「登录」重新授权即可（回调带 `?cid=`，多账号时只会选中刚授权的那个）

## 功能

- **三数据源**：选舰船+物品搭建 / ESI 读取已保存装配 / 粘贴 EFT
- **pyfa 三栏界面**：左栏（船体与装配/装备/弹药 标签页 + 搜索 + 装配列表 + 装配舰船/另存为/浏览/上传），
  中央（舰船渲染图 + 高/中/低/改槽位 + 货舱/机库 + 模拟历史/保存状态），
  右栏（资源/抗性/火力/电容/目标/航行/技能 标签页 + ISK 余额）
- **左栏分组浏览**：舰船按 **舰种 → 种族** 两级展开（种族四大帝国固定在前，势力/昇威/三神裔等随后，
  未标注 raceID 的归入「其他」），配种族筛选按钮；装备按 槽位、弹药按 家族 → 组 展开
- **左栏点击语义**：点**舰船名** = 换用该船体并**清空全部槽位**（从零开始搭）；点其下的**装配方案**
  （⚙ 本地 / 🌐 ESI）= 按该方案装填槽位
- **三栏各自独立滚动**：页头固定，`main` 高度锁定为「视口 − 页头」（栅格行 `minmax(0,1fr)`），
  左/中/右三栏分别 `overflow-y:auto`；滚任一侧栏都不会带动中间装配界面，也不会出现整页滚动条，
  左栏底部（装配舰船/另存为/上传 EFT）常驻可见（窗口高度 320px 时同样成立）
- **技能加成**：ESI `read_skills` 实时等级参与计算（两段式 dogma 引擎）
- **技能规划**（右栏「技能」）：按当前角色技能算「这艘船 + 这套装配」还缺哪些技能、
  各缺几级、预计训练时长；需求技能递归展开前置（舰船 → 战列巡洋舰操作 → 飞船操控学…）
  并按「前置优先」排序，同时显示 ESI 训练队列（需求 `esi-skills.read_skillqueue.v1`，
  缺该授权时只在该面板提示，不影响其余功能）
- **逐门武器弹药**：高槽每门武器（**炮台与导弹/鱼雷发射架**）的行内下拉框列出该武器
  **全部兼容弹药**（引擎按 SDE 计算：装填尺寸 attr 128 一致 + 弹药组属于 `chargeGroup1..5`
  attr 604-608，排除脚本/电容装料等无伤害「弹药」；发射架没有装填尺寸属性 → 只按弹药组匹配），
  按弹药组分组、标注 T1/T2/势力，货舱里已有的标「货舱」；选中即生效，
  **不必先把弹药放进货舱**（也不占货舱容积，且与货舱内同款弹药吃同一套船体/模块加成）；
  默认「自动」= 按装填尺寸自动配弹（优先弹药组匹配者，发射架按弹药组配弹），
  弹药不存在/尺寸或弹药组不符时回退，不会报错
- **存档**：本地（SQLite）+ 写回 EVE（需 `esi-fittings.write_fittings.v1`，需重新授权）
- 物品详情：点击任意物品查看属性表/需求技能/舰船特性

## 引擎要点（engine/simulate.py）

- 全离线：`typeDogma` + `dogmaEffects.modifierInfo`，无 ESI 依赖
- 操作符语义（2026-09 SDE 实测，勿按直觉记）：
  - `op 0 / 4 / -1` = 原始乘法（损控 ×0.85、回充器 ×0.8、技能阶段1）
  - `op 2` = 平加（电池 +625 这类）
  - `op 6 / 7` = 百分比（硬膜/装甲补偿）
  - `op 3 / 5` = 除法（罕见）
- **Location 过滤器**：`LocationGroupModifier` 目标组取 modifierInfo 的 `groupID` 字段、
  `LocationRequiredSkillModifier` 取 `skillTypeID`（目标属性都是 `modifiedAttributeID`）
- 同属性规则：加性先行 → 乘性后行；乘性按 |delta| 降序叠加惩罚
  `0.5^((n-1)/2.22292081)²`；豁免：技能/损伤控制(group 60)/电容回充(attr 55)
- 两段式技能：① itemID 域 `modifying=280` 折算加成属性 = 基数×等级；② shipID 域按 func 应用
- 结构抗性用 109-113（不是 974-977）；电容容量是 **attr 482**
- 锁定时间 = 40000/(扫描×asinh(信号)²)；起跳 = 质量×惯性×ln4/1e6
- 推进器特殊处理（moduleBonus 效果 6730/6731）：速度×(1+attr20/100)、
  MWD 质量 +500t（5MN）/惯性 ×1.125/信号 ×1.5
- 显式指定但**不在装配/货舱里**的弹药：用同一批修正单独算一遍属性
  （`_solve_virtual_charges`），保证「货舱里」与「从下拉框选中」的同款弹药伤害一致
  （`Location*Modifier` 只对装配内物品生效，不这样处理会出现两个伤害）

### 技能规划（engine/skillplan.py）

- 需求技能：`requiredSkill1..5`(attr 182-186) 配 `requiredSkill*Level`(277/278/279/1286/1287)，
  递归展开前置技能（技能自身也带 requiredSkill*），同技能取「所需最高等级」
- 训练时间：`SP(L) = 250 × rank × 2^(2.5L − 2.5)`（rank = attr 275 `skillTimeConstant`），
  速率 = `主属性 + 副属性/2` SP/分钟（属性取 ESI `attributes` 的 base+implant 有效值）
- 输出按 Kahn 拓扑排序，保证计划自上而下可依次训练；未达标项才计入时长
- 仅按「从 0 级开始」估算，不含角色已有的技能点进度与属性重映射

### 已知口径差异（与游戏「当前激活」面板不同，pyfa 风格）
- 电容消耗按「全部启用模块」估算（游戏只计当前激活）
- 速度/质量按所有推进器同时生效计算
- CPU/PG 按全部装备在线计算（可能显示超配）
- 导弹/发射架武器按「弹药伤害 ÷ 发射间隔 × 数量」计入 `firepower.launcher`（发射架没有
  damageMultiplier，故 450 伤害的鱼雷就是 450；与炮台一样不算射程/target 应用）：
  命中率、导弹飞行时间/信号半径/爆炸速度这些「实际命中伤害」因素不建模，故导弹 DPS 是
  纸面值（pyfa 亦如此）；发射架占发射位（`resources.launcher`）一并统计

## API

```
GET  /api/search?q=&cat=        物品搜索（6 舰船 /7 装备 /8 弹药）
GET  /api/ships  /api/groups    舰船列表（含 group/race）/ 舰船组
GET  /api/item/<tid>            物品详情（属性/需求技能/特性）
GET  /api/weapon/<tid>/charges  该武器全部兼容弹药（尺寸 + chargeGroup，不限货舱）
POST /api/simulate              模拟 {ship_tid, items:[[tid,qty]], skills, charges:{武器tid:弹药tid}}
POST /api/eft/simulate          EFT 文本模拟
POST /api/skillplan             技能计划 {cid, ship_tid, items, skills?}
GET  /api/characters            已授权角色
POST /api/logout                退出登录：{cid} 注销该角色（前端只注销当前角色，退出后停在未登录态）/ {all:true} 注销全部（删本地 token + 尽力吊销 SSO 令牌）
GET  /api/characters/<cid>/skills|wallet|fittings|attributes|skillqueue
POST /api/characters/<cid>/fittings/save   写回 EVE
GET/POST/DELETE /api/local/fittings        本地存档
GET  /api/auth/start  →  EVE SSO → nginx /api/auth/callback → /callback/
```

## 前端

无构建步骤：`static/index.html` + `static/util.js`（纯函数与 API 封装）+ `static/app.js`（Vue 单文件 setup）。
页内用 `{{ASSET_VERSION}}` 占位，由 `webapp.py` 在渲染 `/` 时按 `static/` 下文件的
(路径, mtime, 大小) 摘要替换 —— **改动任意静态资源后版本号自动变化，无需手工改 `app.js?v=NN`**。

## 测试

```bash
python3 -m pytest tests/ -q     # 引擎数值锚定 + 技能规划 + 前端静态检查
python3 tests/test_engine.py    # 单文件直跑（不依赖 pytest，末尾打印通过数）
python3 tests/test_skillplan.py
node tests/check_frontend.js    # JS 语法 + Vue 模板编译 + 资源自动版本占位
```

## OAuth 接线

本应用使用**独立的 EVE 应用凭据**（项目根目录 `config.json`，已 gitignore），
不再复用 qq_auth_bot 的 8000 应用：

- EVE 应用登记的「回调地址(Callback URL)」须逐字符等于 `config.json` 里的 `callback_url`：
  `http://8.138.203.48/api/auth/callback`
  （两者不一致时 EVE 会报 `invalid redirect_uri`，授权直接失败）
- nginx 负责把该公网地址反代到本应用（见 `/etc/nginx/sites-available/report` 的 80 端口 server）：
  `location = /api/auth/callback → http://127.0.0.1:8090/callback/`
- 授权范围：fittings 读/写、skills 读、**训练队列读**、wallet 读；「保存到 EVE」需含 write scope 的
  重新授权（EVE SSO 复用旧同意记录时需先在账号设置撤销本应用授权）
- 环境变量可覆盖配置：`EVE_CLIENT_ID` / `EVE_CLIENT_SECRET` / `EVE_CALLBACK_URL`
  （单字段覆盖，未设置的回退到 `config.json`）；`EVE_SKILL_PLANNER_URL` 覆盖授权成功后
  回跳的前端基址（默认 `http://8.138.203.48:8090`）