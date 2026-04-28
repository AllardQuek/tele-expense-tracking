"""
Debug utility for visualising pdfplumber table detection on PDF statements.

Generates PNG images for each page showing:
  - Detected table boundaries (blue boxes / pdfplumber default)
  - Word-based block boundaries (green boxes, --blocks mode)
  - Raw extracted cell text and/or word positions printed to stdout

Usage:
  python src/debug_pdf.py --input data/YouTrip_SGD-Statement_1-Dec-2025_to_31-Dec-2025.pdf
  python src/debug_pdf.py --input data/eStatement-1225.pdf --pages 1-3
  python src/debug_pdf.py --input data/eStatement-1225.pdf --pages 1,2,5
  python src/debug_pdf.py --input data/eStatement-1225.pdf --text-only
  python src/debug_pdf.py --input data/YouTrip_SGD-Statement_1-Dec-2025_to_31-Dec-2025.pdf --blocks
"""

import argparse
import sys
from pathlib import Path

try:
    import pdfplumber
except ImportError:
    print("pdfplumber is required: pip install pdfplumber")
    sys.exit(1)


def parse_page_range(spec: str, total_pages: int) -> list[int]:
    """Parse page spec like '1-3', '1,2,5', or '2' into 0-based indices."""
    indices = []
    for part in spec.split(','):
        part = part.strip()
        if '-' in part:
            start, end = part.split('-', 1)
            indices.extend(range(int(start) - 1, int(end)))
        else:
            indices.append(int(part) - 1)
    return [i for i in indices if 0 <= i < total_pages]


# x-coordinate buckets mirroring _parse_youtrip constants
_X_DATE_MAX = 110
_X_DESC_MIN = 130
_X_AMOUNT_MIN = 355
_X_AMOUNT_MAX = 430
_X_BALANCE_MIN = 495


def _extract_word_blocks(page) -> list[dict]:
    """
    Mirrors the block-detection logic from _parse_youtrip.
    Returns a list of block dicts: {words, top, bottom, date_str, merchant}
    """
    import re

    words = page.extract_words()
    if not words:
        return []

    # Group words into lines by y (±3pt tolerance)
    lines: list[list[dict]] = []
    for w in sorted(words, key=lambda w: (round(w["top"]), w["x0"])):
        if lines and abs(w["top"] - lines[-1][0]["top"]) <= 3:
            lines[-1].append(w)
        else:
            lines.append([w])

    def is_date_line(line_words):
        text = " ".join(w["text"] for w in line_words)
        return bool(re.match(r"^\d{1,2}\s+[A-Za-z]{3}\s+\d{4}$", text.strip()))

    def is_desc_only_line(ln):
        has_desc = any(w["x0"] >= _X_DESC_MIN for w in ln)
        has_date = any(w["x0"] < _X_DATE_MAX for w in ln)
        first_desc_text = next(
            (w["text"] for w in sorted(ln, key=lambda w: w["x0"]) if w["x0"] >= _X_DESC_MIN), ""
        )
        return has_desc and not has_date and not first_desc_text.lower().startswith("fx")

    blocks_raw: list[list[list[dict]]] = []
    current_block: list[list[dict]] = []
    pending_merchant = None

    for line in lines:
        date_words = [w for w in line if w["x0"] < _X_DATE_MAX]
        if date_words and is_date_line(date_words):
            merchant_line = None
            if current_block:
                if is_desc_only_line(current_block[-1]):
                    merchant_line = current_block.pop()
                blocks_raw.append(current_block)
            else:
                merchant_line = pending_merchant
            current_block = []
            if merchant_line is not None:
                current_block.append(merchant_line)
            current_block.append(line)
            pending_merchant = None
        elif current_block:
            current_block.append(line)
        else:
            if is_desc_only_line(line):
                pending_merchant = line

    if current_block:
        blocks_raw.append(current_block)

    # Build bounding boxes for each block
    results = []
    for block_lines in blocks_raw:
        all_words = [w for line in block_lines for w in line]
        if not all_words:
            continue
        top = min(w["top"] for w in all_words)
        bottom = max(w["bottom"] for w in all_words)
        # Extract date string
        date_str = ""
        merchant = ""
        for line in block_lines:
            date_col = [w for w in line if w["x0"] < _X_DATE_MAX]
            if date_col and is_date_line(date_col):
                date_str = " ".join(w["text"] for w in date_col)
            desc_col = [w for w in line if w["x0"] >= _X_DESC_MIN]
            if desc_col and not merchant:
                merchant = " ".join(w["text"] for w in desc_col)
        amount_words = [w for w in all_words if _X_AMOUNT_MIN <= w["x0"] <= _X_AMOUNT_MAX]
        amount = amount_words[0]["text"] if amount_words else ""
        results.append({"top": top, "bottom": bottom, "date": date_str, "merchant": merchant, "amount": amount})

    return results


