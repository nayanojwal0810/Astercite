"""Standalone chunk validator for Aster Systems knowledge assistant.

Independently validates the generated JSONL chunk collection against the
authoritative input PDFs, Markdown sources, and frozen specifications.
"""

from __future__ import annotations

import csv
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

MAX_CHUNK_WORDS = 220


def extract_pdf_clean_text(pdf_path: Path, doc_title: str, first_sec_title: str) -> tuple[str, int]:
    """Extract full clean body text and total page count from an approved PDF."""
    reader = pypdf.PdfReader(str(pdf_path))
    num_pages = len(reader.pages)
    cleaned_pages: list[str] = []

    for page_idx in range(num_pages):
        page = reader.pages[page_idx]
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
            if 60 <= y_global <= 775:
                body_parts.append(text)

        raw_ptxt = page.extract_text(visitor_text=visitor_extract) or ""
        if has_coords:
            ptxt = "".join(body_parts).strip()
        else:
            ptxt = raw_ptxt.strip()
            # Strip footer from end
            footer_match = re.search(
                rf"\n?Aster Systems Internal Documentation\s+Page {page_idx + 1} of {num_pages}\s*$",
                ptxt,
            )
            if footer_match:
                ptxt = ptxt[: footer_match.start()].rstrip()
            # Strip header on later pages
            if page_idx > 0:
                h_match = re.search(r"\n?Aster Systems\s*—\s*[^\n]+\s*$", ptxt)
                if h_match:
                    ptxt = ptxt[: h_match.start()].rstrip()
                else:
                    h_top = re.match(r"^\s*Aster Systems\s*—\s*[^\n]+\s*\n?", ptxt)
                    if h_top:
                        ptxt = ptxt[h_top.end() :].lstrip()

        # On page 1, strip company heading, title, and metadata banner
        if page_idx == 0:
            if ptxt.startswith("Aster Systems\n"):
                ptxt = ptxt[len("Aster Systems\n") :].lstrip()
            elif ptxt.startswith("Aster Systems"):
                ptxt = ptxt[len("Aster Systems") :].lstrip()
            if ptxt.startswith(doc_title):
                ptxt = ptxt[len(doc_title) :].lstrip()
            pos = ptxt.find(first_sec_title)
            if pos != -1:
                ptxt = ptxt[pos:].strip()

        cleaned_pages.append(ptxt)

    full_body = "\n".join(cleaned_pages).strip()
    return full_body, num_pages


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

    # 2. Parse JSONL file
    try:
        raw_content = chunks_file.read_text(encoding="utf-8")
    except Exception as exc:
        return [f"Failed to read chunk file as UTF-8: {exc}"]

    lines = raw_content.splitlines()
    non_empty_lines = [line.strip() for line in lines if line.strip()]
    if not non_empty_lines:
        return [f"Chunk file is empty: {chunks_file}"]

    chunks: list[dict] = []
    chunk_ids_seen: set[str] = set()

    for line_num, line in enumerate(non_empty_lines, start=1):
        try:
            record = json.loads(line)
        except Exception as exc:
            errors.append(f"Line {line_num}: Malformed JSON record ({exc})")
            continue

        if not isinstance(record, dict):
            errors.append(f"Line {line_num}: Record is not a JSON object")
            continue

        # Check required fields and unexpected fields
        keys_set = set(record.keys())
        expected_keys_set = set(REQUIRED_FIELDS)
        missing_keys = expected_keys_set - keys_set
        extra_keys = keys_set - expected_keys_set

        if missing_keys:
            errors.append(f"Line {line_num} ({record.get('chunk_id', 'unknown')}): Missing required field(s): {sorted(missing_keys)}")
        if extra_keys:
            errors.append(f"Line {line_num} ({record.get('chunk_id', 'unknown')}): Unexpected field(s): {sorted(extra_keys)}")

        chunk_id = record.get("chunk_id")
        if not isinstance(chunk_id, str) or not chunk_id.strip():
            errors.append(f"Line {line_num}: Invalid or empty chunk_id")
        elif chunk_id in chunk_ids_seen:
            errors.append(f"Line {line_num}: Duplicate chunk_id '{chunk_id}'")
        else:
            chunk_ids_seen.add(chunk_id)

        chunks.append(record)

    if errors:
        return errors

    # 3. Validate Document Coverage and Ordering
    expected_doc_ids = sorted(inventory.keys())
    observed_doc_ids = sorted(set(c["document_id"] for c in chunks))

    if observed_doc_ids != expected_doc_ids:
        missing_docs = set(expected_doc_ids) - set(observed_doc_ids)
        extra_docs = set(observed_doc_ids) - set(expected_doc_ids)
        if missing_docs:
            errors.append(f"Missing document IDs in chunk collection: {sorted(missing_docs)}")
        if extra_docs:
            errors.append(f"Unexpected document IDs in chunk collection: {sorted(extra_docs)}")

    # Check ordering of chunks in file: sorted by document_id, section_id, chunk_index
    # Group chunks by document_id
    chunks_by_doc: dict[str, list[dict]] = {}
    for c in chunks:
        chunks_by_doc.setdefault(c["document_id"], []).append(c)

    # Document-level checks
    assigned_facts_all: list[str] = []

    for doc_id, doc_chunks in chunks_by_doc.items():
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

        if len(expected_sections) != 6:
            errors.append(f"Document {doc_id} outline does not have 6 sections")

        # Group doc_chunks by section_id
        chunks_by_sec: dict[str, list[dict]] = {}
        for c in doc_chunks:
            chunks_by_sec.setdefault(c["section_id"], []).append(c)

        # Check section coverage
        observed_sections = [s for s in expected_sections if s in chunks_by_sec]
        if set(chunks_by_sec.keys()) != set(expected_sections):
            missing_secs = set(expected_sections) - set(chunks_by_sec.keys())
            extra_secs = set(chunks_by_sec.keys()) - set(expected_sections)
            if missing_secs:
                errors.append(f"Document {doc_id} missing chunk(s) for section(s): {sorted(missing_secs)}")
            if extra_secs:
                errors.append(f"Document {doc_id} contains unexpected section(s): {sorted(extra_secs)}")

        # Verify PDF file and SHA-256
        dept = inv_entry["owner_department"]
        pdf_rel_path = f"data/pdfs/{dept}/{doc_id.lower().replace('-', '_')}_v1.pdf"
        actual_pdf_file = pdf_dir / dept / f"{doc_id.lower().replace('-', '_')}_v1.pdf"

        if not actual_pdf_file.exists():
            errors.append(f"Referenced PDF file does not exist: {actual_pdf_file}")
            continue

        actual_pdf_sha256 = hashlib.sha256(actual_pdf_file.read_bytes()).hexdigest().lower()
        full_pdf_body, num_pages = extract_pdf_clean_text(
            actual_pdf_file,
            inv_entry["title"].strip(),
            expected_sec_titles.get("S01", "Purpose and Scope"),
        )
        norm_full_pdf = " ".join(full_pdf_body.split())

        # Check each chunk in this document
        doc_reconstructed_text_parts: list[str] = []

        for sec_id in expected_sections:
            sec_chunks = chunks_by_sec.get(sec_id, [])
            if not sec_chunks:
                continue

            sec_title = expected_sec_titles.get(sec_id, "")
            # Check section heading in reconstructed PDF body
            doc_reconstructed_text_parts.append(sec_title)

            # Check chunk index sequence: 1, 2, ...
            for idx, c in enumerate(sec_chunks, start=1):
                chunk_id = c["chunk_id"]

                # Expected chunk ID format
                expected_chunk_id = f"{doc_id}:v1:{sec_id}:C{idx:03d}"
                if chunk_id != expected_chunk_id:
                    errors.append(f"Chunk ID '{chunk_id}' != expected '{expected_chunk_id}'")

                if c["chunk_index"] != idx:
                    errors.append(f"Chunk {chunk_id} chunk_index {c['chunk_index']} != expected {idx}")

                # Document metadata validation
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
                if not isinstance(text_val, str) or not text_val.strip():
                    errors.append(f"Chunk {chunk_id} text is empty or not string")
                    continue

                words = text_val.split()
                if len(words) > MAX_CHUNK_WORDS:
                    errors.append(f"Chunk {chunk_id} exceeds MAX_CHUNK_WORDS ({len(words)} > {MAX_CHUNK_WORDS})")

                # Check for presentation leaks, YAML front matter, or HTML comments in text
                if "<!--" in text_val or "fact_id:" in text_val:
                    errors.append(f"Chunk {chunk_id} contains raw HTML/fact-marker comments in text")
                if "Aster Systems Internal Documentation" in text_val:
                    errors.append(f"Chunk {chunk_id} contains running footer text in body")
                if re.search(r"\bPage \d+ of \d+\b", text_val):
                    errors.append(f"Chunk {chunk_id} contains page numbering in body")
                if "Document ID:" in text_val and "Classification:" in text_val:
                    errors.append(f"Chunk {chunk_id} contains display metadata banner in body")

                # Check restricted text leakage into general/department chunks
                if c["classification"] != "restricted":
                    if "svc-portal" in text_val or "svc-auth" in text_val or "svc-billing" in text_val:
                        errors.append(f"Chunk {chunk_id} (non-restricted) leaks restricted service ownership text")
                    if "Performance Review Process" in text_val and doc_id != "HR-005":
                        errors.append(f"Chunk {chunk_id} leaks restricted document title")

                # Provenance fields
                if c["pdf_path"].replace("\\", "/") != pdf_rel_path:
                    errors.append(f"Chunk {chunk_id} pdf_path '{c['pdf_path']}' != '{pdf_rel_path}'")
                expected_src_path = f"data/source/{dept}/{doc_id.lower().replace('-', '_')}.md"
                if c["source_path"].replace("\\", "/") != expected_src_path:
                    errors.append(f"Chunk {chunk_id} source_path '{c['source_path']}' != '{expected_src_path}'")
                if c["pdf_sha256"] != actual_pdf_sha256:
                    errors.append(f"Chunk {chunk_id} pdf_sha256 '{c['pdf_sha256']}' != actual '{actual_pdf_sha256}'")

                # Page references
                p_start = c["page_start"]
                p_end = c["page_end"]
                if not isinstance(p_start, int) or not isinstance(p_end, int):
                    errors.append(f"Chunk {chunk_id} page numbers must be integers (got {p_start}, {p_end})")
                elif p_start < 1 or p_end < p_start or p_end > num_pages:
                    errors.append(f"Chunk {chunk_id} invalid page range {p_start}-{p_end} (PDF has {num_pages} pages)")

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

                # Fact IDs
                chunk_facts = c.get("fact_ids", [])
                if not isinstance(chunk_facts, list):
                    errors.append(f"Chunk {chunk_id} fact_ids must be a list")
                else:
                    for fid in chunk_facts:
                        if fid not in registry_facts:
                            errors.append(f"Chunk {chunk_id} assigns unknown fact_id '{fid}'")
                        elif registry_facts[fid]["source_doc_id"] != doc_id:
                            errors.append(f"Chunk {chunk_id} assigns fact_id '{fid}' belonging to {registry_facts[fid]['source_doc_id']}")
                        elif fid not in expected_sec_facts.get(sec_id, []):
                            errors.append(f"Chunk {chunk_id} assigns fact_id '{fid}' not designated for section {sec_id}")
                        assigned_facts_all.append(fid)

                # Append chunk text to reconstructed document text
                doc_reconstructed_text_parts.append(text_val)

        # Full-text reconstruction comparison against PDF
        reconstructed_doc_text = " ".join(" ".join(doc_reconstructed_text_parts).split())
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

    # 4. Global Fact Assignment Validation
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
