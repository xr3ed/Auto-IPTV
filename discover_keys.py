import os
import sys
import io
import re
import json
import requests
import urllib3

# Pastikan stdout/stderr menggunakan UTF-8 di terminal Windows untuk menghindari UnicodeEncodeError
if sys.platform.startswith('win'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

# Nonaktifkan peringatan SSL tidak aman
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DRM_KEYS_FILE = os.path.join("playlists", "drm_keys.json")

# URL playlist yang sering memiliki update ClearKey DRM
DRM_SOURCES = [
    "https://raw.githubusercontent.com/apistech/project/refs/heads/main/IndihomeTV.m3u",
    "https://raw.githubusercontent.com/dhasap/dhanytv/main/dhanytv.m3u",
    "https://raw.githubusercontent.com/windozalmi/Playlist-IPTV-Indonesia-online-Aktif-2025/refs/heads/m3u/IPTV%20Indonesia%20by%20WINDO%20ZALMI",
    "https://raw.githubusercontent.com/apistech/project/refs/heads/main/playlists/wc2026.m3u",
]

def clean_manifest_url(url: str) -> str:
    """Membersihkan URL manifest dengan membuang query parameter agar seragam."""
    return url.split("?")[0].strip()

def parse_m3u_for_drm_keys(content: str) -> dict:
    """Mem-parsing isi berkas M3U dan mengekstrak info kunci DRM untuk setiap URL manifest dasar."""
    keys_db = {}
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            extinf = line
            opts = []
            i += 1
            # Kumpulkan semua opsi diawali '#'
            while i < len(lines) and lines[i].startswith('#') and not lines[i].startswith('#EXTINF'):
                opts.append(lines[i].strip())
                i += 1
            
            # Kumpulkan URL
            if i < len(lines) and lines[i].strip() and not lines[i].startswith('#'):
                url = lines[i].strip()
                
                # Cari apakah ada info license di opts
                license_type = ""
                license_key = ""
                referrer = ""
                
                for opt in opts:
                    opt_lower = opt.lower()
                    if "license_type" in opt_lower:
                        m = re.search(r'license_type=([^&\s]+)', opt)
                        if m:
                            license_type = m.group(1).strip()
                    elif "license_key" in opt_lower:
                        m = re.search(r'license_key=([^&\s]+)', opt)
                        if m:
                            license_key = m.group(1).strip()
                    elif "http-referrer" in opt_lower:
                        m = re.search(r'http-referrer=([^&\s]+)', opt)
                        if m:
                            referrer = m.group(1).strip()
                    elif "http-origin" in opt_lower:
                        m = re.search(r'http-origin=([^&\s]+)', opt)
                        if m:
                            # Gunakan origin sebagai referrer cadangan
                            if not referrer:
                                referrer = m.group(1).strip()
                
                # Jika ada license_key, masukkan ke database mapping
                if license_key:
                    base_url = clean_manifest_url(url)
                    keys_db[base_url] = {
                        "license_type": license_type or "org.w3.clearkey",
                        "license_key": license_key,
                        "referrer": referrer
                    }
        i += 1
    return keys_db

def harvest_keys():
    print("🌾 Memulai proses pemindaian kunci DRM (ClearKey) dari internet...")
    os.makedirs(os.path.dirname(DRM_KEYS_FILE), exist_ok=True)
    
    # Load database lama jika ada
    existing_db = {}
    if os.path.exists(DRM_KEYS_FILE):
        try:
            with open(DRM_KEYS_FILE, 'r', encoding='utf-8') as f:
                existing_db = json.load(f)
            print(f"📖 Memuat {len(existing_db)} kunci DRM dari cache lokal.")
        except Exception:
            pass
            
    updated_db = dict(existing_db)
    new_keys_count = 0
    
    for src in DRM_SOURCES:
        print(f"🔗 Memindai sumber: {src}...")
        try:
            r = requests.get(src, timeout=15, verify=False)
            if r.status_code == 200:
                keys = parse_m3u_for_drm_keys(r.text)
                for k, v in keys.items():
                    if k not in updated_db or updated_db[k]["license_key"] != v["license_key"]:
                        if k not in updated_db:
                            new_keys_count += 1
                        updated_db[k] = v
                print(f"   -> Ditemukan {len(keys)} kunci DRM di sumber ini.")
            else:
                print(f"   [WARNING] Gagal mengunduh sumber: HTTP {r.status_code}")
        except Exception as e:
            print(f"   [WARNING] Error saat mengakses sumber: {e}")
            
    # Tulis hasil database terbaru
    try:
        with open(DRM_KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(updated_db, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Database kunci DRM berhasil disimpan di {DRM_KEYS_FILE}")
        print(f"   Total Kunci Aktif: {len(updated_db)} (+{new_keys_count} baru)")
    except Exception as e:
        print(f"❌ Gagal menyimpan database kunci: {e}")

if __name__ == "__main__":
    harvest_keys()
