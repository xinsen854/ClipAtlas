"""Self-installing Windows desktop launcher for the small LAN search companion."""
from __future__ import annotations

import argparse
import ctypes
import json
import os
from pathlib import Path
import shutil
import socket
import subprocess
import sys
import threading
import time
import tkinter as tk
from tkinter import filedialog, messagebox, ttk

import httpx
import uvicorn

from clipatlas.lan import PORT, DISCOVERY_PORT, advertise, create_gateway
from clipatlas.lan_library import create_library_app, validate_data_root

APP = "ClipAtlasSearch"
TITLE = "ClipAtlas 素材搜索 · 局域网版"
CONFIG = Path(os.environ.get("LOCALAPPDATA", str(Path.home()))) / APP
DEFAULT_INSTALL = CONFIG.parent / "Programs" / APP


def bundle_root() -> Path:
    return Path(getattr(sys, "_MEIPASS", Path(__file__).resolve().parents[1]))


def start_server(app, host: str, port: int) -> uvicorn.Server:
    server = uvicorn.Server(uvicorn.Config(app, host=host, port=port,
                            log_config=None, access_log=False))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()
    deadline = time.monotonic() + 12
    while not server.started:
        if not thread.is_alive() or time.monotonic() > deadline:
            raise RuntimeError(f"无法启动服务，端口 {port} 可能已被占用")
        time.sleep(0.05)
    return server


def find_data_root() -> Path:
    saved = CONFIG / "shared-data.json"
    candidates: list[Path] = []
    if saved.is_file():
        try:
            candidates.append(Path(json.loads(saved.read_text(encoding="utf-8"))["path"]))
        except (OSError, ValueError, KeyError):
            pass
    candidates.extend([Path(r"D:\ClipAtlas\data"), Path.cwd() / "data"])
    for candidate in candidates:
        try:
            return validate_data_root(candidate)
        except ValueError:
            continue
    return Path(r"D:\ClipAtlas\data")


def host_is_running() -> bool:
    try:
        result = httpx.get(f"http://127.0.0.1:{PORT}/lan/info", timeout=2, trust_env=False)
        return result.status_code == 200 and result.json().get("host") is True
    except (httpx.HTTPError, ValueError):
        return False


def startup_shortcut() -> Path:
    return (Path(os.environ["APPDATA"]) /
            "Microsoft/Windows/Start Menu/Programs/Startup/ClipAtlas 素材库共享端.lnk")


def enable_always_on(executable: Path) -> None:
    path = startup_shortcut()
    path.parent.mkdir(parents=True, exist_ok=True)
    make_shortcut(path, executable, "--serve-host")


def configure_firewall() -> None:
    """Limit inbound access to local subnets; Windows requests elevation itself."""
    script = CONFIG / "enable-sharing.ps1"
    script.parent.mkdir(parents=True, exist_ok=True)
    script.write_text(
        "$ErrorActionPreference = 'Stop'\n"
        f"Get-NetFirewallRule -DisplayName 'ClipAtlas LAN Search TCP' -ErrorAction SilentlyContinue | Remove-NetFirewallRule\n"
        f"New-NetFirewallRule -DisplayName 'ClipAtlas LAN Search TCP' -Direction Inbound -Action Allow -Protocol TCP -LocalPort {PORT} -RemoteAddress LocalSubnet -Profile Any | Out-Null\n"
        f"Get-NetFirewallRule -DisplayName 'ClipAtlas LAN Search Discovery' -ErrorAction SilentlyContinue | Remove-NetFirewallRule\n"
        f"New-NetFirewallRule -DisplayName 'ClipAtlas LAN Search Discovery' -Direction Inbound -Action Allow -Protocol UDP -LocalPort {DISCOVERY_PORT} -RemoteAddress LocalSubnet -Profile Any | Out-Null\n",
        encoding="utf-8-sig",
    )
    result = ctypes.windll.shell32.ShellExecuteW(None, "runas", "powershell.exe",
        f'-NoProfile -ExecutionPolicy Bypass -File "{script}"', None, 0)
    if result <= 32:
        messagebox.showerror(TITLE, "未能配置防火墙。请同意 Windows 管理员提示后再试。")
    else:
        messagebox.showinfo(TITLE, "已请求 Windows 配置局域网访问。如仍无法连接，请检查 Windows 防火墙中两条 ClipAtlas LAN Search 入站规则。")


