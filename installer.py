"""ClipAtlas 安装器（G 盘便携包 -> 安装版）

安装包结构：
    ClipAtlasSetup.exe        <- 本安装器（PyInstaller onefile）
    app/                      <- 便携包完整内容（dist/ClipAtlas/*）

功能：
  1. 说明：安装向导第一页展示软件说明与系统要求
  2. 环境检测：WebView2 Runtime / VC++ Redist 2015-2022 x64，缺失时给出国内下载地址
  3. 安装完成后删除安装包（安装器自身），无需确认
"""
from __future__ import annotations

import ctypes
import os
import shutil
import subprocess
import sys
import tkinter as tk
from pathlib import Path
from tkinter import filedialog, messagebox, ttk

APP_NAME = "ClipAtlas"
DEFAULT_INSTALL_DIR = os.path.join(os.environ.get("LOCALAPPDATA", r"C:\Users\Public"), "Programs", APP_NAME)

WEBVIEW2_GUID = "{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}"
WEBVIEW2_DOWNLOAD = "https://developer.microsoft.com/zh-cn/microsoft-edge/webview2/"
VC_REDIST_URL = "https://aka.ms/vs/17/release/vc_redist.x64.exe"
VC_REDIST_PAGE = "https://learn.microsoft.com/zh-cn/cpp/windows/latest-supported-vc-redist"

WELCOME_TEXT = f"""{APP_NAME} 安装程序

ClipAtlas 是一款 AI 视频粗剪工具，把文案自动变成剪映草稿：

· 导入本地素材，自动建立素材库
· 输入文案，自动按内容匹配画面
· 自动生成字幕 / 旁白
· 一键导出剪映粗剪草稿，人工微调即可成片

系统要求：
· Windows 10 / 11（64 位）
· WebView2 Runtime（Edge 自带，缺失时安装程序会提示下载）
· 建议 8GB 以上内存、10GB 以上磁盘空间
· 首次使用需在软件内填入大模型 API Key
"""


def _reg_value_winreg(root, subkey, name):
    """直接通过注册表 API 读取值，避免调用外部 reg.exe（不闪窗、不依赖 cmd）。"""
    try:
        import winreg
        with winreg.OpenKey(root, subkey) as k:
            v, _ = winreg.QueryValueEx(k, name)
            return str(v).strip()
    except OSError:
        return None


def check_webview2() -> tuple[bool, str]:
    import winreg
    for root in (winreg.HKEY_LOCAL_MACHINE, winreg.HKEY_CURRENT_USER):
        for subkey in (
            r"SOFTWARE\WOW6432Node\Microsoft\EdgeUpdate\Clients\%s" % WEBVIEW2_GUID,
            r"SOFTWARE\Microsoft\EdgeUpdate\Clients\%s" % WEBVIEW2_GUID,
        ):
            v = _reg_value_winreg(root, subkey, "pv")
            if v:
                return True, v
    # 兜底：检查 edge webview2 程序目录
    candidates = [
        Path(os.environ.get("PROGRAMFILES", r"C:\Program Files")) / "Microsoft" / "EdgeWebView" / "Application",
        Path(os.environ.get("PROGRAMFILES(X86)", r"C:\Program Files (x86)")) / "Microsoft" / "EdgeWebView" / "Application",
    ]
    for c in candidates:
        if c.exists():
            ver = [p.name for p in c.iterdir() if p.is_dir()]
            return True, ver[0] if ver else "installed"
    return False, ""


def check_vcredist() -> tuple[bool, str]:
    import winreg
    v = _reg_value_winreg(winreg.HKEY_LOCAL_MACHINE,
                           r"SOFTWARE\Microsoft\VisualStudio\14.0\VC\Runtimes\x64", "Version")
    if v:
        return True, v
    return False, ""


