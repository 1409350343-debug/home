#!/bin/bash
# 给缺自启的 4 个服务补上 systemd 单元并开机自启
# 用法（在 VPS 上、root 身份）：bash /var/www/home/api/setup_autostart.sh
set -e

declare -A SVC=(
  [usage]=usage.py
  [stats]=stats.py
  [board]=board_api.py
  [toy]=toy_api.py
)

for name in "${!SVC[@]}"; do
  script="${SVC[$name]}"
  unit="/etc/systemd/system/home-${name}.service"
  cat > "$unit" <<EOF
[Unit]
Description=Home ${name} API
After=network.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /var/www/home/api/${script}
WorkingDirectory=/var/www/home/api
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
EOF
  echo "写入 $unit"
done

systemctl daemon-reload

# 先停掉现在手动跑的进程，交给 systemd 接管（避免端口占用）
for script in usage.py stats.py board_api.py toy_api.py; do
  pkill -f "python3 /var/www/home/api/${script}" 2>/dev/null || true
done
sleep 1

for name in usage stats board toy; do
  systemctl enable "home-${name}.service"
  systemctl restart "home-${name}.service"
  echo "启用并启动 home-${name}"
done

echo "---- 状态 ----"
systemctl is-active home-usage home-stats home-board home-toy
echo "全部搞定，以后 VPS 重启也会自动拉起～"
