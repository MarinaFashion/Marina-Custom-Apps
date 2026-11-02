"""Standard report shell around the shared permission-scoped visual report."""
from html import escape

import frappe
from marina_custom_apps.design_management.collection_report import report_context


def execute(filters=None):
    filters = filters or {}
    columns = [
        {'fieldname': 'design_code', 'label': 'Design Code', 'fieldtype': 'Link', 'options': 'Design Code', 'width': 160},
        {'fieldname': 'mood_board', 'label': 'Mood Board', 'fieldtype': 'Data', 'width': 220},
        {'fieldname': 'milestones', 'label': 'Current Milestones', 'fieldtype': 'Data', 'width': 350},
    ]
    selected = {key: filters.get(key) for key in ('year', 'season', 'collection', 'mood_boards')}
    if not any(selected.values()):
        return columns, [], 'Select Year, Season, Collection or Mood Board above, then click Run Report.'
    context = report_context(**selected)
    html = frappe.render_template('templates/design_collection_report.html', context)
    message = ('<iframe class="marina-mood-board-preview" title="Mood Board Overview" '
               'style="width:100%;height:78vh;border:0;display:block" srcdoc="' + escape(html, quote=True) + '"></iframe>')
    # Keep real rows for standard export; show the visual report on screen.
    rows = [{'design_code': design['name'], 'mood_board': board['title'],
             'milestones': design['milestone_caption']}
            for board in context['boards'] for page in board['pages'] for design in page]
    return columns, rows, message
