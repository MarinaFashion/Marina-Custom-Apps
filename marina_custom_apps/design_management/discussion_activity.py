"""Mentions, per-message read receipts and transactional workflow updates.

Receipts acknowledge only messages the browser displayed, never a timestamp
watermark that could accidentally acknowledge a concurrent unseen message.
"""
import hashlib
import json
from urllib.parse import quote

import frappe
from frappe.utils import now_datetime
from marina_custom_apps.design_management.discussions import MESSAGE, parent_access, _internal

RECEIPT = 'Marina Discussion Receipt'


def _key(message, user):
    return hashlib.sha256((message + '\0' + user).encode()).hexdigest()


def _list(value, maximum=50):
    if isinstance(value, str):
        try:
            value = json.loads(value)
        except ValueError:
            frappe.throw('Invalid discussion selection.')
    if value is None:
        return []
    if not isinstance(value, list) or len(value) > maximum or any(not isinstance(v, str) or not v or len(v) > 140 for v in value):
        frappe.throw('Invalid discussion selection.')
    return list(dict.fromkeys(value))


def _allowed(parent, user):
    from marina_custom_apps.design_management.security.participants import is_participant
    return is_participant(user) and parent.has_permission('read', user=user)


def validate_mentions(doctype, name, mentions, strict=True):
    users = _list(mentions, 10 if strict else 50)
    if not users:
        return []
    parent = parent_access(doctype, name)
    result = []
    for user in users:
        if _allowed(parent, user):
            result.append(user)
        elif strict:
            frappe.throw('A selected colleague no longer has access to this record. Remove the mention and try again.', frappe.PermissionError)
    return result


@frappe.whitelist()
def mention_candidates(reference_doctype, reference_name, query=''):
    parent = parent_access(reference_doctype, reference_name)
    if not isinstance(query, str) or len(query) > 100:
        frappe.throw('Invalid user search.')
    # Bound the candidate set and filter document access before returning names.
    candidates = frappe.db.sql('''SELECT u.name, COALESCE(NULLIF(u.username,''),u.name) AS label
        FROM `tabUser` u WHERE u.enabled=1 AND u.user_type='System User'
        AND EXISTS (SELECT 1 FROM `tabHas Role` h WHERE h.parent=u.name
                    AND h.parenttype='User' AND h.role='Marina Design Participant')
        AND (u.username LIKE %s OR u.name LIKE %s)
        ORDER BY u.username,u.name LIMIT 100''', ('%'+query+'%', '%'+query+'%'), as_dict=True)
    return [dict(value=u.name, label=u.label) for u in candidates
            if parent.has_permission('read', user=u.name)][:20]


def record_mentions(doc, users):
    """Called only on new messages; retries and text edits never resend alerts."""
    from frappe.desk.doctype.notification_log.notification_log import set_notifications_as_unseen
    from frappe.desk.doctype.notification_settings.notification_settings import is_notifications_enabled
    for user in users:
        receipt_name = _key(doc.name, user)
        if frappe.db.exists(RECEIPT, receipt_name):
            continue
        notification = None
        if is_notifications_enabled(user) and (user != frappe.session.user or doc.is_system):
            notification = 'mdm-' + receipt_name[:32]
            # db_insert deliberately avoids NotificationLog.after_insert, which
            # may send email. This release authorizes in-app notifications only.
            frappe.get_doc(dict(doctype='Notification Log', name=notification,
                type='Mention', subject='You have a new mention in Design Discussions',
                for_user=user, from_user=frappe.session.user,
                link='/app/design-discussions?message=' + quote(doc.name, safe=''),
                read=0)).db_insert()
            set_notifications_as_unseen(user)
            frappe.publish_realtime('notification', user=user, after_commit=True)
        frappe.get_doc(dict(doctype=RECEIPT, name=receipt_name, message=doc.name,
            user=user, is_mention=1, is_read=0, notification=notification)).db_insert()


def unread_count(doctype, name):
    return int(frappe.db.sql('''SELECT COUNT(*) FROM `tabMarina Discussion Message` m
        LEFT JOIN `tabMarina Discussion Receipt` r ON r.message=m.name AND r.user=%s
        WHERE m.reference_doctype=%s AND m.reference_name=%s AND m.is_archived=0
        AND m.is_removed=0 AND (m.owner!=%s OR m.is_system=1)
        AND COALESCE(r.is_read,0)=0''', (frappe.session.user, doctype, name, frappe.session.user))[0][0])


