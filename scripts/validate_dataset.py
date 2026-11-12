import csv
from datetime import datetime
from pathlib import Path
import sys
import yaml

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

GENERAL_ROLES = [
    "employee",
    "engineer",
    "it_support",
    "hr_staff",
    "finance_staff",
    "team_lead",
]

EXPECTED_TITLES = {
    "ENG-001": "Production Incident Severity & Escalation Policy",
    "ENG-002": "On-call Handover Guide",
    "ENG-003": "Deployment & Rollback Procedure",
    "ENG-004": "Change Approval Checklist",
    "ENG-005": "Troubleshooting Known Error Codes",
    "ENG-006": "Service Ownership & Escalation Directory",
    "ITS-001": "Laptop Provisioning and Replacement",
    "ITS-002": "Account Provisioning / Deprovisioning",
    "ITS-003": "MFA and Password Reset Procedure",
    "ITS-004": "Approved Software Request Process",
    "ITS-005": "Device Loss or Theft Response",
    "ITS-006": "IT Support Ticket Priorities and SLAs",
    "HR-001": "Leave and Attendance Policy",
    "HR-002": "Remote and Hybrid Work Policy",
    "HR-003": "Employee Onboarding Process",
    "HR-004": "Learning and Training Reimbursement",
    "HR-005": "Performance Review Process",
    "HR-006": "Grievance and Escalation Procedure",
    "OPS-001": "Travel Reimbursement Policy",
    "OPS-002": "Purchase Approval Limits",
    "OPS-003": "Vendor Onboarding Checklist",
    "OPS-004": "Expense Claim Submission Process",
    "OPS-005": "Asset Procurement and Ownership",
    "OPS-006": "Business Continuity & Facilities Procedure",
}

EXPECTED_OUTLINE_TITLES = {
    "ENG-001": ("P1 Incident Acknowledgment", "P2 Incident Acknowledgment", "P1 Postmortem Requirements"),
    "ENG-002": ("Handover Schedule", "Handover Time", "Required Handover Information"),
    "ENG-003": ("Standard Deployment Days", "Deployment Window", "Rollback Conditions"),
    "ENG-004": ("High-Risk Change Approval", "Migration Change Freeze", "Emergency Change Approval"),
    "ENG-005": ("E1001 Authentication Error", "E2003 Retry Procedure", "E3002 Billing Error"),
    "ENG-006": ("Portal Service Ownership", "Authentication Service Ownership", "Billing Service Ownership"),
    "ITS-001": ("Standard Laptop Provisioning", "Urgent Laptop Replacement", "Equipment Purchase Policies"),
    "ITS-002": ("New Account Requests", "Employee Exit and Access Deactivation", "Account Request Approval"),
    "ITS-003": ("MFA Reset Verification", "MFA Reset Resolution", "Prohibited Reset Practices"),
    "ITS-004": ("Software Request Approval", "Unlisted Software Review", "Standard Request Processing"),
    "ITS-005": ("Lost Device Reporting", "Device Access Protection", "Required Incident Records"),
    "ITS-006": ("P1 Ticket Response", "P2 Ticket Response", "P3 Ticket Response"),
    "HR-001": ("Annual Leave Entitlement", "Sick Leave Entitlement", "Leave Request Process"),
    "HR-002": ("Office Attendance Requirements", "Remote Work Exceptions", "Remote Work Equipment"),
    "HR-003": ("Onboarding Preparation", "Account Provisioning", "Laptop Provisioning"),
    "HR-004": ("Training Reimbursement Limit", "Training Approval", "Reimbursement Claim Deadline"),
    "HR-005": ("Performance Review Schedule", "Goal Submission", "Review Document Access"),
    "HR-006": ("Grievance Acknowledgment", "Grievance Appeals", "Private Grievance Case Access"),
    "OPS-001": ("Domestic Travel Allowance", "Travel Booking Approval", "Travel Expense Claims"),
    "OPS-002": ("Team Lead Purchase Approval", "Finance Purchase Approval", "High-Value Purchase Approval"),
    "OPS-003": ("Vendor Onboarding Timeline", "Required Vendor Documents", "First Purchase Approval"),
    "OPS-004": ("Expense Claim Deadline", "Receipt Requirements", "Finance Review Timeline"),
    "OPS-005": ("Asset Register Ownership", "Equipment Return", "New Equipment Purchases"),
    "OPS-006": ("Continuity Testing", "Critical Service Recovery", "Continuity Escalation"),
}

