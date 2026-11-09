#!/usr/bin/env python3
"""云原神客户端引导与更新管理。

**重要：本模块不分发米哈游的客户端本体。**
客户端从米哈游官方 API 获取（接口地址来自官方客户端自身），
本模块只负责：检测 → 引导下载 → 交给 Wine 安装 → 记录版本指纹。

官方下载接口（从官方客户端安装包的资源段提取）：
    https://act-api-takumi.mihoyo.com/event/download_porter/link/clgm_cn/official/pc_dd180m
该接口直接返回安装包二进制（PE 头 MZ）。
"""

from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import urllib.request
from pathlib import Path

from runtime import Layout, RuntimeManager, log

# 米哈游官方下载接口（与官方客户端内置的一致）
OFFICIAL_DOWNLOAD_URL = (
    "https://act-api-takumi.mihoyo.com/event/download_porter/link/clgm_cn/official/pc_dd180m"
)

# 客户端安装包内的可执行文件名
INSTALLER_RE = re.compile(r"yscloud[_-][\d.]+\.exe", re.IGNORECASE)

USER_AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/120.0 Safari/537.36"
)


class ClientBootstrap:
    """引导用户安装官方客户端。"""

    def __init__(self, layout: Layout):
        self.layout = layout
        self.mgr = RuntimeManager(layout)
        self.state_file = layout.root / "client-state.json"

    # ---------- 状态 ----------

    def load_state(self) -> dict:
        if self.state_file.exists():
            try:
                return json.loads(self.state_file.read_text())
            except Exception:
                return {}
        return {}

    def save_state(self, state: dict) -> None:
        self.state_file.parent.mkdir(parents=True, exist_ok=True)
        self.state_file.write_text(json.dumps(state, indent=2))

    def client_changed(self) -> bool:
        """客户端内容是否变化过（换版本 / 换 FFmpeg）。"""
        cur = self.mgr.client_fingerprint()
        if cur is None:
            return False
        st = self.load_state()
        old = st.get("fingerprint")
        return old is not None and old != cur

    def record_client(self) -> None:
        fp = self.mgr.client_fingerprint()
        if fp:
            st = self.load_state()
            st["fingerprint"] = fp
            st["version"] = self.mgr.client_version()
            self.save_state(st)

    # ---------- 下载 ----------

    def download_installer(self, dest_dir: Path) -> Path | None:
        """从官方接口下载安装包。返回文件路径，失败返回 None。"""
        dest_dir.mkdir(parents=True, exist_ok=True)
        log(f"从官方接口下载客户端安装包 …\n  {OFFICIAL_DOWNLOAD_URL}")

        req = urllib.request.Request(
            OFFICIAL_DOWNLOAD_URL, headers={"User-Agent": USER_AGENT}
        )
        tmp = dest_dir / "yscloud_download.exe"
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                total = int(resp.headers.get("Content-Length", 0))
                done = 0
                last = 0
                with tmp.open("wb") as f:
                    while True:
                        chunk = resp.read(1 << 20)
                        if not chunk:
                            break
                        f.write(chunk)
                        done += len(chunk)
                        if total and done - last > (32 << 20):
                            last = done
                            pct = done * 100 // total
                            log(f"  下载中 … {done >> 20}/{total >> 20} MiB ({pct}%)")
            log(f"下载完成：{tmp}（{tmp.stat().st_size >> 20} MiB）")
            return tmp
        except Exception as e:  # noqa: BLE001
            log(f"✗ 下载失败：{e}")
            if tmp.exists():
                tmp.unlink()
            return None

    # ---------- 安装 ----------

    def install_client(self, installer: Path) -> bool:
        """用 Wine 静默安装客户端。

        客户端安装器是 NSIS/自解压包，Windows 下双击即可解压到
        %LOCALAPPDATA%\\Programs\\... —— 这里用 Wine 跑它，
        完成后校验 exe 是否落到预期位置。
        """
        log("通过 Wine 安装客户端 …")
        env = self.mgr.launch_env()
        try:
            subprocess.run(
                [str(self.layout.wine_bin), str(installer)],
                env=env,
                timeout=1800,
                check=False,
            )
        except subprocess.TimeoutExpired:
            log("✗ 安装超时")
            return False
        except Exception as e:  # noqa: BLE001
            log(f"✗ 安装失败：{e}")
            return False

        if self.mgr.client_installed():
            log("✓ 客户端安装完成")
            return True

        # 有些版本会装到别的路径，扫一遍 prefix 找
        found = self._find_client_in_prefix()
        if found:
            log(f"✓ 客户端已安装于 {found}")
            return True
        log("✗ 安装后未找到客户端可执行文件")
        return False

    def _find_client_in_prefix(self) -> Path | None:
        base = self.layout.prefix / "drive_c" / "users"
        if not base.exists():
            return None
        for p in base.rglob(CLIENT_EXE_NAME):
            return p
        return None

    # ---------- 一站式 ----------

    def ensure_installed(self, allow_download: bool = True) -> bool:
        """确保客户端已安装。缺则引导下载安装。"""
        if self.mgr.client_installed():
            log("✓ 客户端已安装")
            return True

        if not allow_download:
            log("客户端未安装（已跳过下载）")
            return False

        dl = self.layout.root / "downloads"
        installer = self.download_installer(dl)
        if not installer:
            return False
        return self.install_client(installer)

    def sync_patches_after_update(self) -> bool:
        """客户端更新后：重新部署补丁 + 校验。"""
        if not self.client_changed():
            log("客户端未变化，无需处理")
            return True

        log("检测到客户端已更新，重新部署补丁 …")
        st = self.mgr.deploy_patches()
        if not st.ok:
            log("✗ 补丁部署不完整")
            return False
        self.record_client()
        log("✓ 补丁已适配新客户端")
        return True


CLIENT_EXE_NAME = "Genshin Impact Cloud Game.exe"


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog="yun-genshin-client")
    ap.add_argument("--base", type=Path, default=None)
    ap.add_argument("--download", action="store_true", help="强制重新下载客户端")
    ap.add_argument("--sync", action="store_true", help="检测更新并重新部署补丁")
    args = ap.parse_args(argv)

    lay = Layout.create(args.base)
    boot = ClientBootstrap(lay)

    if args.download:
        dl = lay.root / "downloads"
        inst = boot.download_installer(dl)
        return 0 if inst else 1

    if args.sync:
        return 0 if boot.sync_patches_after_update() else 1

    return 0 if boot.ensure_installed() else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
