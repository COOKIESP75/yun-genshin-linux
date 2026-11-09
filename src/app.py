#!/usr/bin/env python3
"""yun-genshin-linux —— 云原神 Linux 整合应用（图形界面）。

提供：
  * 一键启动（自动处理 prefix、补丁部署、客户端更新适配）
  * 客户端安装引导（从米哈游官方接口下载，本项目不分发客户端本体）
  * 运行状态与健康检查
  * 日志查看

命令行模式（无 GUI 环境或排障时）：
    yun-genshin --check            健康检查
    yun-genshin --install-client   下载并安装官方客户端
    yun-genshin --launch           直接启动
    yun-genshin --sync             检测客户端更新并重新部署补丁
"""

from __future__ import annotations

import os
import subprocess
import sys
import threading
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))

from client import ClientBootstrap  # noqa: E402
from runtime import Layout, RuntimeManager, log  # noqa: E402


# ---------------------------------------------------------------- 命令行

def cmd_check(base: Path | None) -> int:
    lay = Layout.create(base)
    mgr = RuntimeManager(lay)
    ok, problems = mgr.health_check()
    print(f"运行时：{lay.root}")
    print(f"客户端：{'已安装' if mgr.client_installed() else '未安装'}")
    st = mgr.check_patches()
    print(f"补丁：{'OK' if st.ok else '不完整'}")
    for p in problems:
        print(f"  - {p}")
    return 0 if ok else 1


def cmd_install_client(base: Path | None) -> int:
    lay = Layout.create(base)
    boot = ClientBootstrap(lay)
    mgr = RuntimeManager(lay)
    mgr.create_prefix()
    if not boot.ensure_installed():
        return 1
    mgr.deploy_patches()
    boot.record_client()
    return 0


def cmd_launch(base: Path | None) -> int:
    lay = Layout.create(base)
    mgr = RuntimeManager(lay)
    boot = ClientBootstrap(lay)

    mgr.create_prefix()
    if not boot.ensure_installed():
        return 1
    # 客户端可能刚更新过 → 重新部署补丁
    boot.sync_patches_after_update()
    mgr.deploy_patches()
    mgr.launch()
    return 0


def cmd_sync(base: Path | None) -> int:
    lay = Layout.create(base)
    boot = ClientBootstrap(lay)
    return 0 if boot.sync_patches_after_update() else 1


# ---------------------------------------------------------------- GTK4

