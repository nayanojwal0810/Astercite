"""Standalone chunk validator for Aster Systems knowledge assistant.

Independently validates the generated JSONL chunk collection against the
authoritative input PDFs, Markdown sources, and frozen specifications.
"""

from __future__ import annotations

import csv
import datetime
import hashlib
import json
import os
from pathlib import Path
import re
import sys
import yaml

import pypdf

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

EXPECTED_DEPARTMENTS = [
    "engineering",
    "it_support",
    "people_operations",
    "finance_operations",
]

VALID_ROLES = [
    "employee",
    "engineer",
    "it_support",
    "hr_staff",
    "finance_staff",
    "team_lead",
    "document_admin",
]

REQUIRED_FIELDS = [
    "chunk_id",
    "document_id",
    "document_version",
    "title",
    "owner_department",
    "classification",
    "effective_from",
    "source_type",
    "section_id",
    "section_title",
    "chunk_index",
    "text",
    "page_start",
    "page_end",
    "pdf_path",
    "source_path",
    "pdf_sha256",
    "fact_ids",
    "allowed_roles",
    "team_lead_departments",
]

REQUIRED_FRONTMATTER_FIELDS = [
    "document_id",
    "document_version",
    "title",
    "owner_department",
    "classification",
    "effective_from",
    "source_type",
]

MAX_CHUNK_WORDS = 220


def _json_object_pairs_hook(pairs: list[tuple[str, any]]) -> dict:
    """Decode JSON object pairs while detecting duplicate keys."""
    d = {}
    for k, v in pairs:
        if k in d:
            raise ValueError(f"Duplicate key '{k}' in JSON object")
        d[k] = v
    return d


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


def extract_pdf_clean_text(pdf_path: Path, doc_title: str, first_sec_title: str) -> tuple[str, int]:
    """Extract full clean body text and total page count from an approved PDF (compatibility helper)."""
    page_texts, num_pages = extract_pdf_page_texts(pdf_path, "", doc_title, first_sec_title)
    return "\n".join(page_texts).strip(), num_pages


