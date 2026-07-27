#!/usr/bin/env python3
import json
import subprocess
import os
from http.server import HTTPServer, BaseHTTPRequestHandler

class StatsHandler(BaseHTTPRequestHandler):
    def do_GET(self):
        path = self.path.split('?')[0]
        if path == '/api/stats':
            stats = self.get_stats()
            self.send_response(200)
            self.send_header('Content-Type', 'application/json')
            self.send_header('Access-Control-Allow-Origin', '*')
            self.end_headers()
            self.wfile.write(json.dumps(stats).encode())
        else:
            self.send_response(404)
            self.end_headers()

    def log_message(self, format, *args):
        pass

    def get_stats(self):
        cpu = self._get_cpu()
        mem = self._get_mem()
        disk = self._get_disk()
        net = self._get_net()
        uptime = self._get_uptime()
        services = self._get_services()
        return {
            'cpu': cpu,
            'memory': mem,
            'disk': disk,
            'network': net,
            'uptime': uptime,
            'services': services
        }

    def _get_cpu(self):
        try:
            load = os.getloadavg()
            return {'load_1m': round(load[0], 2), 'load_5m': round(load[1], 2), 'load_15m': round(load[2], 2)}
        except:
            return {'load_1m': 0, 'load_5m': 0, 'load_15m': 0}

    def _get_mem(self):
        try:
            with open('/proc/meminfo') as f:
                lines = f.readlines()
            info = {}
            for line in lines:
                parts = line.split()
                if parts[0] in ('MemTotal:', 'MemAvailable:', 'SwapTotal:', 'SwapFree:'):
                    info[parts[0].rstrip(':')] = int(parts[1])
            total = info.get('MemTotal', 0) // 1024
            available = info.get('MemAvailable', 0) // 1024
            used = total - available
            return {'total_mb': total, 'used_mb': used, 'available_mb': available, 'percent': round(used / total * 100, 1) if total else 0}
        except:
            return {'total_mb': 0, 'used_mb': 0, 'available_mb': 0, 'percent': 0}

    def _get_disk(self):
        try:
            st = os.statvfs('/')
            total = st.f_blocks * st.f_frsize // (1024 * 1024)
            free = st.f_bavail * st.f_frsize // (1024 * 1024)
            used = total - free
            return {'total_mb': total, 'used_mb': used, 'free_mb': free, 'percent': round(used / total * 100, 1) if total else 0}
        except:
            return {'total_mb': 0, 'used_mb': 0, 'free_mb': 0, 'percent': 0}

    def _get_net(self):
        try:
            with open('/proc/net/dev') as f:
                lines = f.readlines()
            rx_total = 0
            tx_total = 0
            for line in lines[2:]:
                parts = line.split()
                if parts[0].rstrip(':') in ('eth0', 'ens3', 'venet0'):
                    rx_total += int(parts[1])
                    tx_total += int(parts[9])
            return {
                'rx_mb': round(rx_total / (1024 * 1024), 1),
                'tx_mb': round(tx_total / (1024 * 1024), 1),
                'total_mb': round((rx_total + tx_total) / (1024 * 1024), 1),
                'total_gb': round((rx_total + tx_total) / (1024 * 1024 * 1024), 2)
            }
        except:
            return {'rx_mb': 0, 'tx_mb': 0, 'total_mb': 0, 'total_gb': 0}

    def _get_uptime(self):
        try:
            with open('/proc/uptime') as f:
                seconds = float(f.read().split()[0])
            days = int(seconds // 86400)
            hours = int((seconds % 86400) // 3600)
            return f'{days}天{hours}小时'
        except:
            return 'N/A'

    def _get_services(self):
        services = []
        checks = [
            ('Nginx', 'nginx'),
            ('Claude Code', 'claude')
        ]
        for name, keyword in checks:
            try:
                result = subprocess.run(['pgrep', '-f', keyword], capture_output=True)
                services.append({'name': name, 'status': 'online' if result.returncode == 0 else 'offline'})
            except:
                services.append({'name': name, 'status': 'unknown'})
        # LMC-5 是个 sqlite 库不是常驻进程，看库在不在就行
        db = '/var/www/home/api/lmc5_memory.db'
        services.append({'name': 'LMC-5', 'status': 'online' if os.path.exists(db) else 'offline'})
        return services

if __name__ == '__main__':
    server = HTTPServer(('127.0.0.1', 9902), StatsHandler)
    print('Stats API running on :9902')
    server.serve_forever()
