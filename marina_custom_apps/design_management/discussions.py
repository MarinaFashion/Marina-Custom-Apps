"""Record-scoped discussions. No milestone or evidence side effects."""
import base64
import binascii
from contextvars import ContextVar
import io
import json
from pathlib import PurePath
import re

import frappe
from frappe.utils import now_datetime

MESSAGE = 'Marina Discussion Message'
PARENTS = ('Design Code', 'Mood Board')
MAX_FILE = 10 * 1024 * 1024
_internal = ContextVar('marina_discussion_write', default=False)


def require_internal_write():
    if not _internal.get():
        frappe.throw('Use the Discussion panel to change messages.', frappe.PermissionError)


def parent_access(doctype, name, user=None):
    user = user or frappe.session.user
    if user == 'Guest' or doctype not in PARENTS or not isinstance(name, str) or not name:
        frappe.throw('Discussion access denied.', frappe.PermissionError)
    doc = frappe.get_doc(doctype, name)
    if not doc.has_permission('read', user=user):
        frappe.throw('Discussion access denied.', frappe.PermissionError)
    return doc


def has_permission(doc, ptype=None, user=None):
    if doc.is_archived or ptype not in (None, 'read', 'select'):
        return False
    try:
        parent_access(doc.reference_doctype, doc.reference_name, user)
        return True
    except (frappe.PermissionError, frappe.DoesNotExistError):
        return False


def query_condition(user=None):
    # Listing and exporting messages directly must not bypass the parent check.
    return '1=0'


def file_permission(doc, ptype=None, user=None):
    if doc.attached_to_doctype != MESSAGE:
        return None
    if ptype not in (None, 'read', 'select'):
        return False
    message = frappe.get_doc(MESSAGE, doc.attached_to_name)
    from marina_custom_apps.design_management.discussion_retention import is_past_expiry
    if is_past_expiry(message):
        return False
    return has_permission(message, 'read', user)


def file_query_condition(user=None):
    # Private download checks the message's parent. Generic File lists must not
    # expose discussion attachment metadata from other teams.
    return "COALESCE(`tabFile`.`attached_to_doctype`, '') != 'Marina Discussion Message'"


def clean_body(body):
    if not isinstance(body, str) or len(body) > 10000:
        frappe.throw('Messages must be text with at most 10,000 characters.')
    return body.strip()


