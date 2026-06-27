import re

def categorize_channels():
    m3u_path = "playlists/live_events.m3u"
    try:
        with open(m3u_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        print(f"Error reading {m3u_path}: {e}")
        return

    # Extract channel names and group-titles line-by-line
    matches = []
    for line in content.splitlines():
        if line.startswith("#EXTINF"):
            parts = line.split(",", 1)
            if len(parts) >= 2:
                name = parts[1].strip()
                group_match = re.search(r'group-title="([^"]+)"', line)
                group_title = group_match.group(1) if group_match else "General"
                matches.append((group_title, name))
    
    categorized = {
        "World Cup 2026": [],
        "Football (Sepak Bola)": [],
        "Volleyball (Bola Voli)": [],
        "Motorsports (Balap Motor/Mobil)": [],
        "Combat Sports (Beladiri/WWE)": [],
        "Basketball (Bola Basket)": [],
        "Cue Sports (Biliar/Snooker)": [],
        "Tennis (Tenis)": [],
        "General Sports / TV Olahraga": []
    }
    
    for group_title, name in matches:
        name_clean = name.strip()
        name_lower = name_clean.lower()
        
        # Determine specific category
        if "world cup" in group_title.lower() or any(kw in name_lower for kw in ["world cup", "worldcup", "piala dunia", "fifa"]):
            cat = "World Cup 2026"
        elif any(kw in name_lower for kw in ["fcb", "barca", "real madrid", "mutv", "inter tv", "rmtv", "soccer", "champions", "premier league", "laliga"]):
            cat = "Football (Sepak Bola)"
        elif any(kw in name_lower for kw in ["vnl", "volleyball", "voli", "proliga", "avc"]):
            cat = "Volleyball (Bola Voli)"
        elif any(kw in name_lower for kw in ["motogp", "f1", "formula 1", "nascar", "indycar", "wrc", "rally", "racing", "superbike", "motorvision"]):
            cat = "Motorsports (Balap Motor/Mobil)"
        elif any(kw in name_lower for kw in ["ufc", "wwe", "mma", "boxing", "ringside", "fight"]):
            cat = "Combat Sports (Beladiri/WWE)"
        elif any(kw in name_lower for kw in ["nba", "wnba", "basketball", "basket"]):
            cat = "Basketball (Bola Basket)"
        elif any(kw in name_lower for kw in ["billiard", "pool", "snooker"]):
            cat = "Cue Sports (Biliar/Snooker)"
        elif any(kw in name_lower for kw in ["tennis", "tenis"]):
            cat = "Tennis (Tenis)"
        else:
            cat = "General Sports / TV Olahraga"
            
        categorized[cat].append((name_clean, group_title))

    # Generate Markdown Note
    md_lines = [
        "# Laporan Pengelompokan Saluran TV Olahraga & Live Events\n",
        "Dokumen ini memuat data kurasi kategorisasi saluran TV olahraga dan pertandingan langsung yang berhasil dipetakan secara otomatis.\n",
        "## Ringkasan Kategori\n",
        "| Kategori | Jumlah Saluran |",
        "| :--- | :--- |"
    ]
    
    for cat, items in categorized.items():
        md_lines.append(f"| {cat} | {len(items)} |")
        
    md_lines.append("\n## Daftar Saluran per Kategori\n")
    
    for cat, items in categorized.items():
        md_lines.append(f"### {cat}")
        if not items:
            md_lines.append("*Tidak ada saluran aktif saat ini.*\n")
            continue
        md_lines.append("| No | Nama Saluran | Kelompok Asal |")
        md_lines.append("| :--- | :--- | :--- |")
        for idx, (name, orig_group) in enumerate(items, 1):
            md_lines.append(f"| {idx} | {name} | {orig_group} |")
        md_lines.append("")
        
    report_path = "playlists/channel_categories.md"
    try:
        with open(report_path, "w", encoding="utf-8") as f:
            f.write("\n".join(md_lines))
        print(f"[OK] Laporan kategori berhasil disimpan di {report_path}")
    except Exception as e:
        print(f"Error writing report: {e}")

if __name__ == "__main__":
    categorize_channels()
