/* Central communication workspace: existing message engine, one view per parent. */
frappe.pages['design-communication-center'].on_page_load = function(wrapper) {
    const page = frappe.ui.make_app_page({parent: wrapper, title: __('Design Communication Center'), single_column: true});
    const call = (method, args) => frappe.call({
        method: 'marina_custom_apps.design_management.discussion_center.' + method, args
    }).then(r => r.message);
    const activity = (method, args) => frappe.call({
        method: 'marina_custom_apps.design_management.discussion_activity.' + method, args
    }).then(r => r.message);

    const root = $('<div class="mdm-center"></div>').appendTo(page.main);
    // Mobile browsers sometimes retain an older app-wide discussion bundle.
    // The central page must use the current embedded messenger implementation.
    const style = $('<style>').text(`
      .mdm-center {color:#2D2926;width:100%;min-width:0}
      .mdm-center .mdm-filters {display:flex;flex-wrap:wrap;gap:10px;align-items:end;padding:12px;background:#F2EBE7;border-radius:8px;margin-bottom:12px}
      .mdm-center .mdm-filter-toggle {display:flex;align-items:center;justify-content:space-between;width:100%;padding:9px 14px;margin-bottom:10px;background:#F2EBE7;border:0;border-radius:8px;color:#551C25;font-weight:600;text-align:left}
      .mdm-center .mdm-filters[hidden] {display:none!important}
      .mdm-center .mdm-sidebar {display:flex!important;flex-direction:column;overflow:hidden!important;padding:0!important}
      .mdm-center .mdm-recent {flex:0 0 auto;max-height:36%;min-height:90px;overflow:auto;border-bottom:1px solid #E4D5C4}
      .mdm-center .mdm-tree {flex:1;min-height:0;overflow-y:auto;padding:10px}
      .mdm-center .mdm-sidebar-heading {font-weight:700;padding:10px 12px;background:#F2EBE7;color:#551C25}
      .mdm-center .mdm-recent-chat {width:100%;display:flex;align-items:center;gap:9px;padding:9px 12px;text-align:left;border:0;border-bottom:1px solid #f5efea;background:#fff}
      .mdm-center .mdm-recent-chat:hover,.mdm-center .mdm-recent-chat.mdm-selected {background:#F2EBE7}
      .mdm-center .mdm-recent-thumb {width:40px;height:40px;object-fit:cover;flex-shrink:0;border-radius:6px;background:#F2EBE7}
      .mdm-center .mdm-recent-info {flex:1;min-width:0}
      .mdm-center .mdm-recent-preview {display:block;overflow:hidden;white-space:nowrap;text-overflow:ellipsis;color:#817572;font-size:11px}
      .mdm-center .mdm-filters label {display:block;font-size:12px;font-weight:600}
      .mdm-center .mdm-filters input {width:165px;max-width:100%}
      .mdm-center .mdm-layout {display:grid!important;grid-template-columns:minmax(240px,30%) minmax(0,70%)!important;gap:12px;width:100%!important;max-width:100%!important;height:calc(100dvh - 235px);min-height:490px;align-items:stretch}
      .mdm-center .mdm-sidebar,.mdm-center .mdm-chat {box-sizing:border-box;border:1px solid #E4D5C4;border-radius:8px;min-width:0!important;min-height:0;background:#fff}
      .mdm-center .mdm-sidebar {display:block;overflow-y:auto;padding:10px}
      .mdm-center .mdm-chat {display:flex!important;flex-direction:column;overflow:hidden;width:auto!important}
      .mdm-center .mdm-header {flex:0 0 auto;z-index:2;padding:12px 14px;background:#fff;border-bottom:1px solid #E4D5C4;display:flex;gap:12px;align-items:center;min-height:94px;min-width:0}
      .mdm-center .mdm-header img {width:68px;height:68px;object-fit:contain;border:1px solid #E4D5C4;border-radius:6px;flex-shrink:0}
      .mdm-center .mdm-header-details {min-width:0;flex:1;display:flex;flex-direction:column;gap:4px}
      .mdm-center .mdm-header-title {font-weight:700;font-size:16px;color:#551C25;overflow-wrap:anywhere;text-decoration:none;display:inline-block;align-self:flex-start}
      .mdm-center .mdm-header-title:hover {color:#551C25;text-decoration:underline}
      .mdm-center .mdm-milestone {font-size:12px;color:#5c5754;line-height:1.4}
      .mdm-center .mdm-completion {font-size:12px;font-weight:600}
      .mdm-center .mdm-conversation {display:block;flex:1;min-height:0;overflow:hidden;padding:0;background:#faf8f7;width:100%}
      .mdm-center .mdm-messenger {display:flex;flex-direction:column;height:100%;min-height:0;min-width:0}
      .mdm-center .mdm-messenger .mdm-message-tools {flex:0 0 auto;padding:7px 12px;margin:0!important;background:#fff}
      .mdm-center .mdm-messenger [role="status"] {flex:0 0 auto;padding:0 12px;margin:0!important}
      .mdm-center .mdm-messenger .mdm-message-list {flex:1;min-height:0;overflow-y:auto;padding:14px 16px;display:flex;flex-direction:column;gap:8px}
      .mdm-center .mdm-messenger .mdm-bubble {position:relative;display:flex;align-items:flex-start;gap:10px;width:100%;max-width:100%;min-width:0;border:0!important;border-radius:0!important;background:transparent!important;box-shadow:none!important;padding:5px 8px!important;margin:0 0 10px!important;overflow-wrap:anywhere}
      .mdm-center .mdm-messenger .mdm-bubble.mdm-own {align-self:auto;background:transparent!important}
      .mdm-center .mdm-message-avatar {width:38px;height:38px;flex:0 0 38px;display:flex;align-items:center;justify-content:center;border-radius:50%;background:#F2EBE7;color:#551C25;font-weight:700;overflow:hidden}
      .mdm-center .mdm-message-avatar img {width:100%;height:100%;object-fit:cover}
      .mdm-center .mdm-message-content {position:relative;flex:1;min-width:0;padding:2px 33px 0 0;background:transparent}
      .mdm-center .mdm-message-heading {display:flex;gap:10px;align-items:center;flex-wrap:wrap;margin-bottom:4px}
      .mdm-center .mdm-message-heading strong {color:#551C25;font-size:13px}
      .mdm-center .mdm-message-heading small {color:#8b8580;font-size:11px}
      .mdm-center .mdm-message-menu-trigger {position:absolute;right:0;top:0;border:0;background:transparent;color:#6c625d;border-radius:6px;font-size:20px;width:28px;height:28px;opacity:0}
      .mdm-center .mdm-bubble:hover .mdm-message-menu-trigger,.mdm-center .mdm-message-menu-trigger:focus-visible {opacity:1}
      .mdm-center .mdm-message-actions {display:none;position:absolute;right:0;top:30px;z-index:8;background:white;padding:5px;border:1px solid #E4D5C4;border-radius:8px;box-shadow:0 6px 18px #0002;min-width:130px}
      .mdm-center .mdm-message-actions.mdm-actions-open {display:flex;flex-direction:column;gap:2px}
      .mdm-center .mdm-message-actions button {width:100%;border:0;background:transparent;text-align:left;padding:8px 10px}
      .mdm-center .mdm-message-actions button:hover {background:#F2EBE7}
      .mdm-center .mdm-system-message .mdm-message-content {background:#F2EBE7;border-left:3px solid #551C25;border-radius:6px;padding:10px 35px 10px 12px}
      .mdm-center .mdm-system-message .mdm-message-menu-trigger {top:8px;right:8px}
      .mdm-center .mdm-messenger .mdm-composer {flex:0 0 auto;margin:0!important;border:0!important;border-top:1px solid #E4D5C4!important;background:#fff;display:grid;grid-template-columns:42px minmax(0,1fr) auto;gap:8px;align-items:center;padding:10px!important;border-radius:0!important;position:relative}
      .mdm-center .mdm-messenger .mdm-composer textarea {grid-column:2;grid-row:1;border-radius:22px;resize:none;min-height:42px;height:44px;max-height:100px;align-self:center;padding:10px 14px}
      .mdm-center .mdm-messenger .mdm-composer .mdm-attach {grid-column:1;grid-row:1;font-size:24px;border:0;background:#F2EBE7;color:#551C25;border-radius:50%;width:40px;height:40px;padding:0;margin:0}
      .mdm-center .mdm-messenger .mdm-composer > .btn-primary {grid-column:3;grid-row:1;border-radius:22px;background:#551C25;border-color:#551C25;padding:10px 16px;margin:0}
      .mdm-center .mdm-messenger .mdm-composer input[type=file] {position:absolute;width:1px;height:1px;opacity:0;pointer-events:none}
      .mdm-center .mdm-messenger .mdm-composer .mdm-file-name,.mdm-center .mdm-messenger .mdm-composer .mdm-mention-suggestions,.mdm-center .mdm-messenger .mdm-composer .mb-2 {grid-column:1/-1}
      .mdm-center .mdm-messenger .mdm-composer > .small.text-muted:not(.mdm-file-name) {display:none}
      .mdm-center .mdm-mention-suggestions {display:flex;flex-wrap:wrap;gap:4px;max-height:130px;overflow-y:auto}
      .mdm-center .mdm-mention-suggestions .btn {border-radius:18px}
      .mdm-center .mdm-back {display:none}
      .mdm-center .mdm-board,.mdm-center .mdm-design {width:100%;text-align:left;display:block;border:0;background:transparent;padding:9px;border-radius:5px;color:#2D2926;overflow-wrap:anywhere}
      .mdm-center .mdm-board {font-weight:600;background:#F2EBE7;margin-top:5px}
      .mdm-center .mdm-design {padding-left:26px;display:flex;align-items:center;justify-content:space-between;gap:8px}
      .mdm-center .mdm-design-name {min-width:0;overflow-wrap:anywhere}
      .mdm-center .mdm-unread {background:#551C25;color:#fff;border-radius:999px;padding:2px 7px;font-size:11px;font-weight:700;min-width:21px;text-align:center;flex:0 0 auto}
      .mdm-center .mdm-board:hover,.mdm-center .mdm-design:hover,.mdm-center .mdm-selected {background:#E4D5C4}
      .mdm-center .mdm-progress {height:6px;background:#E4D5C4;border-radius:8px;overflow:hidden;margin-top:2px;width:220px;max-width:100%}
      .mdm-center .mdm-progress span {height:100%;display:block;background:#551C25}
      @media(max-width:760px) {
        .mdm-center .mdm-filters {padding:8px;gap:6px}
        .mdm-center .mdm-filters input {width:135px}
        .mdm-center .mdm-layout {display:block!important;height:calc(100dvh - 205px)!important;min-height:0!important;overflow:hidden}
        /* A conversation occupies the mobile viewport, independently of Desk's chrome. */
        .mdm-center.mdm-mobile-chat .mdm-layout {position:fixed!important;inset:0!important;width:100vw!important;max-width:100vw!important;height:100dvh!important;min-height:0!important;z-index:1040;background:#fff;padding:0;margin:0;border:0;border-radius:0;overflow:hidden}
        .mdm-center.mdm-mobile-chat .mdm-chat {display:flex!important;height:100%!important;min-height:0!important;overflow:hidden!important;border:0!important;border-radius:0!important}
        .mdm-center.mdm-mobile-chat .mdm-header {flex-shrink:0;padding-top:max(10px, env(safe-area-inset-top));box-shadow:0 1px 3px #0000000d}
        .mdm-center.mdm-mobile-chat .mdm-messenger {min-height:0!important;height:100%!important;display:flex!important;flex-direction:column!important}
        .mdm-center.mdm-mobile-chat .mdm-composer {padding-bottom:max(12px, env(safe-area-inset-bottom))!important}
        .mdm-center.mdm-mobile-chat .mdm-message-tools {display:flex;align-items:center;min-height:38px}
        body.mdm-center-chat-open {overflow:hidden!important}
        .mdm-center.mdm-mobile-chat .mdm-messenger > p {display:none!important}
        .mdm-center .mdm-chat,.mdm-center .mdm-sidebar {box-sizing:border-box;min-height:0!important}
        .mdm-center .mdm-conversation {display:flex!important;flex-direction:column;min-height:0!important;overflow:hidden!important}
        .mdm-center .mdm-conversation.mdm-messenger {height:100%!important}
        .mdm-center .mdm-message-list {overflow-y:auto!important;min-height:0!important;flex:1 1 auto!important}
        .mdm-center .mdm-composer {flex:0 0 auto!important;position:relative!important;padding-bottom:max(9px,env(safe-area-inset-bottom))!important}
        .mdm-center .mdm-message-tools {padding:4px 9px!important}
        .mdm-center .mdm-messenger .mdm-composer textarea {height:42px!important;min-height:42px!important;font-size:16px!important}
        .mdm-center .mdm-header-details {overflow:hidden}
        .mdm-center .mdm-milestone {display:-webkit-box;-webkit-line-clamp:2;-webkit-box-orient:vertical;overflow:hidden}
        .mdm-center .mdm-filter-toggle {margin-bottom:8px}
        .mdm-center .mdm-sidebar {height:100%;max-height:none}
        .mdm-center .mdm-recent {max-height:38%}
        .mdm-center .mdm-chat {display:none!important;height:100%;width:100%!important}
        .mdm-center.mdm-mobile-chat .mdm-sidebar {display:none!important}
        .mdm-center.mdm-mobile-chat .mdm-chat {display:flex!important}
        .mdm-center .mdm-back {display:inline-flex;align-items:center;justify-content:center;flex:0 0 36px;font-size:24px;margin-right:1px;border:0;background:transparent;color:#551C25}
        .mdm-center .mdm-header {padding:8px;gap:8px;min-height:78px}
        .mdm-center .mdm-header img {width:50px;height:50px}
        .mdm-center .mdm-header-title {font-size:14px}
        .mdm-center .mdm-milestone,.mdm-center .mdm-completion {font-size:11px}
        .mdm-center .mdm-progress {height:4px;width:150px}
        .mdm-center .mdm-messenger .mdm-bubble {max-width:100%}
        .mdm-center .mdm-message-avatar {width:32px;height:32px;flex-basis:32px}
        .mdm-center .mdm-message-menu-trigger {opacity:1}
        .mdm-center .mdm-messenger .mdm-message-list {padding:10px}
      }
    `).appendTo(root);
    const filterToggle = $('<button type="button" class="mdm-filter-toggle" aria-expanded="false"></button>').text(__('Filters') + ' ▾').appendTo(root);
    const filters = $('<div class="mdm-filters" hidden></div>').appendTo(root);
    filterToggle.on('click', () => { const open = filters.is('[hidden]'); filters.prop('hidden', !open); filterToggle.attr('aria-expanded', String(open)).text(__('Filters') + (open ? ' ▴' : ' ▾')); });
    const inputs = {};
    [['year','Year'],['season','Season'],['collection','Collection'],['design_code','Design Code']].forEach(([key,label]) => {
        const group = $('<div></div>').appendTo(filters);
        $('<label></label>').text(__(label)).appendTo(group);
        inputs[key] = $('<input type="text" class="form-control input-sm">').attr('placeholder', __(label)).appendTo(group);
    });
    const reset = $('<button type="button" class="btn btn-default btn-sm"></button>').text(__('Clear All')).appendTo(filters);
    const layout = $('<div class="mdm-layout"></div>').appendTo(root);
    const sidebar = $('<aside class="mdm-sidebar" aria-label="Mood Boards and Design Codes"></aside>').appendTo(layout);
    const recentSection = $('<section class="mdm-recent"></section>').appendTo(sidebar);
    $('<div class="mdm-sidebar-heading"></div>').text(__('Recent Chats')).appendTo(recentSection);
    const recentList = $('<div></div>').appendTo(recentSection);
    const treeSection = $('<section class="mdm-tree"></section>').appendTo(sidebar);
    $('<div class="mdm-sidebar-heading"></div>').text(__('Designs & Mood Boards')).appendTo(treeSection);
    const tree = $('<div></div>').appendTo(treeSection);
    const chat = $('<section class="mdm-chat"></section>').appendTo(layout);
    const header = $('<div class="mdm-header"></div>').appendTo(chat);
    const back = $('<button type="button" class="btn btn-default btn-sm mdm-back" aria-label="Back to conversations">‹</button>').appendTo(header);
    back.on('click', () => {
        root.removeClass('mdm-mobile-chat');
        $('body').removeClass('mdm-center-chat-open');
    });
    const conversation = $('<div class="mdm-conversation"></div>').appendTo(chat);
    let boardGeneration = 0, selectionGeneration = 0, selected = null, dispose = null, boardOffset = 0, currentFocus = null;
    const boardsShown = new Set();
    const filtersValue = () => Object.fromEntries(Object.entries(inputs).map(([k,v]) => [k, v.val().trim()]));
    const button = (label, container, className) =>
        $('<button type="button"></button>').addClass(className).text(__(label)).appendTo(container);
    let scriptPromise = null;
    async function ensureDiscussionScript() {
        // The normal Desk bundle may retain an older renderer in mobile Safari.
        // Load the Communication Center's dedicated, uniquely named asset.
        if (window.marina?.centerMessenger?.mount?.mdmMessengerVersion === 4) return;
        if (!scriptPromise) {
            scriptPromise = frappe.require('/assets/marina_custom_apps/js/marina_center_messenger_v4.js')
                .catch(error => { scriptPromise = null; throw error; });
        }
        await scriptPromise;
        if (window.marina?.centerMessenger?.mount?.mdmMessengerVersion !== 4) {
            scriptPromise = null;
            throw new Error('The Communication Center asset is missing. Please check Frappe asset build and refresh.');
        }
    }
    async function bounded(operation, timeoutMs = 12000) {
        let timeout;
        try {
            return await Promise.race([
                operation,
                new Promise((_, reject) => {
                    timeout = setTimeout(() => reject(new Error('Chat loading timed out. Try again or reload the page.')), timeoutMs);
                })
            ]);
        } finally { clearTimeout(timeout); }
    }
    async function select(doctype, name, focus) {
        const token = ++selectionGeneration;
        try {
            const info = await bounded(call('context', {reference_doctype: doctype, reference_name: name}));
            if (token !== selectionGeneration) return;
            await bounded(ensureDiscussionScript());
            if (token !== selectionGeneration) return;
            if (dispose) dispose();
            dispose = null;
            selected = {doctype, name};
            currentFocus = focus || null;
            sidebar.find('.mdm-selected').removeClass('mdm-selected');
            sidebar.find('button').filter((i,e) => e.dataset.doctype === doctype && e.dataset.name === name).addClass('mdm-selected');
            header.contents().not(back).remove();
            root.addClass('mdm-mobile-chat');
            if (window.matchMedia('(max-width:760px)').matches) $('body').addClass('mdm-center-chat-open');
            if (info.image) $('<img alt="">').attr('src', info.image).appendTo(header);
            const details = $('<div class="mdm-header-details"></div>').appendTo(header);
            $('<a class="mdm-header-title" title="Open document in new tab"></a>')
                .attr('href', frappe.utils.get_form_link(doctype, name))
                .attr('target', '_blank')
                .attr('rel', 'noopener noreferrer')
                .text(name).appendTo(details);
            if (doctype === 'Design Code') {
                $('<div class="mdm-milestone"></div>').text(__('Current Milestone') + ': ' + (info.current_milestones.join(', ') || __('None'))).appendTo(details);
                const percent = Math.max(0, Math.min(100, Number(info.completion_percent) || 0));
                $('<div class="mdm-completion"></div>').text(__('Completion') + ': ' + percent + '%').appendTo(details);
                $('<div class="mdm-progress"></div>').append($('<span></span>').css('width', percent + '%')).appendTo(details);
            } else {
                $('<div class="mdm-milestone"></div>').text(__('Mood Board Discussion')).appendTo(details);
            }
            conversation.empty();
            if (window.marina?.centerMessenger?.mount?.mdmMessengerVersion !== 4) {
                throw new Error('The up-to-date chat component is not available.');
            }
            dispose = marina.centerMessenger.mount(conversation, doctype, name, focus || null, unread => {
                const item = sidebar.find('.mdm-design').filter((i,e) => e.dataset.doctype === doctype && e.dataset.name === name);
                item.find('.mdm-unread').remove();
                if (unread > 0) $('<span class="mdm-unread"></span>').text(unread > 99 ? '99+' : unread).appendTo(item);
                refreshRecent();
            });
        } catch(e) {
            if (token === selectionGeneration) {
                console.error('Design Communication Center failed to open discussion', e);
                frappe.msgprint({title: __('Unable to open discussion'), message: $('<div>').text(e.message || __('Check permissions and retry.')).html(), indicator: 'red'});
            }
        }
    }
    async function addDesigns(board, container, append) {
        const offset = append ? Number(container.data('offset') || 0) : 0;
        const version = container.data('version') || 0;
        const data = await call('designs', {mood_board: board, design_code: filtersValue().design_code, offset});
        if (version !== container.data('version')) return;
        if (!append) container.empty();
        data.rows.forEach(row => {
            const b = button('', container, 'mdm-design');
            $('<span class="mdm-design-name"></span>').text(row.design_number || row.name).appendTo(b);
            if (row.unread > 0) $('<span class="mdm-unread"></span>').text(row.unread > 99 ? '99+' : row.unread).appendTo(b);
            b[0].dataset.doctype = 'Design Code'; b[0].dataset.name = row.name;
            b.on('click', () => select('Design Code', row.name));
        });
        container.data('offset', offset + data.rows.length);
        if (data.has_more) button('More designs…', container, 'mdm-design text-muted').on('click', function() {
            $(this).remove(); addDesigns(board, container, true);
        });
    }
    async function loadBoards(append) {
        const token = ++boardGeneration;
        const offset = append ? boardOffset : 0;
        try {
            const data = await call('boards', {...filtersValue(), offset});
            if (token !== boardGeneration) return;
            if (!append) { tree.empty(); boardOffset = 0; boardsShown.clear(); }
            data.rows.forEach(board => {
                if (boardsShown.has(board.name)) return;
                boardsShown.add(board.name);
                const node = $('<div></div>').appendTo(tree);
                const toggle = button('▸ ' + board.name, node, 'mdm-board');
                const children = $('<div></div>').hide().appendTo(node).data('version', 0);
                toggle[0].dataset.doctype = 'Mood Board'; toggle[0].dataset.name = board.name;
                let expanded = false, loaded = false;
                toggle.on('click', async () => {
                    expanded = !expanded;
                    children.toggle(expanded);
                    toggle.text((expanded ? '▾ ' : '▸ ') + board.name);
                    if (expanded && !loaded) {
                        loaded = true;
                        children.data('version', children.data('version') + 1);
                        try {
                            const boardChat = button(__('Mood Board Chat'), children, 'mdm-design');
                            boardChat[0].dataset.doctype = 'Mood Board'; boardChat[0].dataset.name = board.name;
                            boardChat.on('click', () => select('Mood Board', board.name));
                            const designsHolder = $('<div></div>').appendTo(children).data('version', 1);
                            await addDesigns(board.name, designsHolder, false);
                        } catch(e) { loaded = false; children.empty().text(__('Could not load designs. Collapse and retry.')); }
                    }
                });
            });
            boardOffset = offset + data.rows.length;
            if (!data.rows.length && !append) $('<div class="text-muted p-2"></div>').text(__('No accessible Mood Boards match the filters.')).appendTo(tree);
            if (data.has_more) button('More Mood Boards…', tree, 'btn btn-default btn-sm').on('click', function() {
                $(this).remove(); loadBoards(true);
            });
        } catch(e) {
            if (token === boardGeneration) tree.empty().text(__('Unable to load conversations.'));
        }
    }
    let recentGeneration = 0;
    async function refreshRecent() {
        const token = ++recentGeneration;
        try {
            const data = await activity('inbox', {view:'All', offset:0});
            if (token !== recentGeneration) return;
            recentList.empty();
            data.rows.forEach(row => {
                const item = $('<button type="button" class="mdm-recent-chat"></button>').appendTo(recentList);
                item[0].dataset.doctype = row.reference_doctype; item[0].dataset.name = row.reference_name;
                if (row.image) $('<img class="mdm-recent-thumb" alt="">').attr('src',row.image).appendTo(item);
                const info = $('<span class="mdm-recent-info"></span>').appendTo(item);
                $('<strong></strong>').text(row.reference_name).appendTo(info);
                $('<span class="mdm-recent-preview"></span>').text(row.preview || __(row.reference_doctype)).appendTo(info);
                if (row.unread) $('<span class="mdm-unread"></span>').text(row.unread > 99 ? '99+' : row.unread).appendTo(item);
                item.on('click', () => select(row.reference_doctype, row.reference_name));
            });
            if (!data.rows.length) recentList.text(__('No recent conversations.'));
        } catch(error) { console.error('Recent chats failed',error); }
    }
    if (frappe.realtime?.on) frappe.realtime.on('marina_discussion_changed', refreshRecent);
    let debounce;
    Object.values(inputs).forEach(input => input.on('input', () => {
        clearTimeout(debounce); debounce = setTimeout(() => loadBoards(false), 300);
    }));
    reset.on('click', () => { Object.values(inputs).forEach(i => i.val('')); loadBoards(false); });
    page.set_secondary_action(__('Refresh'), () => {
        loadBoards(false);
        if (selected) select(selected.doctype, selected.name, currentFocus);
    });
    wrapper.open_discussion_link = async () => {
        const message = new URLSearchParams(window.location.search).get('message') || frappe.route_options?.message;
        if (message) {
            try {
                const target = await activity('locate', {message});
                await select(target.reference_doctype, target.reference_name, target.message);
            } catch(e) { frappe.msgprint(__('This message is unavailable or you no longer have access.')); }
        } else if (frappe.route_options?.reference_doctype && frappe.route_options?.reference_name) {
            await select(frappe.route_options.reference_doctype, frappe.route_options.reference_name);
        }
    };
    wrapper.refresh_discussions = () => { loadBoards(false); refreshRecent(); };
    wrapper.dispose_discussion = () => { clearTimeout(debounce); if (dispose) dispose(); $('body').removeClass('mdm-center-chat-open'); };
    $('<span class="mdm-empty-heading"></span>').text(__('Select a Mood Board or Design Code to open its conversation.')).appendTo(header);
    loadBoards(false); refreshRecent();
    wrapper.open_discussion_link();
};
frappe.pages['design-communication-center'].on_page_hide = function(wrapper) {
    $('body').removeClass('mdm-center-chat-open');
};
frappe.pages['design-communication-center'].on_page_show = function(wrapper) {
    if (wrapper.refresh_discussions) wrapper.refresh_discussions();
    if (wrapper.open_discussion_link) wrapper.open_discussion_link();
};
