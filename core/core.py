import os
import sys
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlparse
from tqdm import tqdm
import urllib3


class Downloader:
    def __init__(self, url, download_dir=".", chunk_size_mb=20, max_workers=None, proxy_mode="system", proxies=None):
        self.url = url
        self.download_dir = download_dir
        self.chunk_size_mb = chunk_size_mb
        self.max_workers = max_workers or (os.cpu_count() * 2)
        self.proxy_mode = proxy_mode
        self.proxies = proxies if proxy_mode == "manual" else self._detect_proxy()
        self.stop_flag = False
        self.overall_pbar = None
        self.complete_flag = False

    def is_completed(self):
        return self.complete_flag

    def stop(self,flag):
        self.stop_flag = flag

    def get_pbar(self):
        returns = self.overall_pbar.format_dict if self.overall_pbar else None
        return (returns['n'], returns['total'], (returns['total'] - returns['n']) // int(returns['rate']) if returns['rate'] else 0) if returns else (-1, -1, -1)

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

    def parse_filename_from_headers(self, headers):
        content_disposition = headers.get("Content-Disposition", "")
        if 'filename=' in content_disposition:
            if "filename*" in content_disposition:
                _, encoded_name = content_disposition.split("filename*=", 1)
                _, _, value = encoded_name.partition("'")
                return unquote(value)
            elif "filename=" in content_disposition:
                file_name = content_disposition.split("filename=")[1].strip('"')
                return unquote(file_name)
        parsed_url = urlparse(self.url)
        file_name = os.path.basename(parsed_url.path)
        return unquote(file_name)

    def load_config(self, temp_folder, file_name):
        state_file = os.path.join(temp_folder, f"{file_name}.state")
        if os.path.exists(state_file):
            with open(state_file, 'r') as f:
                return json.load(f)
        return None

    def save_config(self, temp_folder, file_name):
        state_file = os.path.join(temp_folder, f"{file_name}.state")
        config = {
            "url": self.url,
            "chunk_size_bytes": self.chunk_size_mb * 1024 * 1024,
            "max_workers": self.max_workers
        }
        with open(state_file, 'w') as f:
            json.dump(config, f)

    def calculate_downloaded_size(self, chunk_files):
        return sum(os.path.getsize(chunk_file) for chunk_file in chunk_files if os.path.exists(chunk_file))

    def download_chunk(self, session, chunk_index, chunk_file_path, start_byte, end_byte, retries=3):
        downloaded_size = os.path.getsize(chunk_file_path) if os.path.exists(chunk_file_path) else 0
        remaining_bytes = end_byte - (start_byte + downloaded_size) + 1
        if remaining_bytes <= 0:
            self.overall_pbar.update(remaining_bytes)
            return
        headers = {"Range": f"bytes={start_byte + downloaded_size}-{end_byte}"}
        while retries > 0:
            if self.stop_flag:
                print(f"Stopping chunk {chunk_index}...")
                return
            try:
                response = session.get(self.url, headers=headers, stream=True, proxies=self.proxies, timeout=60, verify=False)  # 使用 self.url
                response.raise_for_status()
                with open(chunk_file_path, "ab") as f:
                    for chunk in response.iter_content(chunk_size=65536):
                        if self.stop_flag:
                            print(f"Stopping chunk {chunk_index} during download...")
                            return
                        if chunk:
                            written_bytes = len(chunk)
                            f.write(chunk[:remaining_bytes])
                            self.overall_pbar.update(len(chunk))
                            remaining_bytes -= len(chunk)
                            if remaining_bytes <= 0:
                                break
                return
            except requests.RequestException:
                retries -= 1

    def merge_chunks(self, chunk_files, final_file_path):
        with open(final_file_path, "wb") as final_file:
            for chunk_file in chunk_files:
                if self.stop_flag:
                    print("Stopping during merge...")
                    return
                with open(chunk_file, "rb") as part_file:
                    final_file.write(part_file.read())
                os.remove(chunk_file)

    def download(self):
        urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
        session = requests.Session()
        response = session.head(self.url, allow_redirects=True, proxies=self.proxies)
        response.raise_for_status()
        file_name = self.parse_filename_from_headers(response.headers)
        file_size = int(response.headers.get("Content-Length", 0))
        temp_folder = os.path.join(self.download_dir, os.path.splitext(file_name)[0])
        os.makedirs(temp_folder, exist_ok=True)
        final_file_path = os.path.join(self.download_dir, file_name)
        config = self.load_config(temp_folder, file_name)
        if config:
            self.chunk_size_mb = config["chunk_size_bytes"] // (1024 * 1024)
            self.max_workers = config["max_workers"]
        else:
            self.save_config(temp_folder, file_name)

        chunk_size_bytes = self.chunk_size_mb * 1024 * 1024

        if (chunk_size_bytes * self.max_workers) >= file_size:
            total_chunks = self.max_workers
            chunk_size_bytes = file_size // total_chunks
            remainder = file_size % total_chunks
        else:
            total_chunks = (file_size + chunk_size_bytes - 1) // chunk_size_bytes
            remainder = 0

        chunk_files = [os.path.join(temp_folder, f"{file_name}.part{i}") for i in range(total_chunks)]
        downloaded_size = self.calculate_downloaded_size(chunk_files)

        self.overall_pbar = tqdm(
            total=file_size,
            unit="B",
            unit_scale=True,
            desc="Progress",
            position=0,
            initial=downloaded_size
        )

        futures = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for i in range(total_chunks):
                if self.stop_flag:
                    print("Stopping download process...")
                    return

                start_byte = i * chunk_size_bytes
                end_byte = min(start_byte + chunk_size_bytes - 1, file_size - 1)

                if i == total_chunks - 1 and remainder > 0:
                    end_byte += remainder

                chunk_file_path = chunk_files[i]
                futures.append(executor.submit(self.download_chunk, session, i, chunk_file_path, start_byte, end_byte))

            for future in as_completed(futures):
                if self.stop_flag:
                    print("Stopping during future completion...")
                    return
                future.result()

        if not self.stop_flag:
            self.merge_chunks(chunk_files, final_file_path)

        self.overall_pbar.close()

        if os.path.exists(temp_folder):
            for root, dirs, files in os.walk(temp_folder, topdown=False):
                for name in files:
                    os.remove(os.path.join(root, name))
                for name in dirs:
                    os.rmdir(os.path.join(root, name))
            os.rmdir(temp_folder)
        self.complete_flag = True
