#!/usr/bin/env bash
# build-runtime.sh — 组装可分发的定制 Wine 运行时
#
# 输入：wine-patched/（我们自己编译的完整 Wine，已含全部补丁）
# 输出：runtime/（bin + lib + share + 补丁 DLL），供分发
#
# 瘦身策略：
#   * strip 全部 PE/ELF → 去掉调试符号（-g 构建的产物瘦身 ~2/3）
#   * 去掉 i386-windows / i386-unix（客户端是 PE32+，纯 64 位运行）
#     ⚠ 若客户端某个组件是 32 位，需要保留 i386；用 --keep32 开关
#   * 补丁 DLL 单独 strip 后覆盖进去
set -u

ROOT=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
SRC_WINE=${SRC_WINE:-$ROOT/../wine-patched}
OUT="$ROOT/runtime"
KEEP32=0
[ "${1:-}" = "--keep32" ] && KEEP32=1

log(){ echo "[runtime] $*"; }
die(){ echo "[runtime] ✗ $*" >&2; exit 1; }

[ -d "$SRC_WINE/bin" ] || die "找不到 Wine 运行时：$SRC_WINE/bin（先跑 scripts/build-wine.sh）"

log "清空输出目录 …"
node /home/ax210/.zcode/local-plugins/safe-rm/bin/trash.mjs "$OUT" 2>/dev/null
mkdir -p "$OUT/lib/wine/x86_64-windows" "$OUT/lib/wine/x86_64-unix" "$OUT/bin" "$OUT/share"

log "复制 bin …"
cp -a "$SRC_WINE/bin/." "$OUT/bin/"

log "复制 share …"
cp -a "$SRC_WINE/share/." "$OUT/share/"

log "复制 x86_64-windows …"
cp -a "$SRC_WINE/lib/wine/x86_64-windows/." "$OUT/lib/wine/x86_64-windows/"

log "复制 x86_64-unix …"
cp -a "$SRC_WINE/lib/wine/x86_64-unix/." "$OUT/lib/wine/x86_64-unix/"

if [ "$KEEP32" = "0" ]; then
    log "去掉 32 位 Wine（客户端是 PE32+）…"
    node /home/ax210/.zcode/local-plugins/safe-rm/bin/trash.mjs \
        "$OUT/lib/wine/i386-windows" "$OUT/lib/wine/i386-unix" 2>/dev/null
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
( cd "$OUT/lib/wine/x86_64-windows" && sha256sum *.dll 2>/dev/null
  cd ../x86_64-unix && sha256sum *.so 2>/dev/null ) > "$OUT/sha256.txt"

log "✓ 运行时体积：$(du -sh "$OUT" | cut -f1)"
log "  （其中 lib/wine: $(du -sh "$OUT/lib/wine" | cut -f1)）"
