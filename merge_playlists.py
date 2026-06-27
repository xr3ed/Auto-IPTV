import os
import gzip
import re
import sys
import io
import time
import requests
import urllib3
from datetime import datetime
from concurrent.futures import ThreadPoolExecutor, as_completed

# Bungkam peringatan keamanan SSL/TLS urllib3 secara global
urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

# Pastikan stdout/stderr menggunakan UTF-8 di terminal Windows untuk menghindari UnicodeEncodeError
if sys.platform.startswith('win'):
    try:
        sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding='utf-8')
        sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding='utf-8')
    except Exception:
        pass

OUTPUT_DIR = "playlists"
INDIHOME_FILE = "IndihomeTV.m3u"

# Daftar playlist target dan kelompok platformnya (tanpa live_events.m3u)
PLAYLISTS_TO_MERGE = [
    {"file": "indo_extras.m3u", "section": "INDO_EXTRAS"},
    {"file": "bittv_indo.m3u", "section": "BITTV_INDO"},
    {"file": "rctiplus.m3u", "section": "RCTI+"},
    {"file": "tcl.m3u", "section": "TCL"},
    {"file": "roku.m3u", "section": "ROKU"},
    {"file": "pluto_all.m3u", "section": "PLUTO"},
    {"file": "samsungtvplus_all.m3u", "section": "SAMSUNGTV+"},
]


def clean_channel_name(display_name: str) -> str:
    """Membersihkan nama saluran untuk mendeteksi duplikat secara case-insensitive & space-insensitive."""
    name = display_name.strip().lower()
    # Hapus label resolusi seperti [hd], [fhd], [sd]
    name = re.sub(r'\[?(fhd|hd|sd)\]?', '', name)
    # Hapus spasi dan karakter non-alphanumeric dasar
    name = re.sub(r'[^a-z0-9]', '', name)
    return name


def extract_streams_from_content(content: str, source_name: str) -> list[dict]:
    """Mengurai konten M3U menjadi daftar objek saluran."""
    streams = []
    lines = content.split('\n')
    i = 0
    while i < len(lines):
        line = lines[i]
        if line.startswith('#EXTINF'):
            extinf = line
            opts = []
            i += 1
            # Kumpulkan opsi VLC
            while i < len(lines) and lines[i].startswith('#') and not lines[i].startswith('#EXTINF'):
                opts.append(lines[i].strip())
                i += 1
            # Kumpulkan URL
            if i < len(lines) and lines[i].strip() and not lines[i].startswith('#'):
                url = lines[i].strip()
                
                # Ekstrak display name (tampilan setelah koma terakhir)
                display_name = ""
                parts = extinf.rsplit(',', 1)
                if len(parts) == 2:
                    display_name = parts[1].strip()
                else:
                    display_name = "Unknown"

                # Ekstrak group-title
                group = "Other"
                group_match = re.search(r'group-title="([^"]+)"', extinf)
                if group_match:
                    group = group_match.group(1)

                from utils import enrich_stream_with_drm_keys
                opts = enrich_stream_with_drm_keys(url, opts)

                streams.append({
                    "display_name": display_name,
                    "clean_name": clean_channel_name(display_name),
                    "extinf": extinf,
                    "opts": opts,
                    "url": url,
                    "group": group,
                    "source": source_name
                })
        i += 1
    return streams


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


