"""PDF ingestion and intelligent chunking pipeline for Aster Systems knowledge documents.

Extracts text from the 24 approved v1 PDFs, excludes presentation elements,
applies section-aware paragraph-packed chunking (max 220 words), attaches
accurate metadata, fact IDs, and page references, validates the collection,
and atomically publishes data/chunks/v1_chunks.jsonl.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import stat
import sys
import tempfile
import yaml

import pypdf

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_pdfs import _get_temp_dir_on_same_volume
from scripts.validate_documents import validate_documents
from scripts.validate_pdfs import validate_pdfs
from scripts.validate_chunks import validate_chunks

MAX_CHUNK_WORDS = 220


def calculate_sha256(file_path: Path) -> str:
    """Calculate the lowercase SHA-256 checksum of a file."""
    return hashlib.sha256(file_path.read_bytes()).hexdigest().lower()


def validate_destination_path(dest_path: Path) -> None:
    """Validate that dest_path is safe for replacement before staging or generation.

    Rejects symbolic links, directory junctions, directories, reparse points,
    and non-regular filesystem objects. Accepts absent paths or regular files.
    """
    try:
        st = dest_path.lstat()
    except FileNotFoundError:
        # Genuinely absent path is accepted
        return
    except OSError as err:
        if not dest_path.exists(follow_symlinks=False):
            return
        raise RuntimeError(
            f"Refusing publication: unable to inspect destination path '{dest_path}': {err}"
        ) from err

    # Check for symbolic links (valid or broken)
    if dest_path.is_symlink():
        raise RuntimeError(
            f"Refusing publication: output path '{dest_path}' is an unsafe symbolic link"
        )

    # Check for Windows directory junctions
    is_junc = False
    if hasattr(dest_path, "is_junction"):
        try:
            is_junc = dest_path.is_junction()
        except Exception:
            pass
    if not is_junc and hasattr(os.path, "isjunction"):
        try:
            is_junc = os.path.isjunction(str(dest_path))
        except Exception:
            pass
    if is_junc:
        raise RuntimeError(
            f"Refusing publication: output path '{dest_path}' is an unsafe directory junction"
        )

    # Check for Windows reparse points
    st_attrs = getattr(st, "st_file_attributes", 0)
    if st_attrs & 0x400:
        raise RuntimeError(
            f"Refusing publication: output path '{dest_path}' is an unsafe reparse point"
        )

    # Reject if it is an existing directory
    if stat.S_ISDIR(st.st_mode):
        raise RuntimeError(
            f"Refusing publication: output path '{dest_path}' is an existing directory"
        )

    # Must be a regular file if it exists
    if not stat.S_ISREG(st.st_mode):
        raise RuntimeError(
            f"Refusing publication: output path '{dest_path}' is not an ordinary file"
        )


def extract_pdf_page_texts(
    pdf_path: Path,
    doc_id: str,
    doc_title: str,
    first_section_title: str,
) -> tuple[list[str], int]:
    """Extract clean body text per page and total page count from an approved PDF.

    Removes running headers, footers, top company headings, document titles,
    and display metadata banners without deleting genuine source content.
    """
    try:
        reader = pypdf.PdfReader(str(pdf_path))
    except Exception as exc:
        raise RuntimeError(f"Corrupted or invalid PDF {doc_id} ({pdf_path.name}): {exc}") from exc

    if reader.is_encrypted:
        raise RuntimeError(f"PDF {doc_id} is encrypted")

    num_pages = len(reader.pages)
    if num_pages < 1:
        raise RuntimeError(f"PDF {doc_id} has no pages")

    page_texts: list[str] = []

    for page_idx in range(num_pages):
        page = reader.pages[page_idx]
        header_parts: list[str] = []
        footer_parts: list[str] = []
        body_parts: list[str] = []
        has_coords = True

        def visitor_extract(text, cm, tm, font_dict, font_size):
            nonlocal has_coords
            if not text:
                return
            if tm is None or len(tm) < 6:
                has_coords = False
                body_parts.append(text)
                return
            cm_val = cm if (cm is not None and len(cm) >= 6) else [1.0, 0.0, 0.0, 1.0, 0.0, 0.0]
            y_global = cm_val[1] * tm[4] + cm_val[3] * tm[5] + cm_val[5]

            if y_global > 775:
                header_parts.append(text)
            elif y_global < 60:
                footer_parts.append(text)
            else:
                body_parts.append(text)

        raw_ptxt = page.extract_text(visitor_text=visitor_extract) or ""
        expected_footer = f"Aster Systems Internal Documentation Page {page_idx + 1} of {num_pages}"
        expected_header = f"Aster Systems — {doc_id}"

        if has_coords and (footer_parts or header_parts):
            header_norm = " ".join("".join(header_parts).split())
            footer_norm = " ".join("".join(footer_parts).split())

            # Validate header
            if page_idx == 0:
                if header_norm:
                    raise RuntimeError(
                        f"PDF {doc_id} page 1 contains unexpected running header/margin text: '{header_norm}'"
                    )
            else:
                if header_norm != expected_header:
                    raise RuntimeError(
                        f"PDF {doc_id} page {page_idx + 1} invalid running header: '{header_norm}' (expected '{expected_header}')"
                    )

            # Validate footer
            if footer_norm != expected_footer:
                raise RuntimeError(
                    f"PDF {doc_id} page {page_idx + 1} invalid running footer: '{footer_norm}' (expected '{expected_footer}')"
                )

            ptxt = "".join(body_parts).strip()
        else:
            # Fallback stream parsing
            ptxt = raw_ptxt.strip()
            footer_match = re.search(
                rf"\n?Aster Systems Internal Documentation\s+Page {page_idx + 1} of {num_pages}\s*$",
                ptxt,
            )
            if not footer_match:
                raise RuntimeError(
                    f"PDF {doc_id} page {page_idx + 1} missing standard running footer: expected '{expected_footer}'"
                )
            ptxt = ptxt[: footer_match.start()].rstrip()

            if page_idx == 0:
                p1_h = re.search(r"\bAster Systems\s*—\s*[^\n]+", ptxt)
                if p1_h:
                    raise RuntimeError(f"PDF {doc_id} page 1 contains unexpected running header")
            else:
                h_end = re.search(rf"\n?{re.escape(expected_header)}\s*$", ptxt)
                if h_end:
                    ptxt = ptxt[: h_end.start()].rstrip()
                else:
                    h_top = re.match(rf"^\s*{re.escape(expected_header)}\s*\n?", ptxt)
                    if h_top:
                        ptxt = ptxt[h_top.end() :].lstrip()
                    else:
                        raise RuntimeError(
                            f"PDF {doc_id} page {page_idx + 1} missing required running header '{expected_header}'"
                        )

        # On page 1: strip company heading, document title, and display metadata banner
        if page_idx == 0:
            if ptxt.startswith("Aster Systems\n"):
                ptxt = ptxt[len("Aster Systems\n") :].lstrip()
            elif ptxt.startswith("Aster Systems"):
                ptxt = ptxt[len("Aster Systems") :].lstrip()
            else:
                raise RuntimeError(f"PDF {doc_id} missing top company header 'Aster Systems'")

            if ptxt.startswith(doc_title):
                ptxt = ptxt[len(doc_title) :].lstrip()
            else:
                raise RuntimeError(f"PDF {doc_id} missing document title '{doc_title}'")

            pos = ptxt.find(first_section_title)
            if pos == -1:
                raise RuntimeError(f"PDF {doc_id} missing first section heading '{first_section_title}'")
            ptxt = ptxt[pos:].strip()

        page_texts.append(ptxt)

    return page_texts, num_pages


def locate_paragraph_pages(
    para: str,
    page_texts: list[str],
    start_search_page: int,
) -> tuple[int, int]:
    """Determine the 1-based start and end page numbers containing the paragraph.

    Handles single-page paragraphs as well as paragraphs spanning across page boundaries.
    """
    norm_p = " ".join(para.split())
    words = norm_p.split()
    if not words:
        return (start_search_page, start_search_page)

    num_pages = len(page_texts)
    start_page = max(1, min(start_search_page, num_pages))

    # Fast path: check from start_page onwards for an accumulated page range containing norm_p
    for p_start in range(start_page, num_pages + 1):
        for p_end in range(p_start, num_pages + 1):
            accumulated = " ".join(" ".join(page_texts[i - 1].split()) for i in range(p_start, p_end + 1))
            if norm_p in accumulated:
                return (p_start, p_end)

    # Fallback search from page 1 in case search page was advanced
    for p_start in range(1, num_pages + 1):
        for p_end in range(p_start, num_pages + 1):
            accumulated = " ".join(" ".join(page_texts[i - 1].split()) for i in range(p_start, p_end + 1))
            if norm_p in accumulated:
                return (p_start, p_end)

    # Fallback using opening and closing phrase search in accumulated pages
    first_phrase = " ".join(words[: min(6, len(words))])
    last_phrase = " ".join(words[-min(6, len(words)) :])

    p_start = None
    for p_num in range(start_page, num_pages + 1):
        norm_page = " ".join(page_texts[p_num - 1].split())
        if first_phrase in norm_page:
            p_start = p_num
            break

    if p_start is None:
        for p_num in range(1, num_pages + 1):
            norm_page = " ".join(page_texts[p_num - 1].split())
            if first_phrase in norm_page:
                p_start = p_num
                break

    if p_start is None:
        raise ValueError(f"Paragraph start phrase '{first_phrase}' not found in PDF pages")

    p_end = None
    for p_num in range(p_start, num_pages + 1):
        accumulated = " ".join(" ".join(page_texts[i - 1].split()) for i in range(p_start, p_num + 1))
        if last_phrase in accumulated:
            p_end = p_num
            break

    if p_end is None:
        raise ValueError(f"Paragraph end phrase '{last_phrase}' not found in PDF pages")

    return (p_start, p_end)


def parse_source_markdown_document(
    src_path: Path,
) -> tuple[dict, str, list[tuple[str, list[str]]], dict[str, str]]:
    """Parse Markdown front matter, H1 title, sections, paragraphs, and canonical facts."""
    content = src_path.read_text(encoding="utf-8").lstrip("\ufeff")
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n(.*))?$", content, re.DOTALL)
    if not fm_match:
        raise ValueError(f"Missing YAML front matter in {src_path.name}")

    metadata = yaml.safe_load(fm_match.group(1))
    body = fm_match.group(2) or ""

    h1_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if not h1_match:
        raise ValueError(f"Missing H1 title in {src_path.name}")
    doc_title = h1_match.group(1).strip()

    raw_sections = re.split(r"^##\s+(.+)$", body, flags=re.MULTILINE)
    if len(raw_sections) != 13:
        raise ValueError(f"Expected 6 sections in {src_path.name}, got {(len(raw_sections)-1)//2}")

    sections: list[tuple[str, list[str]]] = []
    fact_to_para: dict[str, str] = {}

    for i in range(1, len(raw_sections), 2):
        sec_title = raw_sections[i].strip()
        sec_content = raw_sections[i + 1].strip()

        # Extract fact markers
        marker_matches = list(re.finditer(r"<!--\s*fact_id:\s*([A-Za-z0-9_]+)\s*-->", sec_content))
        if marker_matches:
            paras: list[str] = []
            last_end = 0
            for mm in marker_matches:
                before_text = sec_content[last_end : mm.start()].strip()
                if before_text:
                    paras.extend([p.strip() for p in re.split(r"\r?\n\s*\r?\n", before_text) if p.strip()])
                fact_id = mm.group(1).strip()
                last_end = mm.end()

            # Text following last marker
            after_text = sec_content[last_end:].strip()
            after_paras = [p.strip() for p in re.split(r"\r?\n\s*\r?\n", after_text) if p.strip()]
            if after_paras:
                factual_para = after_paras[0]
                fact_to_para[fact_id] = " ".join(factual_para.split())
                paras.extend(after_paras)
        else:
            paras = [p.strip() for p in re.split(r"\r?\n\s*\r?\n", sec_content) if p.strip()]

        norm_paras = [" ".join(p.split()) for p in paras]
        sections.append((sec_title, norm_paras))

    return metadata, doc_title, sections, fact_to_para


def ingest_all_pdfs(
    source_dir_path: Path | str | None = None,
    pdf_dir_path: Path | str | None = None,
    output_file_path: Path | str | None = None,
    spec_dir_path: Path | str | None = None,
) -> list[dict]:
    """Ingest 24 PDFs, divide into section-aware chunks, validate, and publish safely."""
    source_dir = Path(source_dir_path) if source_dir_path else PROJECT_ROOT / "data" / "source"
    pdf_dir = Path(pdf_dir_path) if pdf_dir_path else PROJECT_ROOT / "data" / "pdfs"
    output_file = Path(output_file_path) if output_file_path else PROJECT_ROOT / "data" / "chunks" / "v1_chunks.jsonl"
    spec_dir = Path(spec_dir_path) if spec_dir_path else PROJECT_ROOT / "data" / "spec"

    # Step 1: Pre-ingestion validation
    src_errors = validate_documents(source_dir, spec_dir)
    if src_errors:
        raise RuntimeError(
            f"Pre-ingestion source document validation failed with {len(src_errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in src_errors)
        )

    pdf_errors = validate_pdfs(pdf_dir, source_dir, spec_dir)
    if pdf_errors:
        raise RuntimeError(
            f"Pre-ingestion PDF collection validation failed with {len(pdf_errors)} error(s):\n"
            + "\n".join(f"  - {e}" for e in pdf_errors)
        )

    # Step 2: Validate destination path safety
    validate_destination_path(output_file)

    # Step 3: Read specifications
    inv_file = spec_dir / "document_inventory.csv"
    if not inv_file.exists():
        raise FileNotFoundError(f"Missing inventory file: {inv_file}")
    with open(inv_file, encoding="utf-8") as f:
        inventory = {r["document_id"]: r for r in csv.DictReader(f)}

    if len(inventory) != 24:
        raise ValueError(f"Expected 24 documents in inventory, found {len(inventory)}")

    outlines_file = spec_dir / "document_outlines.yaml"
    if not outlines_file.exists():
        raise FileNotFoundError(f"Missing outlines file: {outlines_file}")
    with open(outlines_file, encoding="utf-8") as f:
        outlines_list = yaml.safe_load(f)
    outlines = {d["document_id"]: d for d in outlines_list}

    policy_file = spec_dir / "access_policy.yaml"
    if not policy_file.exists():
        raise FileNotFoundError(f"Missing access policy file: {policy_file}")
    with open(policy_file, encoding="utf-8") as f:
        access_policy = yaml.safe_load(f)
    policy_docs = access_policy.get("documents", {})

    # Step 4: Staging setup on same volume for atomic replacement
    staging_base = _get_temp_dir_on_same_volume(output_file, prefix="astercite_chunks_staging_")
    staging_file = staging_base / "staged_v1_chunks.jsonl"

    all_chunks: list[dict] = []

    try:
        # Step 5: Process documents in deterministic sorted document-ID order
        for doc_id in sorted(inventory.keys()):
            inv_entry = inventory[doc_id]
            dept = inv_entry["owner_department"]
            fname = doc_id.lower().replace("-", "_")

            pdf_file = pdf_dir / dept / f"{fname}_v1.pdf"
            src_file = source_dir / dept / f"{fname}.md"

            if not pdf_file.exists():
                raise FileNotFoundError(f"PDF missing for {doc_id}: {pdf_file}")
            if not src_file.exists():
                raise FileNotFoundError(f"Source missing for {doc_id}: {src_file}")

            # Parse source Markdown
            src_meta, src_title, src_sections, fact_to_para = parse_source_markdown_document(src_file)

            # Get outline and access policy
            outline = outlines[doc_id]
            policy_entry = policy_docs[doc_id]

            allowed_roles = list(policy_entry.get("allowed_roles", []))
            team_lead_departments = list(policy_entry.get("team_lead_departments", []))

            pdf_sha256 = calculate_sha256(pdf_file)
            first_sec_title = outline["sections"][0]["title"].strip()

            # Extract clean PDF body text per page
            page_texts, num_pages = extract_pdf_page_texts(pdf_file, doc_id, src_title, first_sec_title)

            # Verify that PDF body text contains all source sections and paragraphs exactly
            full_pdf_body = " ".join(" ".join(page_texts).split())
            cursor = 0

            # Map section IDs and outlines
            sec_outline_map = {s["section_id"]: s for s in outline["sections"]}
            sec_ids_ordered = [s["section_id"] for s in outline["sections"]]

            curr_search_page = 1

            for sec_idx, sec_id in enumerate(sec_ids_ordered):
                sec_outline = sec_outline_map[sec_id]
                sec_title = sec_outline["title"].strip()
                sec_expected_facts = sec_outline.get("fact_ids", [])

                # Verify section title in PDF body
                pos_st = full_pdf_body.find(sec_title, cursor)
                if pos_st == -1:
                    raise RuntimeError(f"Section title '{sec_title}' missing in extracted PDF text for {doc_id}")
                cursor = pos_st + len(sec_title)

                # Get matching source paragraphs for this section
                src_sec_title, src_paras = src_sections[sec_idx]
                if src_sec_title != sec_title:
                    raise ValueError(f"Outline section title '{sec_title}' != source title '{src_sec_title}' for {doc_id}")

                # Locate paragraphs on pages and verify text
                para_page_info: list[tuple[str, int, int]] = []
                for para in src_paras:
                    pos_p = full_pdf_body.find(para, cursor)
                    if pos_p == -1:
                        raise RuntimeError(f"Paragraph '{para[:30]}...' missing in extracted PDF text for {doc_id}")
                    cursor = pos_p + len(para)

                    p_start, p_end = locate_paragraph_pages(para, page_texts, curr_search_page)
                    curr_search_page = p_start
                    para_page_info.append((para, p_start, p_end))

                # Section-aware paragraph-packed chunking (MAX_CHUNK_WORDS = 220)
                sec_chunks_paras: list[list[tuple[str, int, int]]] = []
                current_chunk_paras: list[tuple[str, int, int]] = []
                current_chunk_words = 0

                for p_text, p_s, p_e in para_page_info:
                    p_word_count = len(p_text.split())
                    if p_word_count > MAX_CHUNK_WORDS:
                        raise RuntimeError(
                            f"Oversized individual paragraph in {doc_id} {sec_id} exceeds {MAX_CHUNK_WORDS} words "
                            f"({p_word_count} words): '{p_text[:50]}...'"
                        )

                    # Check if adding paragraph fits within 220 words
                    if current_chunk_paras and (current_chunk_words + p_word_count > MAX_CHUNK_WORDS):
                        sec_chunks_paras.append(current_chunk_paras)
                        current_chunk_paras = [(p_text, p_s, p_e)]
                        current_chunk_words = p_word_count
                    else:
                        current_chunk_paras.append((p_text, p_s, p_e))
                        current_chunk_words += p_word_count

                if current_chunk_paras:
                    sec_chunks_paras.append(current_chunk_paras)

                # Form chunk records for this section
                for chunk_idx, c_paras in enumerate(sec_chunks_paras, start=1):
                    chunk_id = f"{doc_id}:v1:{sec_id}:C{chunk_idx:03d}"
                    chunk_text = "\n\n".join(p[0] for p in c_paras)
                    chunk_p_start = c_paras[0][1]
                    chunk_p_end = c_paras[-1][2]

                    # Assign canonical fact IDs whose complete paragraph is in this chunk
                    chunk_facts: list[str] = []
                    chunk_para_texts = {p[0] for p in c_paras}
                    for fid in sec_expected_facts:
                        canonical_p = fact_to_para.get(fid)
                        if canonical_p and canonical_p in chunk_para_texts:
                            chunk_facts.append(fid)

                    record = {
                        "chunk_id": chunk_id,
                        "document_id": doc_id,
                        "document_version": "v1",
                        "title": inv_entry["title"].strip(),
                        "owner_department": dept,
                        "classification": inv_entry["classification"].strip().lower(),
                        "effective_from": "2026-11-01",
                        "source_type": "synthetic",
                        "section_id": sec_id,
                        "section_title": sec_title,
                        "chunk_index": chunk_idx,
                        "text": chunk_text,
                        "page_start": chunk_p_start,
                        "page_end": chunk_p_end,
                        "pdf_path": f"data/pdfs/{dept}/{fname}_v1.pdf",
                        "source_path": f"data/source/{dept}/{fname}.md",
                        "pdf_sha256": pdf_sha256,
                        "fact_ids": sorted(chunk_facts),
                        "allowed_roles": allowed_roles,
                        "team_lead_departments": team_lead_departments,
                    }
                    all_chunks.append(record)

        # Step 6: Write JSONL to staging file (UTF-8, LF newlines)
        with open(staging_file, "w", encoding="utf-8", newline="\n") as f:
            for rec in all_chunks:
                line = json.dumps(rec, ensure_ascii=False)
                f.write(line + "\n")

        # Step 7: Validate staged JSONL output
        val_errors = validate_chunks(
            chunks_file_path=staging_file,
            pdf_dir_path=pdf_dir,
            source_dir_path=source_dir,
            spec_dir_path=spec_dir,
        )
        if val_errors:
            raise RuntimeError(
                f"Staged chunk collection failed validation with {len(val_errors)} error(s):\n"
                + "\n".join(f"  - {err}" for err in val_errors)
            )

        # Step 8: Safe atomic replacement into target destination
        output_file.parent.mkdir(parents=True, exist_ok=True)
        os.replace(str(staging_file), str(output_file))
        return all_chunks

    finally:
        # Step 9: Clean up staging base directory
        if staging_base.exists():
            shutil.rmtree(staging_base, ignore_errors=True)


def main() -> int:
    """CLI entrypoint for PDF ingestion and chunk generation."""
    print("Starting AsterCite v1 PDF ingestion and intelligent chunking...")
    try:
        chunks = ingest_all_pdfs()
        print(f"Successfully ingested 24 PDFs and generated {len(chunks)} validated chunks.")
        print(f"Published to: {PROJECT_ROOT / 'data' / 'chunks' / 'v1_chunks.jsonl'}")
        return 0
    except Exception as exc:
        print(f"Ingestion failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())

