# 宣传图（平面海报）

云原神 Linux 整合应用的开源宣传物料。全部为**纯 HTML/CSS 平面设计**，
不含游戏截图、不含米哈游 Logo —— 项目本身与米哈游无关联，宣传物料也不制造关联暗示。

| 文件 | 说明 |
|---|---|
| `poster.html` | 竖版主海报源文件（1240×1754，比例 1:√2 = A3） |
| `poster.png` | 2480×3508（300 dpi）位图，用于社交平台/印刷 |
| `poster.pdf` | 矢量 PDF，文字可选中、可无损印刷（328×464 mm，A3 缩放打印） |
| `banner.html` | 横版源文件（1920×1080），用于视频封面/横幅 |
| `banner.png` / `banner.pdf` | 横版成品 |
| `render.mjs` | 渲染器：Chrome headless + CDP，出图并做版面自检 |
| `qa.py` | 验收脚本：OCR 核对、密度/空洞检测、PNG↔PDF 交叉比对、对比度检查 |

## 重新生成

```bash
cd docs/promo
node render.mjs poster.html . 1240 1754   # → poster.png + poster.pdf
node render.mjs banner.html . 1920 1080   # → banner.png + banner.pdf
python3 qa.py poster.png poster.pdf       # 验收
```

依赖：系统 `google-chrome`（已验证 154.x）、`node` ≥ 18（用内置 WebSocket 走 CDP）、
`python3` + `pillow` + `pymupdf` + `tesseract-ocr`（含 `chi_sim`）。

> 渲染器**不用** `captureBeyondViewport + clip` 截全页 —— Chrome 会分块重栅格化，
> 实测导致页面中部出现 120px 空白（DOM 有字、PNG 没字）。视口尺寸等于页面尺寸后
> 直接截视口即可，`qa.py` 的 PNG↔PDF 交叉比对就是为此加的回归检查。

## 设计说明

**风格**：平面（flat）暗色技术风 —— 大字重排版 + 扁平几何图形 + 极细分隔线，
不用卡片堆、不用边框盒子，靠字号/字重/留白建立层级。

**配色**（Material 低饱和暗色 + 双强调色）

| 角色 | 色值 | 用途 |
|---|---|---|
| 底色 | `#131A2E` → `#0C1120` 渐变 | 页面底 + 右上青色光晕 + 左下琥珀光晕 |
| 结构 | `rgba(255,255,255,.11)` 细线 | 区块分隔、统计列分隔 |
| 强调 1 | 青 `#3BD8F5` | 标题关键词、数据、流程热点芯片、H.265 徽章 |
| 强调 2 | 琥珀 `#FFB547` | 第二组数据、强调词、品牌角标 |
| 文字 | `#F3F6FC` / `#98A6C6` / `#7E8DAE` | 主文 / 次要 / 页脚 |

**版式**（自上而下单列流，模块间用留白 + 细线分隔，无卡片墙）

```
页眉（品牌标 + 版本/许可）        y 46–135
主视觉（眉题 + 88px 巨标题 + 导语）y 135–607      右上角 H.265 扁平徽章
流程条（云端→RTC→FFmpeg→Vulkan→交换链）y 639–781
数据条（62.5fps / 0 次 / 261MB / +4400 行） y 809–936
特性（5 条，含图标 + 细线分隔）        y 964–1470
安装（两行命令 + 引导说明）            y 1494–1654
页脚（免责声明 / 许可 / 致谢）          y 1654–1733
```

内容占画布 46→1733 px，底部余量 22 px，模块间隙 24–32 px，无空洞。

**字体**（3 款以内，全部本机已有，无需联网）

- `Noto Sans CJK SC`（Black/Bold/Medium/Regular）—— 标题与正文
- `DejaVu Sans Mono` —— 命令与技术标识

## 文案数据出处

宣传图上的数字都来自仓库实测，不是估计值：

| 宣传文案 | 出处 |
|---|---|
| 62.5 fps 实测中位帧率 | 2026-11-09 HEVC 硬解实测；注意取中位数而非均值（长尾停顿会拉低均值） |
| 0 次 CPU 回读与上传 | wine 日志判据 `yg-upload = 0`、`yg-nv12 = 0` |
| 261 MB 定制 Wine 运行时 | `~/.local/share/yun-genshin-linux/runtime` 实测（已 strip） |
| +4400 行 / 25 个文件 | `README.md` 补丁说明；`patches/wine/*.patch` 实测 4864 行 |
| 客户端更新自动适配 | `docs/architecture.md` —— `client_fingerprint()` + 按导出名挂钩 FFmpeg |
| 开箱即用 | `scripts/install.sh` + `yun-genshin` 两条命令 |
| 与米哈游无关联、不分发客户端 | `README.md` 声明 |

## 修改注意

- 改动 `poster.html` 后**必须**重跑 `qa.py`：PNG 与 PDF 任一路渲染缺失文字，
  交叉比对会报出来；OCR 一节能确认每句文案确实画上去了。
- 页面高度不要写死，改文案后若 `content.scrollHeight` 超过画布高度，
  `render.mjs` 的自检会在 `overflows` 里报元素越界。
- 别引入米哈游客户端截图或 Logo：项目明确声明与米哈游无关，不分发客户端本体。
