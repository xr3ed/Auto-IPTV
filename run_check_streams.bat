@echo off
cd /d "%~dp0"
title Auto-IPTV - Generate Blocklist
echo ==============================================
echo Menjalankan Pengecekan Stream (Lokal) ...
echo ==============================================
python check_streams.py
echo ==============================================
echo Menghasilkan Playlist Gabungan (Lokal) ...
echo ==============================================
python generate_liveevents.py
echo ==============================================
echo Melakukan Commit dan Push ke Git ...
echo ==============================================
git add playlists/blocklist.json playlists/live_events.m3u playlists/live_events.m3u.gz
git commit -m "chore: update local blocklist and live events playlist [auto]"
git pull --rebase origin main
git push origin main
echo ==============================================
echo Selesai! Tekan tombol apa saja untuk keluar.
echo ==============================================
pause
