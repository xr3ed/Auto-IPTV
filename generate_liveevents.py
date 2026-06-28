import os
import re
import requests
import gzip
from pathlib import Path

URL_GCIKAR = os.environ.get("GCIKAR_URL", "https://gcikar.bigsentinel.biz.id/cs/cs.m3u8")
OUTPUT_DIR = Path("playlists")
M3U_PATH = OUTPUT_DIR / "live_events.m3u"
M3U_GZ_PATH = OUTPUT_DIR / "live_events.m3u.gz"

# Logo default FIFA World Cup 2026 seragam
DEFAULT_LOGO = "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/fifa.png"

def parse_and_filter_worldcup(raw_m3u):
    lines = raw_m3u.splitlines()
    wc_keywords = ["world cup", "worldcup", "piala dunia", "fifa"]
    
    entries = []
    current_extinf = ""
    current_options = []
    
    for line in lines:
        line_str = line.strip()
        if not line_str:
            continue
        if line_str.startswith("#EXTM3U"):
            continue
            
        if line_str.startswith("#EXTINF:"):
            current_extinf = line_str
            current_options = []
        elif line_str.startswith("#"):
            current_options.append(line)
        else:
            if current_extinf:
                parts = current_extinf.split(",", 1)
                channel_name = parts[1].strip() if len(parts) >= 2 else ""
                
                # Cek filter World Cup
                if any(kw in channel_name.lower() for kw in wc_keywords):
                    entries.append({
                        "extinf": current_extinf,
                        "options": current_options,
                        "url": line,
                        "name": channel_name
                    })
                current_extinf = ""
                current_options = []
                
    processed_entries = []
    
    # Counter untuk memberikan nomor unik pada cadangan/feed
    feed_counters = {}
    
    for entry in entries:
        name = entry["name"]
        
        # 1. Deteksi Bahasa
        lang = "Lainnya"
        name_lower = name.lower()
        if "english" in name_lower or "eng" in name_lower:
            lang = "Inggris"
        elif "indo" in name_lower or "laga" in name_lower or "wib" in name_lower:
            lang = "Indonesia"
            
        # 2. Deteksi Resolusi / Kualitas
        quality = "SD"
        if "fhd" in name_lower or "1080p" in name_lower:
            quality = "FHD"
        elif "hd" in name_lower or "720p" in name_lower:
            quality = "HD"
            
        # 3. Ekstrak nama laga untuk diidentifikasi pemicu live match
        is_live_match = 0
        if re.search(r'\d{2}:\d{2}\s*WIB', name, re.IGNORECASE):
            is_live_match = 2
        elif "feed" in name_lower or "cadangan" in name_lower:
            is_live_match = 1
            
        # 4. Berikan nomor urut dinamis per grup Kualitas + Bahasa agar nama tetap unik
        key_group = f"{quality}_{lang}"
        feed_counters[key_group] = feed_counters.get(key_group, 0) + 1
        num_suffix = feed_counters[key_group]
        
        # 5. Penyeragaman Nama Baru Tanpa Nama Tim Yang Bertanding
        # Format Baru: [Resolusi] World Cup 2026 - [Bahasa] [Nomor]
        standardized_name = f"[{quality}] World Cup 2026 - {lang} {num_suffix}"
        
        # 6. Modifikasi EXTINF
        extinf_raw = entry["extinf"]
        
        # Ganti logo dengan logo seragam FIFA
        if 'tvg-logo="' in extinf_raw:
            extinf_raw = re.sub(r'tvg-logo="[^"]+"', f'tvg-logo="{DEFAULT_LOGO}"', extinf_raw)
        else:
            extinf_raw = extinf_raw.replace(",", f' tvg-logo="{DEFAULT_LOGO}",', 1)
            
        # Ganti group-title
        if 'group-title="' in extinf_raw:
            extinf_raw = re.sub(r'group-title="[^"]+"', 'group-title="World Cup 2026"', extinf_raw)
        else:
            extinf_raw = extinf_raw.replace(",", ' group-title="World Cup 2026",', 1)
            
        # Ganti nama di akhir EXTINF
        parts_extinf = extinf_raw.split(",", 1)
        new_extinf = f"{parts_extinf[0]},{standardized_name}"
        
        processed_entries.append({
            "extinf": new_extinf,
            "options": entry["options"],
            "url": entry["url"],
            "is_live": is_live_match,
            "quality_score": {"FHD": 3, "HD": 2, "SD": 1}.get(quality, 0),
            "lang_score": {"Inggris": 3, "Indonesia": 2, "Lainnya": 1}.get(lang, 0)
        })
        
    # Urutkan berdasarkan:
    # 1. Live Match Terjadwal Utama (is_live DESC)
    # 2. Prioritas Bahasa Inggris Utama (lang_score DESC)
    # 3. Kualitas Resolusi (quality_score DESC)
    processed_entries.sort(key=lambda x: (-x["is_live"], -x["lang_score"], -x["quality_score"]))
    
    # Rakit kembali menjadi format M3U
    output_lines = ["#EXTM3U\n"]
    for entry in processed_entries:
        output_lines.append(entry["extinf"] + "\n")
        for opt in entry["options"]:
            output_lines.append(opt + "\n")
        output_lines.append(entry["url"] + "\n")
        
    return "".join(output_lines)

def main():
    print(f"Mengunduh playlist dari {URL_GCIKAR}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(URL_GCIKAR, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        raw_content = response.text
        
        print("Menyaring, menstandarkan nama/logo, serta mengurutkan saluran...")
        filtered_content = parse_and_filter_worldcup(raw_content)
        
        # Pastikan output folder ada
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Tulis file M3U yang sudah difilter
        with open(M3U_PATH, "w", encoding="utf-8") as f:
            f.write(filtered_content)
        print(f"File berhasil disimpan di: {M3U_PATH}")
        
        # Tulis versi terkompresi (.gz)
        with gzip.open(M3U_GZ_PATH, "wb") as f_gz:
            f_gz.write(filtered_content.encode("utf-8"))
        print(f"File terkompresi berhasil disimpan di: {M3U_GZ_PATH}")
        
    except Exception as e:
        print(f"Gagal mengambil/memproses playlist: {e}")
        exit(1)

if __name__ == "__main__":
    # Matikan warning SSL tidak aman
    import urllib3
    urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)
    main()