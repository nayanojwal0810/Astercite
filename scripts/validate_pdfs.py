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

        try:
            if reader.is_encrypted:
                errors.append(f"PDF {doc_id} is encrypted")
                continue
        except Exception as exc:
            errors.append(f"Failed to check encryption status for PDF {doc_id}: {exc}")
            continue

        try:
            num_pages = len(reader.pages)
        except Exception as exc:
            errors.append(f"Failed to read pages from PDF {doc_id}: {exc}")
            continue

        if num_pages < 1:
            errors.append(f"PDF {doc_id} has no pages")
            continue

        # Page dimension check (A4 portrait: 595.28 x 841.89 pt, tolerance +- 5 pt)
        dim_error = False
        for page_idx in range(num_pages):
            try:
                page = reader.pages[page_idx]
                w = float(page.mediabox.width)
                h = float(page.mediabox.height)
                if not (590 <= w <= 600 and 835 <= h <= 850):
                    errors.append(
                        f"PDF {doc_id} page {page_idx + 1} dimensions not standard A4 portrait: {w:.1f}x{h:.1f} pt"
                    )
            except Exception as exc:
                errors.append(f"Failed to inspect page dimensions for PDF {doc_id} page {page_idx + 1}: {exc}")
                dim_error = True
                break
        if dim_error:
            continue

        # Reader metadata check
        try:
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
        except Exception as exc:
            errors.append(f"Failed to read metadata from PDF {doc_id}: {exc}")
            continue

        # Extract text from all pages and identify headers/footers based on actual layout and position
        extract_failed = False
        cleaned_page_texts: list[str] = []
        raw_page_texts: list[str] = []
        for page_idx in range(num_pages):
            try:
                page = reader.pages[page_idx]

                header_parts: list[str] = []
                footer_parts: list[str] = []
                body_parts: list[str] = []
                has_coordinates = True

                def visitor_extract(text, cm, tm, font_dict, font_size):
                    nonlocal has_coordinates
                    if not text:
                        return
                    if tm is None or len(tm) < 6:
                        has_coordinates = False
                        body_parts.append(text)
                        return
                    cm_val = cm if (cm is not None and len(cm) >= 6) else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
                    # Compute global y-coordinate in page space
                    y_global = cm_val[1] * tm[4] + cm_val[3] * tm[5] + cm_val[5]

                    # Running header margin zone: y_global > 775 pt
                    if y_global > 775:
                        header_parts.append(text)
                    # Running footer margin zone: y_global < 60 pt
                    elif y_global < 60:
                        footer_parts.append(text)
                    else:
                        body_parts.append(text)

                ptxt_raw = page.extract_text(visitor_text=visitor_extract) or ""
                raw_page_texts.append(ptxt_raw)

                if not ptxt_raw.strip():
                    errors.append(f"PDF {doc_id} page {page_idx + 1} has no extractable text")

                expected_footer = f"Aster Systems Internal Documentation Page {page_idx + 1} of {num_pages}"
                expected_page_str = f"Page {page_idx + 1} of {num_pages}"
                expected_header = f"Aster Systems — {doc_id}"

                # If coordinate visitor successfully separated footer/header candidates:
                if has_coordinates and (footer_parts or header_parts):
                    header_norm = " ".join("".join(header_parts).split())
                    footer_norm = " ".join("".join(footer_parts).split())

                    # 1. Strict running header validation
                    if page_idx == 0:
                        if header_norm:
                            errors.append(
                                f"PDF {doc_id} page 1 contains unexpected running header or margin text: '{header_norm}'"
                            )
                    else:
                        if not header_norm:
                            errors.append(
                                f"PDF {doc_id} page {page_idx + 1} missing required running header '{expected_header}'"
                            )
                        elif header_norm == expected_header:
                            pass
                        elif header_norm.startswith("Aster Systems — "):
                            trailing = header_norm[len("Aster Systems — ") :].strip()
                            if trailing.startswith(f"{doc_id} ") or trailing.endswith(f" {doc_id}"):
                                errors.append(
                                    f"PDF {doc_id} page {page_idx + 1} running header contains extra or malformed content: '{header_norm}' (expected '{expected_header}')"
                                )
                            elif trailing != doc_id:
                                errors.append(
                                    f"PDF {doc_id} page {page_idx + 1} running header has wrong document ID: '{header_norm}' (expected '{expected_header}')"
                                )
                            else:
                                errors.append(
                                    f"PDF {doc_id} page {page_idx + 1} running header contains extra or malformed content: '{header_norm}' (expected '{expected_header}')"
                                )
                        else:
                            errors.append(
                                f"PDF {doc_id} page {page_idx + 1} invalid or extra running header content: '{header_norm}' (expected '{expected_header}')"
                            )

                    # 2. Strict running footer validation
                    if not footer_norm:
                        errors.append(
                            f"PDF {doc_id} page {page_idx + 1} missing standard running footer: expected '{expected_footer}'"
                        )
                    elif footer_norm == expected_footer:
                        pass
                    elif "Aster Systems Internal Documentation" in footer_norm and expected_page_str not in footer_norm:
                        errors.append(
                            f"PDF {doc_id} page {page_idx + 1} footer has incorrect page numbering: '{footer_norm}' (expected '{expected_footer}')"
                        )
                    else:
                        errors.append(
                            f"PDF {doc_id} page {page_idx + 1} invalid or extra running footer content: '{footer_norm}' (expected '{expected_footer}')"
                        )

                    cleaned_page_texts.append("".join(body_parts).strip())
                else:
                    # Fallback to layout-aware stream parsing on ptxt_raw
                    ptxt = ptxt_raw.strip()
                    # 1. Running footer at bottom of extracted text
                    footer_match = re.search(
                        rf"\n?Aster Systems Internal Documentation\s+Page {page_idx + 1} of {num_pages}\s*$",
                        ptxt,
                    )
                    if footer_match:
                        ptxt = ptxt[: footer_match.start()].rstrip()
                    else:
                        generic_footer = re.search(r"\n?Aster Systems Internal Documentation.*$", ptxt)
                        if generic_footer:
                            errors.append(
                                f"PDF {doc_id} page {page_idx + 1} footer has incorrect content or numbering: '{generic_footer.group(0).strip()}' (expected '{expected_footer}')"
                            )
                            ptxt = ptxt[: generic_footer.start()].rstrip()
                        else:
                            errors.append(
                                f"PDF {doc_id} page {page_idx + 1} missing standard running footer: expected '{expected_footer}'"
                            )

                    # 2. Running header on pages > 1 (or check absence on page 1)
                    if page_idx == 0:
                        p1_header_match = re.search(r"\bAster Systems\s*—\s*[^\n]+", ptxt)
                        if p1_header_match:
                            errors.append(
                                f"PDF {doc_id} page 1 contains unexpected running header: '{p1_header_match.group(0).strip()}'"
                            )
                    else:
                        header_end_match = re.search(
                            rf"\n?{re.escape(expected_header)}\s*$",
                            ptxt,
                        )
                        if header_end_match:
                            ptxt = ptxt[: header_end_match.start()].rstrip()
                        else:
                            header_top_match = re.match(
                                rf"^\s*{re.escape(expected_header)}\s*\n?",
                                ptxt,
                            )
                            if header_top_match:
                                ptxt = ptxt[header_top_match.end() :].lstrip()
                            else:
                                wrong_end = re.search(r"\n?(Aster Systems\s*—\s*[^\n]+)\s*$", ptxt)
                                wrong_top = re.match(r"^\s*(Aster Systems\s*—\s*[^\n]+)\s*\n?", ptxt)
                                if wrong_end:
                                    errors.append(
                                        f"PDF {doc_id} page {page_idx + 1} running header invalid or extra content: '{wrong_end.group(1).strip()}' (expected '{expected_header}')"
                                    )
                                    ptxt = ptxt[: wrong_end.start()].rstrip()
                                elif wrong_top:
                                    errors.append(
                                        f"PDF {doc_id} page {page_idx + 1} running header invalid or extra content: '{wrong_top.group(1).strip()}' (expected '{expected_header}')"
                                    )
                                    ptxt = ptxt[wrong_top.end() :].lstrip()
                                else:
                                    errors.append(
                                        f"PDF {doc_id} page {page_idx + 1} missing standard running header: expected '{expected_header}'"
                                    )

                    cleaned_page_texts.append(ptxt)

            except Exception as exc:
                errors.append(f"Failed to extract text from PDF {doc_id} page {page_idx + 1}: {exc}")
                extract_failed = True
                break

        if extract_failed:
            continue

        full_pdf_text = "\n".join(raw_page_texts)

        # Presentation element removal on page 1
        full_cleaned = "\n".join(cleaned_page_texts).strip()

        # 1. Company heading at top of page 1
        if full_cleaned.startswith("Aster Systems\n"):
            full_cleaned = full_cleaned[len("Aster Systems\n") :].lstrip()
        elif full_cleaned.startswith("Aster Systems"):
            full_cleaned = full_cleaned[len("Aster Systems") :].lstrip()
        else:
            errors.append(f"PDF {doc_id} missing top company header 'Aster Systems'")

        # 2. Document title
        if not full_cleaned.startswith(src_title):
            errors.append(f"PDF {doc_id} missing or mismatched document title '{src_title}'")
            after_title = full_cleaned
        else:
            after_title = full_cleaned[len(src_title) :].lstrip()

        # 3. Display metadata block
        first_sec_heading = src_sections[0][0]
        pos = after_title.find(first_sec_heading)
        if pos == -1:
            errors.append(f"PDF {doc_id} missing first section heading '{first_sec_heading}'")
            body_text = after_title
        else:
            meta_banner = after_title[:pos].strip()
            norm_meta = " ".join(meta_banner.split())
            body_text = after_title[pos:].strip()

            dept_disp = dept.replace("_", " ").title()
            class_disp = str(src_metadata.get("classification", "")).strip().title()

            expected_meta_parts = [
                f"Document ID: {doc_id}",
                "Version: v1",
                f"Department: {dept_disp}",
                f"Classification: {class_disp}",
                "Effective Date: 2026-11-01",
            ]
            for part in expected_meta_parts:
                if part.lower() not in norm_meta.lower():
                    errors.append(f"PDF {doc_id} metadata banner missing '{part}'")

            expected_meta_clean = "".join(
                f"DocumentID:{doc_id}|Version:v1|Department:{dept_disp}|Classification:{class_disp}|EffectiveDate:2026-11-01".split()
            )
            norm_meta_clean = "".join(norm_meta.split())
            if norm_meta_clean != expected_meta_clean:
                errors.append(
                    f"PDF {doc_id} metadata banner contains unexpected text: '{norm_meta}'"
                )

        # 4. Exact source-text comparison
        extracted_content = src_title + " " + body_text
        norm_pdf = " ".join(extracted_content.split())

        expected_units = [src_title]
        for sec_title, paras in src_sections:
            expected_units.append(sec_title)
            for p in paras:
                expected_units.append(p)
        norm_expected = " ".join(" ".join(expected_units).split())

        if norm_pdf != norm_expected:
            min_len = min(len(norm_pdf), len(norm_expected))
            diff_idx = min_len
            for i in range(min_len):
                if norm_pdf[i] != norm_expected[i]:
                    diff_idx = i
                    break
            start = max(0, diff_idx - 30)
            ext_snippet = norm_pdf[start : min(len(norm_pdf), diff_idx + 40)]
            exp_snippet = norm_expected[start : min(len(norm_expected), diff_idx + 40)]
            errors.append(
                f"PDF {doc_id} content does not match source Markdown (first difference around char {diff_idx}): "
                f"PDF has '{ext_snippet}' vs expected '{exp_snippet}'"
            )

        # Document identity checks in full raw text
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

