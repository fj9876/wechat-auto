# -*- coding: utf-8 -*-
"""虚拟摄像头驱动检测工具 (tools/vcam/check_vcam.py)"""
import sys

# 强制控制台编码为 UTF-8，杜绝 Windows 命令行乱码
if hasattr(sys.stdout, "reconfigure"):
    try:
        sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    except Exception:
        pass

def main():
    try:
        import pyvirtualcam
    except ImportError:
        print("[FAIL] pyvirtualcam 模块未安装！请先在 runtime 环境中安装 pyvirtualcam。")
        return 1

    try:
        with pyvirtualcam.Camera(width=640, height=480, fps=25) as cam:
            print(f"[OK] 虚拟摄像头驱动已就绪！当前检测到设备: {cam.device} (后端: {cam.backend})")
            return 0
    except Exception as e:
        err = str(e)
        if "device not found" in err or "No camera registered" in err:
            print("[INFO] 当前系统中未检测到已就绪的虚拟摄像头 DirectShow 滤镜驱动。")
        else:
            print(f"[WARN] 检测虚拟摄像头时异常: {err}")
        return 2

if __name__ == "__main__":
    sys.exit(main())