EXPECTED_FACTS = {
    "ENG001_F01": {"source_doc_id": "ENG-001", "exact_value": "10", "unit": "minutes"},
    "ENG001_F02": {"source_doc_id": "ENG-001", "exact_value": "30", "unit": "minutes"},
    "ENG001_F03": {"source_doc_id": "ENG-001", "exact_value": "2", "unit": "business_days"},
    "ENG002_F01": {"source_doc_id": "ENG-002", "exact_value": "Friday", "unit": ""},
    "ENG002_F02": {"source_doc_id": "ENG-002", "exact_value": "18:00", "unit": "IST"},
    "ENG002_F03": {"source_doc_id": "ENG-002", "exact_value": "open_incidents_owner_next_action", "unit": ""},
    "ENG003_F01": {"source_doc_id": "ENG-003", "exact_value": "Tuesday_and_Thursday", "unit": ""},
    "ENG003_F02": {"source_doc_id": "ENG-003", "exact_value": "14:00-17:00", "unit": "IST"},
    "ENG003_F03": {"source_doc_id": "ENG-003", "exact_value": "error_rate_gt_5_percent_for_10_minutes", "unit": ""},
    "ENG004_F01": {"source_doc_id": "ENG-004", "exact_value": "team_lead_and_service_owner", "unit": ""},
    "ENG004_F02": {"source_doc_id": "ENG-004", "exact_value": "24", "unit": "hours"},
    "ENG004_F03": {"source_doc_id": "ENG-004", "exact_value": "1", "unit": "business_days"},
    "ENG005_F01": {"source_doc_id": "ENG-005", "exact_value": "expired_authentication_token_sign_in_again", "unit": ""},
    "ENG005_F02": {"source_doc_id": "ENG-005", "exact_value": "60", "unit": "seconds"},
    "ENG005_F03": {"source_doc_id": "ENG-005", "exact_value": "billing_sync_pending_check_reconciliation_status", "unit": ""},
    "ENG006_F01": {"source_doc_id": "ENG-006", "exact_value": "platform_team", "unit": ""},
    "ENG006_F02": {"source_doc_id": "ENG-006", "exact_value": "identity_team", "unit": ""},
    "ENG006_F03": {"source_doc_id": "ENG-006", "exact_value": "payments_team", "unit": ""},
    "ITS001_F01": {"source_doc_id": "ITS-001", "exact_value": "3", "unit": "business_days"},
    "ITS001_F02": {"source_doc_id": "ITS-001", "exact_value": "1", "unit": "business_days"},
    "ITS001_F03": {"source_doc_id": "ITS-001", "exact_value": "OPS-005_and_OPS-002", "unit": ""},
    "ITS002_F01": {"source_doc_id": "ITS-002", "exact_value": "2", "unit": "business_days"},
    "ITS002_F02": {"source_doc_id": "ITS-002", "exact_value": "4", "unit": "hours"},
    "ITS002_F03": {"source_doc_id": "ITS-002", "exact_value": "hr_staff", "unit": ""},
    "ITS003_F01": {"source_doc_id": "ITS-003", "exact_value": "identity_verification_and_service_ticket", "unit": ""},
    "ITS003_F02": {"source_doc_id": "ITS-003", "exact_value": "4", "unit": "business_hours"},
    "ITS003_F03": {"source_doc_id": "ITS-003", "exact_value": "prohibited", "unit": ""},
    "ITS004_F01": {"source_doc_id": "ITS-004", "exact_value": "team_lead", "unit": ""},
    "ITS004_F02": {"source_doc_id": "ITS-004", "exact_value": "security_review_required", "unit": ""},
    "ITS004_F03": {"source_doc_id": "ITS-004", "exact_value": "3", "unit": "business_days"},
    "ITS005_F01": {"source_doc_id": "ITS-005", "exact_value": "1", "unit": "hours"},
    "ITS005_F02": {"source_doc_id": "ITS-005", "exact_value": "disable_device_access", "unit": ""},
    "ITS005_F03": {"source_doc_id": "ITS-005", "exact_value": "it_support_ticket", "unit": ""},
    "ITS006_F01": {"source_doc_id": "ITS-006", "exact_value": "15", "unit": "minutes"},
    "ITS006_F02": {"source_doc_id": "ITS-006", "exact_value": "2", "unit": "business_hours"},
    "ITS006_F03": {"source_doc_id": "ITS-006", "exact_value": "1", "unit": "business_days"},
    "HR001_F01": {"source_doc_id": "HR-001", "exact_value": "18", "unit": "days_per_year"},
    "HR001_F02": {"source_doc_id": "HR-001", "exact_value": "10", "unit": "days_per_year"},
    "HR001_F03": {"source_doc_id": "HR-001", "exact_value": "3", "unit": "business_days"},
    "HR002_F01": {"source_doc_id": "HR-002", "exact_value": "2", "unit": "days_per_week"},
    "HR002_F02": {"source_doc_id": "HR-002", "exact_value": "team_lead", "unit": ""},
    "HR002_F03": {"source_doc_id": "HR-002", "exact_value": "ITS-004_and_OPS-005", "unit": ""},
    "HR003_F01": {"source_doc_id": "HR-003", "exact_value": "5", "unit": "business_days_before_join"},
    "HR003_F02": {"source_doc_id": "HR-003", "exact_value": "ITS-002", "unit": ""},
    "HR003_F03": {"source_doc_id": "HR-003", "exact_value": "ITS-001", "unit": ""},
    "HR004_F01": {"source_doc_id": "HR-004", "exact_value": "20000", "unit": "inr"},
    "HR004_F02": {"source_doc_id": "HR-004", "exact_value": "team_lead", "unit": ""},
    "HR004_F03": {"source_doc_id": "HR-004", "exact_value": "30", "unit": "calendar_days"},
    "HR005_F01": {"source_doc_id": "HR-005", "exact_value": "April_and_October", "unit": ""},
    "HR005_F02": {"source_doc_id": "HR-005", "exact_value": "5", "unit": "business_days_before_review"},
    "HR005_F03": {"source_doc_id": "HR-005", "exact_value": "hr_staff_and_team_lead", "unit": ""},
    "HR006_F01": {"source_doc_id": "HR-006", "exact_value": "2", "unit": "business_days"},
    "HR006_F02": {"source_doc_id": "HR-006", "exact_value": "10", "unit": "business_days"},
    "HR006_F03": {"source_doc_id": "HR-006", "exact_value": "hr_staff_only", "unit": ""},
    "OPS001_F01": {"source_doc_id": "OPS-001", "exact_value": "1500", "unit": "inr_per_day"},
    "OPS001_F02": {"source_doc_id": "OPS-001", "exact_value": "required_before_booking", "unit": ""},
    "OPS001_F03": {"source_doc_id": "OPS-001", "exact_value": "OPS-004", "unit": ""},
    "OPS002_F01": {"source_doc_id": "OPS-002", "exact_value": "25000", "unit": "inr"},
    "OPS002_F02": {"source_doc_id": "OPS-002", "exact_value": "above_25000_through_100000", "unit": ""},
    "OPS002_F03": {"source_doc_id": "OPS-002", "exact_value": "finance_staff_and_team_lead_approval", "unit": ""},
    "OPS003_F01": {"source_doc_id": "OPS-003", "exact_value": "5", "unit": "business_days"},
    "OPS003_F02": {"source_doc_id": "OPS-003", "exact_value": "tax_registration_and_verified_bank_details", "unit": ""},
    "OPS003_F03": {"source_doc_id": "OPS-003", "exact_value": "finance_staff", "unit": ""},
    "OPS004_F01": {"source_doc_id": "OPS-004", "exact_value": "30", "unit": "calendar_days"},
    "OPS004_F02": {"source_doc_id": "OPS-004", "exact_value": "500", "unit": "inr"},
    "OPS004_F03": {"source_doc_id": "OPS-004", "exact_value": "5", "unit": "business_days"},
    "OPS005_F01": {"source_doc_id": "OPS-005", "exact_value": "it_support", "unit": ""},
    "OPS005_F02": {"source_doc_id": "OPS-005", "exact_value": "5", "unit": "business_days"},
    "OPS005_F03": {"source_doc_id": "OPS-005", "exact_value": "OPS-002", "unit": ""},
    "OPS006_F01": {"source_doc_id": "OPS-006", "exact_value": "6", "unit": "months"},
    "OPS006_F02": {"source_doc_id": "OPS-006", "exact_value": "4", "unit": "hours"},
    "OPS006_F03": {"source_doc_id": "OPS-006", "exact_value": "duty_team_lead", "unit": ""},
}


