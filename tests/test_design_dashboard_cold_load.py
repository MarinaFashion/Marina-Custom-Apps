"""Guard dashboard against blank first navigation and blocking refreshes."""
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1] / "marina_custom_apps"
JS = ROOT / "marina_design_management/page/design_management_dashboard/design_management_dashboard.js"


class DashboardColdLoadTests(unittest.TestCase):
    def test_page_show_recovers_initialization_without_duplicate_handlers(self):
        code = JS.read_text(encoding="utf-8")
        self.assertIn('on_page_show=function(wrapper)', code)
        self.assertIn('if(wrapper.__marina_dashboard_initialized)return;', code)
        self.assertIn('wrapper.__marina_dashboard_initialized=true;', code)
        self.assertIn('wrapper.__marina_dashboard_refresh?.()', code)

    def test_initial_statistics_have_nonblocking_visible_state(self):
        code = JS.read_text(encoding="utf-8")
        self.assertNotIn('freeze:true', code)
        self.assertIn('role="status"', code)
        self.assertIn('Loading design statistics...', code)
        self.assertIn('Dashboard statistics could not be loaded.', code)
        self.assertIn('Previous figures are still shown.', code)
        self.assertIn('let pending=false;', code)
        self.assertIn('if(pending)return;', code)

    def test_permission_scoped_server_endpoint_is_unchanged(self):
        code = JS.read_text(encoding="utf-8")
        self.assertIn('api.dashboard.get_design_dashboard', code)
        self.assertIn('api.dashboard.get_dashboard_mood_board_options', code)
        self.assertIn('mdm-milestone-drilldown', code)


if __name__ == "__main__":
    unittest.main()
