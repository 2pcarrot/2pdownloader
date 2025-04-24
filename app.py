import tkinter as tk
from tkinter import ttk, messagebox, filedialog
from threading import Thread, Lock
import time
import os
import multiprocessing
from urllib.parse import urlparse, unquote
import requests
import json
import shutil

from core import Downloader


class DownloaderGUI:
    def __init__(self, root):
        self.root = root
        self.root.title("多任务文件下载器")
        self.root.geometry("600x500")
        
        self.settings_file = "settings.json"
        self.load_settings()
        
        tk.Label(root, text="下载链接:").pack(pady=5)
        self.url_entry = tk.Entry(root, width=50)
        self.url_entry.pack(pady=5)
        
        self.settings_button = tk.Button(root, text="设置", command=self.open_settings)
        self.settings_button.pack(pady=5)
        
        self.download_button = tk.Button(root, text="添加下载任务", command=self.add_download_task)
        self.download_button.pack(pady=10)
        
        self.task_frame_canvas = tk.Canvas(root)
        self.task_frame_scrollbar = ttk.Scrollbar(root, orient="vertical", command=self.task_frame_canvas.yview)
        self.task_frame = ttk.Frame(self.task_frame_canvas)
        self.task_frame.bind("<Configure>", lambda e: self.task_frame_canvas.configure(scrollregion=self.task_frame_canvas.bbox("all")))
        self.task_frame_canvas.create_window((0, 0), window=self.task_frame, anchor="nw")
        self.task_frame_canvas.configure(yscrollcommand=self.task_frame_scrollbar.set)
        self.task_frame_canvas.pack(side="left", fill=tk.BOTH, expand=True)
        self.task_frame_scrollbar.pack(side="right", fill=tk.Y)
        
        self.tasks = {}
        self.lock = Lock()
        self.running = True
        
        self.archive_file = "download_archive.json"
        self.load_tasks_from_archive()
        
        self.monitor_thread = Thread(target=self.monitor_tasks)
        self.monitor_thread.start()
        
        self.root.protocol("WM_DELETE_WINDOW", self.on_close)

    def load_settings(self):
        if not os.path.exists(self.settings_file):
            self.default_process_count = multiprocessing.cpu_count() * 2
            self.default_chunk_size = 20 * 1024 * 1024
            self.default_download_dir = "./downloads"
            self.default_proxy_mode = "system"
            self.default_proxies = {}
            return
        
        try:
            with open(self.settings_file, "r") as f:
                settings = json.load(f)
            self.default_process_count = settings.get("process_count", multiprocessing.cpu_count() * 2)
            self.default_chunk_size = settings.get("chunk_size", 20 * 1024 * 1024)
            self.default_download_dir = settings.get("download_dir", "./downloads")
            self.default_proxy_mode = settings.get("proxy_mode", "system")
            self.default_proxies = settings.get("proxies", {})
        except Exception as e:
            messagebox.showerror("加载设置失败", f"无法加载设置：{str(e)}")
            self.load_default_settings()

    def save_settings(self):
        settings = {
            "process_count": self.default_process_count,
            "chunk_size": self.default_chunk_size,
            "download_dir": self.default_download_dir,
            "proxy_mode": self.default_proxy_mode,
            "proxies": self.default_proxies,
        }
        try:
            with open(self.settings_file, "w") as f:
                json.dump(settings, f, indent=4)
        except Exception as e:
            messagebox.showerror("保存设置失败", f"无法保存设置：{str(e)}")

    def open_settings(self):
        settings_window = tk.Toplevel(self.root)
        settings_window.title("设置")
        settings_window.geometry("350x500")
        
        tk.Label(settings_window, text="下载目录:").pack(pady=5)
        download_dir_frame = tk.Frame(settings_window)
        download_dir_frame.pack(fill=tk.X, pady=5)
        self.download_dir_entry = tk.Entry(download_dir_frame, width=40)
        self.download_dir_entry.insert(0, self.default_download_dir)
        self.download_dir_entry.pack(side=tk.LEFT, padx=5)
        tk.Button(download_dir_frame, text="浏览", command=self.select_download_dir).pack(side=tk.RIGHT)
        
        tk.Label(settings_window, text="线程数:").pack(pady=5)
        self.process_count_entry = tk.Entry(settings_window, width=10)
        self.process_count_entry.insert(0, str(self.default_process_count))
        self.process_count_entry.pack(pady=5)
        
        tk.Label(settings_window, text="分块大小 (MB):").pack(pady=5)
        self.chunk_size_entry = tk.Entry(settings_window, width=10)
        self.chunk_size_entry.insert(0, str(self.default_chunk_size // (1024 * 1024)))
        self.chunk_size_entry.pack(pady=5)
        
        tk.Label(settings_window, text="代理模式:").pack(pady=5)
        proxy_mode_frame = tk.Frame(settings_window)
        proxy_mode_frame.pack(fill=tk.X, pady=5)
        self.proxy_mode_var = tk.StringVar(value=self.default_proxy_mode)
        tk.Radiobutton(proxy_mode_frame, text="系统代理", variable=self.proxy_mode_var, value="system").pack(side=tk.LEFT)
        tk.Radiobutton(proxy_mode_frame, text="手动代理", variable=self.proxy_mode_var, value="manual").pack(side=tk.LEFT)
        
        tk.Label(settings_window, text="代理地址 (仅手动模式):").pack(pady=5)
        self.proxies_entry = tk.Entry(settings_window, width=40)
        self.proxies_entry.insert(0, json.dumps(self.default_proxies) if self.default_proxies else "")
        self.proxies_entry.pack(pady=5)
        
        tk.Button(settings_window, text="保存", command=lambda: self.save_and_close_settings(settings_window)).pack(pady=10)

    def select_download_dir(self):
        directory = filedialog.askdirectory(initialdir=self.default_download_dir)
        if directory:
            self.download_dir_entry.delete(0, tk.END)
            self.download_dir_entry.insert(0, directory)

    def save_and_close_settings(self, window):
        try:
            self.default_download_dir = self.download_dir_entry.get().strip()
            self.default_process_count = int(self.process_count_entry.get().strip())
            self.default_chunk_size = int(self.chunk_size_entry.get().strip()) * 1024 * 1024
            self.default_proxy_mode = self.proxy_mode_var.get()
            proxies_str = self.proxies_entry.get().strip()
            self.default_proxies = json.loads(proxies_str) if proxies_str else {}
            self.save_settings()
            messagebox.showinfo("设置保存成功", "设置已保存！")
            window.destroy()
        except Exception as e:
            messagebox.showerror("设置保存失败", f"无法保存设置：{str(e)}")

    def add_download_task(self):
        url = self.url_entry.get().strip()
        if not url:
            return
        with self.lock:
            for task_id, task_info in self.tasks.items():
                if task_info["url"] == url:
                    if task_info["downloader"].is_completed():
                        filepath = os.path.join(task_info["download_dir"], task_info["filename"])
                        if os.path.exists(filepath):
                            messagebox.showinfo("文件已下载", f"文件已下载完成：\n{filepath}")
                            self.open_file(filepath)
                            return
                    else:
                        messagebox.showwarning("重复任务", "该任务已在下载中，请勿重复添加！")
                        return
        self.url_entry.delete(0, tk.END)
        with self.lock:
            task_id = f"task_{len(self.tasks) + 1}"
            filename = self.get_filename(url) or "未知文件"
            downloader = Downloader(
                url=url,
                download_dir=self.default_download_dir,
                chunk_size_mb=self.default_chunk_size // (1024 * 1024),
                max_workers=self.default_process_count,
                proxy_mode=self.default_proxy_mode,
                proxies=self.default_proxies if self.default_proxy_mode == "manual" else None
            )
            task_widgets = self.create_task_widgets(task_id, filename, url)
            self.tasks[task_id] = {
                "url": url,
                "filename": filename,
                "download_dir": self.default_download_dir,
                "widgets": task_widgets,
                "downloader": downloader,
                "thread": None,
                "running": True,
                "stopped": False,
            }
            thread = Thread(target=self.run_downloader, args=(task_id,))
            self.tasks[task_id]["thread"] = thread
            thread.start()

    def get_filename(self, url):
        try:
            response = requests.head(url, allow_redirects=True, timeout=5)
            headers = response.headers
            downloader = Downloader(url=url, download_dir="./downloads")
            filename = downloader.parse_filename_from_headers(headers)
            if filename:
                return filename
        except Exception:
            pass
        parsed_url = urlparse(url)
        filename = os.path.basename(parsed_url.path)
        filename = unquote(filename)
        return filename or "未知文件"

    def create_task_widgets(self, task_id, filename, url):
        frame = tk.Frame(self.task_frame, borderwidth=1, relief="solid")
        frame.pack(fill=tk.X, pady=5, side=tk.TOP)
        name_label = tk.Label(frame, text=f"任务 {task_id}: {filename}")
        name_label.pack(anchor=tk.W)
        progress_bar = ttk.Progressbar(frame, orient="horizontal", length=500, mode="determinate")
        progress_bar.pack(pady=5)
        percent_label = tk.Label(frame, text="进度: 0%")
        percent_label.pack(anchor=tk.W)
        eta_label = tk.Label(frame, text="ETA: --:--:--")
        eta_label.pack(anchor=tk.W)
        status_label = tk.Label(frame, text="等待下载...")
        status_label.pack(anchor=tk.W)
        button_frame = tk.Frame(frame)
        button_frame.pack(anchor=tk.W)
        stop_button = tk.Button(button_frame, text="停止", command=lambda: self.stop_task(task_id))
        stop_button.pack(side=tk.LEFT, padx=5)
        restart_button = tk.Button(button_frame, text="重启", command=lambda: self.restart_task(task_id))
        restart_button.pack(side=tk.LEFT, padx=5)
        open_button = tk.Button(button_frame, text="打开文件", command=lambda: self.open_file_safe(task_id))
        open_button.pack(side=tk.LEFT, padx=5)
        delete_button = tk.Button(button_frame, text="删除", command=lambda: self.delete_task(task_id))
        delete_button.pack(side=tk.LEFT, padx=5)
        return {
            "frame": frame,
            "name_label": name_label,
            "progress_bar": progress_bar,
            "percent_label": percent_label,
            "eta_label": eta_label,
            "status_label": status_label,
            "stop_button": stop_button,
            "restart_button": restart_button,
            "open_button": open_button,
            "delete_button": delete_button,
        }

    def open_file_safe(self, task_id):
        with self.lock:
            task_info = self.tasks.get(task_id)
            if not task_info:
                return
            downloader = task_info["downloader"]
            if not downloader.is_completed():
                messagebox.showwarning("文件未完成", "文件尚未下载完成，无法打开！")
                return
            filepath = os.path.join(task_info["download_dir"], task_info["filename"])
            self.open_file(filepath)

    def delete_task(self, task_id):
        with self.lock:
            task_info = self.tasks.get(task_id)
            if not task_info:
                return
            
            downloader = task_info["downloader"]
            if task_info["running"]:
                task_info["running"] = False
                downloader.stop(True)

            time.sleep(1)
            
            filename = task_info["filename"]
            folder_name = os.path.splitext(filename)[0]
            folder_path = os.path.join(task_info["download_dir"], folder_name)

            if not downloader.is_completed():
                if os.path.exists(folder_path) and os.path.isdir(folder_path):
                    try:
                        for file_or_dir in os.listdir(folder_path):
                            item_path = os.path.join(folder_path, file_or_dir)
                            if os.path.isfile(item_path):
                                os.remove(item_path)
                            elif os.path.isdir(item_path):
                                shutil.rmtree(item_path)
                        os.rmdir(folder_path)
                        messagebox.showinfo("删除成功", f"已清空并删除零时文件夹：{folder_path}")
                    except Exception as e:
                        messagebox.showerror("删除失败", f"无法清理或删除文件夹：{str(e)}")
            
            else:
                filepath = os.path.join(task_info["download_dir"], filename)
                if os.path.exists(filepath):
                    try:
                        os.remove(filepath)
                        messagebox.showinfo("删除成功", "已删除下载完成的文件！")
                    except Exception as e:
                        messagebox.showerror("删除失败", f"无法删除文件：{str(e)}")

            task_info["widgets"]["frame"].destroy()
            del self.tasks[task_id]

    def run_downloader(self, task_id):
        with self.lock:
            task_info = self.tasks[task_id]
            url = task_info["url"]
            widgets = task_info["widgets"]
            downloader = task_info["downloader"]
        try:
            widgets["status_label"].config(text="正在下载...")
            while task_info["running"]:
                if task_info["stopped"]:
                    break
                downloader.download()
                if downloader.is_completed():
                    widgets["status_label"].config(text="下载完成！")
                    task_info["running"] = False
                    break
        except Exception as e:
            widgets["status_label"].config(text=f"下载失败: {str(e)}")
        finally:
            task_info["running"] = False

    def stop_task(self, task_id):
        with self.lock:
            task_info = self.tasks.get(task_id)
            if not task_info or task_info["stopped"]:
                return
            downloader = task_info["downloader"]
            downloader.stop(True)
            task_info["stopped"] = True
            task_info["running"] = False
            task_info["widgets"]["status_label"].config(text="已停止")
            task_info["widgets"]["stop_button"].config(state=tk.DISABLED)
            task_info["widgets"]["restart_button"].config(state=tk.NORMAL)

    def restart_task(self, task_id):
        with self.lock:
            task_info = self.tasks.get(task_id)
            if not task_info or not task_info["stopped"]:
                return
            downloader = task_info["downloader"]
            downloader.stop(False)
            task_info["stopped"] = False
            task_info["running"] = True
            task_info["widgets"]["status_label"].config(text="等待下载...")
            task_info["widgets"]["stop_button"].config(state=tk.NORMAL)
            task_info["widgets"]["restart_button"].config(state=tk.DISABLED)
            thread = Thread(target=self.run_downloader, args=(task_id,))
            task_info["thread"] = thread
            thread.start()

    def open_file(self, filepath):
        if os.path.exists(filepath):
            os.startfile(filepath)
        else:
            messagebox.showerror("文件不存在", "文件已被删除或移动！")

    def monitor_tasks(self):
        while self.running:
            with self.lock:
                for task_id, task_info in list(self.tasks.items()):
                    if not task_info["running"]:
                        continue
                    downloader = task_info["downloader"]
                    widgets = task_info["widgets"]
                    if not downloader:
                        continue
                    downloaded, total, eta = downloader.get_pbar()
                    if downloaded == -1 or total == -1:
                        continue
                    progress = (downloaded / total) * 100 if total > 0 else 0
                    widgets["progress_bar"]["value"] = progress
                    percent_text = f"进度: {progress:.2f}%" if total > 0 else "进度: 0%"
                    widgets["percent_label"].config(text=percent_text)
                    if eta >= 0:
                        hours = eta // 3600
                        minutes = (eta % 3600) // 60
                        seconds = eta % 60
                        widgets["eta_label"].config(text=f"ETA: {hours:02}:{minutes:02}:{seconds:02}")
                    else:
                        widgets["eta_label"].config(text="ETA: --:--:--")
            time.sleep(0.1)

    def on_close(self):
        if messagebox.askokcancel("退出", "确定要退出吗？"):
            self.stop()

    def stop(self):
        self.running = False
        with self.lock:
            for task_info in self.tasks.values():
                if task_info["running"]:
                    task_info["running"] = False
                    if task_info["downloader"]:
                        task_info["downloader"].stop(True)
                    if task_info["thread"]:
                        task_info["thread"].join(timeout=2)
        self.save_tasks_to_archive()
        if self.monitor_thread.is_alive():
            self.monitor_thread.join(timeout=2)
        self.root.destroy()

    def save_tasks_to_archive(self):
        archive_data = []
        with self.lock:
            for task_id, task_info in self.tasks.items():
                if not task_info["downloader"].is_completed():
                    archive_data.append({
                        "task_id": task_id,
                        "url": task_info["url"],
                        "filename": task_info["filename"],
                        "download_dir": task_info["download_dir"],
                        "process_count": self.default_process_count,
                        "chunk_size": self.default_chunk_size,
                        "proxy_mode": self.default_proxy_mode,
                        "proxies": self.default_proxies,
                        "stopped": task_info["stopped"],
                    })
        with open(self.archive_file, "w") as f:
            json.dump(archive_data, f)

    def load_tasks_from_archive(self):
        if not os.path.exists(self.archive_file):
            return
        try:
            with open(self.archive_file, "r") as f:
                archive_data = json.load(f)
            for task_data in archive_data:
                task_id = task_data["task_id"]
                url = task_data["url"]
                filename = task_data["filename"]
                download_dir = task_data["download_dir"]
                process_count = task_data["process_count"]
                chunk_size = task_data["chunk_size"]
                proxy_mode = task_data["proxy_mode"]
                proxies = task_data["proxies"]
                stopped = task_data.get("stopped", False)
                downloader = Downloader(
                    url=url,
                    download_dir=download_dir,
                    chunk_size_mb=chunk_size // (1024 * 1024),
                    max_workers=process_count,
                    proxy_mode=proxy_mode,
                    proxies=proxies if proxy_mode == "manual" else None
                )
                task_widgets = self.create_task_widgets(task_id, filename, url)
                self.tasks[task_id] = {
                    "url": url,
                    "filename": filename,
                    "download_dir": download_dir,
                    "widgets": task_widgets,
                    "downloader": downloader,
                    "thread": None,
                    "running": not stopped,
                    "stopped": stopped,
                }
                if not stopped:
                    thread = Thread(target=self.run_downloader, args=(task_id,))
                    self.tasks[task_id]["thread"] = thread
                    thread.start()
                else:
                    widgets = task_widgets
                    widgets["status_label"].config(text="已停止")
                    widgets["stop_button"].config(state=tk.DISABLED)
                    widgets["restart_button"].config(state=tk.NORMAL)
        except Exception as e:
            messagebox.showerror("加载存档失败", f"无法加载存档：{str(e)}")


if __name__ == "__main__":
    root = tk.Tk()
    app = DownloaderGUI(root)
    root.mainloop()
