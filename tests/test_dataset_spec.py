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
        self.assertTrue(any("allowed_roles" in err for err in errors))

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

        content = content.replace(",v1,synthetic", ",v2,synthetic")
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
        # Engineering team lead can access ENG-006 (restricted)
        self.assertTrue(check_document_access(docs["ENG-006"], ["team_lead"], "restricted", "engineering"))
        # Finance team lead cannot access ENG-006
        self.assertFalse(check_document_access(docs["ENG-006"], ["team_lead"], "restricted", "finance_operations"))
        # Engineering team lead cannot access HR-005 (restricted)
        self.assertFalse(check_document_access(docs["HR-005"], ["team_lead"], "restricted", "engineering"))
        # People Operations team lead can access HR-005
        self.assertTrue(check_document_access(docs["HR-005"], ["team_lead"], "restricted", "people_operations"))
        # Engineering team lead cannot access OPS-002 (department)
        self.assertFalse(check_document_access(docs["OPS-002"], ["team_lead"], "department", "engineering"))
        # Finance team lead can access OPS-002
        self.assertTrue(check_document_access(docs["OPS-002"], ["team_lead"], "department", "finance_operations"))

    def test_cross_document_reference_does_not_grant_access(self):
        """12. Confirm that a cross-document reference does not grant access to restricted destination."""
        with open(self.spec_dir / "access_policy.yaml", "r", encoding="utf-8") as f:
            policy_data = yaml.safe_load(f)

        docs = policy_data["documents"]
        # ENG-002 references ENG-006. An engineer can read ENG-002 (department).
        self.assertTrue(check_document_access(docs["ENG-002"], ["engineer"], "department"))
        # But an engineer cannot read ENG-006 (restricted to team_lead).
        self.assertFalse(check_document_access(docs["ENG-006"], ["engineer"], "restricted"))

    def test_document_without_relationships_allows_empty_field(self):
        """13. Confirm that documents without relationships have an empty related_documents field."""
        with open(self.spec_dir / "document_inventory.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            inv = {row["document_id"]: row for row in reader}

        self.assertEqual(inv["ENG-005"]["related_documents"], "")
        self.assertEqual(inv["ITS-003"]["related_documents"], "")
        self.assertEqual(inv["HR-001"]["related_documents"], "")
        self.assertEqual(inv["OPS-003"]["related_documents"], "")
        self.assertEqual(inv["OPS-006"]["related_documents"], "")

    def test_inventory_and_policy_grant_employee_to_eng001_rejected(self):
        """14. Both inventory and access policy grant employee access to ENG-001 incorrectly. Validation must fail."""
        temp_spec = self._create_temp_spec()
        # In inventory
        inv_path = temp_spec / "document_inventory.csv"
        with open(inv_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(
            "ENG-001,Production Incident Severity & Escalation Policy,engineering,department,engineer|team_lead,",
            "ENG-001,Production Incident Severity & Escalation Policy,engineering,department,employee|engineer|team_lead,",
        )
        with open(inv_path, "w", encoding="utf-8") as f:
            f.write(content)

        # In policy
        policy_path = temp_spec / "access_policy.yaml"
        with open(policy_path, "r", encoding="utf-8") as f:
            p_data = yaml.safe_load(f)
        p_data["documents"]["ENG-001"]["allowed_roles"] = ["employee", "engineer", "team_lead"]
        with open(policy_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(p_data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("ENG-001" in err and "allowed_roles" in err for err in errors))

    def test_wrong_team_lead_department_in_both_files_rejected(self):
        """15. An Engineering restricted document has the wrong team lead department in both files. Validation must fail."""
        temp_spec = self._create_temp_spec()
        inv_path = temp_spec / "document_inventory.csv"
        with open(inv_path, "r", encoding="utf-8") as f:
            content = f.read()
        content = content.replace(
            "ENG-006,Service Ownership & Escalation Directory,engineering,restricted,team_lead,engineering,",
            "ENG-006,Service Ownership & Escalation Directory,engineering,restricted,team_lead,finance_operations,",
        )
        with open(inv_path, "w", encoding="utf-8") as f:
            f.write(content)

        policy_path = temp_spec / "access_policy.yaml"
        with open(policy_path, "r", encoding="utf-8") as f:
            p_data = yaml.safe_load(f)
        p_data["documents"]["ENG-006"]["team_lead_departments"] = ["finance_operations"]
        with open(policy_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(p_data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("ENG-006" in err and "team_lead_departments" in err for err in errors))

    def test_protected_document_empty_team_lead_department_denies_team_lead(self):
        """16. A protected document has an empty team lead department scope. Access through team_lead must be denied."""
        doc_perm = {"allowed_roles": ["team_lead"], "team_lead_departments": []}
        self.assertFalse(check_document_access(doc_perm, ["team_lead"], "department", "engineering"))
        self.assertFalse(check_document_access(doc_perm, ["team_lead"], "restricted", "engineering"))

    def test_general_document_empty_team_lead_department_accessible(self):
        """17. A general document with an empty team lead department scope remains accessible to permitted roles."""
        doc_perm = {"allowed_roles": ["employee", "team_lead"], "team_lead_departments": []}
        self.assertTrue(check_document_access(doc_perm, ["team_lead"], "general"))
        self.assertTrue(check_document_access(doc_perm, ["employee"], "general"))

    def test_planned_revision_incorrect_new_value_rejected(self):
        """18. The ENG-003 planned revision contains an incorrect new value. Validation must fail."""
        temp_spec = self._create_temp_spec()
        company_path = temp_spec / "company_spec.yaml"
        with open(company_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        data["planned_revisions"][0]["changes"][0]["new_value"] = "error_rate_gt_10_percent"
        with open(company_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("new_value mismatch" in err for err in errors))

    def test_planned_revision_incorrect_unit_rejected(self):
        """19. The HR-001 planned revision contains an incorrect unit. Validation must fail."""
        temp_spec = self._create_temp_spec()
        company_path = temp_spec / "company_spec.yaml"
        with open(company_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        data["planned_revisions"][1]["changes"][0]["unit"] = "weeks_per_year"
        with open(company_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("unit mismatch" in err for err in errors))

    def test_planned_revision_unexpected_additional_change_rejected(self):
        """20. OPS-002 contains an unexpected additional changed fact. Validation must fail."""
        temp_spec = self._create_temp_spec()
        company_path = temp_spec / "company_spec.yaml"
        with open(company_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        data["planned_revisions"][2]["changes"].append(
            {"fact_id": "OPS002_F03", "old_value": "x", "new_value": "y", "unit": ""}
        )
        with open(company_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("expected 2 change(s)" in err or "unexpected changed fact" in err for err in errors))

    def test_planned_revision_missing_required_change_rejected(self):
        """21. A required planned revision fact change is missing. Validation must fail."""
        temp_spec = self._create_temp_spec()
        company_path = temp_spec / "company_spec.yaml"
        with open(company_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Remove the second change from OPS-002
        data["planned_revisions"][2]["changes"].pop()
        with open(company_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("expected 2 change(s)" in err or "missing required change" in err for err in errors))

    def test_unapproved_relationship_pair_rejected(self):
        """22. A relationship is replaced with an unapproved document pair while total remains 12. Validation must fail."""
        temp_spec = self._create_temp_spec()
        cr_path = temp_spec / "cross_references.csv"
        with open(cr_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("ENG-001,ENG-002,", "ENG-001,ENG-005,")
        with open(cr_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("Unapproved relationship pair" in err or "Missing required relationship pair" in err for err in errors))

    def test_relationship_references_unknown_document_error_without_crash(self):
        """23. A relationship references an unknown document. Validation must return an error without crashing."""
        temp_spec = self._create_temp_spec()
        cr_path = temp_spec / "cross_references.csv"
        with open(cr_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("ENG-001,ENG-002,", "ENG-001,UNKNOWN-DOC,")
        with open(cr_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("UNKNOWN-DOC" in err for err in errors))

    def test_outline_fewer_than_six_sections_error_without_crash(self):
        """24. An outline contains fewer than six sections. Validation must return an error without crashing."""
        temp_spec = self._create_temp_spec()
        outlines_path = temp_spec / "document_outlines.yaml"
        with open(outlines_path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f)

        # Truncate sections of first document to 2
        data[0]["sections"] = data[0]["sections"][:2]
        with open(outlines_path, "w", encoding="utf-8") as f:
            yaml.safe_dump(data, f)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("must have 6 sections" in err for err in errors))

    def test_empty_or_invalid_top_level_yaml_error_without_crash(self):
        """25. A required YAML document is empty or has an invalid top-level structure. Validation must return an error without crashing."""
        temp_spec = self._create_temp_spec()
        company_path = temp_spec / "company_spec.yaml"
        with open(company_path, "w", encoding="utf-8") as f:
            f.write("")

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("company_spec.yaml is empty or has invalid top-level structure" in err for err in errors))

    def test_missing_required_csv_column_error_without_crash(self):
        """26. A required CSV column is missing. Validation must return an error without crashing."""
        temp_spec = self._create_temp_spec()
        inv_path = temp_spec / "document_inventory.csv"
        with open(inv_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        # Rewrite without 'classification' column
        headers = [c for c in reader.fieldnames if c != "classification"]
        with open(inv_path, "w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=headers)
            writer.writeheader()
            for r in rows:
                r_copy = {k: v for k, v in r.items() if k != "classification"}
                writer.writerow(r_copy)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("missing required columns" in err for err in errors))

    def test_fact_incorrect_effective_date_rejected(self):
        """27. A fact has an incorrect effective date. Validation must fail."""
        temp_spec = self._create_temp_spec()
        facts_path = temp_spec / "fact_registry.csv"
        with open(facts_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("ENG001_F01,v1,ENG-001,p1_incident_acknowledgment,10,minutes,engineer,2026-11-01,", "ENG001_F01,v1,ENG-001,p1_incident_acknowledgment,10,minutes,engineer,2026-10-01,")
        with open(facts_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("ENG001_F01 effective_from must be '2026-11-01'" in err for err in errors))

    def test_valid_non_team_lead_role_retains_access_despite_unmatched_dept(self):
        """28. A user with a valid non-team-lead role retains access even when their team lead department does not match."""
        doc_perm = {
            "allowed_roles": ["engineer", "team_lead"],
            "team_lead_departments": ["engineering"],
        }
        # User has engineer role and team_lead role, but department is finance_operations
        # Since engineer is explicitly allowed, user should still have access
        self.assertTrue(
            check_document_access(
                doc_perm,
                ["engineer", "team_lead"],
                "department",
                "finance_operations",
            )
        )

    def test_fact_incorrect_topic_rejected(self):
        """29. A fact has an incorrect topic. Validation must reject it with a specific topic mismatch error."""
        temp_spec = self._create_temp_spec()
        facts_path = temp_spec / "fact_registry.csv"
        with open(facts_path, "r", encoding="utf-8") as f:
            content = f.read()

        content = content.replace("annual_leave_allowance", "general_leave_allowance")
        with open(facts_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("Fact HR001_F01 topic mismatch" in err for err in errors))

    def test_fact_incorrect_applicable_role_rejected(self):
        """30. A fact has an incorrect applicable role. Use another valid role to prove exact role check."""
        temp_spec = self._create_temp_spec()
        facts_path = temp_spec / "fact_registry.csv"
        with open(facts_path, "r", encoding="utf-8") as f:
            content = f.read()

        # HR001_F01 expects 'all'; change to valid role 'hr_staff'
        content = content.replace("HR001_F01,v1,HR-001,annual_leave_allowance,18,days_per_year,all,", "HR001_F01,v1,HR-001,annual_leave_allowance,18,days_per_year,hr_staff,")
        with open(facts_path, "w", encoding="utf-8") as f:
            f.write(content)

        errors = validate_dataset(temp_spec)
        self.assertTrue(any("Fact HR001_F01 applicable_role mismatch" in err for err in errors))

    def test_mandatory_classification_checks(self):
        """31. Mandatory classification checks: invalid, None, empty, or omitted classification must be denied or raise error."""
        doc_perm = {"allowed_roles": ["employee"], "team_lead_departments": []}

        # Invalid classification denies access
        self.assertFalse(check_document_access(doc_perm, ["employee"], "confidential"))
        # Empty classification denies access
        self.assertFalse(check_document_access(doc_perm, ["employee"], ""))
        # None classification denies access
        self.assertFalse(check_document_access(doc_perm, ["employee"], None))
        # Missing classification argument raises TypeError
        with self.assertRaises(TypeError):
            check_document_access(doc_perm, ["employee"])

    def test_extra_csv_fields_rejected_without_crash(self):
        """32. Confirm unexpected extra fields in CSV files are rejected with file and row without crashing."""
        csv_files = [
            ("document_inventory.csv", 2),
            ("cross_references.csv", 2),
            ("fact_registry.csv", 2),
        ]
        for filename, row_num in csv_files:
            with self.subTest(file=filename, row=row_num):
                temp_spec = self._create_temp_spec()
                file_path = temp_spec / filename
                with open(file_path, "r", encoding="utf-8") as f:
                    lines = f.readlines()

                # Add an unexpected extra field to row 2 (index 1)
                lines[row_num - 1] = lines[row_num - 1].rstrip("\r\n") + ",unexpected_extra_field\n"
                with open(file_path, "w", encoding="utf-8") as f:
                    f.writelines(lines)

                errors = validate_dataset(temp_spec)
                expected_file_str = filename
                expected_row_str = f"row {row_num}"
                self.assertTrue(
                    any(
                        expected_file_str in err
                        and expected_row_str in err
                        and "unexpected extra field" in err
                        for err in errors
                    ),
                    f"Expected extra field error for {filename} {expected_row_str}, got: {errors}",
                )

    def test_malformed_permission_lists_rejected_without_crash(self):
        """33. Confirm malformed permission lists in access_policy.yaml and helper are rejected without crashing."""
        # 1-3. Malformed allowed_roles items: nested list, dict, number, null
        malformed_role_cases = [
            ("nested_list", [["engineer"]]),
            ("dict", [{"role": "engineer"}]),
            ("number", [42]),
            ("null", [None]),
        ]
        for label, invalid_value in malformed_role_cases:
            with self.subTest(case=f"allowed_roles_{label}"):
                temp_spec = self._create_temp_spec()
                policy_path = temp_spec / "access_policy.yaml"
                with open(policy_path, "r", encoding="utf-8") as f:
                    policy_data = yaml.safe_load(f)

                policy_data["documents"]["ENG-001"]["allowed_roles"] = invalid_value
                with open(policy_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(policy_data, f)

                errors = validate_dataset(temp_spec)
                self.assertTrue(
                    any("ENG-001" in err and "allowed_roles" in err for err in errors),
                    f"Expected error for ENG-001 allowed_roles {label}, got: {errors}",
                )

        # 4. Malformed team_lead_departments items: nested list, dict, number, null
        malformed_dept_cases = [
            ("nested_list", [["engineering"]]),
            ("dict", [{"dept": "engineering"}]),
            ("number", [99]),
            ("null", [None]),
        ]
        for label, invalid_value in malformed_dept_cases:
            with self.subTest(case=f"team_lead_departments_{label}"):
                temp_spec = self._create_temp_spec()
                policy_path = temp_spec / "access_policy.yaml"
                with open(policy_path, "r", encoding="utf-8") as f:
                    policy_data = yaml.safe_load(f)

                policy_data["documents"]["ENG-001"]["team_lead_departments"] = invalid_value
                with open(policy_path, "w", encoding="utf-8") as f:
                    yaml.safe_dump(policy_data, f)

                errors = validate_dataset(temp_spec)
                self.assertTrue(
                    any("ENG-001" in err and "team_lead_departments" in err for err in errors),
                    f"Expected error for ENG-001 team_lead_departments {label}, got: {errors}",
                )

        # 5. check_document_access() returns False for malformed permission lists
        malformed_doc_perms = [
            {"allowed_roles": [["engineer"]], "team_lead_departments": []},
            {"allowed_roles": [{"role": "engineer"}], "team_lead_departments": []},
            {"allowed_roles": [123], "team_lead_departments": []},
            {"allowed_roles": [None], "team_lead_departments": []},
            {"allowed_roles": "engineer", "team_lead_departments": []},
            {"allowed_roles": ["engineer"], "team_lead_departments": [["engineering"]]},
            {"allowed_roles": ["engineer"], "team_lead_departments": [{"dept": "engineering"}]},
            {"allowed_roles": ["engineer"], "team_lead_departments": [456]},
            {"allowed_roles": ["engineer"], "team_lead_departments": [None]},
            {"allowed_roles": ["engineer"], "team_lead_departments": "engineering"},
        ]
        for perm in malformed_doc_perms:
            with self.subTest(helper_perm=perm):
                self.assertFalse(
                    check_document_access(perm, ["engineer"], "department", "engineering")
                )
                self.assertFalse(
                    check_document_access(perm, ["team_lead"], "restricted", "engineering")
                )

        # 6. Valid permissions still work
        valid_perm = {
            "allowed_roles": ["engineer", "team_lead"],
            "team_lead_departments": ["engineering"],
        }
        self.assertTrue(
            check_document_access(valid_perm, ["engineer"], "department")
        )
        self.assertTrue(
            check_document_access(valid_perm, ["team_lead"], "department", "engineering")
        )
        self.assertFalse(
            check_document_access(valid_perm, ["team_lead"], "department", "finance_operations")
        )
        general_perm = {
            "allowed_roles": ["employee", "team_lead"],
            "team_lead_departments": [],
        }
        self.assertTrue(
            check_document_access(general_perm, ["employee"], "general")
        )
        self.assertTrue(
            check_document_access(general_perm, ["team_lead"], "general")
        )


if __name__ == "__main__":
    unittest.main()
