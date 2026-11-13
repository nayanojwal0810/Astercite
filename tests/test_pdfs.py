"""Test suite for Aster Systems PDF generation and validation.

Verifies:
- 24 expected source-to-PDF mappings with _v1 naming.
- A4 portrait format and pypdf readability.
- Document identity and reader metadata.
- Section structure and full source-text preservation in order.
- Canonical factual paragraphs and absence of internal markers.
- Negative tests: missing, unexpected, v2, and corrupted PDFs.
- Source validation failure preventing publication.
- Repeat-generation consistency.
"""

from __future__ import annotations

import csv
import hashlib
import os
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest
from unittest.mock import MagicMock, PropertyMock, patch

import pypdf
import yaml

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_pdfs import (
    _get_temp_dir_on_same_volume,
    build_pdf,
    generate_all_pdfs,
    load_source_document,
)
from scripts.validate_pdfs import validate_pdfs


class TestPDFs(unittest.TestCase):
    """Test suite covering PDF generation and validation."""

    @classmethod
    def setUpClass(cls):
        """Generate shared PDF corpus in a temporary directory for efficient test runs."""
        cls.source_dir = PROJECT_ROOT / "data" / "source"
        cls.spec_dir = PROJECT_ROOT / "data" / "spec"
        cls.temp_dir = Path(tempfile.mkdtemp(prefix="astercite_shared_test_pdfs_"))

        inv_file = cls.spec_dir / "document_inventory.csv"
        with open(inv_file, encoding="utf-8") as f:
            cls.inventory = {r["document_id"]: r for r in csv.DictReader(f)}

        # Generate all 24 PDFs into cls.temp_dir
        cls.generated_paths = generate_all_pdfs(
            source_dir_path=cls.source_dir,
            output_dir_path=cls.temp_dir,
            spec_dir_path=cls.spec_dir,
        )

    @classmethod
    def tearDownClass(cls):
        """Clean up shared temporary PDF directory."""
        shutil.rmtree(cls.temp_dir, ignore_errors=True)

    def _create_temp_pdf_copy(self) -> Path:
        """Create a temporary copy of generated PDFs for mutation tests."""
        dest = Path(tempfile.mkdtemp(prefix="astercite_pdf_mutation_"))
        self.addCleanup(shutil.rmtree, dest, ignore_errors=True)
        for dept in ["engineering", "it_support", "people_operations", "finance_operations"]:
            src_dept = self.temp_dir / dept
            if src_dept.exists():
                shutil.copytree(src_dept, dest / dept)
        return dest

    def _create_temp_source_copy(self) -> Path:
        """Create a temporary copy of data/source for source-mutation tests."""
        dest = Path(tempfile.mkdtemp(prefix="astercite_src_mutation_"))
        self.addCleanup(shutil.rmtree, dest, ignore_errors=True)
        shutil.copytree(self.source_dir, dest, dirs_exist_ok=True)
        return dest

    def test_01_expected_source_to_pdf_mappings_and_v1_filenames(self):
        """1 & 2. Verify all 24 expected source-to-PDF mappings with approved _v1 filenames."""
        self.assertEqual(len(self.generated_paths), 24)
        for doc_id, meta in self.inventory.items():
            dept = meta["owner_department"]
            expected_name = f"{doc_id.lower().replace('-', '_')}_v1.pdf"
            pdf_path = self.temp_dir / dept / expected_name
            self.assertTrue(
                pdf_path.exists(),
                f"Missing expected PDF for {doc_id} at {pdf_path}",
            )
            self.assertTrue(
                expected_name.endswith("_v1.pdf"),
                f"PDF filename {expected_name} must end with '_v1.pdf'",
            )

    def test_02_pdf_validation_passes_on_valid_corpus(self):
        """3. Confirm that the full generated PDF corpus passes all validation checks."""
        errors = validate_pdfs(
            output_dir_path=self.temp_dir,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(errors, [], f"Validation reported unexpected errors: {errors}")

    def test_03_readable_pdf_structure_and_nonempty_text(self):
        """4 & 5. Verify every PDF opens, is unencrypted, has A4 portrait dimensions, and has text."""
        for doc_id, meta in self.inventory.items():
            dept = meta["owner_department"]
            pdf_path = self.temp_dir / dept / f"{doc_id.lower().replace('-', '_')}_v1.pdf"
            reader = pypdf.PdfReader(str(pdf_path))

            self.assertFalse(reader.is_encrypted, f"PDF {doc_id} must not be encrypted")
            self.assertGreaterEqual(len(reader.pages), 1, f"PDF {doc_id} must have >= 1 page")

            for page_idx, page in enumerate(reader.pages):
                w = float(page.mediabox.width)
                h = float(page.mediabox.height)
                self.assertTrue(
                    590 <= w <= 600 and 835 <= h <= 850,
                    f"PDF {doc_id} page {page_idx + 1} dimensions ({w}x{h}) outside A4 bounds",
                )
                text = page.extract_text()
                self.assertTrue(
                    bool(text and text.strip()),
                    f"PDF {doc_id} page {page_idx + 1} has empty extractable text",
                )

    def test_04_document_identity_and_metadata(self):
        """6 & 7. Verify document title, ID, version, department, classification, date, and PDF info."""
        for doc_id, meta in self.inventory.items():
            dept = meta["owner_department"]
            expected_title = meta["title"].strip()
            expected_class = meta["classification"].strip().lower()
            pdf_path = self.temp_dir / dept / f"{doc_id.lower().replace('-', '_')}_v1.pdf"
            reader = pypdf.PdfReader(str(pdf_path))

            full_text = "\n".join(p.extract_text() for p in reader.pages)
            self.assertIn(expected_title.lower(), full_text.lower(), f"Missing title in {doc_id}")
            self.assertIn(doc_id, full_text, f"Missing doc_id in {doc_id}")
            self.assertIn("v1", full_text, f"Missing version in {doc_id}")
            self.assertIn(dept.replace("_", " ").lower(), full_text.lower(), f"Missing dept in {doc_id}")
            self.assertIn(expected_class, full_text.lower(), f"Missing classification in {doc_id}")
            self.assertIn("2026-11-01", full_text, f"Missing date in {doc_id}")

            # PDF reader metadata
            pdf_meta = reader.metadata or {}
            self.assertEqual(pdf_meta.get("/Title"), expected_title)
            self.assertEqual(pdf_meta.get("/Author"), "Aster Systems")
            self.assertEqual(pdf_meta.get("/Subject"), f"{doc_id} v1")

    def test_05_section_headings_preserved_in_order(self):
        """8. Verify all six section headings appear in exact order in each PDF."""
        outlines_file = self.spec_dir / "document_outlines.yaml"
        with open(outlines_file, encoding="utf-8") as f:
            outlines = {d["document_id"]: d for d in yaml.safe_load(f)}

        for doc_id, meta in self.inventory.items():
            dept = meta["owner_department"]
            pdf_path = self.temp_dir / dept / f"{doc_id.lower().replace('-', '_')}_v1.pdf"
            reader = pypdf.PdfReader(str(pdf_path))
            full_text = " ".join(" ".join(p.extract_text().split()) for p in reader.pages)

            expected_headings = [s["title"].strip() for s in outlines[doc_id]["sections"]]
            self.assertEqual(len(expected_headings), 6)

            curr_idx = 0
            for heading in expected_headings:
                norm_heading = " ".join(heading.split())
                pos = full_text.find(norm_heading, curr_idx)
                self.assertNotEqual(
                    pos, -1,
                    f"Heading '{heading}' not found in {doc_id} after position {curr_idx}",
                )
                curr_idx = pos + len(norm_heading)

    def test_06_canonical_facts_and_source_paragraphs_preserved(self):
        """9 & 12. Verify all 72 canonical factual paragraphs and full source text are preserved."""
        facts_file = self.spec_dir / "fact_registry.csv"
        with open(facts_file, encoding="utf-8") as f:
            facts_by_doc: dict[str, list[dict]] = {}
            for r in csv.DictReader(f):
                facts_by_doc.setdefault(r["source_doc_id"], []).append(r)

        total_facts_verified = 0
        for doc_id, meta in self.inventory.items():
            dept = meta["owner_department"]
            src_file = self.source_dir / dept / f"{doc_id.lower().replace('-', '_')}.md"
            pdf_path = self.temp_dir / dept / f"{doc_id.lower().replace('-', '_')}_v1.pdf"

            reader = pypdf.PdfReader(str(pdf_path))
            full_text = " ".join(" ".join(p.extract_text().split()) for p in reader.pages)

            # Check full source text preservation
            _, src_title, src_sections = load_source_document(src_file)
            expected_units = [src_title]
            for sec_title, paras in src_sections:
                expected_units.append(sec_title)
                expected_units.extend(paras)

            curr_pos = 0
            for unit in expected_units:
                norm_unit = " ".join(unit.split())
                pos = full_text.find(norm_unit, curr_pos)
                self.assertNotEqual(
                    pos, -1,
                    f"Source unit '{norm_unit[:40]}...' missing or out of order in {doc_id}",
                )
                curr_pos = pos + len(norm_unit)

            # Check 3 canonical facts per document
            raw_src = src_file.read_text(encoding="utf-8")
            for f_row in facts_by_doc[doc_id]:
                fid = f_row["fact_id"]
                marker = f"<!-- fact_id: {fid} -->"
                after = raw_src.split(marker, 1)[1].lstrip("\r\n")
                fact_para = re.split(r"\r?\n\s*\r?\n", after, maxsplit=1)[0].strip()
                norm_fact = " ".join(fact_para.split())
                self.assertIn(norm_fact, full_text, f"Fact {fid} paragraph missing in {doc_id}")
                total_facts_verified += 1

        self.assertEqual(total_facts_verified, 72)

    def test_07_no_internal_markers_or_front_matter_leaks(self):
        """10 & 11. Confirm no fact-marker comments, raw YAML keys, or placeholders in any PDF."""
        for doc_id, meta in self.inventory.items():
            dept = meta["owner_department"]
            pdf_path = self.temp_dir / dept / f"{doc_id.lower().replace('-', '_')}_v1.pdf"
            reader = pypdf.PdfReader(str(pdf_path))
            full_text = "\n".join(p.extract_text() for p in reader.pages)

            self.assertNotIn("<!--", full_text, f"HTML comment marker exposed in {doc_id}")
            self.assertNotIn("fact_id:", full_text, f"fact_id marker exposed in {doc_id}")
            self.assertNotIn("source_type:", full_text, f"source_type key exposed in {doc_id}")
            self.assertFalse(
                re.search(r"\b(TODO|TBD|FIXME|Lorem ipsum)\b", full_text, re.IGNORECASE),
                f"Placeholder text found in {doc_id}",
            )

    def test_08_special_characters_and_identifiers_render_correctly(self):
        """19. Verify ampersands, document IDs, and service IDs render accurately without corruption."""
        # 1. Ampersand in ENG-001 title
        eng_001_pdf = self.temp_dir / "engineering" / "eng_001_v1.pdf"
        eng_text = "\n".join(p.extract_text() for p in pypdf.PdfReader(str(eng_001_pdf)).pages)
        self.assertIn("Production Incident Severity & Escalation Policy", eng_text)
        self.assertNotIn("&amp;", eng_text)

        # 2. Service identifier in ENG-006
        eng_006_pdf = self.temp_dir / "engineering" / "eng_006_v1.pdf"
        eng_006_text = "\n".join(p.extract_text() for p in pypdf.PdfReader(str(eng_006_pdf)).pages)
        self.assertIn("svc-auth", eng_006_text)
        self.assertIn("svc-portal", eng_006_text)

        # 3. Currency symbol and numbers in OPS-002
        ops_002_pdf = self.temp_dir / "finance_operations" / "ops_002_v1.pdf"
        ops_002_text = "\n".join(p.extract_text() for p in pypdf.PdfReader(str(ops_002_pdf)).pages)
        self.assertIn("INR 25,000", ops_002_text)
        self.assertIn("INR 100,000", ops_002_text)

    def test_09_protected_canonical_references_remain_unchanged(self):
        """20. Approved protected document IDs appear in canonical facts without expanding to titles."""
        # ITS-001 canonical reference to OPS-002
        its_001_pdf = self.temp_dir / "it_support" / "its_001_v1.pdf"
        its_text = "\n".join(p.extract_text() for p in pypdf.PdfReader(str(its_001_pdf)).pages)
        self.assertIn("OPS-002", its_text)
        self.assertNotIn("Procurement Approval Thresholds", its_text)

        # HR-003 canonical reference to ITS-002
        hr_003_pdf = self.temp_dir / "people_operations" / "hr_003_v1.pdf"
        hr_text = "\n".join(p.extract_text() for p in pypdf.PdfReader(str(hr_003_pdf)).pages)
        self.assertIn("ITS-002", hr_text)
        self.assertNotIn("Account Provisioning / Deprovisioning", hr_text)

    def test_10_missing_pdf_detection(self):
        """13. Validate that a missing PDF is detected and reported."""
        temp_copy = self._create_temp_pdf_copy()
        target = temp_copy / "engineering" / "eng_001_v1.pdf"
        target.unlink()

        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("Missing expected PDF" in err and "eng_001_v1.pdf" in err for err in errors),
            f"Expected missing PDF error, got: {errors}",
        )

    def test_11_unexpected_pdf_detection(self):
        """14. Validate that an unexpected PDF file is detected and rejected."""
        temp_copy = self._create_temp_pdf_copy()
        extra = temp_copy / "engineering" / "eng_999_v1.pdf"
        extra.write_bytes(b"%PDF-1.4 extra test")

        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("Unexpected PDF file" in err and "eng_999_v1.pdf" in err for err in errors),
            f"Expected unexpected PDF error, got: {errors}",
        )

    def test_12_unexpected_v2_pdf_detection(self):
        """16. Validate that an unexpected v2 PDF file is detected and rejected."""
        temp_copy = self._create_temp_pdf_copy()
        v2_file = temp_copy / "engineering" / "eng_001_v2.pdf"
        v2_file.write_bytes(b"%PDF-1.4 v2 test")

        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("Unexpected PDF file" in err and "eng_001_v2.pdf" in err for err in errors),
            f"Expected unexpected v2 PDF error, got: {errors}",
        )

    def test_13_corrupted_pdf_detection(self):
        """15. Validate that a corrupted PDF file causes validation to fail gracefully."""
        temp_copy = self._create_temp_pdf_copy()
        corrupted = temp_copy / "engineering" / "eng_001_v1.pdf"
        corrupted.write_bytes(b"NOT A VALID PDF FILE HEADER")

        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("Corrupted or invalid PDF" in err and "ENG-001" in err for err in errors),
            f"Expected corrupted PDF error, got: {errors}",
        )

    def test_14_source_validation_failure_stops_generation(self):
        """17. Verify that invalid Markdown source stops PDF generation before publication."""
        temp_src = self._create_temp_source_copy()
        # Invalidate eng_001 by changing document_version to v2
        eng_file = temp_src / "engineering" / "eng_001.md"
        eng_file.write_text(
            eng_file.read_text(encoding="utf-8").replace("document_version: v1", "document_version: v2"),
            encoding="utf-8",
        )

        temp_out = Path(tempfile.mkdtemp(prefix="astercite_stop_pub_"))
        self.addCleanup(shutil.rmtree, temp_out, ignore_errors=True)

        with self.assertRaises(RuntimeError) as ctx:
            generate_all_pdfs(
                source_dir_path=temp_src,
                output_dir_path=temp_out,
                spec_dir_path=self.spec_dir,
            )

        self.assertIn("Source document validation failed", str(ctx.exception))
        # Ensure no PDFs were published to temp_out
        published = list(temp_out.rglob("*.pdf"))
        self.assertEqual(published, [])

    def test_15_repeat_generation_consistency(self):
        """18. Verify repeat generation produces identical, valid PDF paths and content."""
        temp_repeat = Path(tempfile.mkdtemp(prefix="astercite_repeat_test_"))
        self.addCleanup(shutil.rmtree, temp_repeat, ignore_errors=True)

        paths1 = generate_all_pdfs(
            source_dir_path=self.source_dir,
            output_dir_path=temp_repeat,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(len(paths1), 24)

        paths2 = generate_all_pdfs(
            source_dir_path=self.source_dir,
            output_dir_path=temp_repeat,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(len(paths2), 24)
        self.assertEqual([str(p) for p in paths1], [str(p) for p in paths2])

        errors = validate_pdfs(
            output_dir_path=temp_repeat,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(errors, [])

    # --- Publication Safety Regression Tests ---

    def test_16_failed_publication_restores_all_24_previous_pdfs_with_identical_hashes(self):
        """16. Verify failed publication restores all 24 previous PDFs with identical SHA-256 hashes."""
        temp_pub = self._create_temp_pdf_copy()
        # Record pre-publication SHA-256 hashes
        pre_hashes: dict[str, str] = {}
        for p in temp_pub.rglob("*_v1.pdf"):
            pre_hashes[str(p.relative_to(temp_pub))] = hashlib.sha256(p.read_bytes()).hexdigest()
        self.assertEqual(len(pre_hashes), 24)

        orig_validate = validate_pdfs

        def fail_on_target(*args, **kwargs):
            out_p = Path(kwargs.get("output_dir_path", args[0] if args else ""))
            if out_p.resolve() == temp_pub.resolve():
                return ["Simulated post-publication validation failure"]
            return orig_validate(*args, **kwargs)

        with patch("scripts.validate_pdfs.validate_pdfs", side_effect=fail_on_target):
            with self.assertRaises(RuntimeError) as ctx:
                generate_all_pdfs(
                    source_dir_path=self.source_dir,
                    output_dir_path=temp_pub,
                    spec_dir_path=self.spec_dir,
                )
            self.assertIn("Published PDF collection failed validation", str(ctx.exception))

        # Confirm all 24 files are restored with exact same hashes
        post_hashes: dict[str, str] = {}
        for p in temp_pub.rglob("*_v1.pdf"):
            post_hashes[str(p.relative_to(temp_pub))] = hashlib.sha256(p.read_bytes()).hexdigest()

        self.assertEqual(len(post_hashes), 24)
        self.assertEqual(pre_hashes, post_hashes)

    def test_17_failure_after_moving_old_collection_triggers_rollback(self):
        """17. Verify failure during staging replacement triggers complete rollback to original files."""
        temp_pub = self._create_temp_pdf_copy()
        pre_hashes = {
            str(p.relative_to(temp_pub)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in temp_pub.rglob("*_v1.pdf")
        }

        orig_replace = os.replace
        replace_count = 0

        def mock_replace(src, dst):
            nonlocal replace_count
            replace_count += 1
            # Second call in generate_all_pdfs is os.replace(staging_dir, output_dir)
            if replace_count == 2:
                raise OSError("Simulated filesystem I/O error during staging swap")
            return orig_replace(src, dst)

        with patch("os.replace", side_effect=mock_replace):
            with self.assertRaises(RuntimeError) as ctx:
                generate_all_pdfs(
                    source_dir_path=self.source_dir,
                    output_dir_path=temp_pub,
                    spec_dir_path=self.spec_dir,
                )
            self.assertIn("Simulated filesystem I/O error", str(ctx.exception))

        # Confirm rollback restored all 24 original files
        post_hashes = {
            str(p.relative_to(temp_pub)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in temp_pub.rglob("*_v1.pdf")
        }
        self.assertEqual(len(post_hashes), 24)
        self.assertEqual(pre_hashes, post_hashes)

    def test_18_failure_during_final_published_validation_triggers_rollback(self):
        """18. Verify failure during final published validation triggers rollback to previous collection."""
        temp_pub = self._create_temp_pdf_copy()
        pre_files = sorted(str(p.relative_to(temp_pub)) for p in temp_pub.rglob("*_v1.pdf"))
        self.assertEqual(len(pre_files), 24)

        orig_validate = validate_pdfs

        def fail_final(*args, **kwargs):
            out_p = Path(kwargs.get("output_dir_path", args[0] if args else ""))
            if out_p.resolve() == temp_pub.resolve():
                return ["Simulated post-publication checksum discrepancy"]
            return orig_validate(*args, **kwargs)

        with patch("scripts.validate_pdfs.validate_pdfs", side_effect=fail_final):
            with self.assertRaises(RuntimeError):
                generate_all_pdfs(
                    source_dir_path=self.source_dir,
                    output_dir_path=temp_pub,
                    spec_dir_path=self.spec_dir,
                )

        post_files = sorted(str(p.relative_to(temp_pub)) for p in temp_pub.rglob("*_v1.pdf"))
        self.assertEqual(pre_files, post_files)

    def test_19_failure_with_no_previous_collection_leaves_no_partial_output(self):
        """19. Verify failure with no previous published collection leaves no partial output."""
        base_dir = _get_temp_dir_on_same_volume(PROJECT_ROOT / "data" / "pdfs", prefix="astercite_no_prev_")
        target_dir = base_dir / "target_pdfs"
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)

        with patch("scripts.validate_pdfs.validate_pdfs", return_value=["Simulated staging validation failure"]):
            with self.assertRaises(RuntimeError):
                generate_all_pdfs(
                    source_dir_path=self.source_dir,
                    output_dir_path=target_dir,
                    spec_dir_path=self.spec_dir,
                )

        # Confirm target directory does not exist or has 0 PDFs
        published_pdfs = list(target_dir.rglob("*.pdf")) if target_dir.exists() else []
        self.assertEqual(published_pdfs, [])

    def test_20_unexpected_user_files_are_preserved(self):
        """20. Verify unexpected user files in destination block replacement and are preserved."""
        temp_pub = self._create_temp_pdf_copy()
        user_file = temp_pub / "user_notes.txt"
        user_file.write_text("critical user notes that must never be deleted", encoding="utf-8")

        with self.assertRaises(RuntimeError) as ctx:
            generate_all_pdfs(
                source_dir_path=self.source_dir,
                output_dir_path=temp_pub,
                spec_dir_path=self.spec_dir,
            )

        self.assertIn("unexpected", str(ctx.exception).lower())
        self.assertIn("user_notes.txt", str(ctx.exception))
        self.assertTrue(user_file.exists())
        self.assertEqual(user_file.read_text(encoding="utf-8"), "critical user notes that must never be deleted")

    def test_21_normal_and_repeated_publication_succeed(self):
        """21. Verify normal and repeated publication succeed cleanly using directory swap."""
        base_dir = _get_temp_dir_on_same_volume(PROJECT_ROOT / "data" / "pdfs", prefix="astercite_norm_repeat_")
        target_dir = base_dir / "published_pdfs"
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)

        # First publication
        pub1 = generate_all_pdfs(
            source_dir_path=self.source_dir,
            output_dir_path=target_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(len(pub1), 24)
        errs1 = validate_pdfs(
            output_dir_path=target_dir,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(errs1, [])

        # Repeated publication
        pub2 = generate_all_pdfs(
            source_dir_path=self.source_dir,
            output_dir_path=target_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(len(pub2), 24)
        errs2 = validate_pdfs(
            output_dir_path=target_dir,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(errs2, [])

    # --- Exact Content Validation Tests ---

    def test_22_added_paragraph_between_approved_paragraphs_rejected(self):
        """22. Verify an added paragraph between approved paragraphs is rejected."""
        temp_copy = self._create_temp_pdf_copy()
        src_path = self.source_dir / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        mutated_secs[0][1].insert(1, "This is an unapproved additional paragraph between approved sections.")

        build_pdf(temp_copy / "engineering" / "eng_001_v1.pdf", meta, title, mutated_secs)
        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("content does not match source Markdown" in err and "ENG-001" in err for err in errors),
            f"Expected content mismatch error, got: {errors}",
        )

    def test_23_extra_text_after_final_paragraph_rejected(self):
        """23. Verify extra text after the final paragraph is rejected."""
        temp_copy = self._create_temp_pdf_copy()
        src_path = self.source_dir / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        mutated_secs[-1][1].append("Unauthorized appendix paragraph after revision history.")

        build_pdf(temp_copy / "engineering" / "eng_001_v1.pdf", meta, title, mutated_secs)
        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("content does not match source Markdown" in err and "ENG-001" in err for err in errors),
            f"Expected content mismatch error, got: {errors}",
        )

    def test_24_missing_paragraph_rejected(self):
        """24. Verify a missing paragraph is rejected."""
        temp_copy = self._create_temp_pdf_copy()
        src_path = self.source_dir / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        del mutated_secs[1][1][0]  # Omit first paragraph of P1 section

        build_pdf(temp_copy / "engineering" / "eng_001_v1.pdf", meta, title, mutated_secs)
        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("content does not match source Markdown" in err and "ENG-001" in err for err in errors),
            f"Expected content mismatch error, got: {errors}",
        )

    def test_25_reordered_paragraphs_rejected(self):
        """25. Verify reordered paragraphs are rejected."""
        temp_copy = self._create_temp_pdf_copy()
        src_path = self.source_dir / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        mutated_secs[1][1].reverse()  # Reverse paragraphs in P1 section

        build_pdf(temp_copy / "engineering" / "eng_001_v1.pdf", meta, title, mutated_secs)
        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("content does not match source Markdown" in err and "ENG-001" in err for err in errors),
            f"Expected content mismatch error, got: {errors}",
        )

    def test_26_changed_numerical_values_rejected(self):
        """26. Verify changed numerical values are rejected."""
        temp_copy = self._create_temp_pdf_copy()
        src_path = self.source_dir / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        mutated_secs[1][1][1] = mutated_secs[1][1][1].replace("10 minutes", "15 minutes")

        build_pdf(temp_copy / "engineering" / "eng_001_v1.pdf", meta, title, mutated_secs)
        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("content does not match source Markdown" in err and "ENG-001" in err for err in errors),
            f"Expected content mismatch error, got: {errors}",
        )

    def test_27_changed_punctuation_rejected(self):
        """27. Verify changed punctuation is rejected."""
        temp_copy = self._create_temp_pdf_copy()
        src_path = self.source_dir / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        mutated_secs[0][1][0] = mutated_secs[0][1][0].replace("availability.", "availability!")

        build_pdf(temp_copy / "engineering" / "eng_001_v1.pdf", meta, title, mutated_secs)
        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("content does not match source Markdown" in err and "ENG-001" in err for err in errors),
            f"Expected content mismatch error, got: {errors}",
        )

    def test_28_valid_metadata_headers_and_footers_accepted(self):
        """28. Verify standard metadata, headers, and footers remain fully accepted."""
        errors = validate_pdfs(
            output_dir_path=self.temp_dir,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(errors, [])

    # --- Invalid PDF Handling Tests ---

    def test_29_encrypted_pdf_rejected_without_crash(self):
        """29. Verify an encrypted PDF is rejected cleanly without crashing."""
        temp_copy = self._create_temp_pdf_copy()
        target_pdf = temp_copy / "engineering" / "eng_001_v1.pdf"

        # Encrypt the PDF
        reader = pypdf.PdfReader(str(target_pdf))
        writer = pypdf.PdfWriter()
        for p in reader.pages:
            writer.add_page(p)
        writer.encrypt("secure_password")
        with open(target_pdf, "wb") as f:
            writer.write(f)

        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("PDF ENG-001 is encrypted" in err for err in errors),
            f"Expected encryption error, got: {errors}",
        )

    def test_30_corrupted_pdf_rejected_cleanly(self):
        """30. Verify a corrupted or malformed PDF is rejected cleanly without crashing."""
        temp_copy = self._create_temp_pdf_copy()
        corrupted = temp_copy / "engineering" / "eng_001_v1.pdf"
        corrupted.write_bytes(b"%PDF-1.4\xff\xfe\x00\x01MALFORMED_HEADER_DATA")

        errors = validate_pdfs(
            output_dir_path=temp_copy,
            source_dir_path=self.source_dir,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("Corrupted or invalid PDF" in err and "ENG-001" in err for err in errors),
            f"Expected corrupted PDF error, got: {errors}",
        )

    def test_31_page_extraction_or_metadata_reading_errors_produce_clear_validation_errors(self):
        """31. Verify page extraction and metadata reading errors produce clear validation errors."""
        temp_copy = self._create_temp_pdf_copy()

        # 1. Page extraction failure
        with patch.object(pypdf.PageObject, "extract_text", side_effect=pypdf.errors.PdfReadError("Simulated extraction error")):
            errors = validate_pdfs(
                output_dir_path=temp_copy,
                source_dir_path=self.source_dir,
                spec_dir_path=self.spec_dir,
            )
            self.assertTrue(
                any("Failed to extract text from PDF" in err for err in errors),
                f"Expected extraction failure error, got: {errors}",
            )

        # 2. Metadata reading failure
        with patch.object(pypdf.PdfReader, "metadata", new_callable=PropertyMock, side_effect=pypdf.errors.PdfReadError("Simulated metadata error")):
            errors = validate_pdfs(
                output_dir_path=temp_copy,
                source_dir_path=self.source_dir,
                spec_dir_path=self.spec_dir,
            )
            self.assertTrue(
                any("Failed to read metadata from PDF" in err for err in errors),
                f"Expected metadata failure error, got: {errors}",
            )

    # --- Multi-Page, Directory-Safety & Advanced Cleanup Tests ---

    def test_32_multipage_pdf_passes_exact_validation(self):
        """32. Verify genuine multi-page A4 PDF validates exact full text and layout across page breaks."""
        temp_src = self._create_temp_source_copy()
        temp_out = self._create_temp_pdf_copy()

        # Expand ENG-001 in temp_src with extra paragraphs to force a page break
        eng_src_path = temp_src / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(eng_src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        for i in range(12):
            mutated_secs[0][1].append(
                f"Operational procedure addendum paragraph {i} defining detailed technical workflows for incident management."
            )

        # Write mutated Markdown back
        md_lines = ["---", "document_id: ENG-001", "document_version: v1", "owner_department: engineering", "classification: department", "---", "", f"# {title}", ""]
        for s_title, paras in mutated_secs:
            md_lines.append(f"## {s_title}")
            for p in paras:
                md_lines.append(p)
                md_lines.append("")
        eng_src_path.write_text("\n".join(md_lines), encoding="utf-8")

        # Build multi-page PDF into temp_out
        eng_pdf_path = temp_out / "engineering" / "eng_001_v1.pdf"
        build_pdf(eng_pdf_path, meta, title, mutated_secs)

        # 1. Assert PDF has at least two pages
        reader = pypdf.PdfReader(str(eng_pdf_path))
        self.assertGreaterEqual(len(reader.pages), 2, "Test multi-page PDF must have at least 2 pages")

        # 2. Every page has correct footer; pages after page 1 have expected running header
        for page_idx, page in enumerate(reader.pages):
            p_text = page.extract_text() or ""
            self.assertIn("Aster Systems Internal Documentation", p_text)
            self.assertIn(f"Page {page_idx + 1} of {len(reader.pages)}", p_text)
            if page_idx > 0:
                self.assertIn("Aster Systems — ENG-001", p_text)

        # 3. Exact full-text validation passes
        errors = validate_pdfs(
            output_dir_path=temp_out,
            source_dir_path=temp_src,
            spec_dir_path=self.spec_dir,
        )
        self.assertEqual(errors, [], f"Multi-page PDF failed validation: {errors}")

    def test_33_multipage_pdf_rejects_unrelated_content(self):
        """33. Verify multi-page PDF validator rejects unauthorized extra text across pages."""
        temp_src = self._create_temp_source_copy()
        temp_out = self._create_temp_pdf_copy()

        eng_src_path = temp_src / "engineering" / "eng_001.md"
        meta, title, secs = load_source_document(eng_src_path)
        mutated_secs = [(s[0], list(s[1])) for s in secs]
        for i in range(12):
            mutated_secs[0][1].append(
                f"Operational procedure addendum paragraph {i} defining detailed technical workflows for incident management."
            )

        md_lines = ["---", "document_id: ENG-001", "document_version: v1", "owner_department: engineering", "classification: department", "---", "", f"# {title}", ""]
        for s_title, paras in mutated_secs:
            md_lines.append(f"## {s_title}")
            for p in paras:
                md_lines.append(p)
                md_lines.append("")
        eng_src_path.write_text("\n".join(md_lines), encoding="utf-8")

        # In PDF only, insert an extra unapproved paragraph on page 2
        mutated_pdf_secs = [(s[0], list(s[1])) for s in mutated_secs]
        mutated_pdf_secs[3][1].append("Unauthorized injected clause on page two.")

        eng_pdf_path = temp_out / "engineering" / "eng_001_v1.pdf"
        build_pdf(eng_pdf_path, meta, title, mutated_pdf_secs)

        errors = validate_pdfs(
            output_dir_path=temp_out,
            source_dir_path=temp_src,
            spec_dir_path=self.spec_dir,
        )
        self.assertTrue(
            any("content does not match source Markdown" in err and "ENG-001" in err for err in errors),
            f"Expected multi-page content mismatch error, got: {errors}",
        )

    def test_34_no_previous_collection_post_publication_failure_cleans_up(self):
        """34. Verify failure during post-publication validation with no previous collection cleans up installed files."""
        base_dir = _get_temp_dir_on_same_volume(PROJECT_ROOT / "data" / "pdfs", prefix="astercite_noprev_pub_")
        target_dir = base_dir / "target_published_pdfs"
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)

        orig_validate = validate_pdfs
        staged_validated = False

        def fail_post_pub(*args, **kwargs):
            nonlocal staged_validated
            out_p = Path(kwargs.get("output_dir_path", args[0] if args else ""))
            if out_p.resolve() == target_dir.resolve():
                return ["Simulated post-publication checksum discrepancy on installed collection"]
            staged_validated = True
            return orig_validate(*args, **kwargs)

        with patch("scripts.validate_pdfs.validate_pdfs", side_effect=fail_post_pub):
            with self.assertRaises(RuntimeError) as ctx:
                generate_all_pdfs(
                    source_dir_path=self.source_dir,
                    output_dir_path=target_dir,
                    spec_dir_path=self.spec_dir,
                )
            self.assertIn("Published PDF collection failed validation", str(ctx.exception))

        # Confirm staged validation was reached and passed
        self.assertTrue(staged_validated, "Staged collection validation should have passed before publication")
        # Confirm no incomplete published files remain in target_dir
        remaining_pdfs = list(target_dir.rglob("*.pdf")) if target_dir.exists() else []
        self.assertEqual(remaining_pdfs, [], "Failed installation without previous collection must leave 0 PDFs")

    def test_35_unexpected_empty_root_directory_rejected_and_preserved(self):
        """35. Verify unexpected empty root-level directory is rejected before swap and preserved."""
        temp_pub = self._create_temp_pdf_copy()
        pre_hashes = {
            str(p.relative_to(temp_pub)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in temp_pub.rglob("*_v1.pdf")
        }

        extra_dir = temp_pub / "private_notes"
        extra_dir.mkdir()

        with self.assertRaises(RuntimeError) as ctx:
            generate_all_pdfs(
                source_dir_path=self.source_dir,
                output_dir_path=temp_pub,
                spec_dir_path=self.spec_dir,
            )

        self.assertIn("unexpected filesystem entries", str(ctx.exception))
        self.assertIn("private_notes", str(ctx.exception))
        self.assertTrue(extra_dir.exists(), "Unexpected directory must be preserved")

        post_hashes = {
            str(p.relative_to(temp_pub)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in temp_pub.rglob("*_v1.pdf")
        }
        self.assertEqual(pre_hashes, post_hashes, "Existing PDF hashes must remain unchanged after rejection")

    def test_36_unexpected_empty_nested_directory_rejected_and_preserved(self):
        """36. Verify unexpected empty nested directory is rejected before swap and preserved."""
        temp_pub = self._create_temp_pdf_copy()
        pre_hashes = {
            str(p.relative_to(temp_pub)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in temp_pub.rglob("*_v1.pdf")
        }

        extra_nested = temp_pub / "engineering" / "archive"
        extra_nested.mkdir(parents=True)

        with self.assertRaises(RuntimeError) as ctx:
            generate_all_pdfs(
                source_dir_path=self.source_dir,
                output_dir_path=temp_pub,
                spec_dir_path=self.spec_dir,
            )

        self.assertIn("unexpected filesystem entries", str(ctx.exception))
        self.assertTrue(extra_nested.exists(), "Unexpected nested directory must be preserved")

        post_hashes = {
            str(p.relative_to(temp_pub)): hashlib.sha256(p.read_bytes()).hexdigest()
            for p in temp_pub.rglob("*_v1.pdf")
        }
        self.assertEqual(pre_hashes, post_hashes, "Existing PDF hashes must remain unchanged after rejection")

    def test_37_backup_deletion_failure_preserves_valid_published_collection(self):
        """37. Verify backup deletion failure after successful publication does not destroy valid collection."""
        base_dir = _get_temp_dir_on_same_volume(PROJECT_ROOT / "data" / "pdfs", prefix="astercite_bk_del_")
        target_dir = base_dir / "published_pdfs"
        self.addCleanup(shutil.rmtree, base_dir, ignore_errors=True)

        # First publication
        generate_all_pdfs(self.source_dir, target_dir, self.spec_dir)

        # Second publication where backup_base deletion fails
        orig_rmtree = shutil.rmtree

        def mock_rmtree_bk(path, *args, **kwargs):
            if "astercite_pdf_backup_" in str(path):
                raise PermissionError("Simulated backup directory lock")
            return orig_rmtree(path, *args, **kwargs)

        with patch("shutil.rmtree", side_effect=mock_rmtree_bk):
            paths = generate_all_pdfs(self.source_dir, target_dir, self.spec_dir)
            self.assertEqual(len(paths), 24)

        # Valid published collection is preserved
        errors = validate_pdfs(target_dir, self.source_dir, self.spec_dir)
        self.assertEqual(errors, [])

    def test_38_failed_replacement_removal_preserves_recoverable_backup(self):
        """38. Verify failure during replacement cleanup preserves recoverable backup and reports location."""
        temp_pub = self._create_temp_pdf_copy()

        orig_rmtree = shutil.rmtree

        # When post-publication validation fails AND removing output_dir fails
        orig_validate = validate_pdfs

        def fail_final(*args, **kwargs):
            out_p = Path(kwargs.get("output_dir_path", args[0] if args else ""))
            if out_p.resolve() == temp_pub.resolve():
                return ["Simulated post-publication checksum discrepancy"]
            return orig_validate(*args, **kwargs)

        def mock_rmtree_fail_output(path, *args, **kwargs):
            if Path(path).resolve() == temp_pub.resolve():
                raise PermissionError("Simulated output directory lock during rollback")
            return orig_rmtree(path, *args, **kwargs)

        with patch("scripts.validate_pdfs.validate_pdfs", side_effect=fail_final):
            with patch("shutil.rmtree", side_effect=mock_rmtree_fail_output):
                with self.assertRaises(RuntimeError) as ctx:
                    generate_all_pdfs(self.source_dir, temp_pub, self.spec_dir)

        msg = str(ctx.exception)
        self.assertIn("CRITICAL: Rollback failed", msg)
        self.assertIn("previous collection preserved at", msg)


if __name__ == "__main__":
    unittest.main()
