# 📺 Auto-IPTV & EPG Streamer Pipeline

Otomasi penyaringan, deduplikasi cerdas, dan generator EPG terpadu untuk playlist IPTV FAST Channels, RCTI+, and Live Sports (Piala Dunia) secara berkala menggunakan GitHub Actions.

> [!IMPORTANT]
> **DISCLAIMER:** Proyek ini ditujukan untuk keperluan informasi dan edukasi pribadi. Tidak ada jaminan ketersediaan, akurasi, atau kesesuaian untuk tujuan tertentu. Gunakan dengan risiko Anda sendiri.

---

## 🔗 Daftar Playlist & EPG Utama

Untuk memutar saluran, salin tautan raw di bawah ini dan tempelkan langsung ke aplikasi IPTV Player favorit Anda (seperti **TiviMate, Kodi, OTT Navigator, Televizo, atau Perfect Player**).

| Jenis Playlist / EPG | Deskripsi | Tautan URL Raw |
| :--- | :--- | :--- |
| **Master Playlist** | Saluran TV Indonesia, Regional, dan Hiburan umum (bebas duplikat & aktif). | `https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/IndihomeTV.m3u` |
| **Sports & Live Events** | Khusus siaran olahraga langsung dengan prioritas Piala Dunia 2026 di baris paling atas. | `https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/playlists/live_events.m3u` |
| **EPG Guide (Jadwal TV)** | EPG XML TV terintegrasi dan dikompresi agar loading lebih cepat. | `https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/epgs/guide.xml.gz` |

---

## 🌟 Fitur Unggulan

* **Deduplikasi Pintar (Smart Deduplication)**: Skrip secara otomatis mendeteksi saluran dengan nama yang sama, menguji latensi server stream secara real-time via ping paralel, dan hanya memilih saluran dengan respons tercepat dan teraktif.
* **World Cup & Sports Priority**: Mengurutkan saluran olahraga berdasarkan ketersediaan bahasa (Bahasa Indonesia & Inggris diutamakan) serta resolusi video (HD/FHD).
* **Paralel EPG Builder**: Generator EPG menggabungkan data dari berbagai sumber penyedia jadwal acara secara paralel serta melakukan pembersihan (pruning) program kedaluwarsa secara otomatis.
* **Bebas Konflik Push (Concurrency Lock)**: Dikonfigurasi menggunakan kunci concurrency GitHub Actions agar proses update otomatis terjadwal berjalan berurutan tanpa risiko bentrok commit.

---

## 📡 Sumber Playlist & EPG

Saluran dan jadwal acara TV di dalam proyek ini didapatkan dari berbagai sumber publik:
- **Layanan Lokal**: Indihome TV (DASH Stream), RCTI+
- **FAST Channels**: TCL Channel, Pluto TV, Roku Channel, Samsung TV Plus
- **Penyedia EPG**: i.mjh.nz, BuddyChewChew, iptv-org

---

Jika repositori ini membantu Anda, jangan lupa berikan ⭐ ya!
