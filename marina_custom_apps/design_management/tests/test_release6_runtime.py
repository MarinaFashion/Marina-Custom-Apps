"""Real Frappe/MariaDB tests, explicitly guarded to the backed-up Demo site.

Not run by dependency-free CI. Never enable/run this module on Live.
"""
from uuid import uuid4

import frappe
from frappe.tests.utils import FrappeTestCase
from frappe.utils import add_days, today

from marina_custom_apps.design_management.api import milestones
from marina_custom_apps.design_management.api.follow_up import get_grid, bulk_save
from marina_custom_apps.design_management.milestone_store import RECORD


class TestRelease6Runtime(FrappeTestCase):
    def setUp(self):
        if frappe.local.site != 'marinademo.frappe.cloud':
            self.skipTest('Package 6 runtime fixtures are restricted to Marina Demo')
        if not frappe.conf.get('marina_design_release6_test_enabled'):
            self.skipTest('Explicit Demo test flag is required after taking a backup')
        frappe.set_user('Administrator')
        self.point = 'p6_test_' + uuid4().hex
        frappe.db.savepoint(self.point)
        self.suffix = uuid4().hex[:10]
        self.owner_user = self.user('Marina Merchandiser')
        self.other_user = self.user('Marina Merchandiser')
        self.designer = self.user('Marina Design Team')
        self.eligible(self.owner_user, 'merchandisers')
        self.eligible(self.other_user, 'merchandisers')
        self.eligible(self.designer, 'designers')
        category = frappe.get_doc({'doctype':'Marina Fashion Category', 'category_name':'P6 CAT '+self.suffix, 'is_active':1}).insert()
        subcategory = frappe.get_doc({'doctype':'Marina Fashion Category', 'category_name':'P6 SUB '+self.suffix,
                                     'parent_category':category.name, 'is_active':1}).insert()
        board = frappe.get_doc({'doctype':'Mood Board', 'mood_board_name':'P6 BOARD '+self.suffix,
            'year':'2027','season':'Summer','collection':'P6 TEST','image':'/files/p6-test.png',
            'authorized_merchandisers':[{'merchandiser':self.owner_user},{'merchandiser':self.other_user}]}).insert()
        self.design = frappe.get_doc({'doctype':'Design Code','design_number':'P6 DESIGN '+self.suffix,
            'mood_board':board.name,'assigned_merchandiser':self.owner_user,'designer':self.designer,
            'category':category.name,'subcategory':subcategory.name,'image':'/files/p6-test.png'}).insert()
        self.kind = frappe.get_doc({'doctype':'Design Milestone Type','milestone_type':'P6 STEP '+self.suffix,
            'sequence':1,'party_type':'Internal','responsible_party':'Other',
            'default_assignment_rule':'Accountable Merchandiser','default_lead_time_days':0,
            'schedule_mode':'Sequential','requires_evidence':0,'requires_qc_approval':0,'is_active':1}).insert()
        milestones.create_standard_milestones(self.design.name, add_days(today(), 3), [self.kind.name])
        self.record = frappe.get_all(RECORD, filters={'design_code':self.design.name}, fields=['*'])[0]

    def tearDown(self):
        if hasattr(self, 'point'):
            frappe.set_user('Administrator')
            frappe.db.rollback(save_point=self.point)
        super().tearDown()

    def user(self, role):
        name = 'p6-'+uuid4().hex[:10]+'@example.invalid'
        frappe.get_doc({'doctype':'User','email':name,'first_name':'Package6 Test',
            'username':'p6_'+uuid4().hex[:10],'enabled':1,'send_welcome_email':0,
            'roles':[{'role':role}]}).insert(ignore_permissions=True)
        return name

    def eligible(self, user, field):
        frappe.get_doc({'doctype':'Design Eligible User','name':uuid4().hex,
            'parent':'Design Management Settings','parenttype':'Design Management Settings',
            'parentfield':field,'user':user,'active':1}).db_insert()

    def test_workflow_persists_record_and_reuses_todo(self):
        original_todo = self.record.linked_todo
        self.assertTrue(original_todo)
        frappe.set_user(self.owner_user)
        milestones.mark_in_progress(self.design.name, self.record.milestone_id)
        milestones.mark_ready(self.design.name, self.record.milestone_id)
        milestones.confirm_completion(self.design.name, self.record.milestone_id)
        record = frappe.get_doc(RECORD, self.record.name)
        self.assertEqual(record.status, 'Completed')
        self.assertEqual(record.linked_todo, original_todo)
        self.assertEqual(frappe.db.get_value('ToDo', original_todo, 'status'), 'Closed')
        self.assertEqual(frappe.db.get_value('Design Code', self.design.name, 'milestone_completion'), 100)
        self.assertFalse(frappe.db.exists('Design Milestone', {'parent':self.design.name}))

    def test_grid_and_direct_record_permissions_agree(self):
        frappe.set_user(self.other_user)
        grid = get_grid(filters={'design_code':self.design.name})
        self.assertEqual(grid['total'], 0)
        self.assertFalse(frappe.has_permission(RECORD, 'read', doc=self.record.name))
        result = bulk_save([{'name':self.record.name, 'design_code':self.design.name,
            'expected_modified':str(self.record.modified), 'changes':{'due_date':str(add_days(today(),5))},
            'reason':'Unauthorized attempt'}])
        self.assertFalse(result['results'][0]['ok'])
        frappe.set_user(self.owner_user)
        grid = get_grid(filters={'design_code':self.design.name})
        self.assertEqual(grid['total'], 1)
        self.assertTrue(frappe.has_permission(RECORD, 'read', doc=self.record.name))

    def test_stale_bulk_edit_fails_without_overwriting(self):
        frappe.set_user(self.owner_user)
        original = str(self.record.modified)
        date1 = str(add_days(today(),4))
        milestones.revise_deadline(self.design.name,self.record.milestone_id,date1,'First revision')
        result = bulk_save([{'name':self.record.name,'design_code':self.design.name,
            'expected_modified':original,'changes':{'due_date':str(add_days(today(),7))},'reason':'Stale edit'}])
        self.assertFalse(result['results'][0]['ok'])
        self.assertEqual(str(frappe.db.get_value(RECORD,self.record.name,'due_date')),date1)

    def test_direct_form_write_cannot_bypass_actions(self):
        record = frappe.get_doc(RECORD,self.record.name)
        record.status = 'Completed'
        with self.assertRaises(frappe.ValidationError): record.save(ignore_permissions=True)
        self.assertEqual(frappe.db.get_value(RECORD,self.record.name,'status'),'Pending')

    def test_group_expansion_matches_global_group_count(self):
        frappe.set_user(self.owner_user)
        grouped = get_grid(filters={'design_code':self.design.name},group_by='milestone_type')
        self.assertEqual(grouped['groups'][0].total,1)
        expanded = get_grid(filters={'design_code':self.design.name},group_by='milestone_type',group_value=self.kind.name)
        self.assertEqual(expanded['total'],1)
        self.assertEqual(expanded['rows'][0].name,self.record.name)
