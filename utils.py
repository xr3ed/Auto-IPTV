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


def load_drm_keys_db() -> dict:
    """Memuat database kunci DRM hasil harvester."""
    import json
    path = os.path.join("playlists", "drm_keys.json")
    if os.path.exists(path):
        try:
            with open(path, 'r', encoding='utf-8') as f:
                return json.load(f)
        except Exception:
            pass
    return {}


def clean_manifest_url(url: str) -> str:
    """Membersihkan URL manifest agar seragam dan menormalisasi semua tipe token path dinamis global."""
    # 1. Buang query parameters di belakang tanda tanya
    url_clean = url.split("?")[0].strip()
    
    # 2. Normalisasi token dinamis UUID 36-karakter (misal: 376c96cd-193f-46d1-a2b6-7c2b78cb0aa5)
    url_clean = re.sub(r'/[a-f0-9]{8}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{4}-[a-f0-9]{12}/', '/TOKEN/', url_clean, flags=re.IGNORECASE)
    
    # 3. Normalisasi semua segmen path berukuran 32 karakter hex murni secara global
    parts = url_clean.split('/')
    new_parts = []
    for part in parts:
        if re.match(r'^[a-f0-9]{32}$', part, re.IGNORECASE):
            new_parts.append('TOKEN')
        else:
            new_parts.append(part)
    url_clean = '/'.join(new_parts)
    
    return url_clean


def enrich_stream_with_drm_keys(url: str, opts: list) -> list:
    """Menyuntikkan lisensi ClearKey DRM dari database ke dalam opsi jika ada kecocokan manifest URL."""
    base_url = clean_manifest_url(url)
    db = load_drm_keys_db()
    
    if base_url in db:
        info = db[base_url]
        license_type = info.get("license_type", "org.w3.clearkey")
        license_key = info.get("license_key", "")
        referrer = info.get("referrer", "")
        
        # Saring opsi yang lama
        new_opts = []
        for opt in opts:
            opt_lower = opt.lower()
            if "license_type" in opt_lower or "license_key" in opt_lower:
                continue
            if referrer and "http-referrer" in opt_lower:
                continue
            new_opts.append(opt)
            
        # Suntikkan opsi baru
        if license_key:
            new_opts.append(f"#KODIPROP:inputstream.adaptive.license_type={license_type}")
            new_opts.append(f"#KODIPROP:inputstream.adaptive.license_key={license_key}")
        if referrer:
            new_opts.append(f"#EXTVLCOPT:http-referrer={referrer}")
            
        return new_opts
        
    return opts


def should_bypass_ping(url: str) -> bool:
    """Mengecek apakah URL stream menggunakan domain lokal Indihome/Telkom yang wajib dibypass ping."""
    url_lower = url.lower()
    bypass_keywords = [
        "indihometv.com",
        "telkom",
        "useetv",
        "10.0.",
        "192.168.",
        "172.16."
    ]
    return any(kw in url_lower for kw in bypass_keywords)


