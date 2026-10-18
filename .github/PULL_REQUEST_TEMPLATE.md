## Summary of Changes

Provide a brief description of what this PR does and why it was introduced.

## Issue Reference

Fixes #(issue)

## Component(s) Changed

- [ ] Core Engine / Pipeline (`pipeline.py`, `state_machine.py`)
- [ ] Identity & Access Management (`keycloak_auth.py`, `keycloak_client.py`, `dual_control_store.py`)
- [ ] Evidence Chain & Ledger (`evidence_log.py`, `verify_log.py`)
- [ ] Digital Twin & Physics (`physics_digital_twin.py`, `digital_twin.py`)
- [ ] Risk Engine & XAI (`multi_dimensional_risk.py`, `causal_xai.py`)
- [ ] Qt HMI Dashboard (`dashboard_qt.py`, `industrial_theme.py`, etc.)
- [ ] API & Server (`main.py`)
- [ ] Deployment / Containers / Docs

## Verification & Testing

- [ ] All 103+ unit and compliance tests pass (`pytest`)
- [ ] Test isolation verified (no local ledger/db pollution outside temp directories)
- [ ] New functionality covered with unit tests
- [ ] Code formatted and linted (`ruff check .`)

## Security Checklist

- [ ] No hardcoded secrets, tokens, or credentials added
- [ ] Authorization gates properly validated for subsystem states
- [ ] Audit logs and tamper-evident hashes preserved