def ping_stream(url: str, headers: dict = None, opts: list = None) -> tuple[str, bool, float]:
    """Melakukan pengujian HTTP HEAD/GET untuk mengecek status, DRM, dan response time stream."""
    from contextlib import closing
    from utils import should_bypass_ping
    import time
    import random
    
    if should_bypass_ping(url):
        return url, True, 0.05
        
    # Jeda acak (jitter) untuk menghindari pembatasan rate limit 429
    time.sleep(random.uniform(0.1, 0.5))
    
    headers = headers or {'User-Agent': 'Mozilla/5.0'}
    url = sanitize_url_protocol(url)
    url_lower = url.lower()
    opts = opts or []
    
    start_time = datetime.now()
    is_manifest = any(ext in url_lower for ext in [".mpd", ".m3u8", "cenc", "manifest"])
    
    if is_manifest:
        try:
            with closing(requests.get(url, headers=headers, timeout=5, stream=True, verify=False, allow_redirects=True)) as r:
                if r.status_code == 200:
                    chunk_sz = 102400 if is_manifest else 10240
                    chunk = next(r.iter_content(chunk_size=chunk_sz), b"")
                    preview = chunk.decode("utf-8", errors="ignore")
                    
                    # 1. Pastikan respons bukan berupa halaman web HTML (seperti Internet Positif atau portal iklan)
                    preview_lower = preview.lower().strip()
                    if "<html" in preview_lower or "<!doctype html" in preview_lower:
                        return url, False, 999.0
                        
                    # 2. Validasi format manifes untuk menghindari link palsu
                    if ".m3u8" in url_lower:
                        if "#EXTM3U" not in preview:
                            return url, False, 999.0
                    elif ".mpd" in url_lower:
                        if "<MPD" not in preview and "<mpd" not in preview:
                            return url, False, 999.0
                            
                    # 3. Validasi perlindungan DRM
                    if is_drm_protected_content(preview, url):
                        # Cek apakah ada opsi lisensi DRM di opts
                        has_license = any("license_key" in opt.lower() or "license_type" in opt.lower() for opt in opts) if opts else False
                        if not has_license:
                            return url, False, 999.0
                            
                    latency = (datetime.now() - start_time).total_seconds()
                    return url, True, latency
        except Exception:
            pass
        return url, False, 999.0

    # 1. Coba HEAD request (untuk non-manifest)
    try:
        r = requests.head(url, headers=headers, timeout=5, verify=False, allow_redirects=True)
        if r.status_code < 400:
            latency = (datetime.now() - start_time).total_seconds()
            return url, True, latency
    except Exception:
        pass
    
    # 2. Fallback ke GET minimal
    try:
        with closing(requests.get(url, headers=headers, timeout=5, verify=False, stream=True, allow_redirects=True)) as r:
            if r.status_code < 400:
                latency = (datetime.now() - start_time).total_seconds()
                return url, True, latency
    except Exception:
        pass
        
    return url, False, 999.0


def deduplicate_channels_smart(channels: list[dict]) -> list[dict]:
    """Menguji seluruh saluran secara paralel, menyaring yang mati/DRM, dan memilih alternatif tercepat untuk duplikat."""
    print("🧠 Memulai pembersihan DRM dan Deduplikasi Pintar...")
    
    if not channels:
        return []
        
    # Kumpulkan semua URL unik beserta opsi mereka untuk diuji secara paralel
    url_to_opts = {}
    for ch in channels:
        url_to_opts[ch["url"]] = ch["opts"]
        
    print(f"  -> Menguji {len(url_to_opts)} URL unik secara paralel...")
    
    # Jalankan pengujian ping secara paralel
    url_results = {}
    with ThreadPoolExecutor(max_workers=32) as executor:
        futures = {
            executor.submit(ping_stream, url, opts=opts): url 
            for url, opts in url_to_opts.items()
        }
        for future in as_completed(futures):
            url = futures[future]
            try:
                res_url, playable, latency = future.result()
                url_results[res_url] = {"playable": playable, "latency": latency}
            except Exception as e:
                print(f"Error testing URL {url}: {e}")
                url_results[url] = {"playable": False, "latency": 999.0}

    # Saring hanya saluran yang playable
    playable_channels = []
    for ch in channels:
        res = url_results.get(ch["url"], {"playable": False, "latency": 999.0})
        if res["playable"]:
            ch["latency"] = res["latency"]
            playable_channels.append(ch)
            
    print(f"  -> Penyaringan selesai. Saluran aktif: {len(playable_channels)} dari {len(channels)}")

    # Kelompokkan saluran yang playable berdasarkan clean_name untuk deduplikasi
    grouped = {}
    for ch in playable_channels:
        name = ch["clean_name"]
        if not name:
            name = "unknown"
        grouped.setdefault(name, []).append(ch)

    final_channels = []
    for name, group in grouped.items():
        if len(group) == 1:
            final_channels.append(group[0])
        else:
            # Urutkan: prioritas latency terkecil
            sorted_group = sorted(group, key=lambda x: x["latency"])
            best_channel = sorted_group[0]
            print(f"  [PILIH DUP] {best_channel['display_name']} ({best_channel['source']}) - Latency: {best_channel['latency']:.2f}s")
            final_channels.append(best_channel)

    return final_channels


