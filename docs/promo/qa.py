#!/usr/bin/env python3
"""宣传图 QA：OCR 文本核对 + 版面空洞检测 + 对比度/出血检查。

用法: python3 qa.py poster.png [poster.pdf]
"""
import subprocess, sys, tempfile, os, json
from PIL import Image, ImageStat

png = sys.argv[1] if len(sys.argv) > 1 else "poster.png"
pdf = sys.argv[2] if len(sys.argv) > 2 else "poster.pdf"

im = Image.open(png).convert("RGB")
W, H = im.size
print(f"[PNG] {W}x{H}  ratio={W/H:.4f}")

# ---------- 1. OCR ----------
ocr_img = im.resize((W // 2, H // 2), Image.LANCZOS)
with tempfile.NamedTemporaryFile(suffix=".png", delete=False) as f:
    ocr_img.save(f.name)
    tmp = f.name
out = subprocess.run(["tesseract", tmp, "stdout", "-l", "chi_sim+eng", "--psm", "3"],
                     capture_output=True, text=True).stdout
os.unlink(tmp)
lines = [l.strip() for l in out.splitlines() if l.strip()]
print("\n[OCR] 识别到文本行：")
for l in lines:
    print("   ", l)

# 关键文案是否真的画上去了（OCR 对艺术字可能漏，逐一报告命中情况）
keys = ["云原神", "Linux", "GPU", "硬解", "62.5", "fps", "261", "MB", "4400",
        "VK_KHR_video_decode_h265", "install.sh", "yun-genshin", "MIT", "LGPL", "米哈游"]
print("\n[OCR] 关键文案命中：")
flat = out.replace(" ", "").replace("\n", "")
for k in keys:
    print(f"    {'OK ' if k.replace(' ','') in flat else 'MISS'}  {k}")

# ---------- 2. 版面空洞 / 密度分布 ----------
bands = 40
bh = H // bands
print("\n[密度] 每条带的非背景像素占比（找大片空洞）：")
rows = []
for i in range(bands):
    strip = im.crop((0, i * bh, W, (i + 1) * bh)).resize((W // 8, bh // 8))
    st = ImageStat.Stat(strip)
    r, g, b = st.mean
    std = sum(st.stddev) / 3
    # 亮度标准差低 => 近乎纯色/空洞
    lum = 0.2126 * r + 0.7152 * g + 0.0722 * b
    rows.append((i, lum, std))
    flag = "  <== 近似空白" if std < 6 else ""
    print(f"    band{i:02d} y={i*bh:5d}-{ (i+1)*bh:5d}  亮度均值={lum:6.1f}  标准差={std:5.1f}{flag}")

# ---------- 3. 边距与出血 ----------
print("\n[边距] 四边 8px 条带的平均颜色（应与页面底色一致，不应出现白边）：")
for name, box in [("上", (0, 0, W, 8)), ("下", (0, H - 8, W, H)),
                  ("左", (0, 0, 8, H)), ("右", (W - 8, 0, W, H))]:
    st = ImageStat.Stat(im.crop(box))
    print(f"    {name}: RGB({st.mean[0]:.0f},{st.mean[1]:.0f},{st.mean[2]:.0f})")

# ---------- 4. PDF 页面尺寸与四角 ----------
if os.path.exists(pdf):
    import pymupdf
    d = pymupdf.open(pdf)
    pg = d[0]
    print(f"\n[PDF] 页数={d.page_count} 页面={pg.rect.width:.1f}x{pg.rect.height:.1f}pt "
          f"= {pg.rect.width/72*25.4:.0f}x{pg.rect.height/72*25.4:.0f}mm "
          f"(A3=297x420mm, 比例 {pg.rect.width/pg.rect.height:.4f})")
    pm = pg.get_pixmap(dpi=72)
    for (x, y, name) in [(2, 2, "左上"), (pm.width - 3, 2, "右上"),
                         (2, pm.height - 3, "左下"), (pm.width - 3, pm.height - 3, "右下")]:
        print(f"    {name} 像素: {pm.pixel(x, y)}")
    # PDF 内文字是否可提取（可选中 = 矢量文本，不是图片）
    txt = pg.get_text().strip()
    print(f"\n[PDF] 可提取文本长度 {len(txt)} 字（>0 说明是矢量文字，非位图）")
    print("    预览:", txt[:160].replace("\n", " | "))

# ---------- 5. PNG 与 PDF 交叉渲染比对（防止截图分块缺失） ----------
try:
    import numpy as np, pymupdf
    d2 = pymupdf.open(pdf)
    pm = d2[0].get_pixmap(dpi=192)
    pdfimg = Image.frombytes("RGB", (pm.width, pm.height), pm.samples)
    a = np.asarray(im.resize((1240, 1754), Image.LANCZOS)).astype(int)
    b = np.asarray(pdfimg.resize((1240, 1754), Image.LANCZOS)).astype(int)
    print(f"\n[交叉比对] PNG vs PDF 平均像素差 = {np.abs(a-b).mean():.2f} (<12 视为一致)")
    def ink(arr):
        l = 0.2126*arr[:,:,0]+0.7152*arr[:,:,1]+0.0722*arr[:,:,2]
        return np.array([(np.abs(l[y:y+8]-np.median(l[y:y+8]))>22).mean() for y in range(0, 1746, 8)])
    ia, ib = ink(a), ink(b)
    bad = [(i*8, round(float(ia[i]),3), round(float(ib[i]),3)) for i in range(len(ia)) if abs(ia[i]-ib[i]) > 0.05]
    print(f"[交叉比对] 墨迹覆盖率偏差 >5% 的扫描带: {bad if bad else '无 —— 两种渲染一致'}")
except Exception as e:
    print("[交叉比对] 跳过:", e)

# ---------- 6. 文字对比度（WCAG） ----------
def _lin(c):
    c = c/255
    return c/12.92 if c <= 0.04045 else ((c+0.055)/1.055)**2.4
def lum(rgb):
    r,g,b = [_lin(x) for x in rgb]
    return 0.2126*r+0.7152*g+0.0722*b
def ratio(fg, bg):
    l1,l2 = lum(fg), lum(bg)
    if l1 < l2: l1,l2 = l2,l1
    return (l1+0.05)/(l2+0.05)
def hx(s):
    s = s.lstrip('#')
    return tuple(int(s[i:i+2],16) for i in (0,2,4))
print("\n[对比度] WCAG 文字对比度：")
bg = hx('#131A2E')
checks = [
    ("正文 ink #F3F6FC", hx('#F3F6FC'), bg, 4.5),
    ("次要 muted #98A6C6", hx('#98A6C6'), bg, 4.5),
    ("标题青 #3BD8F5", hx('#3BD8F5'), bg, 3.0),
    ("强调琥珀 #FFB547", hx('#FFB547'), bg, 3.0),
    ("导语 #C6D2EA", hx('#C6D2EA'), bg, 4.5),
    ("页脚 #7E8DAE", hx('#7E8DAE'), bg, 4.5),
    ("页脚强 #B4C2DE", hx('#B4C2DE'), bg, 4.5),
    ("chip 字 on 面板", hx('#CFE0F5'), hx('#222A42'), 4.5),
    ("面板内正文", hx('#98A6C6'), hx('#20263A'), 4.5),
    ("徽章内暗字 on 青", hx('#08121E'), hx('#3BD8F5'), 4.5),
]
for name, fg, bgc, need in checks:
    r = ratio(fg, bgc)
    print(f"    {'PASS' if r>=need else 'FAIL'}  {name}: {r:.2f}:1  (需 ≥{need})")
