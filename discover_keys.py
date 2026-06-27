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
    # M3U Playlists
    "https://raw.githubusercontent.com/apistech/project/refs/heads/main/IndihomeTV.m3u",
    "https://raw.githubusercontent.com/dhasap/dhanytv/main/dhanytv.m3u",
    "https://raw.githubusercontent.com/windozalmi/Playlist-IPTV-Indonesia-online-Aktif-2025/refs/heads/m3u/IPTV%20Indonesia%20by%20WINDO%20ZALMI",
    "https://raw.githubusercontent.com/apistech/project/refs/heads/main/playlists/wc2026.m3u",
    "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/World_Cup.m3u",
    "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/Toffee.m3u",
    "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/Combined_Live_TV.m3u",
]

def clean_manifest_url(url: str) -> str:
    """Membersihkan URL manifest agar seragam dan menormalisasi token path dinamis Amazon Prime Video."""
    # 1. Buang query parameters di belakang tanda tanya
    url_clean = url.split("?")[0].strip()
    
    # 2. Normalisasi token dinamis di path URL Amazon (mengubah 32 karakter hex acak menjadi 'TOKEN')
    url_clean = re.sub(r'/out/v1/[a-f0-9]{32}/', '/out/v1/TOKEN/', url_clean, flags=re.IGNORECASE)
    
    return url_clean

def parse_m3u_for_drm_keys(content: str) -> dict:
    """Mem-parsing isi berkas M3U dan mengekstrak info kunci DRM untuk setiap URL manifest dasar."""
    keys_db = {}
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    lines = content.splitlines()
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith("#EXTINF"):
            opts = []
            i += 1
            # Kumpulkan semua opsi diawali '#'
            while i < len(lines) and lines[i].strip().startswith('#') and not lines[i].strip().startswith('#EXTINF'):
                opts.append(lines[i].strip())
                i += 1
            
            # Kumpulkan URL
            if i < len(lines) and lines[i].strip() and not lines[i].strip().startswith('#'):
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
                            if not referrer:
                                referrer = m.group(1).strip()
                
                if license_key:
                    base_url = clean_manifest_url(url)
                    keys_db[base_url] = {
                        "license_type": license_type or "org.w3.clearkey",
                        "license_key": license_key,
                        "referrer": referrer,
                        "last_scanned": today_str
                    }
        i += 1
    return keys_db

def parse_json_for_drm_keys(content: str) -> dict:
    """Mem-parsing isi berkas JSON dan mengekstrak info kunci DRM."""
    keys_db = {}
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    try:
        data = json.loads(content)
        if isinstance(data, dict):
            for url, val in data.items():
                if isinstance(val, dict):
                    license_key = val.get("license_key") or val.get("key") or val.get("license")
                    if license_key:
                        base_url = clean_manifest_url(url)
                        keys_db[base_url] = {
                            "license_type": val.get("license_type") or "org.w3.clearkey",
                            "license_key": license_key,
                            "referrer": val.get("referrer") or val.get("referer") or "",
                            "last_scanned": today_str
                        }
                elif isinstance(val, str):
                    base_url = clean_manifest_url(url)
                    keys_db[base_url] = {
                        "license_type": "org.w3.clearkey",
                        "license_key": val,
                        "referrer": "",
                        "last_scanned": today_str
                    }
        elif isinstance(data, list):
            for item in data:
                if isinstance(item, dict):
                    url = item.get("url") or item.get("uri")
                    license_key = item.get("license_key") or item.get("key") or item.get("license")
                    if url and license_key:
                        base_url = clean_manifest_url(url)
                        keys_db[base_url] = {
                            "license_type": item.get("license_type") or "org.w3.clearkey",
                            "license_key": license_key,
                            "referrer": item.get("referrer") or item.get("referer") or "",
                            "last_scanned": today_str
                        }
    except Exception:
        pass
    return keys_db

