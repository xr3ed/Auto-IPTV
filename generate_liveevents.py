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


def is_stream_playable(url: str, headers: dict = None) -> bool:
    headers = headers or {}

    # 1. Coba HEAD request dulu (efisien) - bypass SSL verify
    try:
        response = requests.head(
            url, headers=headers, timeout=TIMEOUT, allow_redirects=True, verify=False
        )
        if response.status_code < 400:
            content_type = response.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type in VALID_CONTENT_TYPES:
                return True
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

    except requests.RequestException:
        return False


def detect_stream_resolution(url: str, headers: dict = None) -> str:
    """Mengunduh chunk awal manifest .m3u8 untuk menganalisis resolusi stream secara dinamis."""
    headers = headers or {}
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
            url = stripped

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


def enrich_extinf(extinf_line: str, resolution: str, is_wc: bool) -> str:
    """Mengubah group-title dan menambahkan resolusi ke dalam baris #EXTINF."""
    group = "World Cup 2026" if is_wc else "Live Events"
    
    # Ganti group-title
    if 'group-title="' in extinf_line:
        extinf_line = re.sub(r'group-title="[^"]+"', f'group-title="{group}"', extinf_line)
    else:
        extinf_line = extinf_line.replace('#EXTINF:-1 ', f'#EXTINF:-1 group-title="{group}" ')
        
    # Sisipkan label resolusi
    if resolution in ("FHD", "HD"):
        label = f"[{resolution}] "
        extinf_line = re.sub(r'tvg-name="([^"]+)"', r'tvg-name="' + label + r'\1"', extinf_line)
        parts = extinf_line.rsplit(',', 1)
        if len(parts) == 2:
            extinf_line = f"{parts[0]},{label}{parts[1]}"
            
    return extinf_line


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
        # Deteksi resolusi jika playable
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
        is_wc = source["is_wc"]

        print(f"\n{'=' * 60}")
        print(f"Source: {name} (Kategori: {'World Cup' if is_wc else 'Live Events'})")
        print(f"URL   : {url}")
        print(f"{'=' * 60}")

        lines = fetch_playlist(url)
        if lines is None:
            print(f"[SKIP] {name}: tidak bisa diunduh")
            continue

        entries = parse_m3u(lines)
        print(f"Total entri awal: {len(entries)}")

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
                executor.submit(check_and_enrich_entry, entry, is_wc): entry
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

        if is_wc:
            all_wc_entries.extend(playable_entries)
        else:
            all_live_entries.extend(playable_entries)

    # Dedup antar source jika ada url ganda
    unique_wc, _ = dedup_entries(all_wc_entries)
    unique_live, _ = dedup_entries(all_live_entries)

    # Lakukan pengurutan prioritas untuk saluran Piala Dunia
    print("\nSorting World Cup channels by language priority (Indo/English) and resolution...")
    unique_wc = sorted(unique_wc, key=calculate_wc_score, reverse=True)

    # Gabungkan semua ke dalam satu playlist master
    output_lines = [f'#EXTM3U url-tvg="{EPG_URL}"']

    # 1. World Cup di posisi paling atas
    for entry in unique_wc:
        enriched_extinf = [enrich_extinf(line, entry["resolution"], is_wc=True) for line in entry["extinf"]]
        output_lines.extend(enriched_extinf)
        output_lines.extend(entry["other"])
        output_lines.extend(entry["vlcopt"])
        output_lines.append(entry["url"])

    # 2. Live Events di bawahnya
    for entry in unique_live:
        enriched_extinf = [enrich_extinf(line, entry["resolution"], is_wc=False) for line in entry["extinf"]]
        output_lines.extend(enriched_extinf)
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