import os
import sys
import io
import re
import gzip
import xml.etree.ElementTree as ET
from datetime import datetime, timezone, timedelta
from contextlib import closing
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor, as_completed
import requests
import urllib3

# Pastikan stdout/stderr menggunakan UTF-8 di terminal Windows untuk menghindari UnicodeEncodeError
if sys.platform.startswith('win'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

# Nonaktifkan peringatan SSL tidak aman untuk bypass
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

TIMEOUT = 15
MAX_WORKERS = 16
OUTPUT_DIR = Path("playlists")
EPG_URL = "https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/epgs/guide.xml.gz"

# Database EPG global untuk penamaan dinamis
EPG_ACTIVE_PROGS = {}
EPG_NAME_TO_ID = {}
EPG_CHANNEL_NAMES = {}

# Daftar laga World Cup yang sudah selesai hari ini agar disaring keluar
FINISHED_WC_MATCHES = set()


# ====================================================================
# DAFTAR SUMBER PLAYLIST
# ====================================================================
SOURCES = [
    {
        "name": "apistech_wc",
        "url": "https://raw.githubusercontent.com/apistech/project/refs/heads/main/playlists/wc2026.m3u",
        "is_wc": True
    },
    {
        "name": "wc2026",
        "url": "https://github.com/sm-monirulislam/SM-Live-TV/raw/refs/heads/main/World_Cup.m3u",
        "is_wc": True
    },
    {
        "name": "buddy_sport",
        "url": "https://github.com/BuddyChewChew/storage/raw/main/sport.m3u",
        "is_wc": False
    },
    {
        "name": "live_events",
        "url": "https://github.com/doms9/iptv/raw/refs/heads/default/M3U8/events.m3u8",
        "is_wc": False
    },
    {
        "name": "bittv_sports_local",
        "url": "playlists/bittv_sports.m3u",
        "filter_groups": {
            "Sports": "live"
        }
    },
    {
        "name": "dhanytv_sports",
        "url": "https://raw.githubusercontent.com/dhasap/dhanytv/main/dhanytv.m3u",
        "filter_groups": {
            "WorldCup 2026": "wc",
            "Sports": "live",
            "bEIN SPORTS": "live",
            "⚽ Bola Indonesia": "live"
        }
    },
    {
        "name": "basictv_sports",
        "url": "https://gist.githubusercontent.com/R03nDL03n1/6361525c226ccc713f48e7fea5399df4/raw/d4443e16c36c8b73cfb028e5b771b870d5695f55/BasicTVStandar",
        "filter_groups": {
            "Live Event": "live",
            "Sports TV": "live",
            "Bein Sports": "live"
        }
    },
    {
        "name": "windozalmi_sports",
        "url": "https://raw.githubusercontent.com/windozalmi/Playlist-IPTV-Indonesia-online-Aktif-2025/refs/heads/m3u/IPTV%20Indonesia%20by%20WINDO%20ZALMI",
        "filter_groups": {
            "SPORTS": "live",
            "WORLD SPORTS": "live",
            "PIALA DUNIA": "wc"
        }
    }
]

VALID_CONTENT_TYPES = {
    "application/dash+xml",
    "application/vnd.apple.mpegurl",
    "application/x-mpegurl",
    "video/m4s",
    "video/mp2t",
    "video/mp4",
    "video/mpeg",
    "video/ogg",
    "video/ts",
    "video/webm",
    "video/x-flv",
}


def sanitize_url_protocol(url: str) -> str:
    """Mengubah https ke http untuk port non-standar untuk menghindari jabat tangan SSL gagal."""
    match = re.search(r'https://([^:/]+):(\d+)', url)
    if match:
        port = int(match.group(2))
        if port in (8080, 8000, 8070, 25461, 9080, 9090, 80, 3000, 19360):
            url = url.replace("https://", "http://", 1)
    return url


def is_stream_playable(url: str, headers: dict = None) -> bool:
    headers = headers or {}
    url = sanitize_url_protocol(url)

    # 1. Coba HEAD request dulu (efisien) - bypass SSL verify
    try:
        response = requests.head(
            url, headers=headers, timeout=TIMEOUT, allow_redirects=True, verify=False
        )
        if response.status_code < 400:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type in VALID_CONTENT_TYPES or not content_type:
                return True
    except requests.exceptions.SSLError:
        if url.startswith("https://"):
            return is_stream_playable(url.replace("https://", "http://", 1), headers)
    except requests.RequestException:
        pass

    # 2. Fallback ke GET stream, body-sniff untuk validasi konten - bypass SSL verify
    try:
        with closing(
            requests.get(
                url, headers=headers, timeout=TIMEOUT, stream=True, allow_redirects=True, verify=False
            )
        ) as response:
            if response.status_code >= 400:
                return False

            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type in VALID_CONTENT_TYPES:
                return True

            # Body-sniff: baca chunk pertama, cek apakah manifest/stream valid
            try:
                chunk = next(response.iter_content(chunk_size=2048), b"")
            except (StopIteration, requests.RequestException):
                return False

            if not chunk:
                return False

            preview = chunk.decode("utf-8", errors="ignore").lstrip()
            preview_lower = preview.lower()

            # HTML page (error/geo-block) -> not playable
            if preview_lower.startswith("<html") or "<html" in preview_lower[:200]:
                return False

            # Valid M3U8 manifest
            if preview.startswith("#EXTM3U") or preview.startswith("#EXT-X-"):
                return True

            # Binary stream signatures (MPEG-TS sync byte, MP4 ftyp box, ID3 tag)
            if chunk[:1] == b"\x47":  # MPEG-TS sync byte
                return True
            if b"ftyp" in chunk[:32]:  # MP4 container
                return True
            if chunk[:3] == b"ID3" or chunk[:2] == b"\xff\xff" or chunk[:2] == b"\xff\xfb":  # MP3/ID3
                return True

            return False

    except requests.exceptions.SSLError:
        if url.startswith("https://"):
            return is_stream_playable(url.replace("https://", "http://", 1), headers)
    except requests.RequestException:
        return False


def detect_stream_resolution(url: str, headers: dict = None) -> str:
    """Mengunduh chunk awal manifest .m3u8 untuk menganalisis resolusi stream secara dinamis."""
    headers = headers or {}
    url = sanitize_url_protocol(url)
    try:
        with closing(requests.get(url, headers=headers, timeout=5, stream=True, verify=False)) as r:
            if r.status_code >= 400:
                return ""
            chunk = next(r.iter_content(chunk_size=4096), b"")
            preview = chunk.decode("utf-8", errors="ignore")
            
            # Deteksi resolusi (misal: RESOLUTION=1920x1080)
            resolutions = re.findall(r'RESOLUTION=(\d+x\d+)', preview)
            if resolutions:
                highest = sorted(resolutions, key=lambda x: int(x.split('x')[0]))[-1]
                width = int(highest.split('x')[0])
                if width >= 1920:
                    return "FHD"
                elif width >= 1280:
                    return "HD"
                return "SD"
    except requests.exceptions.SSLError:
        if url.startswith("https://"):
            return detect_stream_resolution(url.replace("https://", "http://", 1), headers)
    except Exception:
        pass
    return ""


def parse_m3u(lines: list[str]) -> list[dict]:
    entries = []
    buffer_extinf = []
    buffer_other = []
    buffer_vlcopt = []

    for line in lines:
        stripped = line.strip()

        if line.startswith("#EXTINF"):
            buffer_extinf.append(line)
        elif line.startswith("#EXTVLCOPT"):
            buffer_vlcopt.append(line)
        elif stripped.startswith("#EXTM3U"):
            continue
        elif stripped.startswith("#"):
            buffer_other.append(line)
        elif stripped and not stripped.startswith("#"):
            url = sanitize_url_protocol(stripped)

            # Lakukan enrichment dengan kunci DRM otomatis
            from utils import enrich_stream_with_drm_keys
            combined_opts = buffer_vlcopt + buffer_other
            enriched_opts = enrich_stream_with_drm_keys(url, combined_opts)
            
            new_vlcopt = []
            new_other = []
            for opt in enriched_opts:
                if opt.startswith("#EXTVLCOPT"):
                    new_vlcopt.append(opt)
                else:
                    new_other.append(opt)
                    
            buffer_vlcopt = new_vlcopt
            buffer_other = new_other

            headers = {}
            for opt in buffer_vlcopt:
                if opt.startswith("#EXTVLCOPT:"):
                    key_value = opt[len("#EXTVLCOPT:"):].split("=", 1)
                    if len(key_value) == 2:
                        key, value = key_value
                        key = key.lower()
                        if key == "http-referrer":
                            headers["Referer"] = value
                        elif key == "http-origin":
                            headers["Origin"] = value
                        elif key == "http-user-agent":
                            headers["User-Agent"] = value

            entries.append({
                "extinf": buffer_extinf,
                "other": buffer_other,
                "vlcopt": buffer_vlcopt,
                "url": url,
                "headers": headers,
            })

            buffer_extinf = []
            buffer_other = []
            buffer_vlcopt = []

    return entries


def dedup_entries(entries: list[dict]) -> tuple[list[dict], int]:
    seen_urls = set()
    unique_entries = []

    for entry in entries:
        url = entry["url"]
        if url not in seen_urls:
            seen_urls.add(url)
            unique_entries.append(entry)

    removed = len(entries) - len(unique_entries)
    return unique_entries, removed


def fetch_playlist(url: str) -> list[str] | None:
    if os.path.exists(url):
        try:
            with open(url, 'r', encoding='utf-8', errors='ignore') as f:
                return [line.rstrip() for line in f.read().splitlines()]
        except Exception as e:
            print(f"  [ERROR] Gagal membaca file lokal: {e}")
            return None
    try:
        response = requests.get(url, timeout=30, verify=False)
        response.raise_for_status()
        return [line.rstrip() for line in response.text.splitlines()]
    except requests.RequestException as e:
        print(f"  [ERROR] Gagal fetch source: {e}")
        return None


# ====================================================================
# SINKRONISASI STREAM & NEGARA DILUAR PLAYLIST
# ====================================================================
COUNTRY_MAP = {
    "ger": "Jerman", "ivo": "Pantai Gading",
    "ecu": "Ekuador", "cur": "Curacao",
    "tun": "Tunisia", "jap": "Jepang",
    "swe": "Swedia", "aus": "Australia",
    "par": "Paraguay", "usa": "AS",
    "tur": "Turki", "ned": "Belanda",
    "col": "Kolombia", "bra": "Brasil",
    "arg": "Argentina", "fra": "Prancis",
    "esp": "Spanyol", "eng": "Inggris",
    "ita": "Italia", "por": "Portugal",
    "cro": "Kroasia", "mex": "Meksiko",
    "can": "Kanada", "sen": "Senegal",
    "mar": "Maroko", "gha": "Ghana",
    "cmr": "Kamerun", "kor": "Korsel",
    "ksa": "Arab Saudi", "pol": "Polandia",
    "bel": "Belgia", "den": "Denmark",
    "sui": "Swiss", "uru": "Uruguay"
}

STREAM_MATCH_MAP = {}
STREAM_RES_MAP = {}

def get_url_path_key(url: str) -> str:
    """Mengambil bagian path unik dari URL HLS (mengabaikan domain dan query params) untuk matching silang."""
    match = re.search(r'https?://[^/]+(/.*)', url)
    if match:
        path = match.group(1).split('?')[0]
        return path
    return url

def parse_url_code(url: str) -> str:
    """Mendeteksi kode laga di dalam URL path (misal: /live/gervsivo/ -> Jerman vs Pantai Gading)."""
    match = re.search(r'/live/([a-z]{3})vs([a-z]{3})/', url.lower())
    if match:
        c1 = match.group(1)
        c2 = match.group(2)
        team1 = COUNTRY_MAP.get(c1, c1.upper())
        team2 = COUNTRY_MAP.get(c2, c2.upper())
        return f"{team1} vs {team2}"
    return ""


SPORT_POSTER_MAP = {
    "baseball": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/mlb.png",
    "mlb": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/mlb.png",
    "basketball": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/nba.png",
    "nba": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/nba.png",
    "wnba": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/wnba.png",
    "motogp": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/motogp.png",
    "moto gp": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/motogp.png",
    "f1": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/f1.png",
    "formula 1": "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/f1.png",
    "volleyball": "https://upload.wikimedia.org/wikipedia/commons/e/e0/Volleyball_pictogram.svg",
    "vnl": "https://upload.wikimedia.org/wikipedia/commons/e/e0/Volleyball_pictogram.svg",
}


def clean_channel_name(display_name: str) -> str:
    name = display_name.strip().lower()
    # Hapus label resolusi
    name = re.sub(r'\[?(fhd|hd|sd)\]?', '', name)
    # Hapus spasi dan karakter non-alphanumeric dasar
    name = re.sub(r'[^a-z0-9]', '', name)
    return name


def clean_match_name(title: str) -> str:
    # 1. Hapus WIB, tanggal, dll.
    title_clean = re.sub(r'\d+:\d+\s*(WIB|WITA|WIT)?', '', title, flags=re.IGNORECASE)
    title_clean = re.sub(r'\d+\s*[A-Za-z]+\s*\d+:\d+\s*(WIB|WITA|WIT)?', '', title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'\d+\s*[A-Za-z]+', '', title_clean, flags=re.IGNORECASE)
    
    # 2. Hapus turnamen/prefix sampah dan VNL, Week, dll.
    title_clean = re.sub(r'^.*?world\s*cup[^:]*:\s*', '', title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'^.*?piala\s*dunia[^:]*:\s*', '', title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'^.*?live\s*:\s*', '', title_clean, flags=re.IGNORECASE)
    title_clean = re.sub(r'\|\s*Week\s*\d+\s*\|.*', '', title_clean, flags=re.IGNORECASE)
    
    # 3. Cari match "vs" atau "v" atau "at" (mendukung huruf Unicode seperti ü, ç, dll.)
    match = re.search(r"([\w\s\-\.']+)\s+(vs|v|at)\s+([\w\s\-\.']+)", title_clean, re.IGNORECASE | re.UNICODE)
    if match:
        team1 = match.group(1).strip()
        team2 = match.group(3).strip()
    else:
        # Fallback 4: Jika mengandung " - " dan di judulnya berkaitan dengan World Cup / Soccer, parse " - " sebagai separator laga
        # Contoh: "[Fifa World Cup] Japan - Sweden (EMBEDHD)"
        title_lower = title.lower()
        is_football_related = any(kw in title_lower for kw in ["world cup", "worldcup", "piala dunia", "fifa", "soccer", "football"])
        if is_football_related and " - " in title_clean:
            # Bersihkan title_clean dari kata-kata turnamen/sampah
            temp = re.sub(r'\[?(fifa|world|cup|2026|soccer|football)\]?', '', title_clean, flags=re.IGNORECASE).strip()
            # Hapus kurung bracket di awal jika ada
            temp = re.sub(r'^\[.*?\]', '', temp).strip()
            parts = temp.split(" - ")
            if len(parts) >= 2:
                team1 = parts[0].strip()
                team2 = parts[1].strip()
            else:
                return title.strip()
        else:
            return title.strip()
            
    # Bersihkan kata-kata sampah dari team1 & team2
    team1 = re.sub(r'^[\[\s]*[\w\s]+\s*\]', '', team1).strip() # [WNBA], [Baseball], [Football]
    team1 = re.sub(r'^[\[\s]*(fifa|world|cup|2026|soccer|football)\s*\]?', '', team1, flags=re.IGNORECASE).strip()
    team2 = re.sub(r'\(.*?\)', '', team2).strip() # (CDNTV)
    team2 = re.sub(r'\|.*', '', team2).strip()
    team1 = re.sub(r'\s+', ' ', team1)
    team2 = re.sub(r'\s+', ' ', team2)
    
    # Terjemahkan nama negara English -> Indonesia
    team1_lower = team1.lower()
    team2_lower = team2.lower()
    
    ENG_TO_IDN_MAP = {
        "japan": "Jepang", "sweden": "Swedia", "germany": "Jerman", 
        "ecuador": "Ekuador", "tunisia": "Tunisia", "netherlands": "Belanda",
        "paraguay": "Paraguay", "australia": "Australia", "turkey": "Turki",
        "türkiye": "Turki", "united states": "AS", "usa": "AS",
        "ivory coast": "Pantai Gading", "curacao": "Curacao", "curaçao": "Curacao",
        "spain": "Spanyol", "france": "Prancis", "england": "Inggris",
        "italy": "Italia", "portugal": "Portugal", "croatia": "Kroasia",
        "mexico": "Meksiko", "canada": "Kanada", "senegal": "Senegal",
        "morocco": "Maroko", "ghana": "Ghana", "cameroon": "Kamerun",
        "south korea": "Korsel", "korea": "Korsel", "saudi arabia": "Arab Saudi",
        "poland": "Polandia", "belgium": "Belgia", "denmark": "Denmark",
        "switzerland": "Swiss", "uruguay": "Uruguay", "argentina": "Argentina",
        "brazil": "Brasil", "colombia": "Kolombia"
    }
    
    t1_clean = ENG_TO_IDN_MAP.get(team1_lower, team1)
    t2_clean = ENG_TO_IDN_MAP.get(team2_lower, team2)
    
    return f"{t1_clean} vs {t2_clean}"


def parse_xmltv_time(value: str) -> datetime | None:
    if not value:
        return None
    try:
        value = value.strip()
        dt_part, _, tz_part = value.partition(" ")
        dt = datetime.strptime(dt_part, "%Y%m%d%H%M%S")
        if tz_part:
            sign = 1 if tz_part[0] == "+" else -1
            hours = int(tz_part[1:3])
            minutes = int(tz_part[3:5])
            offset = sign * (hours * 3600 + minutes * 60)
            dt = dt - timedelta(seconds=offset)
        return dt.replace(tzinfo=timezone.utc)
    except Exception:
        return None


def score_epg_title(title: str) -> int:
    score = 0
    title_lower = title.lower()
    if "vs" in title_lower or " v " in title_lower or " at " in title_lower or " - " in title_lower:
        score += 10
    if "world cup" in title_lower or "worldcup" in title_lower or "piala dunia" in title_lower or "fifa" in title_lower:
        score += 5
    if len(title) > 30:
        score += 2
    if title_lower in ["tvri", "sctv", "indosiar", "rcti", "mnc tv", "trans 7", "trans tv", "global tv", "antv"]:
        score -= 20
    return score


def get_epg_match_for_channel(attrs: dict) -> str:
    tid = attrs.get("tvg-id")
    matched_prog = None
    
    # 1. Direct tvg-id match
    if tid:
        for possible_id in [tid, tid + "@SD", tid + "@HD"]:
            if possible_id in EPG_ACTIVE_PROGS:
                matched_prog = EPG_ACTIVE_PROGS[possible_id]
                break
                
    # 2. Name-based fuzzy match
    if not matched_prog:
        for name_val in [attrs.get("tvg-id"), attrs.get("tvg-name"), attrs.get("display_name")]:
            if not name_val:
                continue
            norm_val = re.sub(r'[^a-z0-9]', '', name_val.lower())
            
            # Try stripping standard suffixes
            for suffix in ["hd", "fhd", "sd", "indonesia"]:
                if norm_val.endswith(suffix) and len(norm_val) > len(suffix):
                    norm_val_strip = norm_val[:-len(suffix)]
                    if norm_val_strip in EPG_NAME_TO_ID:
                        cid = EPG_NAME_TO_ID[norm_val_strip]
                        if cid in EPG_ACTIVE_PROGS:
                            matched_prog = EPG_ACTIVE_PROGS[cid]
                            break
            if matched_prog:
                break
                
            if norm_val in EPG_NAME_TO_ID:
                cid = EPG_NAME_TO_ID[norm_val]
                if cid in EPG_ACTIVE_PROGS:
                    matched_prog = EPG_ACTIVE_PROGS[cid]
                    break
                    
    if matched_prog:
        # Clean it using clean_match_name
        cleaned = clean_match_name(matched_prog)
        if cleaned and cleaned != matched_prog and "vs" in cleaned.lower():
            return cleaned
            
    return ""


def parse_extinf_attributes(extinf_line: str) -> dict:
    attrs = {}
    for key in ["tvg-chno", "tvg-id", "tvg-name", "tvg-logo", "group-title"]:
        match = re.search(rf'{key}="([^"]*)"', extinf_line)
        if match:
            attrs[key] = match.group(1)
        else:
            attrs[key] = ""
    display_name = ""
    parts = extinf_line.rsplit(',', 1)
    if len(parts) == 2:
        display_name = parts[1].strip()
    attrs["display_name"] = display_name
    return attrs


def build_extinf_line(attrs: dict) -> str:
    parts = ["#EXTINF:-1"]
    for key in ["tvg-chno", "tvg-id", "tvg-name", "tvg-logo", "group-title"]:
        if attrs.get(key):
            parts.append(f'{key}="{attrs[key]}"')
    return " ".join(parts) + f",{attrs.get('display_name', 'Unknown')}"


def extract_channel_suffix(title: str, source_name: str) -> str:
    # 1. Jika ada "|" (pipe), ambil bagian kanannya
    if "|" in title:
        suffix = title.split("|", 1)[1].strip()
        return re.sub(r'\[?(fhd|hd|sd)\]?', '', suffix, flags=re.IGNORECASE).strip()
        
    # 2. Jika ada kurung di akhir, ambil isi kurungnya (misal: (EMBEDHD) -> EMBED)
    match_paren = re.search(r'\(([^)]+)\)\s*$', title)
    if match_paren:
        suffix = match_paren.group(1).strip()
        suffix = re.sub(r'(fhd|hd|sd)', '', suffix, flags=re.IGNORECASE).strip()
        if suffix:
            return suffix
            
    # 3. Jika ada " - " di akhir
    parts = title.split(" - ")
    if len(parts) > 1 and not any(kw in parts[-1].lower() for kw in ["world cup", "piala dunia", "fifa"]):
        suffix = parts[-1].strip()
        return re.sub(r'\[?(fhd|hd|sd)\]?', '', suffix, flags=re.IGNORECASE).strip()
        
    # Default: gunakan nama source
    return source_name.replace("_sports", "").replace("buddy_", "").replace("wc2026", "SM-TV").upper()


def format_and_enrich_sports_entry(entry: dict, source_name: str, active_wc_matches: list[str] = None) -> dict:
    extinf_line = entry["extinf"][0]
    attrs = parse_extinf_attributes(extinf_line)
    title = attrs["display_name"]
    title_lower = title.lower()
    
    # Saring keluar jika laga ini sudah selesai hari ini berdasarkan data ESPN
    cleaned_title_match = clean_match_name(title_lower)
    if cleaned_title_match:
        norm_match = cleaned_title_match.lower()
        if norm_match in FINISHED_WC_MATCHES:
            print(f"  [FILTER OUT] Mengabaikan laga yang sudah selesai: {title}")
            return None
            
        for finished_match in FINISHED_WC_MATCHES:
            teams = finished_match.split(" vs ")
            if len(teams) == 2:
                if teams[0] in title_lower and teams[1] in title_lower:
                    print(f"  [FILTER OUT] Mengabaikan laga yang sudah selesai (cadangan): {title}")
                    return None
                    
    resolution = entry.get("resolution", "")
    if not resolution:
        resolution = "HD"  # Fallback default agar format nama di IPTV player selalu seragam
    res_label = f"[{resolution}] " if resolution else ""
    
    # Klasifikasi World Cup vs Live Events
    is_wc = entry.get("is_wc", False)
    is_other_sport = any(kw in title_lower for kw in [
        "vnl", "volleyball", "baseball", "mlb", "motogp", "wnba", "nba", "basketball", 
        "f1", "formula 1", "tennis", "badminton", "ufc", "wwe", "nhl", "hockey", 
        "rugby", "cricket", "golf", "darts", "snooker", "nascar", "indycar", "superbike",
        "cfl", "nfl", "afl", "american football", "ncaa", "athletics", "boxing", "mma",
        "billiard", "pool", "snooker", "darts", "rally", "wrc", "racing", "cycling",
        "one championship", "one fight night", "one friday fights", "bellator", "pfl"
    ])
    
    # 1. Deteksi pencocokan nama laga dinamis dari URL
    url_key = get_url_path_key(entry["url"])
    match_name = STREAM_MATCH_MAP.get(url_key, "")
    if not match_name:
        match_name = parse_url_code(entry["url"])
        
    if match_name:
        if not resolution and STREAM_RES_MAP.get(url_key):
            resolution = STREAM_RES_MAP[url_key]
            res_label = f"[{resolution}] " if resolution else ""
        if not is_other_sport:
            is_wc = True
            
    # 2. Deteksi berdasarkan judul dan separator
    has_match_separator = any(sep in title_lower for sep in [" vs ", " v ", " at ", " - "])
    
    if not is_other_sport:
        if any(kw in title_lower for kw in ["world cup", "worldcup", "piala dunia", "fifa"]) or "wc" in source_name.lower():
            is_wc = True
        elif has_match_separator:
            # Set is_wc hanya jika laga tersebut cocok dengan laga aktif World Cup dari ESPN/EPG
            is_match_wc = False
            cleaned_title_match = clean_match_name(title_lower)
            if active_wc_matches:
                for match in active_wc_matches:
                    match_lower = match.lower()
                    teams = match_lower.split(" vs ")
                    if len(teams) == 2:
                        # Cek apakah kedua nama tim terdeteksi di judul saluran
                        if (teams[0] in cleaned_title_match and teams[1] in cleaned_title_match) or \
                           (teams[0] in title_lower and teams[1] in title_lower):
                            is_match_wc = True
                            break
            is_wc = is_match_wc
            
    # FORCE OVERRIDE: Jika olahraga lain, tidak boleh masuk World Cup
    if is_other_sport:
        is_wc = False
            
    FIFA_LOGO = "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/Script/world_cup.png"
    
    if is_wc:
        group = "World Cup 2026"
        logo = FIFA_LOGO
        
        # Format nama: [Kualitas] Team A vs Team B - Channel/Source
        cleaned_title_match = clean_match_name(title)
        
        # Coba EPG match untuk penamaan otomatis dinamis
        epg_match = get_epg_match_for_channel(attrs)
        
        has_actual_match = bool(match_name) or bool(epg_match) or (cleaned_title_match != title)
        entry["has_actual_match"] = has_actual_match
        entry["source_name"] = source_name
        
        if has_actual_match:
            if match_name:
                actual_match = match_name
            elif epg_match:
                actual_match = epg_match
            else:
                actual_match = cleaned_title_match
            
            if match_name or epg_match:
                # Jika di-rename dinamis, suffix-nya adalah judul saluran asli (misal: "Toffee 1" atau "FOX ONE")
                channel_suffix = re.sub(r'\[?(fhd|hd|sd)\]?', '', title, flags=re.IGNORECASE).strip()
                # Bersihkan channel suffix agar tidak terlalu panjang di TV
                for clean_kw in ["TVRI", "SCTV", "Indosiar", "Moji", "Vidio", "Trans7", "Trans TV", "RCTI", "MNC TV"]:
                    if clean_kw.lower() in channel_suffix.lower():
                        channel_suffix = clean_kw
                        break
            else:
                # Jika judul asli sudah mengandung laga, gunakan ekstraksi cerdas
                channel_suffix = extract_channel_suffix(title, source_name)
            
            display_name = f"{res_label}{actual_match} - {channel_suffix}"
        else:
            clean_title = re.sub(r'\[?(fhd|hd|sd)\]?', '', title, flags=re.IGNORECASE).strip()
            display_name = f"{res_label}World Cup 2026 - {clean_title}"
    else:
        group = "Live Events"
        logo = None
        for sport_key, sport_img in SPORT_POSTER_MAP.items():
            if sport_key in title_lower:
                logo = sport_img
                break
        if not logo:
            orig_logo = attrs.get("tvg-logo", "")
            if orig_logo and "gyazo" not in orig_logo and "world_cup" not in orig_logo:
                logo = orig_logo
            else:
                logo = "https://a.espncdn.com/combiner/i?img=/i/teamlogos/leagues/500/all.png"
                
        if match_name:
            display_name = f"{res_label}{match_name}"
        else:
            clean_title = re.sub(r'\[?(fhd|hd|sd)\]?', '', title, flags=re.IGNORECASE).strip()
            display_name = f"{res_label}{clean_title}"
        
    attrs["group-title"] = group
    attrs["tvg-logo"] = logo
    attrs["display_name"] = display_name
    attrs["tvg-name"] = display_name
    
    entry["extinf"] = [build_extinf_line(attrs)]
    entry["is_wc"] = is_wc
    return entry


def dedup_entries_by_name(entries: list[dict]) -> tuple[list[dict], int]:
    grouped = {}
    for entry in entries:
        extinf_line = entry["extinf"][0]
        attrs = parse_extinf_attributes(extinf_line)
        name = clean_channel_name(attrs["display_name"])
        if not name:
            name = "unknown"
        grouped.setdefault(name, []).append(entry)

    unique_entries = []
    removed = 0

    for name, group in grouped.items():
        if len(group) == 1:
            unique_entries.append(group[0])
        else:
            # Urutkan duplikat: prioritas non-DRM, lalu resolusi tertinggi
            def sort_key(x):
                is_drm = 1 if ".mpd" in x["url"].lower() or any("clearkey" in line.lower() or "widevine" in line.lower() for line in x["other"]) else 0
                res = x.get("resolution", "")
                res_val = 0
                if res == "FHD":
                    res_val = 2
                elif res == "HD":
                    res_val = 1
                return (is_drm, -res_val)

            sorted_group = sorted(group, key=sort_key)
            unique_entries.append(sorted_group[0])
            removed += len(group) - 1

    return unique_entries, removed


def calculate_wc_score(entry: dict) -> int:
    """Menghitung skor prioritas untuk saluran Piala Dunia (Bahasa Indonesia/Inggris dan Resolusi)."""
    score = 0
    title = ""
    for line in entry["extinf"]:
        if line.startswith("#EXTINF"):
            parts = line.rsplit(',', 1)
            if len(parts) == 2:
                title = parts[1].lower()
                
    # Prioritas 1: Bahasa Indonesia (SCTV, Vidio, TVRI, Indosiar, Moji, dll.) selalu di atas
    if any(kw in title for kw in ["indo", "indonesia", "sctv", "vidio", "rcti", "mnc", "tvri", "indosiar", "moji", "piala dunia", "trans7", "transtv"]):
        score += 1000
        
    # Prioritas 2: Kualitas/Resolusi (FHD > HD > SD/unknown)
    res = entry.get("resolution", "")
    if res == "FHD":
        score += 300
    elif res == "HD":
        score += 200
        
    # Prioritas 3: Bahasa Inggris (dibandingkan bahasa asing lain di resolusi yang sama)
    if any(kw in title for kw in ["english", " en ", "[en]", "tsn", "espn", "fox", "astro", "supersport"]):
        score += 50
        
    return score


import urllib.parse as urlparse

def is_token_expired(url: str) -> bool:
    """Mendeteksi apakah URL memiliki token expires yang berumur sangat pendek (< 6 jam)."""
    try:
        parsed = urlparse.urlparse(url)
        query = urlparse.parse_qs(parsed.query)
        for expires_key in ["expires", "exp", "expiration"]:
            if expires_key in query:
                val = query[expires_key][0]
                if val.isdigit():
                    ts = int(val)
                    now_ts = int(datetime.now(timezone.utc).timestamp())
                    if ts - now_ts < 21600:  # 6 jam
                        return True
    except Exception:
        pass
    return False


def is_hevc_stream(preview: str) -> bool:
    """Mendeteksi apakah stream menggunakan codec HEVC (H.265) yang tidak didukung universal."""
    preview_lower = preview.lower()
    if 'codecs="' in preview_lower:
        codecs_matches = re.findall(r'codecs="([^"]+)"', preview_lower)
        for codecs in codecs_matches:
            if any(c.strip().startswith(("hvc", "hev")) for c in codecs.split(",")):
                return True
    return False


def is_drm_protected_content(preview: str, url: str) -> bool:
    """Mendeteksi apakah konten manifest terproteksi DRM."""
    preview_lower = preview.lower()
    url_lower = url.lower()
    
    # Check DASH ContentProtection
    if "<contentprotection" in preview_lower or "cenc:default_kid" in preview_lower:
        if not any(k in url_lower for k in ["key=", "token="]):
            return True
            
    # Check HLS DRM (SAMPLE-AES or urn:uuid)
    if "method=sample-aes" in preview_lower or "keyformat=\"urn:uuid" in preview_lower:
        return True
        
    return False


def fetch_live_wc_matches_from_espn() -> list[str]:
    """Mengambil pertandingan Piala Dunia yang sedang live/in-progress dari API ESPN."""
    url = "https://site.api.espn.com/apis/site/v2/sports/soccer/fifa.world/scoreboard"
    live_matches = []
    
    ENG_TO_IDN_MAP = {
        "japan": "Jepang", "sweden": "Swedia", "germany": "Jerman", 
        "ecuador": "Ekuador", "tunisia": "Tunisia", "netherlands": "Belanda",
        "paraguay": "Paraguay", "australia": "Australia", "turkey": "Turki",
        "türkiye": "Turki", "united states": "AS", "usa": "AS",
        "ivory coast": "Pantai Gading", "curacao": "Curacao", "curaçao": "Curacao",
        "spain": "Spanyol", "france": "Prancis", "england": "Inggris",
        "italy": "Italia", "portugal": "Portugal", "croatia": "Kroasia",
        "mexico": "Meksiko", "canada": "Kanada", "senegal": "Senegal",
        "morocco": "Maroko", "ghana": "Ghana", "cameroon": "Kamerun",
        "south korea": "Korsel", "korea": "Korsel", "saudi arabia": "Arab Saudi",
        "poland": "Polandia", "belgium": "Belgia", "denmark": "Denmark",
        "switzerland": "Swiss", "uruguay": "Uruguay", "argentina": "Argentina",
        "brazil": "Brasil", "colombia": "Kolombia"
    }

    try:
        print("⏳ Menghubungi API ESPN Scoreboard untuk mencari laga live...")
        r = requests.get(url, timeout=10)
        if r.status_code == 200:
            data = r.json()
            events = data.get("events", [])
            for event in events:
                status_state = event.get("status", {}).get("type", {}).get("state", "").lower()
                competitors = event.get("competitions", [{}])[0].get("competitors", [])
                if len(competitors) >= 2:
                    teams = []
                    for comp in competitors:
                        t_name = comp.get("team", {}).get("displayName", "")
                        t_name_idn = ENG_TO_IDN_MAP.get(t_name.lower(), t_name)
                        teams.append(t_name_idn)
                    
                    laga_name = f"{teams[0]} vs {teams[1]}"
                    
                    if status_state == "in":
                        live_matches.append(laga_name)
                        print(f"  [ESPN LIVE] Terdeteksi sedang berlangsung: {laga_name}")
                    elif status_state == "post":
                        FINISHED_WC_MATCHES.add(laga_name.lower())
                        # Tambahkan versi terbalik untuk pencarian aman
                        laga_name_rev = f"{teams[1]} vs {teams[0]}"
                        FINISHED_WC_MATCHES.add(laga_name_rev.lower())
                        print(f"  [ESPN POST] Laga sudah selesai: {laga_name}")
        else:
            print(f"  [WARNING] API ESPN mengembalikan HTTP {r.status_code}")
    except Exception as e:
        print(f"  [WARNING] Gagal mengambil laga live dari ESPN: {e}")
        
    return live_matches


def get_active_wc_matches(epg_active_progs: dict, stream_match_map: dict) -> list[str]:
    """Mengumpulkan daftar laga Piala Dunia aktif berdasarkan API ESPN dan EPG stasiun TV nasional."""
    matches = set()
    
    # 1. Ambil laga live secara real-time dari API ESPN Internasional
    espn_live = fetch_live_wc_matches_from_espn()
    for match in espn_live:
        matches.add(match)
        
    # 2. Ambil laga live sebagai cadangan dari EPG stasiun TV nasional Indonesia
    main_channels = ["TVRI.id", "SCTV.id", "Indosiar.id", "Moji.id", "RCTI.id"]
    for cid, title in epg_active_progs.items():
        is_main = any(mc.lower() in cid.lower() for mc in main_channels)
        if is_main and title:
            title_lower = title.lower()
            # Hanya saring jika berkaitan dengan Piala Dunia/FIFA/Sepak Bola
            is_wc_related = any(kw in title_lower for kw in ["world cup", "worldcup", "piala dunia", "fifa", "kualifikasi pd"])
            # Dan abaikan olahraga non-sepakbola yang sering disiarkan Moji/TVRI
            is_other = any(kw in title_lower for kw in [
                "voli", "volleyball", "avc", "vnl", "proliga", "basket", "basketball", 
                "badminton", "bulutangkis", "tennis", "tenis", "f1", "motogp"
            ])
            
            if is_wc_related and not is_other:
                cleaned = clean_match_name(title)
                if cleaned and cleaned != title and "vs" in cleaned.lower():
                    matches.add(cleaned)
                
    # CATATAN: JANGAN gunakan stream_match_map secara mentah untuk active matches global
    # karena stream_match_map memuat seluruh jadwal harian events.m3u8 (bukan yang sedang live saja).
    
    return list(matches)


def check_and_enrich_entry(entry: dict, is_wc: bool) -> dict:
    # 1. Cek token kedaluwarsa terlebih dahulu
    if is_token_expired(entry["url"]):
        entry["playable"] = False
        entry["is_wc"] = is_wc
        entry["resolution"] = ""
        return entry

    playable = is_stream_playable(entry["url"], entry["headers"])
    if playable:
        # Lakukan body-sniffing tunggal untuk DRM dan HEVC
        url = sanitize_url_protocol(entry["url"])
        try:
            with closing(requests.get(url, headers=entry["headers"], timeout=5, stream=True, verify=False)) as r:
                if r.status_code == 200:
                    chunk = next(r.iter_content(chunk_size=10240), b"")
                    preview = chunk.decode("utf-8", errors="ignore")
                    
                    if is_drm_protected_content(preview, url):
                        has_license = any("license_key" in line.lower() or "license_type" in line.lower() for line in entry.get("other", []) + entry.get("vlcopt", []))
                        if not has_license:
                            playable = False
                    elif is_hevc_stream(preview):
                        playable = False
        except Exception:
            playable = False
            
    entry["playable"] = playable
    entry["is_wc"] = is_wc
    
    if playable:
        res = detect_stream_resolution(entry["url"], entry["headers"])
        if not res:
            # Fallback 1: Ekstrak dari URL
            url_lower = entry["url"].lower()
            if "fhd" in url_lower or "1080p" in url_lower:
                res = "FHD"
            elif "hd" in url_lower or "720p" in url_lower:
                res = "HD"
            else:
                # Fallback 2: Ekstrak dari display-name asli di extinf
                title = ""
                for line in entry["extinf"]:
                    if line.startswith("#EXTINF"):
                        parts = line.rsplit(',', 1)
                        if len(parts) == 2:
                            title = parts[1].lower()
                if "fhd" in title or "1080" in title or "4k" in title:
                    res = "FHD"
                elif "hd" in title or "720" in title:
                    res = "HD"
                elif "sd" in title or "480" in title:
                    res = "SD"
        entry["resolution"] = res
    else:
        entry["resolution"] = ""
        
    return entry


def main():
    print("🚀 Memulai proses penggabungan & penyaringan saluran...")
    
    # Jalankan harvester kunci DRM otomatis sebelum memproses playlist
    try:
        import sys
        import subprocess
        print("🌾 Menjalankan Auto DRM Key Harvester...")
        subprocess.run([sys.executable, "discover_keys.py"], check=True)
    except Exception as e:
        print(f"⚠️ Gagal memanggil harvester kunci DRM: {e}")
    
    # Pre-pass EPG: Load EPG data to build the active programmes database
    print("⏳ Menyiapkan database EPG dari guide.xml...")
    local_xml = Path("epgs/guide.xml")
    local_gz = Path("epgs/guide.xml.gz")
    xml_data = None
    
    try:
        if local_gz.exists():
            print(f"  [EPG] Membaca EPG lokal {local_gz}...")
            with gzip.open(local_gz, "rb") as f:
                xml_data = f.read()
        elif local_xml.exists():
            print(f"  [EPG] Membaca EPG lokal {local_xml}...")
            with open(local_xml, "rb") as f:
                xml_data = f.read()
        else:
            # Fallback download remote EPG
            print(f"  [EPG] Mengunduh EPG remote dari {EPG_URL}...")
            r_epg = requests.get(EPG_URL, timeout=30, verify=False)
            if r_epg.status_code == 200:
                content = r_epg.content
                if EPG_URL.endswith(".gz"):
                    content = gzip.decompress(content)
                xml_data = content
    except Exception as e:
        print(f"  [WARNING] Gagal memuat EPG: {e}")
        
    if xml_data:
        try:
            epg_root = ET.fromstring(xml_data)
            now_utc = datetime.now(timezone.utc)
            
            for ch in epg_root.findall("channel"):
                cid = ch.get("id")
                dn = ch.find("display-name")
                EPG_CHANNEL_NAMES[cid] = dn.text if dn is not None else cid
                
            for prog in epg_root.findall("programme"):
                cid = prog.get("channel")
                start_val = prog.get("start")
                stop_val = prog.get("stop")
                if cid and start_val and stop_val:
                    start = parse_xmltv_time(start_val)
                    stop = parse_xmltv_time(stop_val)
                    if start and stop and start <= now_utc < stop:
                        title = prog.find("title").text if prog.find("title") is not None else ""
                        if cid in EPG_ACTIVE_PROGS:
                            if score_epg_title(title) > score_epg_title(EPG_ACTIVE_PROGS[cid]):
                                EPG_ACTIVE_PROGS[cid] = title
                        else:
                            EPG_ACTIVE_PROGS[cid] = title
                            
            # Bangun lookup name EPG
            for cid, epg_name in EPG_CHANNEL_NAMES.items():
                norm_name = re.sub(r'[^a-z0-9]', '', epg_name.lower())
                EPG_NAME_TO_ID[norm_name] = cid
                norm_id = re.sub(r'[^a-z0-9]', '', cid.lower())
                EPG_NAME_TO_ID[norm_id] = cid
                
            print(f"  [EPG] Berhasil memuat {len(EPG_CHANNEL_NAMES)} saluran dan {len(EPG_ACTIVE_PROGS)} program aktif.")
        except Exception as e:
            print(f"  [WARNING] Gagal mengurai EPG XML: {e}")
    
    # Pre-pass: Unduh events.m3u8 untuk membangun database laga aktif secara real-time
    print("⏳ Menyiapkan database laga aktif dari events.m3u8...")
    events_url = "https://github.com/doms9/iptv/raw/refs/heads/default/M3U8/events.m3u8"
    events_lines = fetch_playlist(events_url)
    if events_lines:
        temp_entries = parse_m3u(events_lines)
        url_to_matches_list = {}
        url_to_res_list = {}
        for entry in temp_entries:
            title = ""
            for line in entry["extinf"]:
                if line.startswith("#EXTINF"):
                    parts = line.rsplit(',', 1)
                    if len(parts) == 2:
                        title = parts[1].strip()
            match_name = clean_match_name(title)
            # Pastikan clean_match_name berhasil mendeteksi laga (artinya hasil bersih berbeda dari aslinya)
            if match_name and match_name != title:
                url_key = get_url_path_key(entry["url"])
                url_to_matches_list.setdefault(url_key, set()).add(match_name)
                
                # Deteksi resolusi
                res = ""
                title_lower = title.lower()
                url_lower = entry["url"].lower()
                if "fhd" in title_lower or "1080p" in url_lower:
                    res = "FHD"
                elif "hd" in title_lower or "720p" in url_lower:
                    res = "HD"
                if res:
                    url_to_res_list.setdefault(url_key, set()).add(res)
                    
        # Filter keluar HLS URL yang ambigu (dipakai oleh lebih dari 1 laga berbeda)
        valid_matches = 0
        for url_key, matches in url_to_matches_list.items():
            if len(matches) == 1:
                match_val = list(matches)[0]
                STREAM_MATCH_MAP[url_key] = match_val
                valid_matches += 1
                
                # Ambil resolusi jika konsisten
                res_set = url_to_res_list.get(url_key, set())
                if len(res_set) == 1:
                    STREAM_RES_MAP[url_key] = list(res_set)[0]
            else:
                print(f"  [INFO] Mengabaikan URL ambigu {url_key} karena dipakai bersama oleh laga: {matches}")
                
        print(f"✅ Berhasil memetakan {valid_matches} laga aktif unik untuk penamaan otomatis.")
    else:
        print("⚠️ Gagal mengunduh events.m3u8 untuk database laga.")

    active_wc_matches = get_active_wc_matches(EPG_ACTIVE_PROGS, STREAM_MATCH_MAP)
    print(f"📊 Laga World Cup aktif global terdeteksi saat generate: {active_wc_matches}")

    all_wc_entries = []
    all_live_entries = []

    for source in SOURCES:
        name = source["name"]
        url = source["url"]
        is_wc = source.get("is_wc", False)

        print(f"\n{'=' * 60}")
        print(f"Source: {name} (Kategori: {'World Cup/Filtered' if 'filter_groups' in source else ('World Cup' if is_wc else 'Live Events')})")
        print(f"URL   : {url}")
        print(f"{'=' * 60}")

        lines = fetch_playlist(url)
        if lines is None:
            print(f"[SKIP] {name}: tidak bisa diunduh")
            continue

        entries = parse_m3u(lines)
        print(f"Total entri awal: {len(entries)}")

        # Jika ada filter_groups, saring hanya kategori olahraga/world cup yang diinginkan
        if "filter_groups" in source:
            filtered_entries = []
            filter_map = source["filter_groups"]
            for entry in entries:
                group = "No Group"
                for line in entry["extinf"]:
                    group_match = re.search(r'group-title="([^"]+)"', line)
                    if group_match:
                        group = group_match.group(1)
                        break
                if group in filter_map:
                    entry_copy = dict(entry)
                    entry_copy["is_wc_override"] = (filter_map[group] == "wc")
                    filtered_entries.append(entry_copy)
            entries = filtered_entries
            print(f"Entri setelah difilter kategori olahraga: {len(entries)}")

        if not entries:
            continue

        entries, dup_removed = dedup_entries(entries)
        if dup_removed > 0:
            print(f"Duplikat dihapus: {dup_removed} entri")
        print(f"Entri unik      : {len(entries)}")

        print(f"Memeriksa {len(entries)} saluran secara paralel...")
        
        playable_entries = []
        with ThreadPoolExecutor(max_workers=MAX_WORKERS) as executor:
            future_to_entry = {
                executor.submit(check_and_enrich_entry, entry, entry.get("is_wc_override", is_wc)): entry
                for entry in entries
            }

            done = 0
            total = len(entries)
            for future in as_completed(future_to_entry):
                try:
                    res_entry = future.result()
                    done += 1
                    status = "OK " if res_entry["playable"] else "DEAD"
                    res_lbl = f"[{res_entry['resolution']}]" if res_entry["resolution"] else ""
                    print(f"[{done}/{total}] {status} {res_lbl} {res_entry['url']}")
                    
                    if res_entry["playable"]:
                        playable_entries.append(res_entry)
                except Exception as e:
                    print(f"Error checking entry: {e}")

        for res_entry in playable_entries:
            enriched = format_and_enrich_sports_entry(res_entry, name, active_wc_matches)
            if enriched is None:
                continue
            if enriched["is_wc"]:
                all_wc_entries.append(enriched)
            else:
                all_live_entries.append(enriched)

    # Distribusikan laga aktif ke entri Piala Dunia yang generik (round-robin)
    generics = [entry for entry in all_wc_entries if not entry.get("has_actual_match")]
    if generics and active_wc_matches:
        print(f"\nDistributing {len(active_wc_matches)} active matches to {len(generics)} generic World Cup channels (round-robin)...")
        for idx, entry in enumerate(generics):
            actual_match = active_wc_matches[idx % len(active_wc_matches)]
            
            extinf_line = entry["extinf"][0]
            attrs = parse_extinf_attributes(extinf_line)
            title = attrs["display_name"]
            
            resolution = entry.get("resolution", "")
            if not resolution:
                resolution = "HD"
            res_label = f"[{resolution}] " if resolution else ""
            
            source_name = entry.get("source_name", "SM-TV")
            channel_suffix = extract_channel_suffix(title, source_name)
            
            # Update display name
            display_name = f"{res_label}{actual_match} - {channel_suffix}"
            attrs["display_name"] = display_name
            attrs["tvg-name"] = display_name
            attrs["group-title"] = "World Cup 2026"
            attrs["tvg-logo"] = "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/Script/world_cup.png"
            
            entry["extinf"] = [build_extinf_line(attrs)]

    # Dedup antar source jika ada nama/url ganda secara pintar
    unique_wc, wc_dup_removed = dedup_entries_by_name(all_wc_entries)
    unique_live, live_dup_removed = dedup_entries_by_name(all_live_entries)
    print(f"\nDeduplikasi nama selesai: {wc_dup_removed} duplikat World Cup dibersihkan, {live_dup_removed} duplikat Live Events dibersihkan.")

    # Lakukan pengurutan prioritas untuk saluran Piala Dunia
    print("\nSorting World Cup channels by language priority (Indo/English) and resolution...")
    unique_wc = sorted(unique_wc, key=calculate_wc_score, reverse=True)

    # Gabungkan semua ke dalam satu playlist master
    output_lines = [f'#EXTM3U url-tvg="{EPG_URL}"']

    # 1. World Cup di posisi paling atas
    for entry in unique_wc:
        output_lines.extend(entry["extinf"])
        output_lines.extend(entry["other"])
        output_lines.extend(entry["vlcopt"])
        output_lines.append(entry["url"])

    # 2. Live Events di bawahnya
    for entry in unique_live:
        output_lines.extend(entry["extinf"])
        output_lines.extend(entry["other"])
        output_lines.extend(entry["vlcopt"])
        output_lines.append(entry["url"])

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    output_path = OUTPUT_DIR / "live_events.m3u"
    
    playlist_content = "\n".join(output_lines) + "\n"
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(playlist_content)

    # Simpan versi terkompresi .gz
    output_path_gz = OUTPUT_DIR / "live_events.m3u.gz"
    with gzip.open(output_path_gz, 'wb') as f_gz:
        f_gz.write(playlist_content.encode('utf-8'))

    print(f"\n{'=' * 60}")
    print("PROSES SELESAI")
    print(f"{'=' * 60}")
    print(f"  Total Saluran Piala Dunia Aktif  : {len(unique_wc)}")
    print(f"  Total Saluran Olahraga Umum Aktif: {len(unique_live)}")
    print(f"  Saved -> {output_path} & {output_path_gz}")


if __name__ == "__main__":
    main()