import os
import re
import requests
import gzip
from pathlib import Path

URL_GCIKAR = "https://gcikar.bigsentinel.biz.id/cs/cs.m3u8"
OUTPUT_DIR = Path("playlists")
M3U_PATH = OUTPUT_DIR / "live_events.m3u"
M3U_GZ_PATH = OUTPUT_DIR / "live_events.m3u.gz"

def parse_and_filter_worldcup(raw_m3u):
    """
    Mem-parse berkas M3U mentah, menyaring entri selain World Cup,
    dan mengatur ulang kategori (group-title) menjadi 'World Cup 2026'.
    """
    filtered_lines = ["#EXTM3U\n"]
    
    # Memisahkan baris mentah
    lines = raw_m3u.splitlines()
    
    # Daftar kata kunci World Cup
    wc_keywords = ["world cup", "worldcup", "piala dunia", "fifa"]
    
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
            # Menyimpan opsi tambahan (#EXTVLCOPT / #KODIPROP dsb)
            current_options.append(line)
        else:
            # Ini adalah baris URL stream
            if current_extinf:
                # Periksa apakah nama saluran (bagian setelah koma) mengandung keyword World Cup
                parts = current_extinf.split(",", 1)
                channel_name = parts[1].strip() if len(parts) >= 2 else ""
                
                # Cek keyword
                if any(kw in channel_name.lower() for kw in wc_keywords):
                    # Ubah group-title menjadi "World Cup 2026"
                    # Mencari group-title="..." dan menggantinya
                    if 'group-title="' in current_extinf:
                        updated_extinf = re.sub(r'group-title="[^"]+"', 'group-title="World Cup 2026"', current_extinf)
                    else:
                        # Jika tidak ada group-title, sisipkan sebelum koma terakhir
                        updated_extinf = current_extinf.replace(",", ' group-title="World Cup 2026",', 1)
                        
                    # Tambahkan extinf yang sudah dimodifikasi
                    filtered_lines.append(updated_extinf + "\n")
                    
                    # Tambahkan opsi tambahan pendukung
                    for opt in current_options:
                        filtered_lines.append(opt + "\n")
                        
                    # Tambahkan URL stream
                    filtered_lines.append(line + "\n")
                
                # Reset penampung
                current_extinf = ""
                current_options = []
                
    return "".join(filtered_lines)

def main():
    print(f"Mengunduh playlist dari {URL_GCIKAR}...")
    headers = {
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    }
    
    try:
        response = requests.get(URL_GCIKAR, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        raw_content = response.text
        
        print("Menyaring saluran, menyisakan hanya kategori World Cup 2026...")
        filtered_content = parse_and_filter_worldcup(raw_content)
        
        # Pastikan output folder ada
        OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
        
        # Tulis file M3U yang sudah difilter
        with open(M3U_PATH, "w", encoding="utf-8") as f:
            f.write(filtered_content)
        print(f"File berhasil disaring dan disimpan di: {M3U_PATH}")
        
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