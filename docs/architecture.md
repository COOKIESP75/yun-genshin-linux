# 架构说明

## 全景

```
┌──────────────────────────────────────────────────────────────┐
│  用户                                                          │
│   ├─ 图形界面 (GTK4)      src/app.py                          │
│   └─ 命令行               yun-genshin --check/--launch/...     │
└────────────────────────────┬─────────────────────────────────┘
                             │
              ┌──────────────▼──────────────┐
              │  应用层 (Python)              │
              │   runtime.py  目录布局/补丁部署/健康检查 │
              │   client.py   官方客户端引导/更新检测      │
              └──────────────┬──────────────┘
                             │
   ┌─────────────────────────▼──────────────────────────┐
   │  ~/.local/share/yun-genshin-linux/                   │
   │    runtime/   定制 Wine 11.0 (261MB, stripped)        │
   │      bin/wine                                      │
   │      lib/wine/x86_64-windows/*.dll  ← 补丁版         │
   │      lib/wine/x86_64-unix/win32u.so  ← 补丁版(关键)   │
   │    prefix/    隔离的 Wine prefix（含客户端）          │
   │      drive_c/windows/system32/*.dll  ← 补丁版(第二份)  │
   │      drive_c/users/<u>/AppData/.../GenshinImpactCloudGame/  │
   │    logs/      wine.log                               │
   └─────────────────────────┬───────────────────────────┘
                             │
                    ┌────────▼────────┐
                    │  云原神客户端      │  ← 米哈游官方 exe，不随包分发
                    │  (自带 FFmpeg 等)  │
                    └────────┬────────┘
                             │ RTC/UDP 流
                    ┌────────▼────────┐
                    │  微信服务器       │
                    └──────────────────┘
```

## 三个关键设计决策

### 1. 为什么补丁要放两处（Wine 安装目录 + prefix/system32）

Wine 加载 DLL 的顺序是：应用目录 → prefix/system32 → Wine 安装目录。

- 客户端自带的 `avcodec-61.dll` 等在**应用目录**，我们不动它。
- 我们改的 `wined3d.dll` / `d3d11.dll` / `dxva2.dll` / `d3d9.dll` 是 Wine 的组件，
  必须放 **prefix/system32**（这样 prefix 优先于系统 Wine）**和** Wine 安装目录
  （这样即使 prefix 被重建也不丢）。

⚠ **实测结论**：`WINEDLLPATH` **不能**覆盖 prefix/system32 里的同名 DLL
（用 `d1.dll`/`d2.dll` 对照实验验证过：WINEDLLPATH 指向别处时，加载的仍是 system32 那份）。
所以「双份部署」不是冗余，是必需的。

### 2. 为什么 `win32u.so` 必须在 Wine 安装目录

`include/wine/vulkan.h` 里加了 H.265 结构后，`vulkan_device_extensions`
这个结构体布局变了。它被 `dlls/win32u/vulkan.c` 消费 —— 而 win32u 的
Vulkan 相关代码编译进的是 **Unix 侧的 `win32u.so`**（不是 `win32u.dll`）。

如果 `win32u.so` 是旧的：
- `init_physical_device` 会认为设备未启用 video_queue
- `host vkGetDeviceProcAddr` 对 `vkCreateVideoSessionKHR` /
  `vkCreateVideoSessionParametersKHR` / `vkCmdBeginVideoCodingKHR` 返回 **NULL**
- 客户端表现为 `c0000005 @ 0`（RIP=0，执行空指针）

同一个 `vkCmdDecodeVideoKHR` 却非 NULL —— **极具误导性**，会让人以为是解码器的问题。

⇒ **凡是消费 `ALL_VK_DEVICE_EXTS` 的模块都必须一起重建**：
`winevulkan.so`、`winevulkan.dll`、`win32u.so`、`wined3d.dll`。

### 3. 为什么客户端更新不会破坏补丁

客户端安装包（`yscloud_*.exe`）只往
`drive_c/users/<u>/AppData/Local/Programs/miHoYo/GenshinImpactCloudGame/` 解压。
我们改的 `drive_c/windows/system32/` 与 Wine 安装目录**完全隔离**。

但客户端**自带** `avcodec-61.dll` / `avutil-59.dll`，我们的 FFmpeg 钩子打在这些库上。
钩子用 `GetProcAddress(h, "avcodec_open2")` 按**导出名**查找（不是硬编码偏移），
所以客户端换 FFmpeg 版本也能自适应。

仍需校验：客户端更新后 `avcodec` 的导出名是否变化 → 用 `client_fingerprint()`
（exe + avcodec + avutil 的 sha256）检测变化 → 重新部署补丁 + 校验。

