#!/bin/bash
# 把 echo-reading 深读库同步到网页可访问的位置（不含 .git/.claude 等）
# 福福在改动 /root/echo-reading 的书稿/insight 之后跑一次这个脚本
set -e
SRC=/root/echo-reading
DST=/var/www/home/vault
mkdir -p "$DST"
rsync -a --delete \
  --exclude '.git' --exclude '.claude' --exclude '.codex' --exclude '.obsidian' \
  --exclude '.agents' --exclude '_image' --exclude '*.epub' --exclude '*.mobi' --exclude '*.azw*' \
  "$SRC/books" "$SRC/insight" "$DST/"
python3 /var/www/home/api/gen_vault_manifest.py
echo "vault synced: $(date '+%F %T')"