def parse_attachment(filename, content):
    if not filename and not content:
        return None
    if not isinstance(filename, str) or not isinstance(content, str) or len(content) > ((MAX_FILE + 2) // 3) * 4:
        frappe.throw('Choose a file up to 10 MB.')
    filename = PurePath(filename.replace('\\', '/')).name
    if not filename or len(filename) > 140 or any(ord(c) < 32 for c in filename):
        frappe.throw('Invalid file name.')
    ext = PurePath(filename).suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.pdf', '.txt', '.csv', '.docx', '.xlsx', '.pptx', '.zip', '.psd', '.ai', '.eps', '.tif', '.tiff', '.mp4', '.mov'):
        frappe.throw('Supported files: images, PDF, Office, ZIP, Adobe design files and videos (MP4/MOV).')
    try:
        raw = base64.b64decode(content, validate=True)
    except (ValueError, binascii.Error):
        frappe.throw('Invalid attachment.')
    if not raw or len(raw) > MAX_FILE:
        frappe.throw('Choose a nonempty file up to 10 MB.')
    is_image = ext in ('.jpg', '.jpeg', '.png', '.webp')
    if is_image:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 40000000:
                    raise ValueError('Unsupported image')
                image.verify()
        except Exception:
            frappe.throw('The image could not be read. Use a valid JPG, PNG or WebP image.')
    return filename, raw, is_image


def public_message(doc):
    from marina_custom_apps.design_management.discussion_retention import is_past_expiry
    removed = bool(doc.is_removed)
    expired = is_past_expiry(doc)
    expiry = doc.attachment_expires_on
    remaining = None
    if expiry:
        from frappe.utils import get_datetime
        remaining = max(0, int((get_datetime(expiry) - now_datetime()).total_seconds()))
    mentions = json.loads(doc.mentions_json or '[]')
    return dict(name=doc.name, owner=doc.owner, creation=str(doc.creation),
                owner_label=frappe.get_cached_value('User', doc.owner, 'username') or doc.owner,
                owner_image=frappe.get_cached_value('User', doc.owner, 'user_image') or '',
                body='' if removed else doc.body, reply_to=doc.reply_to,
                revision=doc.revision or 0, is_removed=removed, is_system=bool(doc.is_system),
                mentions=mentions, mention_labels={u: frappe.get_cached_value('User', u, 'username') or u for u in mentions},
                attachment_url='' if removed or expired else doc.attachment_url,
                attachment_name='' if removed else doc.attachment_name,
                attachment_expired=expired,
                attachment_expires_on=str(expiry or ''),
                attachment_seconds_remaining=remaining,
                attachment_size=int(doc.attachment_size or 0),
                is_image=bool(doc.is_image), can_edit=doc.owner == frappe.session.user and not removed and not doc.is_system)


@frappe.whitelist()
def attachment_policy(reference_doctype, reference_name):
    """Return the current *new upload* policy only to conversation participants."""
    parent_access(reference_doctype, reference_name)
    from marina_custom_apps.design_management.discussion_retention import get_retention_policy
    policy = get_retention_policy()
    return dict(threshold_mb=policy["threshold_mb"],
                retention_days=policy["retention_days"])


@frappe.whitelist()
def messages(reference_doctype, reference_name, before=None, focus=None):
    parent_access(reference_doctype, reference_name)
    filters = dict(reference_doctype=reference_doctype, reference_name=reference_name)
    # Cursor is an existing message, never a client-provided SQL expression.
    if before or focus:
        cursor = frappe.get_doc(MESSAGE, before or focus)
        if cursor.is_archived or (cursor.reference_doctype, cursor.reference_name) != (reference_doctype, reference_name):
            frappe.throw('Invalid discussion cursor.', frappe.PermissionError)
        conditions = 'AND (creation < %(created)s OR (creation = %(created)s AND name < %(before)s))'
        if focus and not before:
            conditions = conditions.replace('name <', 'name <=')
        filters.update(created=cursor.creation, before=cursor.name)
    else:
        conditions = ''
    rows = frappe.db.sql('''SELECT name FROM `tabMarina Discussion Message`
        WHERE is_archived=0 AND reference_doctype=%(reference_doctype)s AND reference_name=%(reference_name)s
        ''' + conditions + ' ORDER BY creation DESC, name DESC LIMIT 51', filters, as_dict=True)
    result = [public_message(frappe.get_doc(MESSAGE, row.name)) for row in rows[:50]]
    # Include quoted messages even when they fall outside this page.
    quotes = {}
    for item in result:
        if item['reply_to'] and item['reply_to'] not in quotes:
            reply = frappe.get_doc(MESSAGE, item['reply_to'])
            if not reply.is_archived and (reply.reference_doctype, reply.reference_name) == (reference_doctype, reference_name):
                quotes[reply.name] = public_message(reply)
    return dict(messages=list(reversed(result)), quotes=quotes, has_more=len(rows) > 50,
                next_cursor=result[-1]['name'] if result else None)


def validate_binary_attachment(filename, raw, max_size=None):
    """Validate a native binary attachment without Base64 conversion."""
    if not isinstance(filename, str) or not filename:
        frappe.throw("Invalid attachment name.")
    filename = PurePath(filename.replace('\\\\', '/')).name
    if not filename or len(filename) > 140 or any(ord(c) < 32 for c in filename):
        frappe.throw("Invalid file name.")
    if not isinstance(raw, bytes) or not raw:
        frappe.throw("Choose a nonempty attachment.")
    if max_size is not None and len(raw) > max_size:
        frappe.throw("Attachment exceeds the permitted size.")
    ext = PurePath(filename).suffix.lower()
    if ext not in ('.jpg', '.jpeg', '.png', '.webp', '.pdf', '.txt', '.csv', '.docx', '.xlsx', '.pptx', '.zip', '.psd', '.ai', '.eps', '.tif', '.tiff', '.mp4', '.mov'):
        frappe.throw("Supported files: images, PDF, Office, ZIP, Adobe design files and videos (MP4/MOV).")
    is_image = ext in ('.jpg', '.jpeg', '.png', '.webp')
    if is_image:
        from PIL import Image
        try:
            with Image.open(io.BytesIO(raw)) as image:
                if image.format not in ('JPEG', 'PNG', 'WEBP') or image.width * image.height > 40000000:
                    raise ValueError("Unsupported image")
                image.verify()
        except Exception:
            frappe.throw("The image could not be read. Use a valid JPG, PNG or WebP image.")
    return filename, raw, is_image


def _create_discussion_message(reference_doctype, reference_name, body, reply_to,
                               request_id, mentions, attachment=None):
    """Shared transactional implementation for text and native binary uploads."""
    parent_access(reference_doctype, reference_name)
    body = clean_body(body)
    if not isinstance(request_id, str) or not re.fullmatch(r'[a-f0-9]{32}', request_id):
        frappe.throw("Invalid message request. Refresh and retry.")
    name = "discussion-" + request_id
    if frappe.db.exists(MESSAGE, name):
        existing = frappe.get_doc(MESSAGE, name)
        if (existing.is_archived or
            (existing.owner, existing.reference_doctype, existing.reference_name)
            != (frappe.session.user, reference_doctype, reference_name)):
            frappe.throw("Invalid message request.", frappe.PermissionError)
        return public_message(existing)

    from marina_custom_apps.design_management.discussion_activity import validate_mentions, record_mentions
    users = validate_mentions(reference_doctype, reference_name, mentions)
    if not body and not attachment:
        frappe.throw("Enter a message or select a file.")
    if reply_to:
        reply = frappe.get_doc(MESSAGE, reply_to)
        if reply.is_archived or (reply.reference_doctype, reply.reference_name) != (reference_doctype, reference_name):
            frappe.throw("Replies must belong to the same discussion.", frappe.PermissionError)

    token = _internal.set(True)
    try:
        doc = frappe.get_doc(dict(
            doctype=MESSAGE, reference_doctype=reference_doctype,
            reference_name=reference_name, body=body, reply_to=reply_to,
            revision=0, history_json='[]', mentions_json=json.dumps(users)
        ))
        doc.insert(ignore_permissions=True, set_name=name)
        if attachment:
            filename, raw, is_image = attachment
            file = frappe.get_doc(dict(
                doctype='File', file_name=filename, content=raw, is_private=1,
                owner='Administrator', attached_to_doctype=MESSAGE,
                attached_to_name=doc.name
            ))
            file.insert(ignore_permissions=True)
            file.db_set('owner', 'Administrator', update_modified=False)
            from marina_custom_apps.design_management.discussion_retention import expiry_for_size
            doc.attachment_file_id = file.name
            doc.attachment_size = int(file.file_size or len(raw))
            doc.attachment_expires_on = expiry_for_size(doc.attachment_size)
            doc.attachment_url = file.file_url
            doc.attachment_name = filename
            doc.is_image = int(is_image)
            doc.save(ignore_permissions=True)
        record_mentions(doc, users)
        frappe.publish_realtime('marina_discussion_changed', after_commit=True)
        return public_message(doc)
    finally:
        _internal.reset(token)


@frappe.whitelist(methods=['POST'])
def send(reference_doctype, reference_name, body='', reply_to=None,
         filename=None, content=None, request_id=None, mentions=None):
    """Compatibility endpoint for text and older <=10 MiB Base64 clients."""
    # Reject file payloads larger than the legacy limit; use multipart for all
    # newer attachments to avoid 33% Base64 inflation and long JSON requests.
    attachment = parse_attachment(filename, content)
    return _create_discussion_message(
        reference_doctype, reference_name, body, reply_to, request_id, mentions,
        attachment=attachment
    )


@frappe.whitelist(methods=['POST'])
def send_uploaded_file():
    """Called only via /api/method/upload_file's whitelisted 'method' hook.

    The Frappe upload handler makes the binary content available in
    frappe.local.uploaded_file. We do not accept a generic File ID or URL from
    the client, preventing attachment of arbitrary existing private files.
    """
    if frappe.session.user == "Guest":
        frappe.throw("Login required.", frappe.PermissionError)
    args = frappe.form_dict
    if args.get("file_url") or args.get("library_file_name"):
        frappe.throw("Upload a new binary file.", frappe.PermissionError)
    raw = getattr(frappe.local, 'uploaded_file', None)
    filename = getattr(frappe.local, 'uploaded_filename', None)
    # Keep an application-specific upper bound, even when the site upload
    # configuration is higher. Frappe's File controller also applies its
    # configured server-side maximum.
    attachment = validate_binary_attachment(filename, raw, max_size=500 * 1024 * 1024)
    return _create_discussion_message(
        args.get("reference_doctype"), args.get("reference_name"),
        args.get("body", ""), args.get("reply_to"),
        args.get("request_id"), args.get("mentions"),
        attachment=attachment
    )


@frappe.whitelist(methods=['POST'])
def change(name, expected_revision, body='', remove=0):
    # Serialize concurrent edits so neither history nor message text is lost.
    frappe.db.sql('SELECT name FROM `tabMarina Discussion Message` WHERE name=%s FOR UPDATE', (name,))
    doc = frappe.get_doc(MESSAGE, name)
    parent_access(doc.reference_doctype, doc.reference_name)
    if doc.is_archived or doc.is_system or doc.owner != frappe.session.user or doc.is_removed:
        frappe.throw('Only the author can change an active message.', frappe.PermissionError)
    if str(expected_revision) != str(doc.revision or 0):
        frappe.throw('This message has changed. Refresh the discussion before editing.')
    remove = str(remove) == '1'
    body = clean_body(body)
    if not remove and not body and not doc.attachment_url:
        frappe.throw('Enter a message, or use Remove.')
    history = json.loads(doc.history_json or '[]')
    history.append(dict(body=doc.body, changed_by=frappe.session.user, changed_at=str(now_datetime()),
                        action='removed' if remove else 'edited', revision=doc.revision or 0,
                        attachment_url=doc.attachment_url, attachment_name=doc.attachment_name))
    doc.history_json = json.dumps(history)
    doc.body = '' if remove else body
    doc.is_removed = int(remove)
    doc.revision = (doc.revision or 0) + 1
    token = _internal.set(True)
    try:
        doc.save(ignore_permissions=True)
    finally:
        _internal.reset(token)
    return public_message(doc)


@frappe.whitelist()
def history(name):
    doc = frappe.get_doc(MESSAGE, name)
    parent_access(doc.reference_doctype, doc.reference_name)
    if doc.is_archived:
        frappe.throw('This discussion was archived with its deleted record.', frappe.PermissionError)
    revisions = json.loads(doc.history_json or '[]')
    from marina_custom_apps.design_management.discussion_retention import is_past_expiry
    if is_past_expiry(doc):
        for revision in revisions:
            revision['attachment_url'] = ''
    return revisions


def archive_on_parent_delete(doc, method=None):
    """Keep audit data without reattaching it to a recreated record name."""
    frappe.db.sql("""UPDATE `tabMarina Discussion Message` SET is_archived=1
        WHERE reference_doctype=%s AND reference_name=%s""", (doc.doctype, doc.name))
