"""生成 macOS 风格 App 图标：紫底渐变 squircle + 白色 ">_<" 横向排列。

字形：">" 在左，"_" 在中，"<" 在右，同一水平线（字面 >_<）。
用法：backend/.venv/bin/python scripts/make_icon.py
产物：frontend/build/icon.png（1024x1024，electron-builder 转 icns）
"""
from pathlib import Path
from PIL import Image, ImageDraw

S = 2048  # 超采样，缩小到 1024 抗锯齿
OUT = Path(__file__).resolve().parents[1] / "frontend" / "build" / "icon.png"

# ---------- 紫底渐变 squircle ----------
icon = Image.new("RGBA", (S, S), (0, 0, 0, 0))
draw = ImageDraw.Draw(icon)
top, bottom = (139, 92, 246), (109, 40, 217)  # #8b5cf6 -> #6d28d9 紫渐变
for y in range(S):
    t = y / S
    c = tuple(int(top[i] + (bottom[i] - top[i]) * t) for i in range(3))
    draw.line([(0, y), (S, y)], fill=c + (255,))
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([0, 0, S - 1, S - 1], radius=int(S * 0.225), fill=255)
icon.putalpha(mask)

# ---------- 白色 ">_<" 横向一字排开 ----------
white = (255, 255, 255, 255)
cx, cy = S // 2, S // 2
W = int(S * 0.058)          # 笔画粗细
hw, hh = int(S * 0.095), int(S * 0.080)   # chevron 半宽/半高
sep = int(S * 0.225)        # 左右字符与中心的间距

# 左 ">"
lx = cx - sep
draw.line([(lx - hw, cy - hh), (lx + hw, cy)], fill=white, width=W, joint="curve")
draw.line([(lx + hw, cy), (lx - hw, cy + hh)], fill=white, width=W, joint="curve")
# 右 "<"
rx = cx + sep
draw.line([(rx + hw, cy - hh), (rx - hw, cy)], fill=white, width=W, joint="curve")
draw.line([(rx - hw, cy), (rx + hw, cy + hh)], fill=white, width=W, joint="curve")
# 中 "_"（同一水平线）
draw.rectangle([cx - int(S * 0.09), cy - int(S * 0.005), cx + int(S * 0.09), cy + int(S * 0.032)], fill=white)

icon = icon.resize((1024, 1024), Image.LANCZOS)
OUT.parent.mkdir(parents=True, exist_ok=True)
icon.save(OUT)
print("wrote", OUT, f"({OUT.stat().st_size//1024}KB)")
