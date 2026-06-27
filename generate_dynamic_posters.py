import os
import re
import string
from PIL import Image, ImageDraw, ImageFont

def get_safe_filename(name: str) -> str:
    valid_chars = f"-_.{string.ascii_letters}{string.digits}"
    slug = name.strip().lower().replace(" ", "_")
    slug = "".join(c for c in slug if c in valid_chars)
    return slug if slug else "event"

def create_event_poster(channel_name: str, output_dir="logo") -> str:
    """
    Membuat poster dinamis berukuran 600x340 dengan tema premium dark-gradient neon,
    dan membagi teks duel (Team A vs Team B).
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"event_{get_safe_filename(channel_name)}.png"
    local_path = os.path.join(output_dir, filename)
    
    # Jika poster sudah ada, langsung kembalikan path-nya
    if os.path.exists(local_path):
        return f"https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/{filename}"
        
    print(f"[POSTER] Menghasilkan poster dinamis baru: {filename}...")
    
    # 1. Inisialisasi kanvas (600 x 340)
    width, height = 600, 340
    img = Image.new("RGBA", (width, height), (30, 30, 30, 255))
    draw = ImageDraw.Draw(img)
    
    # 2. Gambar background gradient modern (Dark Blue ke Deep Purple)
    for y in range(height):
        # Hitung interpolasi warna
        r = int(15 + (y / height) * 20)      # 15 to 35
        g = int(20 + (y / height) * 10)      # 20 to 30
        b = int(45 + (y / height) * 45)      # 45 to 90
        for x in range(width):
            # Campur warna horizontal juga agar menghasilkan gradient diagonal yang mewah
            factor = x / width
            rx = int(r + factor * 25)
            gx = int(g - factor * 5)
            bx = int(b + factor * 30)
            draw.point((x, y), fill=(rx, gx, bx, 255))
            
    # Draw a subtle neon border
    draw.rectangle([0, 0, width-1, height-1], outline=(0, 229, 255, 128), width=3)
    
    # 3. Cari font (fallback chain untuk Windows & Linux)
    font_large = None
    font_small = None
    
    font_names = [
        "calibrib.ttf", "arialbd.ttf", "calibri.ttf", "arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    ]
    
    for f_name in font_names:
        try:
            font_large = ImageFont.truetype(f_name, 28)
            font_small = ImageFont.truetype(f_name, 16)
            break
        except Exception:
            continue
            
    # Fallback ke default font jika tidak ditemukan ttf
    if not font_large:
        font_large = ImageFont.load_default()
        font_small = ImageFont.load_default()
        
    # 4. Parsing Teks Duel
    # Bersihkan penanda resolusi
    clean_name = re.sub(r'\[?(fhd|hd|sd)\]?', '', channel_name, flags=re.IGNORECASE).strip()
    
    # Pisahkan Duel
    team1, team2 = "", ""
    vs_markers = [r'\s+vs\s+', r'\s+v\s+', r'\s+-\s+']
    matched = False
    
    for marker in vs_markers:
        parts = re.split(marker, clean_name, flags=re.IGNORECASE)
        if len(parts) == 2:
            team1, team2 = parts[0].strip(), parts[1].strip()
            matched = True
            break
            
    if not matched:
        team1 = clean_name
        team2 = ""
        
    # 5. Menggambar Teks ke Kanvas
    # Gambar Label Kategori Utama di bagian atas
    draw.text((width // 2, 40), "LIVE MATCH", fill=(0, 229, 255, 255), font=font_small, anchor="mm")
    
    if team2:
        # Gambar nama Tim 1 (Kiri)
        draw.text((width // 4 + 20, height // 2 - 10), team1, fill=(255, 255, 255, 255), font=font_large, anchor="mm")
        
        # Gambar lingkaran "VS" di tengah
        vs_x, vs_y = width // 2, height // 2 - 10
        draw.ellipse([vs_x - 22, vs_y - 22, vs_x + 22, vs_y + 22], fill=(0, 229, 255, 40), outline=(0, 229, 255, 255), width=2)
        draw.text((vs_x, vs_y), "VS", fill=(0, 229, 255, 255), font=font_large, anchor="mm")
        
        # Gambar nama Tim 2 (Kanan)
        draw.text((3 * width // 4 - 20, height // 2 - 10), team2, fill=(255, 255, 255, 255), font=font_large, anchor="mm")
    else:
        # Jika bukan duel, gambar teks penuh di tengah
        draw.text((width // 2, height // 2 - 10), team1, fill=(255, 255, 255, 255), font=font_large, anchor="mm")
        
    # Gambar aksen neon garis pemisah bawah
    draw.line([100, height - 70, width - 100, height - 70], fill=(0, 229, 255, 80), width=2)
    
    # Tambahkan label instruksi/pemberitahuan kecil di bawah
    draw.text((width // 2, height - 40), "AUTO-IPTV LIVE STREAM", fill=(170, 170, 170, 255), font=font_small, anchor="mm")
    
    # 6. Simpan berkas gambar
    img.save(local_path, "PNG")
    return f"https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/{filename}"
