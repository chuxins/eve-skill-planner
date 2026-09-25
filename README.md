# eve-skill-planner（模拟装配，从零新写版）

pyfa 风格的单页 Web 装配模拟器，全离线 SDE 引擎（数值锚定 pyfa/游戏实测）。

## 运行

```bash
cd /root/eve-skill-planner
nohup python3 webapp.py --port 8090 > data/webapp.log 2>&1 &
# 浏览器访问 http://8.138.203.48:8090/ （nginx 反代或 --host 0.0.0.0）
```

前置数据（自动准备）：
- `python3 build_index.py` —— 从 SDE zip 构建 `data/staticdata.db`（默认复用 `/root/eve_esi/sde.zip`）
- 角色 token：复用 `~/.eve-skill-planner/tokens/<cid>.json`；无 token 时点「授权角色」走 EVE SSO

## 功能

- **三数据源**：选舰船+物品搭建 / ESI 读取已保存装配 / 粘贴 EFT
- **pyfa 三栏界面**：左栏（船体与装配/装备/弹药 标签页 + 搜索 + 装配列表 + 装配舰船/另存为/浏览/上传），
  中央（舰船渲染图 + 高/中/低/改槽位 + 货舱/机库 + 模拟历史/保存状态），
  右栏（资源/抗性/火力/电容/目标/航行 标签页 + ISK 余额）
- **技能加成**：ESI `read_skills` 实时等级参与计算（两段式 dogma 引擎）
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

### 已知口径差异（与游戏「当前激活」面板不同，pyfa 风格）
- 电容消耗按「全部启用模块」估算（游戏只计当前激活）
- 速度/质量按所有推进器同时生效计算
- CPU/PG 按全部装备在线计算（可能显示超配）

## API

```
GET  /api/search?q=&cat=        物品搜索（6 舰船 /7 装备 /8 弹药）
GET  /api/ships  /api/groups    舰船与分组
GET  /api/item/<tid>            物品详情（属性/需求技能/特性）
POST /api/simulate              模拟 {ship_tid, items:[[tid,qty]], skills}
POST /api/eft/simulate          EFT 文本模拟
GET  /api/characters            已授权角色
GET  /api/characters/<cid>/skills|wallet|fittings
POST /api/characters/<cid>/fittings/save   写回 EVE
GET/POST/DELETE /api/local/fittings        本地存档
GET  /api/auth/start  →  EVE SSO → qq_auth_bot(8000) → /callback/
```

## OAuth 接线

- EVE 注册回调为 `http://8.138.203.48:8000/callback/`（qq_auth_bot 8000）
- `qq_auth_bot.py` 已加 `sim-` state 前缀转发 → `127.0.0.1:8090/callback/`（追加式改动）
- 授权范围：fittings 读/写、skills 读、wallet 读；「保存到 EVE」需含 write scope 的
  重新授权（EVE SSO 复用旧同意记录时需先在账号设置撤销本应用授权）