def host_window() -> None:
    root = tk.Tk()
    root.title("ClipAtlas 素材库共享端")
    root.geometry("690x440")
    root.configure(bg="#f8f4ef")
    frame = ttk.Frame(root, padding=26)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="共享这台电脑的标注素材库", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    ttk.Label(frame, text="设置一次后后台常开，并在登录 Windows 时自动启动；本设置窗口可以关闭。", padding=(0, 14)).pack(anchor="w")
    name = socket.gethostname()
    addresses = sorted({a[4][0] for a in socket.getaddrinfo(name, None, socket.AF_INET)
                        if not a[4][0].startswith(("127.", "169.254."))})
    ttk.Label(frame, text=(f"电脑名：\\\\{name}\n"
                           f"局域网 IP：{' / '.join(addresses) or '请检查网络连接'}\n"
                           f"局域网共享端口：{PORT}（自动发现：{DISCOVERY_PORT}）"),
              font=("Microsoft YaHei UI", 11), padding=(0, 12)).pack(anchor="w")
    data_path = tk.StringVar(value=str(find_data_root()))
    data_row = ttk.Frame(frame)
    data_row.pack(fill="x", pady=(2, 10))
    ttk.Label(data_row, text="标注数据目录：").pack(side="left")
    ttk.Entry(data_row, textvariable=data_path, width=48).pack(side="left", fill="x", expand=True)
    def choose_data():
        selected = filedialog.askdirectory(title="选择 ClipAtlas 标注数据目录", initialdir=data_path.get())
        if selected:
            data_path.set(selected)
    ttk.Button(data_row, text="选择", command=choose_data).pack(side="left", padx=(8, 0))
    status = tk.StringVar(value="准备启动共享…")
    ttk.Label(frame, textvariable=status, wraplength=620, padding=(0, 12)).pack(anchor="w")
    def begin():
        start_button.config(state="disabled")
        status.set("正在设置后台常开共享…")
        def worker():
            try:
                data_root = validate_data_root(Path(data_path.get()))
                (CONFIG / "shared-data.json").write_text(
                    json.dumps({"path": str(data_root)}, ensure_ascii=False), encoding="utf-8")
                executable = Path(sys.executable).resolve()
                enable_always_on(executable)
                if not host_is_running():
                    subprocess.Popen([str(executable), "--serve-host"], cwd=str(executable.parent),
                                     creationflags=subprocess.CREATE_NO_WINDOW)
                deadline = time.monotonic() + 30
                while not host_is_running() and time.monotonic() < deadline:
                    time.sleep(0.4)
                if not host_is_running():
                    raise RuntimeError("后台共享启动超时，请点击重试")
                root.after(0, lambda: status.set(
                    f"常开共享已启用 · 局域网端口 {PORT}\n"
                    f"正在只读使用 {data_root}。本窗口可以关闭，后台共享不会停止。"
                ))
                root.after(0, lambda: start_button.config(state="normal"))
            except Exception as exc:
                msg = str(exc)
                root.after(0, lambda: status.set(msg))
                root.after(0, lambda: start_button.config(state="normal"))
        threading.Thread(target=worker, daemon=True).start()

    buttons = ttk.Frame(frame)
    buttons.pack(anchor="w", pady=12)
    start_button = ttk.Button(buttons, text="设置常开共享 / 修复", command=begin)
    start_button.pack(side="left", padx=(0, 12))
    ttk.Button(buttons, text="允许局域网访问（防火墙）", command=configure_firewall).pack(side="left")
    ttk.Label(frame, text="客户端仅可搜索、读取标注和预览。母体无需运行；修改标注仍在原 ClipAtlas 中操作。",
              wraplength=620).pack(anchor="w", pady=10)
    root.after(200, begin)
    root.mainloop()


