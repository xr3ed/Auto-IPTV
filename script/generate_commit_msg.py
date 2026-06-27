import subprocess
import re
import sys
from datetime import datetime, timezone

def get_git_diff():
    try:
        # Jalankan git diff HEAD untuk file playlist utama
        result = subprocess.run(
            ["git", "diff", "HEAD", "--", "IndihomeTV.m3u", "playlists/live_events.m3u"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            text=True,
            encoding="utf-8",
            errors="ignore"
        )
        return result.stdout
    except Exception as e:
        print(f"Error running git diff: {e}")
        return ""

def extract_channel_name(extinf_line):
    # Mengambil nama saluran di setelah koma terakhir
    parts = extinf_line.rsplit(',', 1)
    if len(parts) == 2:
        return parts[1].strip()
    return "Unknown Channel"

def generate_message():
    diff_output = get_git_diff()
    
    added = set()
    removed = set()
    
    # Parse diff output
    lines = diff_output.splitlines()
    for line in lines:
        if line.startswith("+#EXTINF"):
            name = extract_channel_name(line)
            added.add(name)
        elif line.startswith("-#EXTINF"):
            name = extract_channel_name(line)
            removed.add(name)
            
    # Cari irisan (saluran yang diubah posisinya/update ringan tidak perlu dicatat ganda)
    intersection = added.intersection(removed)
    added = added - intersection
    removed = removed - intersection
    
    # Buat timestamp UTC
    timestamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    
    # Susun pesan commit
    title = f"Auto-Update {timestamp}"
    body = []
    
    if added:
        body.append("\nDitambahkan:")
        for ch in sorted(added):
            body.append(f"  + {ch}")
            
    if removed:
        body.append("\nDikurangi:")
        for ch in sorted(removed):
            body.append(f"  - {ch}")
            
    # Jika tidak ada penambahan/pengurangan nama saluran, beri keterangan update parameter/token
    if not added and not removed:
        body.append("\n• Pembaruan parameter link, token, atau EPG berkala.")
        
    full_message = title + "\n" + "\n".join(body)
    
    # Tulis ke file commit_msg.txt di root proyek
    with open("commit_msg.txt", "w", encoding="utf-8") as f:
        f.write(full_message)
        
    print("Commit message generated successfully in commit_msg.txt:")
    print("--------------------------------------------------")
    print(full_message)
    print("--------------------------------------------------")

if __name__ == "__main__":
    generate_message()
