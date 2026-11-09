# tools/

## vkext.c — Vulkan 设备扩展枚举自检

用途：验证**打包后的运行时**能否枚举到 `VK_KHR_video_decode_h265`。
这是整套项目最关键的单项检查（详见 `docs/checklist.md` 第 3 节）。

```bash
x86_64-w64-mingw32-gcc -o vkext.exe vkext.c
WINEPREFIX=/tmp/probe ../runtime/bin/wine ./vkext.exe | grep h265
```

期望输出：

```
  VK_KHR_video_decode_av1
  VK_KHR_video_decode_h264
  VK_KHR_video_decode_h265     ← 这条必须在
  VK_KHR_video_decode_queue
  VK_KHR_video_decode_vp9
```

### 为什么这条检查最重要

Wine 默认在 `dlls/winevulkan/make_vulkan` 的 `UNSUPPORTED_EXTENSIONS` 里
列了 `VK_KHR_video_decode_h265`，导致**即使驱动支持，Wine 进程也枚举不到**。
补丁 `0000-winevulkan-allow-h265.patch` 就是删掉这一行。

而且这条检查同时验证了**最容易出错的一对组合**：

- `winevulkan.dll`（Windows 侧，放行 h265）
- `win32u.so`（Unix 侧，含 `vulkan_device_extensions` 结构）

`include/wine/vulkan.h` 加了 H.265 结构后，`vulkan_device_extensions` 布局改变。
如果 `win32u.so` 不是同批编译，旧结构会让
`vkCreateVideoSessionKHR` / `vkCreateVideoSessionParametersKHR` /
`vkCmdBeginVideoCodingKHR` 的指针变成 **NULL**，
客户端表现为 `c0000005 @ 0`（RIP=0）——
而同一个 `vkCmdDecodeVideoKHR` 却非 NULL，**极具误导性**。

⇒ 这条检查通过 ⇒ 发行产物的 ABI 组合是对的。