class InstallerApp:
    def __init__(self, root: tk.Tk) -> None:
        self.root = root
        root.title(f"{APP_NAME} 安装程序")
        root.geometry("680x600")
        root.resizable(False, False)
        root.configure(bg="#F4F3EE")

        self.app_dir = self._locate_app_dir()
        self.install_dir = tk.StringVar(value=DEFAULT_INSTALL_DIR)

        self._build_header()
        self.container = tk.Frame(root, bg="#F4F3EE")
        self.container.pack(fill="both", expand=True, padx=24, pady=(4, 8))
        self.pages: dict[str, tk.Frame] = {}
        self._build_pages()
        self._show("welcome")

    # ---------- helpers ----------
    def _locate_app_dir(self) -> Path:
        """安装器同目录下的 app/ 即便携包内容；onefile 解压模式下用 _MEIPASS 回退"""
        if getattr(sys, "frozen", False):
            here = Path(sys.argv[0]).resolve().parent if sys.argv[0] else Path(sys.executable).resolve().parent
        else:
            here = Path(__file__).resolve().parent
        candidate = here / "app"
        if candidate.exists():
            return candidate
        # PyInstaller onefile: 先看 _MEIPASS 旁
        meipass = Path(getattr(sys, "_MEIPASS", here))
        if (meipass / "app").exists():
            return meipass / "app"
        return candidate

    def _build_header(self) -> None:
        bar = tk.Frame(self.root, bg="#2F3945", height=72)
        bar.pack(fill="x")
        bar.pack_propagate(False)
        # 深色头栏放方形 logo 图标（若打包资源缺失则仅显示文字）
        try:
            icon_path = self.app_dir / "_internal" / "assets" / "clipatlas_icon.png"
            if icon_path.is_file():
                logo_img = tk.PhotoImage(file=str(icon_path))
                logo_img = logo_img.subsample(max(1, logo_img.width() // 40))
                tk.Label(bar, image=logo_img, bg="#2F3945").pack(side="left", padx=(18, 6))
                self._header_logo = logo_img  # 防止被 GC 回收
        except Exception:
            pass
        tk.Label(bar, text=APP_NAME, bg="#2F3945", fg="white",
                 font=("Microsoft YaHei UI", 20, "bold")).pack(side="left", padx=24)
        tk.Label(bar, text="安装程序", bg="#2F3945", fg="#C9D4DE",
                 font=("Microsoft YaHei UI", 11)).pack(side="left", padx=(0, 24))

    def _build_pages(self) -> None:
        # 1. 说明
        p1 = tk.Frame(self.container, bg="#F4F3EE")
        tk.Label(p1, text="欢迎安装 ClipAtlas", bg="#F4F3EE", fg="#1A1B1C",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(4, 10))
        txt = tk.Text(p1, wrap="word", bg="white", fg="#2A2B2C", relief="flat",
                      borderwidth=1, highlightbackground="#E4E3DD", highlightthickness=1,
                         font=("Microsoft YaHei UI", 10), padx=14, pady=12, height=14)
        txt.insert("1.0", WELCOME_TEXT)
        txt.config(state="disabled")
        txt.pack(fill="both", expand=True)
        self.pages["welcome"] = p1

        # 2. 环境检测
        p2 = tk.Frame(self.container, bg="#F4F3EE")
        tk.Label(p2, text="环境检测", bg="#F4F3EE", fg="#1A1B1C",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(4, 10))
        self.wv_label = tk.Label(p2, text="WebView2 Runtime：检测中…", bg="#F4F3EE", fg="#1A1B1C",
                                 font=("Microsoft YaHei UI", 10), anchor="w")
        self.wv_label.pack(fill="x", pady=4)
        self.wv_hint = tk.Label(p2, text="", bg="#F4F3EE", fg="#B3261E",
                                font=("Microsoft YaHei UI", 9), anchor="w", justify="left", wraplength=600)
        self.wv_hint.pack(fill="x", pady=2)
        self.vc_label = tk.Label(p2, text="VC++ 运行库：检测中…", bg="#F4F3EE", fg="#1A1B1C",
                                 font=("Microsoft YaHei UI", 10), anchor="w")
        self.vc_label.pack(fill="x", pady=4)
        self.vc_hint = tk.Label(p2, text="", bg="#F4F3EE", fg="#B3261E",
                                font=("Microsoft YaHei UI", 9), anchor="w", justify="left", wraplength=600)
        self.vc_hint.pack(fill="x", pady=2)
        tk.Label(p2, text="（缺失项可先下载安装，再返回点击“重新检测”）",
                 bg="#F4F3EE", fg="#6B7280", font=("Microsoft YaHei UI", 9)).pack(anchor="w", pady=(8, 2))
        self.pages["env"] = p2

        # 3. 安装目录
        p3 = tk.Frame(self.container, bg="#F4F3EE")
        tk.Label(p3, text="选择安装位置", bg="#F4F3EE", fg="#1A1B1C",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(4, 10))
        row = tk.Frame(p3, bg="#F4F3EE")
        row.pack(fill="x")
        tk.Label(row, text="安装到：", bg="#F4F3EE", fg="#1A1B1C",
                 font=("Microsoft YaHei UI", 10)).pack(side="left")
        entry = tk.Entry(row, textvariable=self.install_dir, font=("Microsoft YaHei UI", 9))
        entry.pack(side="left", fill="x", expand=True, padx=8)
        tk.Button(row, text="浏览…", command=self._browse, bg="#FFFFFF", fg="#1A1B1C",
                  relief="flat", highlightbackground="#C9C4B8", padx=10,
                  font=("Microsoft YaHei UI", 9)).pack(side="left")
        tk.Label(p3, text=f"安装将占用约 {self._app_size_mb()} MB 磁盘空间。\n将创建桌面与开始菜单快捷方式。",
                 bg="#F4F3EE", fg="#6B7280", font=("Microsoft YaHei UI", 9),
                 justify="left", anchor="w").pack(anchor="w", pady=(16, 2))
        self.pages["dir"] = p3

        # 4. 安装进度
        p4 = tk.Frame(self.container, bg="#F4F3EE")
        tk.Label(p4, text="正在安装…", bg="#F4F3EE", fg="#1A1B1C",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(4, 14))
        self.progress = ttk.Progressbar(p4, mode="determinate", maximum=100)
        self.progress.pack(fill="x", pady=8)
        self.status = tk.Label(p4, text="准备中…", bg="#F4F3EE", fg="#1A1B1C",
                               font=("Microsoft YaHei UI", 10), anchor="w")
        self.status.pack(fill="x", pady=6)
        self.pages["install"] = p4

        # 5. 完成
        p5 = tk.Frame(self.container, bg="#F4F3EE")
        tk.Label(p5, text="安装完成", bg="#F4F3EE", fg="#1A1B1C",
                 font=("Microsoft YaHei UI", 15, "bold")).pack(anchor="w", pady=(4, 10))
        self.done_text = tk.Label(p5, text="", bg="#F4F3EE", fg="#1A1B1C",
                                  font=("Microsoft YaHei UI", 10), justify="left", anchor="w", wraplength=600)
        self.done_text.pack(fill="x", pady=6)
        self.pages["done"] = p5

        for page in self.pages.values():
            page.pack(fill="both", expand=True)
            page.pack_forget()

    # ---------- navigation ----------
    def _show(self, name: str) -> None:
        for page in self.pages.values():
            page.pack_forget()
        self.pages[name].pack(fill="both", expand=True)
        self.current = name
        self._update_buttons()

    def _update_buttons(self) -> None:
        for w in self.root.winfo_children():
            pass
        # 底部按钮条
        if hasattr(self, "btnbar"):
            self.btnbar.destroy()
        self.btnbar = tk.Frame(self.root, bg="#F4F3EE")
        self.btnbar.pack(side="bottom", fill="x", padx=24, pady=(0, 16))
        self.btnbar.pack_propagate(False)
        self.btnbar.configure(height=40)
        self._btn_prev = None
        self._btn_next = None
        if self.current == "welcome":
            tk.Button(self.btnbar, text="下一步", command=self._next, bg="#2F3945", fg="white",
                      relief="flat", padx=22, font=("Microsoft YaHei UI", 10)).pack(side="right")
        elif self.current == "env":
            tk.Button(self.btnbar, text="重新检测", command=self.run_env_check, bg="#FFFFFF", fg="#1A1B1C",
                      relief="flat", highlightbackground="#C9C4B8", padx=14,
                      font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Button(self.btnbar, text="下一步", command=self._next, bg="#2F3945", fg="white",
                      relief="flat", padx=22, font=("Microsoft YaHei UI", 10)).pack(side="right")
        elif self.current == "dir":
            tk.Button(self.btnbar, text="上一步", command=self._prev, bg="#FFFFFF", fg="#1A1B1C",
                      relief="flat", highlightbackground="#C9C4B8", padx=14,
                      font=("Microsoft YaHei UI", 9)).pack(side="left")
            tk.Button(self.btnbar, text="开始安装", command=self._install, bg="#2F3945", fg="white",
                      relief="flat", padx=22, font=("Microsoft YaHei UI", 10)).pack(side="right")
        elif self.current == "install":
            pass
        elif self.current == "done":
            tk.Button(self.btnbar, text="完成", command=self._finish, bg="#2F3945", fg="white",
                      relief="flat", padx=22, font=("Microsoft YaHei UI", 10)).pack(side="right")

    def _next(self) -> None:
        order = ["welcome", "env", "dir", "install"]
        if self.current == "env" and self.current in order:
            pass
        nxt = order[order.index(self.current) + 1]
        if nxt == "env":
            self.run_env_check()
        self._show(nxt)

    def _prev(self) -> None:
        order = ["welcome", "env", "dir"]
        self._show(order[order.index(self.current) - 1])

    def _browse(self) -> None:
        d = filedialog.askdirectory(title="选择安装位置")
        if d:
            self.install_dir.set(os.path.join(d, APP_NAME))

    def _app_size_mb(self) -> int:
        if not self.app_dir.exists():
            return 0
        total = sum(f.stat().st_size for f in self.app_dir.rglob("*") if f.is_file())
        return max(1, round(total / (1024 * 1024)))

    # ---------- env check ----------
    def run_env_check(self) -> None:
        self.wv_label.config(text="WebView2 Runtime：检测中…")
        self.vc_label.config(text="VC++ 运行库：检测中…")
        self.wv_hint.config(text="")
        self.vc_hint.config(text="")
        self.root.update_idletasks()
        wv_ok, wv_ver = check_webview2()
        vc_ok, vc_ver = check_vcredist()
        if wv_ok:
            self.wv_label.config(text=f"WebView2 Runtime：已安装（{wv_ver}）", fg="#1A1B1C")
        else:
            self.wv_label.config(text="WebView2 Runtime：未检测到", fg="#B3261E")
            self.wv_hint.config(text="ClipAtlas 需要 WebView2 Runtime（Windows 10/11 通常已自带）。\n"
                                     "国内下载地址（微软官方中文页）：\n"
                                     "https://developer.microsoft.com/zh-cn/microsoft-edge/webview2/")
        if vc_ok:
            self.vc_label.config(text=f"VC++ 运行库：已安装（{vc_ver}）", fg="#1A1B1C")
        else:
            self.vc_label.config(text="VC++ 运行库（2015-2022 x64）：未检测到", fg="#B3261E")
            self.vc_hint.config(text="建议安装 Microsoft Visual C++ 2015-2022 Redistributable (x64)。\n"
                                     "国内下载地址：\n"
                                     "https://aka.ms/vs/17/release/vc_redist.x64.exe\n"
                                     "（微软官方直链，国内可直接访问）")

    # ---------- install ----------
    def _install(self) -> None:
        if not self.app_dir.exists():
            messagebox.showerror("错误", "未找到安装源（app 目录缺失）。请重新下载完整安装包。")
            return
        target = Path(self.install_dir.get())
        try:
            target.mkdir(parents=True, exist_ok=True)
        except Exception as exc:
            messagebox.showerror("错误", f"无法创建安装目录：{exc}")
            return
        self._show("install")
        self.root.update()
        self._do_copy(target)

    def _do_copy(self, target: Path) -> None:
        files = [f for f in self.app_dir.rglob("*") if f.is_file()]
        total = len(files)
        copied = 0
        try:
            for src in files:
                rel = src.relative_to(self.app_dir)
                dst = target / rel
                # 用户数据（数据库 / 配置 / 缓存 / 日志）保留现有内容，不覆盖；
                # 其余程序文件（exe / _internal / 前端资源）总是覆盖，保证覆盖安装生效。
                if rel.parts and rel.parts[0] == "data" and dst.exists():
                    copied += 1
                    continue
                dst.parent.mkdir(parents=True, exist_ok=True)
                try:
                    shutil.copy2(src, dst)
                except PermissionError:
                    messagebox.showerror(
                        "安装失败",
                        f"无法覆盖程序文件：\n{dst}\n\n请先关闭正在运行的 ClipAtlas，再重新安装。",
                    )
                    return
                copied += 1
                if copied % 200 == 0 or copied == total:
                    self.progress["value"] = copied / total * 100
                    self.status.config(text=f"复制文件 {copied}/{total} …")
                    self.root.update()
            self._create_shortcuts(target)
            self.progress["value"] = 100
            self.status.config(text="创建快捷方式…")
            self.root.update()
            self.done_text.config(text=f"ClipAtlas 已安装到：\n{target}")
            self._show("done")
            self._self_delete()
        except Exception as exc:
            messagebox.showerror("安装失败", f"安装过程中出现错误：\n{exc}")

    def _create_shortcuts(self, target: Path) -> None:
        exe = target / "ClipAtlas.exe"
        ps = (
            "$ws = New-Object -ComObject WScript.Shell; "
            f"$s = $ws.CreateShortcut([Environment]::GetFolderPath('Desktop') + '\\{APP_NAME}.lnk'); "
            f"$s.TargetPath = '{exe}'; $s.IconLocation = '{exe},0'; $s.WorkingDirectory = '{target}'; $s.Save(); "
            f"$m = [Environment]::GetFolderPath('Programs') + '\\{APP_NAME}.lnk'; "
            f"$s2 = $ws.CreateShortcut($m); $s2.TargetPath = '{exe}'; $s2.IconLocation = '{exe},0'; $s2.WorkingDirectory = '{target}'; $s2.Save()"
        )
        subprocess.run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps],
                       capture_output=True, timeout=60)

    def _self_delete(self) -> None:
        """安装完成后删除安装包（安装器自身 exe），无需确认。

        安装器运行时 Windows 不允许删除正在运行的 exe，因此先写一个轮询
        bat：等待本进程完全退出（用户点“完成”关闭窗口）后再删除 exe，
        顺带尝试清理空的所在目录。
        """
        if not getattr(sys, "frozen", False):
            return
        target = Path(sys.argv[0]).resolve() if sys.argv[0] else Path(sys.executable).resolve()
        if not target.exists():
            return
        exe_name = target.name
        parent = target.parent
        try:
            import tempfile
            bat = Path(tempfile.gettempdir()) / f"_clipatlas_setup_del_{os.getpid()}.bat"
            bat.write_text(
                "@echo off\r\n"
                "set /a n=0\r\n"
                ":wait\r\n"
                f'tasklist /fi "imagename eq {exe_name}" 2>nul | find /i "{exe_name}" >nul\r\n'
                "if errorlevel 1 goto del\r\n"
                "ping -n 2 127.0.0.1 >nul\r\n"
                "set /a n+=1\r\n"
                "if %n% lss 60 goto wait\r\n"
                ":del\r\n"
                f'del /f /q "{target}"\r\n'
                f'rmdir "{parent}" 2>nul\r\n'
                'del /f /q "%~f0"\r\n',
                encoding="gbk", errors="ignore",
            )
            subprocess.Popen(
                ["cmd", "/c", str(bat)],
                creationflags=0x08000000,  # CREATE_NO_WINDOW
            )
        except Exception:
            pass

    def _finish(self) -> None:
        self.root.destroy()


def main() -> None:
    # PyInstaller --windowed has a bootloader bug here (tkinter window never
    # appears), so we build --console and hide the console window ourselves.
    try:
        cw = ctypes.windll.kernel32.GetConsoleWindow()
        if cw:
            ctypes.windll.user32.ShowWindow(cw, 0)  # SW_HIDE
    except Exception:
        pass
    root = tk.Tk()
    try:
        ctypes.windll.shcore.SetProcessDpiAwareness(1)
    except Exception:
        pass
    app = InstallerApp(root)
    root.after(300, app.run_env_check)
    root.mainloop()


if __name__ == "__main__":
    main()