def client_window() -> None:
    import webview
    class Bridge:
        def choose_folder(self):
            selected = webview.windows[0].create_file_dialog(webview.FOLDER_DIALOG)
            return selected[0] if selected else None
    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    frontend = bundle_root() / "frontend" / "dist-lan"
    server = start_server(create_gateway(frontend=frontend, history_path=CONFIG / "connections.json"),
                          "127.0.0.1", port)
    try:
        webview.create_window(TITLE, f"http://127.0.0.1:{port}", width=1360, height=900,
                              min_size=(960, 680), background_color="#f8f4ef", js_api=Bridge())
        webview.start()
    finally:
        server.should_exit = True


def make_shortcut(path: Path, executable: Path, arguments: str) -> None:
    def quote(value):
        return "'" + str(value).replace("'", "''") + "'"
    script = ("$w = New-Object -ComObject WScript.Shell\n"
              f"$s = $w.CreateShortcut({quote(path)})\n"
              f"$s.TargetPath = {quote(executable)}\n"
              f"$s.Arguments = {quote(arguments)}\n"
              f"$s.WorkingDirectory = {quote(executable.parent)}\n"
              "$s.Save()\n")
    subprocess.run(["powershell.exe", "-NoProfile", "-Command", script], check=True,
                   creationflags=subprocess.CREATE_NO_WINDOW)


def install_window() -> None:
    root = tk.Tk()
    root.title("ClipAtlas 素材搜索 · 安装程序")
    root.geometry("680x430")
    frame = ttk.Frame(root, padding=26)
    frame.pack(fill="both", expand=True)
    ttk.Label(frame, text="安装局域网素材搜索", font=("Microsoft YaHei UI", 18, "bold")).pack(anchor="w")
    ttk.Label(frame, text="Windows 10 / 11（64 位）\n其他电脑安装后选择共享电脑，即可搜索现有标注并预览视频。\n无需安装 Python，也无需复制标注库。", padding=(0, 18)).pack(anchor="w")
    target = tk.StringVar(value=str(DEFAULT_INSTALL))
    ttk.Label(frame, text="安装位置").pack(anchor="w")
    ttk.Entry(frame, textvariable=target, width=75).pack(fill="x", pady=8)
    ttk.Button(frame, text="选择文件夹", command=lambda: target.set(filedialog.askdirectory() or target.get())).pack(anchor="w")
    role = tk.BooleanVar(value=False)
    ttk.Checkbutton(frame, text="这台电脑存有标注库（安装后打开共享端）", variable=role).pack(anchor="w", pady=18)
    status = tk.StringVar(value="将创建素材搜索和素材库共享端快捷方式。需要 Microsoft Edge WebView2。")
    ttk.Label(frame, textvariable=status, wraplength=620).pack(anchor="w", pady=8)

    def install():
        try:
            folder = Path(target.get()).expanduser().resolve()
            folder.mkdir(parents=True, exist_ok=True)
            executable = folder / f"{APP}.exe"
            source = Path(sys.executable).resolve()
            if executable != source:
                shutil.copy2(source, executable)
            desktop = Path(subprocess.check_output(["powershell.exe", "-NoProfile", "-Command",
                "[Environment]::GetFolderPath('Desktop')"], text=True,
                creationflags=subprocess.CREATE_NO_WINDOW).strip())
            programs = Path(os.environ["APPDATA"]) / "Microsoft/Windows/Start Menu/Programs" / APP
            programs.mkdir(parents=True, exist_ok=True)
            for base in (desktop, programs):
                make_shortcut(base / "ClipAtlas 素材搜索.lnk", executable, "--client")
                make_shortcut(base / "ClipAtlas 素材库共享端.lnk", executable, "--host")
            if role.get():
                enable_always_on(executable)
            elif startup_shortcut().exists():
                startup_shortcut().unlink()
            import winreg
            with winreg.CreateKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipAtlasSearch") as key:
                for name, value in {"DisplayName": TITLE, "DisplayVersion": "1.0.4",
                        "InstallLocation": str(folder), "DisplayIcon": str(executable),
                        "UninstallString": f'"{executable}" --uninstall'}.items():
                    winreg.SetValueEx(key, name, 0, winreg.REG_SZ, value)
            status.set("安装完成，桌面快捷方式已创建。")
            subprocess.Popen([str(executable), "--host" if role.get() else "--client"],
                             creationflags=subprocess.CREATE_NO_WINDOW)
            messagebox.showinfo(TITLE, "安装完成。\n共享电脑：打开素材库共享端并选择标注数据目录，母体无需运行。\n其他电脑：打开素材搜索，选择共享电脑。")
            root.destroy()
        except Exception as exc:
            messagebox.showerror("安装失败", str(exc))
    ttk.Button(frame, text="安装并打开", command=install).pack(anchor="e", pady=10)
    root.mainloop()


