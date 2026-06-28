import os
import re
import requests
import gzip
from pathlib import Path
from dotenv import load_dotenv

load_dotenv()

def to_raw_github_url(url):
    if "github.com" in url and "/blob/" in url:
        url = url.replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
    return url

URL_GCIKAR = os.environ.get("GCIKAR_URL", "")
ADDITIONAL_URLS_RAW = os.environ.get("ADDITIONAL_M3U_URLS", "")
ADDITIONAL_URLS = []
if ADDITIONAL_URLS_RAW:
    ADDITIONAL_URLS = [
        to_raw_github_url(url.strip())
        for url in ADDITIONAL_URLS_RAW.split(",")
        if url.strip()
    ]
else:
    ADDITIONAL_URLS = [
        to_raw_github_url("https://github.com/apistech/project/blob/main/playlists/wc2026.m3u"),
        to_raw_github_url("https://github.com/apistech/project/blob/main/playlists/live_events.m3u"),
        to_raw_github_url("https://raw.githubusercontent.com/dhasap/dhanytv/main/dhanytv.m3u")
    ]
OUTPUT_DIR = Path("playlists")
M3U_PATH = OUTPUT_DIR / "live_events.m3u"
M3U_GZ_PATH = OUTPUT_DIR / "live_events.m3u.gz"

# Logo default FIFA World Cup 2026 seragam
DEFAULT_LOGO = "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/fifa.png"

