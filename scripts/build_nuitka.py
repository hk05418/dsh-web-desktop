#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""dsh-desktop 通用 Nuitka 打包脚本：按当前平台自动打包并产出分发压缩包。

产物（在 dist/ 下，文件名含平台与架构）：
- Windows -> dist/dsh-desktop-windows-<arch>.zip   （内含单文件 dsh-desktop.exe）
- Linux   -> dist/dsh-desktop-linux-<arch>.tar.gz  （内含 dsh-desktop/ 目录包）
- macOS   -> dist/dsh-desktop-macos-<arch>.zip     （内含 dsh-desktop.app）

用法：
    python scripts/build_nuitka.py                 # 按当前平台打包
    python scripts/build_nuitka.py --onefile       # Windows/Linux 单文件（macOS 固定 .app）
    python scripts/build_nuitka.py --dry-run       # 只打印 Nuitka 命令，不构建

说明：
- 入口 main.py（项目根），--include-path 由 PYTHONPATH=src 提供（Nuitka 4.x
  无 --include-path 选项，靠 sys.path 解析 dsh_desktop 包）；
- Nuitka pyside6 插件自动收集 Qt 库/插件/资源（含 QtWebEngine）；
- Linux 构建机若装有系统 fcitx5 输入法插件会一并打包（PySide6 wheel 不含），
  否则应用首次启动时从用户系统 Qt 自动补（见 app._ensure_fcitx5_plugin，
  PLAN.md §6.2）；
