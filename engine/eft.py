"""EFT 文本 解析 / 生成。"""

import re

_QTYS = re.compile(r"^(.*?)\s+x(\d+)\s*$")


def parse_eft(text):
    """解析 EFT 文本 → (ship_name, fit_name, [(item_name, qty)])。"""
    ship = fit_name = None
    items = []
    for idx, raw in enumerate(text.splitlines()):
        line = raw.strip()
        if not line:
            continue
        if line.startswith("["):
            if ship is None or "," in line:
                body = line[1:-1]
                if "," in body:
                    ship, fit_name = (p.strip() for p in body.split(",", 1))
                else:
                    ship = body.strip()
                continue
            continue  # [Empty High slot] 之类
        m = _QTYS.match(line)
        if m:
            items.append((m.group(1).strip(), int(m.group(2))))
        else:
            items.append((line, 1))
    return ship, fit_name, items


def render_eft(ship_name, fit_name, items):
    """items: [(item_name, qty)] → EFT 文本。"""
    lines = [f"[{ship_name}, {fit_name}]"]
    for name, qty in items:
        lines.append(f"{name} x{qty}" if qty > 1 else f"{name}")
    return "\n".join(lines) + "\n"