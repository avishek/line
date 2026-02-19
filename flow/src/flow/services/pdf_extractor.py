from __future__ import annotations

import sys
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
    
def main() -> int:
    if len(sys.argv) != 2:
        print("Usage: python -m flow.services.pdf_extractor /path/to/input.pdf", file=sys.stderr)
        return 1

    pdf_path = sys.argv[1]

    try:
        extracted_text = extract_text_from_pdf(pdf_path)
    except (FileNotFoundError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    except PermissionError as exc:
        print(
            (
                "Error: Unable to read the PDF due to OS permissions. "
                "Move the file to an accessible location (for example, under this project) "
                "or grant terminal access to that folder."
            ),
            file=sys.stderr,
        )
        return 1
    except Exception as exc:  # pragma: no cover - defensive CLI fallback
        print(f"Unexpected extraction error: {exc}", file=sys.stderr)
        return 1

    print(extracted_text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

