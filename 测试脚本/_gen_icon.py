# -*- coding: utf-8 -*-
"""生成应用图标 app.ico（圆角渐变蓝底 + 白色麦克风 + 音符）。
超采样 1024 绘制 → 缩到各尺寸，一次生成多分辨率 .ico。"""
import math
from PIL import Image, ImageDraw, ImageFilter

S = 1024
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# ── 圆角方形底（渐变蓝 #2563EB → #3B82F6，对角）──
mask = Image.new("L", (S, S), 0)
ImageDraw.Draw(mask).rounded_rectangle([24, 24, S - 24, S - 24], radius=210, fill=255)
base = Image.new("RGBA", (S, S), (0, 0, 0, 0))
bd = ImageDraw.Draw(base)
top, bot = (37, 99, 235), (59, 130, 246)
for y in range(S):
    t = y / S
    # 对角渐变：按 (x+y) 加权
    c = tuple(int(top[i] + (bot[i] - top[i]) * t) for i in range(3))
    bd.line([(0, y), (S, y)], fill=c + (255,))
img.paste(base, (0, 0), mask)

d = ImageDraw.Draw(img)
WHITE = (255, 255, 255, 255)

# ── 麦克风主体：竖直胶囊 ──
mic_w, mic_h = 250, 430
mx, my = S // 2 - 10, 300          # 中心略偏左上，给音符留位
d.rounded_rectangle([mx - mic_w // 2, my - mic_h // 2,
                     mx + mic_w // 2, my + mic_h // 2],
                    radius=mic_w // 2, fill=WHITE)
# 胶囊上的横向栅格纹（麦克风质感）：挖几条半透明槽
for i in range(3):
    yy = my - 120 + i * 120
    d.rounded_rectangle([mx - mic_w // 2 + 34, yy - 9, mx + mic_w // 2 - 34, yy + 9],
                        radius=9, fill=(37, 99, 235, 170))

# ── 麦克风支架弧 ──
arc_box = [mx - 230, my + 40, mx + 210, my + 500]
d.arc(arc_box, start=20, end=160, fill=WHITE, width=58)
# 立杆 + 底座
d.line([(mx - 10, my + 470), (mx - 10, my + 585)], fill=WHITE, width=58)
d.rounded_rectangle([mx - 150, my + 585, mx + 130, my + 645], radius=30, fill=WHITE)

# ── 右上音符（八分音符）──
def note(cx, cy, r, scale=1.0):
    d.ellipse([cx - 30 * scale, cy - 22 * scale, cx + 30 * scale, cy + 22 * scale],
              fill=WHITE)
    d.line([(cx + 26 * scale, cy), (cx + 26 * scale, cy - 150 * scale)], fill=WHITE,
           width=int(16 * scale))
    d.arc([cx + 26 * scale, cy - 190 * scale, cx + 95 * scale, cy - 90 * scale],
          start=-10, end=110, fill=WHITE, width=int(16 * scale))

note(818, 250, 30, 1.15)
# 左上小音符
note(210, 330, 20, 0.8)

# ── 轻微内发光（顶部高光）──
glow = Image.new("L", (S, S), 0)
gd = ImageDraw.Draw(glow)
gd.ellipse([120, 60, 900, 520], fill=48)
glow = glow.filter(ImageFilter.GaussianBlur(120))
glow = glow.point(lambda x: min(x, 55))          # 限幅，别过曝
white_layer = Image.new("RGBA", (S, S), (255, 255, 255, 255))
img = Image.composite(white_layer, img, glow)

# ── 导出多尺寸 ico ──
out = r"D:\点歌台干活处\点歌台拆分\app.ico"
img.save(out, format="ICO", sizes=[(256, 256), (128, 128), (64, 64),
                                   (48, 48), (32, 32), (16, 16)])
print("已生成:", out)
# 同时导出一张 PNG 预览
img.resize((256, 256), Image.LANCZOS).save(r"D:\点歌台干活处\_icon_preview.png")
print("预览: _icon_preview.png")