def run_gui(base: Path | None) -> int:
    try:
        import gi
        gi.require_version("Gtk", "4.0")
        from gi.repository import GLib, Gtk
    except Exception as e:  # noqa: BLE001
        print(f"无法初始化 GTK4：{e}", file=sys.stderr)
        print("可用命令行模式：yun-genshin --check / --install-client / --launch",
              file=sys.stderr)
        return 1

    lay = Layout.create(base)
    mgr = RuntimeManager(lay)
    boot = ClientBootstrap(lay)

    class App(Gtk.Application):
        def __init__(self):
            super().__init__(application_id="io.github.yun_genshin_linux")
            self.win = None
            self._proc = None

        # ---- UI 构建 ----
        def do_activate(self):
            if self.win:
                self.win.present()
                return
            self.win = Gtk.ApplicationWindow(application=self, title="云原神 (Linux)")
            self.win.set_default_size(560, 460)
            self.win.set_child(self._build_ui())
            self.win.present()

        def _build_ui(self):
            box = Gtk.Box(orientation=Gtk.Orientation.VERTICAL, spacing=12)
            box.set_margin_top(16)
            box.set_margin_bottom(16)
            box.set_margin_start(16)
            box.set_margin_end(16)

            title = Gtk.Label(label="云原神 · Linux 整合应用")
            title.add_css_class("title-1")
            box.append(title)

            # 状态区
            self.status = Gtk.Label(label="检查中 …")
            self.status.set_wrap(True)
            box.append(self.status)

            self.detail = Gtk.Label(label="")
            self.detail.set_wrap(True)
            self.detail.add_css_class("dim-label")
            box.append(self.detail)

            # 按钮
            btns = Gtk.Box(orientation=Gtk.Orientation.HORIZONTAL, spacing=8)
            btns.set_halign(Gtk.Align.CENTER)

            self.btn_launch = Gtk.Button(label="启动游戏")
            self.btn_launch.add_css_class("suggested-action")
            self.btn_launch.set_size_request(140, 42)
            self.btn_launch.connect("clicked", lambda _b: self._on_launch())
            btns.append(self.btn_launch)

            self.btn_client = Gtk.Button(label="安装客户端")
            self.btn_client.connect("clicked", lambda _b: self._on_install_client())
            btns.append(self.btn_client)

            self.btn_repair = Gtk.Button(label="修复补丁")
            self.btn_repair.connect("clicked", lambda _b: self._on_repair())
            btns.append(self.btn_repair)

            box.append(btns)

            # 进度条
            self.progress = Gtk.ProgressBar()
            self.progress.set_show_text(True)
            box.append(self.progress)

            # 日志
            self.logbuf = Gtk.TextView(editable=False, monospace=True)
            self.logbuf.set_monospace(True)
            scroller = Gtk.ScrolledWindow()
            scroller.set_child(self.logbuf)
            scroller.set_vexpand(True)
            scroller.set_min_content_height(180)
            box.append(scroller)

            self._append_log("就绪。\n")
            GLib.idle_add(self._refresh_status)
            return box

        def _append_log(self, text: str):
            buf = self.logbuf.get_buffer()
            buf.insert(buf.get_end_iter(), text)

        # ---- 状态 ----
        def _refresh_status(self):
            ok, problems = mgr.health_check()
            client = "已安装" if mgr.client_installed() else "未安装"
            st = mgr.check_patches()
            self.status.set_text(
                f"客户端：{client}    补丁：{'正常' if st.ok else '需修复'}"
                + ("    可以启动" if ok else "")
            )
            if problems:
                self.detail.set_text("\n".join(problems))
            else:
                self.detail.set_text("")
            return False

        # ---- 动作 ----
        def _run_bg(self, fn, done_msg: str):
            """在后台线程跑耗时任务，进度条 + 日志实时更新。"""
            self.progress.set_text("处理中 …")
            self.progress.pulse()

            def worker():
                try:
                    fn()
                    self._post(f"\n✓ {done_msg}\n")
                except Exception as e:  # noqa: BLE001
                    self._post(f"\n✗ {e}\n")
                GLib.idle_add(self._finish)

            threading.Thread(target=worker, daemon=True).start()

        def _post(self, text: str):
            GLib.idle_add(self._append_log, text)

        def _finish(self):
            self.progress.set_text("")
            self._refresh_status()
            return False

        def _on_launch(self):
            def job():
                mgr.create_prefix()
                if not boot.ensure_installed():
                    raise RuntimeError("客户端未安装，请先点「安装客户端」")
                boot.sync_patches_after_update()
                mgr.deploy_patches()
                self._proc = mgr.launch()
                self._post("\n客户端已启动。\n")
            self._run_bg(job, "启动完成")

        def _on_install_client(self):
            self._run_bg(
                lambda: (mgr.create_prefix(), boot.ensure_installed(),
                         mgr.deploy_patches(), boot.record_client()),
                "客户端安装完成",
            )

        def _on_repair(self):
            self._run_bg(
                lambda: (mgr.deploy_patches(), boot.record_client()),
                "补丁已重新部署",
            )

    app = App()
    return app.run([])


# ---------------------------------------------------------------- 入口

def main(argv: list[str]) -> int:
    base = None
    args = list(argv)
    if "--base" in args:
        i = args.index("--base")
        base = Path(args[i + 1])
        del args[i : i + 2]

    if "--check" in args:
        return cmd_check(base)
    if "--install-client" in args:
        return cmd_install_client(base)
    if "--launch" in args:
        return cmd_launch(base)
    if "--sync" in args:
        return cmd_sync(base)
    if "--version" in args:
        print("yun-genshin-linux 0.1.0")
        return 0

    return run_gui(base)


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
