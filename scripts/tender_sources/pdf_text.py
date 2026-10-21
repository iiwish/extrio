"""Bounded text-only PDF reader; invoked in a separate process."""

import io
import json
import os
import resource
import subprocess
import sys
import tempfile
from pathlib import Path


def ocr(data: bytes, pages: int) -> dict:
    renderer, engine = os.environ.get("TENDER_PDFTOPPM"), os.environ.get("TENDER_OCR_COMMAND")
    if not renderer or not engine:
        raise ValueError("pdf_has_no_text_layer_ocr_not_configured")
    if pages > 10:
        raise ValueError("ocr_pdf_over_page_limit")
    with tempfile.TemporaryDirectory(prefix="extrio-pdf-ocr-") as folder:
        root = Path(folder)
        (root / "input.pdf").write_bytes(data)
        subprocess.run(
            [renderer, "-scale-to", "2200", "-png", str(root / "input.pdf"), str(root / "page")],
            check=True,
            capture_output=True,
            timeout=30,
        )
        files = sorted(root.glob("page-*.png"))
        if len(files) != pages:
            raise ValueError("ocr_render_page_count_mismatch")
        recognized = []
        for file in files:
            result = subprocess.run([engine, str(file)], check=False, capture_output=True, timeout=40)
            if result.returncode:
                raise ValueError(f"local_ocr_failed_{result.returncode}:" + result.stderr.decode(errors="replace")[-400:])
            recognized.extend(json.loads(result.stdout))
        if len(recognized) != pages or any(not p["lines"] for p in recognized):
            raise ValueError("ocr_empty_page")
        lines = [line for p in recognized for line in p["lines"]]
        return {
            "text": "\n".join(line["text"] for line in lines),
            "pages": pages,
            "extraction": "ocr",
            "minimumLineConfidence": min(line["confidence"] for line in lines),
            "reviewRequired": True,
        }


def main():
    resource.setrlimit(resource.RLIMIT_CPU, (45, 45))
    data = sys.stdin.buffer.read(5_000_001)
    if len(data) > 5_000_000 or not data.startswith(b"%PDF-"):
        raise ValueError("invalid_or_oversized_pdf")
    from pypdf import PdfReader

    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted or len(reader.pages) > 40:
        raise ValueError("encrypted_or_over_page_limit")
    page_text = [page.extract_text() or "" for page in reader.pages]
    # Mixed image/text PDFs must not silently lose their image-only pages.
    if any(not text.strip() for text in page_text):
        print(json.dumps(ocr(data, len(reader.pages)), ensure_ascii=False))
        return
    text = "\n".join(page_text)
    if len(text) > 1_000_000:
        raise ValueError("pdf_text_too_large")
    print(json.dumps({"text": text, "pages": len(reader.pages), "extraction": "text_layer", "reviewRequired": False}, ensure_ascii=False))


if __name__ == "__main__":
    main()
