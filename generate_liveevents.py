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
        # Cek resolusi baik dari string nama maupun dari URL
        quality = "SD"
        url_lower = entry["url"].lower()
        
        # Cari resolusi (fhd, 1080p, hd, 720p, sd, lhd, lsd, mono, uhd)
        if any(q in name_lower or q in url_lower for q in ["fhd", "1080p", "uhd"]):
            quality = "FHD"
        elif any(q in name_lower or q in url_lower for q in ["hd", "720p", "lhd"]):
            quality = "HD"
        elif any(q in name_lower or q in url_lower for q in ["sd", "lsd", "mono"]):
            quality = "SD"
            
        # 3. Ekstrak nama laga untuk diidentifikasi pemicu live match
        is_live_match = 0
        if re.search(r'\d{2}:\d{2}\s*WIB', name, re.IGNORECASE):
            is_live_match = 2
        elif "feed" in name_lower or "cadangan" in name_lower:
            is_live_match = 1
            
        # 4. Deteksi Sumber Asli (Nama Channel Asal, misal: Caze TV, T Sports, CCTV 5, dll)
        # Menghapus tag bracket dan keterangan resolusi/laga untuk mencari nama stasiun TV
        source_channel = "Feed"
        
        # Pola umum mendeteksi nama channel
        if "caze" in name_lower:
            source_channel = "Caze TV"
        elif "tsports" in name_lower or "t sports" in name_lower:
            source_channel = "T Sports"
        elif "cctv" in name_lower:
            # Cari apakah cctv 5 atau cctv 5+
            match_cctv = re.search(r'cctv\s*\d+\+?', name_lower)
            source_channel = match_cctv.group(0).upper() if match_cctv else "CCTV"
        elif "tv-berati" in name_lower or "berati" in name_lower:
            source_channel = "TV Berati"
        elif "arabic" in name_lower:
            source_channel = "Arabic Feed"
        elif "english" in name_lower:
            source_channel = "English Feed"
            
        processed_entries.append({
            "extinf_base": entry["extinf"],
            "options": entry["options"],
            "url": entry["url"],
            "is_live": is_live_match,
            "quality": quality,
            "lang": lang,
            "source_channel": source_channel,
            "quality_score": {"FHD": 3, "HD": 2, "SD": 1}.get(quality, 0),
            "lang_score": {"Inggris": 3, "Indonesia": 2, "Lainnya": 1}.get(lang, 0)
        })
        
    # Urutkan berdasarkan:
    # 1. Kualitas Resolusi (quality_score DESC) -> FHD lalu HD lalu SD
    # 2. Prioritas Bahasa Inggris Utama (lang_score DESC) -> Inggris lalu Indonesia lalu Lainnya
    # 3. Live Match Terjadwal Utama (is_live DESC)
    processed_entries.sort(key=lambda x: (-x["quality_score"], -x["lang_score"], -x["is_live"]))
    
    # Counter untuk memberikan nomor unik pada kombinasi Kualitas + Bahasa + Nama Channel Asal
    feed_counters = {}
    
    # Rakit kembali menjadi format M3U
    output_lines = ["#EXTM3U\n"]
    for entry in processed_entries:
        q = entry["quality"]
        l = entry["lang"]
        src = entry["source_channel"]
        
        # Berikan nomor urut dinamis per grup
        key_group = f"{q}_{l}_{src}"
        feed_counters[key_group] = feed_counters.get(key_group, 0) + 1
        num_suffix = feed_counters[key_group]
        
        # Format Baru yang diminta: [Resolusi] World Cup - [Nama Channel] [Bahasa] [Nomor]
        # Contoh: [HD] World Cup - Caze TV Inggris 1
        # Mengubah case resolusi menjadi huruf kecil jika berada di dalam bracket (misal: [hd], [fhd], [sd])
        q_lower = q.lower()
        standardized_name = f"[{q_lower}] World Cup - {src} {l} {num_suffix}"
        
        extinf_raw = entry["extinf_base"]
        
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
        
        output_lines.append(new_extinf + "\n")
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