def get_fallback_logo(channel_name: str) -> str:
    """Mendapatkan logo cadangan resmi dari CDN IPTV-org jika logo bawaan kosong."""
    name_clean = channel_name.strip()
    # Bersihkan resolusi label seperti [HD], [FHD], dll.
    name_clean = re.sub(r'\[?(fhd|hd|sd)\]?', '', name_clean, flags=re.IGNORECASE).strip()
    # Bersihkan akhiran match atau source (misal: "Uruguay vs Spanyol - TVRI" -> "TVRI")
    if " - " in name_clean:
        name_clean = name_clean.split(" - ")[-1].strip()
        
    # Bersihkan spasi untuk pencocokan slug
    slug = name_clean.replace(" ", "").replace("TV", "tv").replace("Tv", "tv")
    
    # Mapping logo untuk stasiun TV lokal populer Indonesia
    indo_logos = {
        "rcti": "https://iptv-org.github.io/iptv/logos/countries/id/RCTI.png",
        "sctv": "https://iptv-org.github.io/iptv/logos/countries/id/SCTV.png",
        "indosiar": "https://iptv-org.github.io/iptv/logos/countries/id/Indosiar.png",
        "trans7": "https://iptv-org.github.io/iptv/logos/countries/id/Trans7.png",
        "transtv": "https://iptv-org.github.io/iptv/logos/countries/id/TransTV.png",
        "antv": "https://iptv-org.github.io/iptv/logos/countries/id/ANTV.png",
        "metrotv": "https://iptv-org.github.io/iptv/logos/countries/id/MetroTV.png",
        "kompastv": "https://iptv-org.github.io/iptv/logos/countries/id/KompasTV.png",
        "tvone": "https://iptv-org.github.io/iptv/logos/countries/id/tvOne.png",
        "rtv": "https://iptv-org.github.io/iptv/logos/countries/id/RTV.png",
        "net": "https://iptv-org.github.io/iptv/logos/countries/id/NETTV.png",
        "nettv": "https://iptv-org.github.io/iptv/logos/countries/id/NETTV.png",
        "mnctv": "https://iptv-org.github.io/iptv/logos/countries/id/MNCTV.png",
        "gtv": "https://iptv-org.github.io/iptv/logos/countries/id/GTV.png",
        "inews": "https://iptv-org.github.io/iptv/logos/countries/id/iNews.png",
        "tvri": "https://iptv-org.github.io/iptv/logos/countries/id/TVRI.png",
        "mojitv": "https://iptv-org.github.io/iptv/logos/countries/id/Moji.png",
        "moji": "https://iptv-org.github.io/iptv/logos/countries/id/Moji.png",
    }
    
    key = slug.lower()
    if key in indo_logos:
        return indo_logos[key]
        
    # Jika merupakan TVRI daerah, gunakan logo TVRI Nasional resmi sebagai fallback
    if "tvri" in key:
        return "https://iptv-org.github.io/iptv/logos/countries/id/TVRI.png"
        
    # Fallback default ke CDN global IPTV-org
    return f"https://iptv-org.github.io/iptv/logos/countries/id/{name_clean}.png"


def download_and_localize_logo(channel_name: str, original_logo_url: str) -> str:
    """Mengunduh logo dari URL eksternal ke folder logo lokal jika belum ada, dan mengembalikan URL repositori GitHub."""
    import requests
    import string
    
    # Langsung arahkan seluruh TVRI regional ke logo TVRI nasional lokal milik user
    if "tvri" in channel_name.lower():
        return "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/tvri.png"
        
    if not original_logo_url or not original_logo_url.strip():
        # Fallback jika URL kosong
        original_logo_url = get_fallback_logo(channel_name)
        
    # Buat nama berkas slug yang aman (misal: "TRANS TV" -> "trans_tv.png")
    valid_chars = f"-_.{string.ascii_letters}{string.digits}"
    slug = channel_name.strip().lower().replace(" ", "_")
    slug = "".join(c for c in slug if c in valid_chars)
    if not slug:
        slug = "channel"
        
    # Cek ekstensi file logo (default .png)
    ext = ".png"
    if ".jpg" in original_logo_url.lower() or ".jpeg" in original_logo_url.lower():
        ext = ".jpg"
        
    filename = f"{slug}{ext}"
    local_path = os.path.join("logo", filename)
    
    # 1. Jika gambar belum ada secara lokal, unduh gambarnya
    os.makedirs("logo", exist_ok=True)
    if not os.path.exists(local_path):
        try:
            print(f"📥 Mengunduh logo lokal baru: {filename}...")
            r = requests.get(original_logo_url, timeout=10, verify=False)
            if r.status_code == 200:
                with open(local_path, "wb") as img_f:
                    img_f.write(r.content)
            else:
                # Jika gagal unduh, pakai default fallback get_fallback_logo
                fallback_url = get_fallback_logo(channel_name)
                if fallback_url != original_logo_url:
                    return download_and_localize_logo(channel_name, fallback_url)
        except Exception as e:
            print(f"   [WARNING] Gagal mengunduh logo untuk {channel_name}: {e}")
            
    # 2. Kembalikan URL Raw GitHub milik user sendiri
    # Jika file terbukti berhasil ada di lokal (atau setidaknya kita asumsikan akan dipush)
    return f"https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/{filename}"


