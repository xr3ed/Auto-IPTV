import os
import requests
import gzip
from pathlib import Path

URL_GCIKAR = "https://gcikar.bigsentinel.biz.id/cs/cs.m3u8"
OUTPUT_DIR = Path("playlists")
M3U_PATH = OUTPUT_DIR / "live_events.m3u"
M3U_GZ_PATH = OUTPUT_DIR / "live_events.m3u.gz"

def main():
    print(f"Mengunduh playlist dari {URL_GCIKAR}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(URL_GCIKAR, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        content = response.text
        
        # Pastikan output folder ada
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Tulis file M3U mentah
        with open(M3U_PATH, "w", encoding="utf-8") as f:
            f.write(content)
        print(f"File berhasil disimpan di: {M3U_PATH}")
        
        # Tulis versi terkompresi (.gz)
        with gzip.open(M3U_GZ_PATH, "wb") as f_gz:
            f_gz.write(content.encode("utf-8"))
        print(f"File terkompresi berhasil disimpan di: {M3U_GZ_PATH}")
        
    except Exception as e:
        print(f"Gagal mengambil/memproses playlist: {e}")
        exit(1)

if __name__ == "__main__":
    # Matikan warning SSL tidak aman
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()