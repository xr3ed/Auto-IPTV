import os
import sys
import re
import json
import requests
from datetime import datetime
import urllib3
from dotenv import load_dotenv

# Muat variabel lingkungan dari berkas .env
load_dotenv()

# Konfigurasi stdout ke UTF-8 agar tidak terjadi UnicodeEncodeError di Windows
if sys.platform.startswith('win'):
    try:
        sys.stdout.reconfigure(encoding='utf-8')
    except Exception:
        pass

# Matikan warning SSL tidak aman
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

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
# URL tambahan hanya dimuat jika didefinisikan secara eksplisit di env
DEFAULT_UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
BLOCKLIST_PATH = os.path.join("playlists", "blocklist.json")

def parse_worldcup_streams(raw_m3u_list):
    wc_keywords = ["world cup", "worldcup", "piala dunia", "fifa"]
    
    entries = []
    seen_urls = set()
    
    for raw_m3u in raw_m3u_list:
        lines = raw_m3u.splitlines()
        current_extinf = ""
        current_options = []
        
        for line in lines:
            line_str = line.strip()
            if not line_str or line_str.startswith("#EXTM3U"):
                continue
                
            if line_str.startswith("#EXTINF:"):
                current_extinf = line_str
                current_options = []
            elif line_str.startswith("#"):
                current_options.append(line_str)
            else:
                if current_extinf:
                    parts = current_extinf.split(",", 1)
                    channel_name = parts[1].strip() if len(parts) >= 2 else ""
                    
                    if line_str not in seen_urls:
                        # Cek filter berdasarkan nama channel atau kategori (group-title)
                        group_title = ""
                        group_match = re.search(r'group-title="([^"]+)"', current_extinf, re.IGNORECASE)
                        if group_match:
                            group_title = group_match.group(1).lower()
                            
                        is_wc_name = any(kw in channel_name.lower() for kw in wc_keywords)
                        is_wc_group = any(g_kw in group_title for g_kw in ["world cup", "worldcup", "piala dunia", "fifa", "2026"])
                        
                        if is_wc_name or is_wc_group:
                            seen_urls.add(line_str)
                            entries.append({
                                "name": channel_name,
                                "options": current_options,
                                "url": line_str
                            })
                    current_extinf = ""
                    current_options = []
                    
    return entries

def check_stream(entry):
    url = entry["url"]
    name = entry["name"]
    options = entry["options"]
    
    headers = {
        "User-Agent": DEFAULT_UA
    }
    
    # Ekstrak custom referrer atau user-agent dari opsi M3U
    for opt in options:
        # Contoh: #EXTVLCOPT:http-referrer=https://cazetv.com.br/
        ref_match = re.search(r'http-referrer=(.+)', opt, re.IGNORECASE)
        if ref_match:
            headers["Referer"] = ref_match.group(1).strip()
            headers["Origin"] = ref_match.group(1).strip()
            
        ua_match = re.search(r'http-user-agent=(.+)', opt, re.IGNORECASE)
        if ua_match:
            headers["User-Agent"] = ua_match.group(1).strip()
            
    print(f"Menguji: {name}")
    print("  URL: [HIDDEN]")
    if "Referer" in headers:
        print(f"  Referer: {headers['Referer']}")
        
    try:
        # Lakukan request GET dengan timeout 10 detik.
        # Meniru player Kodi/Tivimate dengan verifikasi SSL dimatikan agar bypass error sertifikat lokal.
        response = requests.get(url, headers=headers, timeout=10, verify=False, stream=True)
        
        # Jika status 2xx, anggap online dan berfungsi
        if response.status_code >= 200 and response.status_code < 300:
            print(f"  [OK] Status: {response.status_code}")
            return True, response.status_code, "OK"
        else:
            print(f"  [FAIL] Status: {response.status_code}")
            return False, response.status_code, f"HTTP Error {response.status_code}"
            
    except requests.exceptions.Timeout:
        print("  [FAIL] Timeout")
        return False, None, "Timeout"
    except Exception as e:
        print(f"  [FAIL] Error: {e}")
        return False, None, str(e)

def main():
    if not URL_GCIKAR:
        print("Error: GCIKAR_URL tidak didefinisikan di environment variables (.env / GitHub secrets).")
        return
    print("Mengunduh playlist utama...")
    headers = {
        "User-Agent": DEFAULT_UA
    }
    raw_contents = []
    try:
        response = requests.get(URL_GCIKAR, headers=headers, timeout=30, verify=False)
        response.raise_for_status()
        raw_contents.append(response.text)
    except Exception as e:
        print(f"Gagal mengunduh playlist utama: {e}")

    for idx, url in enumerate(ADDITIONAL_URLS):
        try:
            print(f"Mengunduh playlist tambahan {idx+1}...")
            resp = requests.get(url, headers=headers, timeout=30, verify=False)
            resp.raise_for_status()
            raw_contents.append(resp.text)
        except Exception as e:
            print(f"Gagal mengunduh playlist tambahan {idx+1}: {e}")

    if not raw_contents:
        print("Tidak ada konten playlist yang berhasil diunduh.")
        return

    wc_entries = parse_worldcup_streams(raw_contents)
    print(f"Menemukan {len(wc_entries)} channel World Cup untuk diuji.\n")
    
    # Load blocklist yang sudah ada
    blocklist = {}
    if os.path.exists(BLOCKLIST_PATH):
        try:
            with open(BLOCKLIST_PATH, "r", encoding="utf-8") as f:
                blocklist = json.load(f)
        except Exception:
            pass
            
    failed_count = 0
    passed_count = 0
    
    # Lakukan uji coba
    for entry in wc_entries:
        url = entry["url"]
        is_ok, status_code, reason = check_stream(entry)
        
        if not is_ok:
            failed_count += 1
            blocklist[url] = {
                "name": entry["name"],
                "status_code": status_code,
                "reason": reason,
                "timestamp": datetime.utcnow().isoformat() + "Z"
            }
        else:
            passed_count += 1
            # Hapus dari blocklist jika sebelumnya ada tapi sekarang sudah aktif kembali
            if url in blocklist:
                del blocklist[url]
                
    # Pastikan direktori playlists ada
    os.makedirs(os.path.dirname(BLOCKLIST_PATH), exist_ok=True)
    
    # Simpan kembali blocklist
    with open(BLOCKLIST_PATH, "w", encoding="utf-8") as f:
        json.dump(blocklist, f, indent=2, ensure_ascii=False)
        
    print("\n=== Ringkasan Pengujian ===")
    print(f"Total diuji: {len(wc_entries)}")
    print(f"Berhasil: {passed_count}")
    print(f"Gagal/Bermasalah: {failed_count}")
    print(f"Total terdaftar di blocklist saat ini: {len(blocklist)}")
    print(f"Blocklist disimpan di: {BLOCKLIST_PATH}")

if __name__ == "__main__":
    main()
