"""
Enhance hero scroll-animation frames.
- Apply UnsharpMask to recover detail lost in GIF→JPEG compression
- Re-save at JPEG quality 90 with 4:4:4 chroma subsampling
- Process all 240 frames in-place
"""
import os
import sys
from pathlib import Path
from PIL import Image, ImageFilter, ImageEnhance

HERO_DIR = Path(__file__).parent.parent / "static" / "images" / "hero"
JPEG_QUALITY = 90

def enhance_frame(path: Path) -> int:
    """Enhance a single frame. Returns new file size."""
    img = Image.open(path)

    # 1. Gentle sharpening — just enough to recover lost detail
    img = img.filter(ImageFilter.UnsharpMask(radius=1.5, percent=80, threshold=3))

    # 2. Save at quality 90, 4:4:4 subsampling (no chroma downsampling)
    img.save(path, "JPEG", quality=JPEG_QUALITY, optimize=True, subsampling=0)
    return os.path.getsize(path)


def main():
    frames = sorted(HERO_DIR.glob("frame-*.jpg"))
    if not frames:
        print("No frames found!")
        sys.exit(1)

    print(f"Enhancing {len(frames)} frames...")
    old_total = sum(f.stat().st_size for f in frames)
    new_total = 0

    for i, frame in enumerate(frames, 1):
        new_size = enhance_frame(frame)
        new_total += new_size
        if i % 60 == 0 or i == len(frames):
            print(f"  [{i}/{len(frames)}] done")

    old_mb = old_total / (1024 * 1024)
    new_mb = new_total / (1024 * 1024)
    print(f"\nDone! {old_mb:.1f} MB -> {new_mb:.1f} MB")
    print(f"Average per frame: {new_total / len(frames) / 1024:.0f} KB")


if __name__ == "__main__":
    main()
