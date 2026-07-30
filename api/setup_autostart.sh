#!/bin/bash
# 给缺自启的服务补上 systemd 单元并开机自启
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

cat > "/etc/systemd/system/home-time-sense.service" <<EOF
[Unit]
Description=Home shared time awareness
After=network-online.target

[Service]
Type=simple
ExecStart=/usr/bin/python3 /var/www/home/api/time_sense.py --watch --interval 300
WorkingDirectory=/var/www/home/api
Restart=always
RestartSec=5
Environment=HOME_TIMEZONE=Asia/Shanghai
Environment=HOME_LOCATION=新疆奇台
Environment=HOME_LAT=44.02
Environment=HOME_LON=89.59

[Install]
WantedBy=multi-user.target
EOF
echo "写入 /etc/systemd/system/home-time-sense.service"

cat > "/etc/systemd/system/home-memory-steward.service" <<EOF
[Unit]
Description=Home Gemini memory steward
After=network-online.target home-memory.service

[Service]
Type=simple
ExecStart=/usr/bin/python3 /var/www/home/api/memory_steward.py watch --interval 300
WorkingDirectory=/var/www/home/api
Restart=always
RestartSec=10
Environment=HOME_TIMEZONE=Asia/Shanghai

[Install]
WantedBy=multi-user.target
EOF
echo "写入 /etc/systemd/system/home-memory-steward.service"

systemctl daemon-reload

# 先停掉现在手动跑的进程，交给 systemd 接管（避免端口占用）
for script in usage.py stats.py board_api.py toy_api.py time_sense.py memory_steward.py; do
  pkill -f "python3 /var/www/home/api/${script}" 2>/dev/null || true
done
sleep 1

for name in usage stats board toy time-sense memory-steward; do
  systemctl enable "home-${name}.service"
  systemctl restart "home-${name}.service"
  echo "启用并启动 home-${name}"
done

echo "---- 状态 ----"
systemctl is-active home-usage home-stats home-board home-toy home-time-sense home-memory-steward
echo "全部搞定，以后 VPS 重启也会自动拉起～"