---

## 数据流（HEVC 硬解）

```
云端编码 H.265 → RTC/UDP → 客户端 FFmpeg (avcodec_send_packet)
   │
   │  d3d11 的 FFmpeg 钩子在此提取 VPS/SPS/PPS NAL (类型 32/33/34)
   │  → wined3d_yg_h265_set_params() → 解析成 StdVideoH265* 结构
   │
   ▼
D3D11VA 硬件解码请求 → d3d11 → wined3d_decoder_vk_decode_h265()
   │
   ├─ create_h265_params() 用真实参数集建 Vulkan session parameters
   ├─ 解析 slice → 构建 RefPicSet → vkCmdDecodeVideoKHR
   ├─ 提交到 decode queue（vkQueueSubmit）
   └─ wined3d_decoder_vk_blit_output() 把解码结果拷到客户端的输出纹理
   │
   ▼
客户端 CopySubresourceRegion → 自己的渲染纹理 → Vulkan swapchain → 屏幕
```

**全程在 GPU**：没有 `vkCmdCopyImageToBuffer` 回读、没有 CPU 上传。
日志判据：`yg-upload` = 0、`yg-nv12` = 0。

---

## RPS 语义（本项目最核心的坑）

DXVA 的 `RefPicSetStCurrBefore[8]` 存的是 **RPS 位置**
（参考图在短期参考集里的序号），**不是** DXVA surface index。

错误做法（11-08 的实现）：

```c
/* ✗ 把 RPS 位置当 surface index 去反查 DPB 槽位 */
find_reference_slot_quiet(decoder_vk, params->RefPicSetStCurrBefore[i], &ref_slot);
```

`find_reference_slot_quiet()` 按 `images[].dxva_index == 查到的值` 匹配。
而 RPS 位置通常就是 **0**；`images[].dxva_index` 实际是 14~19 这种
（客户端复用 DXVA surface index），**永远查不到 0** ⇒
查表失败 ⇒ 原值 0 被原样传给驱动。

结果：驱动每帧都去读 **DPB slot 0**，而真实参考帧在另一个槽位
（本流是纯 P 链，参考帧在 slot 0/1 之间交替）⇒ **一半 P 帧用错参考帧**
⇒ 撕裂 / 重影 / 黑屏。

正确做法：构建 `pReferenceSlots` 时顺带记录每个参考项的 DPB 槽位，
再用 RPS 位置索引它。

```c
unsigned int ref_dpb_slot[ARRAY_SIZE(params->RefPicList)];
/* 构建参考列表时： ref_dpb_slot[i] = slot_index; */

for (yg_i = 0; yg_i < 8; ++yg_i) {
    unsigned int rps_pos = params->RefPicSetStCurrBefore[yg_i];
    if (rps_pos == 0xff || rps_pos >= ARRAY_SIZE(ref_dpb_slot)) continue;
    if (ref_dpb_slot[rps_pos] == 0xff) continue;
    h265_picture.RefPicSetStCurrBefore[yg_i] = (uint8_t)ref_dpb_slot[rps_pos];
}
```

诊断日志字段 `rps0`（原 RPS 位置 `->` 解析出的槽位）就是为此加的：

```
REFMAP cur dxva 16 -> pool 0 poc 4 | StB 1 255 255 255 | rps0 0->1
                                  ^^^^^^^^^^^^^^^^^^^^   ^^^^^^
                                  随参考帧槽位交替 = 正确
```

---

## 判据陷阱

### 「截图非黑」≠「解码成功」

客户端**首页 UI 本身就是非黑的**（35 万色，与正常游戏帧的像素差只有 0.03）。
⇒ 判据必须是三条同时成立：

1. 客户端日志有 `Connect succ` + `Received first frame`
2. wine 日志有 `yg-h265` / `decode_queue_submit`
3. 抓到的是**游戏窗口**（不是首页）

`src/app.py` 和 `src/runtime.py` 的健康检查都按这个标准。

### 限流日志 ≠ 真实计数

`yg-frame`(8 次)、`yg-getbuf`(30)、`send_packet`(12/32)、`yg-copyres`(3)、
`cmdDecode`(5) 全是**限流**的。曾据此得出「解码停摆、逐轮递减」的错误结论。

真实计数用**未门控**的：`decode_queue_submit`、`acquire_next_image`，
或本项目新增的 `yg-dec counter decoded/presented`（每 128 帧一条）。

### 帧率看中位数，不看均值

长尾停顿会把 62.5fps 的中位数拉成 42.6fps 的均值。
