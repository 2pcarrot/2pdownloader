import os
import sys
import json
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib.parse import unquote, urlparse
from tqdm import tqdm
import urllib3

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
            return unquote(value)
        elif "filename=" in content_disposition:
            file_name = content_disposition.split("filename=")[1].strip('"')
            return unquote(file_name)
    parsed_url = urlparse(url)
    file_name = os.path.basename(parsed_url.path)
    return unquote(file_name)

def load_config(temp_folder, file_name):
    state_file = os.path.join(temp_folder, f"{file_name}.state")
    if os.path.exists(state_file):
        with open(state_file, 'r') as f:
            return json.load(f)
    return None

def save_config(temp_folder, file_name, chunk_size_bytes, max_workers):
    state_file = os.path.join(temp_folder, f"{file_name}.state")
    config = {
        "chunk_size_bytes": chunk_size_bytes,
        "max_workers": max_workers
    }
    with open(state_file, 'w') as f:
        json.dump(config, f)

def calculate_downloaded_size(chunk_files):
    downloaded_size = 0
    for chunk_file in chunk_files:
        if os.path.exists(chunk_file):
            downloaded_size += os.path.getsize(chunk_file)
    return downloaded_size

def download_chunk(session, url, chunk_index, chunk_file_path, start_byte, end_byte, overall_pbar, proxies=None):
    downloaded_size = os.path.getsize(chunk_file_path) if os.path.exists(chunk_file_path) else 0
    remaining_bytes = end_byte - (start_byte + downloaded_size) + 1
    
    if remaining_bytes <= 0:
        overall_pbar.update(remaining_bytes)
        return

    headers = {"Range": f"bytes={start_byte + downloaded_size}-{end_byte}"}
    response = session.get(url, headers=headers, stream=True, proxies=proxies, timeout=60, verify=False)
    response.raise_for_status()

    with open(chunk_file_path, "ab") as f:
        for chunk in response.iter_content(chunk_size=65536):
            if chunk:
                written_bytes = len(chunk)
                if written_bytes > remaining_bytes:
                    chunk = chunk[:remaining_bytes]
                f.write(chunk)
                overall_pbar.update(len(chunk))
                remaining_bytes -= len(chunk)
                if remaining_bytes <= 0:
                    break

def merge_chunks(chunk_files, final_file_path):
    print("\nMerging chunks...")
    with open(final_file_path, "wb") as final_file:
        for chunk_file in chunk_files:
            with open(chunk_file, "rb") as part_file:
                final_file.write(part_file.read())
            os.remove(chunk_file)
    print(f"Merged all chunks into {final_file_path}")

def download_file(url, dest_folder=".", chunk_size_mb=20, max_workers=20, proxies=None):
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    session = requests.Session()
    response = session.head(url, allow_redirects=True, proxies=proxies)
    file_name = parse_filename_from_headers(response.headers, url)
    file_size = int(response.headers.get("Content-Length", 0))
    
    print(f"File size: {file_size} bytes")

    temp_folder = os.path.join(dest_folder, os.path.splitext(file_name)[0])
    os.makedirs(temp_folder, exist_ok=True)
    final_file_path = os.path.join(dest_folder, file_name)

    config = load_config(temp_folder, file_name)
    if config:
        saved_chunk_size_bytes = config["chunk_size_bytes"]
        saved_max_workers = config["max_workers"]
        if saved_chunk_size_bytes != chunk_size_mb * 1024 * 1024 or saved_max_workers != max_workers:
            raise ValueError("Configuration mismatch. Please use the same chunk size and max workers.")
        chunk_size_bytes = saved_chunk_size_bytes
        max_workers = saved_max_workers
        print(f"Loaded configuration from state file: chunk_size_bytes={chunk_size_bytes}, max_workers={max_workers}")
    else:
        chunk_size_bytes = chunk_size_mb * 1024 * 1024
        save_config(temp_folder, file_name, chunk_size_bytes, max_workers)

    total_chunks = (file_size + chunk_size_bytes - 1) // chunk_size_bytes

    chunk_files = [os.path.join(temp_folder, f"{file_name}.part{i}") for i in range(total_chunks)]
    downloaded_size = calculate_downloaded_size(chunk_files)

    with tqdm(total=file_size, unit="B", unit_scale=True, desc="Overall Progress", position=0, initial=downloaded_size) as overall_pbar:
        futures = []
        with ThreadPoolExecutor(max_workers=max_workers) as executor:
            for i in range(total_chunks):
                start_byte = i * chunk_size_bytes
                end_byte = min(start_byte + chunk_size_bytes - 1, file_size - 1)
                chunk_file_path = chunk_files[i]
                
                future = executor.submit(download_chunk, session, url, i, chunk_file_path, start_byte, end_byte, overall_pbar, proxies)
                futures.append(future)
            
            for future in as_completed(futures):
                try:
                    future.result()
                except Exception as e:
                    print(f"Failed to download chunk after retries: {e}")

    merge_chunks(chunk_files, final_file_path)
    
    if os.path.exists(temp_folder):
        for root, dirs, files in os.walk(temp_folder, topdown=False):
            for name in files:
                os.remove(os.path.join(root, name))
            for name in dirs:
                os.rmdir(os.path.join(root, name))
        os.rmdir(temp_folder)
        print(f"Temporary folder '{temp_folder}' deleted.")

