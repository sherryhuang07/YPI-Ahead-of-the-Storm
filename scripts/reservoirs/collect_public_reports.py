"""Download known public CT DPH reservoir reports and extract their source text.

Original PDFs and text are written beneath data/reservoirs/historical/ (ignored by
git, retained locally). The dated source manifest is checked in separately.
"""
from __future__ import annotations

import hashlib
import json
from pathlib import Path

import requests
from pypdf import PdfReader


ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "data" / "reservoirs" / "historical"
REPORTS = [
    ("2022-05-20", "https://portal.ct.gov/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/surface-water-capacity-summary-and-drought-tracking-report.pdf"),
    ("2022-07-29", "https://portal.ct.gov/-/media/Departments-and-Agencies/DPH/dph/drinking_water/pdf/Surface-Water-Capacity-Summary-and-Drought-Tracking-Report-7-29-2022.pdf"),
    ("2022-08-05", "https://portal.ct.gov/-/media/Departments-and-Agencies/DPH/dph/drinking_water/pdf/Surface-Water-Capacity-Summary-and-Drought-Tracking-Report-8-5-2022.pdf"),
    ("2022-08-12", "https://portal.ct.gov/-/media/water/drought/2022/drought-report-2022-08-18.pdf"),
    ("2022-09-02", "https://portal.ct.gov/-/media/Water/Drought/2022/2022-09-08_Drought_Conditions.pdf"),
    ("2022-09-16", "https://portal.ct.gov/-/media/Departments-and-Agencies/DPH/dph/drinking_water/pdf/Surface-Water-Capacity-Summary-and-Drought-Tracking-Report-9-16-2022.pdf"),
    ("2023-01-06", "https://portal.ct.gov/-/media/Departments-and-Agencies/DPH/dph/drinking_water/pdf/Surface-Water-Capacity-Summary-and-Drought-Tracking-Report-1-6-2023.pdf"),
    ("2023-05-05", "https://portal.ct.gov/dph/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/surface-water-capacity-summary-and-drought-tracking-report-5-5-2023.pdf"),
    ("2024-10-25", "https://portal.ct.gov/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/surface-water-capacity-summary-and-drought-tracking-report-10-25-2024.pdf"),
    ("2024-11-01", "https://portal.ct.gov/-/media/departments-and-agencies/dph/dph/drinking_water/pdf/surface-water-capacity-summary-and-drought-tracking-report-11-1-2024.pdf"),
]


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = []
    for report_date, url in REPORTS:
        pdf_path = OUT / f"{report_date}.pdf"
        if not pdf_path.exists():
            response = requests.get(url, timeout=60)
            response.raise_for_status()
            if not response.content.startswith(b"%PDF"):
                raise ValueError(f"Unexpected content at {url}")
            pdf_path.write_bytes(response.content)
        digest = hashlib.sha256(pdf_path.read_bytes()).hexdigest().upper()
        reader = PdfReader(str(pdf_path))
        text = "\n\n".join(page.extract_text() or "" for page in reader.pages)
        text_path = OUT / f"{report_date}.txt"
        text_path.write_text(text, encoding="utf-8")
        manifest.append({
            "report_date": report_date,
            "url": url,
            "pdf": str(pdf_path.relative_to(ROOT)).replace("\\", "/"),
            "text": str(text_path.relative_to(ROOT)).replace("\\", "/"),
            "sha256": digest,
            "pages": len(reader.pages),
            "characters_extracted": len(text),
        })
        print(f"{report_date}: {len(reader.pages)} pages, {len(text)} extracted characters, SHA256 {digest}")
    (OUT / "manifest.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")


if __name__ == "__main__":
    main()