def fix_missing_local_logo(extinf_line: str) -> str:
    """Jika logo merujuk ke folder logo lokal tapi berkas fisiknya tidak ada, alihkan ke logo default Indihome."""
    match = re.search(r'tvg-logo="https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/([^"]+)"', extinf_line)
    if match:
        filename = match.group(1)
        local_path = os.path.join("logo", filename)
        if not os.path.exists(local_path):
            default_logo = "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/logo-indihome-tsel-og-default.png"
            extinf_line = re.sub(
                r'tvg-logo="https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/[^"]+"',
                f'tvg-logo="{default_logo}"',
                extinf_line
            )
    return extinf_line


def merge_all_to_indihome():
    print("🔗 Memulai penggabungan dan pembersihan terpadu ke IndihomeTV.m3u...")
    
    # Jalankan harvester kunci DRM otomatis sebelum memproses playlist
    try:
        import subprocess
        print("🌾 Menjalankan Auto DRM Key Harvester...")
        subprocess.run([sys.executable, "discover_keys.py"], check=True)
    except Exception as e:
        print(f"⚠️ Gagal memanggil harvester kunci DRM: {e}")
    
    # 1. Muat playlist master bawaan yang ada (original)
    indihome_path = INDIHOME_FILE
    original_channels = []
    
    if os.path.exists(indihome_path):
        print(f"📖 Memuat saluran bawaan dari {indihome_path}...")
        with open(indihome_path, 'r', encoding='utf-8') as f:
            content = f.read()
        
        # Bersihkan section otomatis lama agar tidak ditumpuk
        for p_info in PLAYLISTS_TO_MERGE:
            section_name = p_info["section"]
            marker_start = f"# === {section_name} SECTION ==="
            marker_end = f"# === END {section_name} SECTION ==="
            if marker_start in content and marker_end in content:
                pattern = rf'{re.escape(marker_start)}.*?{re.escape(marker_end)}'
                content = re.sub(pattern, '', content, flags=re.DOTALL)

        raw_original = extract_streams_from_content(content, "IndihomeTV (Bawaan)")
        # Saring agar saluran olahraga (World Cup & Live Events) tidak ikut masuk ke master playlist
        original_channels = [ch for ch in raw_original if ch["group"] not in ("World Cup 2026", "Live Events")]
        print(f"  -> Memuat {len(original_channels)} saluran bawaan asli (disaring dari {len(raw_original)}).")
    
    # 2. Muat saluran dari seluruh playlist pendukung di folder playlists/
    merged_sections = {}
    for p_info in PLAYLISTS_TO_MERGE:
        filename = p_info["file"]
        section_name = p_info["section"]
        filepath = os.path.join(OUTPUT_DIR, filename)
        
        if not os.path.exists(filepath):
            continue
            
        with open(filepath, 'r', encoding='utf-8') as f:
            p_content = f.read()
            
        streams = extract_streams_from_content(p_content, filename)
        if streams:
            merged_sections[section_name] = streams
            print(f"  -> Memuat {len(streams)} saluran dari {filename} ({section_name}).")

    # 3. Kumpulkan semua saluran untuk dideduplikasi secara global
    all_channels_to_dedup = list(original_channels)
    for section_streams in merged_sections.values():
        all_channels_to_dedup.extend(section_streams)

    # Jalankan deduplikasi pintar
    deduped_channels = deduplicate_channels_smart(all_channels_to_dedup)

    # Jalankan pengujian playability paralel hanya untuk saluran FAST TV yang digabungkan
    print("⚡ Memverifikasi keaktifan saluran FAST TV gabungan secara paralel...")
    from concurrent.futures import ThreadPoolExecutor, as_completed
    from utils import is_stream_playable
    
    fast_tv_channels = [ch for ch in deduped_channels if ch["source"] in ("tcl.m3u", "roku.m3u", "pluto_all.m3u", "samsungtvplus_all.m3u")]
    other_channels = [ch for ch in deduped_channels if ch["source"] not in ("tcl.m3u", "roku.m3u", "pluto_all.m3u", "samsungtvplus_all.m3u")]
    
    playable_fast_tv = []
    
    def test_fast_channel(ch):
        headers = {
            "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }
        if is_stream_playable(ch["url"], headers):
            return ch
        return None
        
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {executor.submit(test_fast_channel, ch): ch for ch in fast_tv_channels}
        for future in as_completed(futures):
            try:
                res = future.result()
                if res:
                    playable_fast_tv.append(res)
            except Exception:
                pass
                
    print(f"✅ Selesai! {len(playable_fast_tv)} dari {len(fast_tv_channels)} saluran FAST TV aktif.")
    deduped_channels = other_channels + playable_fast_tv

    # 4. Tulis kembali seluruh saluran yang unik ke IndihomeTV.m3u
    # Pisahkan saluran yang lolos filter kembali ke kelompoknya semula
    deduped_original = [ch for ch in deduped_channels if ch["source"] == "IndihomeTV (Bawaan)"]
    
    output_content = [f'#EXTM3U url-tvg="https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/epgs/guide.xml.gz"\n']
    
    # Tulis saluran bawaan asli terlebih dahulu
    for ch in deduped_original:
        extinf_line = ch["extinf"]
        extinf_line = re.sub(r'group-title="[Ss]ports"', 'group-title="Sport"', extinf_line)
        extinf_line = extinf_line.replace(
            "https://raw.githubusercontent.com/apistech/project/refs/heads/main/logo/",
            "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/"
        ).replace(
            "https://raw.githubusercontent.com/apistech/project/main/logo/",
            "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/"
        )
        extinf_line = fix_missing_local_logo(extinf_line)
        output_content.append(extinf_line)
        output_content.extend(ch["opts"])
        output_content.append(ch["url"])
        output_content.append("")

    # Tulis setiap kelompok platform secara terpisah dengan section marker
    for p_info in PLAYLISTS_TO_MERGE:
        filename = p_info["file"]
        section_name = p_info["section"]
        
        # Ambil saluran unik yang terpilih yang berasal dari file ini
        ch_in_section = [ch for ch in deduped_channels if ch["source"] == filename]
        
        if not ch_in_section:
            continue
            
        marker_start = f"# === {section_name} SECTION ==="
        marker_end = f"# === END {section_name} SECTION ==="
        
        section_lines = [
            marker_start,
            f"# Updated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
            f"# Total Saluran: {len(ch_in_section)}",
            ""
        ]
        
        for ch in ch_in_section:
            extinf_line = ch["extinf"]
            extinf_line = re.sub(r'group-title="[Ss]ports"', 'group-title="Sport"', extinf_line)
            extinf_line = extinf_line.replace(
                "https://raw.githubusercontent.com/apistech/project/refs/heads/main/logo/",
                "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/"
            ).replace(
                "https://raw.githubusercontent.com/apistech/project/main/logo/",
                "https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/"
            )
            extinf_line = fix_missing_local_logo(extinf_line)
            section_lines.append(extinf_line)
            section_lines.extend(ch["opts"])
            section_lines.append(ch["url"])
            section_lines.append("")
            
        section_lines.append(marker_end)
        
        output_content.append("\n".join(section_lines))
        output_content.append("")

    # Bersihkan whitespace dan simpan file master
    final_output = re.sub(r'\n{3,}', '\n\n', "\n".join(output_content)).strip() + "\n"
    
    with open(indihome_path, 'w', encoding='utf-8') as f:
        f.write(final_output)

    # Simpan versi terkompresi .gz
    gz_path = indihome_path + ".gz"
    with gzip.open(gz_path, 'wb') as f_gz:
        f_gz.write(final_output.encode('utf-8'))
        
    print(f"\n✅ Penggabungan dan Pembersihan Selesai! Berkas disimpan di {indihome_path} & {gz_path}")
    print(f"   Total Saluran Akhir yang Bersih: {len(deduped_channels)} (sebelumnya: {len(all_channels_to_dedup)})")


if __name__ == "__main__":
    merge_all_to_indihome()