def uninstall() -> None:
    root = tk.Tk(); root.withdraw()
    if not messagebox.askyesno(TITLE, "卸载局域网素材搜索？原 ClipAtlas 和标注数据会保留。"):
        return
    import winreg
    with winreg.OpenKey(winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipAtlasSearch") as key:
        folder = Path(winreg.QueryValueEx(key, "InstallLocation")[0]).resolve()
    executable = folder / f"{APP}.exe"
    if executable != Path(sys.executable).resolve():
        raise RuntimeError("卸载路径与当前程序不一致")
    winreg.DeleteKey(winreg.HKEY_CURRENT_USER,
                    r"Software\Microsoft\Windows\CurrentVersion\Uninstall\ClipAtlasSearch")
    # Only remove the exact installed executable and our shortcuts; never recurse.
    def quote(value): return "'" + str(value).replace("'", "''") + "'"
    script = CONFIG / "uninstall.ps1"
    script.write_text(
        f"Wait-Process -Id {os.getpid()} -ErrorAction SilentlyContinue\n"
        f"Remove-Item -LiteralPath {quote(executable)} -ErrorAction SilentlyContinue\n"
        "$desktop = [Environment]::GetFolderPath('Desktop')\n"
        "$programs = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/ClipAtlasSearch'\n"
        "$startup = Join-Path $env:APPDATA 'Microsoft/Windows/Start Menu/Programs/Startup'\n"
        "foreach ($base in @($desktop, $programs, $startup)) {\n"
        " foreach ($name in @('ClipAtlas 素材搜索.lnk', 'ClipAtlas 素材库共享端.lnk')) {\n"
        "  Remove-Item -LiteralPath (Join-Path $base $name) -ErrorAction SilentlyContinue\n"
        " }\n}\n", encoding="utf-8-sig")
    subprocess.Popen(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(script)],
                     creationflags=subprocess.CREATE_NO_WINDOW)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--host", action="store_true")
    parser.add_argument("--client", action="store_true")
    parser.add_argument("--uninstall", action="store_true")
    parser.add_argument("--serve-client", type=int)
    parser.add_argument("--serve-host", action="store_true")
    args = parser.parse_args()
    CONFIG.mkdir(parents=True, exist_ok=True)
    log = open(CONFIG / "app.log", "a", encoding="utf-8", buffering=1)
    sys.stdout = sys.stderr = log
    try:
        if args.serve_client:
            uvicorn.run(create_gateway(frontend=bundle_root() / "frontend/dist-lan",
                        history_path=CONFIG / "connections.json"), host="127.0.0.1", port=args.serve_client,
                        log_config=None)
        elif args.serve_host:
            data_root = find_data_root()
            backend = create_library_app(data_root)
            threading.Thread(target=advertise, args=(threading.Event(),), daemon=True).start()
            uvicorn.run(create_gateway(host=True, upstream="http://library",
                        transport=httpx.ASGITransport(app=backend)), host="0.0.0.0", port=PORT,
                        log_config=None)
        elif args.uninstall:
            uninstall()
        elif args.host:
            host_window()
        elif args.client:
            client_window()
        else:
            install_window()
    except Exception as exc:
        import traceback
        traceback.print_exc()
        log.flush()
        if args.serve_client or args.serve_host:
            raise
        root = tk.Tk(); root.withdraw()
        messagebox.showerror(TITLE, f"{exc}\n\n日志：{CONFIG / 'app.log'}")


if __name__ == "__main__":
    main()
