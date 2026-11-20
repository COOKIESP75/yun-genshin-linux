#!/usr/bin/env bash
# build-runtime.sh — 组装可分发的定制 Wine 运行时
#
# 输入：wine-patched/（我们自己编译的完整 Wine，已含全部补丁）
# 输出：runtime/（bin + lib + share + 补丁 DLL），供分发
#
# 瘦身策略：
#   * strip 全部 PE/ELF → 去掉调试符号（-g 构建的产物瘦身 ~2/3）
#   * 保留 i386-windows / i386-unix —— 米哈游官方客户端安装包
#     （yscloud_*.exe）是 PE32/80386 的 NSIS 自解压包，缺了 i386 就装不上：
#       wine: failed to load L"\\??\\C:\\windows\\syswow64\\ntdll.dll" error c0000135
#     客户端本体是 PE32+，运行期仍走 64 位；32 位这一份只用于安装器。
#     用 --no32 开关可再瘦掉 ~220 MB，代价是装不了客户端。
#   * 补丁 DLL 单独 strip 后覆盖进去
set -u

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SRC_WINE=${SRC_WINE:-$ROOT/../wine-patched}
OUT="$ROOT/runtime"
KEEP32=1
[ "${1:-}" = "--no32" ] && KEEP32=0

log(){ echo "[runtime] $*"; }
die(){ echo "[runtime] ✗ $*" >&2; exit 1; }

# 删除目录。用 trash(1) 若可用（可恢复），否则 rm -rf。
# 刻意不用任何特定机器上的路径 —— 本脚本必须能在别人机器上跑。
remove_dir(){
    local d=$1
    [ -e "$d" ] || return 0
    if command -v trash >/dev/null 2>&1; then
        trash "$d" 2>/dev/null && return 0
    fi
    rm -rf "$d"
}

[ -d "$SRC_WINE/bin" ] || die "找不到 Wine 运行时：$SRC_WINE/bin（先跑 scripts/build-wine.sh）"

log "清空输出目录 …"
remove_dir "$OUT"
mkdir -p "$OUT/lib/wine/x86_64-windows" "$OUT/lib/wine/x86_64-unix" "$OUT/bin" "$OUT/share"

log "复制 bin …"
cp -a "$SRC_WINE/bin/." "$OUT/bin/"

log "复制 share …"
cp -a "$SRC_WINE/share/." "$OUT/share/"

log "复制 x86_64-windows …"
cp -a "$SRC_WINE/lib/wine/x86_64-windows/." "$OUT/lib/wine/x86_64-windows/"

log "复制 x86_64-unix …"
cp -a "$SRC_WINE/lib/wine/x86_64-unix/." "$OUT/lib/wine/x86_64-unix/"

if [ "$KEEP32" = "1" ]; then
    log "复制 i386-windows / i386-unix（官方安装包是 32 位 PE）…"
    mkdir -p "$OUT/lib/wine/i386-windows" "$OUT/lib/wine/i386-unix"
    cp -a "$SRC_WINE/lib/wine/i386-windows/." "$OUT/lib/wine/i386-windows/"
    cp -a "$SRC_WINE/lib/wine/i386-unix/." "$OUT/lib/wine/i386-unix/"
else
    log "去掉 32 位 Wine（将无法安装客户端）…"
    remove_dir "$OUT/lib/wine/i386-windows"
    remove_dir "$OUT/lib/wine/i386-unix"
fi

log "strip 全部二进制 …"
find "$OUT/lib" "$OUT/bin" -type f \( -name "*.dll" -o -name "*.exe" -o -name "*.so*" -o -name "wine*" \) \
    -exec strip --strip-unneeded {} + 2>/dev/null

# 覆盖回 strip 后的补丁 DLL（保证与发行清单一致）
if [ -d "$ROOT/runtime-patches" ]; then
    log "覆盖补丁 DLL …"
    for f in "$ROOT"/runtime-patches/lib/wine/x86_64-windows/*.dll; do
        [ -e "$f" ] || continue
        cp -f "$f" "$OUT/lib/wine/x86_64-windows/$(basename "$f")"
    done
    for f in "$ROOT"/runtime-patches/lib/wine/x86_64-unix/*.so; do
        [ -e "$f" ] || continue
        cp -f "$f" "$OUT/lib/wine/x86_64-unix/$(basename "$f")"
    done
fi

log "生成哈希清单 …"
( cd "$OUT" && sha256sum lib/wine/x86_64-windows/*.dll 2>/dev/null
  sha256sum lib/wine/x86_64-unix/*.so 2>/dev/null
  sha256sum lib/wine/i386-windows/*.dll 2>/dev/null
  sha256sum lib/wine/i386-unix/* 2>/dev/null ) > "$OUT/sha256.txt"

log "✓ 运行时体积：$(du -sh "$OUT" | cut -f1)"
log "  （其中 lib/wine: $(du -sh "$OUT/lib/wine" | cut -f1)）"
