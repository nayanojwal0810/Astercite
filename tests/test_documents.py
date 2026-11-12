"""Test suite for Aster Systems original v1 Markdown knowledge documents.

Validates all 24 knowledge documents, metadata, section structure, fact placement,
YAML date handling, relationship directions, raw token detection, receipt threshold rules,
access-control leak prevention, and relationship coverage preservation.
"""

import datetime
from pathlib import Path
import re
import shutil
import sys
import tempfile
import unittest

# Ensure project root is in python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_documents import (
    load_specifications,
    normalize_and_check_date,
    validate_documents,
)


class TestDocuments(unittest.TestCase):
    """Unit test suite verifying 24 original v1 Markdown documents."""

    def setUp(self):
        self.source_dir = PROJECT_ROOT / "data" / "source"
        self.spec_dir = PROJECT_ROOT / "data" / "spec"
        self.specs = load_specifications(self.spec_dir)

    def _create_temp_source(self) -> Path:
        """Create a temporary copy of data/source for negative testing."""
        temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        dest = temp_dir / "source"
        shutil.copytree(self.source_dir, dest)
        return dest

    def test_01_all_valid_documents_pass_structural_validation(self):
        """1. All 24 valid documents pass structural validation."""
        errors = validate_documents(self.source_dir, self.spec_dir)
        self.assertEqual(errors, [])

    def test_02_missing_document_file_rejected(self):
        """2. A missing document file is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        doc_path.unlink()

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("Missing source document" in err and "eng_001.md" in err for err in errors))

    def test_03_unexpected_extra_markdown_file_rejected(self):
        """3. An unexpected extra Markdown file is rejected."""
        temp_source = self._create_temp_source()
        extra_file = temp_source / "engineering" / "extra_doc.md"
        extra_file.write_text("# Extra Doc\n", encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("Unexpected source document" in err and "extra_doc.md" in err for err in errors))

    def test_04_wrong_document_id_in_metadata_rejected(self):
        """4. A wrong document ID in metadata is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("document_id: ENG-001", "document_id: ENG-999"), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("document_id 'ENG-999' != expected 'ENG-001'" in err for err in errors))

    def test_05_incorrect_active_document_version_rejected(self):
        """5. An incorrect active document version is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("document_version: v1", "document_version: v2"), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("document_version must be 'v1', got: 'v2'" in err for err in errors))

    def test_06_incorrect_document_title_rejected(self):
        """6. An incorrect document title is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("Production Incident Severity & Escalation Policy", "Wrong Incident Policy"), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("metadata title 'Wrong Incident Policy' != inventory" in err for err in errors))

    def test_07_missing_section_rejected(self):
        """7. A missing section is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        s04_idx = content.find("## P1 Postmortem Requirements")
        s05_idx = content.find("## Exceptions and Related Documents")
        new_content = content[:s04_idx] + content[s05_idx:]
        doc_path.write_text(new_content, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("must have exactly 6 level-2 sections" in err for err in errors))

    def test_08_incorrect_section_title_rejected(self):
        """8. An incorrect section title is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("## P1 Postmortem Requirements", "## Wrong Section Title"), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("section titles mismatch" in err for err in errors))

    def test_09_duplicate_fact_marker_rejected(self):
        """9. A duplicate fact marker is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("fact_id: ENG001_F02", "fact_id: ENG001_F01"), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("duplicate fact markers" in err for err in errors))

    def test_10_missing_fact_marker_rejected(self):
        """10. A missing fact marker is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("<!-- fact_id: ENG001_F01 -->", ""), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("must contain exactly 3 fact markers" in err or "fact marker mismatch" in err for err in errors))

    def test_11_fact_marker_in_wrong_section_rejected(self):
        """11. A fact marker in the wrong section is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        content = content.replace("fact_id: ENG001_F01", "fact_id: TEMP_F")
        content = content.replace("fact_id: ENG001_F02", "fact_id: ENG001_F01")
        content = content.replace("fact_id: TEMP_F", "fact_id: ENG001_F02")
        doc_path.write_text(content, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("fact marker mismatch" in err for err in errors))

    def test_12_unknown_fact_id_rejected(self):
        """12. An unknown fact ID is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("fact_id: ENG001_F01", "fact_id: UNKNOWN_F99"), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("unexpected fact marker: UNKNOWN_F99" in err for err in errors))

    def test_13_empty_section_rejected(self):
        """13. An empty section is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        s01_heading = "## Purpose and Scope\n"
        s02_heading = "\n## P1 Incident Acknowledgment"
        s01_idx = content.find(s01_heading)
        s02_idx = content.find(s02_heading)
        new_content = content[:s01_idx + len(s01_heading)] + "\n" + content[s02_idx:]
        doc_path.write_text(new_content, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("section S01 ('Purpose and Scope') is empty" in err for err in errors))

    def test_14_unfinished_placeholder_rejected(self):
        """14. An unfinished placeholder is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        doc_path.write_text(content.replace("## Purpose and Scope\n", "## Purpose and Scope\nTODO: complete this section\n"), encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("contains placeholder or unfinished text: 'TODO'" in err for err in errors))

    def test_15_restricted_title_copied_into_lower_access_doc_rejected(self):
        """15. A restricted document title copied into a lower-access source document is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "it_support" / "its_004.md"
        content = doc_path.read_text(encoding="utf-8")
        leak_text = "\nThis software catalog is referenced in the Performance Review Process for evaluating goals.\n"
        doc_path.write_text(content + leak_text, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("exposes protected document title 'Performance Review Process'" in err for err in errors))

    def test_16_valid_unquoted_yaml_date_accepted(self):
        """16. A valid unquoted YAML date 2026-11-01 is accepted when PyYAML returns a datetime.date object."""
        date_obj = datetime.date(2026, 11, 1)
        errors = []
        is_valid = normalize_and_check_date(date_obj, "DOC-001", errors)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_17_valid_quoted_yaml_date_accepted(self):
        """17. A valid quoted YAML date "2026-11-01" is accepted as a string."""
        date_str = "2026-11-01"
        errors = []
        is_valid = normalize_and_check_date(date_str, "DOC-001", errors)
        self.assertTrue(is_valid)
        self.assertEqual(errors, [])

    def test_18_incorrect_unquoted_date_rejected(self):
        """18. An incorrect unquoted date, such as 2026-11-02, is rejected."""
        wrong_date_obj = datetime.date(2026, 11, 2)
        errors = []
        is_valid = normalize_and_check_date(wrong_date_obj, "DOC-001", errors)
        self.assertFalse(is_valid)
        self.assertTrue(any("2026-11-02" in err for err in errors))

    def test_19_incorrect_quoted_date_rejected(self):
        """19. An incorrect quoted date, such as "2026-11-02", is rejected."""
        wrong_date_str = "2026-11-02"
        errors = []
        is_valid = normalize_and_check_date(wrong_date_str, "DOC-001", errors)
        self.assertFalse(is_valid)
        self.assertTrue(any("2026-11-02" in err for err in errors))

    def test_20_missing_empty_or_unsupported_date_rejected(self):
        """20. A missing, empty, or unsupported date value produces a clear validation error without crashing."""
        invalid_cases = [None, "", "   ", "invalid-date-format", 20261101, ["2026-11-01"]]
        for raw_val in invalid_cases:
            with self.subTest(raw_val=raw_val):
                errors = []
                is_valid = normalize_and_check_date(raw_val, "DOC-001", errors)
                self.assertFalse(is_valid)
                self.assertGreater(len(errors), 0)

    def test_21_approved_outgoing_reference_accepted(self):
        """21. An approved outgoing reference is accepted."""
        errors = validate_documents(self.source_dir, self.spec_dir)
        eng_001_errs = [e for e in errors if "ENG-001" in e and "ENG-002" in e]
        self.assertEqual(eng_001_errs, [])

    def test_22_reversed_or_unapproved_outgoing_workflow_rejected(self):
        """22. A reversed or unapproved outgoing workflow reference is rejected."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_002.md"
        content = doc_path.read_text(encoding="utf-8")
        s05_heading = "## Exceptions and Related Documents\n"
        reversed_text = "This on-call rotation depends on ENG-001 for all incident approvals.\n"
        new_content = content.replace(s05_heading, s05_heading + reversed_text)
        doc_path.write_text(new_content, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("contains reversed or unapproved outgoing workflow reference to incoming document ENG-001" in err for err in errors))

    def test_23_valid_incoming_relationship_description_accepted(self):
        """23. A valid incoming relationship description is not incorrectly treated as an outgoing dependency."""
        errors = validate_documents(self.source_dir, self.spec_dir)
        eng_002_errs = [e for e in errors if "ENG-002" in e and "ENG-001" in e]
        self.assertEqual(eng_002_errs, [])

    def test_24_unrelated_doc_id_rejected_as_outgoing_dependency(self):
        """24. An unrelated document is not accepted as an approved outgoing dependency merely because its ID exists in the inventory."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_001.md"
        content = doc_path.read_text(encoding="utf-8")
        s05_heading = "## Exceptions and Related Documents\n"
        unrelated_text = "Operational leave policies are handled under HR-001.\n"
        new_content = content.replace(s05_heading, s05_heading + unrelated_text)
        doc_path.write_text(new_content, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("Document ENG-001 contains unapproved document reference to HR-001" in err for err in errors))

    def test_25_approved_canonical_fact_containing_protected_id_accepted(self):
        """25. An approved canonical fact containing a protected document ID is accepted."""
        errors = validate_documents(self.source_dir, self.spec_dir)
        ops_005_errs = [e for e in errors if "OPS-005" in e and "OPS-002" in e]
        self.assertEqual(ops_005_errs, [])

    def test_26_protected_document_full_title_rejected_when_exposed(self):
        """26. A protected document's full title is rejected when exposed to readers without permission."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "engineering" / "eng_002.md"
        content = doc_path.read_text(encoding="utf-8")
        leak_text = "\nEngineers should consult the Service Ownership & Escalation Directory for service contacts.\n"
        doc_path.write_text(content + leak_text, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("exposes protected document title 'Service Ownership & Escalation Directory' (from ENG-006)" in err for err in errors))

    def test_27_direct_markdown_link_to_restricted_source_file_rejected(self):
        """27. A general document cannot expose restricted information through a direct Markdown link to a source file."""
        temp_source = self._create_temp_source()
        doc_path = temp_source / "finance_operations" / "ops_005.md"
        content = doc_path.read_text(encoding="utf-8")
        link_text = "\nFor purchase thresholds, see [Purchase Limits](../finance_operations/ops_002.md).\n"
        doc_path.write_text(content + link_text, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("contains forbidden direct Markdown link to source document" in err for err in errors))

    # --- New tests required by Section 11 ---

    def test_28_raw_registry_tokens_rejected_in_visible_prose(self):
        """28. Raw database-style snake_case tokens in visible prose are rejected with document ID and token name."""
        tokens_to_test = ["business_days", "team_lead", "above_25000_through_100000"]
        for token in tokens_to_test:
            with self.subTest(token=token):
                temp_source = self._create_temp_source()
                doc_path = temp_source / "engineering" / "eng_001.md"
                content = doc_path.read_text(encoding="utf-8")
                # Insert token into visible paragraph
                mutated = content.replace("within 10 minutes", f"within 10 {token}")
                doc_path.write_text(mutated, encoding="utf-8")

                errors = validate_documents(temp_source, self.spec_dir)
                self.assertTrue(
                    any("ENG-001" in err and f"raw registry token '{token}'" in err for err in errors),
                    f"Expected error identifying ENG-001 and token '{token}', got: {errors}",
                )

    def test_29_valid_identifiers_remain_accepted(self):
        """29. Fact-marker comments, document IDs, service IDs, and YAML fields do not trigger the raw token rule."""
        # Confirm that the complete corrected source document collection has 0 raw token errors
        errors = validate_documents(self.source_dir, self.spec_dir)
        token_errors = [e for e in errors if "raw registry token" in e]
        self.assertEqual(token_errors, [])

    def test_30_correct_receipt_threshold_ops_004(self):
        """30. Verify that OPS-004 uses the approved strict threshold 'above INR 500' and lacks 'equal to or exceeding'."""
        ops_004_path = self.source_dir / "finance_operations" / "ops_004.md"
        content = ops_004_path.read_text(encoding="utf-8")

        s03_match = re.search(r"## Receipt Requirements\s+(.*?)\s+## Finance Review Timeline", content, re.DOTALL)
        self.assertIsNotNone(s03_match)
        s03_text = s03_match.group(1)

        # Confirm strict 'above INR 500' exists
        self.assertTrue(
            bool(re.search(r"\babove\s+INR\s+500\b", s03_text, re.IGNORECASE)),
            "OPS-004 S03 must state receipts are required for claims above INR 500",
        )
        # Confirm incorrect phrasing is absent
        forbidden = re.findall(r"\b(equal to or exceeding|at least|500 or more|greater than or equal to)\b", s03_text, re.IGNORECASE)
        self.assertEqual(forbidden, [], f"OPS-004 S03 contains forbidden phrasing: {forbidden}")

        # Test validator catches forbidden phrasing in temporary copy
        temp_source = self._create_temp_source()
        temp_doc = temp_source / "finance_operations" / "ops_004.md"
        temp_content = temp_doc.read_text(encoding="utf-8")
        bad_content = temp_content.replace("above INR 500", "equal to or exceeding INR 500")
        temp_doc.write_text(bad_content, encoding="utf-8")

        temp_errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(any("forbidden receipt threshold phrasing" in err for err in temp_errors))

    def test_31_protected_canonical_references_allowed(self):
        """31. Confirm approved canonical fact references containing protected IDs remain valid."""
        # ITS-001 references OPS-002 in ITS001_F03
        # HR-003 references ITS-002 in HR003_F02
        # OPS-005 references OPS-002 in OPS005_F03
        errors = validate_documents(self.source_dir, self.spec_dir)
        canonical_errors = [
            e for e in errors
            if any(p in e for p in ["ITS-001", "HR-003", "OPS-005"])
            and any(t in e for t in ["OPS-002", "ITS-002"])
        ]
        self.assertEqual(canonical_errors, [])

    def test_32_relationship_coverage_preservation(self):
        """32. Confirm safe outgoing relationship references are required in S05, while protected targets use safe wording."""
        # ENG-003 has approved outgoing relationship to safe destination ENG-004
        # Removing ENG-004 from S05 of ENG-003 must be rejected
        temp_source = self._create_temp_source()
        eng_003_path = temp_source / "engineering" / "eng_003.md"
        content = eng_003_path.read_text(encoding="utf-8")
        mutated = content.replace("ENG-004", "external change guidelines")
        eng_003_path.write_text(mutated, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("ENG-003 S05 is missing required outgoing relationship reference to ENG-004" in err for err in errors),
            f"Expected missing outgoing reference error for ENG-004, got: {errors}",
        )

        # Unchanged original documents pass
        orig_errors = validate_documents(self.source_dir, self.spec_dir)
        self.assertEqual(orig_errors, [])

    def test_33_protected_id_in_unrelated_section_rejected(self):
        """33. Reject protected document IDs exposed in unrelated sections of lower-access documents."""
        # ENG-002 is accessible to engineers; ENG-006 is restricted to engineering team leads
        # Inserting ENG-006 into S05 of ENG-002 must be rejected
        temp_source = self._create_temp_source()
        eng_002_path = temp_source / "engineering" / "eng_002.md"
        content = eng_002_path.read_text(encoding="utf-8")
        mutated = content.replace("restricted service directory", "restricted service directory ENG-006")
        eng_002_path.write_text(mutated, encoding="utf-8")

        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("ENG-002" in err and "ENG-006" in err and "protected document ID" in err for err in errors),
            f"Expected protected document ID error for ENG-006 in ENG-002, got: {errors}",
        )


    def test_34_unexpected_yaml_metadata_keys_rejected(self):
        """34. Reject unexpected YAML front-matter fields, preserving only the 7 approved keys."""
        temp_source = self._create_temp_source()
        eng_001_path = temp_source / "engineering" / "eng_001.md"
        content = eng_001_path.read_text(encoding="utf-8")

        # Test A: allowed_roles key rejected
        bad_roles = content.replace("source_type: synthetic\n", "source_type: synthetic\nallowed_roles: [employee]\n")
        eng_001_path.write_text(bad_roles, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("ENG-001 contains unexpected metadata field: allowed_roles" in err for err in errors),
            f"Expected unexpected metadata field error for allowed_roles, got: {errors}",
        )

        # Test B: approval_status key rejected
        bad_status = content.replace("source_type: synthetic\n", "source_type: synthetic\napproval_status: approved\n")
        eng_001_path.write_text(bad_status, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("ENG-001 contains unexpected metadata field: approval_status" in err for err in errors),
            f"Expected unexpected metadata field error for approval_status, got: {errors}",
        )

        # Original document passes
        eng_001_path.write_text(content, encoding="utf-8")
        orig_errors = validate_documents(temp_source, self.spec_dir)
        self.assertEqual(orig_errors, [])

    def test_35_front_matter_position_and_delimiters(self):
        """35. Require YAML front matter at file start and reject malformed/missing delimiters."""
        temp_source = self._create_temp_source()
        eng_001_path = temp_source / "engineering" / "eng_001.md"
        orig_content = eng_001_path.read_text(encoding="utf-8")

        # Case A: Leading text before opening delimiter
        leading_text = "Ordinary preamble notes\n" + orig_content
        eng_001_path.write_text(leading_text, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("front matter must start at the beginning of the file" in err for err in errors),
            f"Expected front-matter-position error, got: {errors}",
        )

        # Case B: Malformed opening delimiter (e.g. ---- or ---foo)
        malformed_open = orig_content.replace("---\n", "----\n", 1)
        eng_001_path.write_text(malformed_open, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("malformed opening front matter delimiter" in err for err in errors),
            f"Expected malformed opening delimiter error, got: {errors}",
        )

        # Case C: Missing closing delimiter
        parts = orig_content.split("---\n", 2)
        missing_close = "---\n" + parts[1] + parts[2]
        eng_001_path.write_text(missing_close, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("missing closing front matter delimiter" in err for err in errors),
            f"Expected missing closing delimiter error, got: {errors}",
        )

        # Case D: Valid existing front matter passes
        eng_001_path.write_text(orig_content, encoding="utf-8")
        orig_errors = validate_documents(temp_source, self.spec_dir)
        self.assertEqual(orig_errors, [])

    def test_36_protected_canonical_id_placement(self):
        """36. Restrict protected canonical document IDs strictly to their approved fact sections."""
        # Test A: Existing canonical references in approved sections pass
        errors = validate_documents(self.source_dir, self.spec_dir)
        self.assertEqual(errors, [])

        temp_source = self._create_temp_source()
        ops_005_path = temp_source / "finance_operations" / "ops_005.md"
        orig_content = ops_005_path.read_text(encoding="utf-8")

        # Test B: Protected ID in S01 (Purpose and Scope)
        bad_s01 = orig_content.replace(
            "## Purpose and Scope\n",
            "## Purpose and Scope\nThis policy references OPS-002 purchasing requirements. ",
        )
        ops_005_path.write_text(bad_s01, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("OPS-005" in err and "OPS-002" in err and "section S01" in err for err in errors),
            f"Expected protected ID error for OPS-002 in S01, got: {errors}",
        )

        # Test C: Protected ID in wrong factual section (S02)
        bad_s02 = orig_content.replace(
            "## Asset Register Ownership\n",
            "## Asset Register Ownership\nAsset register protocols connect to OPS-002 procedures. ",
        )
        ops_005_path.write_text(bad_s02, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("OPS-005" in err and "OPS-002" in err and "section S02" in err for err in errors),
            f"Expected protected ID error for OPS-002 in S02, got: {errors}",
        )

        # Test D: Protected ID in S05
        bad_s05 = orig_content.replace(
            "## Exceptions and Related Documents\n",
            "## Exceptions and Related Documents\nOutbound procurement aligns with OPS-002 directly. ",
        )
        ops_005_path.write_text(bad_s05, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("OPS-005" in err and "OPS-002" in err and "section S05" in err for err in errors),
            f"Expected protected ID error for OPS-002 in S05, got: {errors}",
        )

        # Test E: Safe relationship description passes without exposing OPS-002 in S05
        ops_005_path.write_text(orig_content, encoding="utf-8")
        clean_errors = validate_documents(temp_source, self.spec_dir)
        self.assertEqual(clean_errors, [])

    def test_37_unapproved_protected_id_rejected(self):
        """37. Reject unapproved protected document IDs exposed in lower-access documents."""
        temp_source = self._create_temp_source()
        hr_001_path = temp_source / "people_operations" / "hr_001.md"
        content = hr_001_path.read_text(encoding="utf-8")

        # HR-001 is general classification; inserting restricted ENG-006 must be rejected
        mutated = content.replace("## Leave Request Process\n", "## Leave Request Process\nEscalations follow ENG-006. ")
        hr_001_path.write_text(mutated, encoding="utf-8")
        errors = validate_documents(temp_source, self.spec_dir)
        self.assertTrue(
            any("HR-001" in err and "ENG-006" in err and "section S04" in err for err in errors),
            f"Expected protected document ID error for ENG-006 in HR-001, got: {errors}",
        )

    def test_38_its002_purpose_and_scope_reading_roles(self):
        """38. Verify that ITS-002 Purpose and Scope identifies IT Support and HR staff and denies team leads."""
        # 1. Authority check from access policy
        its002_policy = self.specs["access_policy"]["documents"]["ITS-002"]
        self.assertIn("it_support", its002_policy["allowed_roles"])
        self.assertIn("hr_staff", its002_policy["allowed_roles"])
        self.assertNotIn("team_lead", its002_policy["allowed_roles"])
        self.assertEqual(its002_policy["team_lead_departments"], [])

        # 2. Document content check
        its002_file = self.source_dir / "it_support" / "its_002.md"
        content = its002_file.read_text(encoding="utf-8")

        # Extract Purpose and Scope section (S01)
        match = re.search(r"## Purpose and Scope\n(.*?)(?=\n## |\Z)", content, re.DOTALL)
        self.assertIsNotNone(match, "ITS-002 missing Purpose and Scope section")
        purpose_text = match.group(1)

        # Confirm it identifies authorized readership: IT Support and HR staff
        self.assertIn(
            "This document is restricted to authorized IT Support and HR staff",
            purpose_text,
            "ITS-002 Purpose and Scope must identify IT Support and HR staff as authorized readership",
        )

        # Confirm team leads are not granted reading access
        self.assertNotIn(
            "team lead",
            purpose_text.lower(),
            "ITS-002 Purpose and Scope must not claim team leads have reading permission",
        )


if __name__ == "__main__":
    unittest.main()
