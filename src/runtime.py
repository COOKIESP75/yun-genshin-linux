#!/usr/bin/env python3
"""yun-genshin-linux 运行时管理。

职责：
  * 管理隔离的 Wine prefix
  * 部署/校验补丁 DLL（prefix + Wine 安装目录两处）
  * 检测官方客户端版本变化 → 重新部署补丁
  * 健康校验（确认补丁生效、解码链路可用）

设计要点（来自 2026-11-09 的实战经验）：
  * 客户端更新只动它自己的目录 GenshinImpactCloudGame/，与我们改的 system32/
    完全隔离 ⇒ 客户端更新不会覆盖补丁。
  * 但客户端自带 avcodec-61.dll / avutil-59.dll，我们的钩子打在这些库上
    ⇒ 客户端换 FFmpeg 版本后必须重新校验钩子是否命中。
  * WINEDLLPATH **不能**覆盖 prefix/system32 里的同名 DLL（实测），
    所以补丁必须在 prefix 和 Wine 安装目录各放一份。
  * win32u.so 是 Unix 侧，必须在 Wine 安装目录，且必须与 wined3d 同批构建
    （vulkan.h 变过，ABI 会错位 → vkCreateVideoSessionKHR 变 NULL）。
"""

from __future__ import annotations

import hashlib
import os
import re
import shutil
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

APP_NAME = "yun-genshin-linux"

# 客户端 exe 相对 prefix 的位置。
# 用户名部分是 Wine 的默认（通常与 Linux 用户名同名），但不能写死 ——
# 所以运行时动态解析（见 Layout.client_dir）。
CLIENT_REL_TAIL = Path("AppData/Local/Programs/miHoYo/GenshinImpactCloudGame")
CLIENT_EXE = "Genshin Impact Cloud Game.exe"

# 需要部署的补丁文件：(相对 Wine 安装目录的路径, 目标 basename)
# 前 6 个是 Windows 侧 DLL（要同时进 prefix/system32 和 Wine 安装目录），
# win32u.so 是 Unix 侧（只能进 Wine 安装目录）。
PATCH_FILES = [
    "lib/wine/x86_64-windows/wined3d.dll",
    "lib/wine/x86_64-windows/d3d11.dll",
    "lib/wine/x86_64-windows/dxva2.dll",
    "lib/wine/x86_64-windows/d3d9.dll",
    "lib/wine/x86_64-windows/win32u.dll",
    "lib/wine/x86_64-windows/winevulkan.dll",
    "lib/wine/x86_64-unix/win32u.so",
]

# 放进 prefix/system32 的（win32u.so 是 .so，不在此列）
PREFIX_SYSTEM32 = [
    "wined3d.dll",
    "d3d11.dll",
    "dxva2.dll",
    "d3d9.dll",
    "win32u.dll",
    "winevulkan.dll",
]


def log(msg: str) -> None:
    print(f"[{APP_NAME}] {msg}", flush=True)


