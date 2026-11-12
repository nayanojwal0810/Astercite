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
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

import pypdf
import yaml

# Ensure project root is in sys.path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.generate_pdfs import generate_all_pdfs, load_source_document
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


if __name__ == "__main__":
    unittest.main()