@frappe.whitelist(methods=['POST'])
def mark_read(reference_doctype, reference_name, names):
    parent_access(reference_doctype, reference_name)
    names = _list(names)
    if names:
        rows = frappe.get_all(MESSAGE, filters={'name': ['in', names],
            'reference_doctype': reference_doctype, 'reference_name': reference_name,
            'is_archived': 0}, pluck='name', limit_page_length=50)
        if set(rows) != set(names):
            frappe.throw('Messages must belong to this discussion.', frappe.PermissionError)
        # Unique message/user key handles concurrent tabs. Updating after insert
        # also preserves an existing mention and its notification relationship.
        for name in rows:
            # Plain idempotent SQL avoids Frappe validation of an existing receipt
            # interrupting display of historical messages. Do not replace existing
            # rows: a prior mention/notification must be preserved.
            frappe.db.sql("""INSERT IGNORE INTO `tabMarina Discussion Receipt`
                (`name`, `creation`, `modified`, `modified_by`,
                 `owner`, `docstatus`, `idx`, `message`, `user`,
                 `is_read`, `is_mention`)
                VALUES (%s, NOW(), NOW(), %s, %s, 0, 0, %s, %s, 1, 0)""",
                (_key(name, frappe.session.user), frappe.session.user,
                 frappe.session.user, name, frappe.session.user))
        frappe.db.sql('''UPDATE `tabMarina Discussion Receipt` SET is_read=1
            WHERE user=%s AND message IN %s''', (frappe.session.user, tuple(rows)))
        notifications = frappe.get_all(RECEIPT, filters={'user': frappe.session.user,
            'message': ['in', rows], 'notification': ['is', 'set']}, pluck='notification', limit_page_length=50)
        if notifications:
            frappe.db.sql('''UPDATE `tabNotification Log` SET `read`=1
                WHERE for_user=%s AND name IN %s''', (frappe.session.user, tuple(notifications)))
    return {'unread': unread_count(reference_doctype, reference_name)}


@frappe.whitelist()
def count(reference_doctype, reference_name):
    parent_access(reference_doctype, reference_name)
    return {'unread': unread_count(reference_doctype, reference_name)}


@frappe.whitelist()
def locate(message):
    doc = frappe.get_doc(MESSAGE, message)
    parent_access(doc.reference_doctype, doc.reference_name)
    if doc.is_archived:
        frappe.throw('This discussion was archived.', frappe.PermissionError)
    return dict(reference_doctype=doc.reference_doctype, reference_name=doc.reference_name, message=doc.name)