def query_github_search_api(token: str = None) -> list[str]:
    """Mencari berkas playlist/keys baru di GitHub yang memuat ClearKey secara dinamis."""
    found_urls = []
    headers = {"Accept": "application/vnd.github.v3+json"}
    if token:
        headers["Authorization"] = f"token {token}"
        
    queries = [
        "inputstream.adaptive.license_key+extension:m3u",
        "license_key+filename:keys.json",
        "license_key+filename:drm_keys.json"
    ]
    
    for q in queries:
        url = f"https://api.github.com/search/code?q={q}&sort=indexed&order=desc"
        try:
            r = requests.get(url, headers=headers, timeout=10)
            if r.status_code == 200:
                data = r.json()
                for item in data.get("items", []):
                    raw_url = item.get("html_url", "").replace("github.com", "raw.githubusercontent.com").replace("/blob/", "/")
                    if raw_url and raw_url not in found_urls:
                        found_urls.append(raw_url)
            elif r.status_code == 403:
                print("   [INFO] GitHub Search API rate limited. Melewati pencarian dinamis.")
                break
        except Exception:
            pass
    return found_urls

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
    
    # Cari berkas playlist/kunci DRM secara dinamis di GitHub Search API
    token = os.environ.get("GITHUB_TOKEN")
    dynamic_sources = query_github_search_api(token)
    if dynamic_sources:
        print(f"🔍 GitHub Search API menemukan {len(dynamic_sources)} sumber kunci DRM tambahan secara dinamis.")
    
    # Gabungkan sumber statis dan dinamis
    all_sources = list(DRM_SOURCES)
    for ds in dynamic_sources:
        if ds not in all_sources:
            all_sources.append(ds)
            
    from datetime import datetime
    today_str = datetime.now().strftime("%Y-%m-%d")
    
    for src in all_sources:
        print(f"🔗 Memindai sumber: {src}...")
        try:
            r = requests.get(src, timeout=15, verify=False)
            if r.status_code == 200:
                # Deteksi format berkas (JSON vs M3U)
                is_json = src.lower().endswith(".json") or r.text.strip().startswith("{") or r.text.strip().startswith("[")
                if is_json:
                    keys = parse_json_for_drm_keys(r.text)
                else:
                    keys = parse_m3u_for_drm_keys(r.text)
                
                for k, v in keys.items():
                    if k not in updated_db or updated_db[k]["license_key"] != v["license_key"]:
                        if k not in updated_db:
                            new_keys_count += 1
                        updated_db[k] = v
                    else:
                        updated_db[k]["last_scanned"] = today_str
                print(f"   -> Ditemukan {len(keys)} kunci DRM di sumber ini.")
            else:
                print(f"   [WARNING] Gagal mengunduh sumber: HTTP {r.status_code}")
        except Exception as e:
            print(f"   [WARNING] Error saat mengakses sumber: {e}")
            
    # Lakukan pruning (pembersihan) kunci yang usianya > 14 hari
    final_db = {}
    pruned_count = 0
    today = datetime.now()
    
    for k, v in updated_db.items():
        ls_str = v.get("last_scanned")
        keep = True
        if ls_str:
            try:
                ls_date = datetime.strptime(ls_str, "%Y-%m-%d")
                if (today - ls_date).days > 14:
                    keep = False
            except Exception:
                pass
        
        if keep:
            final_db[k] = v
        else:
            pruned_count += 1
            
    if pruned_count > 0:
        print(f"🧹 Membersihkan {pruned_count} kunci DRM usang (lebih dari 14 hari).")
 
    # Tulis hasil database terbaru
    try:
        with open(DRM_KEYS_FILE, 'w', encoding='utf-8') as f:
            json.dump(final_db, f, indent=2, ensure_ascii=False)
        print(f"\n💾 Database kunci DRM berhasil disimpan di {DRM_KEYS_FILE}")
        print(f"   Total Kunci Aktif: {len(final_db)} (+{new_keys_count} baru, {pruned_count} dibersihkan)")
    except Exception as e:
        print(f"❌ Gagal menyimpan database kunci: {e}")
 
if __name__ == "__main__":
    harvest_keys()
