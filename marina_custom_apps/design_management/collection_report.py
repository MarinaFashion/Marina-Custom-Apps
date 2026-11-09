"""Read-only collection report using the user's existing Design Code scope."""
import re
from urllib.parse import urlsplit

import frappe

MAX_DESIGNS = 1000
PAGE_SIZE = 24


def mood_board_sort_key(board):
    """Natural Drop order (2 before 10), with unassigned drops last."""
    drop = str(board.get("drop") or "").strip().casefold()
    parts = tuple((1, int(part)) if part.isdigit() else (0, part)
                  for part in re.split(r"(\d+)", drop) if part)
    return (not bool(drop), parts, str(board.get("title") or "").casefold())


def report_sort_key(row):
    position = row.get('report_position') or 0
    code = row.get('design_number') or row['name']
    if position > 0:
        return (0, position, code.casefold(), row['name'])
    dress = (row.get('category') or '').strip().casefold() in ('dress', 'dresses')
    return (1, 0 if dress else 1, code.casefold(), row['name'])


def safe_image(value):
    """Allow browser-loaded web images and local attachments/assets."""
    if not isinstance(value, str):
        return ''
    value = value.strip()
    if not value or any(ord(c) < 32 for c in value) or '\\' in value:
        return ''
    try:
        parsed = urlsplit(value)
        if parsed.scheme in ('http', 'https') and parsed.hostname:
            if parsed.username or parsed.password:
                return ''
            return value
    except ValueError:
        return ''
    if parsed.scheme or parsed.netloc:
        return ''
    return value if parsed.path.startswith(('/files/', '/private/files/', '/assets/')) else ''


def mood_board_display_name(name):
    """Remove a numeric presentation prefix; never change the stored Mood Board ID."""
    name = str(name or '').strip()
    return re.sub(r'^\d+\s*[-–—]\s*', '', name, count=1) or name


def cover_heading(year, season, collection, drop, title):
    return ' / '.join(str(value).strip() for value in (year, season, collection, drop,
                                                       mood_board_display_name(title))
                      if value is not None and str(value).strip())


def milestone_caption(plans):
    active = list(dict.fromkeys(p['milestone_type'] for p in plans if p['plan_state'] == 'Active'))
    if active:
        return 'Current: ' + ' / '.join(active)
    if not plans:
        return 'Milestones not created'
    if all(p['plan_state'] == 'Completed' for p in plans):
        return 'All milestones completed'
    return 'Awaiting milestone activation'


def board_context(mood_board):
    if not isinstance(mood_board, str) or not mood_board or len(mood_board) > 140:
        frappe.throw('Select a Mood Board')
    board = frappe.get_doc('Mood Board', mood_board)
    board.check_permission('read')
    if not frappe.has_permission('Design Code', 'read'):
        frappe.throw('Design Code read permission required', frappe.PermissionError)
    designs = frappe.get_list('Design Code', filters={'mood_board': board.name},
        fields=['name', 'design_number', 'image', 'category', 'report_position'],
        order_by='name asc', limit_page_length=MAX_DESIGNS + 1)
    if len(designs) > MAX_DESIGNS:
        frappe.throw('This report supports up to 1,000 designs per Mood Board')
    if not designs:
        frappe.throw('No accessible designs in this Mood Board')
    designs.sort(key=report_sort_key)
    names = [d['name'] for d in designs]
    # Only read milestones belonging to designs already authorized above.
    limit = len(names) * 50 + 1
    plans = frappe.get_all('Design Milestone Plan Entry',
        filters={'design_code': ['in', names]},
        fields=['design_code', 'milestone_type', 'plan_state', 'sequence'],
        order_by='sequence asc, name asc', limit_page_length=limit)
    if len(plans) >= limit:
        frappe.throw('Too many milestone plans for this report')
    grouped = {name: [] for name in names}
    for plan in plans:
        grouped[plan['design_code']].append(plan)
    for design in designs:
        design['report_image'] = safe_image(design.get('image'))
        design['milestone_caption'] = milestone_caption(grouped[design['name']])
    display_name = mood_board_display_name(board.mood_board_name or board.name)
    return {
        'title': display_name,
        'cover_heading': cover_heading(board.year, board.season, board.collection, board.drop, display_name),
        'cover': safe_image(board.image),
        'year': board.year or '',
        'season': board.season or '',
        'collection': board.collection or '',
        'drop': board.drop or '',
        'pages': [designs[i:i + PAGE_SIZE] for i in range(0, len(designs), PAGE_SIZE)],
    }


def report_context(mood_boards=None, year=None, season=None, collection=None):
    filters = {}
    for field, value in (("year", year), ("season", season), ("collection", collection)):
        if value:
            if not isinstance(value, str) or len(value) > 140:
                frappe.throw("Invalid report filter")
            filters[field] = value
    if mood_boards is None:
        mood_boards = []
    if isinstance(mood_boards, str):
        mood_boards = frappe.parse_json(mood_boards)
    if (not isinstance(mood_boards, list) or len(mood_boards) > 20
            or any(not isinstance(name, str) or not name or len(name) > 140 for name in mood_boards)):
        frappe.throw('Select between 1 and 20 Mood Boards')
    if mood_boards:
        filters["name"] = ["in", list(dict.fromkeys(mood_boards))]
    if not filters:
        frappe.throw("Select at least one report filter")
    matches = frappe.get_list("Mood Board", filters=filters, fields=["name"],
        order_by="year asc, season asc, collection asc, name asc", limit_page_length=21)
    if not matches:
        frappe.throw("No accessible Mood Boards match these filters")
    if len(matches) > 20:
        frappe.throw("More than 20 Mood Boards match. Narrow the report filters")
    names = [row["name"] for row in matches]
    if mood_boards:
        allowed = set(names)
        names = [name for name in dict.fromkeys(mood_boards) if name in allowed]
    boards = []
    total = 0
    for name in names:
        context = board_context(name)
        total += sum(len(page) for page in context['pages'])
        if total > MAX_DESIGNS:
            frappe.throw('Select fewer Mood Boards: the report supports up to 1,000 designs')
        boards.append(context)
    boards.sort(key=mood_board_sort_key)
    return {'boards': boards,
        'logo': safe_image(frappe.db.get_single_value('Navbar Settings', 'app_logo'))}


@frappe.whitelist()
def preview(mood_boards=None, year=None, season=None, collection=None):
    return frappe.render_template('templates/design_collection_report.html',
        report_context(mood_boards=mood_boards, year=year, season=season, collection=collection))
