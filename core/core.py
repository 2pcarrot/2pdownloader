import os
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlparse
from tqdm import tqdm
import urllib3

class Downloader:
    def __init__(self, download_dir=".", chunk_size_mb=20, max_workers=None, proxy_mode="system", proxies=None, progress_callback=None):
        self.download_dir = download_dir
        self.chunk_size_mb = chunk_size_mb
        self.max_workers = max_workers or (os.cpu_count() * 2)
        self.proxy_mode = proxy_mode
        self.proxies = proxies if proxy_mode == "manual" else self._detect_proxy()
        self.progress_callback = progress_callback

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

    def check_http_range_support(self, url):
        try:
            headers = {"Range": "bytes=0-1"}
            response = requests.get(url, headers=headers, stream=True, proxies=self.proxies, timeout=10)
            return response.status_code == 206
        except Exception as e:
            print(f"Error checking HTTP Range support: {e}")
            return False

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

        supports_range = self.check_http_range_support(url)
        if not supports_range:
            print("Server does not support HTTP Range. Falling back to normal download.")
            self._download_normal(url, final_file_path, file_size)
        else:
            print("Server supports HTTP Range. Proceeding with range-based download.")
            self._download_with_range(url, final_file_path, file_size, temp_folder)

    def _download_with_range(self, url, final_file_path, file_size, temp_folder):
        chunk_size_bytes = self.chunk_size_mb * 1024 * 1024
        total_chunks = (file_size + chunk_size_bytes - 1) // chunk_size_bytes
        chunk_files = [os.path.join(temp_folder, f"{os.path.basename(final_file_path)}.part{i}") for i in range(total_chunks)]

        overall_pbar = tqdm(total=file_size, unit="B", unit_scale=True, desc="Overall Progress")

        futures = []
        with ThreadPoolExecutor(max_workers=self.max_workers) as executor:
            for i in range(total_chunks):
                start_byte = i * chunk_size_bytes
                end_byte = min(start_byte + chunk_size_bytes - 1, file_size - 1)
                chunk_file_path = chunk_files[i]

                if os.path.exists(chunk_file_path):
                    downloaded_size = os.path.getsize(chunk_file_path)
                    overall_pbar.update(downloaded_size)
                else:
                    downloaded_size = 0

                futures.append(executor.submit(self.download_chunk, url, chunk_file_path, start_byte, end_byte, overall_pbar))

            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Chunk download failed: {e}. Retrying...")
                    chunk_index = futures.index(future)
                    start_byte = chunk_index * chunk_size_bytes
                    end_byte = min(start_byte + chunk_size_bytes - 1, file_size - 1)
                    chunk_file_path = chunk_files[chunk_index]
                    futures.append(executor.submit(self.download_chunk, url, chunk_file_path, start_byte, end_byte, overall_pbar))

        overall_pbar.close()
        self.merge_chunks(chunk_files, final_file_path)

    def _download_normal(self, url, final_file_path, file_size):
        retries = 3
        while retries > 0:
            try:
                response = requests.get(url, stream=True, proxies=self.proxies, timeout=60)
                response.raise_for_status()

                with open(final_file_path, "wb") as f, tqdm(total=file_size, unit="B", unit_scale=True, desc="Overall Progress") as pbar:
                    for data in response.iter_content(chunk_size=8192):
                        f.write(data)
                        pbar.update(len(data))
                return
            except requests.RequestException as e:
                retries -= 1
                print(f"Download failed: {e}. Retries left: {retries}")
                if retries == 0:
                    raise

    def download_chunk(self, url, chunk_file_path, start_byte, end_byte, overall_pbar):
        downloaded_size = os.path.getsize(chunk_file_path) if os.path.exists(chunk_file_path) else 0
        remaining_bytes = end_byte - (start_byte + downloaded_size) + 1
        if remaining_bytes <= 0:
            overall_pbar.update(remaining_bytes)
            return

        headers = {"Range": f"bytes={start_byte + downloaded_size}-{end_byte}"}
        retries = 3
        while retries > 0:
            try:
                response = requests.get(url, headers=headers, stream=True, proxies=self.proxies, timeout=60)
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
            except requests.RequestException as e:
                retries -= 1
                if retries == 0:
                    raise Exception(f"Failed to download chunk after multiple attempts: {e}")

    def merge_chunks(self, chunk_files, final_file_path):
        try:
            with open(final_file_path, "wb") as final_file:
                for chunk_file in chunk_files:
                    with open(chunk_file, "rb") as part_file:
                        final_file.write(part_file.read())
                    os.remove(chunk_file)

            temp_folder = os.path.dirname(chunk_files[0])

            if not os.listdir(temp_folder):
                os.rmdir(temp_folder)
                print(f"Temporary folder '{temp_folder}' has been deleted.")
            else:
                print(f"Temporary folder '{temp_folder}' is not empty and cannot be deleted.")
        except Exception as e:
            print(f"Error while merging chunks or deleting temporary folder: {e}")


def download_file(url, download_dir=".", chunk_size_mb=20, max_workers=32, proxy_mode="system", proxies=None, progress_callback=None):
    downloader = Downloader(download_dir, chunk_size_mb, max_workers, proxy_mode, proxies, progress_callback)
    downloader.download(url)