def parse_and_filter_worldcup(raw_m3u_list, blocklist=None):
    wc_keywords = ["world cup", "worldcup", "piala dunia", "fifa"]
    
    entries = []
    seen_urls = set()
    
    for raw_m3u in raw_m3u_list:
        lines = raw_m3u.splitlines()
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
                    
                    # Deduplikasi berdasarkan URL stream
                    if line not in seen_urls:
                        # Cek filter World Cup
                        if any(kw in channel_name.lower() for kw in wc_keywords):
                            seen_urls.add(line)
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
        
        # Cari kata kunci di nama asal atau URL
        combined_text = (name_lower + " " + url_lower)
        if "caze" in combined_text:
            source_channel = "Caze TV"
        elif "tsports" in combined_text or "t sports" in combined_text:
            source_channel = "T Sports"
        elif "cctv" in combined_text:
            match_cctv = re.search(r'cctv\s*\d+\+?', combined_text)
            source_channel = match_cctv.group(0).upper() if match_cctv else "CCTV"
        elif "tv-berati" in combined_text or "berati" in combined_text:
            source_channel = "TV Berati"
        elif "arabic" in combined_text:
            source_channel = "Arabic Feed"
        elif "english" in combined_text:
            source_channel = "English Feed"
        # Tambahan deteksi channel lain dari URL
        elif "f2k3.shop" in combined_text:
            source_channel = "Khandaia Feed"
        elif "meung.app" in combined_text:
            source_channel = "Meung TV"
        elif "100ycdn.com" in combined_text or "cdnfaster" in combined_text:
            source_channel = "CDN Feed"
        elif "myxpanel.pro" in combined_text:
            match_wc_num = re.search(r'world\s*cup\s*\d{4}\s*(\d+)', name_lower)
            if match_wc_num:
                source_channel = f"WC Feed {match_wc_num.group(1)}"
            else:
                source_channel = "Panel Feed"
        # Jika tidak cocok dengan penentu di atas, coba bersihkan name bawaan
        else:
            tvg_name_match = re.search(r'tvg-name="([^"]+)"', entry["extinf"])
            if tvg_name_match:
                tvg_val = tvg_name_match.group(1)
                tvg_clean = re.sub(r'\[[^\]]+\]', '', tvg_val).strip()
                tvg_clean = re.sub(r'(fifa|world\s*cup|2026|hd|fhd|sd|feed|cadangan|live|event)', '', tvg_clean, flags=re.IGNORECASE).strip()
                if tvg_clean and len(tvg_clean) > 2:
                    source_channel = tvg_clean
            
            if source_channel == "Feed":
                name_clean = re.sub(r'\[[^\]]+\]', '', name).strip()
                name_clean = re.sub(r'(fifa|world\s*cup|2026|hd|fhd|sd|feed|cadangan|live|event|gvision\s*tv|gvision)', '', name_clean, flags=re.IGNORECASE).strip()
                name_clean = re.sub(r'\s+\d+$', '', name_clean).strip()
                if name_clean and len(name_clean) > 2:
                    source_channel = name_clean
                    
        # --- PERBAIKAN: JIKA NAMA CHANNEL MASIH MENGANDUNG NAMA TIM BERTANDING, KITA HAPUS ---
        # Bersihkan kata penanda laga seperti "vs", "v", "tường thuật" dari nama channel
        # Hal ini mencegah timbulnya nama duel panjang (misal: "Tường thuật:  - Panama vs England  Flv") di nama channel.
        source_channel_lower = source_channel.lower()
        if "vs" in source_channel_lower or " v " in source_channel_lower or "tường thuật" in source_channel_lower or "versus" in source_channel_lower:
            # Jika merupakan duel tim, potong atau ubah menjadi label default "Feed"
            source_channel = "Feed"
            
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
        url = entry["url"]
        
        # Berikan nomor urut dinamis per grup
        key_group = f"{q}_{l}_{src}"
        feed_counters[key_group] = feed_counters.get(key_group, 0) + 1
        num_suffix = feed_counters[key_group]
        

        # Format Baru: [resolusi] World Cup - [Nama Channel] [Nomor]
        q_lower = q.lower()
        standardized_name = f"[{q_lower}] World Cup - {src} {num_suffix}"
        
        # Cek jika URL terdaftar di blocklist
        is_blocked = blocklist and url in blocklist
        if is_blocked:
            standardized_name += " [Mungkin Bermasalah]"
            
        extinf_raw = entry["extinf_base"]
        
        # Logo warning kustom jika bermasalah, atau logo default
        logo_url = "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/warning_wc.png" if is_blocked else DEFAULT_LOGO
        
        # Ganti logo dengan logo seragam FIFA / Warning
        if 'tvg-logo="' in extinf_raw:
            extinf_raw = re.sub(r'tvg-logo="[^"]+"', f'tvg-logo="{logo_url}"', extinf_raw)
        else:
            extinf_raw = extinf_raw.replace(",", f' tvg-logo="{logo_url}",', 1)
            
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
    if not URL_GCIKAR:
        print("Error: GCIKAR_URL tidak didefinisikan di environment variables (.env / GitHub secrets).")
        exit(1)
    print(f"Mengunduh playlist dari {URL_GCIKAR}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(URL_GCIKAR, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        raw_content = response.text
        
        # Muat blocklist jika ada
        blocklist = []
        blocklist_path = Path("playlists/blocklist.json")
        if blocklist_path.exists():
            try:
                import json
                with open(blocklist_path, "r", encoding="utf-8") as f:
                    blocklist_data = json.load(f)
                    blocklist = list(blocklist_data.keys())
                print(f"Memuat {len(blocklist)} URL ke dalam blocklist.")
            except Exception as e:
                print(f"Gagal memuat blocklist: {e}")
                
        # Unduh playlist tambahan
        raw_contents = [raw_content]
        for idx, url in enumerate(ADDITIONAL_URLS):
            try:
                print(f"Mengunduh playlist tambahan {idx+1}: {url}...")
                resp = requests.get(url, headers=headers, timeout=30, verify=False)
                resp.raise_for_status()
                raw_contents.append(resp.text)
            except Exception as e:
                print(f"Gagal mengunduh playlist tambahan {url}: {e}")
                
        print("Menyaring, menstandarkan nama/logo, serta mengurutkan saluran...")
        filtered_content = parse_and_filter_worldcup(raw_contents, blocklist)
        
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