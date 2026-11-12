"""Validator for Aster Systems original v1 Markdown knowledge documents.

Validates that Markdown source documents adhere to dataset specifications, including:
- Exact 24 source document files in approved departmental locations.
- Valid YAML front matter and required metadata fields.
- Effective date normalization (datetime.date vs string '2026-11-01').
- Heading levels (one # title, exactly 6 ## section titles matching outlines).
- Non-empty section content.
- Exactly 3 canonical fact markers in S02, S03, S04.
- Prevention of unfinished placeholders.
- Prevention of direct Markdown links to source documents.
- Prevention of information leaks (protected titles, restricted ID exposure).
- Prevention of raw database-style snake_case tokens in visible prose.
- Strict receipt requirement threshold validation for OPS-004.
- Relationship coverage and workflow direction consistency.
"""

import csv
import datetime
import os
from pathlib import Path
import re
import sys
import yaml

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_dataset import (
    EXPECTED_DEPARTMENTS,
    VALID_ROLES,
    check_document_access,
)

REQUIRED_METADATA_FIELDS = [
    "document_id",
    "document_version",
    "title",
    "owner_department",
    "classification",
    "effective_from",
    "source_type",
]

PLACEHOLDER_REGEX = re.compile(
    r"\b(TODO|TBD|FIXME|Lorem ipsum)\b|\[(?:instruction|template|insert|placeholder)",
    re.IGNORECASE,
)

MARKDOWN_LINK_REGEX = re.compile(
    r"\[([^\]]+)\]\(([^)]+\.(?:md|markdown))\)",
    re.IGNORECASE,
)

DOC_ID_REGEX = re.compile(r"\b([A-Z]{2,3}-\d{3})\b")

FACT_MARKER_REGEX = re.compile(
    r"<!--\s*fact_id:\s*([A-Za-z0-9_]+)\s*-->"
)

ANY_COMMENT_REGEX = re.compile(r"<!--(.*?)-->", re.DOTALL)

RAW_TOKEN_REGEX = re.compile(r"\b[a-z0-9]+_[a-z0-9]+(?:_[a-z0-9]+)*\b")

FORBIDDEN_RECEIPT_REGEX = re.compile(
    r"\b(equal to or exceeding|at least|500 or more|greater than or equal to)\b",
    re.IGNORECASE,
)


def load_specifications(spec_dir_path: Path | str = "data/spec") -> dict:
    """Load authoritative specification files for document validation."""
    spec_dir = Path(spec_dir_path)

    with open(spec_dir / "document_inventory.csv", "r", encoding="utf-8") as f:
        inventory = {row["document_id"]: row for row in csv.DictReader(f)}

    with open(spec_dir / "fact_registry.csv", "r", encoding="utf-8") as f:
        facts = {}
        for row in csv.DictReader(f):
            facts.setdefault(row["source_doc_id"], {})[row["fact_id"]] = row

    with open(spec_dir / "document_outlines.yaml", "r", encoding="utf-8") as f:
        raw_outlines = yaml.safe_load(f)
        outlines = {doc["document_id"]: doc for doc in raw_outlines}

    with open(spec_dir / "access_policy.yaml", "r", encoding="utf-8") as f:
        access_policy = yaml.safe_load(f)

    with open(spec_dir / "cross_references.csv", "r", encoding="utf-8") as f:
        cross_refs = list(csv.DictReader(f))

    outgoing_map = {}
    incoming_map = {}
    for cr in cross_refs:
        outgoing_map.setdefault(cr["from_doc"], []).append(cr)
        incoming_map.setdefault(cr["to_doc"], []).append(cr)

    return {
        "inventory": inventory,
        "facts": facts,
        "outlines": outlines,
        "access_policy": access_policy,
        "cross_refs": cross_refs,
        "outgoing_map": outgoing_map,
        "incoming_map": incoming_map,
    }


def normalize_and_check_date(raw_date: any, doc_id: str, errors: list[str]) -> bool:
    """Normalize supported date types and require 2026-11-01."""
    if raw_date is None or (isinstance(raw_date, str) and not raw_date.strip()):
        errors.append(f"Document {doc_id} missing or empty effective_from date")
        return False

    if isinstance(raw_date, datetime.date):
        normalized = raw_date.isoformat()
    elif isinstance(raw_date, str):
        normalized = raw_date.strip()
    else:
        errors.append(
            f"Document {doc_id} effective_from has unsupported type: {type(raw_date).__name__}"
        )
        return False

    if normalized != "2026-11-01":
        errors.append(
            f"Document {doc_id} effective_from date must be '2026-11-01', got: '{normalized}'"
        )
        return False

    return True


