import os
import gzip
import re
import sys
import io
import requests
import urllib3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Nonaktifkan peringatan SSL tidak aman
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Pastikan stdout/stderr menggunakan UTF-8 di terminal Windows untuk menghindari UnicodeEncodeError
if sys.platform.startswith('win'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

OUTPUT_DIR = "playlists"
OUTPUT_FILE = os.path.join(OUTPUT_DIR, "indo_extras.m3u")

SOURCES = {
    "dhanytv": "https://raw.githubusercontent.com/dhasap/dhanytv/main/dhanytv.m3u",
    "windozalmi": "https://raw.githubusercontent.com/windozalmi/Playlist-IPTV-Indonesia-online-Aktif-2025/refs/heads/m3u/IPTV%20Indonesia%20by%20WINDO%20ZALMI",
    "basictv": "https://gist.githubusercontent.com/R03nDL03n1/6361525c226ccc713f48e7fea5399df4/raw/d4443e16c36c8b73cfb028e5b771b870d5695f55/BasicTVStandar"
}

# Pemetaan kategori dari playlist luar ke kategori standar kita
GROUP_MAPPING = {
    # Nasional
    "indonesia channels": "Nasional",
    "indonesia tv": "Nasional",
    "nasional": "Nasional",
    "national": "Nasional",
    "tv nasional (by: windo zalmi)": "Nasional",
    "vision+": "Nasional",
    "vidio": "Nasional",
    "denstv": "Nasional",
    "biznet tv": "Nasional",
    
    # Daerah
    "local channels": "Daerah",
    "tvri": "Daerah",
    "daerah": "Daerah",
    
    # Religi
    "religion": "Religi",
    "religi": "Religi",
    "islam": "Religi",
    "christian": "Religi",
    
    # Movies
    "movies tv": "Movies",
    "movies": "Movies",
    "hbo group": "Movies",
    "max group": "Movies",
    "premium movies": "Movies",
    "movies & entertainment": "Movies",
    "vod indo": "Movies",
    
    # Kids
    "kids tv": "Kids",
    "kids": "Kids",
    "kids channel": "Kids",
    "family & kids": "Kids",
    
    # Entertainment
    "entertainment": "Entertainment",
    "variety": "Entertainment",
    
    # News
    "news tv": "News",
    "news": "News",
    
    # Music
    "music tv": "Music",
    "music": "Music",
    
    # Knowledge
    "knowledge": "Knowledge",
    "documentary": "Knowledge",
}

# Normalisasi tvg-id populer agar cocok dengan EPG XML
TVG_ID_MAP = {
    "btv": "BTV.id@SD",
    "cnbc indonesia": "CNBCIndonesia.id@SD",
    "cnn indonesia": "CNNIndonesia.id@SD",
    "idx channel": "IDXChannel.id@SD",
    "indosiar": "Indosiar.id@SD",
    "kompas tv": "KompasTV.id@SD",
    "mdtv": "MDTV.id@HD",
    "metro tv": "MetroTV.id@SD",
    "moji": "Moji.id@SD",
    "sctv": "SCTV.id@SD",
    "sin po tv": "SinPoTV.id@HD",
    "sinpotv": "SinPoTV.id@HD",
    "sindonews": "SindoNewsTV.id@SD",
    "sindonews tv": "SindoNewsTV.id@SD",
    "trans7": "Trans7.id@SD",
    "trans 7": "Trans7.id@SD",
    "transtv": "TransTV.id@SD",
    "trans tv": "TransTV.id@SD",
    "tvone": "tvOne.id@SD",
    "tv one": "tvOne.id@SD",
    "tvri world": "TVRIWorld.id@SD",
    "antara tv": "AntaraTV.id@SD",
    "bali tv": "BaliTV.id@SD",
    "channel jowo": "ChannelJowo.id@SD",
    "daai tv": "DAAITV.id@SD",
    "elshinta tv": "ElshintaTV.id@SD",
    "garuda tv": "GarudaTV.id@SD",
    "jaktv": "JakTV.id@SD",
    "jak tv": "JakTV.id@SD",
    "jawapos tv": "JawaPosTV.id@SD",
    "jawa pos tv": "JawaPosTV.id@SD",
    "jtv": "JTV.id@SD",
    "magna channel": "MagnaChannel.id@SD",
    "rodja tv": "RodjaTV.id@SD",
    "sunna tv": "AlSunnahAlNabawiyahTV.sa@SD",
    "berita satu": "BeritaSatu.id@SD",
    "nusantara tv": "NusantaraTV.id@SD",
    "rtv": "RajawaliTV.id@SD",
    "tvri": "TVRI.id@SD",
    "gtv": "GTV.id@SD",
    "inews": "iNews.id@SD",
    "mnctv": "MNCTV.id@SD",
    "rcti": "RCTI.id@SD",
}

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


def clean_category_name(group: str) -> str:
    return group.strip().lower()


def standardize_extinf(extinf_line: str, display_name: str, mapped_group: str) -> str:
    clean_name = display_name.strip().lower()
    
    # 1. Tentukan tvg-id yang benar
    tvg_id = ""
    # Cari kecocokan exact/substring di TVG_ID_MAP
    for name_key, tid in TVG_ID_MAP.items():
        if name_key in clean_name:
            tvg_id = tid
            break
            
    # 2. Update tvg-id di baris extinf
    if tvg_id:
        if 'tvg-id="' in extinf_line:
            extinf_line = re.sub(r'tvg-id="[^"]*"', f'tvg-id="{tvg_id}"', extinf_line)
        else:
            extinf_line = extinf_line.replace('#EXTINF:-1 ', f'#EXTINF:-1 tvg-id="{tvg_id}" ')
            
    # 3. Update group-title di baris extinf
    if 'group-title="' in extinf_line:
        extinf_line = re.sub(r'group-title="[^"]*"', f'group-title="{mapped_group}"', extinf_line)
    else:
        extinf_line = extinf_line.replace('#EXTINF:-1 ', f'#EXTINF:-1 group-title="{mapped_group}" ')
        
    return extinf_line


def sanitize_url_protocol(url: str) -> str:
    """Mengubah https ke http untuk port non-standar untuk menghindari jabat tangan SSL gagal."""
    match = re.search(r'https://([^:/]+):(\d+)', url)
    if match:
        port = int(match.group(2))
        if port in (8080, 8000, 8070, 25461, 9080, 9090, 80, 3000, 19360):
            url = url.replace("https://", "http://", 1)
    return url


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


def ping_stream(url: str, headers: dict = None) -> bool:
    from contextlib import closing
    headers = headers or {'User-Agent': 'Mozilla/5.0'}
    url = sanitize_url_protocol(url)
    url_lower = url.lower()
    
    # Jika URL berupa manifest, lakukan GET untuk sniff DRM
    is_manifest = any(ext in url_lower for ext in [".mpd", ".m3u8", "cenc", "manifest"])
    if is_manifest:
        try:
            with closing(requests.get(url, headers=headers, timeout=5, stream=True, verify=False, allow_redirects=True)) as r:
                if r.status_code == 200:
                    chunk = next(r.iter_content(chunk_size=10240), b"")
                    preview = chunk.decode("utf-8", errors="ignore")
                    if is_drm_protected_content(preview, url):
                        return False
                    return True
        except requests.exceptions.SSLError:
            if url.startswith("https://"):
                return ping_stream(url.replace("https://", "http://", 1), headers)
        except Exception:
            pass
        return False
        
    # 1. Coba HEAD request (untuk berkas video/stream langsung biasa)
    try:
        r = requests.head(url, headers=headers, timeout=5, verify=False, allow_redirects=True)
        if r.status_code < 400:
            content_type = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
            if content_type in VALID_CONTENT_TYPES or not content_type:
                return True
    except requests.exceptions.SSLError:
        if url.startswith("https://"):
            return ping_stream(url.replace("https://", "http://", 1), headers)
    except Exception:
        pass
        
    # 2. Fallback ke GET minimal
    try:
        with closing(requests.get(url, headers=headers, timeout=5, verify=False, stream=True, allow_redirects=True)) as r:
            if r.status_code < 400:
                content_type = r.headers.get("Content-Type", "").split(";")[0].strip().lower()
                if content_type in VALID_CONTENT_TYPES or not content_type:
                    return True
    except requests.exceptions.SSLError:
        if url.startswith("https://"):
            return ping_stream(url.replace("https://", "http://", 1), headers)
    except Exception:
        pass
        
    return False


def parse_m3u_to_streams(content: str, source_name: str) -> list[dict]:
    streams = []
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('#EXTINF'):
            extinf = line
            opts = []
            i += 1
            while i < len(lines) and (lines[i].startswith('#EXTVLCOPT') or lines[i].startswith('#EXTGRP')):
                opts.append(lines[i])
                i += 1
            if i < len(lines) and lines[i].strip() and not lines[i].startswith('#'):
                url = sanitize_url_protocol(lines[i].strip())
                
                # Ekstrak display name
                display_name = "Unknown"
                parts = extinf.rsplit(',', 1)
                if len(parts) == 2:
                    display_name = parts[1].strip()
                
                # Ekstrak group-title
                group = "Other"
                group_match = re.search(r'group-title="([^"]+)"', extinf)
                if group_match:
                    group = group_match.group(1)
                
                # Cek apakah kategori masuk ke pemetaan target
                clean_group = clean_category_name(group)
                mapped_group = None
                for key, val in GROUP_MAPPING.items():
                    if key == clean_group:
                        mapped_group = val
                        break
                
                # Jika masuk kategori target, simpan
                if mapped_group:
                    streams.append({
                        "display_name": display_name,
                        "extinf": extinf,
                        "opts": opts,
                        "url": url,
                        "group": mapped_group,
                        "source": source_name
                    })
        i += 1
    return streams


def main():
    print("🚀 Memulai proses pengumpulan Saluran TV Tambahan Indonesia...")
    
    # 1. Unduh dan parse playlist eksternal
    all_raw_streams = []
    for name, url in SOURCES.items():
        print(f"📖 Mengunduh {name}...")
        try:
            r = requests.get(url, timeout=20, verify=False)
            if r.status_code == 200:
                streams = parse_m3u_to_streams(r.text, name)
                all_raw_streams.extend(streams)
                print(f"   -> Ditemukan {len(streams)} saluran relevan dari {name}.")
            else:
                print(f"   [ERROR] Gagal unduh {name}: HTTP {r.status_code}")
        except Exception as e:
            print(f"   [ERROR] Gagal unduh {name}: {e}")
            
    if not all_raw_streams:
        print("❌ Tidak ada saluran yang berhasil dikumpulkan. Proses dihentikan.")
        return
        
    print(f"\nTotal Saluran Terkumpul Sebelum Tes: {len(all_raw_streams)}")
    
    # 2. Deduplikasi awal berdasarkan URL sebelum ping untuk menghemat waktu
    unique_streams_map = {}
    for ch in all_raw_streams:
        url = ch["url"]
        if url not in unique_streams_map:
            unique_streams_map[url] = ch
            
    unique_streams = list(unique_streams_map.values())
    print(f"Total Saluran Unik (berdasarkan URL) untuk di-ping: {len(unique_streams)}")
    
    # 3. Jalankan pengujian playability (ping) secara paralel
    print("⚡ Memulai pengujian playability paralel...")
    playable_channels = []
    
    # Ekstrak header VLC jika ada
    def get_vlc_headers(opts):
        headers = {'User-Agent': 'Mozilla/5.0'}
        for opt in opts:
            if opt.startswith("#EXTVLCOPT:"):
                kv = opt[len("#EXTVLCOPT:"):].split("=", 1)
                if len(kv) == 2:
                    k, v = kv
                    k = k.lower()
                    if k == "http-referrer":
                        headers["Referer"] = v
                    elif k == "http-origin":
                        headers["Origin"] = v
                    elif k == "http-user-agent":
                        headers["User-Agent"] = v
        return headers

    with ThreadPoolExecutor(max_workers=16) as executor:
        future_to_ch = {
            executor.submit(ping_stream, ch["url"], get_vlc_headers(ch["opts"])): ch
            for ch in unique_streams
        }
        
        done = 0
        total = len(unique_streams)
        for future in as_completed(future_to_ch):
            ch = future_to_ch[future]
            done += 1
            try:
                is_ok = future.result()
                status = "OK " if is_ok else "DEAD"
                print(f"[{done}/{total}] {status} | {ch['display_name']} ({ch['source']})")
                if is_ok:
                    playable_channels.append(ch)
            except Exception as e:
                print(f"[{done}/{total}] ERROR | {ch['display_name']} - {e}")
                
    print(f"\n✅ Pengujian Selesai! {len(playable_channels)} dari {len(unique_streams)} saluran aktif.")
    
    # 4. Tulis hasil ke indo_extras.m3u dan versi .gz
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    
    output_lines = ["#EXTM3U\n"]
    for ch in playable_channels:
        # Standardize extinf (tvg-id & group-title)
        std_extinf = standardize_extinf(ch["extinf"], ch["display_name"], ch["group"])
        output_lines.append(std_extinf)
        output_lines.extend(ch["opts"])
        output_lines.append(ch["url"])
        output_lines.append("")
        
    playlist_content = "\n".join(output_lines) + "\n"
    
    with open(OUTPUT_FILE, "w", encoding="utf-8") as f:
        f.write(playlist_content)
        
    gz_file = OUTPUT_FILE + ".gz"
    with gzip.open(gz_file, "wb") as f_gz:
        f_gz.write(playlist_content.encode("utf-8"))
        
    print(f"💾 Berkas berhasil disimpan di {OUTPUT_FILE} & {gz_file}")


if __name__ == "__main__":
    main()
