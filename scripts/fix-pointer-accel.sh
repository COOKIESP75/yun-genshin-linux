#!/usr/bin/env bash
# fix-pointer-accel.sh — 把 X11 指针加速改成纯线性
#
# 为什么需要：
#   云原神客户端把鼠标**绝对位置差值**换算成相对位移发给云端
#   （RtcMouse.cursor_relative_x/y）。而 X11 的指针加速是**阈值型非线性**的：
#       acceleration: A/B  threshold: T  ⇒  位移 < T 时 ×A，≥ T 时 ×B
#   慢速移动 ×2、快速移动 ×1 ⇒  手感「忽快忽慢」。
#   threshold=0 时无分段，统一 ×A ⇒ 纯线性。
#
# 另外：纯 X11 会话（XDG_SESSION_TYPE=x11）下 GNOME 的
#   gsettings org.gnome.desktop.peripherals.mouse accel-profile
#   只作用于 libinput/Wayland 路径，对物理鼠标**无效**；
#   真正生效的是 X server 层的 xset m。两个都设，双保险。
#
# 用法：
#   bash fix-pointer-accel.sh          # 设为 1 倍（无加速，纯 1:1）
#   bash fix-pointer-accel.sh 2        # 设为 2 倍线性
#   bash fix-pointer-accel.sh reset    # 恢复系统原始设置
set -u
export DISPLAY="${DISPLAY:-:0}"

case "${1:-1}" in
    reset)
        xset m 2/1 4 2>/dev/null && echo "已恢复 X 指针加速：2/1 threshold 4"
        gsettings set org.gnome.desktop.peripherals.mouse accel-profile 'default' 2>/dev/null \
            && echo "已恢复 GNOME accel-profile=default"
        ;;
    *)
        N="${1:-1}"
        case "$N" in (*[!0-9]*|'') echo "参数须为正整数"; exit 1;; esac
        # threshold=0 ⇒ 纯线性
        xset m "$N"/1 0 2>/dev/null && echo "X 指针加速：${N} 倍线性（acceleration $N/1 threshold 0）"
        gsettings set org.gnome.desktop.peripherals.mouse accel-profile 'flat' 2>/dev/null
        ;;
esac

xset q 2>/dev/null | grep -A1 "Pointer Control" | tail -1
