# 📺 Auto-IPTV & Sports Pipeline

Otomasi penyaringan, penyelarasan, dan optimalisasi playlist IPTV khusus siaran olahraga dan Piala Dunia 2026 secara berkala menggunakan GitHub Actions.

> [!IMPORTANT]
> **DISCLAIMER:** Proyek ini ditujukan untuk keperluan informasi dan edukasi pribadi. Tidak ada jaminan ketersediaan, akurasi, atau kesesuaian untuk tujuan tertentu. Gunakan dengan risiko Anda sendiri.

---

## 🔗 Daftar Playlist Utama

Untuk memutar siaran, salin tautan raw di bawah ini dan tempelkan langsung ke aplikasi IPTV Player favorit Anda (seperti **Cloudstream, TiviMate, Kodi, OTT Navigator, Televizo, atau Perfect Player**).

| Jenis Playlist | Deskripsi | Tautan URL Raw |
| :--- | :--- | :--- |
| **Sports & Live Events** | Siaran olahraga dan laga live terintegrasi, tersaring, dan diurutkan berdasarkan kualitas terbaik di baris teratas. | `https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/playlists/live_events.m3u` |
| **Sports (Gzipped)** | Versi terkompresi dari playlist utama agar loading di perangkat memori rendah lebih cepat. | `https://github.com/xr3ed/Auto-IPTV/raw/refs/heads/main/playlists/live_events.m3u.gz` |

---

## 🌟 Fitur Unggulan Proyek Saat Ini

* **Optimalisasi Format Namaan**: Menyeragamkan format penulisan agar rapi dan informatif di pemutar IPTV: `[resolusi] World Cup - [Nama Channel] [Bahasa] [Nomor]`.
* **Dukungan Logo Premium**: Menyematkan poster logo premium khusus bertema World Cup 2026 di seluruh saluran secara seragam.
* **Sortir Kualitas Otomatis**: Memindai manifest resolusi stream (FHD, HD, SD) dan mengurutkan secara berurutan agar kualitas tertinggi (FHD & HD) tampil di baris teratas.
* **Prioritas Bahasa**: Mengelompokkan saluran berdasarkan bahasa dengan prioritas utama Bahasa Inggris, disusul Bahasa Indonesia dan bahasa feed alternatif lainnya.
* **Sinkronisasi Otomatis**: Sinkronisasi berkala terjadwal setiap jam menggunakan GitHub Actions untuk menjaga keaktifan tautan.

---

Jika repositori ini membantu Anda, jangan lupa berikan ⭐ ya!
