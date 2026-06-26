import sys
import io
import re
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

# ====================================================================
# DAFTAR SUMBER PLAYLIST
# ====================================================================
SOURCES = [
    {
        "name": "wc2026",
        "url": "https://github.com/sm-monirulislam/SM-Live-TV/raw/refs/heads/main/World_Cup.m3u",
        "is_wc": True
    },
    {
        "name": "buddy_sport",
        "url": "https://github.com/BuddyChewChew/storage/raw/main/sport.m3u",
        "is_wc": True
    },
    {
        "name": "live_events",
        "url": "https://github.com/doms9/iptv/raw/refs/heads/default/M3U8/events.m3u8",
        "is_wc": False
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
    try:
        response = requests.get(url, timeout=30, verify=False)
        response.raise_for_status()
        return [line.rstrip() for line in response.text.splitlines()]
    except requests.RequestException as e:
        print(f"  [ERROR] Gagal fetch source: {e}")
        return None


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
    "soccer": "https://a.espncdn.com/combiner/i?img=/i/leaguelogos/soccer/500/4.png",
    "football": "https://a.espncdn.com/combiner/i?img=/i/leaguelogos/soccer/500/4.png",
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
    
    # 2. Hapus VNL, Week, dll.
    title_clean = re.sub(r'\|\s*Week\s*\d+\s*\|.*', '', title_clean, flags=re.IGNORECASE)
    
    # 3. Cari match "vs" atau "v" atau "at"
    match = re.search(r'([A-Za-z\s\-\.]+)\s+(vs|v|at)\s+([A-Za-z\s\-\.]+)', title_clean, re.IGNORECASE)
    if match:
        team1 = match.group(1).strip()
        team2 = match.group(3).strip()
        # Bersihkan kata-kata sampah
        team1 = re.sub(r'^[\[\s]*[A-Za-z\s]+\s*\]', '', team1).strip() # [WNBA], [Baseball]
        team2 = re.sub(r'\(.*?\)', '', team2).strip() # (CDNTV)
        team2 = re.sub(r'\|.*', '', team2).strip()
        team1 = re.sub(r'\s+', ' ', team1)
        team2 = re.sub(r'\s+', ' ', team2)
        return f"{team1} vs {team2}"
    
    return title.strip()


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


def format_and_enrich_sports_entry(entry: dict, source_name: str) -> dict:
    extinf_line = entry["extinf"][0]
    attrs = parse_extinf_attributes(extinf_line)
    title = attrs["display_name"]
    title_lower = title.lower()
    
    resolution = entry.get("resolution", "")
    res_label = f"[{resolution}] " if resolution else ""
    
    # Klasifikasi World Cup vs Live Events
    is_wc = entry.get("is_wc", False)
    is_other_sport = any(kw in title_lower for kw in ["vnl", "volleyball", "baseball", "mlb", "motogp", "wnba", "basketball", "f1", "formula 1", "serie b"])
    
    if not is_other_sport:
        if any(kw in title_lower for kw in ["world cup", "worldcup", "piala dunia", "fifa"]) or "wc" in source_name.lower():
            is_wc = True
        elif "vs" in title_lower or " v " in title_lower:
            is_wc = True
            
    FIFA_LOGO = "https://raw.githubusercontent.com/sm-monirulislam/SM-Live-TV/main/Script/world_cup.png"
    
    if is_wc:
        group = "World Cup 2026"
        logo = FIFA_LOGO
        
        # Format nama: [Kualitas] Team A vs Team B - Channel/Source
        if "vs" in title_lower or " v " in title_lower:
            match_name = clean_match_name(title)
            clean_source = source_name.replace("_sports", "").replace("buddy_", "").replace("wc2026", "SM-TV").upper()
            display_name = f"{res_label}{match_name} - {clean_source}"
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
                
    # Prioritas Bahasa Indonesia (SCTV, Vidio, Indo, dll.)
    if any(kw in title for kw in ["indo", "indonesia", "sctv", "vidio", "rcti", "mnc"]):
        score += 100
    # Prioritas Bahasa Inggris
    elif any(kw in title for kw in ["english", " en ", "[en]", "tsn", "espn", "fox", "astro", "supersport"]):
        score += 50
        
    # Skor tambahan untuk resolusi tinggi
    res = entry.get("resolution", "")
    if res == "FHD":
        score += 20
    elif res == "HD":
        score += 10
        
    return score


def check_and_enrich_entry(entry: dict, is_wc: bool) -> dict:
    playable = is_stream_playable(entry["url"], entry["headers"])
    entry["playable"] = playable
    entry["is_wc"] = is_wc
    
    if playable:
        res = detect_stream_resolution(entry["url"], entry["headers"])
        entry["resolution"] = res
    else:
        entry["resolution"] = ""
        
    return entry


def main():
    print("🚀 Memulai proses penggabungan & penyaringan saluran...")
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
            enriched = format_and_enrich_sports_entry(res_entry, name)
            if enriched["is_wc"]:
                all_wc_entries.append(enriched)
            else:
                all_live_entries.append(enriched)

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
    import gzip
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