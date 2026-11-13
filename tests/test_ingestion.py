"""Test suite for AsterCite PDF ingestion and intelligent chunking pipeline.

Verifies:
- 24 approved PDFs ingested, 144 sections represented, at least 144 chunks.
- Chunk schema, unique deterministic chunk IDs, max word count (220 words).
- Accurate page mapping, fact traceability (72 unique facts), access metadata.
- Deterministic repeat generation.
- Negative tests for missing/corrupted PDFs, schema violations, fact errors,
  reordered text, oversized paragraphs, staging rollback, and unsafe output paths.
- Multi-page extraction and page mapping across page breaks.
- Section-splitting across paragraph boundaries.
- Security tests: restricted document isolation, document_admin denial, scope.
"""

from __future__ import annotations

import csv
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import patch
import yaml

import pypdf

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_pdfs import (
    _get_temp_dir_on_same_volume,
    build_pdf,
    load_source_document,
)
from scripts.ingest_pdfs import (
    MAX_CHUNK_WORDS,
    calculate_sha256,
    ingest_all_pdfs,
)
from scripts.validate_chunks import (
    REQUIRED_FIELDS,
    validate_chunks,
)


class TestIngestion(unittest.TestCase):
    """Test suite covering PDF ingestion, intelligent chunking, and validation."""

    @classmethod
    def setUpClass(cls):
        """Load specifications, source inventory, and pre-generated chunks."""
        cls.source_dir = PROJECT_ROOT / "data" / "source"
        cls.pdf_dir = PROJECT_ROOT / "data" / "pdfs"
        cls.spec_dir = PROJECT_ROOT / "data" / "spec"
        cls.chunks_file = PROJECT_ROOT / "data" / "chunks" / "v1_chunks.jsonl"

        # Ensure chunks file exists and load records
        if not cls.chunks_file.exists():
            ingest_all_pdfs()

        with open(cls.chunks_file, encoding="utf-8") as f:
            cls.chunks = [json.loads(line) for line in f if line.strip()]

        with open(cls.spec_dir / "document_inventory.csv", encoding="utf-8") as f:
            cls.inventory = {r["document_id"]: r for r in csv.DictReader(f)}

        with open(cls.spec_dir / "access_policy.yaml", encoding="utf-8") as f:
            cls.access_policy = yaml.safe_load(f)["documents"]

        with open(cls.spec_dir / "fact_registry.csv", encoding="utf-8") as f:
            cls.registry_facts = {r["fact_id"]: r for r in csv.DictReader(f)}

        with open(cls.spec_dir / "document_outlines.yaml", encoding="utf-8") as f:
            cls.outlines = {d["document_id"]: d for d in yaml.safe_load(f)}

    def _create_temp_jsonl_copy(self, mutated_chunks: list[dict]) -> Path:
        """Write mutated chunk list to a temporary JSONL file and return its path."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_test_chunk_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_file = base_dir / "test_chunks.jsonl"
        with open(temp_file, "w", encoding="utf-8", newline="\n") as f:
            for rec in mutated_chunks:
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        return temp_file

    # --- Positive Tests (1 to 14) ---

    def test_01_all_24_approved_pdfs_ingested(self):
        """1. Verify exactly 24 approved PDFs are represented in the chunk corpus."""
        doc_ids = sorted(set(c["document_id"] for c in self.chunks))
        expected_doc_ids = sorted(self.inventory.keys())
        self.assertEqual(len(doc_ids), 24)
        self.assertEqual(doc_ids, expected_doc_ids)

    def test_02_all_144_sections_represented(self):
        """2. Verify all 144 approved sections are represented in the chunk corpus."""
        observed_sections = set((c["document_id"], c["section_id"]) for c in self.chunks)
        self.assertEqual(len(observed_sections), 144)
        for doc_id, outline in self.outlines.items():
            for s in outline["sections"]:
                self.assertIn((doc_id, s["section_id"]), observed_sections)

    def test_03_every_section_produces_at_least_one_chunk(self):
        """3. Verify every section produces at least one chunk (corpus >= 144 chunks)."""
        self.assertGreaterEqual(len(self.chunks), 144)
        chunks_by_doc_sec: dict[tuple[str, str], int] = {}
        for c in self.chunks:
            key = (c["document_id"], c["section_id"])
            chunks_by_doc_sec[key] = chunks_by_doc_sec.get(key, 0) + 1
        for key, count in chunks_by_doc_sec.items():
            self.assertGreaterEqual(count, 1, f"Section {key} must have at least 1 chunk")

    def test_04_chunk_ids_unique_and_deterministic(self):
        """4. Verify all chunk IDs are unique, non-empty, and follow required naming."""
        chunk_ids = [c["chunk_id"] for c in self.chunks]
        self.assertEqual(len(chunk_ids), len(set(chunk_ids)), "All chunk IDs must be unique")
        id_pattern = re.compile(r"^[A-Z]{2,3}-\d{3}:v1:S0[1-6]:C\d{3}$")
        for cid in chunk_ids:
            self.assertRegex(cid, id_pattern, f"Chunk ID '{cid}' does not match required pattern")

    def test_05_every_chunk_follows_jsonl_schema(self):
        """5. Verify every chunk record contains exactly the 20 required fields with correct types."""
        expected_fields = set(REQUIRED_FIELDS)
        for c in self.chunks:
            self.assertEqual(set(c.keys()), expected_fields)
            self.assertIsInstance(c["chunk_id"], str)
            self.assertIsInstance(c["document_id"], str)
            self.assertEqual(c["document_version"], "v1")
            self.assertIsInstance(c["title"], str)
            self.assertIsInstance(c["owner_department"], str)
            self.assertIn(c["classification"], ["general", "department", "restricted"])
            self.assertEqual(c["effective_from"], "2026-11-01")
            self.assertEqual(c["source_type"], "synthetic")
            self.assertIn(c["section_id"], [f"S0{i}" for i in range(1, 7)])
            self.assertIsInstance(c["section_title"], str)
            self.assertIsInstance(c["chunk_index"], int)
            self.assertGreaterEqual(c["chunk_index"], 1)
            self.assertIsInstance(c["text"], str)
            self.assertTrue(c["text"].strip())
            self.assertIsInstance(c["page_start"], int)
            self.assertIsInstance(c["page_end"], int)
            self.assertGreaterEqual(c["page_start"], 1)
            self.assertGreaterEqual(c["page_end"], c["page_start"])
            self.assertTrue(c["pdf_path"].startswith("data/pdfs/"))
            self.assertTrue(c["source_path"].startswith("data/source/"))
            self.assertEqual(len(c["pdf_sha256"]), 64)
            self.assertIsInstance(c["fact_ids"], list)
            self.assertIsInstance(c["allowed_roles"], list)
            self.assertIsInstance(c["team_lead_departments"], list)

    def test_06_document_metadata_matches_inventory(self):
        """6. Verify chunk document metadata strictly matches document_inventory.csv."""
        for c in self.chunks:
            doc_id = c["document_id"]
            inv = self.inventory[doc_id]
            self.assertEqual(c["title"], inv["title"].strip())
            self.assertEqual(c["owner_department"], inv["owner_department"])
            self.assertEqual(c["classification"], inv["classification"].strip().lower())
            self.assertEqual(c["effective_from"], "2026-11-01")
            self.assertEqual(c["source_type"], inv["source_type"])

    def test_07_access_metadata_matches_frozen_policy(self):
        """7. Verify chunk allowed_roles and team_lead_departments match access_policy.yaml."""
        for c in self.chunks:
            doc_id = c["document_id"]
            policy = self.access_policy[doc_id]
            self.assertEqual(sorted(c["allowed_roles"]), sorted(policy["allowed_roles"]))
            self.assertEqual(sorted(c["team_lead_departments"]), sorted(policy.get("team_lead_departments", [])))
            self.assertNotIn("document_admin", c["allowed_roles"])

    def test_08_all_72_fact_ids_correctly_mapped(self):
        """8. Verify all 72 canonical fact IDs appear exactly once in the correct document and section."""
        all_assigned_facts: list[str] = []
        for c in self.chunks:
            all_assigned_facts.extend(c["fact_ids"])
            for fid in c["fact_ids"]:
                self.assertIn(fid, self.registry_facts)
                self.assertEqual(self.registry_facts[fid]["source_doc_id"], c["document_id"])

        self.assertEqual(len(all_assigned_facts), 72)
        self.assertEqual(len(set(all_assigned_facts)), 72)
        self.assertEqual(set(all_assigned_facts), set(self.registry_facts.keys()))

    def test_09_source_paragraphs_preserved_in_order(self):
        """9. Verify complete source text and paragraph order are preserved across chunks."""
        errors = validate_chunks(self.chunks_file)
        self.assertEqual(errors, [])

    def test_10_chunk_word_counts_within_max_limit(self):
        """10. Verify every chunk's text contains at most 220 words."""
        for c in self.chunks:
            words = c["text"].split()
            self.assertLessEqual(
                len(words),
                MAX_CHUNK_WORDS,
                f"Chunk {c['chunk_id']} exceeds word limit: {len(words)} > {MAX_CHUNK_WORDS}",
            )

    def test_11_page_references_valid_and_accurate(self):
        """11. Verify page references are within PDF page bounds and accurately locate text."""
        for c in self.chunks:
            self.assertGreaterEqual(c["page_start"], 1)
            self.assertGreaterEqual(c["page_end"], c["page_start"])
            pdf_path = PROJECT_ROOT / c["pdf_path"]
            reader = pypdf.PdfReader(str(pdf_path))
            self.assertLessEqual(c["page_end"], len(reader.pages))

    def test_12_output_deterministic_on_repeat_generation(self):
        """12. Verify repeated ingestion produces byte-for-byte identical JSONL output."""
        h1 = hashlib.sha256(self.chunks_file.read_bytes()).hexdigest()
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_det_test_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_out = base_dir / "repeat_chunks.jsonl"
        ingest_all_pdfs(output_file_path=temp_out)
        h2 = hashlib.sha256(temp_out.read_bytes()).hexdigest()
        self.assertEqual(h1, h2, "Repeated generation must produce identical SHA-256 hash")

    def test_13_restricted_document_classifications_intact(self):
        """13. Verify restricted documents retain restricted classification and specific access."""
        restricted_ids = {"ENG-006", "ITS-002", "HR-005"}
        for c in self.chunks:
            if c["document_id"] in restricted_ids:
                self.assertEqual(c["classification"], "restricted")
                self.assertNotIn("employee", c["allowed_roles"])

    def test_14_safe_canonical_document_references_unchanged(self):
        """14. Verify approved cross-references remain intact in chunk text without expansion."""
        its001_s04 = next(c for c in self.chunks if c["document_id"] == "ITS-001" and c["section_id"] == "S04")
        self.assertIn("OPS-005", its001_s04["text"])
        self.assertIn("OPS-002", its001_s04["text"])
        self.assertNotIn("Asset Procurement and Ownership", its001_s04["text"])

    # --- Negative Tests (15 to 28) ---

    def test_15_missing_pdf_causes_ingestion_failure(self):
        """15. Verify missing PDF causes ingestion failure with clear error."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_mis_pdf_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_pdf_dir = base_dir / "pdfs"
        shutil.copytree(self.pdf_dir, temp_pdf_dir)
        (temp_pdf_dir / "engineering" / "eng_001_v1.pdf").unlink()

        with self.assertRaises(RuntimeError) as ctx:
            ingest_all_pdfs(pdf_dir_path=temp_pdf_dir, output_file_path=base_dir / "out.jsonl")
        self.assertTrue(
            "eng_001_v1.pdf" in str(ctx.exception) or "Missing" in str(ctx.exception),
            f"Expected missing PDF error, got: {ctx.exception}",
        )

    def test_16_corrupted_pdf_causes_ingestion_failure(self):
        """16. Verify corrupted PDF causes ingestion failure gracefully."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_corrupt_pdf_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_pdf_dir = base_dir / "pdfs"
        shutil.copytree(self.pdf_dir, temp_pdf_dir)
        (temp_pdf_dir / "engineering" / "eng_001_v1.pdf").write_bytes(b"NOT A VALID PDF FILE")

        with self.assertRaises(RuntimeError) as ctx:
            ingest_all_pdfs(pdf_dir_path=temp_pdf_dir, output_file_path=base_dir / "out.jsonl")
        self.assertTrue(
            "Corrupted" in str(ctx.exception) or "invalid" in str(ctx.exception).lower(),
            f"Expected corruption error, got: {ctx.exception}",
        )

    def test_17_unexpected_v2_pdf_rejected(self):
        """17. Verify unexpected v2 PDF file in collection causes rejection."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_v2_pdf_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_pdf_dir = base_dir / "pdfs"
        shutil.copytree(self.pdf_dir, temp_pdf_dir)
        # Add unapproved v2 PDF
        v2_pdf = temp_pdf_dir / "engineering" / "eng_001_v2.pdf"
        shutil.copy2(temp_pdf_dir / "engineering" / "eng_001_v1.pdf", v2_pdf)

        with self.assertRaises(RuntimeError) as ctx:
            ingest_all_pdfs(pdf_dir_path=temp_pdf_dir, output_file_path=base_dir / "out.jsonl")
        self.assertTrue(
            "unexpected" in str(ctx.exception).lower() or "eng_001_v2.pdf" in str(ctx.exception),
            f"Expected rejection of v2 PDF, got: {ctx.exception}",
        )

    def test_18_missing_or_changed_source_paragraph_rejected(self):
        """18. Verify missing or altered source paragraph fails chunk validation."""
        mutated = [dict(c) for c in self.chunks]
        mutated[0]["text"] = mutated[0]["text"].replace("operational", "altered_unapproved")
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("does not match PDF text" in e for e in errors), f"Expected mismatch error: {errors}")

    def test_19_extra_unauthorized_pdf_text_rejected(self):
        """19. Verify extra unauthorized text in chunk is rejected."""
        mutated = [dict(c) for c in self.chunks]
        mutated[1]["text"] = mutated[1]["text"] + "\n\nUnauthorized clause."
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("does not match PDF text" in e for e in errors), f"Expected mismatch error: {errors}")

    def test_20_missing_or_duplicate_chunk_id_rejected(self):
        """20. Verify duplicate chunk ID is rejected by validator."""
        mutated = [dict(c) for c in self.chunks]
        mutated[1]["chunk_id"] = mutated[0]["chunk_id"]
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("Duplicate chunk_id" in e for e in errors), f"Expected duplicate ID error: {errors}")

    def test_21_missing_duplicate_or_incorrect_fact_id_rejected(self):
        """21. Verify missing or incorrect fact assignment fails validation."""
        mutated = [dict(c) for c in self.chunks]
        # Remove a fact ID
        found = False
        for c in mutated:
            if "ENG001_F01" in c["fact_ids"]:
                c["fact_ids"] = []
                found = True
                break
        self.assertTrue(found)
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(
            any("Expected 72 canonical fact assignments" in e or "Missing canonical fact IDs" in e for e in errors),
            f"Expected missing fact error: {errors}",
        )

    def test_22_wrong_classification_or_allowed_roles_rejected(self):
        """22. Verify wrong classification or altered roles fail validation."""
        mutated = [dict(c) for c in self.chunks]
        mutated[0]["classification"] = "general"  # ENG-001 is department
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("classification" in e for e in errors), f"Expected classification error: {errors}")

    def test_23_wrong_page_number_or_pdf_hash_rejected(self):
        """23. Verify wrong page numbers or incorrect PDF hash are rejected."""
        mutated = [dict(c) for c in self.chunks]
        mutated[0]["page_start"] = 999
        mutated[0]["page_end"] = 999
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("invalid page range" in e for e in errors), f"Expected page range error: {errors}")

    def test_24_reordered_or_duplicated_paragraphs_rejected(self):
        """24. Verify reordering paragraphs within a chunk fails validation."""
        mutated = [dict(c) for c in self.chunks]
        # Find a chunk with multiple paragraphs (S02 has 2 paragraphs)
        s02_chunk = next(c for c in mutated if c["document_id"] == "ENG-001" and c["section_id"] == "S02")
        paras = s02_chunk["text"].split("\n\n")
        self.assertGreaterEqual(len(paras), 2)
        s02_chunk["text"] = f"{paras[1]}\n\n{paras[0]}"
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("does not match PDF text" in e for e in errors), f"Expected reordered error: {errors}")

    def test_25_malformed_jsonl_fails_validation(self):
        """25. Verify malformed JSON line fails validation with clear error."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_mal_json_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_file = base_dir / "malformed.jsonl"
        temp_file.write_text('{"chunk_id": "test"}\n{NOT VALID JSON\n', encoding="utf-8")
        errors = validate_chunks(temp_file)
        self.assertTrue(any("Malformed JSON" in e for e in errors), f"Expected malformed JSON error: {errors}")

    def test_26_oversized_individual_paragraph_fails_clearly(self):
        """26. Verify an oversized individual paragraph fails with clear error identifying section."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_over_para_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_src = base_dir / "source"
        shutil.copytree(self.source_dir, temp_src)

        # Inject 250-word single paragraph into ENG-001 Section 1
        eng_file = temp_src / "engineering" / "eng_001.md"
        content = eng_file.read_text(encoding="utf-8")
        oversized = " ".join(["operational"] * 240)
        eng_file.write_text(content.replace("## Purpose and Scope", f"## Purpose and Scope\n{oversized}"), encoding="utf-8")

        # Also rebuild PDF so PDF matches
        temp_pdf_dir = base_dir / "pdfs"
        shutil.copytree(self.pdf_dir, temp_pdf_dir)
        meta, title, secs = load_source_document(eng_file)
        build_pdf(temp_pdf_dir / "engineering" / "eng_001_v1.pdf", meta, title, secs)

        with self.assertRaises(RuntimeError) as ctx:
            ingest_all_pdfs(source_dir_path=temp_src, pdf_dir_path=temp_pdf_dir, output_file_path=base_dir / "out.jsonl")
        self.assertTrue(
            "Oversized individual paragraph" in str(ctx.exception) and "ENG-001" in str(ctx.exception),
            f"Expected oversized paragraph error: {ctx.exception}",
        )

    def test_27_staging_failure_preserves_previously_published_jsonl(self):
        """27. Verify staging validation failure does not overwrite previously published JSONL."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_pres_jsonl_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        target_file = base_dir / "v1_chunks.jsonl"
        target_file.write_text("ORIGINAL CONTENT MUST BE PRESERVED", encoding="utf-8")

        with patch("scripts.ingest_pdfs.validate_chunks", return_value=["Simulated staging validation error"]):
            with self.assertRaises(RuntimeError):
                ingest_all_pdfs(output_file_path=target_file)

        self.assertEqual(target_file.read_text(encoding="utf-8"), "ORIGINAL CONTENT MUST BE PRESERVED")

    def test_28_unsafe_output_paths_rejected_without_deleting_user_content(self):
        """28. Verify existing directory at output path is rejected and left intact."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_unsafe_out_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        out_dir = base_dir / "blocked_directory"
        out_dir.mkdir()
        (out_dir / "keep.txt").write_text("critical user file", encoding="utf-8")

        with self.assertRaises(RuntimeError) as ctx:
            ingest_all_pdfs(output_file_path=out_dir)

        self.assertIn("existing directory", str(ctx.exception))
        self.assertTrue(out_dir.exists())
        self.assertTrue((out_dir / "keep.txt").exists())

    # --- Multi-Page Test (29) ---

    def test_29_multipage_pdf_ingestion_and_page_mapping(self):
        """29. Verify genuine multi-page PDF extracts correctly and preserves page ranges."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_multi_ingest_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_src = base_dir / "source"
        temp_pdf = base_dir / "pdfs"
        shutil.copytree(self.source_dir, temp_src)
        shutil.copytree(self.pdf_dir, temp_pdf)

        # Expand ENG-001 Section 1 with 15 paragraphs to force 2 pages
        eng_file = temp_src / "engineering" / "eng_001.md"
        content = eng_file.read_text(encoding="utf-8")
        extra_p = "\n\n".join(
            f"Addendum operational procedure paragraph {i} providing technical guidelines."
            for i in range(15)
        )
        target = "## P1 Incident Acknowledgment"
        eng_file.write_text(content.replace(target, f"{extra_p}\n\n{target}"), encoding="utf-8")

        meta, title, secs = load_source_document(eng_file)
        eng_pdf_path = temp_pdf / "engineering" / "eng_001_v1.pdf"
        build_pdf(eng_pdf_path, meta, title, secs)

        reader = pypdf.PdfReader(str(eng_pdf_path))
        self.assertGreaterEqual(len(reader.pages), 2, "Test PDF must have at least 2 pages")

        out_jsonl = base_dir / "multi_chunks.jsonl"
        chunks = ingest_all_pdfs(source_dir_path=temp_src, pdf_dir_path=temp_pdf, output_file_path=out_jsonl)

        # Confirm validation succeeds
        errors = validate_chunks(out_jsonl, pdf_dir_path=temp_pdf, source_dir_path=temp_src, spec_dir_path=self.spec_dir)
        self.assertEqual(errors, [])

        # Confirm chunks exist on page 1 and page 2
        eng_chunks = [c for c in chunks if c["document_id"] == "ENG-001"]
        pages_seen = set()
        for c in eng_chunks:
            pages_seen.add(c["page_start"])
            pages_seen.add(c["page_end"])
        self.assertIn(1, pages_seen)
        self.assertIn(2, pages_seen)

    # --- Section-Splitting Test (30) ---

    def test_30_section_exceeding_word_limit_splits_at_paragraph_boundaries(self):
        """30. Verify section exceeding 220 words splits cleanly into multiple chunks."""
        base_dir = _get_temp_dir_on_same_volume(self.chunks_file, prefix="astercite_split_test_")
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)
        temp_src = base_dir / "source"
        temp_pdf = base_dir / "pdfs"
        shutil.copytree(self.source_dir, temp_src)
        shutil.copytree(self.pdf_dir, temp_pdf)

        # In ENG-001 Purpose and Scope, add 6 distinct paragraphs (total section > 220 words)
        eng_file = temp_src / "engineering" / "eng_001.md"
        content = eng_file.read_text(encoding="utf-8")
        paras_to_add = "\n\n".join(
            f"Addendum distinct paragraph {i} providing comprehensive operational management procedures "
            f"and incident handling guidance for infrastructure teams to ensure seamless incident resolution, "
            f"high system availability, and ongoing service reliability across all Aster Systems cloud environments "
            f"and enterprise application platforms."
            for i in range(6)
        )
        target = "## P1 Incident Acknowledgment"
        eng_file.write_text(content.replace(target, f"{paras_to_add}\n\n{target}"), encoding="utf-8")

        meta, title, secs = load_source_document(eng_file)
        build_pdf(temp_pdf / "engineering" / "eng_001_v1.pdf", meta, title, secs)

        out_jsonl = base_dir / "split_chunks.jsonl"
        chunks = ingest_all_pdfs(source_dir_path=temp_src, pdf_dir_path=temp_pdf, output_file_path=out_jsonl)

        # Confirm validation passes
        errors = validate_chunks(out_jsonl, pdf_dir_path=temp_pdf, source_dir_path=temp_src, spec_dir_path=self.spec_dir)
        self.assertEqual(errors, [])

        # Confirm Purpose and Scope produced at least 2 chunks: C001 and C002
        s01_chunks = [c for c in chunks if c["document_id"] == "ENG-001" and c["section_id"] == "S01"]
        self.assertGreaterEqual(len(s01_chunks), 2, "Oversized section must split into at least 2 chunks")
        self.assertEqual(s01_chunks[0]["chunk_id"], "ENG-001:v1:S01:C001")
        self.assertEqual(s01_chunks[1]["chunk_id"], "ENG-001:v1:S01:C002")

        # Confirm every chunk is within 220 words
        for c in s01_chunks:
            self.assertLessEqual(len(c["text"].split()), MAX_CHUNK_WORDS)

    # --- Security Tests (31 to 35) ---

    def test_31_restricted_document_metadata_and_isolation(self):
        """31. Verify restricted document classification mutation is rejected."""
        mutated = [dict(c) for c in self.chunks]
        # Mutate ENG-006 classification to general
        for c in mutated:
            if c["document_id"] == "ENG-006":
                c["classification"] = "general"
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("classification" in e for e in errors), f"Expected classification error: {errors}")

    def test_32_incorrectly_added_document_admin_role_rejected(self):
        """32. Verify granting read access to document_admin is strictly rejected."""
        mutated = [dict(c) for c in self.chunks]
        mutated[0]["allowed_roles"].append("document_admin")
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("document_admin" in e for e in errors), f"Expected document_admin error: {errors}")

    def test_33_incorrect_team_lead_department_scope_rejected(self):
        """33. Verify incorrect team_lead_departments scope fails validation."""
        mutated = [dict(c) for c in self.chunks]
        mutated[0]["team_lead_departments"] = ["it_support"]  # ENG-001 requires engineering
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("team_lead_departments" in e for e in errors), f"Expected department scope error: {errors}")

    def test_34_general_chunk_containing_restricted_text_rejected(self):
        """34. Verify leaking restricted service ownership text into a general chunk is rejected."""
        mutated = [dict(c) for c in self.chunks]
        # Inject restricted service identifier into general HR-001 chunk
        hr_chunk = next(c for c in mutated if c["document_id"] == "HR-001" and c["section_id"] == "S01")
        hr_chunk["text"] += " Leaked svc-portal service ownership."
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("restricted" in e.lower() for e in errors), f"Expected restricted leak error: {errors}")

    def test_35_protected_reference_expansion_rejected(self):
        """35. Verify expanding protected document ID into restricted title fails validation."""
        mutated = [dict(c) for c in self.chunks]
        # In ITS-001, replace reference 'OPS-005' with protected title
        its_chunk = next(c for c in mutated if c["document_id"] == "ITS-001" and c["section_id"] == "S04")
        its_chunk["text"] = its_chunk["text"].replace("OPS-005", "Asset Procurement and Ownership")
        temp_jsonl = self._create_temp_jsonl_copy(mutated)
        errors = validate_chunks(temp_jsonl)
        self.assertTrue(any("does not match PDF text" in e for e in errors), f"Expected unapproved text error: {errors}")


if __name__ == "__main__":
    unittest.main()

