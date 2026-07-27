#!/usr/bin/env python3
"""SX765B 蓝牙中继 — 跑在 Mac 上
用法:
  pip3 install bleak
  python3 toy_relay.py
连上玩具后会一直轮询 VPS，收到新指令就转发给玩具。Ctrl+C 退出（退出前会发停止指令）。
"""
import asyncio, json, urllib.request

DEVICE_NAME = 'SX765B'
SERVICE_UUID = '0000ffe0-0000-1000-8000-00805f9b34fb'
BASE_URL = 'http://192.210.178.66:9901/api/toy'
POLL_INTERVAL = 1.0
REPORT_INTERVAL = 10.0

try:
    from bleak import BleakClient, BleakScanner
except ImportError:
    raise SystemExit('请先安装 bleak: pip3 install bleak')


def http_json(path, payload=None):
    req = urllib.request.Request(
        BASE_URL + path,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={'Content-Type': 'application/json'},
    )
    with urllib.request.urlopen(req, timeout=5) as resp:
        return json.loads(resp.read())


FUNC_SUCK = 0x09   # 外部吮吸马达
FUNC_VIB = 0x03    # 内部震动马达


def _hex(frame):
    return frame.hex(' ')


def frames_from_state(state):
    """把状态翻译成一串要发的帧（返回 list[bytes]）。"""
    # 原始帧调试：{"cmd":"raw","raw":"55 03 00 00 01 03 00"}
    raw = state.get('raw')
    if raw:
        return [bytes(int(b, 16) for b in raw.replace(',', ' ').split())]
    cmd = state.get('cmd')
    if cmd == 'stop':
        # 关键修复：两个马达各发一次停止，别只停一个
        return [
            bytes([0x55, FUNC_VIB, 0x00, 0x00, 0x00, 0x00, 0x00]),
            bytes([0x55, FUNC_SUCK, 0x00, 0x00, 0x00, 0x00, 0x00]),
        ]
    # set：按 func（马达）+ mode + intensity
    func = int(state.get('func', FUNC_SUCK)) & 0xFF
    mode = int(state.get('mode', 1)) & 0xFF
    intensity = int(state.get('intensity', 1)) & 0xFF
    return [bytes([0x55, func, 0x00, 0x00, mode, intensity, 0x00])]


def find_write_char(client):
    for service in client.services:
        if service.uuid.lower().startswith('0000ffe0'):
            for char in service.characteristics:
                if 'write-without-response' in char.properties or 'write' in char.properties:
                    return char
    return None


async def run_session(client):
    write_char = find_write_char(client)
    if write_char is None:
        print('没找到 0xFFE0 服务里的可写通道，检查设备')
        return
    print(f'已连接 {DEVICE_NAME}，写入通道 {write_char.uuid}')
    last_updated = 0.0
    last_report = 0.0
    loop = asyncio.get_event_loop()
    while client.is_connected:
        try:
            state = await loop.run_in_executor(None, http_json, '/state')
        except Exception as e:
            print(f'轮询失败: {e}')
            await asyncio.sleep(3)
            continue
        if state.get('updated_at', 0) > last_updated:
            last_updated = state['updated_at']
            for frame in frames_from_state(state):
                await client.write_gatt_char(write_char, frame, response=False)
                print(f"发送: {_hex(frame)}  (cmd={state.get('cmd')} func={state.get('func')} mode={state.get('mode')} intensity={state.get('intensity')})")
                await asyncio.sleep(0.05)
        now = loop.time()
        if now - last_report > REPORT_INTERVAL:
            last_report = now
            try:
                await loop.run_in_executor(None, http_json, '/report', {'connected': True, 'device': DEVICE_NAME})
            except Exception:
                pass
        await asyncio.sleep(POLL_INTERVAL)


async def main():
    while True:
        print(f'扫描 {DEVICE_NAME} ...')
        device = await BleakScanner.find_device_by_name(DEVICE_NAME, timeout=15)
        if device is None:
            print('没扫到设备，5秒后重试（确认玩具开机、离电脑近一点）')
            await asyncio.sleep(5)
            continue
        try:
            async with BleakClient(device) as client:
                await run_session(client)
            print('连接断开，重新扫描')
        except Exception as e:
            print(f'连接出错: {e}，5秒后重试')
            await asyncio.sleep(5)


if __name__ == '__main__':
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print('\n退出前发送停止指令...')
        try:
            http_json('/stop', {})
        except Exception:
            pass
        print('拜拜～')
