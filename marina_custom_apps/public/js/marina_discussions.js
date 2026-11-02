/* Shared record-scoped discussion panel. Text is always rendered as text. */
(() => {
    const api = 'marina_custom_apps.design_management.discussions.';
    const call = (method, args) => frappe.call({method: api + method, args}).then(r => r.message);
    const activity = (method, args) => frappe.call({method: 'marina_custom_apps.design_management.discussion_activity.' + method, args}).then(r => r.message);
    const button = label => $('<button type="button" class="btn btn-default btn-sm"></button>').text(__(label));
    const requestId = () => Array.from(crypto.getRandomValues(new Uint8Array(16)), x => x.toString(16).padStart(2, '0')).join('');

    // Small, self-contained presentation layer; no new backend queries or files.
    // Filenames are always added as text, never interpreted as HTML.
    const fileTypes = {
        pdf: ['PDF', '#d9414c'],
        doc: ['W', '#286ac4'], docx: ['W', '#286ac4'],
        xls: ['X', '#217346'], xlsx: ['X', '#217346'], csv: ['CSV', '#217346'],
        ppt: ['P', '#c85838'], pptx: ['P', '#c85838'],
        zip: ['ZIP', '#776b81'], rar: ['ZIP', '#776b81'],
        psd: ['Ps', '#345d9f'], ai: ['Ai', '#bd6d20'], eps: ['EPS', '#bd6d20'],
        mp4: ['▶', '#7954a1'], mov: ['▶', '#7954a1'],
        png: ['IMG', '#4b8291'], jpg: ['IMG', '#4b8291'],
        jpeg: ['IMG', '#4b8291'], webp: ['IMG', '#4b8291'],
        tif: ['IMG', '#4b8291'], tiff: ['IMG', '#4b8291'],
        txt: ['TXT', '#6a7686']
    };
    function ensureAttachmentStyles() {
        if (document.getElementById('mdm-file-card-styles')) return;
        $('<style id="mdm-file-card-styles"></style>').text(`
            .mdm-file-card {display:flex;align-items:center;gap:14px;width:340px;max-width:100%;
                min-width:0;padding:12px 13px;margin-top:8px;background:#fff;border:1px solid #E4D5C4;
                border-radius:10px;color:#2D2926!important;text-decoration:none!important;
                box-shadow:0 1px 3px #2d29260a;box-sizing:border-box}
            a.mdm-file-card:hover,a.mdm-file-card:focus-visible {background:#faf6f3;
                border-color:#C0A392;text-decoration:none!important;outline-offset:2px}
            .mdm-file-card-text {display:flex;flex:1;min-width:0;flex-direction:column;gap:5px}
            .mdm-file-card-name {font-size:13px;line-height:1.4;font-weight:600;color:#2D2926;
                white-space:normal;overflow-wrap:anywhere;word-break:break-word}
            .mdm-file-card-detail {color:#80736d;font-size:11px;line-height:1.4;overflow-wrap:anywhere}
            .mdm-file-card-icon {display:flex;position:relative;flex:0 0 44px;width:44px;height:49px;
                align-items:flex-end;justify-content:center;padding:0 3px 9px;box-sizing:border-box;
                border-radius:5px;background:var(--mdm-icon-bg,#728095);color:#fff;overflow:hidden;
                font-size:12px;line-height:1;font-weight:800;letter-spacing:.1px}
            .mdm-file-card-icon:after {content:"";position:absolute;right:0;top:0;width:0;height:0;
                border-left:12px solid #ffffffb3;border-bottom:12px solid transparent}
            .mdm-file-card--expired {opacity:.72;background:#f8f7f6;border-style:dashed;cursor:default}
            .mdm-file-card--expired .mdm-file-card-icon {filter:grayscale(1)}
            .mdm-file-image-only {display:inline-block;max-width:100%;margin-top:8px}
            .mdm-file-image-only img {display:block;max-width:100%;width:260px;max-height:260px;
                object-fit:contain;border-radius:8px}
            @media(max-width:760px) {
                .mdm-file-card {width:320px;max-width:100%;padding:10px 11px;gap:11px}
                .mdm-file-card-icon {width:40px;flex-basis:40px;height:45px}
            }
        `).appendTo('head');
    }
    function fileCard(message, target, isExpired, imageWithoutName = false) {
        const extension = String(message.attachment_name || '').split('.').pop().toLowerCase();
        const [label, background] = fileTypes[extension] || ['FILE', '#68788a'];
        const card = $(isExpired
            ? '<div class="mdm-file-card mdm-file-card--expired" role="status"></div>'
            : '<a class="mdm-file-card"></a>'
        ).appendTo(target);
        if (!isExpired) card.attr({href: message.attachment_url,
            download: message.attachment_name || 'attachment'});
        const info = $('<span class="mdm-file-card-text"></span>').appendTo(card);
        $('<span class="mdm-file-card-name"></span>')
            .text(imageWithoutName
                ? (isExpired ? __('Image expired') : __('Download large image'))
                : (message.attachment_name || __('Attachment')))
            .appendTo(info);
        const bytes = Number(message.attachment_size) || 0;
        if (bytes > 0) $('<span class="mdm-file-card-detail"></span>')
            .text((bytes / (1024 * 1024)).toFixed(1) + ' MB')
            .appendTo(info);
        if (isExpired) {
            $('<span class="mdm-file-card-detail"></span>')
                .text(__('Expired — file no longer available')).appendTo(info);
        } else if (message.attachment_expires_on) {
            const days = Math.max(1, Math.ceil(
                (Number(message.attachment_seconds_remaining) || 0) / 86400
            ));
            $('<span class="mdm-file-card-detail"></span>')
                .text(__('Expires in {0} days', [days]))
                .attr('title', __('Expires: {0}', [
                    frappe.datetime.str_to_user(message.attachment_expires_on)
                ])).appendTo(info);
        }
        $('<span class="mdm-file-card-icon" aria-hidden="true"></span>')
            .css('--mdm-icon-bg', background).text(label).appendTo(card);
        if (!isExpired) card.attr('aria-label', __('Download attachment: {0}', [
            message.attachment_name || __('Attachment')
        ]));
    }

    function mount(wrapper, doctype, name, focus = null, onUnread = () => {}) {
        ensureAttachmentStyles();
        const root = $(wrapper).empty();
        const embedded = root.hasClass('mdm-conversation');
        if (embedded) root.addClass('mdm-messenger');
        const instance = requestId();
        root.data('discussion-instance', instance);
        if (!embedded) root.append($('<p class="text-muted"></p>').text(__('Discussion attachments are not published milestone evidence.')));
        const toolbar = $('<div class="mb-3 d-flex" style="gap:8px"></div>').appendTo(root);
        const refresh = button('Refresh').appendTo(toolbar);
        const unreadBadge = $('<span class="badge badge-warning align-self-center"></span>').appendTo(toolbar).hide();
        const older = button('Load earlier messages').appendTo(toolbar).hide();
        const status = $('<div role="status" class="text-muted mb-2"></div>').appendTo(root);
        const list = $('<div aria-label="Discussion messages"></div>').appendTo(root);
        const compose = $('<div class="border rounded p-3 mt-3"></div>').appendTo(root);
        if (embedded) { toolbar.addClass('mdm-message-tools'); list.addClass('mdm-message-list'); compose.addClass('mdm-composer'); }
        const replyLabel = $('<div class="mb-2"></div>').appendTo(compose).hide();
        const mentionChips = $('<div class="mb-2 d-flex" style="gap:6px;flex-wrap:wrap"></div>').appendTo(compose);
        const selectedMentions = new Map();
        const text = $('<textarea class="form-control" rows="2" maxlength="10000"></textarea>')
            .attr('placeholder', __('Write a message…')).attr('aria-label', __('Message')).appendTo(compose);
        const file = $('<input type="file" class="mt-2 mb-2">').attr('accept', '.jpg,.jpeg,.png,.webp,.pdf,.txt,.csv,.docx,.xlsx,.pptx,.zip,.psd,.ai,.eps,.tif,.tiff,.mp4,.mov')
            .attr('aria-label', __('Attach a file')).appendTo(compose);
        const help = $('<div class="small text-muted mb-2"></div>')
            .text(__('Large chat attachments may expire; checking current retention settings…'))
            .appendTo(compose);
        const attach = button('+').attr({'aria-label': __('Attach file'), 'title': __('Attach file')}).addClass('mdm-attach').appendTo(compose);
        attach.on('click', () => file.trigger('click'));
        const fileLabel = $('<span class="small text-muted mdm-file-name"></span>').appendTo(compose);
        file.on('change', () => fileLabel.text(file[0].files[0]?.name || ''));
        const send = button('Send').removeClass('btn-default').addClass('btn-primary').appendTo(compose);
        let cursor = null, busy = false, posting = false, replyTo = null, id = requestId();
        let browsingEarlier = !!focus, lastResult = null, displayed = [];
        const acknowledged = new Set();
        const initialFocus = focus;
        let pendingFocus = focus;
        const updateUnread = n => { unreadBadge.text(n + ' ' + __('unread')).toggle(n > 0); onUnread(n); };
        async function acknowledge() {
            if (document.hidden || !root.is(':visible')) return;
            const pending = displayed.filter(name => !acknowledged.has(name));
            const data = pending.length ? await activity('mark_read', {...params, names: JSON.stringify(pending)}) : await activity('count', params);
            pending.forEach(name => acknowledged.add(name));
            updateUnread(data.unread);
        }
        const params = {reference_doctype: doctype, reference_name: name};
        const resetId = () => { id = requestId(); };
        text.on('input', resetId); file.on('change', resetId);
        const mentionButton = button('@ Mention').addClass('ml-2').appendTo(compose);
        if (embedded) mentionButton.hide();
        function drawMentions() {
            mentionChips.empty();
            selectedMentions.forEach((label, user) => {
                button('@' + label + ' ×').appendTo(mentionChips).on('click', () => {
                    if (posting) return;
                    selectedMentions.delete(user); resetId(); drawMentions();
                });
            });
        }
        function chooseMention() {
            if (posting) return;
            const dialog = new frappe.ui.Dialog({title: __('Mention a colleague'), fields: [
                {fieldname: 'search', fieldtype: 'Data', label: __('Search username')},
                {fieldname: 'results', fieldtype: 'HTML'}
            ]});
            const results = dialog.fields_dict.results.$wrapper;
            let generation = 0, timer;
            const search = async () => {
                const current = ++generation;
                const rows = await activity('mention_candidates', {...params, query: dialog.get_value('search') || ''});
                if (current !== generation) return;
                results.empty();
                rows.forEach(row => button('@' + row.label).addClass('m-1').appendTo(results).on('click', () => {
                    if (selectedMentions.size >= 10 && !selectedMentions.has(row.value)) { frappe.msgprint(__('Mention up to 10 colleagues per message.')); return; }
                    selectedMentions.set(row.value, row.label); resetId(); drawMentions(); dialog.hide(); text.trigger('focus');
                }));
                if (!rows.length) results.text(__('No matching colleagues with access to this record.'));
            };
            dialog.fields_dict.search.$input.on('input', () => { clearTimeout(timer); generation++; timer = setTimeout(search, 250); });
            dialog.$wrapper.one('hidden.bs.modal', () => { clearTimeout(timer); generation++; });
            dialog.show(); search();
        }
        mentionButton.on('click', chooseMention);
        if (embedded) {
            const suggestions = $('<div class="mdm-mention-suggestions"></div>').hide().appendTo(compose);
            let lookupTimer, generation = 0;
            text.on('input', () => {
                clearTimeout(lookupTimer);
                const current = ++generation;
                const position = text[0].selectionStart;
                const match = text.val().slice(0, position).match(/(?:^|\s)@([\w.-]{0,40})$/);
                if (!match) { suggestions.empty().hide(); return; }
                lookupTimer = setTimeout(async () => {
                    try {
                        const users = await activity('mention_candidates', {...params, query: match[1]});
                        if (current !== generation) return;
                        suggestions.empty();
                        users.forEach(user => button('@' + user.label).appendTo(suggestions).on('click', () => {
                            if (selectedMentions.size >= 10 && !selectedMentions.has(user.value)) {
                                frappe.msgprint(__('Mention up to 10 colleagues per message.')); return;
                            }
                            const field = text[0], end = field.selectionStart, start = end - match[1].length - 1;
                            text.val(text.val().slice(0, start) + '@' + user.label + ' ' + text.val().slice(end));
                            selectedMentions.set(user.value, user.label);
                            resetId(); drawMentions(); suggestions.empty().hide(); text.trigger('focus');
                        }));
                        suggestions.toggle(users.length > 0);
                    } catch (error) { console.error('Mention lookup failed', error); suggestions.empty().hide(); }
                }, 250);
            });
            text.on('keydown', event => {
                if (event.key === 'Enter' && !event.shiftKey && !suggestions.is(':visible')) {
                    event.preventDefault(); send.trigger('click');
                }
            });
        } else {
            text.on('keydown', event => {
                const position = text[0].selectionStart;
                if (event.key === '@' && (position === 0 || /\s/.test(text.val()[position-1]))) {
                    event.preventDefault(); chooseMention();
                }
            });
        }
        function setReply(message) {
            replyTo = message ? message.name : null;
            resetId(); replyLabel.empty().toggle(!!message);
            if (message) {
                $('<span></span>').text(__('Replying to {0}: {1}', [message.owner, (message.body || message.attachment_name || '').slice(0, 100)])).appendTo(replyLabel);
                button('Cancel reply').addClass('ml-2').appendTo(replyLabel).on('click', () => setReply(null));
                text.trigger('focus');
            }
        }
        function render(message, quotes) {
            const item = $('<article class="border rounded p-3 mb-2"></article>');
            const contentBox = embedded ? $('<div class="mdm-message-content"></div>').appendTo(item) : item;
            if (embedded) {
                const avatar = $('<span class="mdm-message-avatar"></span>').prependTo(item);
                if (message.owner_image && /^(\/files\/|\/private\/files\/)/.test(message.owner_image)) {
                    $('<img alt="">').attr('src', message.owner_image).appendTo(avatar);
                } else $('<span></span>').text(message.is_system ? 'M' : (message.owner_label || '?').slice(0,1).toUpperCase()).appendTo(avatar);
            }
            if (embedded) item.addClass('mdm-bubble').toggleClass('mdm-own', message.owner === frappe.session.user && !message.is_system);
            item.attr('data-message', message.name);
            if (message.name === initialFocus) item.addClass('border-primary');
            if (message.is_system) item.addClass('mdm-system-message');
            const messageHeading = $('<div class="mdm-message-heading"></div>').appendTo(contentBox);
            $('<strong></strong>').text(message.is_system ? __('System – Milestone Update') : (message.owner_label || message.owner)).appendTo(messageHeading);
            $('<small></small>').text(frappe.datetime.str_to_user(message.creation) + (message.revision ? ' · ' + __('Edited') : '')).appendTo(messageHeading);
            if (!message.is_removed && message.mentions && message.mentions.length) $('<div class="small mb-2" style="color:#551C25"></div>').text(message.mentions.map(user => '@' + ((message.mention_labels || {})[user] || user)).join(' ')).appendTo(contentBox);
            if (message.reply_to && quotes[message.reply_to]) {
                const quote = quotes[message.reply_to];
                $('<blockquote class="small text-muted mb-2" style="border-left:3px solid #ddd;padding-left:10px"></blockquote>')
                    .text(quote.owner + ': ' + (quote.is_removed ? __('Message removed') : (quote.body || quote.attachment_name || '').slice(0, 240))).appendTo(contentBox);
            }
            $('<div style="white-space:pre-wrap;overflow-wrap:anywhere"></div>').text(message.is_removed ? __('Message removed. History retained.') : message.body).appendTo(contentBox);
            // Images: preview the image alone, never display its filename.
            // Oversized images remain click-to-open so opening a chat cannot
            // automatically download 50-300 MB of artwork.
            const hasPrivateFile = !!message.attachment_url &&
                message.attachment_url.startsWith('/private/files/');
            const hasAttachment = !!message.attachment_name || hasPrivateFile;
            if (hasAttachment && message.attachment_expired) {
                fileCard(message, contentBox, true, !!message.is_image);
            } else if (hasPrivateFile && message.is_image &&
                       (!message.attachment_size || Number(message.attachment_size) <= 10 * 1024 * 1024)) {
                const preview = $('<a class="mdm-file-image-only"></a>')
                    .attr('href', message.attachment_url)
                    .attr('download', message.attachment_name || 'image')
                    .attr('aria-label', __('Download image'))
                    .appendTo(contentBox);
                $('<img loading="lazy" alt="">').attr('src', message.attachment_url).appendTo(preview);
            } else if (hasPrivateFile) {
                fileCard(message, contentBox, false, !!message.is_image);
            }
            const actions = $('<div class="mdm-message-actions"></div>').appendTo(contentBox);
            if (embedded) {
                const trigger = $('<button type="button" class="mdm-message-menu-trigger" aria-label="Message actions" aria-expanded="false">⋮</button>').prependTo(contentBox);
                trigger.on('click', event => {event.stopPropagation(); const open = !actions.hasClass('mdm-actions-open'); $('.mdm-actions-open').removeClass('mdm-actions-open'); actions.toggleClass('mdm-actions-open', open); trigger.attr('aria-expanded', String(open));});
                actions.on('click', 'button', () => {actions.removeClass('mdm-actions-open'); trigger.attr('aria-expanded','false');});
            }
            if (!message.is_removed) button('Reply').appendTo(actions).on('click', () => setReply(message));
            if (message.can_edit) {
                button('Edit').appendTo(actions).on('click', () => {
                    const dialog = new frappe.ui.Dialog({title: __('Edit message'), fields: [{fieldname: 'body', label: __('Message'), fieldtype: 'Small Text', default: message.body}],
                        primary_action_label: __('Save'), primary_action: async values => {
                            dialog.disable_primary_action();
                            try {
                                await call('change', {name: message.name, expected_revision: message.revision, body: values.body || ''});
                                dialog.hide(); await load(false);
                            } finally { dialog.enable_primary_action(); }
                        }});
                    dialog.show();
                });
                button('Remove').appendTo(actions).on('click', () => frappe.confirm(__('Remove this message? Its history will remain available to people with access to this record.'), async () => {
                    await call('change', {name: message.name, expected_revision: message.revision, remove: 1});
                    await load(false);
                }));
            }
            if (message.revision) button('History').appendTo(actions).on('click', async () => {
                const history = await call('history', {name: message.name});
                const dialog = new frappe.ui.Dialog({title: __('Message history'), fields: [{fieldname: 'history', fieldtype: 'HTML'}]});
                const body = dialog.fields_dict.history.$wrapper;
                history.forEach(version => {
                    const block = $('<div class="border-bottom py-2"></div>').appendTo(body);
                    $('<div class="small text-muted"></div>').text(version.changed_by + ' · ' + frappe.datetime.str_to_user(version.changed_at) + ' · ' + __(version.action)).appendTo(block);
                    $('<div style="white-space:pre-wrap;overflow-wrap:anywhere"></div>').text(version.body || __('Attachment-only message')).appendTo(block);
                    if (version.attachment_url && version.attachment_url.startsWith('/private/files/')) {
                        $('<a target="_blank" rel="noopener noreferrer"></a>').attr('href', version.attachment_url).text(version.attachment_name).appendTo(block);
                    }
                });
                dialog.show();
            });
            if (embedded && !actions.children().length) contentBox.find('.mdm-message-menu-trigger').remove();
            return item;
        }
        async function load(earlier, silent = false) {
            if (busy) return;
            busy = true; refresh.prop('disabled', true); older.prop('disabled', true);
            if (!silent) status.text(__('Loading…'));
            try {
                const focused = !earlier && pendingFocus;
                const data = await call('messages', {...params, before: earlier ? cursor : null, focus: focused || null});
                pendingFocus = null;
                displayed = data.messages.map(message => message.name);
                const signature = JSON.stringify(data);
                if (!earlier && signature === lastResult && !browsingEarlier) { status.text(data.messages.length ? '' : __('No messages yet. Start the discussion below.')); try { await acknowledge(); } catch(error) { console.error('Failed to mark messages read', error); } return; }
                browsingEarlier = !!earlier || !!focused;
                lastResult = earlier ? null : signature;
                if (!earlier) list.empty();
                const batch = $('<div></div>');
                data.messages.forEach(message => batch.append(render(message, data.quotes)));
                if (earlier) list.prepend(batch); else list.append(batch);
                cursor = data.next_cursor;
                older.toggle(data.has_more);
                status.text(browsingEarlier ? __('Viewing earlier messages. Refresh to see the latest discussion.') : (list.find('article').length ? '' : __('No messages yet. Start the discussion below.')));
                if (focused) requestAnimationFrame(() => list.find('article').filter((i, el) => el.dataset.message === focused)[0]?.scrollIntoView({block: 'center'}));
                else if (!earlier && embedded && !silent) list[0]?.scrollTo({top:list[0].scrollHeight,behavior:'instant'});
                try { await acknowledge(); }
                catch (error) { console.error('Failed to mark messages read', error); }
            } catch (error) {
                console.error('Discussion messages/read receipts failed', error);
                if (!list.find('article').length) list.empty();
                older.hide(); lastResult = null;
                status.text(__('Unable to load messages or mark them read. Please refresh.'));
            } finally {
                busy = false; refresh.prop('disabled', false); older.prop('disabled', false);
            }
        }
        refresh.on('click', () => load(false)); older.on('click', () => load(true));
        const MAX_NATIVE_UPLOAD = 500 * 1024 * 1024;
        let uploadRetention = null;
        const progress = $('<div class="small text-muted mdm-upload-progress"></div>')
            .hide().appendTo(compose);
        const fileSummary = selected => {
            if (!selected) return '';
            let description = selected.name + ' · ' + (selected.size / 1024 / 1024).toFixed(1) + ' MB';
            if (uploadRetention && selected.size > uploadRetention.threshold_mb * 1024 * 1024) {
                description += ' · ' + __('Expires after {0} days', [uploadRetention.retention_days]);
            }
            return description;
        };
        const updateSelectedFile = () => fileLabel.text(fileSummary(file[0].files[0]));
        file.off('change.mdmSize').on('change.mdmSize', updateSelectedFile);
        // One small permission-scoped read per opened conversation. The upload
        // handler re-reads the server setting at upload time (authoritative).
        call('attachment_policy', params).then(policy => {
            if (root.data('discussion-instance') !== instance) return;
            if (!policy || !Number.isInteger(policy.threshold_mb) ||
                !Number.isInteger(policy.retention_days)) return;
            uploadRetention = policy;
            help.text(__('Files over {0} MB expire after {1} days; maximum upload size also depends on Frappe site settings.', [
                policy.threshold_mb, policy.retention_days
            ]));
            updateSelectedFile();
        }).catch(error => {
            console.error('Unable to load chat attachment policy', error);
            help.text(__('Attachment retention settings unavailable; server rules apply.'));
        });
        function nativeUpload(selected, payload) {
            return new Promise((resolve, reject) => {
                const form = new FormData();
                form.append('file', selected, selected.name);
                form.append('is_private', '1');
                // Frappe 15 upload_file delegates to our whitelisted method.
                // No doctype/docname is passed because Design participants
                // may have read-only access to the parent DocType; server-side
                // parent_access validates the conversation.
                form.append('method', 'marina_custom_apps.design_management.discussions.send_uploaded_file');
                Object.entries(payload).forEach(([key, value]) => {
                    if (value !== null && value !== undefined) form.append(key, String(value));
                });
                const xhr = new XMLHttpRequest();
                xhr.open('POST', '/api/method/upload_file', true);
                xhr.setRequestHeader('Accept', 'application/json');
                if (frappe.csrf_token) xhr.setRequestHeader('X-Frappe-CSRF-Token', frappe.csrf_token);
                xhr.upload.onprogress = event => {
                    if (!event.lengthComputable) {
                        progress.text(__('Uploading attachment…')).show();
                        return;
                    }
                    const pct = Math.min(100, Math.floor(100 * event.loaded / event.total));
                    progress.text(pct < 100 ? __('Uploading: {0}%', [pct]) : __('Processing attachment…')).show();
                };
                xhr.onerror = () => reject(new Error(__('Network error during file upload.')));
                xhr.onabort = () => reject(new Error(__('File upload cancelled.')));
                xhr.onload = () => {
                    let response;
                    try { response = JSON.parse(xhr.responseText || '{}'); }
                    catch (err) { reject(new Error(__('Unexpected server response during upload.'))); return; }
                    if (xhr.status < 200 || xhr.status >= 300 || response.exc_type || response.exc) {
                        console.error('Chat upload rejected', xhr.status, response);
                        reject(new Error(response._error_message || __('Upload failed (HTTP {0}). Check server limits and permissions.', [xhr.status])));
                        return;
                    }
                    if (!response.message?.name) {
                        reject(new Error(__('Upload completed but message confirmation is missing.')));
                        return;
                    }
                    resolve(response.message);
                };
                progress.text(__('Uploading attachment…')).show();
                xhr.send(form);
            });
        }
        send.on('click', async () => {
            if (posting || busy) return;
            const selected = file[0].files[0];
            if (!text.val().trim() && !selected) return;
            if (selected && selected.size > MAX_NATIVE_UPLOAD) {
                frappe.msgprint(__('The maximum chat attachment size is 500 MB, subject to Frappe site limits.'));
                return;
            }
            const payload = {...params, body: text.val(), reply_to: replyTo,
                request_id: id, mentions: JSON.stringify([...selectedMentions.keys()])};
            posting = true;
            mentionButton.prop('disabled', true);
            send.prop('disabled', true);
            text.prop('disabled', true);
            file.prop('disabled', true);
            replyLabel.find('button').prop('disabled', true);
            try {
                if (selected) await nativeUpload(selected, payload);
                else await call('send', payload);
                text.val(''); file.val(''); fileLabel.text('');
                selectedMentions.clear(); drawMentions(); setReply(null); resetId();
                await load(false);
            } catch (error) {
                console.error('Discussion send failed', error);
                const safeMessage = $('<div></div>')
                    .text(error?.message || __('Could not send the message. Please retry.')).html();
                frappe.msgprint({title: __('Message not sent'), message: safeMessage, indicator: 'red'});
            } finally {
                progress.hide().text('');
                posting = false;
                mentionButton.prop('disabled', false);
                send.prop('disabled', false);
                text.prop('disabled', false);
                file.prop('disabled', false);
                replyLabel.find('button').prop('disabled', false);
            }
        });
        if (!root.is(':visible')) activity('count', params).then(data => updateUnread(data.unread)).catch(console.error);
        load(false);
        // Keep visible conversations current without notifications or draft loss.
        // Realtime is the primary path; polling stays as a reconnect fallback.
        // The event contains no record details and this API rechecks permissions.
        let realtimeRefresh = false;
        const onRealtime = () => {
            if (realtimeRefresh || document.hidden || !root.is(':visible') || posting || busy || browsingEarlier) return;
            realtimeRefresh = true;
            Promise.resolve(load(false, true)).finally(() => { realtimeRefresh = false; });
        };
        if (frappe.realtime?.on) frappe.realtime.on('marina_discussion_changed', onRealtime);
        const timer = setInterval(() => {
            if (!document.body.contains(root[0]) || root.data('discussion-instance') !== instance) {
                clearInterval(timer); return;
            }
            if (!document.hidden && root.is(':visible') && !posting && !busy) {
                if (!browsingEarlier) load(false, true); else acknowledge();
            } else if (!document.hidden && root.closest('.layout-main-section').is(':visible')) {
                activity('count', params).then(data => updateUnread(data.unread));
            }
        }, 15000);
        return () => {
            clearInterval(timer);
            if (frappe.realtime?.off) frappe.realtime.off('marina_discussion_changed', onRealtime);
        };
    }
    frappe.provide('marina.discussions');
    mount.mdmMessengerVersion = 2;
    marina.discussions.mount = mount;
    marina.discussions.open = (doctype, name, focus = null) => {
        const dialog = new frappe.ui.Dialog({title: __('Discussion: {0}', [name]), size: 'extra-large', fields: [{fieldname: 'discussion', fieldtype: 'HTML'}]});
        dialog.show();
        const dispose = mount(dialog.fields_dict.discussion.$wrapper, doctype, name, focus);
        dialog.$wrapper.one('hidden.bs.modal', dispose);
        return dialog;
    };
    ['Mood Board'].forEach(doctype => frappe.ui.form.on(doctype, {
        refresh(frm) {
            const field = frm.fields_dict.discussion_panel;
            if (!field) return;
            if (frm.is_new()) { field.$wrapper.text(__('Save this record to start its discussion.')); return; }
            const key = doctype + '/' + frm.doc.name;
            if (field.$wrapper.data('discussion-key') !== key) {
                field.$wrapper.data('discussion-key', key);
                mount(field.$wrapper, doctype, frm.doc.name, null, count => {
                    frm.set_df_property('discussion_tab', 'label', __('Discussion') + (count ? ' (' + count + ')' : ''));
                });
            }
        }
    }));
})();
