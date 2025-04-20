import os
import sys
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlparse
from tqdm import tqdm
import urllib3

class Downloader:
    def __init__(self, download_dir=".", chunk_size_mb=20, max_workers=None, proxy_mode="system", proxies=None):
        self.download_dir = download_dir
        self.chunk_size_mb = chunk_size_mb
        self.max_workers = max_workers or (os.cpu_count() * 2)
        self.proxy_mode = proxy_mode
        self.proxies = proxies if proxy_mode == "manual" else self._detect_proxy()

    def _detect_proxy(self):
        proxies = {}
        if sys.platform == "win32":
            try:
                import winreg
                reg_key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, r"Software\Microsoft\Windows\CurrentVersion\Internet Settings")
                proxy_enable = winreg.QueryValueEx(reg_key, "ProxyEnable")[0]
                if proxy_enable:
                    proxy_server = winreg.QueryValueEx(reg_key, "ProxyServer")[0]
                    proxies["http"] = f"http://{proxy_server}"
                    proxies["https"] = f"http://{proxy_server}"
            except FileNotFoundError:
                pass
        http_proxy = os.getenv("HTTP_PROXY") or os.getenv("http_proxy")
        https_proxy = os.getenv("HTTPS_PROXY") or os.getenv("https_proxy")
        if http_proxy:
            proxies["http"] = http_proxy
        if https_proxy:
            proxies["https"] = https_proxy
        return proxies if proxies else None

    def parse_filename_from_headers(self, headers, url):
        content_disposition = headers.get("Content-Disposition", "")
        if 'filename=' in content_disposition:
            if "filename*" in content_disposition:
                _, encoded_name = content_disposition.split("filename*=", 1)
                _, _, value = encoded_name.partition("'")
                return unquote(value)
            elif "filename=" in content_disposition:
                file_name = content_disposition.split("filename=")[1].strip('"')
                return unquote(file_name)
        parsed_url = urlparse(url)
        file_name = os.path.basename(parsed_url.path)
        return unquote(file_name)

    def load_config(self, temp_folder, file_name):
        state_file = os.path.join(temp_folder, f"{file_name}.state")
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
        return None

    def save_config(self, temp_folder, file_name, url):
        state_file = os.path.join(temp_folder, f"{file_name}.state")
        config = {
            "url": url,
            "chunk_size_bytes": self.chunk_size_mb * 1024 * 1024,
            "max_workers": self.max_workers
        }
        with open(state_file, 'w') as f:
            json.dump(config, f)

    def calculate_downloaded_size(self, chunk_files):
        return sum(os.path.getsize(chunk_file) for chunk_file in chunk_files if os.path.exists(chunk_file))

    def download_chunk(self, session, url, chunk_index, chunk_file_path, start_byte, end_byte, overall_pbar, retries=3):
        downloaded_size = os.path.getsize(chunk_file_path) if os.path.exists(chunk_file_path) else 0
        remaining_bytes = end_byte - (start_byte + downloaded_size) + 1
        if remaining_bytes <= 0:
            overall_pbar.update(remaining_bytes)
            return
        headers = {"Range": f"bytes={start_byte + downloaded_size}-{end_byte}"}
        while retries > 0:
            try:
                response = session.get(url, headers=headers, stream=True, proxies=self.proxies, timeout=60, verify=False)
                response.raise_for_status()
                with open(chunk_file_path, "ab") as f:
                    for chunk in response.iter_content(chunk_size=65536):
                        if chunk:
                            written_bytes = len(chunk)
                            f.write(chunk[:remaining_bytes])
                            overall_pbar.update(len(chunk))
                            remaining_bytes -= len(chunk)
                            if remaining_bytes <= 0:
                                break
                return
            except requests.RequestException:
                retries -= 1

    def merge_chunks(self, chunk_files, final_file_path):
        with open(final_file_path, "wb") as final_file:
            for chunk_file in chunk_files:
                with open(chunk_file, "rb") as part_file:
                    final_file.write(part_file.read())
                os.remove(chunk_file)

    def download(self, url):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        response = session.head(url, allow_redirects=True, proxies=self.proxies)
        response.raise_for_status()
        file_name = self.parse_filename_from_headers(response.headers, url)
        file_size = int(response.headers.get("Content-Length", 0))
        temp_folder = os.path.join(self.download_dir, os.path.splitext(file_name)[0])
        os.makedirs(temp_folder, exist_ok=True)
        final_file_path = os.path.join(self.download_dir, file_name)
        config = self.load_config(temp_folder, file_name)
        if config:
            self.chunk_size_mb = config["chunk_size_bytes"] // (1024 * 1024)
            self.max_workers = config["max_workers"]
        else:
            self.save_config(temp_folder, file_name, url)
        chunk_size_bytes = self.chunk_size_mb * 1024 * 1024
        total_chunks = (file_size + chunk_size_bytes - 1) // chunk_size_bytes
        chunk_files = [os.path.join(temp_folder, f"{file_name}.part{i}") for i in range(total_chunks)]
        downloaded_size = self.calculate_downloaded_size(chunk_files)
        with tqdm(total=file_size, unit="B", unit_scale=True, desc="Overall Progress", position=0, initial=downloaded_size) as overall_pbar:
            futures = []
            with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
                for i in range(total_chunks):
                    start_byte = i * chunk_size_bytes
                    end_byte = min(start_byte + chunk_size_bytes - 1, file_size - 1)
                    chunk_file_path = chunk_files[i]
                    futures.append(executor.submit(self.download_chunk, session, url, i, chunk_file_path, start_byte, end_byte, overall_pbar))
                for future in as_completed(futures):
                    future.result()
        self.merge_chunks(chunk_files, final_file_path)
        if os.path.exists(temp_folder):
            for root, dirs, files in os.walk(temp_folder, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(temp_folder)

def download_file(url, download_dir=".", chunk_size_mb=20, max_workers=None, proxy_mode="system", proxies=None):
    downloader = Downloader(download_dir, chunk_size_mb, max_workers, proxy_mode, proxies)
    downloader.download(url)
