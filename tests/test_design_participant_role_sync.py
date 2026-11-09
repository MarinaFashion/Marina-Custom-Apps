"""Regression contracts for Design Participant role synchronization.

These tests run without a Frappe site. They execute the actual synchronization
function against a small fake database so RBAC-off regressions are caught in CI.
"""
import ast
import pathlib
import types
import unittest

ROOT = pathlib.Path(__file__).resolve().parents[1]
SYNC = ROOT / "marina_custom_apps/design_management/security/module_role_sync.py"
INSTALL = ROOT / "marina_custom_apps/design_management/setup/install.py"


class _Settings:
    module_rbac_enabled = 0

    def __init__(self, rows, rbac=False):
        self.rows = [types.SimpleNamespace(user=user, module_role=role, active=active)
                     for user, role, active in rows]
        self.module_rbac_enabled = int(rbac)

    def get(self, key):
        assert key == "module_user_roles"
        return self.rows


class _User:
    def __init__(self, roles):
        self.roles = [types.SimpleNamespace(role=role) for role in roles]
        self.saved = 0

    def get(self, key):
        assert key == "roles"
        return self.roles

    def append(self, key, row):
        assert key == "roles"
        self.roles.append(types.SimpleNamespace(**row))

    def set(self, key, value):
        assert key == "roles"
        self.roles = value

    def save(self, **kwargs):
        assert kwargs == {"ignore_permissions": True}
        self.saved += 1


class TestParticipantSync(unittest.TestCase):
    def _execute(self, current, previous=None, *, force=False, roles=(), ledger=(), active_roles=("Merchandiser",)):
        # Extract only the real function; imports elsewhere may need a site.
        module_ast = ast.parse(SYNC.read_text())
        fn = next(n for n in module_ast.body
                  if isinstance(n, ast.FunctionDef) and n.name == "sync_user_roles")
        runner = ast.Module(body=[fn], type_ignores=[])
        ast.fix_missing_locations(runner)
        user = _User(roles)
        ledger_state = dict(ledger)
        writes = []

        class DB:
            def get_all(self, doctype, **kwargs):
                if doctype == "Design Module Role":
                    return list(active_roles)
                if doctype == "Design Module Managed Grant":
                    return [types.SimpleNamespace(name=name, frappe_role=role)
                            for role, name in ledger_state.items()]
                raise AssertionError(doctype)

            def get_doc(self, doctype, identifier=None):
                if doctype == "User":
                    return user
                if isinstance(doctype, dict) and doctype["doctype"] == "Design Module Managed Grant":
                    entry = doctype

                    class Grant:
                        def insert(self, **kwargs):
                            ledger_state[entry["frappe_role"]] = "grant-new"
                            writes.append("grant")
                    return Grant()
                raise AssertionError(doctype)

            def delete_doc(self, doctype, identifier, **kwargs):
                assert doctype == "Design Module Managed Grant"
                for role, name in list(ledger_state.items()):
                    if name == identifier:
                        del ledger_state[role]
                        writes.append("revoke")

            def clear_cache(self, **kwargs):
                pass

            def throw(self, message):
                raise ValueError(message)

        db = DB()
        fake_frappe = types.SimpleNamespace(get_all=db.get_all, get_doc=db.get_doc,
                    delete_doc=db.delete_doc, clear_cache=db.clear_cache, throw=db.throw)
        clear_cache_mod = types.SimpleNamespace(clear_role_cache=lambda: None)
        import sys
        name = "marina_custom_apps.design_management.security.organization"
        prior = sys.modules.get(name)
        sys.modules[name] = clear_cache_mod
        try:
            scope = {"frappe": fake_frappe, "BASE_ROLE": "Marina Design Participant",
                     "now_datetime": lambda: "2026-11-09"}
            exec(compile(runner, str(SYNC), "exec"), scope)
            scope["sync_user_roles"](current, previous, force=force)
        finally:
            if prior is None:
                del sys.modules[name]
            else:
                sys.modules[name] = prior
        return user, ledger_state, writes

    def test_rbac_off_new_assignment_grants_participant(self):
        user, ledger, _ = self._execute(
            _Settings([("staff@example.com", "Merchandiser", 1)], rbac=False),
            _Settings([], rbac=False))
        self.assertEqual({r.role for r in user.roles}, {"Marina Design Participant"})
        self.assertIn("Marina Design Participant", ledger)

    def test_rbac_toggle_does_not_revoke_grant(self):
        rows = [("staff@example.com", "Merchandiser", 1)]
        user, ledger, writes = self._execute(
            _Settings(rows, rbac=False), _Settings(rows, rbac=True),
            roles=("Marina Design Participant",),
            ledger=(("Marina Design Participant", "grant-old"),))
        self.assertEqual({r.role for r in user.roles}, {"Marina Design Participant"})
        self.assertEqual(ledger["Marina Design Participant"], "grant-old")
        self.assertEqual(writes, [])

    def test_force_migration_repairs_missing_grant_without_touching_manual_role(self):
        rows = [("staff@example.com", "Merchandiser", 1)]
        user, ledger, _ = self._execute(
            _Settings(rows, rbac=False), force=True, roles=("Desk User",))
        self.assertEqual({r.role for r in user.roles},
                         {"Desk User", "Marina Design Participant"})
        self.assertIn("Marina Design Participant", ledger)

    def test_inactive_assignment_revokes_only_managed_grant(self):
        user, ledger, _ = self._execute(
            _Settings([("staff@example.com", "Merchandiser", 0)]),
            _Settings([("staff@example.com", "Merchandiser", 1)]),
            roles=("Marina Design Participant", "Desk User"),
            ledger=(("Marina Design Participant", "grant-old"),))
        self.assertEqual({r.role for r in user.roles}, {"Desk User"})
        self.assertEqual(ledger, {})

    def test_migration_invokes_controlled_force_repair(self):
        install = INSTALL.read_text()
        self.assertIn("sync_user_roles(settings, None, force=True)", install)
        self.assertIn("if migrate:", install)


if __name__ == "__main__":
    unittest.main()
