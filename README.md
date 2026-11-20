# 云原神 Linux 整合应用（yun-genshin-linux）

[English](#english) | [简体中文](#这是什么)

在 Linux 上原生运行**云原神**（米哈游云游戏 Windows 客户端），通过给 Wine 打补丁，
让客户端走 **GPU 硬件解码**（Vulkan H.265），而不是 CPU 软解。

---

## English

**yun-genshin-linux** runs **Genshin Impact Cloud** (云原神， miHoYo's official cloud-gaming Windows client) natively on **Linux**. It ships a patched **Wine** runtime so the client renders through **GPU hardware decoding** (Vulkan H.265/HEVC) instead of CPU software decoding.

| Highlights | |
|---|---|
| **GPU hardware decoding** | Vulkan `VK_KHR_video_decode_h265`, works on NVIDIA / AMD / Intel, zero CPU readback or upload |
| **Pure GPU presentation** | decode → texture → Vulkan swapchain, no memory round-trip |
| **Self-healing updates** | re-deploys patches and re-validates after the client self-updates |
| **Linear mouse input** | fixes X11 pointer acceleration causing inconsistent sensitivity |
| **Batteries included** | prebuilt patched Wine runtime (~350 MB), no manual Wine compilation |

> ⚠ **This project does not distribute miHoYo's client and is not affiliated with miHoYo.** First launch guides you through downloading the official installer (`yscloud_*.exe`) from miHoYo's official API and installing it in an isolated Wine prefix.

```bash
# 1. Install to ~/.local/share/yun-genshin-linux
./scripts/install.sh

# 2. Launch (first run guides you through the official client download)
~/.local/bin/yun-genshin
```

Requires: Linux (X11) with a Vulkan-capable GPU driver (NVIDIA / AMD / Intel).
Full documentation, Wine patch details, build instructions and FAQ: see the [简体中文 section](#这是什么) below.

---

## 这是什么

云原神的官方客户端只有 Windows 版。本项目提供一套定制 Wine 运行时 + 补丁，
让 Linux 用户可以直接玩，并获得 GPU 硬解、正确的画面和正常的鼠标手感。

**本项目不分发米哈游的客户端本体** —— 应用会引导你从官方渠道下载安装。

---

## 特性

| | 说明 |
|---|---|
| **GPU 硬件解码** | Vulkan `VK_KHR_video_decode_h265`（NVIDIA/AMD/Intel 通用），零 CPU 回读、零 CPU 上传 |
| **纯 GPU 上屏** | 解码 → 纹理 → Vulkan swapchain，全程不回读内存 |
| **自动适配客户端更新** | 客户端自行更新后自动重新部署补丁并做健康校验 |
| **线性鼠标手感** | 修正 X11 指针加速造成的「灵敏度忽快忽慢」 |
| **开箱即用** | 自带定制 Wine 运行时（约 350 MB），无需用户自行编译 Wine |

---

## 快速开始

```bash
# 1. 安装到 ~/.local/share/yun-genshin-linux
./scripts/install.sh

# 2. 启动（首次会引导下载官方客户端）
~/.local/bin/yun-genshin
```

首次运行会：

1. 检查系统依赖（Vulkan 驱动、图形库等）
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
├── runtime/                   # 预编译的定制 Wine（发行物）
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

`patches/` 下的 Wine 补丁和 `runtime/` 里的预编译二进制是 Wine 衍生物，
遵循 **Wine 的 LGPL-2.1**（见 `runtime/LICENSE.wine`）。

**注意**：本项目与米哈游无任何关联，不包含、不分发云原神客户端。
