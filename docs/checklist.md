# 发行前自检清单

每条都给出**可执行的验证命令**，不靠主观判断。

## 1. 补丁集正确性

```bash
# 从干净 Wine 11.0 源码验证补丁能干净应用
cd /path/to/clean/wine-11.0
git apply --check ../patches/wine/0000-winevulkan-allow-h265.patch
git apply --check ../patches/wine/0001-yg-hevc-vulkan-harddecode.patch
```

**判据**：两个都无输出（`--check` 成功时静默）。

验证「补丁应用结果 == 开发时的源码」：

```bash
# 对每个被改文件比对
diff <(cd baseline && cat file) <(cd patched && cat file)
```

**判据**：23 个文件字节级一致；另外 2 个
（`include/wine/vulkan.h`、`dlls/winevulkan/vulkan_thunks.c`）
由 `make_vulkan` 自动生成，**本就不该在补丁里**。

## 2. 运行时完整性

```bash
cd runtime
# 哈希清单与实际一致
( cd lib/wine/x86_64-windows && sha256sum -c ../../sha256.txt 2>/dev/null ) || true
sha256sum -c sha256.txt --ignore-missing 2>&1 | grep -v "No such" | grep -v OK
```

**判据**：无 FAILED 行。

## 3. H.265 硬解通道（最关键）

这是整套东西的核心 —— Wine 默认把 `VK_KHR_video_decode_h265` 过滤掉，
且 `win32u.so` 与 `wined3d.dll` 必须同批编译（ABI 对齐）。

```bash
WINEPREFIX=/tmp/probe ./bin/wine ./vkext.exe | grep h265
```

**判据**：输出包含 `VK_KHR_video_decode_h265`。

> `vkext.c` 是一个 40 行的小程序：枚举 Vulkan 物理设备扩展。
> 放在 `ctfwork/p0/tools/`（开发目录），也可自行实现。

如果这里失败，两种可能：

| 症状 | 原因 |
|---|---|
| 扩展整个不出现 | `winevulkan.dll` 没换成补丁版，或 `make_vulkan` 没重新生成 |
| 扩展出现但客户端 `c0000005 @ 0`（RIP=0） | `win32u.so` 与 `wined3d.dll` **不是同批构建** → ABI 错位 → `vkCreateVideoSessionKHR` 为 NULL |

## 4. 补丁确实被加载

```bash
strings runtime/lib/wine/x86_64-windows/wined3d.dll | grep -c "rps0"
```

**判据**：输出 ≥ 1（`rps0` 是 RPS 修复的诊断字段，存在即补丁在）。

## 5. 部署链路

```bash
./scripts/install.sh
yun-genshin --check
```

**判据**：
- `补丁：正常`
- 唯一可能存在的提示是 `未安装云原神客户端`（首次运行前正常）

```bash
# 部署后 prefix 里的补丁与 runtime 一致
sha256sum ~/.local/share/yun-genshin-linux/prefix/drive_c/windows/system32/wined3d.dll \
          ~/.local/share/yun-genshin-linux/runtime/lib/wine/x86_64-windows/wined3d.dll
```

**判据**：两个哈希相同。

## 6. 客户端更新后仍可用（可选但推荐）

```bash
# 1. 记录当前指纹
python3 -c "import sys; sys.path.insert(0,'src'); \
from client import ClientBootstrap; from runtime import Layout; \
print(ClientBootstrap(Layout.create()).mgr.client_fingerprint())"

# 2. 客户端更新后，重新检测
yun-genshin --sync
```

**判据**：`检测到客户端已更新，重新部署补丁` → `✓ 补丁已适配新客户端`。

## 7. 画面验证（需要客户端实际进游戏）

⚠ **判据必须像素级**。「客户端日志有 `Received first frame`」**不等于**屏幕有画面
—— 客户端首页 UI 本身就非黑（35 万色，与正常帧像素差仅 0.03）。

```bash
# 抓到游戏窗口后
import -window <GAME_WID> /tmp/shot.png
python3 - <<'PY'
from PIL import Image
from collections import Counter
im = Image.open('/tmp/shot.png').convert('RGB')
c = Counter(im.getdata()); tot = sum(c.values())
print('distinct=%d black=%.1f%%' % (len(c), 100*c.get((0,0,0),0)/tot))
PY
```

**判据**：`distinct` 远大于 1000 且 `black` 远小于 90%
（首页 UI 也有 35 万色，所以还要确认这是**游戏窗口**而非首页）。

同时看 wine 日志：

```bash
grep -a "yg-dec counter" ~/.local/share/yun-genshin-linux/logs/wine.log | tail -4
```

**判据**：`decoded` 与 `presented` 同步增长且大致相等。

## 8. 性能

```bash
# 从 yg-dec counter 的时间戳算帧率（中位数，不要看均值）
```

**判据**：帧间隔中位数 ≤ 18ms（≥55fps）。

⚠ **均值会被长尾停顿拉低**：实测中位数 62.5fps 时均值只有 42.6fps。

---

## 已知的、非缺陷的现象

| 现象 | 说明 |
|---|---|
| `libEGL warning: egl: failed to create dri2 screen` | 客户端会拉起 EGL 做能力探测，无害（正常环境下同样出现） |
| `Video jank over 1000, current value:3665` | **服务端**视频流的帧间隔，与本地解码无关。10-26 那条画面正常的 H.264 路径同样有 6567ms 的 jank |
| `wined3d_allocator_chunk_cleanup Chunk ... is not empty` | 解码器销毁时会话参数释放不干净，长期运行可能泄漏，尚未修 |
| 客户端停在首页不 dispatch | 服务端队列波动，与本项目无关 |
