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

APPROVED_DOCUMENT_SPECS = {
    "ENG-001": {
        "classification": "department",
        "owner_department": "engineering",
        "allowed_roles": ["engineer", "team_lead"],
        "team_lead_departments": ["engineering"],
    },
    "ENG-002": {
        "classification": "department",
        "owner_department": "engineering",
        "allowed_roles": ["engineer", "team_lead"],
        "team_lead_departments": ["engineering"],
    },
    "ENG-003": {
        "classification": "department",
        "owner_department": "engineering",
        "allowed_roles": ["engineer", "team_lead"],
        "team_lead_departments": ["engineering"],
    },
    "ENG-004": {
        "classification": "department",
        "owner_department": "engineering",
        "allowed_roles": ["engineer", "team_lead"],
        "team_lead_departments": ["engineering"],
    },
    "ENG-005": {
        "classification": "department",
        "owner_department": "engineering",
        "allowed_roles": ["engineer", "it_support", "team_lead"],
        "team_lead_departments": ["engineering"],
    },
    "ENG-006": {
        "classification": "restricted",
        "owner_department": "engineering",
        "allowed_roles": ["team_lead"],
        "team_lead_departments": ["engineering"],
    },
    "ITS-001": {
        "classification": "general",
        "owner_department": "it_support",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "ITS-002": {
        "classification": "restricted",
        "owner_department": "it_support",
        "allowed_roles": ["it_support", "hr_staff"],
        "team_lead_departments": [],
    },
    "ITS-003": {
        "classification": "general",
        "owner_department": "it_support",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "ITS-004": {
        "classification": "general",
        "owner_department": "it_support",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "ITS-005": {
        "classification": "general",
        "owner_department": "it_support",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "ITS-006": {
        "classification": "general",
        "owner_department": "it_support",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "HR-001": {
        "classification": "general",
        "owner_department": "people_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "HR-002": {
        "classification": "general",
        "owner_department": "people_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "HR-003": {
        "classification": "department",
        "owner_department": "people_operations",
        "allowed_roles": ["hr_staff", "it_support", "team_lead"],
        "team_lead_departments": ["people_operations"],
    },
    "HR-004": {
        "classification": "general",
        "owner_department": "people_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "HR-005": {
        "classification": "restricted",
        "owner_department": "people_operations",
        "allowed_roles": ["hr_staff", "team_lead"],
        "team_lead_departments": ["people_operations"],
    },
    "HR-006": {
        "classification": "general",
        "owner_department": "people_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "OPS-001": {
        "classification": "general",
        "owner_department": "finance_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "OPS-002": {
        "classification": "department",
        "owner_department": "finance_operations",
        "allowed_roles": ["finance_staff", "team_lead"],
        "team_lead_departments": ["finance_operations"],
    },
    "OPS-003": {
        "classification": "department",
        "owner_department": "finance_operations",
        "allowed_roles": ["finance_staff", "team_lead"],
        "team_lead_departments": ["finance_operations"],
    },
    "OPS-004": {
        "classification": "general",
        "owner_department": "finance_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "OPS-005": {
        "classification": "general",
        "owner_department": "finance_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
    "OPS-006": {
        "classification": "general",
        "owner_department": "finance_operations",
        "allowed_roles": GENERAL_ROLES,
        "team_lead_departments": [],
    },
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
    "ENG001_F01": {"source_doc_id": "ENG-001", "exact_value": "10", "unit": "minutes", "topic": "p1_incident_acknowledgment", "applicable_role": "engineer"},
    "ENG001_F02": {"source_doc_id": "ENG-001", "exact_value": "30", "unit": "minutes", "topic": "p2_incident_acknowledgment", "applicable_role": "engineer"},
    "ENG001_F03": {"source_doc_id": "ENG-001", "exact_value": "2", "unit": "business_days", "topic": "p1_incident_postmortem_deadline", "applicable_role": "engineer"},
    "ENG002_F01": {"source_doc_id": "ENG-002", "exact_value": "Friday", "unit": "", "topic": "oncall_handover_day", "applicable_role": "engineer"},
    "ENG002_F02": {"source_doc_id": "ENG-002", "exact_value": "18:00", "unit": "IST", "topic": "oncall_handover_time", "applicable_role": "engineer"},
    "ENG002_F03": {"source_doc_id": "ENG-002", "exact_value": "open_incidents_owner_next_action", "unit": "", "topic": "required_handover_details", "applicable_role": "engineer"},
    "ENG003_F01": {"source_doc_id": "ENG-003", "exact_value": "Tuesday_and_Thursday", "unit": "", "topic": "normal_deployment_days", "applicable_role": "engineer"},
    "ENG003_F02": {"source_doc_id": "ENG-003", "exact_value": "14:00-17:00", "unit": "IST", "topic": "deployment_window", "applicable_role": "engineer"},
    "ENG003_F03": {"source_doc_id": "ENG-003", "exact_value": "error_rate_gt_5_percent_for_10_minutes", "unit": "", "topic": "rollback_trigger", "applicable_role": "engineer"},
    "ENG004_F01": {"source_doc_id": "ENG-004", "exact_value": "team_lead_and_service_owner", "unit": "", "topic": "high_risk_change_approvers", "applicable_role": "team_lead"},
    "ENG004_F02": {"source_doc_id": "ENG-004", "exact_value": "24", "unit": "hours", "topic": "planned_migration_change_freeze_period", "applicable_role": "engineer"},
    "ENG004_F03": {"source_doc_id": "ENG-004", "exact_value": "1", "unit": "business_days", "topic": "emergency_change_retrospective_approval_deadline", "applicable_role": "team_lead"},
    "ENG005_F01": {"source_doc_id": "ENG-005", "exact_value": "expired_authentication_token_sign_in_again", "unit": "", "topic": "error_code_e1001", "applicable_role": "engineer"},
    "ENG005_F02": {"source_doc_id": "ENG-005", "exact_value": "60", "unit": "seconds", "topic": "error_code_e2003_retry_delay", "applicable_role": "engineer"},
    "ENG005_F03": {"source_doc_id": "ENG-005", "exact_value": "billing_sync_pending_check_reconciliation_status", "unit": "", "topic": "error_code_e3002", "applicable_role": "engineer"},
    "ENG006_F01": {"source_doc_id": "ENG-006", "exact_value": "platform_team", "unit": "", "topic": "svc_portal_owner", "applicable_role": "team_lead"},
    "ENG006_F02": {"source_doc_id": "ENG-006", "exact_value": "identity_team", "unit": "", "topic": "svc_auth_owner", "applicable_role": "team_lead"},
    "ENG006_F03": {"source_doc_id": "ENG-006", "exact_value": "payments_team", "unit": "", "topic": "svc_billing_owner", "applicable_role": "team_lead"},
    "ITS001_F01": {"source_doc_id": "ITS-001", "exact_value": "3", "unit": "business_days", "topic": "standard_laptop_provisioning_target", "applicable_role": "it_support"},
    "ITS001_F02": {"source_doc_id": "ITS-001", "exact_value": "1", "unit": "business_days", "topic": "urgent_security_replacement_target", "applicable_role": "it_support"},
    "ITS001_F03": {"source_doc_id": "ITS-001", "exact_value": "OPS-005_and_OPS-002", "unit": "", "topic": "laptop_purchase_policy_references", "applicable_role": "it_support"},
    "ITS002_F01": {"source_doc_id": "ITS-002", "exact_value": "2", "unit": "business_days", "topic": "new_account_request_lead_time", "applicable_role": "it_support"},
    "ITS002_F02": {"source_doc_id": "ITS-002", "exact_value": "4", "unit": "hours", "topic": "access_deactivation_after_exit", "applicable_role": "it_support"},
    "ITS002_F03": {"source_doc_id": "ITS-002", "exact_value": "hr_staff", "unit": "", "topic": "account_provisioning_request_approval", "applicable_role": "hr_staff"},
    "ITS003_F01": {"source_doc_id": "ITS-003", "exact_value": "identity_verification_and_service_ticket", "unit": "", "topic": "mfa_reset_requirements", "applicable_role": "it_support"},
    "ITS003_F02": {"source_doc_id": "ITS-003", "exact_value": "4", "unit": "business_hours", "topic": "mfa_reset_resolution_target", "applicable_role": "it_support"},
    "ITS003_F03": {"source_doc_id": "ITS-003", "exact_value": "prohibited", "unit": "", "topic": "sending_mfa_reset_codes_by_email", "applicable_role": "it_support"},
    "ITS004_F01": {"source_doc_id": "ITS-004", "exact_value": "team_lead", "unit": "", "topic": "software_request_approver", "applicable_role": "team_lead"},
    "ITS004_F02": {"source_doc_id": "ITS-004", "exact_value": "security_review_required", "unit": "", "topic": "unlisted_software_requirement", "applicable_role": "it_support"},
    "ITS004_F03": {"source_doc_id": "ITS-004", "exact_value": "3", "unit": "business_days", "topic": "standard_software_request_target", "applicable_role": "it_support"},
    "ITS005_F01": {"source_doc_id": "ITS-005", "exact_value": "1", "unit": "hours", "topic": "lost_device_reporting_deadline", "applicable_role": "all"},
    "ITS005_F02": {"source_doc_id": "ITS-005", "exact_value": "disable_device_access", "unit": "", "topic": "it_response_after_verification", "applicable_role": "it_support"},
    "ITS005_F03": {"source_doc_id": "ITS-005", "exact_value": "it_support_ticket", "unit": "", "topic": "required_incident_record", "applicable_role": "it_support"},
    "ITS006_F01": {"source_doc_id": "ITS-006", "exact_value": "15", "unit": "minutes", "topic": "p1_ticket_response_target", "applicable_role": "it_support"},
    "ITS006_F02": {"source_doc_id": "ITS-006", "exact_value": "2", "unit": "business_hours", "topic": "p2_ticket_response_target", "applicable_role": "it_support"},
    "ITS006_F03": {"source_doc_id": "ITS-006", "exact_value": "1", "unit": "business_days", "topic": "p3_ticket_response_target", "applicable_role": "it_support"},
    "HR001_F01": {"source_doc_id": "HR-001", "exact_value": "18", "unit": "days_per_year", "topic": "annual_leave_allowance", "applicable_role": "all"},
    "HR001_F02": {"source_doc_id": "HR-001", "exact_value": "10", "unit": "days_per_year", "topic": "sick_leave_allowance", "applicable_role": "all"},
    "HR001_F03": {"source_doc_id": "HR-001", "exact_value": "3", "unit": "business_days", "topic": "normal_leave_request_advance_period", "applicable_role": "all"},
    "HR002_F01": {"source_doc_id": "HR-002", "exact_value": "2", "unit": "days_per_week", "topic": "minimum_office_attendance", "applicable_role": "all"},
    "HR002_F02": {"source_doc_id": "HR-002", "exact_value": "team_lead", "unit": "", "topic": "remote_work_exception_approver", "applicable_role": "team_lead"},
    "HR002_F03": {"source_doc_id": "HR-002", "exact_value": "ITS-004_and_OPS-005", "unit": "", "topic": "remote_work_equipment_references", "applicable_role": "all"},
    "HR003_F01": {"source_doc_id": "HR-003", "exact_value": "5", "unit": "business_days_before_join", "topic": "onboarding_checklist_lead_time", "applicable_role": "hr_staff"},
    "HR003_F02": {"source_doc_id": "HR-003", "exact_value": "ITS-002", "unit": "", "topic": "account_provisioning_reference", "applicable_role": "hr_staff"},
    "HR003_F03": {"source_doc_id": "HR-003", "exact_value": "ITS-001", "unit": "", "topic": "laptop_provisioning_reference", "applicable_role": "hr_staff"},
    "HR004_F01": {"source_doc_id": "HR-004", "exact_value": "20000", "unit": "inr", "topic": "annual_training_reimbursement_limit", "applicable_role": "all"},
    "HR004_F02": {"source_doc_id": "HR-004", "exact_value": "team_lead", "unit": "", "topic": "training_approval_before_enrollment", "applicable_role": "team_lead"},
    "HR004_F03": {"source_doc_id": "HR-004", "exact_value": "30", "unit": "calendar_days", "topic": "claim_submission_deadline_after_completion", "applicable_role": "all"},
    "HR005_F01": {"source_doc_id": "HR-005", "exact_value": "April_and_October", "unit": "", "topic": "performance_review_months", "applicable_role": "hr_staff"},
    "HR005_F02": {"source_doc_id": "HR-005", "exact_value": "5", "unit": "business_days_before_review", "topic": "goal_submission_lead_time", "applicable_role": "all"},
    "HR005_F03": {"source_doc_id": "HR-005", "exact_value": "hr_staff_and_team_lead", "unit": "", "topic": "performance_review_document_access", "applicable_role": "hr_staff"},
    "HR006_F01": {"source_doc_id": "HR-006", "exact_value": "2", "unit": "business_days", "topic": "grievance_acknowledgment_target", "applicable_role": "hr_staff"},
    "HR006_F02": {"source_doc_id": "HR-006", "exact_value": "10", "unit": "business_days", "topic": "grievance_appeal_period", "applicable_role": "hr_staff"},
    "HR006_F03": {"source_doc_id": "HR-006", "exact_value": "hr_staff_only", "unit": "", "topic": "private_grievance_case_access", "applicable_role": "hr_staff"},
    "OPS001_F01": {"source_doc_id": "OPS-001", "exact_value": "1500", "unit": "inr_per_day", "topic": "domestic_travel_daily_allowance", "applicable_role": "all"},
    "OPS001_F02": {"source_doc_id": "OPS-001", "exact_value": "required_before_booking", "unit": "", "topic": "travel_booking_approval", "applicable_role": "team_lead"},
    "OPS001_F03": {"source_doc_id": "OPS-001", "exact_value": "OPS-004", "unit": "", "topic": "expense_claim_reference", "applicable_role": "all"},
    "OPS002_F01": {"source_doc_id": "OPS-002", "exact_value": "25000", "unit": "inr", "topic": "max_purchase_team_lead_alone", "applicable_role": "team_lead"},
    "OPS002_F02": {"source_doc_id": "OPS-002", "exact_value": "above_25000_through_100000", "unit": "", "topic": "finance_only_approval_range", "applicable_role": "finance_staff"},
    "OPS002_F03": {"source_doc_id": "OPS-002", "exact_value": "finance_staff_and_team_lead_approval", "unit": "", "topic": "purchases_above_100000_approval", "applicable_role": "finance_staff"},
    "OPS003_F01": {"source_doc_id": "OPS-003", "exact_value": "5", "unit": "business_days", "topic": "standard_vendor_onboarding_target", "applicable_role": "finance_staff"},
    "OPS003_F02": {"source_doc_id": "OPS-003", "exact_value": "tax_registration_and_verified_bank_details", "unit": "", "topic": "required_vendor_documents", "applicable_role": "finance_staff"},
    "OPS003_F03": {"source_doc_id": "OPS-003", "exact_value": "finance_staff", "unit": "", "topic": "approval_before_first_purchase", "applicable_role": "finance_staff"},
    "OPS004_F01": {"source_doc_id": "OPS-004", "exact_value": "30", "unit": "calendar_days", "topic": "expense_claim_submission_deadline", "applicable_role": "all"},
    "OPS004_F02": {"source_doc_id": "OPS-004", "exact_value": "500", "unit": "inr", "topic": "receipt_required_threshold", "applicable_role": "all"},
    "OPS004_F03": {"source_doc_id": "OPS-004", "exact_value": "5", "unit": "business_days", "topic": "finance_claim_review_target", "applicable_role": "finance_staff"},
    "OPS005_F01": {"source_doc_id": "OPS-005", "exact_value": "it_support", "unit": "", "topic": "company_asset_register_owner", "applicable_role": "it_support"},
    "OPS005_F02": {"source_doc_id": "OPS-005", "exact_value": "5", "unit": "business_days", "topic": "assigned_equipment_return_after_exit", "applicable_role": "employee"},
    "OPS005_F03": {"source_doc_id": "OPS-005", "exact_value": "OPS-002", "unit": "", "topic": "new_equipment_purchase_reference", "applicable_role": "all"},
    "OPS006_F01": {"source_doc_id": "OPS-006", "exact_value": "6", "unit": "months", "topic": "business_continuity_test_frequency", "applicable_role": "team_lead"},
    "OPS006_F02": {"source_doc_id": "OPS-006", "exact_value": "4", "unit": "hours", "topic": "critical_service_recovery_target", "applicable_role": "it_support"},
    "OPS006_F03": {"source_doc_id": "OPS-006", "exact_value": "duty_team_lead", "unit": "", "topic": "continuity_escalation_contact", "applicable_role": "team_lead"},
}

EXPECTED_PLANNED_REVISIONS = {
    "ENG-003": {
        "base_version": "v1",
        "target_version": "v2",
        "changes": [
            {
                "fact_id": "ENG003_F03",
                "old_value": "error_rate_gt_5_percent_for_10_minutes",
                "new_value": "error_rate_gt_4_percent_for_10_minutes",
                "unit": "",
            }
        ],
    },
    "HR-001": {
        "base_version": "v1",
        "target_version": "v2",
        "changes": [
            {
                "fact_id": "HR001_F01",
                "old_value": "18",
                "new_value": "20",
                "unit": "days_per_year",
            }
        ],
    },
    "OPS-002": {
        "base_version": "v1",
        "target_version": "v2",
        "changes": [
            {
                "fact_id": "OPS002_F01",
                "old_value": "25000",
                "new_value": "30000",
                "unit": "inr",
            },
            {
                "fact_id": "OPS002_F02",
                "old_value": "above_25000_through_100000",
                "new_value": "above_30000_through_100000",
                "unit": "",
            },
        ],
    },
}

EXPECTED_RELATIONSHIPS = {
    ("ITS-001", "OPS-005"),
    ("OPS-005", "OPS-002"),
    ("ENG-001", "ENG-002"),
    ("ENG-002", "ENG-006"),
    ("HR-003", "ITS-002"),
    ("ITS-002", "ITS-001"),
    ("HR-002", "ITS-004"),
    ("ITS-004", "OPS-005"),
    ("OPS-001", "OPS-004"),
    ("OPS-004", "OPS-002"),
    ("ENG-003", "ENG-004"),
    ("HR-004", "OPS-004"),
}


def read_and_validate_csv(
    file_path: Path,
    expected_headers: list[str],
    required_fields: list[str],
    errors: list[str],
) -> list[tuple[int, dict]] | None:
    """Read a CSV file, validate headers, detect extra fields and missing required values."""
    filename = file_path.name
    rows: list[tuple[int, dict]] = []
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            if not reader.fieldnames:
                errors.append(f"{filename} is empty or missing headers")
                return None
            missing_cols = [c for c in expected_headers if c not in reader.fieldnames]
            if missing_cols:
                errors.append(f"{filename} missing required columns: {missing_cols}")
                return None
            if reader.fieldnames != expected_headers:
                errors.append(f"{filename} headers mismatch: {reader.fieldnames}")

            for row in reader:
                row_num = reader.line_num
                # 1. Detect unexpected extra fields in row
                if None in row:
                    errors.append(
                        f"{filename} row {row_num}: contains unexpected extra field(s): {row[None]}"
                    )

                # 2. Detect missing fields (row has fewer columns than header)
                missing_in_row = [c for c in expected_headers if row.get(c) is None]
                if missing_in_row:
                    errors.append(
                        f"{filename} row {row_num}: missing field(s): {missing_in_row}"
                    )

                # 3. Detect missing required field values (excluding allowed empty fields)
                empty_required = [
                    c for c in required_fields if not str(row.get(c) or "").strip()
                ]
                if empty_required:
                    errors.append(
                        f"{filename} row {row_num}: missing required value for field(s): {empty_required}"
                    )

                rows.append((row_num, row))

        return rows
    except Exception as e:
        errors.append(f"Failed to read {filename}: {e}")
        return None


def validate_permission_list(
    items: any, doc_id: str, field_name: str, errors: list[str]
) -> bool:
    """Confirm value is a list of strings without invalid types. Return True if valid."""
    if not isinstance(items, list):
        errors.append(f"Document {doc_id} policy {field_name} must be a list")
        return False
    valid = True
    for idx, item in enumerate(items):
        if not isinstance(item, str):
            item_type = type(item).__name__ if item is not None else "null"
            errors.append(
                f"Document {doc_id} policy {field_name} contains non-string item at index {idx} ({item_type})"
            )
            valid = False
    return valid


def check_document_access(
    doc_permissions: dict,
    user_roles: list[str],
    classification: str,
    user_department: str | None = None,
) -> bool:
    """Evaluate whether a user with given roles and optional department has read access."""
    if not doc_permissions or not isinstance(doc_permissions, dict):
        return False
    if not user_roles or not isinstance(user_roles, (list, tuple, set)):
        return False
    if classification not in ("general", "department", "restricted"):
        return False

    raw_allowed = doc_permissions.get("allowed_roles")
    if not isinstance(raw_allowed, list):
        return False
    if not all(isinstance(r, str) for r in raw_allowed):
        return False

    raw_tl_depts = doc_permissions.get("team_lead_departments")
    if not isinstance(raw_tl_depts, list):
        return False
    if not all(isinstance(d, str) for d in raw_tl_depts):
        return False

    if not all(isinstance(r, str) for r in user_roles):
        return False
    if user_department is not None and not isinstance(user_department, str):
        return False

    allowed_roles = set(raw_allowed)
    tl_depts = set(raw_tl_depts)

    for role in user_roles:
        if role == "document_admin":
            continue
        if role not in allowed_roles:
            continue
        if role == "team_lead":
            if classification == "general":
                return True
            if not tl_depts:
                continue
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

    # 2. Parse YAML files with robust top-level structure validation
    company_data = None
    try:
        with open(spec_dir / "company_spec.yaml", "r", encoding="utf-8") as f:
            company_data = yaml.safe_load(f)
        if company_data is None or not isinstance(company_data, dict):
            errors.append("company_spec.yaml is empty or has invalid top-level structure")
    except Exception as e:
        errors.append(f"company_spec.yaml failed to parse: {e}")

    policy_data = None
    try:
        with open(spec_dir / "access_policy.yaml", "r", encoding="utf-8") as f:
            policy_data = yaml.safe_load(f)
        if policy_data is None or not isinstance(policy_data, dict):
            errors.append("access_policy.yaml is empty or has invalid top-level structure")
    except Exception as e:
        errors.append(f"access_policy.yaml failed to parse: {e}")

    outlines_data = None
    try:
        with open(spec_dir / "document_outlines.yaml", "r", encoding="utf-8") as f:
            outlines_data = yaml.safe_load(f)
        if outlines_data is None or not isinstance(outlines_data, list):
            errors.append("document_outlines.yaml is empty or has invalid top-level structure")
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
    inventory_data = read_and_validate_csv(
        spec_dir / "document_inventory.csv",
        expected_headers=[
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
        ],
        required_fields=[
            "document_id",
            "title",
            "owner_department",
            "classification",
            "allowed_roles",
            "planned_versions",
            "active_version",
            "source_type",
        ],
        errors=errors,
    )
    if inventory_data is None:
        return errors

    inventory_rows = []
    inventory_doc_ids = set()
    dept_counts: dict[str, int] = {}

    for row_num, row in inventory_data:
        inventory_rows.append(row)
        doc_id = row.get("document_id", "").strip()
        if doc_id in inventory_doc_ids:
            errors.append(f"document_inventory.csv row {row_num}: duplicate document_id '{doc_id}'")
        inventory_doc_ids.add(doc_id)
        owner = row.get("owner_department", "").strip()
        dept_counts[owner] = dept_counts.get(owner, 0) + 1

    if len(inventory_rows) != 24:
        errors.append(f"Expected 24 documents in inventory, found {len(inventory_rows)}")

    for dept in EXPECTED_DEPARTMENTS:
        if dept_counts.get(dept, 0) != 6:
            errors.append(f"Department {dept} has {dept_counts.get(dept, 0)} documents, expected 6")

    policy_docs = policy_data.get("documents") if isinstance(policy_data, dict) else {}
    if not isinstance(policy_docs, dict):
        errors.append("access_policy.yaml missing documents mapping")
        policy_docs = {}

    for row in inventory_rows:
        doc_id = row.get("document_id", "").strip()
        title = row.get("title", "").strip()
        if doc_id not in APPROVED_DOCUMENT_SPECS:
            errors.append(f"Unknown or unapproved document_id in inventory: {doc_id}")
            continue

        app_spec = APPROVED_DOCUMENT_SPECS[doc_id]

        if doc_id in EXPECTED_TITLES and EXPECTED_TITLES[doc_id] != title:
            errors.append(f"Document {doc_id} has title '{title}', expected '{EXPECTED_TITLES[doc_id]}'")
        if row.get("owner_department") != app_spec["owner_department"]:
            errors.append(f"Document {doc_id} owner_department '{row.get('owner_department')}' != approved '{app_spec['owner_department']}'")
        if row.get("classification") != app_spec["classification"]:
            errors.append(f"Document {doc_id} classification '{row.get('classification')}' != approved '{app_spec['classification']}'")
        if row.get("active_version") != "v1":
            errors.append(f"Document {doc_id} active_version must be v1, got: {row.get('active_version')}")

        planned_vers = row.get("planned_versions", "").split("|")
        if "v1" not in planned_vers:
            errors.append(f"Document {doc_id} planned_versions does not contain active version v1")
        if doc_id in ["ENG-003", "HR-001", "OPS-002"]:
            if row.get("planned_versions") != "v1|v2":
                errors.append(f"Document {doc_id} expected planned_versions 'v1|v2', got '{row.get('planned_versions')}'")
        else:
            if row.get("planned_versions") != "v1":
                errors.append(f"Document {doc_id} expected planned_versions 'v1', got '{row.get('planned_versions')}'")
        if row.get("source_type") != "synthetic":
            errors.append(f"Document {doc_id} source_type must be synthetic, got: {row.get('source_type')}")

        # Allowed roles in inventory
        allowed_roles_str = row.get("allowed_roles", "").strip()
        inv_roles = allowed_roles_str.split("|") if allowed_roles_str else []
        if len(inv_roles) != len(set(inv_roles)):
            errors.append(f"Document {doc_id} inventory has duplicate allowed roles: {inv_roles}")
        for r in inv_roles:
            if r not in VALID_ROLES:
                errors.append(f"Document {doc_id} inventory has invalid role: {r}")
        if "document_admin" in inv_roles:
            errors.append(f"Document {doc_id} inventory must not grant reading access to document_admin")

        if inv_roles != app_spec["allowed_roles"]:
            errors.append(f"Document {doc_id} inventory allowed_roles {inv_roles} != approved {app_spec['allowed_roles']}")

        # Team lead departments in inventory
        inv_tl_depts_str = row.get("team_lead_departments", "").strip()
        inv_tl_depts = [inv_tl_depts_str] if inv_tl_depts_str else []
        if inv_tl_depts != app_spec["team_lead_departments"]:
            errors.append(f"Document {doc_id} inventory team_lead_departments {inv_tl_depts} != approved {app_spec['team_lead_departments']}")

        # Compare with access_policy.yaml
        if doc_id not in policy_docs:
            errors.append(f"Document {doc_id} missing in access_policy.yaml")
        else:
            p_entry = policy_docs[doc_id]
            if not isinstance(p_entry, dict):
                errors.append(f"Document {doc_id} in access_policy.yaml must be a dictionary")
                continue

            p_allowed = p_entry.get("allowed_roles")
            if not validate_permission_list(p_allowed, doc_id, "allowed_roles", errors):
                pass
            else:
                if len(p_allowed) != len(set(p_allowed)):
                    errors.append(f"Document {doc_id} policy has duplicate allowed roles: {p_allowed}")
                for r in p_allowed:
                    if r not in VALID_ROLES:
                        errors.append(f"Document {doc_id} policy has invalid role: {r}")
                if "document_admin" in p_allowed:
                    errors.append(f"Document {doc_id} policy must not grant reading access to document_admin")
                if p_allowed != app_spec["allowed_roles"]:
                    errors.append(f"Document {doc_id} policy allowed_roles {p_allowed} != approved {app_spec['allowed_roles']}")
                if p_allowed != inv_roles:
                    errors.append(f"Document {doc_id} allowed_roles in policy {p_allowed} != inventory {inv_roles}")

            p_tl_depts = p_entry.get("team_lead_departments")
            if not validate_permission_list(p_tl_depts, doc_id, "team_lead_departments", errors):
                pass
            else:
                if len(p_tl_depts) != len(set(p_tl_depts)):
                    errors.append(f"Document {doc_id} policy has duplicate team_lead_departments: {p_tl_depts}")
                for d in p_tl_depts:
                    if d not in EXPECTED_DEPARTMENTS:
                        errors.append(f"Document {doc_id} policy has invalid team_lead_department: {d}")
                if p_tl_depts != app_spec["team_lead_departments"]:
                    errors.append(f"Document {doc_id} policy team_lead_departments {p_tl_depts} != approved {app_spec['team_lead_departments']}")
                if p_tl_depts != inv_tl_depts:
                    errors.append(f"Document {doc_id} team_lead_departments in policy {p_tl_depts} != inventory {inv_tl_depts}")

    for p_doc_id in policy_docs:
        if p_doc_id not in APPROVED_DOCUMENT_SPECS:
            errors.append(f"Unknown document_id in access_policy.yaml: {p_doc_id}")

    # 5. Access policy checks & department-scoped security evaluation
    if policy_data.get("default_access") != "deny":
        errors.append("access_policy.yaml default_access must be deny")

    # Security tests on policy data
    if not check_document_access(policy_docs.get("ENG-006", {}), ["team_lead"], "restricted", "engineering"):
        errors.append("Security check failed: Engineering team lead should access ENG-006")
    if check_document_access(policy_docs.get("ENG-006", {}), ["team_lead"], "restricted", "finance_operations"):
        errors.append("Security check failed: Finance team lead should NOT access ENG-006")
    if check_document_access(policy_docs.get("HR-005", {}), ["team_lead"], "restricted", "engineering"):
        errors.append("Security check failed: Engineering team lead should NOT access HR-005")
    if check_document_access(policy_docs.get("OPS-002", {}), ["team_lead"], "department", "engineering"):
        errors.append("Security check failed: Engineering team lead should NOT access OPS-002")
    if not check_document_access(policy_docs.get("ITS-001", {}), ["team_lead"], "general", "engineering"):
        errors.append("Security check failed: Team lead should access general document ITS-001")
    if check_document_access(policy_docs.get("ENG-006", {}), ["document_admin"], "restricted"):
        errors.append("Security check failed: document_admin alone should NOT read ENG-006")

    # 6. Cross references checks
    cr_data = read_and_validate_csv(
        spec_dir / "cross_references.csv",
        expected_headers=["from_doc", "to_doc", "relationship", "explanation"],
        required_fields=["from_doc", "to_doc", "relationship", "explanation"],
        errors=errors,
    )
    if cr_data is None:
        return errors

    rel_rows = []
    seen_pairs = set()
    doc_relationships: dict[str, set[str]] = {doc_id: set() for doc_id in inventory_doc_ids}

    for row_num, row in cr_data:
        rel_rows.append(row)
        from_doc = row.get("from_doc", "").strip()
        to_doc = row.get("to_doc", "").strip()

        if from_doc not in inventory_doc_ids:
            errors.append(f"cross_references from_doc not in inventory: {from_doc}")
        if to_doc not in inventory_doc_ids:
            errors.append(f"cross_references to_doc not in inventory: {to_doc}")

        if from_doc == to_doc:
            errors.append(f"Self-referencing relationship in cross_references.csv: {from_doc}")

        pair = (from_doc, to_doc)
        if pair in seen_pairs:
            errors.append(f"Duplicate relationship: {from_doc} -> {to_doc}")
        seen_pairs.add(pair)

        if pair not in EXPECTED_RELATIONSHIPS:
            errors.append(f"Unapproved relationship pair: {from_doc} -> {to_doc}")

        if from_doc in doc_relationships and to_doc in inventory_doc_ids:
            doc_relationships[from_doc].add(to_doc)
        if to_doc in doc_relationships and from_doc in inventory_doc_ids:
            doc_relationships[to_doc].add(from_doc)

    if len(rel_rows) != 12:
        errors.append(f"Expected 12 relationships in cross_references.csv, found {len(rel_rows)}")

    missing_pairs = EXPECTED_RELATIONSHIPS - seen_pairs
    if missing_pairs:
        for mp in sorted(missing_pairs):
            errors.append(f"Missing required relationship pair: {mp[0]} -> {mp[1]}")

    # Check symmetric related_documents in inventory
    for row in inventory_rows:
        doc_id = row.get("document_id", "").strip()
        rel_field = row.get("related_documents", "").strip()
        inv_related = set(rel_field.split("|")) if rel_field else set()
        expected_related = doc_relationships.get(doc_id, set())
        if inv_related != expected_related:
            errors.append(
                f"Document {doc_id} related_documents mismatch: inventory={inv_related}, expected={expected_related}"
            )

    # 7. Fact registry checks
    facts_data = read_and_validate_csv(
        spec_dir / "fact_registry.csv",
        expected_headers=[
            "fact_id",
            "document_version",
            "source_doc_id",
            "topic",
            "exact_value",
            "unit",
            "applicable_role",
            "effective_from",
            "effective_until",
        ],
        required_fields=[
            "fact_id",
            "document_version",
            "source_doc_id",
            "topic",
            "exact_value",
            "applicable_role",
            "effective_from",
        ],
        errors=errors,
    )
    if facts_data is None:
        return errors

    fact_rows = []
    seen_facts = set()
    doc_fact_count: dict[str, int] = {}

    for row_num, row in facts_data:
        fact_rows.append(row)
        fact_id = row.get("fact_id", "").strip()
        doc_version = row.get("document_version", "").strip()
        source_doc = row.get("source_doc_id", "").strip()
        topic = row.get("topic", "").strip()
        exact_value = row.get("exact_value", "").strip()
        unit = row.get("unit", "").strip()
        app_role = row.get("applicable_role", "").strip()
        eff_from = row.get("effective_from", "").strip()
        eff_until = row.get("effective_until", "").strip()

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
            if exact_value != exp["exact_value"]:
                errors.append(
                    f"Fact {fact_id} exact_value mismatch: '{exact_value}' != '{exp['exact_value']}'"
                )
            if unit != exp["unit"]:
                errors.append(
                    f"Fact {fact_id} unit mismatch: '{unit}' != '{exp['unit']}'"
                )
            if topic != exp["topic"]:
                errors.append(
                    f"Fact {fact_id} topic mismatch: '{topic}' != '{exp['topic']}'"
                )
            if app_role != exp["applicable_role"]:
                errors.append(
                    f"Fact {fact_id} applicable_role mismatch: '{app_role}' != '{exp['applicable_role']}'"
                )

        if not topic:
            errors.append(f"Fact {fact_id} topic must not be empty")

        if not app_role:
            errors.append(f"Fact {fact_id} applicable_role must not be empty")
        elif app_role != "all" and app_role not in VALID_ROLES:
            errors.append(f"Fact {fact_id} invalid applicable_role: {app_role}")

        if not eff_from:
            errors.append(f"Fact {fact_id} missing effective_from date")
        elif eff_from != "2026-11-01":
            errors.append(f"Fact {fact_id} effective_from must be '2026-11-01', got '{eff_from}'")
        else:
            try:
                datetime.strptime(eff_from, "%Y-%m-%d")
            except ValueError:
                errors.append(f"Fact {fact_id} invalid effective_from format: '{eff_from}'")

        if eff_until:
            errors.append(f"Fact {fact_id} effective_until must be empty in v1, got '{eff_until}'")

        doc_fact_count[source_doc] = doc_fact_count.get(source_doc, 0) + 1

    if len(fact_rows) != 72:
        errors.append(f"Expected 72 facts in registry, found {len(fact_rows)}")

    for doc_id in inventory_doc_ids:
        if doc_fact_count.get(doc_id, 0) != 3:
            errors.append(f"Document {doc_id} has {doc_fact_count.get(doc_id, 0)} facts, expected 3")

    for exp_id in EXPECTED_FACTS:
        if (exp_id, "v1") not in seen_facts:
            errors.append(f"Missing required v1 fact: {exp_id}")

    # 8. Planned revisions checks
    planned_revs = company_data.get("planned_revisions") if isinstance(company_data, dict) else None
    if not isinstance(planned_revs, list):
        errors.append("company_spec.yaml planned_revisions must be a list")
    else:
        if len(planned_revs) != 3:
            errors.append(f"Expected 3 planned revisions, found {len(planned_revs)}")

        seen_rev_docs = set()
        for rev in planned_revs:
            if not isinstance(rev, dict):
                errors.append("Planned revision entry must be a dictionary")
                continue
            doc_id = rev.get("document_id")
            if not doc_id:
                errors.append("Planned revision missing document_id")
                continue
            if doc_id in seen_rev_docs:
                errors.append(f"Duplicate planned revision for document: {doc_id}")
            seen_rev_docs.add(doc_id)

            if doc_id not in EXPECTED_PLANNED_REVISIONS:
                errors.append(f"Unapproved document in planned_revisions: {doc_id}")
                continue

            exp_rev = EXPECTED_PLANNED_REVISIONS[doc_id]
            if rev.get("base_version") != exp_rev["base_version"]:
                errors.append(f"Revision for {doc_id} base_version must be '{exp_rev['base_version']}', got: {rev.get('base_version')}")
            if rev.get("target_version") != exp_rev["target_version"]:
                errors.append(f"Revision for {doc_id} target_version must be '{exp_rev['target_version']}', got: {rev.get('target_version')}")

            changes = rev.get("changes")
            if not isinstance(changes, list):
                errors.append(f"Revision for {doc_id} changes must be a list")
                continue

            exp_changes = exp_rev["changes"]
            if len(changes) != len(exp_changes):
                errors.append(f"Revision for {doc_id} expected {len(exp_changes)} change(s), found {len(changes)}")

            seen_change_facts = set()
            for idx, change in enumerate(changes):
                if not isinstance(change, dict):
                    errors.append(f"Revision for {doc_id} change {idx} must be a dictionary")
                    continue
                f_id = change.get("fact_id")
                if not f_id:
                    errors.append(f"Revision for {doc_id} change {idx} missing fact_id")
                    continue
                if f_id in seen_change_facts:
                    errors.append(f"Revision for {doc_id} has duplicate change for fact: {f_id}")
                seen_change_facts.add(f_id)

                matching_exp = next((c for c in exp_changes if c["fact_id"] == f_id), None)
                if not matching_exp:
                    errors.append(f"Revision for {doc_id} contains unexpected changed fact: {f_id}")
                else:
                    old_val = str(change.get("old_value", ""))
                    new_val = str(change.get("new_value", ""))
                    unit_val = str(change.get("unit") or "")

                    if old_val != matching_exp["old_value"]:
                        errors.append(f"Revision for {doc_id} fact {f_id} old_value mismatch: '{old_val}' != '{matching_exp['old_value']}'")
                    if new_val != matching_exp["new_value"]:
                        errors.append(f"Revision for {doc_id} fact {f_id} new_value mismatch: '{new_val}' != '{matching_exp['new_value']}'")
                    if unit_val != matching_exp["unit"]:
                        errors.append(f"Revision for {doc_id} fact {f_id} unit mismatch: '{unit_val}' != '{matching_exp['unit']}'")

                    if f_id in EXPECTED_FACTS and old_val != EXPECTED_FACTS[f_id]["exact_value"]:
                        errors.append(f"Revision for {doc_id} fact {f_id} old_value does not match v1 fact exact_value")
                    if f_id in EXPECTED_FACTS and EXPECTED_FACTS[f_id]["source_doc_id"] != doc_id:
                        errors.append(f"Revision for {doc_id} references fact {f_id} belonging to {EXPECTED_FACTS[f_id]['source_doc_id']}")

            for exp_c in exp_changes:
                if exp_c["fact_id"] not in seen_change_facts:
                    errors.append(f"Revision for {doc_id} missing required change for fact: {exp_c['fact_id']}")

        if seen_rev_docs != set(EXPECTED_PLANNED_REVISIONS.keys()):
            errors.append(f"Planned revisions document set mismatch: {seen_rev_docs} != {set(EXPECTED_PLANNED_REVISIONS.keys())}")

    # 9. Content outline checks
    if not isinstance(outlines_data, list):
        errors.append("document_outlines.yaml root must be a list")
    else:
        if len(outlines_data) != 24:
            errors.append(f"Expected 24 outlines, found {len(outlines_data)}")

        seen_outline_docs = set()
        for outline in outlines_data:
            if not isinstance(outline, dict):
                errors.append("Document outline entry must be a dictionary")
                continue
            doc_id = outline.get("document_id")
            if not doc_id:
                errors.append("Document outline missing document_id")
                continue
            if doc_id in seen_outline_docs:
                errors.append(f"Duplicate outline for document: {doc_id}")
            seen_outline_docs.add(doc_id)

            if doc_id not in inventory_doc_ids:
                errors.append(f"Outline references unknown document: {doc_id}")

            if outline.get("document_version") != "v1":
                errors.append(f"Outline for {doc_id} document_version must be v1, got {outline.get('document_version')}")

            sections = outline.get("sections")
            if not isinstance(sections, list):
                errors.append(f"Outline for {doc_id} sections must be a list")
                continue

            if len(sections) != 6:
                errors.append(f"Outline for {doc_id} must have 6 sections, found {len(sections)}")
                continue

            expected_sec_ids = ["S01", "S02", "S03", "S04", "S05", "S06"]
            actual_sec_ids = [s.get("section_id") if isinstance(s, dict) else None for s in sections]
            if actual_sec_ids != expected_sec_ids:
                errors.append(f"Outline for {doc_id} sections order mismatch: {actual_sec_ids} != {expected_sec_ids}")

            if doc_id in EXPECTED_OUTLINE_TITLES:
                exp_t2, exp_t3, exp_t4 = EXPECTED_OUTLINE_TITLES[doc_id]
                s0_title = sections[0].get("title") if isinstance(sections[0], dict) else None
                s1_title = sections[1].get("title") if isinstance(sections[1], dict) else None
                s2_title = sections[2].get("title") if isinstance(sections[2], dict) else None
                s3_title = sections[3].get("title") if isinstance(sections[3], dict) else None
                s4_title = sections[4].get("title") if isinstance(sections[4], dict) else None
                s5_title = sections[5].get("title") if isinstance(sections[5], dict) else None

                if s0_title != "Purpose and Scope":
                    errors.append(f"Outline {doc_id} S01 title mismatch: '{s0_title}'")
                if s1_title != exp_t2:
                    errors.append(f"Outline {doc_id} S02 title mismatch: '{s1_title}' != '{exp_t2}'")
                if s2_title != exp_t3:
                    errors.append(f"Outline {doc_id} S03 title mismatch: '{s2_title}' != '{exp_t3}'")
                if s3_title != exp_t4:
                    errors.append(f"Outline {doc_id} S04 title mismatch: '{s3_title}' != '{exp_t4}'")
                if s4_title != "Exceptions and Related Documents":
                    errors.append(f"Outline {doc_id} S05 title mismatch: '{s4_title}'")
                if s5_title != "Revision History":
                    errors.append(f"Outline {doc_id} S06 title mismatch: '{s5_title}'")

            prefix = doc_id.replace("-", "")
            exp_f01 = f"{prefix}_F01"
            exp_f02 = f"{prefix}_F02"
            exp_f03 = f"{prefix}_F03"

            s0_facts = sections[0].get("fact_ids") if isinstance(sections[0], dict) else None
            s1_facts = sections[1].get("fact_ids") if isinstance(sections[1], dict) else None
            s2_facts = sections[2].get("fact_ids") if isinstance(sections[2], dict) else None
            s3_facts = sections[3].get("fact_ids") if isinstance(sections[3], dict) else None
            s4_facts = sections[4].get("fact_ids") if isinstance(sections[4], dict) else None
            s5_facts = sections[5].get("fact_ids") if isinstance(sections[5], dict) else None

            if s0_facts != []:
                errors.append(f"Outline {doc_id} S01 fact_ids must be empty")
            if s1_facts != [exp_f01]:
                errors.append(f"Outline {doc_id} S02 fact_ids mismatch: {s1_facts} != [{exp_f01}]")
            if s2_facts != [exp_f02]:
                errors.append(f"Outline {doc_id} S03 fact_ids mismatch: {s2_facts} != [{exp_f02}]")
            if s3_facts != [exp_f03]:
                errors.append(f"Outline {doc_id} S04 fact_ids mismatch: {s3_facts} != [{exp_f03}]")
            if s4_facts != []:
                errors.append(f"Outline {doc_id} S05 fact_ids must be empty")
            if s5_facts != []:
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
