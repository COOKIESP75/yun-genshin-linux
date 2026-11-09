#!/usr/bin/env bash
# uninstall.sh — 移除 yun-genshin-linux
#
# 默认保留 prefix（客户端 + 存档），加 --purge 一并删除。
set -u

PREFIX=${XDG_DATA_HOME:-$HOME/.local/share}/yun-genshin-linux
BIN=$HOME/.local/bin
PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

log(){ echo "[uninstall] $*"; }

if [ -f "$BIN/yun-genshin" ]; then
    rm -f "$BIN/yun-genshin" && log "已删除启动器 $BIN/yun-genshin"
fi

if [ -d "$PREFIX" ]; then
    if [ "$PURGE" = "1" ]; then
        rm -rf "$PREFIX" && log "已删除 $PREFIX（含客户端与 prefix）"
    else
        rm -rf "$PREFIX/runtime" "$PREFIX/src" "$PREFIX/client-state.json"
        log "已删除运行时与应用逻辑，保留 prefix 与客户端：$PREFIX"
        log "  （彻底删除请用 --purge）"
    fi
fi

log "完成。"
