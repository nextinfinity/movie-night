"""Generate browser icon fallbacks. Dev-only dependency: resvg-py==0.3.2."""
import struct
from pathlib import Path

import resvg_py

STATIC = Path(__file__).resolve().parents[1] / "app" / "static"


def render(size):
    return resvg_py.svg_to_bytes(svg_path=str(STATIC / "icon.svg"), width=size, height=size)


def main():
    (STATIC / "favicon-32.png").write_bytes(render(32))
    (STATIC / "apple-touch-icon.png").write_bytes(render(180))

    # ICO directory followed by PNG frames, supported by modern ICO decoders.
    sizes = (16, 32, 48)
    frames = [render(size) for size in sizes]
    header = struct.pack("<HHH", 0, 1, len(sizes))
    offset = len(header) + 16 * len(sizes)
    entries = []
    for size, frame in zip(sizes, frames):
        entries.append(struct.pack("<BBBBHHII", size, size, 0, 0, 1, 32, len(frame), offset))
        offset += len(frame)
    (STATIC / "favicon.ico").write_bytes(header + b"".join(entries) + b"".join(frames))


if __name__ == "__main__":
    main()
