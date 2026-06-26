import os
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
INDIHOME_FILE = "IndihomeTV.m3u"

# Daftar playlist target dan kelompok platformnya (tanpa live_events.m3u)
PLAYLISTS_TO_MERGE = [
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
            while i < len(lines) and (lines[i].startswith('#EXTVLCOPT') or lines[i].startswith('#EXTGRP')):
                opts.append(lines[i])
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


def ping_stream(url: str, headers: dict = None) -> tuple[str, bool, float]:
    """Melakukan pengujian HTTP HEAD untuk mengecek status dan response time stream."""
    headers = headers or {'User-Agent': 'Mozilla/5.0'}
    start_time = datetime.now()
    try:
        r = requests.head(url, headers=headers, timeout=5, verify=False, allow_redirects=True)
        if r.status_code < 400:
            latency = (datetime.now() - start_time).total_seconds()
            return url, True, latency
    except Exception:
        pass
    
    # Fallback ke GET minimal jika HEAD diblokir
    try:
        start_time = datetime.now()
        r = requests.get(url, headers=headers, timeout=5, verify=False, stream=True, allow_redirects=True)
        if r.status_code < 400:
            latency = (datetime.now() - start_time).total_seconds()
            return url, True, latency
    except Exception:
        pass
        
    return url, False, 999.0


def deduplicate_channels_smart(channels: list[dict]) -> list[dict]:
    """Mendeduplikasi saluran dengan nama yang sama berdasarkan ping respons tercepat."""
    print("🧠 Memulai proses Deduplikasi Pintar...")
    
    # Kelompokkan saluran berdasarkan nama bersih (clean_name)
    grouped = {}
    for ch in channels:
        name = ch["clean_name"]
        if not name:
            name = "unknown"
        grouped.setdefault(name, []).append(ch)

    unique_channels = []
    dups_groups = []

    for name, group in grouped.items():
        if len(group) == 1:
            unique_channels.append(group[0])
        else:
            dups_groups.append(group)

    if not dups_groups:
        print("  -> Tidak ditemukan saluran dobel.")
        return unique_channels

    print(f"  -> Ditemukan {len(dups_groups)} grup saluran dobel. Menguji respons server secara paralel...")

    # Kumpulkan semua URL dari grup duplikat untuk diuji paralel
    url_to_ch = {}
    for group in dups_groups:
        for ch in group:
            url_to_ch[ch["url"]] = ch

    # Jalankan pengujian ping secara paralel
    url_results = {}
    with ThreadPoolExecutor(max_workers=16) as executor:
        futures = {executor.submit(ping_stream, url): url for url in url_to_ch.keys()}
        for future in as_completed(futures):
            url = futures[future]
            try:
                res_url, playable, latency = future.result()
                url_results[res_url] = {"playable": playable, "latency": latency}
            except Exception:
                url_results[url] = {"playable": False, "latency": 999.0}

    # Pilih satu saluran terbaik dari setiap grup duplikat
    for group in dups_groups:
        # Urutkan: playable=True dahulu, lalu latency terkecil
        sorted_group = sorted(
            group,
            key=lambda x: (
                0 if url_results.get(x["url"], {}).get("playable", False) else 1,
                url_results.get(x["url"], {}).get("latency", 999.0)
            )
        )
        best_channel = sorted_group[0]
        status_str = "OK" if url_results.get(best_channel["url"], {}).get("playable", False) else "DEAD"
        latency_str = f"{url_results.get(best_channel['url'], {}).get('latency', 0.0):.2f}s" if status_str == "OK" else "N/A"
        
        print(f"  [PILIH] {best_channel['display_name']} ({best_channel['source']}) - Status: {status_str} | Latency: {latency_str}")
        unique_channels.append(best_channel)

    return unique_channels


def merge_all_to_indihome():
    print("🔗 Memulai penggabungan dan pembersihan terpadu ke IndihomeTV.m3u...")
    
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

        # Urai saluran bawaan asli yang tersisa (misalnya saluran lokal/nasional)
        original_channels = extract_streams_from_content(content, "IndihomeTV (Bawaan)")
        print(f"  -> Memuat {len(original_channels)} saluran bawaan asli.")
    
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

    # 4. Tulis kembali seluruh saluran yang unik ke IndihomeTV.m3u
    # Pisahkan saluran yang lolos filter kembali ke kelompoknya semula
    deduped_original = [ch for ch in deduped_channels if ch["source"] == "IndihomeTV (Bawaan)"]
    
    output_content = [f'#EXTM3U url-tvg="https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/epgs/guide.xml.gz"\n']
    
    # Tulis saluran bawaan asli terlebih dahulu
    for ch in deduped_original:
        output_content.append(ch["extinf"])
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
            section_lines.append(ch["extinf"])
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
        
    print(f"\n✅ Penggabungan dan Pembersihan Selesai! Berkas disimpan di {indihome_path}")
    print(f"   Total Saluran Akhir yang Bersih: {len(deduped_channels)} (sebelumnya: {len(all_channels_to_dedup)})")


if __name__ == "__main__":
    merge_all_to_indihome()