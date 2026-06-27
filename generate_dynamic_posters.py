import os
import re
import string
from PIL import Image, ImageDraw, ImageFont

def get_safe_filename(name: str) -> str:
    valid_chars = f"-_.{string.ascii_letters}{string.digits}"
    slug = name.strip().lower().replace(" ", "_")
    slug = "".join(c for c in slug if c in valid_chars)
    return slug if slug else "event"

def draw_glowing_text(draw, position, text, font, text_color, glow_color, anchor="mm"):
    # Gambar glow (drop shadow menyebar di 8 arah)
    x, y = position
    for dx, dy in [(-1,-1), (-1,0), (-1,1), (0,-1), (0,1), (1,-1), (1,0), (1,1)]:
        draw.text((x + dx, y + dy), text, fill=glow_color, font=font, anchor=anchor)
    # Gambar teks utama
    draw.text(position, text, fill=text_color, font=font, anchor=anchor)

def create_event_poster(channel_name: str, output_dir="logo") -> str:
    """
    Membuat poster dinamis berukuran 600x340 dengan tema ultra-premium glassmorphism neon,
    termasuk latar belakang grafis lapangan abstrak, teks bercahaya, dan lencana "LIVE" menyala.
    """
    os.makedirs(output_dir, exist_ok=True)
    filename = f"event_{get_safe_filename(channel_name)}.png"
    local_path = os.path.join(output_dir, filename)
    
    # Jika poster sudah ada, langsung kembalikan path-nya
    if os.path.exists(local_path):
        return f"https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/{filename}"
        
    print(f"[POSTER] Menghasilkan poster ultra-premium baru: {filename}...")
    
    # 1. Inisialisasi kanvas (600 x 340)
    width, height = 600, 340
    img = Image.new("RGBA", (width, height), (15, 15, 25, 255))
    draw = ImageDraw.Draw(img)
    
    # 2. Latar belakang: Diagonal Neon Gradient (Sleek Dark Cyberpunk)
    for y in range(height):
        # Campuran diagonal mewah
        for x in range(width):
            factor = (x + y) / (width + height)
            # Interpolasi warna: ungu gelap (#1a0033) ke biru gelap (#001133)
            r = int(10 + factor * 25)
            g = int(5 + factor * 10)
            b = int(30 + factor * 45)
            draw.point((x, y), fill=(r, g, b, 255))
            
    # 3. Efek Latar Belakang: Garis Poligon Abstrak & Lingkaran Lapangan (Sport Theme)
    # Garis-garis diagonal tipis bercahaya redup
    for i in range(-5, 10):
        offset = i * 80
        draw.line([offset, 0, offset + 200, height], fill=(0, 229, 255, 15), width=2)
    # Lingkaran stadion futuristik di tengah
    draw.ellipse([width // 2 - 120, height // 2 - 120, width // 2 + 120, height // 2 + 120], outline=(0, 229, 255, 10), width=3)
    draw.line([width // 2, 0, width // 2, height], fill=(0, 229, 255, 10), width=2)
    
    # 4. Cari Font dengan fallback
    font_title = None
    font_team = None
    font_sub = None
    
    font_names = [
        "impact.ttf", "calibrib.ttf", "arialbd.ttf", "segoeuib.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "/usr/share/fonts/truetype/liberation/LiberationSans-Bold.ttf"
    ]
    
    for f_name in font_names:
        try:
            font_title = ImageFont.truetype(f_name, 20)
            font_team = ImageFont.truetype(f_name, 32)
            font_sub = ImageFont.truetype(f_name, 15)
            break
        except Exception:
            continue
            
    if not font_title:
        font_title = ImageFont.load_default()
        font_team = ImageFont.load_default()
        font_sub = ImageFont.load_default()
        
    # 5. Parsing Teks Duel
    clean_name = re.sub(r'\[?(fhd|hd|sd)\]?', '', channel_name, flags=re.IGNORECASE).strip()
    
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
        
    # 6. Menggambar Lencana "LIVE" Bercahaya (Pill Badge)
    # Background Pill
    live_x1, live_y1, live_x2, live_y2 = 30, 25, 95, 50
    draw.rounded_rectangle([live_x1, live_y1, live_x2, live_y2], radius=6, fill=(255, 17, 85, 255))
    # Teks "LIVE" putih di dalam pill
    draw.text(((live_x1 + live_x2) // 2, (live_y1 + live_y2) // 2 - 1), "LIVE", fill=(255, 255, 255, 255), font=font_title, anchor="mm")
    
    # 7. Menggambar Teks Pertandingan (Glow Mode)
    draw_glowing_text(draw, (width // 2, 40), "MATCHDAY CHAMPIONSHIP", font_title, (0, 229, 255, 255), (0, 229, 255, 40))
    
    if team2:
        # Tim 1 (Kiri)
        draw_glowing_text(draw, (width // 4 + 20, height // 2 - 10), team1.upper(), font_team, (255, 255, 255, 255), (0, 229, 255, 20))
        
        # Lencana "VS" Bulat Berpendar
        vs_x, vs_y = width // 2, height // 2 - 10
        draw.ellipse([vs_x - 24, vs_y - 24, vs_x + 24, vs_y + 24], fill=(15, 15, 30, 255), outline=(0, 229, 255, 255), width=3)
        draw.text((vs_x, vs_y), "VS", fill=(0, 229, 255, 255), font=font_team, anchor="mm")
        
        # Tim 2 (Kanan)
        draw_glowing_text(draw, (3 * width // 4 - 20, height // 2 - 10), team2.upper(), font_team, (255, 255, 255, 255), (0, 229, 255, 20))
    else:
        # Teks Tunggal di Tengah
        draw_glowing_text(draw, (width // 2, height // 2 - 10), team1.upper(), font_team, (255, 255, 255, 255), (0, 229, 255, 20))
        
    # 8. Garis Hias Neon Bawah & Footer
    draw.line([60, height - 70, width - 60, height - 70], fill=(0, 229, 255, 60), width=2)
    draw_glowing_text(draw, (width // 2, height - 40), "AUTO-IPTV PREMIUM STREAM • 60 FPS", font_sub, (180, 180, 200, 255), (0, 229, 255, 10))
    
    # 9. Simpan berkas
    img.save(local_path, "PNG")
    return f"https://raw.githubusercontent.com/xr3ed/Auto-IPTV/main/logo/{filename}"
