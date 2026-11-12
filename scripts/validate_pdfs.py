"""PDF validator for Aster Systems knowledge documents.

Validates that all 24 generated PDF documents:
1. Exist in approved paths with exact v1 naming.
2. Have valid A4 portrait structure and readable, unencrypted pages.
3. Contain matching identity and metadata (Title, Document ID, Department, Classification, Date).
4. Preserve all six section headings in exact order.
5. Preserve full source text (headings and paragraphs) without omissions or reordering.
6. Preserve all canonical factual paragraphs.
7. Contain no internal comments, markers, raw tokens, or leaked protected titles.
"""

from __future__ import annotations

import csv
from pathlib import Path
import re
import sys

import pypdf
import yaml

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_documents import get_protected_titles_for_doc
from scripts.generate_pdfs import load_source_document


def validate_pdfs(
    output_dir_path: Path | str | None = None,
    source_dir_path: Path | str | None = None,
    spec_dir_path: Path | str | None = None,
) -> list[str]:
    """Validate all generated PDFs against approved specifications and source documents."""
    output_dir = Path(output_dir_path) if output_dir_path else PROJECT_ROOT / "data" / "pdfs"
    source_dir = Path(source_dir_path) if source_dir_path else PROJECT_ROOT / "data" / "source"
    spec_dir = Path(spec_dir_path) if spec_dir_path else PROJECT_ROOT / "data" / "spec"

    errors: list[str] = []

    # 1. Load specification files
    inv_file = spec_dir / "document_inventory.csv"
    if not inv_file.exists():
        errors.append(f"Missing inventory file: {inv_file}")
        return errors

    with open(inv_file, encoding="utf-8") as f:
        inventory = {r["document_id"]: r for r in csv.DictReader(f)}

    outlines_file = spec_dir / "document_outlines.yaml"
    with open(outlines_file, encoding="utf-8") as f:
        outlines = {d["document_id"]: d for d in yaml.safe_load(f)}

    access_policy_file = spec_dir / "access_policy.yaml"
    with open(access_policy_file, encoding="utf-8") as f:
        access_policy = yaml.safe_load(f)

    facts_file = spec_dir / "fact_registry.csv"
    with open(facts_file, encoding="utf-8") as f:
        facts_by_doc: dict[str, list[dict]] = {}
        for r in csv.DictReader(f):
            facts_by_doc.setdefault(r["source_doc_id"], []).append(r)

    # 2. Check expected files exist
    expected_pdfs: dict[str, Path] = {}
    for doc_id, meta in inventory.items():
        dept = meta["owner_department"]
        pdf_name = f"{doc_id.lower().replace('-', '_')}_v1.pdf"
        expected_pdfs[doc_id] = output_dir / dept / pdf_name

    for doc_id, pdf_path in expected_pdfs.items():
        if not pdf_path.exists():
            rel = pdf_path.relative_to(output_dir) if pdf_path.is_relative_to(output_dir) else pdf_path
            errors.append(f"Missing expected PDF: {rel}")

    # 3. Check for unexpected PDF files
    expected_resolved = {p.resolve() for p in expected_pdfs.values() if p.exists()}
    found_pdfs = list(output_dir.rglob("*.pdf")) if output_dir.exists() else []

    for found_file in found_pdfs:
        if found_file.resolve() not in expected_resolved:
            rel = found_file.relative_to(output_dir) if found_file.is_relative_to(output_dir) else found_file
            errors.append(f"Unexpected PDF file: {rel}")

    # 4. Validate each PDF document in detail
    for doc_id, pdf_path in sorted(expected_pdfs.items()):
        if not pdf_path.exists():
            continue

        meta = inventory[doc_id]
        dept = meta["owner_department"]
        expected_title = meta["title"].strip()
        expected_class = meta["classification"].strip().lower()

        # Load corresponding source document
        src_path = source_dir / dept / f"{doc_id.lower().replace('-', '_')}.md"
        if not src_path.exists():
            errors.append(f"Corresponding source document missing for {doc_id}: {src_path}")
            continue

        try:
            src_metadata, src_title, src_sections = load_source_document(src_path)
        except Exception as exc:
            errors.append(f"Source document parse error for {doc_id}: {exc}")
            continue

        # Open PDF with pypdf
        try:
            reader = pypdf.PdfReader(str(pdf_path))
        except Exception as exc:
            errors.append(f"Corrupted or invalid PDF {doc_id} ({pdf_path.name}): {exc}")
            continue

        if reader.is_encrypted:
            errors.append(f"PDF {doc_id} is encrypted")

        num_pages = len(reader.pages)
        if num_pages < 1:
            errors.append(f"PDF {doc_id} has no pages")
            continue

        # Page dimension check (A4 portrait: 595.28 x 841.89 pt, tolerance +- 5 pt)
        for page_idx, page in enumerate(reader.pages):
            w = float(page.mediabox.width)
            h = float(page.mediabox.height)
            if not (590 <= w <= 600 and 835 <= h <= 850):
                errors.append(
                    f"PDF {doc_id} page {page_idx + 1} dimensions not standard A4 portrait: {w:.1f}x{h:.1f} pt"
                )

        # Extract text from all pages
        page_texts: list[str] = []
        for page_idx, page in enumerate(reader.pages):
            ptxt = page.extract_text() or ""
            if not ptxt.strip():
                errors.append(f"PDF {doc_id} page {page_idx + 1} has no extractable text")
            page_texts.append(ptxt)

        full_pdf_text = "\n".join(page_texts)

        # Clean running headers and footers for paragraph analysis
        cleaned_text = re.sub(r"Aster Systems — [A-Z0-9-]+", "", full_pdf_text)
        cleaned_text = re.sub(r"Page \d+ of \d+", "", cleaned_text)
        cleaned_text = re.sub(r"Aster Systems Internal Documentation", "", cleaned_text)
        norm_pdf = " ".join(cleaned_text.split())

        # Document identity checks
        if expected_title.lower() not in full_pdf_text.lower():
            errors.append(f"PDF {doc_id} missing document title: '{expected_title}'")

        if doc_id not in full_pdf_text:
            errors.append(f"PDF {doc_id} missing document ID: '{doc_id}'")

        if "v1" not in full_pdf_text:
            errors.append(f"PDF {doc_id} missing document version 'v1'")

        dept_display = dept.replace("_", " ").lower()
        if dept_display not in full_pdf_text.lower():
            errors.append(f"PDF {doc_id} missing department: '{dept_display}'")

        if expected_class not in full_pdf_text.lower():
            errors.append(f"PDF {doc_id} missing classification: '{expected_class}'")

        if "2026-11-01" not in full_pdf_text:
            errors.append(f"PDF {doc_id} missing effective date '2026-11-01'")

        # Reader metadata check
        pdf_meta = reader.metadata or {}
        pdf_title = str(pdf_meta.get("/Title", "")).strip()
        pdf_author = str(pdf_meta.get("/Author", "")).strip()
        pdf_subject = str(pdf_meta.get("/Subject", "")).strip()

        if pdf_title != expected_title:
            errors.append(f"PDF {doc_id} metadata Title '{pdf_title}' != expected '{expected_title}'")

        if pdf_author != "Aster Systems":
            errors.append(f"PDF {doc_id} metadata Author '{pdf_author}' != 'Aster Systems'")

        expected_subject = f"{doc_id} v1"
        if pdf_subject != expected_subject:
            errors.append(f"PDF {doc_id} metadata Subject '{pdf_subject}' != expected '{expected_subject}'")

        # Section structure checks: 6 approved headings in exact order
        doc_outline = outlines.get(doc_id, {})
        expected_sections = [s["title"].strip() for s in doc_outline.get("sections", [])]
        if len(expected_sections) != 6:
            errors.append(f"Document outline for {doc_id} does not contain 6 sections")
        else:
            sec_idx = 0
            for sec_name in expected_sections:
                found_sec = norm_pdf.find(" ".join(sec_name.split()), sec_idx)
                if found_sec == -1:
                    errors.append(f"PDF {doc_id} missing section heading: '{sec_name}'")
                    break
                sec_idx = found_sec + len(" ".join(sec_name.split()))

        # Full source-text preservation in order
        expected_units = [src_title]
        for sec_title, paras in src_sections:
            expected_units.append(sec_title)
            for p in paras:
                expected_units.append(p)

        curr_pos = 0
        for unit_idx, unit in enumerate(expected_units):
            norm_unit = " ".join(unit.split())
            found_pos = norm_pdf.find(norm_unit, curr_pos)
            if found_pos == -1:
                earlier_pos = norm_pdf.find(norm_unit)
                if earlier_pos != -1:
                    errors.append(
                        f"PDF {doc_id} text unit #{unit_idx} out of order: '{norm_unit[:40]}...'"
                    )
                else:
                    errors.append(
                        f"PDF {doc_id} missing source text unit #{unit_idx}: '{norm_unit[:40]}...'"
                    )
                break
            curr_pos = found_pos + len(norm_unit)

        # Canonical factual paragraphs check
        for f_row in facts_by_doc.get(doc_id, []):
            fid = f_row["fact_id"]
            marker_str = f"<!-- fact_id: {fid} -->"
            raw_src = src_path.read_text(encoding="utf-8")
            if marker_str in raw_src:
                after_marker = raw_src.split(marker_str, 1)[1].lstrip("\r\n")
                para_match = re.split(r"\r?\n\s*\r?\n", after_marker, maxsplit=1)
                fact_para = para_match[0].strip() if para_match else ""
                norm_fact_para = " ".join(fact_para.split())
                if norm_fact_para and norm_fact_para not in norm_pdf:
                    errors.append(
                        f"PDF {doc_id} missing canonical factual paragraph for fact {fid}: '{norm_fact_para[:40]}...'"
                    )

        # Absence of internal comments, markers, and code blocks
        if "<!--" in full_pdf_text or "-->" in full_pdf_text:
            errors.append(f"PDF {doc_id} exposes HTML comment markers")

        if "fact_id:" in full_pdf_text or "fact_id" in full_pdf_text:
            errors.append(f"PDF {doc_id} exposes internal fact_id marker text")

        if "source_type:" in full_pdf_text:
            errors.append(f"PDF {doc_id} exposes raw YAML front-matter key 'source_type:'")

        placeholder_match = re.search(
            r"\b(TODO|TBD|FIXME|Lorem ipsum)\b|\[(?:instruction|template|insert|placeholder)",
            full_pdf_text,
            re.IGNORECASE,
        )
        if placeholder_match:
            errors.append(
                f"PDF {doc_id} contains unfinished placeholder text: '{placeholder_match.group(0)}'"
            )

        # Security check: no leaked protected document titles
        protected_titles = get_protected_titles_for_doc(doc_id, inventory, access_policy)
        for prot_id, prot_title in protected_titles.items():
            if prot_title.lower() in full_pdf_text.lower():
                errors.append(
                    f"PDF {doc_id} exposes protected document title '{prot_title}' (from {prot_id})"
                )

    return errors


def main() -> int:
    """CLI entrypoint for PDF validation."""
    print("Validating AsterCite v1 PDF collection...")
    errors = validate_pdfs()

    if errors:
        print(f"PDF validation failed with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("PDF validation passed: 24 v1 PDFs verified, all sections, metadata, and full text preserved.")
    return 0


if __name__ == "__main__":
    sys.exit(main())

