"""
Apple TV Remote — Windows 托盘应用入口
打包: PyInstaller -> Inno Setup
"""
import sys
import os
import threading
import time
import webbrowser

PORT = 7000
APP_NAME = "Apple TV 遥控器"


def resource_path(rel: str) -> str:
    """兼容 PyInstaller 的资源路径 (支持 PyInstaller 6+ 的 _internal 布局)"""
    if hasattr(sys, "_MEIPASS"):
        # 首先尝试在根目录找
        path = os.path.join(sys._MEIPASS, rel)
        if os.path.exists(path):
            return path
        # 其次尝试在 _internal 目录找 (PyInstaller 6+ 默认)
        internal_path = os.path.join(sys._MEIPASS, "_internal", rel)
        if os.path.exists(internal_path):
            return internal_path
        return path # Fallback to root if neither exists
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), rel)


def start_server():
    """在后台线程运行 uvicorn"""
    try:
        import uvicorn
        # 兼容 PyInstaller 6+: 确保 _internal 被加入路径
        if hasattr(sys, "_MEIPASS"):
            internal_dir = os.path.join(sys._MEIPASS, "_internal")
            if os.path.exists(internal_dir) and internal_dir not in sys.path:
                sys.path.insert(0, internal_dir)
        
        sys.path.insert(0, resource_path("."))
        
        print(f"正在启动后端服务... 静态目录: {resource_path('static')}")
        from server import create_app
        app = create_app(resource_path("static"))
        uvicorn.run(app, host="127.0.0.1", port=PORT, log_level="info")
    except Exception as e:
        import traceback
        print("-" * 40)
        print(f"后端启动致命错误: {e}")
        traceback.print_exc()
        print("-" * 40)
        # 保持窗口打开
        time.sleep(30)


def make_icon():
    """用 Pillow 画一个 TV 图标，无需外部 .ico 文件"""
    from PIL import Image, ImageDraw
    size = 64
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    d = ImageDraw.Draw(img)
    # 外框
    d.rounded_rectangle([2, 4, 62, 48], radius=8, fill=(28, 28, 30))
    # 屏幕
    d.rounded_rectangle([6, 8, 58, 44], radius=5, fill=(10, 132, 255))
    # Apple logo (简化白点)
    d.ellipse([28, 22, 36, 30], fill=(255, 255, 255, 200))
    # 支架
    d.rectangle([28, 48, 36, 56], fill=(28, 28, 30))
    d.rounded_rectangle([18, 55, 46, 61], radius=3, fill=(28, 28, 30))
    return img


def open_browser_delayed():
    time.sleep(1.8)
    webbrowser.open(f"http://127.0.0.1:{PORT}")


def run():
    # 启动后端
    t = threading.Thread(target=start_server, daemon=True)
    t.start()

    # 延迟打开浏览器
    bt = threading.Thread(target=open_browser_delayed, daemon=True)
    bt.start()

    # 系统托盘
    try:
        import pystray
        icon_img = make_icon()

        def on_open(icon, item):
            webbrowser.open(f"http://127.0.0.1:{PORT}")

        def on_quit(icon, item):
            icon.stop()
            sys.exit(0)

        menu = pystray.Menu(
            pystray.MenuItem("打开遥控器", on_open, default=True),
            pystray.Menu.SEPARATOR,
            pystray.MenuItem("退出", on_quit),
        )
        tray = pystray.Icon(APP_NAME, icon_img, APP_NAME, menu)
        tray.run()
    except Exception as e:
        print(f"托盘启动失败: {e}，仅运行后端…")
        t.join()


if __name__ == "__main__":
    run()