def check_document_access(
    doc_permissions: dict, user_roles: list[str], user_department: str | None = None
) -> bool:
    """Evaluate whether a user with given roles and optional department has read access."""
    allowed_roles = set(doc_permissions.get("allowed_roles", []))
    tl_depts = set(doc_permissions.get("team_lead_departments", []))

    for role in user_roles:
        if role not in allowed_roles:
            continue
        if role == "team_lead":
            if not tl_depts:
                return True
            if user_department and user_department in tl_depts:
                return True
        else:
            return True

    return False


def validate_dataset(spec_dir_path: Path | str = "data/spec") -> list[str]:
    """Validate all data specification files and return a list of error descriptions."""
    spec_dir = Path(spec_dir_path)
    errors: list[str] = []

    # 1. Required files existence
    required_files = [
        "company_spec.yaml",
        "document_inventory.csv",
        "access_policy.yaml",
        "cross_references.csv",
        "fact_registry.csv",
        "document_outlines.yaml",
    ]
    for filename in required_files:
        if not (spec_dir / filename).exists():
            errors.append(f"Missing required file: {filename}")

    if errors:
        return errors

    # 2. Parse company_spec.yaml
    company_data = None
    try:
        with open(spec_dir / "company_spec.yaml", "r", encoding="utf-8") as f:
            company_data = yaml.safe_load(f)
    except Exception as e:
        errors.append(f"company_spec.yaml failed to parse: {e}")

    # Parse access_policy.yaml
    policy_data = None
    try:
        with open(spec_dir / "access_policy.yaml", "r", encoding="utf-8") as f:
            policy_data = yaml.safe_load(f)
    except Exception as e:
        errors.append(f"access_policy.yaml failed to parse: {e}")

    # Parse document_outlines.yaml
    outlines_data = None
    try:
        with open(spec_dir / "document_outlines.yaml", "r", encoding="utf-8") as f:
            outlines_data = yaml.safe_load(f)
    except Exception as e:
        errors.append(f"document_outlines.yaml failed to parse: {e}")

    if errors:
        return errors

    # 3. Company checks
    if company_data.get("company_name") != "Aster Systems":
        errors.append(f"Invalid company name: {company_data.get('company_name')}")
    if company_data.get("time_zone") != "Asia/Kolkata":
        errors.append(f"Invalid time zone: {company_data.get('time_zone')}")
    if company_data.get("currency") != "INR":
        errors.append(f"Invalid currency: {company_data.get('currency')}")
    if company_data.get("departments") != EXPECTED_DEPARTMENTS:
        errors.append(f"Invalid departments: {company_data.get('departments')}")
    if company_data.get("roles") != VALID_ROLES:
        errors.append(f"Invalid roles: {company_data.get('roles')}")

    # 4. Inventory checks
    inventory_rows = []
    inventory_doc_ids = set()
    dept_counts: dict[str, int] = {}
    try:
        with open(spec_dir / "document_inventory.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            expected_headers = [
                "document_id",
                "title",
                "owner_department",
                "classification",
                "allowed_roles",
                "team_lead_departments",
                "related_documents",
                "planned_versions",
                "active_version",
                "source_type",
            ]
            if reader.fieldnames != expected_headers:
                errors.append(f"document_inventory.csv headers mismatch: {reader.fieldnames}")
            for row in reader:
                inventory_rows.append(row)
                doc_id = row["document_id"]
                if doc_id in inventory_doc_ids:
                    errors.append(f"Duplicate document_id in inventory: {doc_id}")
                inventory_doc_ids.add(doc_id)
                owner = row["owner_department"]
                dept_counts[owner] = dept_counts.get(owner, 0) + 1
    except Exception as e:
        errors.append(f"Failed to read document_inventory.csv: {e}")

    if len(inventory_rows) != 24:
        errors.append(f"Expected 24 documents in inventory, found {len(inventory_rows)}")

    for dept in EXPECTED_DEPARTMENTS:
        if dept_counts.get(dept, 0) != 6:
            errors.append(f"Department {dept} has {dept_counts.get(dept, 0)} documents, expected 6")

    policy_docs = policy_data.get("documents", {}) if policy_data else {}

    for row in inventory_rows:
        doc_id = row["document_id"]
        title = row["title"]
        if doc_id in EXPECTED_TITLES and EXPECTED_TITLES[doc_id] != title:
            errors.append(f"Document {doc_id} has title '{title}', expected '{EXPECTED_TITLES[doc_id]}'")
        if row["owner_department"] not in EXPECTED_DEPARTMENTS:
            errors.append(f"Document {doc_id} has invalid owner_department: {row['owner_department']}")
        if row["classification"] not in ["general", "department", "restricted"]:
            errors.append(f"Document {doc_id} has invalid classification: {row['classification']}")
        if row["active_version"] != "v1":
            errors.append(f"Document {doc_id} active_version must be v1, got: {row['active_version']}")
        planned_vers = row["planned_versions"].split("|")
        if "v1" not in planned_vers:
            errors.append(f"Document {doc_id} planned_versions does not contain active version v1")
        if doc_id in ["ENG-003", "HR-001", "OPS-002"]:
            if row["planned_versions"] != "v1|v2":
                errors.append(f"Document {doc_id} expected planned_versions 'v1|v2', got '{row['planned_versions']}'")
        else:
            if row["planned_versions"] != "v1":
                errors.append(f"Document {doc_id} expected planned_versions 'v1', got '{row['planned_versions']}'")
        if row["source_type"] != "synthetic":
            errors.append(f"Document {doc_id} source_type must be synthetic, got: {row['source_type']}")

        # Allowed roles
        allowed_roles = row["allowed_roles"].split("|")
        for r in allowed_roles:
            if r not in VALID_ROLES:
                errors.append(f"Document {doc_id} has invalid role: {r}")
        if "document_admin" in allowed_roles:
            errors.append(f"Document {doc_id} must not grant content access to document_admin")

        if row["classification"] == "general":
            if allowed_roles != GENERAL_ROLES:
                errors.append(f"General document {doc_id} allowed_roles mismatch: {allowed_roles}")
            if row["team_lead_departments"]:
                errors.append(f"General document {doc_id} must have empty team_lead_departments")
        else:
            if "team_lead" in allowed_roles:
                if not row["team_lead_departments"]:
                    errors.append(f"Protected document {doc_id} allowing team_lead must have team_lead_departments")
                elif row["team_lead_departments"] not in EXPECTED_DEPARTMENTS:
                    errors.append(f"Protected document {doc_id} has invalid team_lead_departments: {row['team_lead_departments']}")

        # Check matching access_policy.yaml
        if doc_id not in policy_docs:
            errors.append(f"Document {doc_id} missing in access_policy.yaml")
        else:
            p_allowed = policy_docs[doc_id].get("allowed_roles", [])
            if p_allowed != allowed_roles:
                errors.append(f"Document {doc_id} allowed_roles in policy {p_allowed} != inventory {allowed_roles}")
            p_tl_depts = policy_docs[doc_id].get("team_lead_departments", [])
            inv_tl_depts = [row["team_lead_departments"]] if row["team_lead_departments"] else []
            if p_tl_depts != inv_tl_depts:
                errors.append(f"Document {doc_id} team_lead_departments in policy {p_tl_depts} != inventory {inv_tl_depts}")

    # 5. Access policy checks & department-scoped security evaluation
    if policy_data.get("default_access") != "deny":
        errors.append("access_policy.yaml default_access must be deny")

    # Security tests on policy data
    # Test: unrelated team lead cannot access protected documents
    if not check_document_access(policy_docs.get("ENG-006", {}), ["team_lead"], "engineering"):
        errors.append("Security check failed: Engineering team lead should access ENG-006")
    if check_document_access(policy_docs.get("ENG-006", {}), ["team_lead"], "finance_operations"):
        errors.append("Security check failed: Finance team lead should NOT access ENG-006")
    if check_document_access(policy_docs.get("HR-005", {}), ["team_lead"], "engineering"):
        errors.append("Security check failed: Engineering team lead should NOT access HR-005")
    if check_document_access(policy_docs.get("OPS-002", {}), ["team_lead"], "engineering"):
        errors.append("Security check failed: Engineering team lead should NOT access OPS-002")
    if not check_document_access(policy_docs.get("ITS-001", {}), ["team_lead"], "engineering"):
        errors.append("Security check failed: Team lead should access general document ITS-001")
    if check_document_access(policy_docs.get("ENG-006", {}), ["document_admin"]):
        errors.append("Security check failed: document_admin alone should NOT read ENG-006")

    # 6. Cross references checks
    rel_rows = []
    doc_relationships: dict[str, set[str]] = {doc_id: set() for doc_id in inventory_doc_ids}
    try:
        with open(spec_dir / "cross_references.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            expected_headers = ["from_doc", "to_doc", "relationship", "explanation"]
            if reader.fieldnames != expected_headers:
                errors.append(f"cross_references.csv headers mismatch: {reader.fieldnames}")
            seen_pairs = set()
            for row in reader:
                rel_rows.append(row)
                from_doc = row["from_doc"]
                to_doc = row["to_doc"]
                if from_doc == to_doc:
                    errors.append(f"Self-referencing relationship in cross_references.csv: {from_doc}")
                pair = (from_doc, to_doc)
                if pair in seen_pairs:
                    errors.append(f"Duplicate relationship: {from_doc} -> {to_doc}")
                seen_pairs.add(pair)
                if from_doc not in inventory_doc_ids:
                    errors.append(f"cross_references from_doc not in inventory: {from_doc}")
                if to_doc not in inventory_doc_ids:
                    errors.append(f"cross_references to_doc not in inventory: {to_doc}")
                doc_relationships[from_doc].add(to_doc)
                doc_relationships[to_doc].add(from_doc)
    except Exception as e:
        errors.append(f"Failed to read cross_references.csv: {e}")

    if len(rel_rows) != 12:
        errors.append(f"Expected 12 relationships in cross_references.csv, found {len(rel_rows)}")

    # Check symmetric related_documents in inventory
    for row in inventory_rows:
        doc_id = row["document_id"]
        rel_field = row["related_documents"].strip()
        inv_related = set(rel_field.split("|")) if rel_field else set()
        expected_related = doc_relationships.get(doc_id, set())
        if inv_related != expected_related:
            errors.append(
                f"Document {doc_id} related_documents mismatch: inventory={inv_related}, expected={expected_related}"
            )

    # 7. Fact registry checks
    fact_rows = []
    seen_facts = set()
    doc_fact_count: dict[str, int] = {}
    try:
        with open(spec_dir / "fact_registry.csv", "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            expected_headers = [
                "fact_id",
                "document_version",
                "source_doc_id",
                "topic",
                "exact_value",
                "unit",
                "applicable_role",
                "effective_from",
                "effective_until",
            ]
            if reader.fieldnames != expected_headers:
                errors.append(f"fact_registry.csv headers mismatch: {reader.fieldnames}")
            for row in reader:
                fact_rows.append(row)
                fact_id = row["fact_id"]
                doc_version = row["document_version"]
                source_doc = row["source_doc_id"]
                key = (fact_id, doc_version)
                if key in seen_facts:
                    errors.append(f"Duplicate fact key (fact_id, document_version): {key}")
                seen_facts.add(key)

                if doc_version != "v1":
                    errors.append(f"Fact {fact_id} must have document_version 'v1', got '{doc_version}'")

                if source_doc not in inventory_doc_ids:
                    errors.append(f"Fact {fact_id} source_doc_id '{source_doc}' not in inventory")

                # Verify expected fact data
                if fact_id not in EXPECTED_FACTS:
                    errors.append(f"Unapproved extra fact in registry: {fact_id}")
                else:
                    exp = EXPECTED_FACTS[fact_id]
                    if source_doc != exp["source_doc_id"]:
                        errors.append(
                            f"Fact {fact_id} source_doc_id mismatch: '{source_doc}' != '{exp['source_doc_id']}'"
                        )
                    if row["exact_value"] != exp["exact_value"]:
                        errors.append(
                            f"Fact {fact_id} exact_value mismatch: '{row['exact_value']}' != '{exp['exact_value']}'"
                        )
                    if row["unit"] != exp["unit"]:
                        errors.append(
                            f"Fact {fact_id} unit mismatch: '{row['unit']}' != '{exp['unit']}'"
                        )

                if not row["topic"]:
                    errors.append(f"Fact {fact_id} topic must not be empty")

                app_role = row["applicable_role"]
                if app_role != "all" and app_role not in VALID_ROLES:
                    errors.append(f"Fact {fact_id} invalid applicable_role: {app_role}")

                try:
                    datetime.strptime(row["effective_from"], "%Y-%m-%d")
                except ValueError:
                    errors.append(f"Fact {fact_id} invalid effective_from date: {row['effective_from']}")

                if row["effective_until"]:
                    errors.append(f"Fact {fact_id} effective_until should be empty in v1")

                doc_fact_count[source_doc] = doc_fact_count.get(source_doc, 0) + 1
    except Exception as e:
        errors.append(f"Failed to read fact_registry.csv: {e}")

    if len(fact_rows) != 72:
        errors.append(f"Expected 72 facts in registry, found {len(fact_rows)}")

    for doc_id in inventory_doc_ids:
        if doc_fact_count.get(doc_id, 0) != 3:
            errors.append(f"Document {doc_id} has {doc_fact_count.get(doc_id, 0)} facts, expected 3")

    for exp_id in EXPECTED_FACTS:
        if (exp_id, "v1") not in seen_facts:
            errors.append(f"Missing required v1 fact: {exp_id}")

    # 8. Planned revisions checks
    planned_revs = company_data.get("planned_revisions", []) if company_data else []
    if len(planned_revs) != 3:
        errors.append(f"Expected 3 planned revisions, found {len(planned_revs)}")

    allowed_rev_docs = {"ENG-003", "HR-001", "OPS-002"}
    seen_rev_docs = set()
    for rev in planned_revs:
        doc_id = rev.get("document_id")
        seen_rev_docs.add(doc_id)
        if doc_id not in allowed_rev_docs:
            errors.append(f"Unapproved document in planned_revisions: {doc_id}")
        if rev.get("base_version") != "v1":
            errors.append(f"Revision for {doc_id} base_version must be v1, got: {rev.get('base_version')}")
        if rev.get("target_version") != "v2":
            errors.append(f"Revision for {doc_id} target_version must be v2, got: {rev.get('target_version')}")

        for change in rev.get("changes", []):
            f_id = change.get("fact_id")
            if f_id not in EXPECTED_FACTS:
                errors.append(f"Revision for {doc_id} references unknown fact: {f_id}")
            else:
                exp_fact = EXPECTED_FACTS[f_id]
                if change.get("old_value") != exp_fact["exact_value"]:
                    errors.append(
                        f"Revision for {doc_id} old_value '{change.get('old_value')}' != v1 fact value '{exp_fact['exact_value']}'"
                    )

    if seen_rev_docs != allowed_rev_docs:
        errors.append(f"Planned revisions document set mismatch: {seen_rev_docs} != {allowed_rev_docs}")

    # 9. Content outline checks
    if not isinstance(outlines_data, list):
        errors.append("document_outlines.yaml root must be a list")
    else:
        if len(outlines_data) != 24:
            errors.append(f"Expected 24 outlines, found {len(outlines_data)}")

        seen_outline_docs = set()
        for outline in outlines_data:
            doc_id = outline.get("document_id")
            if doc_id in seen_outline_docs:
                errors.append(f"Duplicate outline for document: {doc_id}")
            seen_outline_docs.add(doc_id)

            if doc_id not in inventory_doc_ids:
                errors.append(f"Outline references unknown document: {doc_id}")

            if outline.get("document_version") != "v1":
                errors.append(f"Outline for {doc_id} document_version must be v1, got {outline.get('document_version')}")

            sections = outline.get("sections", [])
            if len(sections) != 6:
                errors.append(f"Outline for {doc_id} must have 6 sections, found {len(sections)}")

            expected_sec_ids = ["S01", "S02", "S03", "S04", "S05", "S06"]
            actual_sec_ids = [s.get("section_id") for s in sections]
            if actual_sec_ids != expected_sec_ids:
                errors.append(f"Outline for {doc_id} sections order mismatch: {actual_sec_ids} != {expected_sec_ids}")

            if doc_id in EXPECTED_OUTLINE_TITLES:
                exp_t2, exp_t3, exp_t4 = EXPECTED_OUTLINE_TITLES[doc_id]
                if sections[0].get("title") != "Purpose and Scope":
                    errors.append(f"Outline {doc_id} S01 title mismatch: '{sections[0].get('title')}'")
                if sections[1].get("title") != exp_t2:
                    errors.append(f"Outline {doc_id} S02 title mismatch: '{sections[1].get('title')}' != '{exp_t2}'")
                if sections[2].get("title") != exp_t3:
                    errors.append(f"Outline {doc_id} S03 title mismatch: '{sections[2].get('title')}' != '{exp_t3}'")
                if sections[3].get("title") != exp_t4:
                    errors.append(f"Outline {doc_id} S04 title mismatch: '{sections[3].get('title')}' != '{exp_t4}'")
                if sections[4].get("title") != "Exceptions and Related Documents":
                    errors.append(f"Outline {doc_id} S05 title mismatch: '{sections[4].get('title')}'")
                if sections[5].get("title") != "Revision History":
                    errors.append(f"Outline {doc_id} S06 title mismatch: '{sections[5].get('title')}'")

            # Check fact placements
            prefix = doc_id.replace("-", "")
            exp_f01 = f"{prefix}_F01"
            exp_f02 = f"{prefix}_F02"
            exp_f03 = f"{prefix}_F03"

            if sections[0].get("fact_ids") != []:
                errors.append(f"Outline {doc_id} S01 fact_ids must be empty")
            if sections[1].get("fact_ids") != [exp_f01]:
                errors.append(f"Outline {doc_id} S02 fact_ids mismatch: {sections[1].get('fact_ids')} != [{exp_f01}]")
            if sections[2].get("fact_ids") != [exp_f02]:
                errors.append(f"Outline {doc_id} S03 fact_ids mismatch: {sections[2].get('fact_ids')} != [{exp_f02}]")
            if sections[3].get("fact_ids") != [exp_f03]:
                errors.append(f"Outline {doc_id} S04 fact_ids mismatch: {sections[3].get('fact_ids')} != [{exp_f03}]")
            if sections[4].get("fact_ids") != []:
                errors.append(f"Outline {doc_id} S05 fact_ids must be empty")
            if sections[5].get("fact_ids") != []:
                errors.append(f"Outline {doc_id} S06 fact_ids must be empty")

    return errors


def main() -> None:
    spec_dir = Path("data/spec")
    errors = validate_dataset(spec_dir)
    if errors:
        print(f"Dataset specification validation failed with {len(errors)} error(s):")
        for err in errors:
            print(f"  - {err}")
        sys.exit(1)
    else:
        print("Dataset specification valid: 24 documents, 72 v1 facts, 12 relationships, 24 outlines, 3 planned revisions.")
        sys.exit(0)


if __name__ == "__main__":
    main()
