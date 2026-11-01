"""Deterministic, guarded Package 1 sample dataset. Never invoke on Live."""
import frappe

PREFIX = "MDM-TEST-P1-"

def _guard():
    frappe.only_for("System Manager")
    if frappe.conf.get("marina_design_demo_sample_enabled") is not True:
        frappe.throw("Sample-data operations are disabled for this site. Enable explicitly in DEMO site_config.json only")

def _sample_file(name):
    from frappe.utils.file_manager import save_file
    existing=frappe.db.get_value('File',{'file_name':name,'attached_to_doctype':'Marina Mood Board','attached_to_name':PREFIX+'BOARD-1'},'file_url')
    if existing:return existing
    f=save_file(name,("Synthetic Demo sample document: "+name+". Not a commercial specification.\n").encode(),"Marina Mood Board",PREFIX+'BOARD-1',is_private=1)
    return f.file_url

@frappe.whitelist()
def load_sample_data():
    _guard()
    created=[]
    for name,parent in [(PREFIX+'Dresses',None),(PREFIX+'Evening Dresses',PREFIX+'Dresses')]:
        if not frappe.db.exists('Marina Fashion Category',name):
            frappe.get_doc({'doctype':'Marina Fashion Category','category_name':name,'parent_category':parent,'is_active':1}).insert()
            created.append(name)
    for code in (PREFIX+'19-0001',PREFIX+'19-0002',PREFIX+'19-0003'):
        if not frappe.db.exists('Marina Pantone',code):
            frappe.get_doc({'doctype':'Marina Pantone','pantone_code':code,'color_name':'DEMO ONLY','color_system':'TCX','is_active':1}).insert()
            created.append(code)
    if not frappe.db.exists('Marina Mood Board',PREFIX+'BOARD-1'):
        from frappe.utils.file_manager import save_file
        board=frappe.get_doc({'doctype':'Marina Mood Board','mood_board_name':PREFIX+'BOARD-1','image':'/files/placeholder-demo-image.png','year':'2027','season':'Summer','collection':'DEMO ONLY','tech_packs':[{'tech_pack_title':'Sample tech pack','attachment':'/private/files/sample-techpack-demo.txt'}]})
        board.insert()
        image = save_file('mdm_demo_board.png',bytes.fromhex('89504e470d0a1a0a0000000d49484452000000010000000108060000001f15c4890000000b49444154789c636000020000050001a5f645400000000049454e44ae426082'),'Marina Mood Board',board.name,is_private=1)
        tech = save_file('mdm_demo_techpack.txt',b'SYNTHETIC DEMO TECH PACK - NO REAL SUPPLIER INFORMATION','Marina Mood Board',board.name,is_private=1)
        board.image=image.file_url
        board.tech_packs[0].attachment=tech.file_url
        board.save()
        created.append(board.name)
    return {'sample_prefix':PREFIX,'created':created,'message':'Demo sample records ready. Only Package 1 masters/Mood Board are included.'}

@frappe.whitelist()
def clean_up_sample_data(confirmation=None):
    _guard()
    if confirmation != 'DELETE MDM P1 SAMPLE':
        frappe.throw('Confirmation must equal DELETE MDM P1 SAMPLE')
    deleted=[]
    for typ, names in [
      ('Marina Mood Board',[PREFIX+'BOARD-1']),
      ('Marina Pantone',[PREFIX+'19-0001',PREFIX+'19-0002',PREFIX+'19-0003']),
      ('Marina Fashion Category',[PREFIX+'Evening Dresses',PREFIX+'Dresses'])
    ]:
        for name in names:
            if frappe.db.exists(typ,name):
                frappe.delete_doc(typ,name,ignore_permissions=False)
                deleted.append(typ+': '+name)
    return {'deleted':deleted}