def sha256(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


@dataclass
class Layout:
    """应用的目录布局。

    runtime（定制 Wine）可以和数据目录分开：
      * 默认：~/.local/share/yun-genshin-linux/{runtime,prefix,logs}
      * 便携：把 runtime 放别处（发行包里 runtime 与数据是分开的），
        用 YUN_GENSHAIN_RUNTIME 环境变量或 --runtime 指定。
    """

    root: Path
    runtime: Path          # 定制 Wine
    prefix: Path           # 隔离 prefix
    logs: Path

    @classmethod
    def create(cls, base: Path | None = None, runtime: Path | None = None) -> "Layout":
        base = base or Path(
            os.environ.get("XDG_DATA_HOME", Path.home() / ".local/share")
        ) / APP_NAME
        rt = runtime or Path(os.environ.get("YUN_GENSHAIN_RUNTIME", base / "runtime"))
        lay = cls(
            root=base,
            runtime=rt,
            prefix=base / "prefix",
            logs=base / "logs",
        )
        lay.logs.mkdir(parents=True, exist_ok=True)
        return lay

    @property
    def wine_bin(self) -> Path:
        return self.runtime / "bin" / "wine"

    @property
    def wine_lib(self) -> Path:
        """Wine 的库目录（补丁文件所在处）。

        补丁文件在 runtime/lib/wine/<arch>/ 下，而 PATCH_FILES 里的相对路径
        已经带了 lib/wine/ 前缀 —— 所以这里返回 runtime 本身，路径拼接才不会重复。
        """
        return self.runtime

    @property
    def prefix_system32(self) -> Path:
        return self.prefix / "drive_c" / "windows" / "system32"

    @property
    def users_dir(self) -> Path:
        return self.prefix / "drive_c" / "users"

    def _find_user_dir(self) -> Path | None:
        """在 prefix 里找装了客户端的 Windows 用户目录。

        Wine 的用户目录名默认与 Linux 用户名同名，但可以改 ——
        所以扫一遍而不是写死。
        """
        users = self.users_dir
        if not users.is_dir():
            return None
        for u in sorted(users.iterdir()):
            if not u.is_dir():
                continue
            if (u / CLIENT_REL_TAIL / CLIENT_EXE).exists():
                return u
        return None

    @property
    def client_dir(self) -> Path:
        """客户端安装目录（动态解析用户名）。"""
        u = self._find_user_dir()
        if u is not None:
            return u / CLIENT_REL_TAIL
        # 还没装：给出 Wine 默认用户目录（通常与 Linux 用户名同名）
        return self.users_dir / os.environ.get("USER", "ax210") / CLIENT_REL_TAIL

    @property
    def client_exe(self) -> Path:
        return self.client_dir / CLIENT_EXE


@dataclass
class PatchStatus:
    """补丁部署状态。"""

    deployed: bool = False
    missing: list[str] = field(default_factory=list)
    mismatched: list[str] = field(default_factory=list)

    @property
    def ok(self) -> bool:
        return self.deployed and not self.missing and not self.mismatched


class RuntimeManager:
    """管理 Wine prefix 与补丁部署。"""

    def __init__(self, layout: Layout):
        self.layout = layout

    # ---------- 客户端 ----------

    def client_installed(self) -> bool:
        return self.layout.client_exe.exists()

    def client_version(self) -> str | None:
        """从客户端 exe 的文件版本资源里读版本号。

        Windows PE 的版本信息在资源段，Wine 侧可以用 `wrestool` 之类，
        但我们不引入额外依赖 —— 改用 exe 的 mtime + size 做指纹，
        足以判断「客户端是否换过」。
        """
        exe = self.layout.client_exe
        if not exe.exists():
            return None
        st = exe.stat()
        return f"{st.st_mtime_ns:x}-{st.st_size:x}"

    def client_fingerprint(self) -> str | None:
        """客户端安装内容的指纹（覆盖 exe + 自带 avcodec/avutil）。"""
        exe = self.layout.client_exe
        if not exe.exists():
            return None
        h = hashlib.sha256()
        h.update(sha256(exe).encode())
        for name in ("avcodec-61.dll", "avutil-59.dll"):
            p = self.layout.client_dir / name
            if p.exists():
                h.update(sha256(p).encode())
        return h.hexdigest()[:16]

    # ---------- 补丁 ----------

    def patch_source(self) -> Path:
        return self.layout.runtime

    def check_patches(self) -> PatchStatus:
        """检查补丁是否已正确部署到两处。"""
        st = PatchStatus()
        src = self.patch_source()

        for rel in PATCH_FILES:
            s = src / rel
            if not s.exists():
                st.missing.append(f"runtime/{rel}")
                continue

            base = Path(rel).name
            targets = []
            if rel.endswith(".so"):
                targets = [self.layout.wine_lib / rel]
            else:
                targets = [
                    self.layout.wine_lib / rel,
                    self.layout.prefix_system32 / base,
                ]

            for t in targets:
                if not t.exists():
                    st.missing.append(str(t))
                elif sha256(t) != sha256(s):
                    st.mismatched.append(str(t))

        st.deployed = not st.missing
        return st

    def patches_needed(self) -> PatchStatus:
        """只检查 Wine 安装目录那一份（prefix 还没建时用）。"""
        st = PatchStatus()
        src = self.patch_source()
        for rel in PATCH_FILES:
            s = src / rel
            t = self.layout.wine_lib / rel
            if not s.exists():
                st.missing.append(f"runtime/{rel}")
            elif not t.exists():
                st.missing.append(str(t))
            elif sha256(t) != sha256(s):
                st.mismatched.append(str(t))
        st.deployed = not st.missing
        return st

    def deploy_patches(self) -> PatchStatus:
        """把补丁部署到 Wine 安装目录和 prefix/system32。"""
        src = self.patch_source()
        deployed = 0

        for rel in PATCH_FILES:
            s = src / rel
            if not s.exists():
                log(f"缺少补丁文件：{s}")
                continue

            if rel.endswith(".so"):
                targets = [self.layout.wine_lib / rel]
            else:
                targets = [
                    self.layout.wine_lib / rel,
                    self.layout.prefix_system32 / Path(rel).name,
                ]

            for t in targets:
                # 发行包里 runtime 本身就是打好补丁的 Wine，源和目标可能是同一文件
                if t.resolve() == s.resolve():
                    deployed += 1
                    continue
                t.parent.mkdir(parents=True, exist_ok=True)
                shutil.copy2(s, t)
                deployed += 1

        log(f"已部署 {deployed} 个补丁文件")
        return self.check_patches()

    # ---------- Wine prefix ----------

    def prefix_exists(self) -> bool:
        return (self.layout.prefix / "system.reg").exists()

    def create_prefix(self) -> None:
        if self.prefix_exists():
            log("prefix 已存在，跳过创建")
            return
        log("创建 Wine prefix …")
        self.layout.prefix.parent.mkdir(parents=True, exist_ok=True)
        env = dict(os.environ, WINEPREFIX=str(self.layout.prefix))
        subprocess.run(
            [str(self.layout.wine_bin), "wineboot", "--init"],
            env=env,
            check=False,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )
        log("prefix 创建完成")

    # ---------- 健康校验 ----------

    def health_check(self) -> tuple[bool, list[str]]:
        """检查补丁链路是否健康。返回 (是否健康, 问题列表)。"""
        problems: list[str] = []

        if not self.layout.wine_bin.exists():
            problems.append(f"缺少 Wine 运行时：{self.layout.wine_bin}")
        if not self.client_installed():
            problems.append("未安装云原神客户端")

        # prefix 还没建时，只校验 Wine 安装目录那一份
        if self.prefix_exists():
            st = self.check_patches()
        else:
            st = self.patches_needed()
            if not st.ok:
                problems.append("prefix 尚未初始化（首次启动会自动创建）")

        for m in st.missing:
            problems.append(f"补丁缺失：{m}")
        for m in st.mismatched:
            problems.append(f"补丁版本不符：{m}")

        return (not problems), problems

    def verify_decode_chain(self, log_file: Path | None = None) -> bool:
        """从 wine 日志里确认 H.265 硬解链路真的跑起来了。

        判据（不能用「客户端报 Received first frame」，那不代表有画面）：
          * 日志里有 yg-h265 / decode_queue_submit ⇒ 走了 H.265 硬解路径
          * 有 yg-dec counter decoded ⇒ 计数器在涨
        """
        if log_file is None or not log_file.exists():
            return False
        text = log_file.read_text(errors="ignore")
        return "yg-h265" in text and "decode_queue_submit" in text

    # ---------- 启动 ----------

    def launch_env(self) -> dict[str, str]:
        env = dict(os.environ)
        env["WINEPREFIX"] = str(self.layout.prefix)
        env["WINE_D3D_CONFIG"] = "renderer=vulkan"
        env["WINEDLLOVERRIDES"] = "mscoree=d;mshtml=d;audioses=n"
        env["QTWEBENGINE_DISABLE_SANDBOX"] = "1"
        # 代理会干扰 RTC/UDP
        for k in (
            "HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY",
            "http_proxy", "https_proxy", "all_proxy",
        ):
            env.pop(k, None)
        return env

    def launch(self, extra_env: dict[str, str] | None = None) -> subprocess.Popen:
        env = self.launch_env()
        if extra_env:
            env.update(extra_env)
        log_file = self.layout.logs / "wine.log"
        log(f"启动客户端，日志：{log_file}")
        out = log_file.open("ab")
        return subprocess.Popen(
            [str(self.layout.wine_bin), CLIENT_EXE],
            cwd=str(self.layout.client_dir),
            env=env,
            stdout=out,
            stderr=subprocess.STDOUT,
        )


def main(argv: list[str]) -> int:
    import argparse

    ap = argparse.ArgumentParser(prog=APP_NAME)
    ap.add_argument("--base", type=Path, default=None, help="安装基目录")
    ap.add_argument("--runtime", type=Path, default=None, help="定制 Wine 运行时目录")
    ap.add_argument("--check", action="store_true", help="只做健康检查")
    ap.add_argument("--deploy", action="store_true", help="强制重新部署补丁")
    ap.add_argument("--launch", action="store_true", help="启动客户端")
    args = ap.parse_args(argv)

    lay = Layout.create(args.base, args.runtime)
    mgr = RuntimeManager(lay)

    if args.check:
        ok, problems = mgr.health_check()
        if ok:
            log("✓ 健康检查通过")
            return 0
        for p in problems:
            log(f"✗ {p}")
        return 1

    if args.deploy:
        st = mgr.deploy_patches()
        log("✓ 补丁部署完成" if st.ok else "✗ 补丁部署不完整")
        return 0 if st.ok else 1

    if args.launch:
        mgr.create_prefix()
        mgr.deploy_patches()
        mgr.launch()
        return 0

    # 默认：打印状态
    ok, problems = mgr.health_check()
    log(f"运行时：{lay.root}")
    log(f"客户端：{'已安装' if mgr.client_installed() else '未安装'}")
    log(f"补丁：{'OK' if mgr.check_patches().ok else '不完整'}")
    for p in problems:
        log(f"  - {p}")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
