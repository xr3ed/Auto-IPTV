import re
import os
import sys
import requests
from concurrent.futures import ThreadPoolExecutor, as_completed

def check_logo_url(channel_name, group, logo_url):
    if not logo_url:
        return channel_name, group, logo_url, "KOSONG", 0
        
    # Jika menggunakan URL raw github local, mari cek filenya di repositori lokal kita sendiri terlebih dahulu
    if "raw.githubusercontent.com/xr3ed/Auto-IPTV" in logo_url:
        # Ekstrak nama berkas logo (misal: "tvri.png")
        filename = logo_url.split("/logo/")[-1]
        local_path = os.path.join("logo", filename)
        if os.path.exists(local_path):
            return channel_name, group, logo_url, "OK (LOKAL)", 200
        else:
            return channel_name, group, logo_url, "MATI (Lokal 404)", 404
            
    # Untuk URL eksternal, lakukan pengujian request HTTP HEAD/GET
    try:
        r = requests.head(logo_url, timeout=5, verify=False)
        if r.status_code == 200:
            return channel_name, group, logo_url, "OK (ONLINE)", 200
        # Jika HEAD tidak didukung, coba GET
        r_get = requests.get(logo_url, timeout=5, verify=False, stream=True)
        if r_get.status_code == 200:
            return channel_name, group, logo_url, "OK (ONLINE)", 200
        return channel_name, group, logo_url, f"MATI (HTTP {r_get.status_code})", r_get.status_code
    except Exception as e:
        return channel_name, group, logo_url, f"ERROR ({type(e).__name__})", 500

def main():
    if sys.platform.startswith('win'):
        try:
            sys.stdout.reconfigure(encoding='utf-8')
        except Exception:
            pass
            
    m3u_file = "IndihomeTV.m3u"
    if not os.path.exists(m3u_file):
        print(f"[ERROR] Berkas {m3u_file} tidak ditemukan di root folder!")
        sys.exit(1)
        
    print(f"[INFO] Membaca berkas {m3u_file}...")
    with open(m3u_file, "r", encoding="utf-8") as f:
        content = f.read()
        
    lines = content.split("\n")
    channels_to_test = []
    
    # Ekstrak data logo dari setiap EXTINF
    for i, line in enumerate(lines):
        if line.startswith("#EXTINF"):
            # Ekstrak group-title
            group = "Other"
            group_match = re.search(r'group-title="([^"]+)"', line)
            if group_match:
                group = group_match.group(1)
                
            # Ekstrak tvg-logo
            logo_url = ""
            logo_match = re.search(r'tvg-logo="([^"]+)"', line)
            if logo_match:
                logo_url = logo_match.group(1)
                
            # Ekstrak display name (setelah koma terakhir)
            display_name = "Unknown"
            if "," in line:
                display_name = line.split(",")[-1].strip()
                
            channels_to_test.append({
                "name": display_name,
                "group": group,
                "logo": logo_url
            })
            
    print(f"[INFO] Menemukan total {len(channels_to_test)} saluran.")
    print("[INFO] Menguji keaktifan logo/poster secara paralel...")
    
    results = []
    with ThreadPoolExecutor(max_workers=30) as executor:
        futures = {
            executor.submit(check_logo_url, ch["name"], ch["group"], ch["logo"]): ch
            for ch in channels_to_test
        }
        for future in as_completed(futures):
            try:
                name, group, logo, status, code = future.result()
                results.append({
                    "name": name,
                    "group": group,
                    "logo": logo,
                    "status": status,
                    "code": code
                })
            except Exception as e:
                pass
                
    # Analisis statistik
    ok_count = sum(1 for r in results if "OK" in r["status"])
    kosong_count = sum(1 for r in results if r["status"] == "KOSONG")
    mati_count = sum(1 for r in results if "MATI" in r["status"] or "ERROR" in r["status"])
    
    print("\n================ STATISTIK POSTER/LOGO ================")
    print(f" Total Saluran Diuji : {len(results)}")
    print(f" Logo OK / Aktif     : {ok_count}")
    print(f" Logo Kosong         : {kosong_count}")
    print(f" Logo Mati (HTTP 404): {mati_count}")
    print("=======================================================\n")
    
    # Tulis laporan rinci ke poster_report.md
    report_file = "poster_report.md"
    print(f"[INFO] Menulis laporan poster rinci ke {report_file}...")
    
    with open(report_file, "w", encoding="utf-8") as rf:
        rf.write("# Laporan Hasil Pemeriksaan Poster / Logo IPTV\n\n")
        rf.write(f"- **Total Saluran Diuji:** {len(results)}\n")
        rf.write(f"- **Logo Aktif (OK):** {ok_count}\n")
        rf.write(f"- **Logo Kosong (Belum Ada):** {kosong_count}\n")
        rf.write(f"- **Logo Mati (Error/404):** {mati_count}\n\n")
        
        # Tulis daftar logo mati
        rf.write("## ❌ Daftar Saluran dengan Logo/Poster MATI atau ERROR\n\n")
        rf.write("| Nama Saluran | Kelompok | URL Logo / Status |\n")
        rf.write("| --- | --- | --- |\n")
        
        dead_channels = [r for r in results if "MATI" in r["status"] or "ERROR" in r["status"]]
        # Urutkan berdasarkan kelompok kategori
        dead_channels = sorted(dead_channels, key=lambda x: (x["group"], x["name"]))
        for r in dead_channels:
            rf.write(f"| {r['name']} | {r['group']} | `{r['logo']}`<br>**Status:** {r['status']} |\n")
            
        # Tulis daftar logo kosong
        rf.write("\n## ⚠️ Daftar Saluran dengan Logo KOSONG\n\n")
        rf.write("| Nama Saluran | Kelompok |\n")
        rf.write("| --- | --- |\n")
        
        empty_channels = [r for r in results if r["status"] == "KOSONG"]
        empty_channels = sorted(empty_channels, key=lambda x: (x["group"], x["name"]))
        for r in empty_channels:
            rf.write(f"| {r['name']} | {r['group']} |\n")
            
    print("[OK] Selesai!")

if __name__ == "__main__":
    main()
