# 打包与分发

## 产物构成

| 组成 | 体积 | 说明 |
|---|---|---|
| `runtime/` | **261 MB** | 定制 Wine 11.0（stripped，去 32 位） |
| ├ `bin/wine` + `share/` | ~15 MB | Wine 启动器与数据 |
| └ `lib/wine/` | ~247 MB | 1025 个 DLL + win32u.so（**含全部补丁**） |
| `patches/` | ~210 KB | 源码补丁（供贡献者重建） |
| `src/` + `scripts/` | ~50 KB | 应用逻辑 |

**客户端本体（462 MB）不分发** —— 由用户从米哈游官方渠道获取。

## 瘦身过程

| 阶段 | 体积 |
|---|---|
| 原始 `wine-patched/`（debug 构建，含 32 位） | 1.6 GB |
| → 去掉 `i386-windows` + `i386-unix`（客户端是 PE32+） | ~1.0 GB |
| → strip 全部 PE/ELF（去掉 `-g` 调试符号） | **261 MB** |

去掉 32 位 Wine 是安全的：客户端 exe 是 `PE32+`，纯 64 位运行。
若将来客户端引入 32 位组件，`scripts/build-runtime.sh --keep32` 可保留。

## 构建流程（贡献者）

```bash
./scripts/build-wine.sh      # 从源码构建补丁版 Wine，产出补丁 DLL
./scripts/build-runtime.sh   # 组装完整运行时（含 strip / 去 32 位）
```

`build-wine.sh` 做的事：

1. clone Wine 11.0 源码
2. 依次打 `patches/wine/*.patch`
3. 跑 `make_vulkan`（**需要网络**，从 Khronos 下载 `vk.xml` 1.4.335）
4. `./configure && make -j$(nproc)`
5. 收集 7 个补丁文件并 strip

⚠ `build-wine.sh` 里的 `make_vulkan` 会**重新生成**
`include/wine/vulkan.h` 和 `dlls/winevulkan/vulkan_thunks.c`
—— 这两个文件是自动生成的，**不在补丁里**。改了 `make_vulkan` 就必须重新生成。

## 发布检查清单

- [ ] `runtime/sha256.txt` 与实际文件一致
- [ ] `runtime/lib/wine/x86_64-windows/wined3d.dll` 含 `rps0` 诊断字段（RPS 修复在）
- [ ] `runtime/lib/wine/x86_64-unix/win32u.so` 与 wined3d **同批构建**（ABI 一致）
- [ ] 运行时能枚举到 `VK_KHR_video_decode_h265`
- [ ] 端到端：干净 prefix → 装客户端 → 出画面（**像素级非黑**，不是只看客户端日志）

### h265 扩展自检

```bash
WINEPREFIX=/tmp/probe /path/to/runtime/bin/wine ./vkext.exe | grep h265
# 期望输出：VK_KHR_video_decode_h265
```

`vkext.c` 在 `ctfwork/p0/tools/`（开发目录），也可以自己写一个：
`vkEnumerateDeviceExtensionProperties` 枚举物理设备的扩展。

## 分发形式

### 方案 A：tarball + install.sh（当前实现，最简单）

```bash
tar xf yun-genshin-linux-0.1.0.tar.gz
cd yun-genshin-linux
./scripts/install.sh
yun-genshin
```

### 方案 B：AppImage

需要在 CI 里做一个 AppDir：

```
yun-genshin-linux.AppDir/
├── AppRun              → exec "$APPDIR/usr/bin/yun-genshin"
├── usr/
│   ├── bin/yun-genshin
│   ├── lib/yun-genshin-linux/   ← runtime + src
│   └── share/applications/
└── yun-genshin-linux.desktop
```

用 `appimagetool` 打包。⚠ AppImage 里 Wine 要能访问 GPU 驱动
（`/usr/lib` 里的 Vulkan ICD 必须在宿主上，`LD_LIBRARY_PATH` 不能覆盖 ICD 路径）。

### 方案 C：Flatpak

优点：沙箱化、依赖打包、更新走 Flathub。
难点：Wine + Vulkan + 宿主 GPU 驱动的沙箱访问（`--device=dri`，
ICD 文件通过 `flatpak-spawn --host` 访问）。

### 方案 D：原生包（deb/rpm）

最符合发行版习惯，但每个发行版要单独打，
且 `win32u.so` 需要替换系统 Wine 的文件 → **与发行版的 Wine 冲突**，
建议用方案 A/B/C 并把 Wine 放在应用私有目录。

## 版本号策略

| 版本 | 含义 |
|---|---|
| 应用版本 `0.1.0` | 应用逻辑 + 补丁集的版本 |
| Wine 基线 | 固定 11.0（补丁依赖这个基线） |
| 客户端版本 | **不控制** —— 客户端自行更新，应用适配 |

补丁更新时：应用版本 +1，`runtime/sha256.txt` 更新，
`client.py` 的 `client_fingerprint()` 检测到客户端变化时自动重部补丁。

---

## 上传前检查（已执行）

### 已修复的可移植性问题

| 位置 | 问题 | 修法 |
|---|---|---|
| `src/runtime.py` | 客户端路径写死 `drive_c/users/ax210/...` | 扫 `prefix/drive_c/users` 动态解析 |
| `patches/wine/0001` | `dlls/d3d9/video.c` 的诊断 dump 写死 `C:\users\ax210\...\Temp\` | 改为相对当前目录 `.\yg_*.bin` |
| `scripts/build-runtime.sh` | 用了本机 safe-rm 插件的绝对路径 | 改为 `trash(1)` 或 `rm -rf` 的通用实现 |
| `patches/wine/0001` | 含 `make_vulkan` 的改动，与 `0000` 重复导致 patch 冲突 | 从 0001 中排除 |

第一条不只是洁癖：**换个用户名客户端就找不到**，会让应用在别人机器上直接不可用。

### 提交内容

git 仓库只含源码与补丁（~470KB），**不含** 261MB 的运行时
（`runtime/` 在 `.gitignore` 里，由 `scripts/build-runtime.sh` 生成）。

发布时需要另行上传运行时产物（tarball / AppImage，见上）。

### 当前未上传的部分

- **无 git remote** —— 纯本地仓库
- 运行时未进版本库（体积原因）
- 未做签名、校验和、镜像
