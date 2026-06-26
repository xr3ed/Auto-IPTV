import os
import gzip
import json
import logging
import random
import re
import time
import requests
from io import BytesIO

# --- Configuration ---
USER_AGENT = 'Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0.0.0 Safari/537.36'
REQUEST_TIMEOUT = 30

def setup_logger(name):
    logging.basicConfig(level=logging.INFO, format='%(asctime)s - %(levelname)s - %(message)s')
    return logging.getLogger(name)

logger = setup_logger("utils")

def fetch_url(url, is_json=True, is_gzipped=False, headers=None, stream=False, retries=3, verify=True):
    headers = headers or {'User-Agent': USER_AGENT}
    for i in range(retries):
        try:
            response = requests.get(url, headers=headers, timeout=REQUEST_TIMEOUT, stream=stream, verify=verify)
            if response.status_code == 429:
                time.sleep((i + 1) * 10 + random.uniform(0, 5))
                continue
            response.raise_for_status()
            content = response.content
            if is_gzipped:
                try:
                    with gzip.GzipFile(fileobj=BytesIO(content), mode='rb') as f:
                        content = f.read()
                    content = content.decode('utf-8')
                except:
                    content = content.decode('utf-8')
            else:
                content = content.decode('utf-8')
            return json.loads(content) if is_json else content
        except Exception as e:
            logger.warning(f"Fetch failed for {url} (attempt {i+1}): {e}")
            if i < retries - 1: time.sleep(5)
    return None

def write_m3u_file(filename, content, output_dir="playlists"):
    os.makedirs(output_dir, exist_ok=True)
    filepath = os.path.join(output_dir, filename)
    with open(filepath, 'w', encoding='utf-8') as f:
        f.write(content)

def format_extinf(channel_id, tvg_id, tvg_chno, tvg_name, tvg_logo, group_title, display_name):
    chno_str = str(tvg_chno) if tvg_chno and str(tvg_chno).isdigit() else ""
    return (f'#EXTINF:-1 channel-id="{channel_id}" tvg-id="{tvg_id}" tvg-chno="{chno_str}" '
            f'tvg-name="{tvg_name.replace(chr(34), chr(39))}" tvg-logo="{tvg_logo}" '
            f'group-title="{group_title.replace(chr(34), chr(39))}",{display_name.replace(",", "")}\n')

def sanitize_xml_text(text: str) -> str:
    """Membersihkan karakter kontrol ilegal di XML 1.0."""
    if not text:
        return ""
    return re.sub(r'[\x00-\x08\x0b\x0c\x0e-\x1f\x7f]', '', text)
