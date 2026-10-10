# -*- coding: utf-8 -*-
"""虚拟摄像头驱动全自动安装与检测中枢 (tools/vcam/setup_vcam.py)"""
from __future__ import annotations

import os
import sys
import subprocess
import webbrowser
from typing import Tuple

# 强制控制台输出 UTF-8
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass


def check_vcam() -> Tuple[bool, str]:
    """检测系统中是否有可用的虚拟摄像头"""
    try:
        import pyvirtualcam
    except ImportError:
        return False, "pyvirtualcam 运行库未安装"

    try:
        with pyvirtualcam.Camera(width=640, height=480, fps=25) as cam:
            return True, f"{cam.device} ({cam.backend})"
    except Exception as e:
        err = str(e)
        if "device not found" in err or "No camera registered" in err:
            return False, "未检测到可用的虚拟摄像头驱动"
        return False, err


def get_unitycapture_paths() -> Tuple[str, str]:
    """获取 UnityCapture 64位与32位滤镜 DLL 绝对路径"""
    curr_dir = os.path.dirname(os.path.abspath(__file__))
    dll64 = os.path.join(curr_dir, "unitycapture", "UnityCaptureFilter64.dll")
    dll32 = os.path.join(curr_dir, "unitycapture", "UnityCaptureFilter32.dll")
    return dll64, dll32


def install_unitycapture() -> Tuple[bool, str]:
    """通过管理员权限注册 UnityCapture 驱动 (DirectShow)"""
    dll64, dll32 = get_unitycapture_paths()
    if not os.path.exists(dll64):
        return False, f"未找到驱动文件: {dll64}"

    # 使用 PowerShell 申请单次管理员权限 (UAC 弹窗)，同时注册 64位与 32位滤镜
    # 避免任何批处理文件与 PATH 中的 install.cmd 冲突
    ps_cmd = (
        f"Start-Process cmd -ArgumentList "
        f"'/c regsvr32.exe /s \"{dll64}\" & regsvr32.exe /s \"{dll32}\"' "
        f"-Verb RunAs -Wait"
    )

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            return False, f"注册命令执行失败 (退出码 {res.returncode}): {res.stderr}"
    except subprocess.TimeoutExpired:
        return False, "管理员授权超时或已取消"
    except Exception as e:
        return False, f"调用系统 UAC 授权异常: {e}"

    # 验证是否就绪
    ok, dev = check_vcam()
    if ok:
        return True, f"UnityCapture 注册成功！当前就绪设备: {dev}"
    return True, "UnityCapture 驱动已写入系统注册表，请刷新或重启客户端测试"


def uninstall_unitycapture() -> Tuple[bool, str]:
    """通过管理员权限注销 UnityCapture 驱动"""
    dll64, dll32 = get_unitycapture_paths()
    if not os.path.exists(dll64):
        return False, f"未找到驱动文件: {dll64}"

    ps_cmd = (
        f"Start-Process cmd -ArgumentList "
        f"'/c regsvr32.exe /u /s \"{dll64}\" & regsvr32.exe /u /s \"{dll32}\"' "
        f"-Verb RunAs -Wait"
    )

    try:
        res = subprocess.run(
            ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_cmd],
            capture_output=True,
            text=True,
            timeout=60,
        )
        if res.returncode != 0:
            return False, f"注销命令执行失败: {res.stderr}"
        return True, "UnityCapture 驱动已完全注销"
    except Exception as e:
        return False, f"注销驱动异常: {e}"


def install_obs_winget():
    """打开新控制台执行 winget 安装 OBS Studio (锁定官方 winget 源)"""
    cmd = (
        'start "安装 OBS Studio" cmd /k '
        '"winget install --id OBSProject.OBSStudio -e --source winget --accept-package-agreements --accept-source-agreements '
        '&& echo. && echo [OK] OBS 安装完成！请在 OBS 中点击一次【启动虚拟摄像机】即可。 & pause"'
    )
    subprocess.Popen(cmd, shell=True)


def open_obs_download():
    """打开浏览器前往 OBS 官网下载"""
    webbrowser.open("https://obsproject.com/download")


def cli_menu():
    """终端交互命令行菜单"""
    while True:
        os.system("cls" if os.name == "nt" else "clear")
        print("=" * 63)
        print("    WeChat-AIAgent 微信虚拟数字人摄像头驱动安装与检测中枢")
        print("=" * 63)
        print()
        ok, msg = check_vcam()
        if ok:
            print(f"[*] 当前驱动状态: [OK] 已就绪 -> {msg}")
        else:
            print(f"[*] 当前驱动状态: [INFO] 尚未就绪 ({msg})")
        print()
        print("=" * 63)
        print("请选择操作方案:")
        print("=" * 63)
        print("  [1] 一键安装轻量虚拟摄像头 (UnityCapture，仅 150KB，秒级生效，推荐)")
        print("  [2] 通过 WinGet 自动安装完整 OBS Studio (使用官方 winget 源)")
        print("  [3] 打开 OBS Studio 官网下载安装包 (浏览器下载)")
        print("  [4] 卸载 UnityCapture 驱动")
        print("  [5] 刷新并重新检测当前状态")
        print("  [0] 退出")
        print("=" * 63)
        choice = input("请输入选项序号 [1-5 或 0]: ").strip()

        if choice == "1":
            print("\n[*] 正在请求管理员权限 (UAC) 注册 DirectShow 滤镜驱动...")
            success, info = install_unitycapture()
            print(f"\n{info}")
            input("\n按回车键继续...")
        elif choice == "2":
            print("\n[*] 正在启动 WinGet 安装程序...")
            install_obs_winget()
            input("\n按回车键继续...")
        elif choice == "3":
            print("\n[*] 正在打开 OBS 官方下载页面...")
            open_obs_download()
            input("\n按回车键继续...")
        elif choice == "4":
            print("\n[*] 正在请求管理员权限 (UAC) 注销驱动...")
            success, info = uninstall_unitycapture()
            print(f"\n{info}")
            input("\n按回车键继续...")
        elif choice == "5":
            continue
        elif choice == "0":
            break


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "--check":
        ok, msg = check_vcam()
        print(f"[{'OK' if ok else 'INFO'}] {msg}")
        sys.exit(0 if ok else 2)
    elif len(sys.argv) > 1 and sys.argv[1] == "--install-unity":
        ok, msg = install_unitycapture()
        print(msg)
        sys.exit(0 if ok else 1)
    else:
        cli_menu()
