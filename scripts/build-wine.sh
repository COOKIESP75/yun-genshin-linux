#!/usr/bin/env bash
# build-wine.sh — 从源码构建定制 Wine（贡献者用）
#
# 流程：
#   1. 取 Wine 11.0 源码（默认从 gitlab 官方仓库 clone）
#   2. 依次打 patches/wine/*.patch
#   3. 跑 make_vulkan（会从 Khronos 下载 vk.xml 1.4.335，需要网络）
#   4. 编译
#   5. 收集并 strip 补丁文件到 runtime/
#
# ⚠ 关键坑：include/wine/vulkan.h 加了 h265 之后，
#   `vulkan_device_extensions` 结构布局改变 ⇒ 消费它的模块必须一起重建，
#   尤其是 **win32u.so**（Unix 侧，含 dlls/win32u/vulkan.c）。
#   旧 win32u.so 会让 vkCreateVideoSessionKHR 等函数指针为 NULL，
#   表现为客户端 c0000005 @ 0（RIP=0）。
set -u

SRC_DIR=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
BUILD_DIR=${BUILD_DIR:-$SRC_DIR/build/wine}
JOBS=${JOBS:-$(nproc)}
STRIP=${STRIP:-1}

log(){ echo "[build] $*"; }
die(){ echo "[build] ✗ $*" >&2; exit 1; }

command -v git >/dev/null || die "需要 git"
command -v make >/dev/null || die "需要 make"

# ---- 1. 源码 ----
if [ ! -d "$BUILD_DIR" ]; then
    log "克隆 Wine 11.0 源码 …"
    git clone --depth 1 --branch wine-11.0 \
        https://gitlab.winehq.org/wine/wine.git "$BUILD_DIR" \
        || die "克隆失败"
else
    log "复用已有源码树 $BUILD_DIR"
fi

cd "$BUILD_DIR" || die "进不去 $BUILD_DIR"

# ---- 2. 打补丁 ----
for p in "$SRC_DIR"/patches/wine/*.patch; do
    [ -e "$p" ] || continue
    name=$(basename "$p")
    if git apply --reverse --check "$p" 2>/dev/null; then
        log "补丁已应用，跳过：$name"
        continue
    fi
    log "应用补丁：$name"
    git apply "$p" || die "补丁应用失败：$name"
done

# ---- 3. 重新生成 Vulkan 头/桩 ----
log "运行 make_vulkan（需要网络下载 vk.xml）…"
( cd dlls/winevulkan && python3 make_vulkan ) || die "make_vulkan 失败"

# ---- 4. 编译 ----
log "编译（-j$JOBS）…"
./configure --enable-win64 --disable-tests || die "configure 失败"
make -j"$JOBS" || die "编译失败"

# ---- 5. 收集产物 ----
OUT="$SRC_DIR/runtime"
log "收集补丁文件到 $OUT …"
mkdir -p "$OUT/lib/wine/x86_64-windows" "$OUT/lib/wine/x86_64-unix"

for f in wined3d.dll d3d11.dll dxva2.dll d3d9.dll win32u.dll winevulkan.dll; do
    src="dlls/$([ "$f" = "win32u.dll" ] && echo win32u || echo "${f%.dll}")/x86_64-windows/$f"
    [ -f "$src" ] || { log "⚠ 找不到 $src"; continue; }
    cp -f "$src" "$OUT/lib/wine/x86_64-windows/$f"
done

# win32u.so 在 dlls/win32u/ 下的 x86_64-unix 子目录
for cand in dlls/win32u/x86_64-unix/win32u.so dlls/win32u/.libs/win32u.so; do
    [ -f "$cand" ] && { cp -f "$cand" "$OUT/lib/wine/x86_64-unix/win32u.so"; break; }
done
[ -f "$OUT/lib/wine/x86_64-unix/win32u.so" ] || die "找不到 win32u.so"

if [ "$STRIP" = "1" ]; then
    log "strip …"
    strip --strip-unneeded "$OUT"/lib/wine/x86_64-windows/*.dll "$OUT"/lib/wine/x86_64-unix/*.so
fi

( cd "$OUT/lib/wine/x86_64-windows" && sha256sum *.dll; cd ../x86_64-unix && sha256sum *.so ) \
    > "$OUT/sha256.txt"

log "✓ 完成，补丁运行时体积：$(du -sh "$OUT" | cut -f1)"
log ""
log "注意：完整的定制 Wine（bin/ + 完整 lib/）需要另行打包分发，"
log "     本脚本只产出补丁 DLL —— 见 docs/packaging.md。"