def get_protected_titles_for_doc(
    doc_id: str, inventory: dict, access_policy: dict
) -> dict[str, str]:
    """Find titles of documents more restricted than doc_id."""
    doc_meta = inventory[doc_id]
    raw_roles = (doc_meta.get("allowed_roles") or "").split("|")
    doc_roles = [r.strip() for r in raw_roles if r.strip()]
    doc_dept = doc_meta.get("owner_department")
    policy_docs = access_policy.get("documents", {})

    protected = {}
    for other_id, other_meta in inventory.items():
        if other_id == doc_id:
            continue
        other_perm = policy_docs.get(other_id, {})
        other_class = other_meta.get("classification")

        # Check if any role authorized for doc_id lacks access to other_id
        for role in doc_roles:
            if role == "document_admin":
                continue
            dept_arg = doc_dept if role == "team_lead" else None
            if not check_document_access(other_perm, [role], other_class, dept_arg):
                protected[other_id] = other_meta["title"].strip()
                break

    return protected


def validate_single_document(
    file_path: Path,
    expected_doc_id: str,
    specs: dict,
    errors: list[str],
) -> None:
    """Validate structure, content, metadata, facts, and relationships for a single file."""
    inventory = specs["inventory"]
    facts = specs["facts"]
    outlines = specs["outlines"]
    access_policy = specs["access_policy"]
    outgoing_map = specs["outgoing_map"]
    incoming_map = specs["incoming_map"]

    if not file_path.exists():
        errors.append(f"Missing source document: {file_path}")
        return

    try:
        with open(file_path, "r", encoding="utf-8") as f:
            content = f.read()
    except Exception as e:
        errors.append(f"Cannot read document file {file_path}: {e}")
        return

    # Check YAML front matter
    norm_content = content.lstrip("\ufeff")
    if not norm_content.startswith("---"):
        errors.append(f"Document {file_path.name} front matter must start at the beginning of the file")
        return

    if not re.match(r"^---\r?\n", norm_content):
        errors.append(f"Document {file_path.name} malformed opening front matter delimiter")
        return

    fm_match = re.match(r"^---\r?\n(.*?)\r?\n---(?:\r?\n(.*))?$", norm_content, re.DOTALL)
    if not fm_match:
        errors.append(f"Document {file_path.name} missing closing front matter delimiter")
        return

    raw_yaml = fm_match.group(1)
    body = fm_match.group(2) or ""

    try:
        metadata = yaml.safe_load(raw_yaml)
    except Exception as e:
        errors.append(f"Document {file_path.name} YAML front matter parse error: {e}")
        return

    if not isinstance(metadata, dict):
        errors.append(f"Document {file_path.name} front matter must be a dictionary/mapping")
        return

    # 1. Required metadata checks
    for req_field in REQUIRED_METADATA_FIELDS:
        if req_field not in metadata:
            errors.append(f"Document {expected_doc_id} missing metadata field: {req_field}")

    for key in metadata:
        if key not in REQUIRED_METADATA_FIELDS:
            errors.append(f"Document {expected_doc_id} contains unexpected metadata field: {key}")

    doc_id = metadata.get("document_id")
    if doc_id != expected_doc_id:
        errors.append(f"{file_path.name} metadata document_id '{doc_id}' != expected '{expected_doc_id}'")

    inv_meta = inventory.get(expected_doc_id)
    if not inv_meta:
        errors.append(f"Unknown document ID in inventory: {expected_doc_id}")
        return

    doc_ver = metadata.get("document_version")
    if doc_ver != "v1":
        errors.append(f"Document {expected_doc_id} metadata document_version must be 'v1', got: '{doc_ver}'")

    title = metadata.get("title")
    expected_title = inv_meta["title"].strip()
    if title != expected_title:
        errors.append(f"Document {expected_doc_id} metadata title '{title}' != inventory '{expected_title}'")

    owner_dept = metadata.get("owner_department")
    expected_dept = inv_meta["owner_department"].strip()
    if owner_dept != expected_dept:
        errors.append(f"Document {expected_doc_id} metadata owner_department '{owner_dept}' != inventory '{expected_dept}'")

    classification = metadata.get("classification")
    expected_class = inv_meta["classification"].strip()
    if classification != expected_class:
        errors.append(f"Document {expected_doc_id} metadata classification '{classification}' != inventory '{expected_class}'")

    source_type = metadata.get("source_type")
    if source_type != "synthetic":
        errors.append(f"Document {expected_doc_id} metadata source_type must be 'synthetic', got: '{source_type}'")

    normalize_and_check_date(metadata.get("effective_from"), expected_doc_id, errors)

    # 2. Level 1 title check
    h1_matches = re.findall(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if len(h1_matches) != 1:
        errors.append(f"Document {expected_doc_id} must have exactly one level-1 title, found {len(h1_matches)}")
    elif h1_matches[0].strip() != expected_title:
        errors.append(f"Document {expected_doc_id} level-1 title '{h1_matches[0]}' != expected '{expected_title}'")

    # 3. Level 2 sections check
    outline = outlines.get(expected_doc_id)
    if not outline:
        errors.append(f"Document {expected_doc_id} outline missing from document_outlines.yaml")
        return

    h2_matches = [m.strip() for m in re.findall(r"^##\s+(.+)$", body, flags=re.MULTILINE)]
    expected_sections = outline.get("sections", [])
    expected_h2 = [s["title"].strip() for s in expected_sections]

    if len(h2_matches) != 6:
        errors.append(f"Document {expected_doc_id} must have exactly 6 level-2 sections, found {len(h2_matches)}")
    elif h2_matches != expected_h2:
        errors.append(f"Document {expected_doc_id} section titles mismatch.\nFound: {h2_matches}\nExpected: {expected_h2}")

    # Split body into sections
    raw_sections = re.split(r"^##\s+.+$", body, flags=re.MULTILINE)
    section_bodies = raw_sections[1:] if len(raw_sections) > 1 else []

    if len(section_bodies) != 6:
        errors.append(f"Document {expected_doc_id} section split failed: found {len(section_bodies)} sections, expected 6")
        return

    # Check non-empty content
    for idx, (sec_meta, sec_body) in enumerate(zip(expected_sections, section_bodies)):
        clean_text = sec_body.strip()
        text_without_markers = FACT_MARKER_REGEX.sub("", clean_text).strip()
        if not text_without_markers:
            errors.append(f"Document {expected_doc_id} section {sec_meta['section_id']} ('{sec_meta['title']}') is empty")

    # 4. Fact markers validation
    all_markers = FACT_MARKER_REGEX.findall(body)
    all_comments = ANY_COMMENT_REGEX.findall(body)

    for comm in all_comments:
        if "fact" in comm.lower() and not re.match(r"^\s*fact_id:\s*[A-Za-z0-9_]+\s*$", comm):
            errors.append(f"Document {expected_doc_id} has malformed fact marker: <!--{comm}-->")

    if len(all_markers) != 3:
        errors.append(f"Document {expected_doc_id} must contain exactly 3 fact markers, found {len(all_markers)}")

    prefix = expected_doc_id.replace("-", "")
    exp_f01 = f"{prefix}_F01"
    exp_f02 = f"{prefix}_F02"
    exp_f03 = f"{prefix}_F03"
    expected_doc_facts = [exp_f01, exp_f02, exp_f03]

    if len(all_markers) == len(set(all_markers)):
        for marker in all_markers:
            if marker not in expected_doc_facts:
                errors.append(f"Document {expected_doc_id} contains unexpected fact marker: {marker}")
    else:
        errors.append(f"Document {expected_doc_id} contains duplicate fact markers: {all_markers}")

    # Section-specific marker placement
    s01_markers = FACT_MARKER_REGEX.findall(section_bodies[0])
    if s01_markers:
        errors.append(f"Document {expected_doc_id} S01 must not contain fact markers, found: {s01_markers}")

    s02_markers = FACT_MARKER_REGEX.findall(section_bodies[1])
    if s02_markers != [exp_f01]:
        errors.append(f"Document {expected_doc_id} S02 fact marker mismatch: {s02_markers} != [{exp_f01}]")

    s03_markers = FACT_MARKER_REGEX.findall(section_bodies[2])
    if s03_markers != [exp_f02]:
        errors.append(f"Document {expected_doc_id} S03 fact marker mismatch: {s03_markers} != [{exp_f02}]")

    s04_markers = FACT_MARKER_REGEX.findall(section_bodies[3])
    if s04_markers != [exp_f03]:
        errors.append(f"Document {expected_doc_id} S04 fact marker mismatch: {s04_markers} != [{exp_f03}]")

    s05_markers = FACT_MARKER_REGEX.findall(section_bodies[4])
    if s05_markers:
        errors.append(f"Document {expected_doc_id} S05 must not contain fact markers, found: {s05_markers}")

    s06_markers = FACT_MARKER_REGEX.findall(section_bodies[5])
    if s06_markers:
        errors.append(f"Document {expected_doc_id} S06 must not contain fact markers, found: {s06_markers}")

    # Check non-empty paragraph following each marker in S02, S03, S04
    for sec_idx, exp_fid in [(1, exp_f01), (2, exp_f02), (3, exp_f03)]:
        sec_text = section_bodies[sec_idx]
        marker_str = f"<!-- fact_id: {exp_fid} -->"
        if marker_str in sec_text:
            after_marker = sec_text.split(marker_str, 1)[1].strip()
            if not after_marker:
                errors.append(f"Document {expected_doc_id} fact {exp_fid} is not followed by a factual statement")

    # 5. Quality, Formatting, and Safety checks
    if PLACEHOLDER_REGEX.search(body):
        match = PLACEHOLDER_REGEX.search(body).group(0)
        errors.append(f"Document {expected_doc_id} contains placeholder or unfinished text: '{match}'")

    # Raw registry token check in visible Markdown prose
    clean_prose = ANY_COMMENT_REGEX.sub("", body)
    raw_tokens = RAW_TOKEN_REGEX.findall(clean_prose)
    for token in raw_tokens:
        errors.append(
            f"Document {expected_doc_id} contains raw registry token '{token}' in visible prose"
        )

    # Specific strict threshold check for OPS-004
    if expected_doc_id == "OPS-004":
        s03_text = section_bodies[2]
        has_strict_above = bool(
            re.search(r"\babove\s+(?:INR\s+500|500\s+inr)\b", s03_text, re.IGNORECASE)
        )
        forbidden_phrases = FORBIDDEN_RECEIPT_REGEX.findall(s03_text)
        if forbidden_phrases:
            errors.append(
                f"Document OPS-004 contains forbidden receipt threshold phrasing in S03: {forbidden_phrases}"
            )
        if not has_strict_above:
            errors.append(
                "Document OPS-004 S03 must specify that receipts are required for claims above INR 500"
            )

    # Direct markdown links to source documents
    direct_links = MARKDOWN_LINK_REGEX.findall(body)
    if direct_links:
        for link_text, link_target in direct_links:
            errors.append(f"Document {expected_doc_id} contains forbidden direct Markdown link to source document: '{link_target}'")

    # Protected titles check (Information leak prevention)
    protected_titles = get_protected_titles_for_doc(expected_doc_id, inventory, access_policy)
    for prot_id, prot_title in protected_titles.items():
        if prot_title.lower() in body.lower():
            errors.append(f"Document {expected_doc_id} exposes protected document title '{prot_title}' (from {prot_id})")

    # S05 section body
    s05_text = section_bodies[4]

    # Map protected document IDs required by canonical facts to their approved sections
    allowed_fact_sections = {}
    doc_outline = outlines.get(expected_doc_id, {})
    fact_to_section = {}
    for sec in doc_outline.get("sections", []):
        s_id = sec.get("section_id")
        for fid in sec.get("fact_ids", []):
            fact_to_section[fid] = s_id

    for fid, f_meta in facts.get(expected_doc_id, {}).items():
        val = f_meta.get("exact_value", "") or ""
        sec_id = fact_to_section.get(fid)
        if sec_id:
            for p_id in re.findall(r"[A-Z]{2,3}-\d{3}", val):
                allowed_fact_sections.setdefault(p_id, set()).add(sec_id)

    # Check for exposure of protected document IDs across sections and preamble
    preamble = raw_sections[0] if raw_sections else ""
    for prot_id in protected_titles:
        if prot_id in preamble:
            errors.append(
                f"Document {expected_doc_id} exposes protected document ID '{prot_id}' in title or preamble"
            )

    for sec_meta, sec_body in zip(expected_sections, section_bodies):
        current_sec_id = sec_meta["section_id"]
        for prot_id in protected_titles:
            if prot_id in sec_body:
                if current_sec_id not in allowed_fact_sections.get(prot_id, set()):
                    errors.append(
                        f"Document {expected_doc_id} exposes protected document ID '{prot_id}' in section {current_sec_id}"
                    )

    # 6. Document references, coverage, and relationship direction checks
    all_doc_ids = set(inventory.keys())
    s05_refs = DOC_ID_REGEX.findall(s05_text)
    outgoing_targets = {cr["to_doc"] for cr in outgoing_map.get(expected_doc_id, [])}
    incoming_sources = {cr["from_doc"] for cr in incoming_map.get(expected_doc_id, [])}

    # Relationship coverage: ensure safe outgoing destinations are referenced in S05
    for cr in outgoing_map.get(expected_doc_id, []):
        target_id = cr["to_doc"]
        if target_id not in protected_titles:
            if target_id not in s05_text:
                errors.append(
                    f"Document {expected_doc_id} S05 is missing required outgoing relationship reference to {target_id}"
                )

    for ref_id in s05_refs:
        if ref_id == expected_doc_id:
            errors.append(f"Document {expected_doc_id} S05 self-references itself")
            continue

        if ref_id not in all_doc_ids:
            errors.append(f"Document {expected_doc_id} references unknown document ID: {ref_id}")
            continue

        if ref_id in outgoing_targets:
            # Valid approved outgoing relationship
            continue

        if ref_id in incoming_sources:
            # Check if described as incoming
            sentences = re.split(r"[.\n]", s05_text)
            ref_sentence = next((s for s in sentences if ref_id in s), "")
            is_incoming_described = bool(
                re.search(
                    r"\b(incoming|receives?|received|input\s+from|referred\s+by|referenced\s+by)\b",
                    ref_sentence,
                    re.IGNORECASE,
                )
            )
            has_outgoing_phrasing = bool(
                re.search(
                    r"\b(outgoing\s+(?:workflow|dependency|escalation)|submits?\s+to|escalates?\s+to|depends?\s+on|follows?\s+(?!up\b))\b",
                    ref_sentence,
                    re.IGNORECASE,
                )
            )
            if has_outgoing_phrasing or not is_incoming_described:
                errors.append(
                    f"Document {expected_doc_id} contains reversed or unapproved outgoing workflow reference to incoming document {ref_id}"
                )
            continue

        # ref_id is neither in outgoing nor incoming
        errors.append(
            f"Document {expected_doc_id} contains unapproved document reference to {ref_id}"
        )

    # General check: any unknown document IDs across entire document
    all_body_refs = DOC_ID_REGEX.findall(body)
    for ref_id in all_body_refs:
        if ref_id not in all_doc_ids:
            errors.append(f"Document {expected_doc_id} references unknown document ID: {ref_id}")


def validate_documents(
    source_dir_path: Path | str = "data/source",
    spec_dir_path: Path | str = "data/spec",
) -> list[str]:
    """Validate all 24 source documents against specifications."""
    source_dir = Path(source_dir_path)
    spec_dir = Path(spec_dir_path)
    errors: list[str] = []

    if not spec_dir.exists():
        errors.append(f"Specification directory not found: {spec_dir}")
        return errors

    if not source_dir.exists():
        errors.append(f"Source directory not found: {source_dir}")
        return errors

    try:
        specs = load_specifications(spec_dir)
    except Exception as e:
        errors.append(f"Failed to load specifications: {e}")
        return errors

    inventory = specs["inventory"]

    # 1. Check all 24 expected files exist
    expected_files: dict[str, Path] = {}
    for doc_id, meta in inventory.items():
        dept = meta["owner_department"]
        filename = f"{doc_id.lower().replace('-', '_')}.md"
        expected_files[doc_id] = source_dir / dept / filename

    for doc_id, file_path in expected_files.items():
        if not file_path.exists():
            rel_path = file_path.relative_to(source_dir) if file_path.is_relative_to(source_dir) else file_path
            errors.append(f"Missing source document: {rel_path}")

    # 2. Check for unexpected Markdown files
    all_md_files = list(source_dir.glob("**/*.md"))
    expected_path_set = {p.resolve() for p in expected_files.values()}

    for md_file in all_md_files:
        if md_file.resolve() not in expected_path_set:
            rel_path = md_file.relative_to(source_dir) if md_file.is_relative_to(source_dir) else md_file
            errors.append(f"Unexpected source document: {rel_path}")

    # 3. Validate each document in detail
    for doc_id, file_path in expected_files.items():
        if file_path.exists():
            validate_single_document(file_path, doc_id, specs, errors)

    return errors


def main() -> int:
    """CLI entrypoint for document validation."""
    print("Validating 24 Aster Systems knowledge documents...")
    errors = validate_documents()

    if errors:
        print(f"Document validation failed with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        return 1

    print("Document validation passed: 24 v1 Markdown documents, 144 sections, 72 fact markers.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