def sanitize_url_protocol(url: str) -> str:
    """Mengubah https ke http untuk port non-standar untuk menghindari jabat tangan SSL gagal."""
    import re
    match = re.search(r'https://([^:/]+):(\d+)', url)
    if match:
        port = int(match.group(2))
        if port in (8080, 8000, 8070, 25461, 9080, 9090, 80, 3000, 19360):
            url = url.replace("https://", "http://", 1)
    return url


def is_stream_playable(url: str, headers: dict = None) -> bool:
    """Menguji keaktifan manifest stream HLS/DASH dan mendeteksi geoblocking dengan mem-ping segmen medianya."""
    import requests
    from contextlib import closing
    import re
    
    headers = headers or {}
    url = sanitize_url_protocol(url)
    
    try:
        # Coba GET manifest utama secara stream=True
        with closing(requests.get(url, headers=headers, timeout=8, stream=True, verify=False)) as response:
            if response.status_code >= 400:
                return False
                
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            
            # Baca chunk awal manifest untuk dianalisis
            chunk = next(response.iter_content(chunk_size=15360), b"")
            if not chunk:
                return False
                
            preview = chunk.decode("utf-8", errors="ignore").lstrip()
            preview_lower = preview.lower()
            
            # HTML page (halaman blokir / error CDN) -> DEAD
            if preview_lower.startswith("<html") or "<html" in preview_lower[:300]:
                return False
                
            # A. Jika HLS (.m3u8)
            if preview.startswith("#EXTM3U") or preview.startswith("#EXT-X-") or ".m3u8" in url.lower():
                # Cari sub-playlist atau segmen video pertama (.ts / .m4s / .mp4 / .aac)
                lines = preview.splitlines()
                sub_url = ""
                for line in lines:
                    line_str = line.strip()
                    if line_str and not line_str.startswith("#"):
                        sub_url = line_str
                        break
                
                if sub_url:
                    if not sub_url.startswith("http"):
                        base_path = response.url.rsplit("/", 1)[0]
                        sub_url = base_path + "/" + sub_url
                    
                    try:
                        # Uji sub-playlist / segmen medianya
                        r_sub = requests.head(sub_url, headers=headers, timeout=5, verify=False)
                        if r_sub.status_code >= 400:
                            # Jika diblokir oleh CDN (HTTP 403 / 401)
                            return False
                    except Exception:
                        pass
                return True
                
            # B. Jika DASH (.mpd)
            if "<mpd" in preview_lower or ".mpd" in url.lower():
                # Cari segment inisialisasi media
                init_match = re.search(r'initialization="([^"]+)"', preview)
                if init_match:
                    init_segment = init_match.group(1)
                    if not init_segment.startswith("http"):
                        base_path = response.url.rsplit("/", 1)[0]
                        test_seg_url = base_path + "/" + init_segment
                    else:
                        test_seg_url = init_segment
                        
                    try:
                        # Uji keaktifan segmen video DASH (apakah diblokir geoblock oleh CDN)
                        r_seg = requests.head(test_seg_url, headers=headers, timeout=5, verify=False)
                        if r_seg.status_code >= 400:
                            return False
                    except Exception:
                        pass
                return True
                
            # C. Raw Stream (MPEG-TS, MP4)
            if chunk[:1] == b"\x47" or b"ftyp" in chunk[:32] or chunk[:3] == b"ID3":
                return True
                
            return False
            
    except Exception:
        return False
