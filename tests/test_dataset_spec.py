import csv
from pathlib import Path
import shutil
import sys
import tempfile
import unittest
import yaml

# Ensure project root is in python path
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from scripts.validate_dataset import check_document_access, validate_dataset


class TestDatasetSpec(unittest.TestCase):
    """Test suite validating Aster Systems data specification files."""

    def setUp(self):
        self.spec_dir = PROJECT_ROOT / "data" / "spec"

    def _create_temp_spec(self) -> Path:
        """Create a temporary copy of data/spec for negative testing."""
        temp_dir = Path(tempfile.mkdtemp())
        self.addCleanup(shutil.rmtree, temp_dir, ignore_errors=True)
        dest = temp_dir / "spec"
        shutil.copytree(self.spec_dir, dest)
        return dest

    def test_full_dataset_passes_validation(self):
        """1. Confirm that the current dataset passes all validation checks."""
        errors = validate_dataset(self.spec_dir)
        self.assertEqual(errors, [])

    def test_unknown_referenced_document_rejected(self):
        """2. Confirm that an unknown referenced document in cross_references is rejected."""
        temp_spec = self._create_temp_spec()
        cr_path = temp_spec / "cross_references.csv"
        with open(cr_path, "a", encoding="utf-8") as f:
            f.write("ENG-001,UNKNOWN-999,test_ref,testing unknown destination doc.\n")

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("UNKNOWN-999" in err for err in errors))

    def test_missing_or_invalid_document_permission_rejected(self):
        """3. Confirm that an invalid role in access policy is rejected."""
        temp_spec = self._create_temp_spec()
        policy_path = temp_spec / "access_policy.yaml"
        with open(policy_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        data["documents"]["ENG-001"]["allowed_roles"] = ["superadmin"]
        with open(policy_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("allowed_roles in policy" in err for err in errors))

    def test_duplicate_fact_key_rejected(self):
        """4. Confirm that duplicate (fact_id, document_version) is rejected."""
        temp_spec = self._create_temp_spec()
        facts_path = temp_spec / "fact_registry.csv"
        with open(facts_path, "a", encoding="utf-8") as f:
            f.write("ENG001_F01,v1,ENG-001,p1_incident_acknowledgment,10,minutes,engineer,2026-11-01,\n")

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("Duplicate fact key" in err for err in errors))

    def test_planned_revision_incorrect_old_value_rejected(self):
        """5. Confirm that a planned revision with an incorrect old value is rejected."""
        temp_spec = self._create_temp_spec()
        company_path = temp_spec / "company_spec.yaml"
        with open(company_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        data["planned_revisions"][1]["changes"][0]["old_value"] = "99"
        with open(company_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("old_value" in err for err in errors))

    def test_v1_fact_incorrect_value_rejected(self):
        """6. Confirm that a v1 fact with an incorrect value is rejected."""
        temp_spec = self._create_temp_spec()
        facts_path = temp_spec / "fact_registry.csv"
        with open(facts_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("HR001_F01,v1,HR-001,annual_leave_allowance,18,", "HR001_F01,v1,HR-001,annual_leave_allowance,20,")
        with open(facts_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("HR001_F01 exact_value mismatch" in err for err in errors))

    def test_fact_incorrect_unit_rejected(self):
        """7. Confirm that a fact with an incorrect unit is rejected."""
        temp_spec = self._create_temp_spec()
        facts_path = temp_spec / "fact_registry.csv"
        with open(facts_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("ENG001_F01,v1,ENG-001,p1_incident_acknowledgment,10,minutes,", "ENG001_F01,v1,ENG-001,p1_incident_acknowledgment,10,seconds,")
        with open(facts_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("ENG001_F01 unit mismatch" in err for err in errors))

    def test_fact_wrong_source_document_rejected(self):
        """8. Confirm that a fact assigned to the wrong source document is rejected."""
        temp_spec = self._create_temp_spec()
        facts_path = temp_spec / "fact_registry.csv"
        with open(facts_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("ITS003_F02,v1,ITS-003,", "ITS003_F02,v1,ENG-001,")
        with open(facts_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("ITS003_F02 source_doc_id mismatch" in err for err in errors))

    def test_document_invalid_active_version_rejected(self):
        """9. Confirm that a document with an invalid active version is rejected."""
        temp_spec = self._create_temp_spec()
        inv_path = temp_spec / "document_inventory.csv"
        with open(inv_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("ENG-003,Deployment & Rollback Procedure,engineering,department,engineer|team_lead,engineering,ENG-004,v1|v2,v1,synthetic", "ENG-003,Deployment & Rollback Procedure,engineering,department,engineer|team_lead,engineering,ENG-004,v1|v2,v2,synthetic")
        with open(inv_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("active_version must be v1" in err for err in errors))

    def test_incorrectly_placed_outline_fact_rejected(self):
        """10. Confirm that an incorrectly placed document outline fact is rejected."""
        temp_spec = self._create_temp_spec()
        outlines_path = temp_spec / "document_outlines.yaml"
        with open(outlines_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        data[0]["sections"][1]["fact_ids"] = ["ENG001_F02"]
        with open(outlines_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("fact_ids mismatch" in err for err in errors))

    def test_unrelated_team_lead_cannot_access_protected_document(self):
        """11. Confirm that an unrelated team lead cannot access another department's protected document."""
        with open(self.spec_dir / "access_policy.yaml", "r", encoding="utf-8") as f:
            policy_data = yaml.safe_load(f)

        docs = policy_data["documents"]
        # Engineering team lead can access ENG-006
        self.assertTrue(check_document_access(docs["ENG-006"], ["team_lead"], "engineering"))
        # Finance team lead cannot access ENG-006
        self.assertFalse(check_document_access(docs["ENG-006"], ["team_lead"], "finance_operations"))
        # Engineering team lead cannot access HR-005
        self.assertFalse(check_document_access(docs["HR-005"], ["team_lead"], "engineering"))
        # People Operations team lead can access HR-005
        self.assertTrue(check_document_access(docs["HR-005"], ["team_lead"], "people_operations"))
        # Engineering team lead cannot access OPS-002
        self.assertFalse(check_document_access(docs["OPS-002"], ["team_lead"], "engineering"))
        # Finance team lead can access OPS-002
        self.assertTrue(check_document_access(docs["OPS-002"], ["team_lead"], "finance_operations"))

    def test_cross_document_reference_does_not_grant_access(self):
        """12. Confirm that a cross-document reference does not grant access to restricted destination."""
        with open(self.spec_dir / "access_policy.yaml", "r", encoding="utf-8") as f:
            policy_data = yaml.safe_load(f)

        docs = policy_data["documents"]
        # ENG-002 references ENG-006. An engineer can read ENG-002.
        self.assertTrue(check_document_access(docs["ENG-002"], ["engineer"]))
        # But an engineer cannot read ENG-006 (restricted to team_lead).
        self.assertFalse(check_document_access(docs["ENG-006"], ["engineer"]))

    def test_document_without_relationships_allows_empty_field(self):
        """13. Confirm that documents without relationships have an empty related_documents field."""
        with open(self.spec_dir / "document_inventory.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            inv = {row["document_id"]: row for row in reader}

        # ENG-005, ITS-003, HR-001, OPS-003, OPS-006 have no relationships
        self.assertEqual(inv["ENG-005"]["related_documents"], "")
        self.assertEqual(inv["ITS-003"]["related_documents"], "")
        self.assertEqual(inv["HR-001"]["related_documents"], "")
        self.assertEqual(inv["OPS-003"]["related_documents"], "")
        self.assertEqual(inv["OPS-006"]["related_documents"], "")


if __name__ == "__main__":
    unittest.main()
