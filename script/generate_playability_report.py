import os
import json
from datetime import datetime

def generate_report():
    json_path = "playlists/checked_streams.json"
    report_path = "playlists/playability_report.md"
    
    if not os.path.exists(json_path):
        print(f"Error: {json_path} tidak ditemukan! Harap jalankan generate_liveevents.py terlebih dahulu.")
        return
        
    try:
        with open(json_path, "r", encoding="utf-8") as f:
            checked_streams = json.load(f)
    except Exception as e:
        print(f"Error reading JSON database: {e}")
        return
        
    playable_list = []
    dead_list = []
    
    for stream in checked_streams:
        if stream["playable"]:
            playable_list.append(stream)
        else:
            dead_list.append(stream)
            
    # Urutkan berdasarkan nama/source
    playable_list = sorted(playable_list, key=lambda x: (x["source"], x["url"]))
    dead_list = sorted(dead_list, key=lambda x: (x["source"], x["url"]))
    
    timestamp = datetime.now().strftime("%Y-%m-%d %H:%M:%S WIB")
    
    md_lines = [
        "# Laporan Transparansi Keaktifan Playlist (Playability Report)\n",
        f"Laporan ini dibuat otomatis pada **{timestamp}** untuk mendokumentasikan alasan penyaringan saluran.\n",
        "## Ringkasan Statistik\n",
        f"*   **Total Saluran yang Diuji:** {len(checked_streams)}",
        f"*   **Saluran Aktif (Diloloskan):** {len(playable_list)}",
        f"*   **Saluran Mati / Diblokir (Disaring):** {len(dead_list)}\n",
        "---",
        "## 1. Daftar Saluran Aktif (Diloloskan)\n",
        "Tabel berikut memuat saluran yang berhasil lolos pengujian HTTP dan sniffer manifest:\n",
        "| No | Tautan Stream | Sumber Penyedia | Resolusi | Status / Latency |",
        "| :--- | :--- | :--- | :--- | :--- |"
    ]
    
    for idx, stream in enumerate(playable_list, 1):
        # Potong URL panjang agar muat di layar
        short_url = stream["url"][:60] + "..." if len(stream["url"]) > 60 else stream["url"]
        res = stream["resolution"] if stream["resolution"] else "Auto"
        md_lines.append(f"| {idx} | `{short_url}` | {stream['source']} | {res} | {stream['reason']} |")
        
    md_lines.append("\n---\n")
    md_lines.append("## 2. Daftar Saluran Mati / Diblokir (Disaring Keluar)\n")
    md_lines.append("Tabel berikut menjelaskan secara transparan mengapa saluran-saluran ini disaring keluar dari playlist:\n")
    md_lines.append("| No | Tautan Stream | Sumber Penyedia | Alasan Penyaringan |")
    md_lines.append("| :--- | :--- | :--- | :--- |")
    
    for idx, stream in enumerate(dead_list, 1):
        short_url = stream["url"][:60] + "..." if len(stream["url"]) > 60 else stream["url"]
        md_lines.append(f"| {idx} | `{short_url}` | {stream['source']} | **{stream['reason']}** |")
        
    try:
        with open(report_path, "w", encoding="utf-8") as f_rep:
            f_rep.write("\n".join(md_lines) + "\n")
        print(f"[OK] Laporan keaktifan berhasil disimpan di {report_path}")
    except Exception as e:
        print(f"Error writing markdown report: {e}")

if __name__ == "__main__":
    generate_report()
