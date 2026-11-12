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


def load_specifications(spec_dir_path: Path | str = "data/spec") -> dict:
    spec_dir = Path(spec_dir_path)

    with open(spec_dir / "document_inventory.csv", "r", encoding="utf-8") as f:
        inventory = {row["document_id"]: row for row in csv.DictReader(f)}

    with open(spec_dir / "fact_registry.csv", "r", encoding="utf-8") as f:
        facts = {}
        for row in csv.DictReader(f):
            facts.setdefault(row["source_doc_id"], {})[row["fact_id"]] = row

    with open(spec_dir / "document_outlines.yaml", "r", encoding="utf-8") as f:
        outlines = {item["document_id"]: item for item in yaml.safe_load(f)}

    with open(spec_dir / "access_policy.yaml", "r", encoding="utf-8") as f:
        access_policy = yaml.safe_load(f)

    with open(spec_dir / "cross_references.csv", "r", encoding="utf-8") as f:
        cross_refs = list(csv.DictReader(f))

    outgoing_map: dict[str, list[dict]] = {}
    incoming_map: dict[str, list[dict]] = {}
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
                protected[other_id] = other_meta["title"]
                break

    return protected


def validate_single_document(
    file_path: Path,
    expected_doc_id: str,
    specs: dict,
    errors: list[str],
) -> None:
    filename = file_path.name
    inventory = specs["inventory"]
    facts = specs["facts"]
    outlines = specs["outlines"]
    access_policy = specs["access_policy"]
    outgoing_map = specs["outgoing_map"]
    incoming_map = specs["incoming_map"]

    if expected_doc_id not in inventory:
        errors.append(f"Unexpected document ID: {expected_doc_id}")
        return

    doc_meta = inventory[expected_doc_id]
    outline = outlines.get(expected_doc_id)
    if not outline:
        errors.append(f"Missing outline specification for {expected_doc_id}")
        return

    try:
        content = file_path.read_text(encoding="utf-8")
    except Exception as e:
        errors.append(f"Failed to read {file_path}: {e}")
        return

    # 1. Front matter extraction
    if not content.startswith("---"):
        errors.append(f"{filename}: File must begin with YAML front matter ('---')")
        return

    parts = content.split("---", 2)
    if len(parts) < 3:
        errors.append(f"{filename}: Malformed YAML front matter (missing closing '---')")
        return

    front_matter_raw = parts[1]
    body = parts[2]

    try:
        meta = yaml.safe_load(front_matter_raw)
    except Exception as e:
        errors.append(f"{filename}: YAML front matter failed to parse: {e}")
        return

    if not isinstance(meta, dict):
        errors.append(f"{filename}: YAML front matter must be a dictionary")
        return

    # Check required metadata fields
    for field in REQUIRED_METADATA_FIELDS:
        if field not in meta:
            errors.append(f"Document {expected_doc_id} missing metadata field: {field}")

    for field in meta:
        if field not in REQUIRED_METADATA_FIELDS:
            errors.append(f"Document {expected_doc_id} has unexpected metadata field: {field}")

    # Check metadata values
    doc_id = meta.get("document_id")
    if doc_id != expected_doc_id:
        errors.append(f"{filename} metadata document_id '{doc_id}' != expected '{expected_doc_id}'")

    if meta.get("document_version") != "v1":
        errors.append(f"Document {expected_doc_id} metadata document_version must be 'v1', got: '{meta.get('document_version')}'")

    if meta.get("title") != doc_meta["title"]:
        errors.append(f"Document {expected_doc_id} metadata title '{meta.get('title')}' != inventory '{doc_meta['title']}'")

    if meta.get("owner_department") != doc_meta["owner_department"]:
        errors.append(f"Document {expected_doc_id} metadata owner_department '{meta.get('owner_department')}' != inventory '{doc_meta['owner_department']}'")

    if meta.get("classification") != doc_meta["classification"]:
        errors.append(f"Document {expected_doc_id} metadata classification '{meta.get('classification')}' != inventory '{doc_meta['classification']}'")

    if meta.get("source_type") != "synthetic":
        errors.append(f"Document {expected_doc_id} metadata source_type must be 'synthetic', got: '{meta.get('source_type')}'")

    normalize_and_check_date(meta.get("effective_from"), expected_doc_id, errors)

    # 2. Level 1 title check
    h1_matches = re.findall(r"^#\s+(.+)$", body, flags=re.MULTILINE)
    if len(h1_matches) != 1:
        errors.append(f"Document {expected_doc_id} must have exactly one level-1 heading, found {len(h1_matches)}")
    elif h1_matches[0].strip() != doc_meta["title"]:
        errors.append(f"Document {expected_doc_id} level-1 heading '{h1_matches[0].strip()}' != expected '{doc_meta['title']}'")

    # 3. Level 2 sections check
    h2_matches = [m.strip() for m in re.findall(r"^##\s+(.+)$", body, flags=re.MULTILINE)]
    expected_sections = outline.get("sections", [])
    expected_h2 = [s["title"].strip() for s in expected_sections]

    if len(h2_matches) != 6:
        errors.append(f"Document {expected_doc_id} must have exactly 6 level-2 sections, found {len(h2_matches)}")
    elif h2_matches != expected_h2:
        errors.append(f"Document {expected_doc_id} section titles mismatch.\nFound: {h2_matches}\nExpected: {expected_h2}")

    # Split body into sections
    raw_sections = re.split(r"^##\s+.+$", body, flags=re.MULTILINE)
    # raw_sections[0] is preamble before first ##, raw_sections[1..6] correspond to sections
    section_bodies = raw_sections[1:] if len(raw_sections) > 1 else []

    if len(section_bodies) != 6:
        errors.append(f"Document {expected_doc_id} section split failed: found {len(section_bodies)} sections, expected 6")
        return

    # Check non-empty content
    for idx, (sec_meta, sec_body) in enumerate(zip(expected_sections, section_bodies)):
        clean_text = sec_body.strip()
        # Remove fact marker comment when testing non-empty content
        text_without_markers = FACT_MARKER_REGEX.sub("", clean_text).strip()
        if not text_without_markers:
            errors.append(f"Document {expected_doc_id} section {sec_meta['section_id']} ('{sec_meta['title']}') is empty")

    # 4. Fact markers validation
    # Total fact markers in entire document
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

    # 5. Quality and Safety checks
    if PLACEHOLDER_REGEX.search(body):
        match = PLACEHOLDER_REGEX.search(body).group(0)
        errors.append(f"Document {expected_doc_id} contains placeholder or unfinished text: '{match}'")

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

    # 6. Document references and relationship direction checks
    all_doc_ids = set(inventory.keys())
    # S05 references check
    s05_text = section_bodies[4]
    s05_refs = DOC_ID_REGEX.findall(s05_text)
    outgoing_targets = {cr["to_doc"] for cr in outgoing_map.get(expected_doc_id, [])}
    incoming_sources = {cr["from_doc"] for cr in incoming_map.get(expected_doc_id, [])}

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
            # Extract sentence containing ref_id
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
            errors.append(f"Missing source document: {file_path.relative_to(source_dir)}")

    # Check for unexpected files in source_dir
    actual_files = list(source_dir.rglob("*.md")) + list(source_dir.rglob("*.markdown"))
    expected_paths = set(expected_files.values())
    for af in actual_files:
        if af not in expected_paths:
            errors.append(f"Unexpected source document: {af.relative_to(source_dir)}")

    if len(expected_files) != 24:
        errors.append(f"Expected 24 documents in inventory, found {len(expected_files)}")

    # 2. Validate each document individually
    for doc_id, file_path in expected_files.items():
        if file_path.exists():
            validate_single_document(file_path, doc_id, specs, errors)

    return errors


def main() -> None:
    errors = validate_documents()
    if errors:
        print(f"Document validation failed with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("Document validation passed: 24 v1 Markdown documents, 144 sections, 72 fact markers.")
        sys.exit(0)


if __name__ == "__main__":
    main()
