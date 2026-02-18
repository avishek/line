from __future__ import annotations

from pathlib import Path

from pypdf import PdfReader


def extract_text_from_pdf(pdf_path: str | Path) -> str:
    path = Path(pdf_path).expanduser().resolve()
    if not path.exists():
        raise FileNotFoundError(f"PDF file not found: {path}")
    if path.suffix.lower() != ".pdf":
        raise ValueError(f"Input file must be a PDF: {path}")

    reader = PdfReader(str(path))
    collected_pages: list[str] = []
    for page_number, page in enumerate(reader.pages, start=1):
        page_text = (page.extract_text() or "").strip()
        if not page_text:
            continue
        collected_pages.append(f"[Page {page_number}]\n{page_text}")

    if not collected_pages:
        raise ValueError(f"No extractable text found in PDF: {path}")

    return "\n\n".join(collected_pages)