@frappe.whitelist()
def inbox(view='Unread', reference_doctype=None, reference_name=None, offset=0):
    if frappe.session.user == 'Guest':
        frappe.throw('Sign in to view discussions.', frappe.PermissionError)
    if view not in ('Unread', 'Mentioned Me', 'All') or reference_doctype not in (None, '', 'Design Code', 'Mood Board'):
        frappe.throw('Invalid discussion filter.')
    offset = max(0, min(int(offset), 1000000))
    conditions = ['m.is_archived=0', 'm.is_removed=0']
    args = {'user': frappe.session.user, 'offset': offset}
    if reference_doctype:
        conditions.append('m.reference_doctype=%(doctype)s'); args['doctype'] = reference_doctype
    if reference_name:
        if not reference_doctype:
            frappe.throw('Select a record type first.')
        parent_access(reference_doctype, reference_name)
        conditions.append('m.reference_name=%(record)s'); args['record'] = reference_name
    having = {'All': '', 'Unread': 'HAVING unread>0', 'Mentioned Me': 'HAVING mentions>0'}[view]
    candidates = frappe.db.sql('''SELECT m.reference_doctype, m.reference_name,
        MAX(m.creation) AS last_activity,
        SUM(CASE WHEN (m.owner!=%(user)s OR m.is_system=1) AND COALESCE(r.is_read,0)=0 THEN 1 ELSE 0 END) AS unread,
        SUM(COALESCE(r.is_mention,0)) AS mentions,
        SUM(CASE WHEN r.is_mention=1 AND r.is_read=0 THEN 1 ELSE 0 END) AS unread_mentions
        FROM `tabMarina Discussion Message` m LEFT JOIN `tabMarina Discussion Receipt` r
        ON r.message=m.name AND r.user=%(user)s WHERE ''' + ' AND '.join(conditions) + '''
        GROUP BY m.reference_doctype,m.reference_name ''' + having + '''
        ORDER BY last_activity DESC,m.reference_doctype,m.reference_name
        LIMIT 200 OFFSET %(offset)s''', args, as_dict=True)
    result, scanned = [], 0
    for row in candidates:
        scanned += 1
        # Never return metadata or counts before checking current record access.
        try:
            parent_access(row.reference_doctype, row.reference_name)
        except (frappe.PermissionError, frappe.DoesNotExistError):
            frappe.clear_last_message()
            continue
        item = dict(row)
        if view == 'Mentioned Me' or row.get('unread_mentions'):
            unread_only = 'AND r.is_read=0' if row.get('unread_mentions') else ''
            mention = frappe.db.sql("""SELECT m.name FROM `tabMarina Discussion Message` m
                JOIN `tabMarina Discussion Receipt` r ON r.message=m.name
                WHERE r.user=%s AND r.is_mention=1 AND m.reference_doctype=%s
                AND m.reference_name=%s AND m.is_archived=0 AND m.is_removed=0 """
                + unread_only + ' ORDER BY m.creation DESC,m.name DESC LIMIT 1',
                (frappe.session.user, row.reference_doctype, row.reference_name))
            item['focus_message'] = mention[0][0] if mention else None
        result.append(item)
        if len(result) == 25:
            break
    # Fetch previews only for permitted conversations, in one bounded query.
    # Never include message metadata from discussions that failed access checks.
    for item in result:
        doctype, name = item['reference_doctype'], item['reference_name']
        fields = ['image']
        item['image'] = frappe.db.get_value(doctype, name, 'image')
        latest = frappe.db.sql("""SELECT body, is_system, owner FROM `tabMarina Discussion Message`
            WHERE reference_doctype=%s AND reference_name=%s
              AND is_archived=0 AND is_removed=0
            ORDER BY creation DESC, name DESC LIMIT 1""", (doctype, name), as_dict=True)
        if latest:
            item['preview'] = (latest[0].body or ('Milestone update' if latest[0].is_system else 'Attachment')).replace('\\n', ' ')[:100]
    return dict(rows=result, next_offset=offset+scanned,
                has_more=scanned < len(candidates) or len(candidates) == 200)


def milestone_completed(design, execution, event_id, activated, effective_date):
    """Publish once, inside the same transaction as the successful transition."""
    name = 'milestone-' + hashlib.sha256(event_id.encode()).hexdigest()[:32]
    if frappe.db.exists(MESSAGE, name):
        return
    assignments, automatic, recipients = [], [], []
    for milestone in dict.fromkeys(activated):
        row = frappe.db.get_value('Design Milestone Execution',
            {'design_code': design.name, 'milestone_type': milestone},
            ['status', 'current_custodian'], as_dict=True)
        if not row:
            continue
        if row.status == 'Completed':
            automatic.append(milestone)
        elif row.current_custodian and row.status != 'Planned':
            username = frappe.db.get_value('User', row.current_custodian, 'username') or row.current_custodian
            assignments.append(milestone + ' — assigned to @' + username + ' (' + row.status + ')')
            recipients.append(row.current_custodian)
    actor = frappe.db.get_value('User', frappe.session.user, 'username') or frappe.session.user
    body = execution.milestone_type + ' completed by ' + actor + '. Effective date: ' + str(effective_date) + '.'
    if automatic:
        body += '\nAutomatically completed: ' + ', '.join(automatic) + '.'
    body += '\nNew assignments:\n' + '\n'.join(assignments) if assignments else '\nNo new milestone assignment was activated by this completion.'
    # Scope changes must not turn a valid milestone completion into an invalid
    # mention. Only currently eligible recipients receive an alert.
    users = [user for user in dict.fromkeys(recipients) if _allowed(design, user)]
    token = _internal.set(True)
    try:
        doc = frappe.get_doc(dict(doctype=MESSAGE, reference_doctype='Design Code', reference_name=design.name,
            body=body, is_system=1, source_event=event_id, mentions_json=json.dumps(users), history_json='[]', revision=0))
        doc.insert(ignore_permissions=True, set_name=name)
        record_mentions(doc, users)
        # Notify open discussions only after the milestone transaction commits.
        # Do not include design identifiers or message text in the shared event.
        frappe.publish_realtime('marina_discussion_changed', after_commit=True)
    finally:
        _internal.reset(token)
