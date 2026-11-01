"""12 milestone fresh-install defaults, including PPS Ready/QC review.

The approved original 27 steps now include two additional PPS review steps (29).

Seed only if no Design Milestone Type records exist. Existing master changes
are never overwritten by later migrate calls.
"""
STAGES = [
    # name, trigger milestone, trigger step, ordered steps:
    # (step, mode, actor_role, custody_role, lead_days, evidence_type)
    ("Fabric / Material Sourcing", None, None, [
        ("In Progress", "Auto", None, "Merchandiser", 0, None),
        ("Completed", "Manual", "Merchandiser", "Merchandiser", 7, None),
    ]),
    ("Sample 1 Production", None, None, [
        ("In Progress", "Auto", None, "Merchandiser", 0, None),
        ("Completed", "Manual", "Merchandiser", "Merchandiser", 20, None),
    ]),
    ("Sample Shipping China to KSA", "Sample 1 Production", "Completed", [
        ("Ready to Start", "Auto", None, "Shipping Coordinator", 0, None),
        ("Completed", "Manual", "Shipping Coordinator", "Shipping Coordinator", 5, "Shipping Document"),
    ]),
    ("Sample 1 Fitting", "Sample Shipping China to KSA", "Completed", [
        ("Ready to Start", "Auto", None, "Technical Fitting Officer", 0, None),
        ("Completed", "Manual", "Technical Fitting Officer", "Technical Fitting Officer", 3, "Fitting Report"),
    ]),
    ("Sample Shipping KSA to China", "Sample 1 Fitting", "Completed", [
        ("In Progress", "Auto", None, "Technical Fitting Officer", 0, None),
        ("Completed", "Manual", "Shipping Coordinator", "Shipping Coordinator", 5, "Shipping Document"),
    ]),
    ("Sample 2 Production", "Sample Shipping KSA to China", "Completed", [
        ("In Progress", "Auto", None, "Merchandiser", 0, None),
        ("Completed", "Manual", "Merchandiser", "Merchandiser", 15, None),
    ]),
    ("Sample 2 Fitting", "Sample 2 Production", "Completed", [
        ("Ready to Start", "Auto", None, "Merchandiser", 0, None),
        ("In Progress", "Manual", "QC Officer", "QC Officer", 0, None),
        ("Completed", "Manual", "QC Officer", "QC Officer", 5, "QC Report"),
    ]),
    ("Sample 2 Approval", "Sample 2 Fitting", "Completed", [
        ("In Progress", "Auto", None, "Technical Fitting Officer", 0, None),
        ("Rework", "Manual", "Technical Fitting Manager", "Technical Fitting Officer", 0, None),
        ("Completed", "Manual", "Technical Fitting Manager", "Technical Fitting Manager", 2, "Fitting Report"),
    ]),
    ("PPS Approval", "Sample 2 Approval", "Completed", [
        ("In Progress", "Auto", None, "Merchandiser", 0, None),
        # A Merchandiser reports PPS Ready; QC then owns the review.
        ("Ready", "Manual", "Merchandiser", "QC Officer", 0, None),
        ("Rework", "Manual", "QC Officer", "Merchandiser", 0, None),
        ("Completed", "Manual", "QC Officer", "Merchandiser", 7, None),
    ]),
    ("Bulk Production", "PPS Approval", "Completed", [
        ("Ready to Start", "Auto", None, "Merchandiser", 0, None),
        ("In Progress", "Manual", "Merchandiser", "Merchandiser", 0, None),
        ("Completed", "Manual", "Merchandiser", "Merchandiser", 35, None),
    ]),
    ("Final QC Inspection", "Bulk Production", "In Progress", [
        ("In Progress", "Auto", None, "QC Officer", 0, None),
        ("Completed", "Manual", "QC Officer", "QC Officer", 3, "QC Report"),
    ]),
    ("Shipment Ready", "Final QC Inspection", "Completed", [
        ("Ready to Start", "Auto", None, "Shipping Coordinator", 0, None),
        ("Completed", "Manual", "Shipping Coordinator", "Shipping Coordinator", 35, None),
    ]),
]


def seed_initial_master():
    """Install exactly once on a new site, never modify configured records."""
    import frappe

    if frappe.db.count("Design Milestone Type"):
        return {"seeded": 0, "existing_records": True}
    for position, (name, prerequisite, trigger, steps) in enumerate(STAGES, 1):
        doc = frappe.get_doc({
            "doctype": "Design Milestone Type",
            "milestone_type": name, "sequence": position * 10,
            "is_active": 1, "start_with_design_creation": int(not prerequisite),
            "depends_on_type": prerequisite,
            "r22_trigger_status": trigger or "Completed",
        })
        for step, mode, actor, custody, lead, evidence in steps:
            doc.append("workflow_steps", {
                "step": step, "enabled": 1, "transition_mode": mode,
                "responsible_module_role": actor, "custody_role": custody,
                "lead_time_days": lead, "requires_evidence": int(bool(evidence)),
                "evidence_type": evidence,
            })
        doc.insert(ignore_permissions=True)
    return {"seeded": len(STAGES), "existing_records": False}