def parse_source_markdown_document(
    src_path: Path,
) -> tuple[dict, str, list[tuple[str, list[str]]], dict[str, str]]:
    """Parse Markdown front matter, H1 title, sections, paragraphs, and canonical facts."""
    content = src_path.read_text(encoding="utf-8").lstrip("\ufeff")
    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n(.*))?$", content, re.DOTALL)
    if not fm_match:
        raise ValueError(f"Missing YAML front matter in {src_path.name}")

    try:
        metadata = yaml.safe_load(fm_match.group(1))
    except Exception as exc:
        raise ValueError(f"Malformed YAML front matter in {src_path.name}: {exc}")
    if not isinstance(metadata, dict):
        metadata = {}
    body = fm_match.group(2) or ""

    h1_match = re.search(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    doc_title = h1_match.group(1).strip() if h1_match else ""

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


def validate_chunks(
    chunks_file_path: Path | str | None = None,
    pdf_dir_path: Path | str | None = None,
    source_dir_path: Path | str | None = None,
    spec_dir_path: Path | str | None = None,
) -> list[str]:
    """Validate JSONL chunk corpus against specifications, sources, and PDFs.

    Returns a list of validation error strings. An empty list signifies success.
    """
    chunks_file = Path(chunks_file_path) if chunks_file_path else PROJECT_ROOT / "data" / "chunks" / "v1_chunks.jsonl"
    pdf_dir = Path(pdf_dir_path) if pdf_dir_path else PROJECT_ROOT / "data" / "pdfs"
    source_dir = Path(source_dir_path) if source_dir_path else PROJECT_ROOT / "data" / "source"
    spec_dir = Path(spec_dir_path) if spec_dir_path else PROJECT_ROOT / "data" / "spec"

    errors: list[str] = []

    # Check existence of chunks file
    if not chunks_file.exists():
        return [f"Chunk file does not exist: {chunks_file}"]
    if chunks_file.is_dir():
        return [f"Chunk file path is a directory: {chunks_file}"]

    # 1. Read specifications
    inv_file = spec_dir / "document_inventory.csv"
    if not inv_file.exists():
        return [f"Missing document inventory: {inv_file}"]
    with open(inv_file, encoding="utf-8") as f:
        inventory = {r["document_id"]: r for r in csv.DictReader(f)}

    outlines_file = spec_dir / "document_outlines.yaml"
    if not outlines_file.exists():
        return [f"Missing document outlines: {outlines_file}"]
    with open(outlines_file, encoding="utf-8") as f:
        outlines_list = yaml.safe_load(f)
    outlines = {d["document_id"]: d for d in outlines_list}

    policy_file = spec_dir / "access_policy.yaml"
    if not policy_file.exists():
        return [f"Missing access policy: {policy_file}"]
    with open(policy_file, encoding="utf-8") as f:
        access_policy = yaml.safe_load(f)
    policy_docs = access_policy.get("documents", {})

    fact_file = spec_dir / "fact_registry.csv"
    if not fact_file.exists():
        return [f"Missing fact registry: {fact_file}"]
    with open(fact_file, encoding="utf-8") as f:
        fact_rows = list(csv.DictReader(f))
    registry_facts = {r["fact_id"]: r for r in fact_rows}

    cross_file = spec_dir / "cross_references.csv"
    if not cross_file.exists():
        return [f"Missing cross references file: {cross_file}"]
    with open(cross_file, encoding="utf-8") as f:
        cross_rows = list(csv.DictReader(f))
    if len(cross_rows) != 12:
        errors.append(f"Expected 12 directed relationships in cross_references.csv, found {len(cross_rows)}")

    # 2. Read and parse JSONL file
    try:
        raw_bytes = chunks_file.read_bytes()
    except Exception as exc:
        return [f"Failed to read chunk file '{chunks_file}': {exc}"]

    try:
        raw_content = raw_bytes.decode("utf-8")
    except UnicodeDecodeError as exc:
        return [f"Failed to read chunk file as UTF-8: {exc}"]

    lines = raw_content.splitlines()
    non_empty_lines = [(line_num, line.strip()) for line_num, line in enumerate(lines, start=1) if line.strip()]
    if not non_empty_lines:
        return [f"Chunk file is empty: {chunks_file}"]

    chunks: list[dict] = []
    chunk_ids_seen: set[str] = set()

    for line_num, line in non_empty_lines:
        try:
            record = json.loads(line, object_pairs_hook=_json_object_pairs_hook)
        except Exception as exc:
            errors.append(f"Line {line_num}: Malformed JSON record ({exc})")
            continue

        if not isinstance(record, dict):
            errors.append(f"Line {line_num}: Record is not a JSON object")
            continue

        # Check required fields and unexpected extra fields
        keys_set = set(record.keys())
        expected_keys_set = set(REQUIRED_FIELDS)
        missing_keys = expected_keys_set - keys_set
        extra_keys = keys_set - expected_keys_set

        if missing_keys:
            errors.append(f"Line {line_num}: Missing required field(s): {sorted(missing_keys)}")
        if extra_keys:
            errors.append(f"Line {line_num}: Unexpected extra field(s): {sorted(extra_keys)}")

        # Check that no field has a None value
        for field in REQUIRED_FIELDS:
            if field in record and record[field] is None:
                errors.append(f"Line {line_num}: Field '{field}' cannot be null")

        # Type checks for string fields
        string_fields = [
            "chunk_id", "document_id", "document_version", "title", "owner_department",
            "classification", "effective_from", "source_type", "section_id", "section_title",
            "text", "pdf_path", "source_path", "pdf_sha256",
        ]
        for field in string_fields:
            if field in record and record[field] is not None:
                val = record[field]
                if not isinstance(val, str) or isinstance(val, bool) or not val.strip():
                    errors.append(f"Line {line_num}: Field '{field}' must be a non-empty string (got {type(val).__name__})")

        # Type checks for integer fields (must be int, not bool)
        int_fields = ["chunk_index", "page_start", "page_end"]
        for field in int_fields:
            if field in record and record[field] is not None:
                val = record[field]
                if not isinstance(val, int) or isinstance(val, bool):
                    errors.append(f"Line {line_num}: Field '{field}' must be an integer, not {type(val).__name__}")

        # Type checks for list fields
        list_fields = ["fact_ids", "allowed_roles", "team_lead_departments"]
        for field in list_fields:
            if field in record and record[field] is not None:
                val = record[field]
                if not isinstance(val, list):
                    errors.append(f"Line {line_num}: Field '{field}' must be a list (got {type(val).__name__})")
                else:
                    if not all(isinstance(x, str) and not isinstance(x, bool) for x in val):
                        errors.append(f"Line {line_num}: Field '{field}' must contain only strings")

        chunk_id = record.get("chunk_id")
        if isinstance(chunk_id, str) and not isinstance(chunk_id, bool) and chunk_id.strip():
            if chunk_id in chunk_ids_seen:
                errors.append(f"Line {line_num}: Duplicate chunk_id '{chunk_id}'")
            else:
                chunk_ids_seen.add(chunk_id)

        chunks.append(record)

    # If critical JSON or schema errors occurred, return early
    if errors:
        return errors

    # 3. Enforce strict on-disk record sequence
    expected_doc_order = sorted(inventory.keys())
    valid_sections = ["S01", "S02", "S03", "S04", "S05", "S06"]

    current_doc_idx = 0
    current_sec_idx = 0
    expected_chunk_idx = 1
    seen_docs: list[str] = []
    seen_secs_for_doc: dict[str, list[str]] = {}

    prev_doc_id = None
    prev_sec_id = None

    for line_idx, c in enumerate(chunks, start=1):
        c_doc = c["document_id"]
        c_sec = c["section_id"]
        c_idx = c["chunk_index"]
        c_id = c["chunk_id"]

        expected_id = f"{c_doc}:v1:{c_sec}:C{c_idx:03d}"
        if c_id != expected_id:
            errors.append(f"Line {line_idx}: Chunk ID '{c_id}' != expected '{expected_id}'")

        if prev_doc_id is None:
            if c_doc != expected_doc_order[0]:
                errors.append(f"Line {line_idx}: First document is '{c_doc}', expected '{expected_doc_order[0]}'")
            seen_docs.append(c_doc)
            seen_secs_for_doc[c_doc] = [c_sec]
            current_doc_idx = expected_doc_order.index(c_doc) if c_doc in expected_doc_order else 0
            if c_sec != "S01":
                errors.append(f"Line {line_idx}: First section for {c_doc} is '{c_sec}', expected 'S01'")
            current_sec_idx = valid_sections.index(c_sec) if c_sec in valid_sections else 0
            expected_chunk_idx = 1
        elif c_doc != prev_doc_id:
            if c_doc in seen_docs:
                errors.append(f"Line {line_idx}: Document '{c_doc}' reappeared out of order after '{prev_doc_id}'")
            else:
                if c_doc not in expected_doc_order:
                    errors.append(f"Line {line_idx}: Unknown document ID '{c_doc}'")
                else:
                    new_doc_idx = expected_doc_order.index(c_doc)
                    if new_doc_idx <= current_doc_idx:
                        errors.append(f"Line {line_idx}: Document '{c_doc}' is out of order (previous was '{prev_doc_id}')")
                    current_doc_idx = new_doc_idx
                seen_docs.append(c_doc)
                seen_secs_for_doc[c_doc] = [c_sec]
                if c_sec != "S01":
                    errors.append(f"Line {line_idx}: First section for document '{c_doc}' must be 'S01', got '{c_sec}'")
                current_sec_idx = valid_sections.index(c_sec) if c_sec in valid_sections else 0
                expected_chunk_idx = 1
        elif c_sec != prev_sec_id:
            if c_sec in seen_secs_for_doc.get(c_doc, []):
                errors.append(f"Line {line_idx}: Section '{c_sec}' reappeared out of order in document '{c_doc}'")
            else:
                if c_sec not in valid_sections:
                    errors.append(f"Line {line_idx}: Unknown section ID '{c_sec}' in document '{c_doc}'")
                else:
                    new_sec_idx = valid_sections.index(c_sec)
                    if new_sec_idx <= current_sec_idx:
                        errors.append(f"Line {line_idx}: Section '{c_sec}' out of order in {c_doc} (previous was '{prev_sec_id}')")
                    current_sec_idx = new_sec_idx
                seen_secs_for_doc.setdefault(c_doc, []).append(c_sec)
                expected_chunk_idx = 1

        if c_idx != expected_chunk_idx:
            errors.append(f"Line {line_idx}: In document '{c_doc}' section '{c_sec}', chunk_index {c_idx} != expected {expected_chunk_idx}")
        expected_chunk_idx = c_idx + 1

        prev_doc_id = c_doc
        prev_sec_id = c_sec

    # Verify all 24 documents are represented in order
    if seen_docs != expected_doc_order:
        missing_docs = set(expected_doc_order) - set(seen_docs)
        extra_docs = set(seen_docs) - set(expected_doc_order)
        if missing_docs:
            errors.append(f"Missing document IDs in chunk collection: {sorted(missing_docs)}")
        if extra_docs:
            errors.append(f"Unexpected document IDs in chunk collection: {sorted(extra_docs)}")

    # Verify each document contains all 6 sections
    for doc_id, s_list in seen_secs_for_doc.items():
        if s_list != valid_sections:
            missing_secs = set(valid_sections) - set(s_list)
            if missing_secs:
                errors.append(f"Document {doc_id} missing chunk(s) for section(s): {sorted(missing_secs)}")

    # Group chunks by document_id and section_id
    chunks_by_doc: dict[str, list[dict]] = {}
    for c in chunks:
        chunks_by_doc.setdefault(c["document_id"], []).append(c)

    # 4. Independent Three-Way Content, Metadata, Page, and Fact Verification
    assigned_facts_all: list[str] = []

    for doc_id in expected_doc_order:
        doc_chunks = chunks_by_doc.get(doc_id, [])
        if not doc_chunks:
            continue

        inv_entry = inventory.get(doc_id)
        if not inv_entry:
            continue

        outline = outlines.get(doc_id)
        if not outline:
            errors.append(f"Missing outline for {doc_id}")
            continue

        policy_entry = policy_docs.get(doc_id)
        if not policy_entry:
            errors.append(f"Missing access policy for {doc_id}")
            continue

        expected_sections = [s["section_id"] for s in outline.get("sections", [])]
        expected_sec_titles = {s["section_id"]: s["title"].strip() for s in outline.get("sections", [])}
        expected_sec_facts = {s["section_id"]: s.get("fact_ids", []) for s in outline.get("sections", [])}

        dept = inv_entry["owner_department"]
        fname = doc_id.lower().replace("-", "_")
        pdf_rel_path = f"data/pdfs/{dept}/{fname}_v1.pdf"
        src_rel_path = f"data/source/{dept}/{fname}.md"
        actual_pdf_file = pdf_dir / dept / f"{fname}_v1.pdf"
        actual_src_file = source_dir / dept / f"{fname}.md"

        # Check source Markdown existence and parse independently
        if not actual_src_file.exists():
            errors.append(f"Referenced source file does not exist: {actual_src_file}")
            continue

        try:
            src_meta, src_title, src_sections, src_fact_to_para = parse_source_markdown_document(actual_src_file)
        except Exception as exc:
            errors.append(f"Failed to parse source document {actual_src_file}: {exc}")
            continue

        # Check source Markdown front matter fields and values
        if not isinstance(src_meta, dict):
            errors.append(f"Source {doc_id} front matter is not a valid mapping in {actual_src_file.name}")
            src_meta = {}

        missing_fm = [f for f in REQUIRED_FRONTMATTER_FIELDS if f not in src_meta]
        if missing_fm:
            errors.append(
                f"Source {doc_id} front matter missing required field(s): {missing_fm} in {actual_src_file.name}"
            )

        for fld in REQUIRED_FRONTMATTER_FIELDS:
            if fld in src_meta:
                val = src_meta[fld]
                if val is None or (isinstance(val, str) and not val.strip()):
                    errors.append(
                        f"Source {doc_id} front matter field '{fld}' is null or empty in {actual_src_file.name}"
                    )

        # Document ID check
        if src_meta.get("document_id") != doc_id:
            errors.append(
                f"Source {doc_id} front matter document_id '{src_meta.get('document_id')}' != '{doc_id}' in {actual_src_file.name}"
            )

        # Document version check
        if src_meta.get("document_version") != "v1":
            errors.append(
                f"Source {doc_id} front matter document_version '{src_meta.get('document_version')}' != 'v1' in {actual_src_file.name}"
            )

        # Independent three-way title matching
        inv_title = inv_entry["title"].strip()
        yaml_title = str(src_meta.get("title", "")).strip() if src_meta.get("title") is not None else ""
        h1_title = src_title.strip()

        if not h1_title:
            errors.append(f"Source {doc_id} missing H1 title in {actual_src_file.name}")
        if yaml_title != inv_title:
            errors.append(
                f"Source {doc_id} YAML front matter title '{yaml_title}' != inventory title '{inv_title}' in {actual_src_file.name}"
            )
        if h1_title != inv_title:
            errors.append(
                f"Source {doc_id} H1 title '{h1_title}' != inventory title '{inv_title}' in {actual_src_file.name}"
            )
        if yaml_title != h1_title:
            errors.append(
                f"Source {doc_id} YAML front matter title '{yaml_title}' != H1 title '{h1_title}' in {actual_src_file.name}"
            )

        # Owner department check
        if src_meta.get("owner_department") != dept:
            errors.append(
                f"Source {doc_id} front matter owner_department '{src_meta.get('owner_department')}' != '{dept}' in {actual_src_file.name}"
            )

        # Classification check
        if src_meta.get("classification") != inv_entry["classification"].strip().lower():
            errors.append(
                f"Source {doc_id} front matter classification '{src_meta.get('classification')}' != '{inv_entry['classification'].strip().lower()}' in {actual_src_file.name}"
            )

        # Effective date normalization and check
        raw_eff = src_meta.get("effective_from")
        eff_str = None
        if isinstance(raw_eff, datetime.date) and not isinstance(raw_eff, bool):
            eff_str = raw_eff.strftime("%Y-%m-%d")
        elif isinstance(raw_eff, str):
            eff_str = raw_eff.strip()

        if eff_str != "2026-11-01":
            errors.append(
                f"Source {doc_id} front matter effective_from '{raw_eff}' != '2026-11-01' in {actual_src_file.name}"
            )

        # Source type check
        expected_src_type = inv_entry.get("source_type", "synthetic").strip()
        if src_meta.get("source_type") != expected_src_type:
            errors.append(
                f"Source {doc_id} front matter source_type '{src_meta.get('source_type')}' != '{expected_src_type}' in {actual_src_file.name}"
            )

        # Check source Markdown H2 section headings against approved document_outlines.yaml
        outline_secs = outline.get("sections", [])
        if len(src_sections) != len(outline_secs):
            errors.append(
                f"Document {doc_id} section count mismatch in {actual_src_file.name}: expected {len(outline_secs)}, got {len(src_sections)}"
            )
        else:
            for s_idx, s_info in enumerate(outline_secs):
                exp_sid = s_info["section_id"]
                exp_stitle = s_info["title"].strip()
                act_stitle = src_sections[s_idx][0].strip()
                if act_stitle != exp_stitle:
                    errors.append(
                        f"Document {doc_id} section {exp_sid} heading mismatch in {actual_src_file.name}: expected '{exp_stitle}', got '{act_stitle}'"
                    )

        # Check PDF existence and extract body text per page
        if not actual_pdf_file.exists():
            errors.append(f"Referenced PDF file does not exist: {actual_pdf_file}")
            continue

        actual_pdf_sha256 = hashlib.sha256(actual_pdf_file.read_bytes()).hexdigest().lower()

        try:
            page_texts, num_pages = extract_pdf_page_texts(
                actual_pdf_file,
                doc_id,
                inv_entry["title"].strip(),
                expected_sec_titles.get("S01", "Purpose and Scope"),
            )
        except Exception as exc:
            errors.append(f"Failed to extract text from PDF {actual_pdf_file}: {exc}")
            continue

        # Build forward-only page range offsets over combined PDF text
        norm_pages = [" ".join(pt.split()) for pt in page_texts]
        combined_pdf_text = " ".join(norm_pages)

        page_ranges: list[tuple[int, int]] = []
        curr_offset = 0
        for np in norm_pages:
            p_start_offset = curr_offset
            p_end_offset = curr_offset + len(np)
            page_ranges.append((p_start_offset, p_end_offset))
            curr_offset = p_end_offset + 1

        def _get_page(offset: int) -> int:
            for p_idx, (s, e) in enumerate(page_ranges, start=1):
                if s <= offset <= e:
                    return p_idx
            return len(page_ranges)

        expected_pos_pages: dict[tuple[str, int], tuple[int, int]] = {}
        cursor = 0
        pdf_align_error = False

        for sec_idx, sec_id in enumerate(expected_sections):
            sec_title = expected_sec_titles.get(sec_id, "")
            pos_st = combined_pdf_text.find(sec_title, cursor)
            if pos_st == -1:
                errors.append(f"Document {doc_id}: section title '{sec_title}' missing in extracted PDF text at offset {cursor}")
                pdf_align_error = True
                break
            cursor = pos_st + len(sec_title)

            if sec_idx < len(src_sections):
                src_sec_title, src_paras = src_sections[sec_idx]
                for p_idx, para in enumerate(src_paras):
                    pos_p = combined_pdf_text.find(para, cursor)
                    if pos_p == -1:
                        errors.append(f"Document {doc_id}: paragraph '{para[:40]}...' missing or altered in PDF text at offset {cursor}")
                        pdf_align_error = True
                        break
                    p_s = _get_page(pos_p)
                    p_e = _get_page(pos_p + len(para) - 1)
                    cursor = pos_p + len(para)
                    expected_pos_pages[(sec_id, p_idx)] = (p_s, p_e)
                if pdf_align_error:
                    break

        if not pdf_align_error:
            remainder = combined_pdf_text[cursor:].strip()
            if remainder:
                errors.append(f"Document {doc_id}: unauthorized extra text found in PDF: '{remainder[:50]}...'")

        # Group doc_chunks by section_id
        chunks_by_sec: dict[str, list[dict]] = {}
        for c in doc_chunks:
            chunks_by_sec.setdefault(c["section_id"], []).append(c)

        doc_reconstructed_text_parts: list[str] = []

        for sec_idx, sec_id in enumerate(expected_sections):
            sec_chunks = chunks_by_sec.get(sec_id, [])
            if not sec_chunks:
                continue

            sec_title = expected_sec_titles.get(sec_id, "")
            doc_reconstructed_text_parts.append(sec_title)

            # Reconstruct section paragraphs from chunk text
            rec_section_paras: list[str] = []
            for c in sec_chunks:
                text_val = c.get("text", "")
                c_paras = [p.strip() for p in text_val.split("\n\n") if p.strip()]
                norm_c_paras = [" ".join(p.split()) for p in c_paras]
                rec_section_paras.extend(norm_c_paras)

            # Compare reconstructed section paragraphs against source Markdown paragraphs
            if sec_idx < len(src_sections):
                src_sec_title, src_paras = src_sections[sec_idx]
                if len(rec_section_paras) != len(src_paras):
                    errors.append(
                        f"Document {doc_id} section {sec_id} paragraph count mismatch "
                        f"(chunks: {len(rec_section_paras)}, markdown: {len(src_paras)})"
                    )
                else:
                    for p_i, (cp, sp) in enumerate(zip(rec_section_paras, src_paras), start=1):
                        if cp != sp:
                            errors.append(
                                f"Document {doc_id} section {sec_id} paragraph {p_i} mismatch:\n"
                                f"  Chunk:    '{cp}'\n"
                                f"  Markdown: '{sp}'"
                            )

            # Validate each chunk in this section
            curr_sec_para_idx = 0
            for idx, c in enumerate(sec_chunks, start=1):
                chunk_id = c["chunk_id"]

                # Expected metadata
                if c["document_id"] != doc_id:
                    errors.append(f"Chunk {chunk_id} document_id '{c['document_id']}' != '{doc_id}'")
                if c["document_version"] != "v1":
                    errors.append(f"Chunk {chunk_id} document_version '{c['document_version']}' != 'v1'")
                if c["title"] != inv_entry["title"].strip():
                    errors.append(f"Chunk {chunk_id} title '{c['title']}' != '{inv_entry['title']}'")
                if c["owner_department"] != dept:
                    errors.append(f"Chunk {chunk_id} owner_department '{c['owner_department']}' != '{dept}'")
                if c["classification"] != inv_entry["classification"].strip().lower():
                    errors.append(f"Chunk {chunk_id} classification '{c['classification']}' != '{inv_entry['classification']}'")
                if c["effective_from"] != "2026-11-01":
                    errors.append(f"Chunk {chunk_id} effective_from '{c['effective_from']}' != '2026-11-01'")
                if c["source_type"] != "synthetic":
                    errors.append(f"Chunk {chunk_id} source_type '{c['source_type']}' != 'synthetic'")
                if c["section_id"] != sec_id:
                    errors.append(f"Chunk {chunk_id} section_id '{c['section_id']}' != '{sec_id}'")
                if c["section_title"] != sec_title:
                    errors.append(f"Chunk {chunk_id} section_title '{c['section_title']}' != '{sec_title}'")

                # Word limit check
                text_val = c.get("text", "")
                words = text_val.split()
                if len(words) > MAX_CHUNK_WORDS:
                    errors.append(f"Chunk {chunk_id} exceeds MAX_CHUNK_WORDS ({len(words)} > {MAX_CHUNK_WORDS})")

                # Check presentation leaks
                if "<!--" in text_val or "fact_id:" in text_val:
                    errors.append(f"Chunk {chunk_id} contains raw HTML/fact-marker comments in text")
                if "Aster Systems Internal Documentation" in text_val:
                    errors.append(f"Chunk {chunk_id} contains running footer text in body")
                if re.search(r"\bPage \d+ of \d+\b", text_val):
                    errors.append(f"Chunk {chunk_id} contains page numbering in body")
                if "Document ID:" in text_val and "Classification:" in text_val:
                    errors.append(f"Chunk {chunk_id} contains display metadata banner in body")

                # Restricted text isolation
                if c["classification"] != "restricted":
                    if "svc-portal" in text_val or "svc-auth" in text_val or "svc-billing" in text_val:
                        errors.append(f"Chunk {chunk_id} (non-restricted) leaks restricted service ownership text")
                    if "Performance Review Process" in text_val and doc_id != "HR-005":
                        errors.append(f"Chunk {chunk_id} leaks restricted document title")

                # Provenance fields
                if c["pdf_path"].replace("\\", "/") != pdf_rel_path:
                    errors.append(f"Chunk {chunk_id} pdf_path '{c['pdf_path']}' != '{pdf_rel_path}'")
                if c["source_path"].replace("\\", "/") != src_rel_path:
                    errors.append(f"Chunk {chunk_id} source_path '{c['source_path']}' != '{src_rel_path}'")
                if c["pdf_sha256"] != actual_pdf_sha256:
                    errors.append(f"Chunk {chunk_id} pdf_sha256 '{c['pdf_sha256']}' != actual '{actual_pdf_sha256}'")

                # Page reference validation
                p_start = c["page_start"]
                p_end = c["page_end"]
                chunk_individual_paras = [" ".join(p.split()) for p in text_val.split("\n\n") if p.strip()]
                num_c_paras = len(chunk_individual_paras)
                if p_start < 1 or p_end < p_start or p_end > num_pages:
                    errors.append(f"Chunk {chunk_id} invalid page range {p_start}-{p_end} (PDF has {num_pages} pages)")
                else:
                    first_pos = (sec_id, curr_sec_para_idx)
                    last_pos = (sec_id, curr_sec_para_idx + num_c_paras - 1)
                    if first_pos in expected_pos_pages and last_pos in expected_pos_pages:
                        exp_p_s = expected_pos_pages[first_pos][0]
                        exp_p_e = expected_pos_pages[last_pos][1]
                        if p_start != exp_p_s or p_end != exp_p_e:
                            errors.append(
                                f"Chunk {chunk_id} page range {p_start}-{p_end} != expected {exp_p_s}-{exp_p_e}"
                            )
                curr_sec_para_idx += num_c_paras

                # Access permissions check against access_policy.yaml
                expected_roles = sorted(policy_entry.get("allowed_roles", []))
                observed_roles = sorted(c.get("allowed_roles", []))
                if observed_roles != expected_roles:
                    errors.append(f"Chunk {chunk_id} allowed_roles {observed_roles} != expected {expected_roles}")
                if "document_admin" in observed_roles:
                    errors.append(f"Chunk {chunk_id} improperly grants read access to 'document_admin'")

                expected_depts = sorted(policy_entry.get("team_lead_departments", []))
                observed_depts = sorted(c.get("team_lead_departments", []))
                if observed_depts != expected_depts:
                    errors.append(f"Chunk {chunk_id} team_lead_departments {observed_depts} != expected {expected_depts}")

                # Fact IDs validation
                chunk_facts = c.get("fact_ids", [])
                for fid in chunk_facts:
                    if fid not in registry_facts:
                        errors.append(f"Chunk {chunk_id} assigns unknown fact_id '{fid}'")
                    elif registry_facts[fid]["source_doc_id"] != doc_id:
                        errors.append(f"Chunk {chunk_id} assigns fact_id '{fid}' belonging to {registry_facts[fid]['source_doc_id']}")
                    elif fid not in expected_sec_facts.get(sec_id, []):
                        errors.append(f"Chunk {chunk_id} assigns fact_id '{fid}' not designated for section {sec_id}")
                    assigned_facts_all.append(fid)

                # Append to reconstructed document
                doc_reconstructed_text_parts.append(text_val)

            # Fact-to-chunk exact mapping check for this section
            for fid in expected_sec_facts.get(sec_id, []):
                canonical_p = src_fact_to_para.get(fid)
                if not canonical_p:
                    errors.append(f"Fact {fid} missing canonical paragraph in source {doc_id} {sec_id}")
                    continue

                # Find which chunk(s) contain this complete paragraph
                matching_chunks = [
                    c for c in sec_chunks
                    if canonical_p in [" ".join(p.split()) for p in c.get("text", "").split("\n\n") if p.strip()]
                ]
                if len(matching_chunks) == 0:
                    errors.append(
                        f"Canonical fact {fid} paragraph was not found intact in any chunk of {doc_id} {sec_id}"
                    )
                elif len(matching_chunks) > 1:
                    errors.append(
                        f"Canonical fact {fid} paragraph appears in multiple chunks: {[c['chunk_id'] for c in matching_chunks]}"
                    )
                else:
                    target_chunk = matching_chunks[0]
                    if fid not in target_chunk.get("fact_ids", []):
                        errors.append(
                            f"Fact {fid} complete paragraph is in chunk {target_chunk['chunk_id']}, but {fid} is missing from its fact_ids"
                        )
                    for other_c in sec_chunks:
                        if other_c["chunk_id"] != target_chunk["chunk_id"] and fid in other_c.get("fact_ids", []):
                            errors.append(
                                f"Fact {fid} is assigned to chunk {other_c['chunk_id']}, but its complete paragraph is in {target_chunk['chunk_id']}"
                            )

        # Full-text reconstruction comparison against PDF
        reconstructed_doc_text = " ".join(" ".join(doc_reconstructed_text_parts).split())
        norm_full_pdf = combined_pdf_text
        if reconstructed_doc_text != norm_full_pdf:
            min_l = min(len(reconstructed_doc_text), len(norm_full_pdf))
            diff_idx = min_l
            for i in range(min_l):
                if reconstructed_doc_text[i] != norm_full_pdf[i]:
                    diff_idx = i
                    break
            s = max(0, diff_idx - 30)
            rec_snip = reconstructed_doc_text[s : min(len(reconstructed_doc_text), diff_idx + 40)]
            pdf_snip = norm_full_pdf[s : min(len(norm_full_pdf), diff_idx + 40)]
            errors.append(
                f"Document {doc_id} reconstructed chunk text does not match PDF text at char {diff_idx}:\n"
                f"  Chunk text: '{rec_snip}'\n"
                f"  PDF text:   '{pdf_snip}'"
            )

    # 5. Global Fact Assignment Validation
    if len(assigned_facts_all) != 72:
        errors.append(f"Expected 72 canonical fact assignments across corpus, got {len(assigned_facts_all)}")

    unique_assigned_facts = set(assigned_facts_all)
    if len(unique_assigned_facts) != len(assigned_facts_all):
        duplicates = [fid for fid in unique_assigned_facts if assigned_facts_all.count(fid) > 1]
        errors.append(f"Duplicate fact ID assignments found in chunk collection: {sorted(duplicates)}")

    missing_reg_facts = set(registry_facts.keys()) - unique_assigned_facts
    if missing_reg_facts:
        errors.append(f"Missing canonical fact IDs in chunk collection: {sorted(missing_reg_facts)}")

    return errors


def main() -> int:
    """CLI entrypoint for chunk validation."""
    chunks_path = sys.argv[1] if len(sys.argv) > 1 else None
    target_display = chunks_path if chunks_path else "data/chunks/v1_chunks.jsonl"
    print(f"Validating AsterCite v1 chunk corpus at '{target_display}'...")

    errors = validate_chunks(chunks_file_path=chunks_path)

    if errors:
        print(f"Validation FAILED with {len(errors)} error(s):", file=sys.stderr)
        for err in errors:
            print(f"  - {err}", file=sys.stderr)
        return 1

    print("Chunk validation PASSED: All 24 documents, 144 sections, 72 facts, metadata, and full-text verified.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
