import os
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlparse
from tqdm import tqdm
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

def detect_proxy():
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

def parse_filename_from_headers(headers, url):
    content_disposition = headers.get("Content-Disposition", "")
    if 'filename=' in content_disposition:
        if "filename*" in content_disposition:
            _, encoded_name = content_disposition.split("filename*=", 1)
            encoding, _, value = encoded_name.partition("'")
            encoding, _, value = value.partition("'")
            return unquote(value)
        elif "filename=" in content_disposition:
            file_name = content_disposition.split("filename=")[1].strip('"')
            return unquote(file_name)
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)
    return unquote(file_name)

def download_chunk(session, url, chunk_index, chunk_file_path, start_byte, end_byte, overall_pbar, proxies=None):
    headers = {"Range": f"bytes={start_byte}-{end_byte}"}
    downloaded_size = 0
    max_chunk_size = end_byte - start_byte + 1
    response = session.get(url, headers=headers, stream=True, proxies=proxies, timeout=60, verify=False)
    response.raise_for_status()
    buffer = []
    with open(chunk_file_path, "wb") as f:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                remaining_bytes = max_chunk_size - downloaded_size
                if len(chunk) > remaining_bytes:
                    chunk = chunk[:remaining_bytes]
                buffer.append(chunk)
                written_bytes = len(chunk)
                downloaded_size += written_bytes
                overall_pbar.update(written_bytes)
                if sum(len(c) for c in buffer) >= 1048576:
                    f.write(b"".join(buffer))
                    buffer.clear()
                if downloaded_size >= max_chunk_size:
                    break
        if buffer:
            f.write(b"".join(buffer))

def merge_chunks(chunk_files, final_file_path):
    print("\nMerging chunks...")
    with open(final_file_path, "wb") as final_file:
        for chunk_file in chunk_files:
            with open(chunk_file, "rb") as part_file:
                final_file.write(part_file.read())
            os.remove(chunk_file)
    print(f"Merged all chunks into {final_file_path}")

def download_file(url, dest_folder=".", chunk_size_mb=20, max_workers=20, proxies=None):
    session = requests.Session()
    response = session.head(url, allow_redirects=True, proxies=proxies)
    file_name = parse_filename_from_headers(response.headers, url)
    local_path = os.path.join(dest_folder, file_name)
    file_size = int(response.headers.get("Content-Length", 0))
    print(f"File size: {file_size} bytes")
    chunk_size_bytes = chunk_size_mb * 1024 * 1024
    total_chunks = (file_size + chunk_size_bytes - 1) // chunk_size_bytes
    with tqdm(total=file_size, unit="B", unit_scale=True, desc="Overall Progress", position=0) as overall_pbar:
        chunk_files = []
        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i in range(total_chunks):
                start_byte = i * chunk_size_bytes
                end_byte = min(start_byte + chunk_size_bytes - 1, file_size - 1)
                chunk_file_path = os.path.join(dest_folder, f"{file_name}.part{i}")
                future = executor.submit(download_chunk, session, url, i, chunk_file_path, start_byte, end_byte, overall_pbar, proxies)
                futures.append(future)
                chunk_files.append(chunk_file_path)
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Failed to download chunk after retries: {e}")
    merge_chunks(chunk_files, local_path)

def main(urls, dest_folder=".", chunk_size_mb=50, max_workers=20, proxies=None):
    #proxies = detect_proxy()
    if proxies:
        print(f"Using proxy settings: {proxies}")
    else:
        print("No proxy detected.")
    for url in urls:
        print(f"Starting download: {url}")
        try:
            download_file(url, dest_folder, chunk_size_mb=chunk_size_mb, max_workers=max_workers, proxies=proxies)
        except Exception as e:
            print(f"Failed to download {url}: {e}")