- 需要 Nuitka 与 C 编译器（Windows: MSVC / macOS: Xcode CLT / Linux: gcc）。
"""
from __future__ import annotations

import argparse
import os
import platform
import shutil
import struct
import subprocess
import sys
import tarfile
import zipfile
from pathlib import Path

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
APP_NAME = "dsh-desktop"
ENTRY = "main.py"
DIST = PROJECT_ROOT / "dist"


def detect_platform() -> dict:
    """识别操作系统平台与 CPU 架构/位数。"""
    system = sys.platform
    name = {"win32": "windows", "cygwin": "windows", "darwin": "macos"}.get(system)
    if name is None and system.startswith("linux"):
        name = "linux"
    machine = platform.machine().lower()
    arch = {"x86_64": "x64", "amd64": "x64", "aarch64": "arm64", "arm64": "arm64"}.get(
        machine, machine
    )
    return {
        "name": name or system,
        "machine": machine,
        "arch": arch,
        "bitness": struct.calcsize("P") * 8,
    }


def asset_name(plat: dict) -> str:
    """分发压缩包文件名（与 GitHub Actions 上传的 artifact 对应）。"""
    p, a = plat["name"], plat["arch"]
    if p == "windows":
        return f"{APP_NAME}-windows-{a}.zip"
    if p == "linux":
        return f"{APP_NAME}-linux-{a}.tar.gz"
    if p == "macos":
        return f"{APP_NAME}-macos-{a}.zip"
    return f"{APP_NAME}-{p}.zip"


def check_prereqs(plat_name: str) -> list[str]:
    """构建前置检查，返回警告列表。"""
    warnings = []
    probe = subprocess.run(
        [sys.executable, "-m", "nuitka", "--version"],
        capture_output=True, text=True, cwd=PROJECT_ROOT,
    )
    if probe.returncode != 0:
        warnings.append("Nuitka 不可用，请先安装：uv pip install nuitka")
    cc = {"windows": "cl", "macos": "cc", "linux": "gcc"}.get(plat_name, "cc")
    if shutil.which(cc) is None:
        hints = {
            "windows": "需要 MSVC 构建工具（Visual Studio Build Tools）",
            "macos": "需要 Xcode Command Line Tools（xcode-select --install）",
            "linux": "需要 gcc（如 sudo pacman -S gcc / apt install build-essential）",
        }
        warnings.append(hints.get(plat_name, f"未找到 C 编译器 {cc}"))
    if plat_name == "linux" and shutil.which("patchelf") is None:
        warnings.append(
            "Linux standalone 需要 patchelf（uv pip install patchelf 或 "
            "sudo pacman -S patchelf / apt install patchelf）"
        )
    return warnings


def build_nuitka_args(plat_name: str, args: argparse.Namespace) -> list[str]:
    """按平台组装 Nuitka 参数（Nuitka 4.x 选项）。"""
    nuitka = [
        "--standalone",
        "--assume-yes-for-downloads",
        "--enable-plugins=pyside6",
        "--noinclude-qt-translations",
        "--show-progress",
        f"--output-dir={DIST.name}",
        "--output-filename=" + APP_NAME,
        "--remove-output",
    ]

    if plat_name == "windows":
        nuitka.append("--windows-console-mode=disable")
        if args.onefile:
            nuitka.append("--onefile")
    elif plat_name == "macos":
        arch = args.arch or (
            "arm64" if platform.machine().lower() in ("arm64", "aarch64") else "x86_64"
        )
        nuitka += [
            "--macos-create-app-bundle",
            f"--macos-target-arch={arch}",
            f"--macos-app-name={APP_NAME}",
        ]
        # macOS 产物固定为 .app 应用包，--onefile 忽略
        if args.onefile:
            print("提示: macOS 产物固定为 .app 应用包，--onefile 已忽略")
    elif plat_name == "linux":
        # 构建机若装有系统 fcitx5 输入法插件则打包进去（PySide6 wheel 不含）。
        # 目标路径必须是 PySide6/qt-plugins/（Nuitka standalone 运行时
        # QCoreApplication.setLibraryPaths 只搜这里，见 PySidePyQtPlugin）。
        _name = "libfcitx5platforminputcontextplugin.so"
        for _p in (
            f"/usr/lib/qt6/plugins/platforminputcontexts/{_name}",
            f"/usr/lib64/qt6/plugins/platforminputcontexts/{_name}",
            f"/usr/lib/x86_64-linux-gnu/qt6/plugins/platforminputcontexts/{_name}",
        ):
            if Path(_p).exists():
                nuitka.append(
                    f"--include-data-files={_p}"
                    f"=PySide6/qt-plugins/platforminputcontexts/{_name}"
                )
                break
        if args.onefile:
            nuitka.append("--onefile")
    else:
        raise SystemExit(f"不支持的平台: {plat_name}")

    nuitka.append(ENTRY)
    return nuitka


def _find_nuitka_output(plat_name: str, onefile: bool) -> Path | None:
    """定位 Nuitka 实际产物（不同版本布局可能不同，做通用探测）。"""
    if plat_name == "windows":
        # onefile: dist/dsh-desktop.exe（单文件）
        exe = DIST / f"{APP_NAME}.exe"
        if exe.is_file():
            return exe
        # onedir: dist/main.dist/（目录，内含 dsh-desktop.exe）
        if onefile:
            return None
        dist_dir = DIST / f"{APP_NAME}.dist"
        if dist_dir.is_dir():
            return dist_dir
        for d in sorted(DIST.glob("*.dist")):
            if (d / f"{APP_NAME}.exe").is_file():
                return d
        return None
    if plat_name == "macos":
        # Nuitka 按入口脚本命名 .app（main.py -> main.app）；--macos-app-name
        # 只改 Info.plist 的 CFBundleName，不改目录名。故探测 dist 下任意 .app。
        for cand in sorted(DIST.glob("*.app")):
            if cand.is_dir():
                return cand
        return None
    # Linux: 目录包（.dist）或 onefile 单文件
    if onefile:
        exe = DIST / APP_NAME
        return exe if exe.is_file() else None
    dist_dir = DIST / f"{APP_NAME}.dist"
    if dist_dir.is_dir():
        return dist_dir
    # 兜底：dist 下任意 *.dist 目录
    for d in sorted(DIST.glob("*.dist")):
        if d.is_dir():
            return d
    return None


def _zip_dir(dir_path: Path, out_path: Path, arcname_root: str) -> None:
    """Zip a directory tree; files stored under ``arcname_root/``."""
    with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
        for f in sorted(dir_path.rglob("*")):
            if f.is_file():
                zf.write(f, arcname=f"{arcname_root}/{f.relative_to(dir_path).as_posix()}")


def post_build(plat: dict, args: argparse.Namespace) -> Path:
    """后处理：把 Nuitka 产物打包成分发压缩包，返回压缩包路径。"""
    plat_name = plat["name"]
    out_name = asset_name(plat)
    out_path = DIST / out_name
    src = _find_nuitka_output(plat_name, args.onefile)
    if src is None:
        raise SystemExit(f"未在 {DIST}/ 找到 Nuitka 产物，请检查构建日志")

    if plat_name == "windows":
        if src.is_file():
            # onefile：单文件 exe 直接进 zip
            with zipfile.ZipFile(out_path, "w", zipfile.ZIP_DEFLATED) as zf:
                zf.write(src, arcname=src.name)
        else:
            # onedir：目录包重命名为 dsh-desktop/ 再打 zip
            stage = DIST / APP_NAME
            if stage.exists():
                shutil.rmtree(stage)
            shutil.copytree(src, stage)
            _zip_dir(stage, out_path, APP_NAME)
            shutil.rmtree(stage)
    elif plat_name == "linux":
        if args.onefile and src.is_file():
            # onefile：单文件直接进 tar.gz
            with tarfile.open(out_path, "w:gz") as tf:
                tf.add(src, arcname=APP_NAME)
        else:
            # onedir：把目录包重命名为 dsh-desktop/ 再打 tar.gz
            stage = DIST / APP_NAME
            if stage.exists():
                shutil.rmtree(stage)
            shutil.copytree(src, stage)
            # 附带 .desktop 文件（应用菜单入口）+ 图标
            desktop_file = PROJECT_ROOT / f"{APP_NAME}.desktop"
            if desktop_file.is_file():
                shutil.copy2(desktop_file, stage / desktop_file.name)
            icon_file = PROJECT_ROOT / f"{APP_NAME}.png"
            if icon_file.is_file():
                shutil.copy2(icon_file, stage / icon_file.name)
            with tarfile.open(out_path, "w:gz") as tf:
                tf.add(stage, arcname=APP_NAME)
            shutil.rmtree(stage)
    elif plat_name == "macos":
        # 找到的 .app 可能叫 main.app（按入口脚本命名）；统一重命名为
        # dsh-desktop.app 再打包，保证解压后是 dsh-desktop.app。
        app_bundle = src if src.name == f"{APP_NAME}.app" else None
        if app_bundle is None:
            stage = DIST / f"{APP_NAME}.app"
            if stage.exists():
                shutil.rmtree(stage)
            shutil.copytree(src, stage)
            app_bundle = stage
        _zip_dir(app_bundle, out_path, f"{APP_NAME}.app")
        if app_bundle != src:
            shutil.rmtree(app_bundle)
    else:
        raise SystemExit(f"不支持的平台: {plat_name}")
    return out_path


def _force_utf8_stdio() -> None:
    """Force UTF-8 on stdout/stderr.

    Windows consoles default to cp1252 (and piped output to the locale
    encoding), so printing Chinese (e.g. "打包") raises UnicodeEncodeError.
    Reconfigure to UTF-8 so the script works on all platforms.
    """
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            try:
                stream.reconfigure(encoding="utf-8")
            except Exception:  # noqa: BLE001 - best effort
                pass


def main(argv: list[str]) -> int:
    _force_utf8_stdio()
    parser = argparse.ArgumentParser(
        description="dsh-desktop 通用 Nuitka 打包脚本：按当前平台自动打包",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("--onefile", action="store_true",
                        help="单文件可执行（Windows/Linux；macOS 固定 .app）")
    parser.add_argument("--arch", default=None, choices=["arm64", "x86_64"],
                        help="macOS 目标架构（默认当前机器架构）")
    parser.add_argument("--dry-run", action="store_true",
                        help="只打印 Nuitka 命令，不实际构建")
    args = parser.parse_args(argv)

    plat = detect_platform()
    plat_name = plat["name"]
    DIST.mkdir(exist_ok=True)

    print("=" * 62)
    print("dsh-desktop Nuitka 打包")
    print(f"平台     : {plat_name} ({plat['machine']}, {plat['bitness']} 位)")
    print(f"模式     : {'onefile' if args.onefile else 'onedir'}")
    print(f"入口     : {ENTRY}")
    print(f"输出目录 : {DIST}/")
    print("=" * 62)

    warnings = check_prereqs(plat_name)
    for w in warnings:
        print(f"警告: {w}")
    if any("Nuitka 不可用" in w for w in warnings):
        return 1

    nuitka_args = build_nuitka_args(plat_name, args)
    cmd = [sys.executable, "-m", "nuitka"] + nuitka_args
    print("\n执行命令:")
    print("  " + " ".join(cmd))
    if args.dry_run:
        return 0

    print("\n开始构建（PySide6 应用编译耗时较长，请耐心等待）...\n")
    # PYTHONPATH=src 让 Nuitka 通过 sys.path 解析 dsh_desktop 包
    env = dict(os.environ, PYTHONPATH=str(PROJECT_ROOT / "src"))
    proc = subprocess.run(cmd, cwd=PROJECT_ROOT, env=env)
    if proc.returncode != 0:
        print(f"\n构建失败（退出码 {proc.returncode}）")
        return proc.returncode

    print("\n构建完成，打包产物...")
    out_path = post_build(plat, args)
    print("\n" + "=" * 62)
    print("打包成功，产物：")
    print(f"  {out_path.relative_to(PROJECT_ROOT)}")
    print("=" * 62)
    return 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
