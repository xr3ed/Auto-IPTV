# Aturan Proyek Auto-IPTV

## Alur Kerja Blocklist & Pipeline
1. Berkas `playlists/blocklist.json` hanya dihasilkan dan diperbarui secara manual oleh pengguna di lingkungan lokal melalui perintah `python check_streams.py`.
2. Pipeline GitHub Actions tidak menghasilkan blocklist baru; ia hanya membaca file `playlists/blocklist.json` yang ada di repositori untuk menandai saluran bermasalah di playlist utama.
3. **PENTING**: Selalu lakukan commit dan push berkas `playlists/blocklist.json` ke repositori setiap kali selesai melakukan pemindaian lokal agar sinkronisasi otomatis di GitHub Actions mendapatkan daftar saluran bermasalah terbaru.

## Pemrograman Python & Terminal Windows
1. Saat menulis atau memodifikasi script Python yang mencetak string UTF-8 (seperti nama saluran internasional) ke konsol Windows, konfigurasikan `sys.stdout` agar menggunakan encoding `utf-8` secara aman guna mencegah `UnicodeEncodeError`.
