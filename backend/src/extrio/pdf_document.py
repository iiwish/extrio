"""Bounded, isolated text-layer PDF extraction; image-only pages require review."""

import io
import json
import resource
import sys


def extract(data: bytes, *, allow_footer=False) -> dict:
    from pypdf import PdfReader
    from pypdf.generic import DictionaryObject

    if len(data) > 5_000_000 or not data.startswith(b"%PDF-"):
        raise ValueError("invalid_or_oversized_pdf")
    reader = PdfReader(io.BytesIO(data), strict=True)
    if reader.is_encrypted or not 0 < len(reader.pages) <= 40:
        raise ValueError("encrypted_or_over_page_limit")
    pages = []
    footer_pages = []
    for index, page in enumerate(reader.pages):
        image_area = 0

        def placement(op, args, matrix, _text_matrix):
            nonlocal image_area
            if op == b'Do':
                image_area += abs(matrix[0] * matrix[3] - matrix[1] * matrix[2])

        text = page.extract_text(visitor_operand_before=placement) or ''
        resources = (page.get('/Resources') or DictionaryObject()).get_object()
        objects = (resources.get('/XObject') or DictionaryObject()).get_object()
        images = any(obj.get_object().get('/Subtype') == '/Image' for obj in objects.values())
        known_footer = (allow_footer and index == len(reader.pages) - 1 and bool(pages)
                        and all(len(p.strip()) >= 200 for p in pages) and len(text.strip()) >= 20
                        and len(text.strip()) < 200 and '主办单位：中华人民共和国财政部国库司' in text
                        and '网站标识码：bm14000002' in text and '版权所有' in text
                        and all(obj.get_object().get('/Subtype') == '/Image' for obj in objects.values())
                        and image_area < float(page.mediabox.width * page.mediabox.height) * .03)
        if images and len(text.strip()) < 200 and not known_footer:
            raise ValueError('pdf_image_or_incomplete_text_layer_requires_review')
        if known_footer:
            footer_pages.append(index + 1)
        pages.append(text)
    if any(len(text.strip()) < 20 for text in pages):
        raise ValueError("pdf_image_or_incomplete_text_layer_requires_review")
    text = "\n".join(pages)
    if len(text) > 1_000_000:
        raise ValueError("pdf_text_too_large")
    return {"text": text, "pages": len(pages), "extraction": "text_layer", **({'footerPages': footer_pages} if footer_pages else {})}


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_CPU, (20, 20))
    if sys.platform != 'darwin':
        resource.setrlimit(resource.RLIMIT_AS, (1_000_000_000, 1_000_000_000))
    try:
        print(json.dumps(extract(sys.stdin.buffer.read(5_000_001), allow_footer='--allow-known-footer' in sys.argv), ensure_ascii=False))
    except Exception as exc:
        print(json.dumps({"error": str(exc)[:160]}))
