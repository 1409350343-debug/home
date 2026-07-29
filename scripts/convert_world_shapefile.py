#!/usr/bin/env python3
"""Convert a country Shapefile to a compact browser-ready GeoJSON file."""

import json
import math
import struct
import sys
from pathlib import Path


def read_dbf(path):
    data = Path(path).read_bytes()
    count = struct.unpack_from("<I", data, 4)[0]
    header_len, record_len = struct.unpack_from("<HH", data, 8)
    fields = []
    pos = 32
    while data[pos] != 0x0D:
        desc = data[pos : pos + 32]
        name = desc[:11].split(b"\0", 1)[0].decode("ascii", "ignore")
        fields.append((name, desc[11:12], desc[16]))
        pos += 32
    records = []
    for index in range(count):
        row = data[header_len + index * record_len : header_len + (index + 1) * record_len]
        if not row or row[:1] == b"*":
            records.append({})
            continue
        cursor, record = 1, {}
        for name, _, width in fields:
            raw = row[cursor : cursor + width].strip(b" \0")
            record[name] = raw.decode("utf-8", "ignore").strip()
            cursor += width
        records.append(record)
    return records


def perpendicular_distance(point, start, end):
    if start == end:
        return math.dist(point, start)
    dx, dy = end[0] - start[0], end[1] - start[1]
    return abs(dy * point[0] - dx * point[1] + end[0] * start[1] - end[1] * start[0]) / math.hypot(dx, dy)


def simplify(points, tolerance=0.08):
    if len(points) <= 4:
        return points
    closed = points[0] == points[-1]
    work = points[:-1] if closed else points
    if len(work) <= 3:
        return points

    def rdp(seq):
        if len(seq) <= 2:
            return seq
        farthest, distance = 0, 0
        for i in range(1, len(seq) - 1):
            current = perpendicular_distance(seq[i], seq[0], seq[-1])
            if current > distance:
                farthest, distance = i, current
        if distance > tolerance:
            return rdp(seq[: farthest + 1])[:-1] + rdp(seq[farthest:])
        return [seq[0], seq[-1]]

    result = rdp(work)
    if closed:
        result.append(result[0])
    return [[round(x, 4), round(y, 4)] for x, y in result]


def read_shapes(path):
    data = Path(path).read_bytes()
    records, pos = [], 100
    while pos + 8 <= len(data):
        _, words = struct.unpack_from(">II", data, pos)
        pos += 8
        content = data[pos : pos + words * 2]
        pos += words * 2
        if len(content) < 44:
            records.append([])
            continue
        shape_type = struct.unpack_from("<I", content, 0)[0]
        if shape_type not in (5, 15, 25):
            records.append([])
            continue
        part_count, point_count = struct.unpack_from("<II", content, 36)
        parts = list(struct.unpack_from(f"<{part_count}I", content, 44))
        point_offset = 44 + part_count * 4
        points = [struct.unpack_from("<dd", content, point_offset + i * 16) for i in range(point_count)]
        parts.append(point_count)
        records.append([simplify(points[parts[i] : parts[i + 1]]) for i in range(part_count)])
    return records


def main():
    if len(sys.argv) != 4:
        raise SystemExit("usage: convert_world_shapefile.py source.shp source.dbf output.geojson")
    shapes, records = read_shapes(sys.argv[1]), read_dbf(sys.argv[2])
    features, used = [], set()
    for rings, row in zip(shapes, records):
        iso = (row.get("ISO_A3") or row.get("WB_A3") or "").upper()
        name = row.get("NAME", "")
        if len(iso) != 3 or iso == "-99" or iso in used or not rings:
            continue
        used.add(iso)
        features.append(
            {
                "type": "Feature",
                "properties": {"iso": iso, "name": name},
                "geometry": {"type": "Polygon", "coordinates": rings},
            }
        )
    output = {"type": "FeatureCollection", "features": features}
    Path(sys.argv[3]).write_text(json.dumps(output, ensure_ascii=False, separators=(",", ":")), encoding="utf-8")
    print(f"wrote {len(features)} countries to {sys.argv[3]}")


if __name__ == "__main__":
    main()
