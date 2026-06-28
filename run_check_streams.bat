@echo off
cd /d "%~dp0"
title Auto-IPTV - Generate Blocklist
echo ==============================================
echo Menjalankan Pengecekan Stream (Lokal) ...
echo ==============================================
python check_streams.py
echo ==============================================
echo Melakukan Commit dan Push Blocklist ke Git ...
echo ==============================================
git add playlists/blocklist.json
git commit -m "chore: update local blocklist [auto]"
git pull --rebase origin main
git push origin main
echo ==============================================
echo Selesai! Tekan tombol apa saja untuk keluar.
echo ==============================================
pause
