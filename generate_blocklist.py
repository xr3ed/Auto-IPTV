import os
import json
import sys
if hasattr(sys.stdout, "reconfigure"):
    sys.stdout.reconfigure(encoding="utf-8")
from concurrent.futures import ThreadPoolExecutor, as_completed
from utils import is_stream_playable

# Fallback parsing function
def extract_streams_from_content(content, source_name):
    streams = []
    lines = content.splitlines()
    current_extinf = ""
    current_opts = []
    for line in lines:
        line = line.strip()
        if not line:
            continue
        if line.startswith("#EXTM3U"):
            continue
        if line.startswith("#EXTINF:"):
            current_extinf = line
            current_opts = []
        elif line.startswith("#"):
            current_opts.append(line)
        else:
            if current_extinf:
                streams.append({
                    "extinf": current_extinf,
                    "opts": current_opts,
                    "url": line,
                    "source": source_name
                })
                current_extinf = ""
                current_opts = []
    return streams

def generate_blocklist():
    print("🔍 Memulai pemindaian Geo-block lokal...")
    
    indihome_path = "IndihomeTV.m3u"
    if not os.path.exists(indihome_path):
        print(f"❌ Berkas {indihome_path} tidak ditemukan! Silakan jalankan merge_playlists.py terlebih dahulu.")
        sys.exit(1)
        
    with open(indihome_path, 'r', encoding='utf-8') as f:
        content = f.read()
        
    channels = extract_streams_from_content(content, "IndihomeTV")
    print(f"📖 Memuat {len(channels)} saluran dari {indihome_path} untuk diuji...")
    
    # Kumpulkan URL unik
    unique_urls = list(set(ch["url"] for ch in channels))
    print(f"⚡ Menguji {len(unique_urls)} URL unik secara paralel...")
    
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    geoblocked_urls = []
    
    def test_url(url):
        is_ok = is_stream_playable(url, headers)
        return url, is_ok

    with ThreadPoolExecutor(max_workers=35) as executor:
        futures = {executor.submit(test_url, url): url for url in unique_urls}
        completed = 0
        for future in as_completed(futures):
            url = futures[future]
            try:
                url, is_ok = future.result()
                if not is_ok:
                    geoblocked_urls.append(url)
            except Exception:
                geoblocked_urls.append(url)
            completed += 1
            if completed % 50 == 0:
                print(f"   -> Selesai menguji {completed}/{len(unique_urls)} URL...")

    print(f"\n✅ Pengujian selesai!")
    print(f"   Terdeteksi {len(geoblocked_urls)} URL yang diblokir/mati secara lokal di Indonesia.")
    
    # Simpan hasil ke playlists/geoblock_list.json
    output_dir = "playlists"
    os.makedirs(output_dir, exist_ok=True)
    output_path = os.path.join(output_dir, "geoblock_list.json")
    
    with open(output_path, 'w', encoding='utf-8') as f:
        json.dump(geoblocked_urls, f, indent=2, ensure_ascii=False)
        
    print(f"💾 Database blocklist disimpan di {output_path}")

if __name__ == "__main__":
    generate_blocklist()
