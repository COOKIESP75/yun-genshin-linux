# 云原神 Linux 整合应用（yun-genshin-linux）

[English](#english) | [简体中文](#这是什么)

通过打过补丁的 Wine 在 Linux 上运行**云原神** Windows 客户端，并尝试使用 Vulkan H.265 GPU 硬件解码；这不是客户端的原生 Linux 重写。

![云原神 Linux 项目展示海报](docs/showcase/github-poster.png)

[交互式模型展示](docs/showcase/model-viewer-standalone.html)（GitHub 不直接运行 HTML；请下载后在浏览器中打开） · [Tux Ubuntu 3D 模型](docs/showcase/tux-ubuntu.glb)

Tux、Ubuntu 和云原神相关素材的权利与本项目代码的 MIT 许可证不同，使用时请分别确认其适用条款。

---

## English

**yun-genshin-linux** runs **Genshin Impact Cloud** (云原神, miHoYo's official Windows cloud-gaming client) on Linux using patched **Wine**; it is not a native Linux rewrite. The patches aim to enable GPU hardware decoding using Vulkan H.265/HEVC where supported.

| Highlights | |
|---|---|
| **GPU hardware decoding** | Targets Vulkan `VK_KHR_video_decode_h265`; support depends on the GPU, driver and video capabilities |
| **GPU presentation path** | Aims for decode → texture → Vulkan swapchain without CPU readback or upload when the supported path is active |
| **Update handling** | Re-deploys patches and re-validates after client updates; compatibility with future updates is not guaranteed |
| **Linear mouse input** | Addresses X11 pointer acceleration causing inconsistent sensitivity |
| **Runtime** | A complete patched Wine runtime must be obtained or assembled separately; it is not included in this public repository |

> ⚠ **This project does not distribute miHoYo's client and is not affiliated with miHoYo.** First launch guides you through downloading the official installer (`yscloud_*.exe`) from miHoYo's official API and installing it in an isolated Wine prefix.

**Availability:** The public repository does not include the runtime, and there is currently no Release. A fresh clone cannot run as-is. For contributors, [`scripts/build-wine.sh`](scripts/build-wine.sh) builds Wine and collects patched DLLs and `win32u.so`, but does **not** package a complete runtime (including `bin/` and the full `lib/`). A complete compatible runtime must be assembled separately before installation; see [building from source](#从源码构建定制-wine).

Once a complete runtime is available, the intended installation and launch commands are:

```bash
# 1. Install to ~/.local/share/yun-genshin-linux
./scripts/install.sh

# 2. Launch (first run guides you through the official client download)
~/.local/bin/yun-genshin
```

Requires Linux (X11) and a compatible Vulkan driver; hardware decoding additionally requires the relevant Vulkan Video H.265 capabilities. NVIDIA, AMD or Intel branding alone does not guarantee support.
Full documentation, Wine patch details, build instructions and FAQ: see the [简体中文 section](#这是什么) below.

---

## 这是什么

云原神的官方客户端只有 Windows 版。本项目通过定制 Wine 和补丁运行 Windows 客户端，
尝试改善 GPU 解码、画面和鼠标手感；实际效果取决于运行环境和客户端版本。公开仓库不含完整运行时，目前也没有 Release，克隆后不能直接运行。

**本项目不分发米哈游的客户端本体** —— 应用会引导你从官方渠道下载安装。

---

## 特性

| | 说明 |
|---|---|
| **GPU 硬件解码** | 目标是 Vulkan `VK_KHR_video_decode_h265`；需显卡及驱动支持对应视频能力，NVIDIA/AMD/Intel 型号并非均可用 |
| **GPU 上屏路径** | 支持路径生效时，目标是解码 → 纹理 → Vulkan swapchain，避免 CPU 回读和上传 |
| **客户端更新处理** | 更新后重新部署补丁并做健康校验，不保证兼容后续所有客户端版本 |
| **线性鼠标手感** | 修正 X11 指针加速造成的「灵敏度忽快忽慢」 |
| **运行时** | 公开仓库不包含完整定制 Wine，需另行准备 |

---

## 快速开始

**前提**：目前没有可下载的 Release，仓库也不含完整运行时，不能仅凭克隆仓库执行以下命令。贡献者可先参考[从源码构建定制 Wine](#从源码构建定制-wine)：脚本仅收集补丁 DLL 和 `win32u.so`，不会打包包含 `bin/` 和完整 `lib/` 的运行时；完整兼容运行时需另行组装。还需要 Linux（X11）及兼容 Vulkan 驱动，硬解需设备支持相应 Vulkan Video H.265 能力。

准备好完整运行时后，预期的安装与启动命令如下：

```bash
# 1. 安装到 ~/.local/share/yun-genshin-linux
./scripts/install.sh

# 2. 启动（首次会引导下载官方客户端）
~/.local/bin/yun-genshin
```

首次运行会：

1. 检查应用所需的 Python、GTK4 等依赖（Vulkan 视频解码能力需另行确认）
2. 引导你从米哈游官方 API 下载 Windows 客户端安装包（`yscloud_*.exe`）
3. 在隔离的 Wine prefix 中安装客户端
4. 部署补丁 DLL
5. 启动客户端

---

## 目录结构

```
yun-genshin-linux/
├── README.md
├── LICENSE                    # 本项目代码的许可证（见下）
├── scripts/
│   ├── install.sh             # 安装到 ~/.local/share
│   ├── uninstall.sh
│   └── build-wine.sh          # 从源码构建定制 Wine（贡献者用）
├── patches/wine/
│   ├── 0000-winevulkan-allow-h265.patch
│   └── 0001-yg-hevc-vulkan-harddecode.patch
├── runtime/                   # 完整运行时的预期位置（公开仓库不含）
│   ├── lib/wine/x86_64-windows/{wined3d,d3d11,dxva2,d3d9,win32u,winevulkan}.dll
│   ├── lib/wine/x86_64-unix/win32u.so
│   └── bin/wine ...
└── src/                       # 应用逻辑（Python + GTK4）
```

---

## 补丁说明

补丁基于 **Wine 11.0**，共 25 个文件、约 +4400 行，分两类：

### `0000-winevulkan-allow-h265.patch`（1 行）

`dlls/winevulkan/make_vulkan` 的 `UNSUPPORTED_EXTENSIONS` 列表里删掉了
`VK_KHR_video_decode_h265`。Wine 默认把它过滤掉，导致 Wine 进程枚举设备时
看不到这个扩展 —— 即使驱动支持。

> ⚠ 这个补丁必须先打：改完之后 `make_vulkan` 重新生成
> `include/wine/vulkan.h` 和 `dlls/winevulkan/vulkan_thunks.c`
> （这两个文件是**自动生成**的，不在补丁里）。

### `0001-yg-hevc-vulkan-harddecode.patch`（主补丁）

| 组件 | 改动 |
|---|---|
| `dlls/wined3d/decoder.c` | H.265 硬解：真实 VPS/SPS/PPS 码流解析、RPS 槽位映射、参考帧管理、YUV blit |
| `dlls/d3d11/` | FFmpeg 硬件帧探测钩子、I420→NV12 上传、DXVA 兼容层 |
| `dlls/d3d9/`, `dlls/dxva2/` | 视频解码路径的 D3D9/DXVA2 兼容修补 |
| `dlls/wined3d/{surface,texture_vk,swapchain,view,utils,adapter_vk,context_vk}.c` | Vulkan 路径的 NV12 双平面支持、着色器转换、swapchain 修正 |
| `dlls/wined3d/wined3d.spec` 等 | 导出符号 |

### 关键实现要点

- **真实参数集**：客户端把 VPS/SPS/PPS 放在码流包里，补丁在
  `avcodec_send_packet` 处提取 NAL（类型 32/33/34），自己解析成
  `StdVideoH265*` 结构，用于创建 Vulkan session parameters。
  *不能*用 DXVA 里的标量合成 —— 那样没有 short-term RPS，驱动会误读 slice header。

- **RPS 槽位语义**（踩过的坑）：DXVA 的 `RefPicSetStCurrBefore[]` 存的是
  **RPS 位置**（参考图在短期参考集里的序号），**不是** DXVA surface index。
  把它当 surface index 去反查 DPB 槽位会永远查不到（原值 0 被原样传给驱动），
  导致驱动每帧都读 DPB slot 0，而真实参考帧在另一个槽位 ——
  **一半 P 帧用错参考帧**，表现为撕裂/重影/黑屏。

- **FFmpeg 钩子按导出名查找**：`GetProcAddress(h, "avcodec_open2")`，
  不是硬编码偏移 —— 客户端升级换 FFmpeg 版本也能自适应。

- **`win32u.so` 必须一起重建**：`include/wine/vulkan.h` 加了 h265 后，
  `vulkan_device_extensions` 结构布局改变；旧 `win32u.so` 会导致
  `vkCreateVideoSessionKHR` 等函数指针为 NULL（表现为 `c0000005 @ 0`）。

---

## 从源码构建定制 Wine

以下是贡献者构建补丁产物的路径，需要网络、Wine 构建依赖和编译工具。脚本不会生成可直接安装使用的完整运行时：它只收集下列 DLL 和 `win32u.so`，完整的 `bin/` 与 `lib/` 需要另行打包；具体打包可参考 `docs/packaging.md`。

```bash
./scripts/build-wine.sh
```

流程：

1. 取 Wine 11.0 源码
2. 依次打 `patches/wine/*.patch`
3. 跑 `make_vulkan`（需要网络，会从 Khronos 下载 `vk.xml` 1.4.335）
4. `make -j$(nproc)`
5. 收集并 strip 下列文件：

   ```
   lib/wine/x86_64-windows/{wined3d,d3d11,dxva2,d3d9,win32u,winevulkan}.dll
   lib/wine/x86_64-unix/win32u.so
   ```

---

## 常见问题

**画面全黑 / 只有黑窗口**
先看 `~/.local/share/yun-genshin-linux/logs/wine.log` 里有没有 `yg-h265` 字样。
没有 = 客户端没走 HEVC 路径，检查 `winevulkan.dll` 是否部署到位。

**「Received first frame」但屏幕是黑的**
客户端日志里的这句话**不等于**屏幕有画面 —— 它只表示客户端收到了首帧。
本项目用**像素级非黑**作为判据。

**画面撕裂 / 帧卡**
客户端日志里的 `Video jank over 1000` 是**服务端**视频流的帧间隔，
与本地解码无关。可尝试重启客户端或更换节点。

**鼠标灵敏度忽快忽慢**
X11 指针加速是非线性的。运行 `scripts/fix-pointer-accel.sh` 改为纯线性。

---

## 致谢

- **Wine** —— 项目的基石，LGPL-2.1
- **Khronos Vulkan** —— 硬解依赖 `VK_KHR_video_decode_h265`
- 米哈游 —— 云原神客户端

## 许可证

本项目**自己的代码**（`src/`、`scripts/`、文档）采用 MIT 许可证，
见 [LICENSE](LICENSE)。

`patches/` 下的 Wine 补丁及另行打包的 Wine 二进制是 Wine 衍生物，
遵循 **Wine 的 LGPL-2.1**。Tux、Ubuntu 和云原神相关名称、形象及素材的权利另属于其各自权利人，不随本项目代码的 MIT 许可证授予。

**注意**：本项目与米哈游无任何关联，不包含、不分发云原神客户端。
