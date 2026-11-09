#!/usr/bin/env bash
# install.sh — 安装 yun-genshin-linux 到 ~/.local/share
#
# 安装内容：
#   ~/.local/share/yun-genshin-linux/runtime/   定制 Wine 运行时 + 补丁 DLL
#   ~/.local/share/yun-genshin-linux/src/       应用逻辑
#   ~/.local/bin/yun-genshin                    启动器
#   ~/.config/autostart/                        登录自启（可选）
set -u

SRC=$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)
PREFIX=${XDG_DATA_HOME:-$HOME/.local/share}/yun-genshin-linux
BIN=$HOME/.local/bin

log(){ echo "[install] $*"; }
die(){ echo "[install] ✗ $*" >&2; exit 1; }

[ -d "$SRC/runtime" ] || die "找不到 runtime/ 目录（在 $SRC）"

log "安装到 $PREFIX"
mkdir -p "$PREFIX" "$BIN"

# runtime：定制 Wine + 补丁
log "复制运行时 …"
mkdir -p "$PREFIX/runtime"
cp -a "$SRC/runtime/." "$PREFIX/runtime/"

# src：应用逻辑
log "复制应用逻辑 …"
mkdir -p "$PREFIX/src"
cp -a "$SRC/src/." "$PREFIX/src/"

# 启动器
log "安装启动器到 $BIN/yun-genshin"
cat > "$BIN/yun-genshin" << EOF
#!/usr/bin/env bash
exec python3 "$PREFIX/src/app.py" "\$@"
EOF
chmod +x "$BIN/yun-genshin"

# 依赖自检
log "检查依赖 …"
MISSING=""
for c in python3; do
    command -v $c >/dev/null 2>&1 || MISSING="$MISSING $c"
done
python3 -c 'import gi; gi.require_version("Gtk","4.0"); from gi.repository import Gtk' 2>/dev/null \
    || MISSING="$MISSING python3-gi(GTK4)"
[ -z "$MISSING" ] || log "⚠ 缺少依赖：$MISSING（图形界面不可用，命令行仍可用）"

log ""
log "安装完成。"
log "  启动：  $BIN/yun-genshin"
log "  命令行：yun-genshin --check     # 健康检查"
log "           yun-genshin --install-client  # 下载并安装官方客户端"
log "           yun-genshin --launch     # 直接启动"
log ""
log "客户端需自行从米哈游官方渠道获取，本项目不分发客户端本体。"