def debug_pdf(pdf_path: Path, page_indices: list[int] | None, text_only: bool, words_mode: bool, blocks_mode: bool, output_dir: Path) -> None:
    output_dir.mkdir(parents=True, exist_ok=True)
    log_path = output_dir / f"debug_{pdf_path.stem}.txt"

    lines = []

    def emit(s: str = "") -> None:
        print(s)
        lines.append(s)

    with pdfplumber.open(pdf_path) as pdf:
        total = len(pdf.pages)
        pages_to_check = page_indices if page_indices is not None else list(range(total))

        emit(f"PDF: {pdf_path.name}  ({total} total pages)")
        emit(f"Inspecting pages: {[p + 1 for p in pages_to_check]}")
        emit("=" * 70)

        for page_idx in pages_to_check:
            page = pdf.pages[page_idx]
            page_num = page_idx + 1

            tables = page.extract_tables()
            emit(f"\n── Page {page_num} ──  ({len(tables)} table(s) detected by pdfplumber)")

            for t_idx, table in enumerate(tables):
                emit(f"  Table {t_idx}:  {len(table)} row(s) × {len(table[0]) if table else 0} col(s)")
                for r_idx, row in enumerate(table):
                    cells = [repr(c) if c else "''" for c in row]
                    emit(f"    Row {r_idx}: [{', '.join(cells)}]")

            if words_mode:
                # Dump all words sorted by y then x — reveals text pdfplumber missed in tables
                words = page.extract_words()
                words_sorted = sorted(words, key=lambda w: (round(w['top'], 0), w['x0']))
                emit("\n  Raw words on page (top→bottom, left→right):")
                current_y = None
                line_buf = []
                for w in words_sorted:
                    y = round(w['top'], 0)
                    if current_y is None or abs(y - current_y) > 3:
                        if line_buf:
                            emit(f"    y={current_y:6.1f}  " + "  |  ".join(
                                f"x={ww['x0']:5.1f} {repr(ww['text'])}" for ww in line_buf
                            ))
                        current_y = y
                        line_buf = [w]
                    else:
                        line_buf.append(w)
                if line_buf:
                    emit(f"    y={current_y:6.1f}  " + "  |  ".join(
                        f"x={ww['x0']:5.1f} {repr(ww['text'])}" for ww in line_buf
                    ))

            if not text_only:
                im = page.to_image(resolution=150)

                if blocks_mode:
                    # Draw word-based block boundaries in green (skip pdfplumber tablefinder overlay)
                    blocks = _extract_word_blocks(page)
                    emit(f"\n  Word-based blocks detected: {len(blocks)}")
                    try:
                        from PIL import ImageDraw
                        scale = 150 / 72  # resolution / default dpi
                        draw = ImageDraw.Draw(im.annotated)
                        for i, b in enumerate(blocks):
                            x0_px = int(20 * scale)
                            x1_px = int(560 * scale)
                            y0_px = int(b["top"] * scale)
                            y1_px = int(b["bottom"] * scale)
                            draw.rectangle([x0_px, y0_px, x1_px, y1_px], outline="green", width=2)
                            label = f"{b['date']} {b['amount']}"
                            draw.text((x0_px + 4, y0_px + 2), label, fill="green")
                            emit(f"    Block {i+1:2d}: y={b['top']:6.1f}–{b['bottom']:6.1f}  {b['date']}  {b['amount']}  {b['merchant'][:40]}")
                    except ImportError:
                        emit("  [warning] Pillow ImageDraw not available — green overlays skipped")
                else:
                    im.debug_tablefinder()

                out_path = output_dir / f"debug_page{page_num:02d}.png"
                im.save(str(out_path))
                emit(f"  → image: {out_path}")

        emit("\n" + "=" * 70)

    log_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"\nText log saved to: {log_path}")
    if not text_only:
        print(f"Images saved to:   {output_dir}/")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Visual debug for pdfplumber table detection",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python src/debug_pdf.py --input data/YouTrip_SGD-Statement_1-Dec-2025_to_31-Dec-2025.pdf
  python src/debug_pdf.py --input data/eStatement-1225.pdf --pages 1-3
  python src/debug_pdf.py --input data/eStatement-1225.pdf --text-only
        """,
    )
    parser.add_argument("--input", required=True, help="Path to the PDF file")
    parser.add_argument("--pages", default=None, help="Pages to inspect, e.g. '1-3' or '1,2,5' (default: all)")
    parser.add_argument("--text-only", action="store_true", help="Print cell text only, skip image rendering")
    parser.add_argument("--words", action="store_true", help="Also dump all raw words with positions (reveals text missed by table detection)")
    parser.add_argument("--blocks", action="store_true", help="Overlay word-based block boundaries (green) instead of pdfplumber tablefinder (blue)")
    parser.add_argument("--output-dir", default="output/debug", help="Directory for debug images (default: output/debug/)")
    args = parser.parse_args()

    pdf_path = Path(args.input)
    if not pdf_path.exists():
        print(f"Error: file not found: {pdf_path}", file=sys.stderr)
        sys.exit(1)

    output_dir = Path(args.output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    with pdfplumber.open(pdf_path) as pdf:
        total_pages = len(pdf.pages)

    page_indices = parse_page_range(args.pages, total_pages) if args.pages else None

    debug_pdf(pdf_path, page_indices, args.text_only, args.words, args.blocks, output_dir)


if __name__ == "__main__":
    main()
