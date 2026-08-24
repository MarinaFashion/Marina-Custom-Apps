# Marina Custom Apps

Umbrella Frappe/ERPNext custom application for Marina Trading Company.

## Initial modules

- **Stock Transfer Control** — central policy and workflow controls for Send Stock, Receive Stock, Transfer Between, Material Request → Stock Entry, End Transit, warehouse routing, and receiving discrepancies.
- **Stock Transfer Audit** — audit-window based review and settlement of stock transfer discrepancies.

## Architecture principle

Business modules are separated inside one Frappe app so deployment, versioning, testing, and future consolidation of Marina customizations remain manageable.

Current version: `0.1.0`
