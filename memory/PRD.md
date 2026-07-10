# HomeIVF CRM — PRD

## Fix (2026-07) — "Sync Now not working" → Odoo delta sync now runs IN-PROCESS — iteration_37 (backend 4/4, frontend 100%)
- **Root cause:** `POST /api/admin/sync/start` spawned a *detached subprocess* that wrote to `/var/log/odoo_sync.log`. In the managed/container production deploy this is fragile (read-only FS / detached-process limits) → the button appeared to do nothing.
- **Fix:** sync now runs in-process on a background `threading.Thread` → `odoo_sync.run_sync(run_id, since, until)` (extracted from the script's `__main__`). Progress is written to `sync_runs`; `settings.last_sync` is set on completion; import/connect failures are recorded via a fallback sync pymongo client. No subprocess, no log-file dependency.
- **Verified in preview against LIVE Odoo:** full delta ingested +11,032 leads, +118,625 chatter, +957 WA channels, +3,694 WA messages, +10,733 contacts, activities → status done; a second in-process run completed through all 9 entities and updated last_sync. Live Audit shows all modules match (lead_chatter ~0.01% behind is expected — sync skips empty-body system messages + Odoo grows live). Non-admins get 403.
- **Go-live note:** REDEPLOY to push this to production; on production's own DB the first "Sync Now" auto-runs FULL import if empty, else delta.

## Feature (2026-07) — Lead view & Follow-ups (Cases 1–6) — iteration_35/36
- **Case 1 — Note mandatory:** a follow-up cannot be saved without a note (backend 400 + frontend block) in Assignment & Follow-up (`add_followup`/`update_followup`).
- **Case 2 — Caller Activities:** new lead-view section (`CallerActivities`) with a feedback input + "Add More Note"; each entry stored separately in `caller_activities` and shown as history (note · agent · timestamp). Endpoints `GET/POST /api/leads/{id}/caller-activities`.
- **Case 3 — Default Country India:** `create_lead` defaults `country="India"`; New Lead modal Country select defaults to India (changeable).
- **Case 4 — Follow-up reminder popup:** global `FollowUpReminder` (mounted in Layout) polls `GET /api/leads/followups/reminders` every 60s and shows a card ~5 min before a scheduled follow-up time (caller = own leads, admin = all), with Mark-done/Open/Dismiss. Stays until dismissed.
- **Case 5 — Status + analytics:** dynamic `followup_status` catalog (Completed/Not Done/Rescheduled/Cancelled, admin-editable in Admin → Dropdowns). Status dropdown under the Note + inline per-entry status setter (`POST /followups/{fid}/status`). Analytics bar in Follow-ups tab via `GET /api/leads/followups/analytics?date=` (Total/Completed/Not Done/Rescheduled/Cancelled/Pending; past-due unmarked count as Not Done).
- **Case 6 — Lead export:** Admin-only "Export" button beside New Lead (Lead-in-Pipeline tab) → date-range modal → downloads ALL lead fields + serialized Q&A/custom column as Excel (`GET /api/export/leads.xlsx`, requires `export` permission; caller = 403).

## Feature (2026-07) — Case 3 Marketing Campaigns overhaul (WhatsApp + Email) — iteration_34 (frontend 100%, backend curl-verified)
- **Template preview on create/edit:** selecting a WhatsApp/Email template in the campaign modal now renders a live preview (`template-preview` / `template-preview-body`) with {{1}}→sample name; email shows Subject + rendered HTML.
- **Rich campaign box:** each card now shows channel chip (WhatsApp/Email), template name, trigger/logic (`trigger_desc` from audience filters), status badge (Draft/In Progress/Paused/Completed/Failed/Queued), a progress bar + %, and metrics Total/Sent/Delivered/Read/Replies/Queued/Failed. WA delivered/read/replied are computed live from `wa_tracking` aggregation by `campaign_id` (added `campaign_id` to `record_wa_outbound`).
- **Actions:** Send, **Pause** (in-progress), **Resume** (paused, continues via `/send` skipping already-processed leads), **Edit** (PATCH, blocked while running), Delete, and **View failures & reasons** modal (`/campaigns/{cid}/failures`).
- **Background sender:** `POST /campaigns/{cid}/send` now launches an asyncio background task, sets status `in_progress`, updates counters live (frontend polls every 3s), honours the pause flag, and auto-sets **completed** at 100%.
- New/updated endpoints in `routes/marketing.py`: enriched `GET /campaigns`, `PATCH /campaigns/{cid}`, `POST /campaigns/{cid}/pause`, `GET /campaigns/{cid}/failures`. NOTE: preview WA send returns Meta errors (not connected) → failures panel is populated as expected.

## Feature (2026-06) — Email sender name + WhatsApp Chat Workspace (Case 1 + Case 2 Phase-2A/2B) — iteration_33 (100%: 16/16 backend + all frontend)
- **Case 1 — Email sender name → HomeIVF:** send_email now sets From as `HomeIVF <account>` via `formataddr`. Admin can edit the display name in Admin → Email (`POST /admin/gmail/sender-name`, default "HomeIVF"). Live email send confirmable only on production (Gmail connect).
- **Case 2 — WhatsApp Chat Workspace overhaul (followed the referenced Figma design system):**
  - Unread indicators + per-chat unread counts (bold rows + green badge), auto-marked read on open (`unread_count` on wa_channels, inbound webhook increments it, `POST /whatsapp/channels/{id}/read`).
  - Global floating "new WhatsApp message" notifier (`WaNotifier` in Layout, `GET /whatsapp/unread-summary`, 15s poll) — appears app-wide so no chat is missed.
  - Filter tabs All / Unread / Interested; conversation search; in-conversation message search (`?search=`).
  - "Interested Customer" categorization — `POST /whatsapp/channels/{id}/category` tags the linked lead "Interested" + sets lead_stage="Contacted" + chatter note + runs on_tag_set automations.
  - Star & Pin messages + a Starred side panel (`/messages/{id}/star|pin`, `?starred=true`, pinned bar).
  - Emoji picker (curated, no dep), quote-reply (reply_to snippet).
  - Attachments (image/file/video) — `POST /whatsapp/media/upload` stores a CRM-viewable copy + uploads to Meta (media id) → `send_media`; served via `GET /whatsapp/media?path=&auth=`. Emoji reactions — `/messages/{id}/react` + inbound `reaction` webhook attaches emoji.
  - Backend bug fixed by QA: toggle_star/pin used `if not m` (empty projection dict is falsy) → changed to `is None`.
- **Deferred:** received (inbound) customer media currently shows a "[type]" placeholder (full inbound media download/render not built); voice notes explicitly skipped per user.


- **Gap 1 — inbound from new numbers was dropped:** the inbound webhook only mirrored into an EXISTING wa_channel, so a first-time inbound (number with no migrated thread) never appeared in the WhatsApp inbox. Now `wa_webhook()` auto-creates a wa_channel (via `_next_channel_id()` which self-heals the `wa_channel` counter to max(id) to avoid colliding with the 10.9k migrated channels), then stores the inbound message. Same number reuses the thread.
- **Gap 2 — reply always said "queued":** `POST /whatsapp/channels/{id}/send` now surfaces the real result — returns the live status/wamid on success, and raises HTTP 400 with the Meta error (e.g. free-text only allowed within the 24-hour customer-service window → send a template) on failure. Frontend inbox toasts by status + polls the open thread & channel list every 8s for near-real-time chat.
- **Confirmed working:** testing verified a live reply was accepted by Meta (wamid returned) in preview. So 2-way chat itself works. **Two dependencies for it to flow on production:** (a) the app's WhatsApp `messages` webhook must be subscribed & pointed at the prod CRM (same requirement as delivery-status — use Admin → WhatsApp → "Diagnose delivery status"); (b) free-text replies only work inside Meta's 24h window — outside it, agents must send an approved template.


- **Case 1 (Gmail OAuth "invalid_grant: Missing code verifier"):** PKCE `code_verifier` from `authorization_url()` was lost because the callback built a fresh Flow. Fix: persist `flow.code_verifier` in `oauth_states` (keyed by state) at auth-url time and restore it on the callback flow before `fetch_token` (stateless/multi-worker safe). Verified: verifier stored (~128 chars), callback with bad code → 302 error redirect (no 500). Full Google E2E still needs a live login on production after redeploy.
- **Case 2 (Move to Pipeline in lead detail):** Added `data-testid=move-to-pipeline-button` in LeadDetail header, shown only for raw Ozonetel leads (`ozonetel_lead && !in_pipeline`). Click promotes directly via POST /leads/{id}/promote-to-pipeline using the lead's current info — **no popup**; button disappears after move; merges into existing pipeline lead on duplicate phone.
- **Case 4 (activity preview + status):** Confirmed inline template preview card + live status badge render in the lead Activity log for manual & automation sends (`activity-preview-{id}` / `activity-status-{id}`). Was built iter28; re-verified.
- **Case 5 (WhatsApp Template page + Quick Reply):** Converted Applies To (Lead/Contact), Phone Field (CRM-field dropdown), Header Type (None/Text/Image/Video/Document/Location), Users (all / specific-agents multi-select), and Variables→Field (CRM-field dropdown) to proper dropdowns. New `GET /api/catalogs/lead-field-options` (standard + custom fields). Button tab: Quick Reply/Set Automation buttons get an **automation dropdown** (`button-automation-{i}`) + setup guide. Backend: inbound WhatsApp webhook now parses `type=button`/`interactive` button replies → logs a Quick Reply chatter entry, marks the latest outbound tracking as **replied**, and runs the button's mapped automation (`run_automation_by_id`; refactored `_apply_actions`).
- **Message Log "stuck at SENT" (Case 4/5):** Confirmed NOT a CRM bug — Meta-side webhook delivery config. Use the "Diagnose delivery status" button (Admin → WhatsApp) added iter30 on production to pinpoint (needs App ID+Secret + 'messages' field subscribed + callback pointed at prod CRM).


- Confirmed CRM code is CORRECT end-to-end (wamid stored on send; webhook matches wamid → advances sent→delivered→read; preview verdict='healthy', 5/5 status webhooks matched). The production "stuck at Sent" is a **Meta-side delivery config** issue, not a CRM bug.
- New: `GET /api/admin/whatsapp/diagnose` (wa_cloud.py) + `check_app_subscriptions()` (whatsapp_cloud.py, reads {app_id}/subscriptions via app token). Returns a plain-English **verdict + next_step** and a 5-point checklist: (1) token+phone configured, (2) WABA subscribed to an app, (3) app 'whatsapp_business_account' webhook has 'messages' field + points to this CRM, (4) status webhooks actually received, (5) tracked msgs carry a wamid. Verdict trusts observed matched status webhooks first.
- UI: Admin → WhatsApp → "Diagnose delivery status" button (data-testid=wa-diagnose-button) → verdict panel (wa-diagnose-result / wa-diagnose-verdict).
- **USER ACTION on production (after redeploy):** Admin → WhatsApp → add App ID + App Secret → click "Diagnose delivery status". It will name the exact broken link. Most likely fix: in Meta → App → WhatsApp → Configuration set Callback URL to the prod CRM's /api/webhooks/whatsapp and subscribe the **messages** field, then click "Subscribe WABA to webhooks". NOTE: messages sent BEFORE this stay "Sent" forever — send a fresh one to confirm.


- Root cause: CRM webhook→wa_tracking status logic is CORRECT (verified: signed webhook advances sent→delivered→read→failed with history). Production stayed "Sent" because **Meta wasn't delivering status webhooks** — the WABA wasn't subscribed to the app.
- Fix: `subscribe_waba()`/`get_subscribed_apps()` in whatsapp_cloud.py + admin endpoints `POST /api/admin/whatsapp/subscribe`, `GET /api/admin/whatsapp/subscribed-apps`. Added a webhook diagnostic log (`wa_webhook_log`) + `GET /api/admin/whatsapp/webhook-log`. Admin → WhatsApp UI: "Subscribe WABA to webhooks" + "Recent webhook deliveries" buttons/panel.
- USER ACTION on production (after redeploy): click "Subscribe WABA to webhooks", and ensure the **messages** field is subscribed in Meta → WhatsApp → Configuration. Then delivered/read/replied will flow live.
- NOTE: Case 2 (Ozonetel split) IS built & tested in preview (iter27) — if user doesn't see it, it's because production hasn't been redeployed since.


## Feature (2026-07) — Case 4 fully closed: inline template preview + live status in Activity Log — iteration_28 (100% backend + frontend)
- **Gap fixed:** Case 4 previously used a separate side panel. Now, when a WhatsApp/Email template is sent (manual OR automation), the lead's **Chatter/Activity log** shows the message as an inline **preview card** with a **status badge on the top-right** (hover shows Sent/Delivered/Read/Failed/Bounced/Replied). WhatsApp cards are clickable → message lifecycle detail page; badge reflects live `wa_tracking` status.
- Backend: `log_message` now accepts an `extra` dict; `send_whatsapp`, `send_email`, and `run_automations` attach `{kind, preview, template_name, track_id, status, channel}` to the chatter message. Frontend: `TemplateActivityPreview` in LeadDetail + `waTrackById` live-status map.
- Note: email delivery/read status isn't available from Gmail API (email badge shows Sent/In Queue snapshot).
- **ALL doc Tab-2 cases (1–5) now fully complete & tested.** Case 1/Gmail pending user's production redeploy confirmation.


## Feature (2026-07) — Doc Tab 2 remaining cases 2/3/4 — iteration_27 (backend 100%, frontend 100%)
- **Case 2 — Ozonetel vs Pipeline split:** Leads page now has two buckets: "Lead in Pipeline" (default) and "Ozonetel Lead" (raw, `ozonetel_lead=true & in_pipeline!=true`). Backend `bucket` filter in build_query/query_params_dep. New `POST /api/leads/{id}/promote-to-pipeline` validates a raw lead into the pipeline; DEDUP: if a pipeline lead has the same phone, the raw lead's call activity is merged into it (`merged_into`, is_duplicate/duplicate_of set) and the raw one archived. Frontend: bucket tabs + "→ Pipeline" button + PromoteModal (name/phone/email/city/state).
- **Case 3 — Automation template preview:** In Admin → Automations, selecting a WhatsApp/Email template in an action now shows a live preview (body/subject) below the selector (`action-preview-{idx}`).
- **Case 4 — In-lead message preview + status:** LeadDetail "WhatsApp Messages" panel (WaLeadPanel) shows each tracked message with preview + status badge (hover shows status) linking to the message detail. (Email delivery/read status is not available from Gmail API.)
- ⚠️ Needs production REDEPLOY. NOTE: after any manual DB seed, re-align `db.counters.lead` to MAX(id) or create_lead will 500.
- **ALL DOC CASES NOW COMPLETE** (Tab 1 Cases 1-6, Tab 2 Cases 1-5). Case 5/Gmail pending user's production redeploy confirmation.


## Feature (2026-07) — 📲 Case 5: WhatsApp Template Management + Message Tracking (A→B→C) — iteration_26 (backend 100%, frontend 100%)
- **Decision:** Template config stored in CRM only (Meta approval remains manual).
- **Phase A — tracking:** New `wa_tracking` collection + `record_wa_outbound()` helper. Every outbound WhatsApp template (manual lead send, automation, campaign) is stored with wamid, template, lead, sent_to, created_by, body, status + status_history. Meta status webhook (`/api/webhooks/whatsapp`) updates the record by wamid through the lifecycle (sent→delivered→read→failed, with failure_type/error_code); inbound replies mark the latest outbound as `replied`. New API `routes/wa_tracking.py`: `/api/wa/template/{id}/summary`, `/api/wa/template/{id}/messages`, `/api/wa/message/{id}`, `/api/wa/lead/{id}/messages`. Lifecycle: In Queue→Sent→Delivered→Read→Replied→Received→Failed→Bounced→Cancelled (`core/utils.WA_STATUS_FLOW`).
- **Phase B — full-page template:** WhatsApp templates now open as a full page (`/templates/whatsapp/:id`, `WaTemplateDetail.jsx`) with 3-step approval flow (Draft→Pending→Approved), info fields (Applies To, Phone Field, Language, Header Type, Category, Footer, User Access, Meta name), and Body/Button/Variables tabs + live preview + Submit. Approved templates show an "Ad Messages" summary box (total triggered) → message-list page (`WaMessageList.jsx`, table Created On/Created By/Sent To/State) → message-detail page (`WaMessageDetail.jsx`, visual lifecycle tracker + failure reason/code + history). `templates.py` extended with the new fields + single GET.
- **Phase C — lead log:** LeadDetail shows a "WhatsApp Messages" panel (`WaLeadPanel`) listing tracked messages with a status badge (hover shows status) + preview; click opens the message detail.
- Verified: 14/14 backend pytest incl. HMAC-signed webhook status advance; all frontend selectors/navigation. ⚠️ Needs production REDEPLOY.
- **Still pending:** doc tab t.hx4luqwr4eh5 Case 7 (per user); doc tab t.lzutgaq803u Case 2 (Ozonetel raw-leads vs Pipeline split), Case 3/4 (automation preview + status icons in lead log — partially covered by WaLeadPanel).


## Fix (2026-07) — 📧 Gmail OAuth "Scope has changed" token-exchange failure — iteration_25 (backend 100%)
- Google returns granted scopes reordered and adds the `email` alias (`email gmail.send openid userinfo.email`), which made oauthlib raise "Scope has changed" during `fetch_token` → connection failed even though consent + code were valid.
- Fix: set `OAUTHLIB_RELAX_TOKEN_SCOPE=1` and `OAUTHLIB_IGNORE_SCOPE_CHANGE=1` at import of `core/gmail_send.py` (before token exchange). Callback also surfaces the real reason (`?gmail=error&reason=...`).
- Verified: auth-url, callback error/badstate paths, env flags set at import; RBAC + follow-ups regression clean. ⚠️ Full E2E needs production REDEPLOY + real Google login retry.
- Pending (new doc tab t.lzutgaq803u): large WhatsApp template management + message-tracking epic (Case 5) — NOT yet built; scope confirmation with user.


## Feature (2026-07) — 🔐 Roles & Access Control (RBAC) + 6 Phase-1 UI cases — iteration_24 (100% backend + frontend)
- **RBAC:** 3 fixed roles (admin/manager/caller) with an editable permission matrix. New `core/permissions.py` (MODULE_PERMS + ACTION_PERMS, DEFAULT_PERMISSIONS, admin always full & non-reducible). `require_permission()` in security.py; `get_current_user`/login now attach `permissions`. New GET/PATCH `/api/admin/role-permissions`. Enforcement: reports (require_permission "reports"), export ("export"), marketing ("marketing"), users ("manage_users"). Frontend: `can()` in AuthContext, nav gated in Layout, `Guard` route wrapper in App.js (redirects to / if not allowed), and a "Roles & Access Control" matrix UI in Admin → Users (admin column locked). Defaults: caller no Marketing/Reports/Admin/export/delete; manager has Marketing+Reports+Admin(read-only) but no export/migration/manage_users/delete.
- **Case 1:** Lead detail — left fields & right chatter columns scroll independently; header stays fixed.
- **Case 2:** Follow-up ENTRIES — new `follow_ups` collection + CRUD `/api/leads/{id}/followups`, synced to lead.follow_up_date. UI: add form + list with edit/delete under Assignment & Follow-up. Removed the "Appointment" date field.
- **Case 3:** Admin → Automations edit icon (prefilled "Edit Automation" modal, PATCH).
- **Case 4:** Admin → Custom Fields edit icon (prefilled "Edit Field" modal, PATCH).
- **Case 5 (Gmail):** Callback now surfaces the real Google error reason (`?gmail=error&reason=...`) + logs it. Redirect URI confirmed correct in Console; root cause is production consent-screen/test-user or client-secret config — pending user action after redeploy.
- **Case 6:** Leads list "Columns" menu to show/hide columns; persists in localStorage.
- **⚠️ Needs REDEPLOY** for production. RBAC applies on the user's next login/refresh.


## Original Problem Statement
HomeIVF (homeivf.com, at-home IVF fertility care, venture of Seeds of Innocens) runs its entire CRM/lead management/follow-up/conversion cycle on Odoo (homeivf.odoo.com, Odoo 19 Enterprise SaaS). They want a fully-owned custom CRM ("HomeIVF CRM", to be hosted on homeivfcrm.com, branded "Powered by TagQuest") that:
- **Phase 1**: Replicates ALL Odoo functionality they use — interfaces, flows, workflows, reports with filters/dropdowns, full backend admin — with FULL data migration.
- **Phase 2**: AI insights + AI recommendations on every section, plus an "AI Brain" conversational analytics chat (Emergent LLM key approved by user).

## Fix (2026-07) — FB lead NAME empty / phone-in-name (broadened detection) — iteration_23 (14/15→clean)
- **CAUSE:** Form's name field key varied (first_name+last_name, spaced/cased, or a question like "what is your name?"). Earlier fix caught common variants; this adds a last-resort: any field whose normalized key CONTAINS 'name' (excluding company/form/page/user/product/brand/clinic/business) is used as the name, and such fields are kept out of the Q&A card (skip-branch mirrors the exclusion). Webhook 'created' log now records raw field_keys for diagnosis.
- Verified: "what is your name?"→name set + not duplicated in Q&A; company/clinic/etc excluded → phone fallback; first+last, full_name, phone-only regressions pass.
- **⚠️ Needs REDEPLOY.** IMPORTANT: user's "phone-in-name" may simply be that the earlier name fix (iter22) wasn't redeployed yet — confirm redeploy, then check Admin→Facebook delivery log 'field_keys' to see the exact form field names.

## Fix (2026-07) — FB lead NAME empty (list showed phone, detail showed '—') — iteration_22 (11/11 backend)
- **CAUSE:** Form name field isn't always exact key `full_name` (may be first_name+last_name or spaced/cased key). Also DEFAULT_MAP mapped `first_name`→contact_name, grabbing only first name and dropping last_name.
- **FIX (facebook.py _map_and_create_lead):** removed `first_name` from DEFAULT_MAP; added name-derivation fallback — when contact_name/name empty, scan field_data for full_name/name variants OR combine first_name+last_name; name-part fields excluded from Q&A custom card. Verified 11/11 (Akhil Sharma, Ravi Kumar, Meena, Priya Nair, phone-fallback, custom Q&A preserved).
- **⚠️ Needs REDEPLOY.** Applies to NEW leads; existing name-less leads unaffected (name can be edited manually).

## Fix (2026-07) — 🔴 REAL PRODUCTION BLOCKER: Graph #100 "nonexisting field (form_name)" — iteration_21 (8/8 backend)
- **ROOT CAUSE (code bug):** fb_webhook() requested the leadgen object with `fields=...,form_name,...` but `form_name` is NOT a valid field on Meta's leadgen node → Graph returns `(#100) Tried accessing nonexisting field (form_name)` → the ENTIRE lead fetch failed → 0 leads created (even though token/permissions/webhook were all green). This is why no FB leads ever appeared.
- **FIX:** Removed `form_name` from the leadgen fields request; now fetch form name separately via `GET /{form_id}?fields=name` and inject as lead['form_name'] before mapping. Verified iter21 (8/8) incl. field-string assertion + regressions. NOTE: true end-to-end needs live Meta (confirm after redeploy).
- **⚠️ Needs REDEPLOY.** After redeploy, submit a fresh Meta test lead → it should now be `created` in the delivery log and appear in the Lead report (assigned to a caller, with source + timestamp).

## Fix (2026-07) — FB leads unassigned → invisible to callers; now auto-assigned + findable — iteration_20 (9/9 backend)
- **FIX:** _map_and_create_lead now round-robins each FB lead across ACTIVE caller users when no assignment config applies (counter fb_assign_pointer). FB leads are no longer Unassigned → they appear in callers' Lead reports with source 'Meta Lead Ads' + create_date/create_date_ist, exactly like other leads. Verified iter20 (9/9): rotation works, assigned caller sees lead via user_id filter, recent-leads shows caller name.
- Also live: "Recently captured Facebook leads" panel in Admin → Facebook (below Check connection) with Open→ links (iter19).
- **⚠️ Needs REDEPLOY.** After redeploy, existing 14 old FB leads stay Unassigned (created before this) — user can bulk-assign them; NEW leads auto-distribute to callers. If user wants distribution limited to a specific team, configure Admin → Assignment.

## Fix (2026-07) — "Can't see FB leads in CRM" → leads ARE captured but were unfindable — iteration_19 (7/7 backend)
- **ROOT CAUSE:** FB leads ARE created (14 on prod, source 'Meta Lead Ads') but (1) come in UNASSIGNED and caller-role users only see leads assigned to them, and (2) get buried under ~100k migrated leads by the default create_date sort. Admin CAN see them (verified: a fresh FB lead lands at top of admin list + source filter returns them).
- **FIX:** New `GET /api/admin/facebook/recent-leads` (total + latest 25 facebook_lead:true, with assigned_to). Admin → Facebook now shows a "Recently captured Facebook leads" table with "Open →" links — a guaranteed, filter-proof way to find every Meta lead. Verified testing agent iter19 (7/7) incl. regressions (diagnose 5 checks, webhook-log, invalid-sig 401).
- **PRODUCT NOTE for user:** All FB leads are Unassigned → the sales team (callers) can't see them. Options to discuss: (a) enable round-robin assignment for FB leads so callers get them, or (b) let callers see unassigned FB leads. Awaiting user's preference.

## Fix (2026-07) — FB leads: webhook delivers but Graph fetch fails (leads_retrieval / token-app mismatch) — iteration_18 (backend green)
- **Progress:** After redeploy, webhook DELIVERY now succeeds on prod (app 736963545504625 = Success in Meta Track status; signature/app-secret issue resolved). NEW failure surfaced by our delivery log: Graph API fetch of the lead returns "Object ... does not exist / missing permissions".
- **ROOT CAUSE (production Meta config):** the saved Page Access Token was generated under a DIFFERENT Meta app (user screenshot showed Meta App = "Odoo") than the configured CRM App ID (736963545504625), and/or lacks `leads_retrieval`. So delivery works but lead RETRIEVAL is rejected.
- **CODE FIX (diagnostic):** diagnose() now calls Meta `debug_token` and adds two checks: **'Token ↔ App match'** (token app_id vs configured App ID) and **'leads_retrieval permission'** (scope present). Pinpoints the exact problem on prod. Refined webhook error log message. Verified via testing agent iteration_18 (checks present, diagnose 200, regressions green). NOTE: preview DB token is correct (all 5 checks green) → prod token is the wrong one.
- **⚠️ USER ACTION (production):** In Meta Graph API Explorer / token tool, generate a **Page Access Token with Meta App = the CRM app (736963545504625)** (NOT Odoo) for Page HomeIVF, including **leads_retrieval + pages_manage_metadata**. Paste into Admin → Facebook → Page Access Token → Save → Check connection (both new checks must be ✓). Also: test-tool leads are ephemeral (1 per form, deleted on recreate) — a real ad lead or a freshly-created test lead is the reliable check.


- **Diagnosis from user's Meta "Track status" screenshot:** HomeIVF page (273380505860843) has MULTIPLE apps subscribed to leadgen. Two apps deliver `Success`; app **736963545504625 → Failure: `webhooks.delivery.rejected`**. That means Meta DID deliver the leadgen event to the CRM callback but the CRM returned non-2xx (almost certainly 401 invalid signature) → lead never created. Previously the CRM logged nothing → invisible.
- **ROOT CAUSE (production config):** the App Secret saved in CRM Settings → Facebook does not match the app (736963545504625) whose 'page' webhook points to crm.homeivfmarketing.com. HMAC signature check fails → 401 → Meta reports `webhooks.delivery.rejected`.
- **CODE FIX (visibility):** Added `_log_webhook()` in facebook.py — every inbound webhook outcome (rejected/error/skipped/created) is stored in `db.fb_webhook_log` (capped 200). New `GET /api/admin/facebook/webhook-log`; diagnose() now returns `recent_webhook_deliveries`; Admin Facebook diagnostic panel renders them. Verified via testing agent (6/6): bad-sig→401+rejected log; valid-sig+bad leadgen→200+error log; auth enforced; diagnose surfaces deliveries.
- **⚠️ USER ACTION (production):** (1) Redeploy so logging is live. (2) In Meta, ensure the App Secret saved in CRM Settings belongs to the SAME app whose 'page' webhook callback = crm.homeivfmarketing.com/api/webhooks/facebook (the one showing `webhooks.delivery.rejected`). Re-save the correct App Secret, then click "Check connection" — deliveries should flip to `created`.


- **Symptom 1:** "Meta Lead Ads" missing from Source dropdown on prod after redeploys (it was only created lazily on FB lead ingest; startup seed never added it).
- **FIX 1:** Added "Meta Lead Ads" to the startup `source_lead` seed.
- **Symptom 2 (deploy crash):** First deploy attempt of FIX 1 crashed backend startup with `DuplicateKeyError` on catalogs unique index `type_1_id_1` dup {source_lead, id:6}. Root cause: seed used hardcoded `id:i+1`; prod already had a migrated entry at id=6 (Ozonetel) → collision → startup exits → deploy never ready.
- **FIX 2:** Replaced hardcoded-id source_lead seed loop with collision-safe `ensure_catalog("source_lead", name)` (max-id+1 + retry). Verified via testing agent (6/6): clean startup, no dup names, idempotent across restarts, POST still 200. Local sim confirmed collision-safe (id=6 taken → new item id=12).
- **⚠️ Needs PRODUCTION REDEPLOY.** Deployment agent's .gitignore .env flag is a FALSE POSITIVE (app has deployed successfully before with same .gitignore).



## Fix (2026-07-02, batch 20) — FB leads "not showing in report" + Source dropdown — iteration_14 (7/7 backend, 100%)
- **ROOT CAUSE (production data):** the production `settings.facebook.page_access_token` contained the ENTIRE pasted text block (App ID + app secret + WhatsApp SU token label) instead of just the Page token → Graph fetch failed with "Malformed access token" → leadgen webhooks delivered Success (200) but created 0 leads. FIXED directly on production via API: re-set clean app_id/app_secret/page_id/page_access_token (fresh, points to HomeIVF 273380505860843)/verify_token=homeivf_fb_verify_2026/graph v25.0. Production `/admin/facebook/diagnose` now all 3 checks green; webhook registered → https://crm.homeivfmarketing.com/api/webhooks/facebook. Verified a simulated FB lead creates + shows in GET /leads?source_lead=Meta Lead Ads (then archived the test lead #504779).
- **Source dropdown fix (code):** `_map_and_create_lead` now calls `ensure_catalog('source_lead', source)` so "Meta Lead Ads" auto-appears in Source dropdowns/filters. Added shared `core/utils.ensure_catalog`.
- **Catalog-create 500 bug (code):** `POST /api/catalogs/{ctype}` 500'd for migrated types (source_lead/tag) because the `catalog_{ctype}` counter was behind migrated ids → duplicate-key. Now retries insert with max-id+1. Admins can add sources manually again.
- **⚠️ Needs PRODUCTION REDEPLOY** for the ensure_catalog + catalog-500 + attribution + register-webhook-button code to reach prod. After redeploy the next real FB lead auto-adds "Meta Lead Ads" to the dropdown (or admin adds it manually). Leftover empty test lead #504615 on prod (earlier artifact) not archived — user to decide.

- **FB Attribution fix:** the leadgen fetch now requests `ad_id,ad_name,adset_id,adset_name,campaign_id,campaign_name,form_id,form_name,platform` and `_map_and_create_lead` writes `campaign_name`←campaign_name, `ads_campaign_name`←adset_name, `ads_name`←ad_name (+ fb_campaign_id/fb_adset_id/fb_ad_id/fb_form_name). Verified in UI: Attribution card shows Campaign / Ads Campaign / Ad Name populated. `fb_test_lead` accepts optional campaign_name/adset_name/ad_name/form_name to simulate. NOTE: UTM Source/Medium/Campaign stay empty for FB leads — Meta lead forms don't carry UTM params (those come from web/landing-page URLs) unless the form has hidden UTM fields (which would map via field_data).
- **WhatsApp Cloud unblocked:** the System User token (whatsapp_business_management + whatsapp_business_messaging) resolves the old `(#200)` permission error. Saved config in preview settings key='whatsapp_cloud': WABA `30291513857161871` (HomeIVF, INR), phone_number_id `696577696872486` (+91 92112 24222, quality YELLOW, code_verification EXPIRED), verify_token=homeivf_wa_verify_2026. Verified via app endpoints: status configured=true, phone-numbers ✓, templates ✓ (approved list loads). LIVE outbound send test still PENDING a destination number from user.
 — iteration_13 (9/9 backend, 100%)
- **Root cause (diagnosed via live Graph API):** The Meta app `736963545504625` had NO app-level `page`/leadgen webhook subscription at all — its only webhook was `whatsapp_business_account` → `https://homeivf.odoo.com/whatsapp/webhook`. So FB leads had nowhere to be delivered. Also, the user was pasting a **System User token** (belongs to "Odoo" SU id 122101718660933307) into the Page Access Token field → Meta "Malformed access token".
- **Correct creds identified:** Page **"HomeIVF" id `273380505860843`**; its Page Access Token was fetched via `me/accounts` on the SU token. SU token scopes include leads_retrieval + pages_manage_metadata + whatsapp_* (non-expiring, expires_at:0). App ID `736963545504625`, App Secret `39678a3c68cf84bf247fb2f1b9cafd16`.
- **Done via API:** Page subscribed to leadgen (subscribed_apps) ✓. Proved end-to-end webhook registration works (Meta verified preview callback, success:true), then DELETED the preview page subscription to leave a clean slate (no hijack of production leads).
- **New:** `POST /api/admin/facebook/register-webhook {callback_url}` — registers the app-level `page`/leadgen webhook with Meta (POST /{app_id}/subscriptions using app token; Meta verifies via saved verify_token). One-click **"Register leadgen webhook with Meta"** button in Admin → Facebook (`fb-register-webhook-button`). Enhanced `GET /admin/facebook/diagnose` with a 3rd check "App leadgen webhook" that detects exactly this missing piece. `_map_and_create_lead` now keeps `name`/`contact_name` in sync.
- **⚠️ USER ACTION on PRODUCTION (requires redeploy first, since button/endpoint are new code):** Admin → Facebook → enter App ID/Secret, Page ID `273380505860843`, the **Page** Access Token (NOT the SU token), a Verify Token → Save → click "Register leadgen webhook with Meta" → "Check connection" (should be all green) → send a Meta test lead. Preview settings DB currently holds the real creds (verify_token=homeivf_fb_verify_2026) for demonstrability.


## User Choices (confirmed)
- Keep duplicate Odoo Studio fields AS-IS (raw under `lead.custom`); cleanup deferred to Phase 2. Convenience coalesced fields (lead_stage, follow_up_date, gender, etc.) computed at migration on top.
- Full migration incl. chatter + WhatsApp history.
- Live API creds (Meta WhatsApp, MyOperator auto-caller, SMTP email) will be provided LATER — build ready-to-connect (outbound_queue with status pending_api_credentials).
- Roles: Admin / Manager / Caller (callers see only own leads). JWT email/password auth, admin-managed users.

## The Business (from Odoo discovery)
Tele-calling lead engine: 27 users (24 callers + managers), 99,516 leads, 96K contacts, 10,936 WhatsApp conversations, 55 WA templates, 32 email templates, 16 automations, ~910K lead chatter messages.
Actual workflow: custom **Lead Stage** (Contact Attempt → Contacted → Converted → Closed) + **34 disposition tags** (Ringing, Busy, OPD Booked, OPD Done, Registration Done, Treatment Started, Junk...) + **Follow Up Date/Tag (Follow UP 1-5)**. Leads arrive via webhooks (landing pages/chatbot/website/app/callback) with questionnaire + ads attribution. Reports = group-bys of Caller × Tags × Day/Month.

## Architecture
- FastAPI + MongoDB (motor) + React (CRA, Tailwind, phosphor icons, recharts). Supervisor-managed.
- Backend: /app/backend/server.py (app+startup seed/indexes), core/ (db, security, utils incl. automation engine), routes/ (auth, users, leads, chatter, catalogs, templates, whatsapp, reports, webhooks, filters, admin), migration/odoo_migrate.py (resumable ETL, checkpoints in migration_status).
- Integer `id` fields everywhere (Odoo ids preserved for migrated data; counters for new: leads from 500000, messages 5M, users 1000).
- Collections: users, leads (custom dict holds raw x_studio fields), messages (lead chatter), activities, catalogs (type-scoped: tag/stage/lost_reason/lead_stage/follow_up_tag/utm_*/activity_type/source_lead), templates_email, templates_whatsapp, wa_channels, wa_messages, contacts, webhooks, automations, saved_filters, saved_filters_odoo (raw), settings, outbound_queue, migration_status, counters, login_attempts.
- Dates stored as "YYYY-MM-DD HH:MM:SS" UTC strings + create_date_ist for IST day/month grouping.
- Odoo creds in backend/.env (ODOO_URL/DB/LOGIN/PASSWORD) for migration.

## New cases 18-24 (2026-07-01, batch 17) — verified iteration_12 (10/10 backend, frontend 100%)
- **Case 18 Dashboard date filter**: `/reports/dashboard?date_from&date_to` scopes funnel/chart/leaderboard/tags; default (no range) keeps all-time funnel. UI date pickers + Clear + "In range" summary.
- **Case 19 Follow-up time**: added `follow_up_time` field (EDITABLE_FIELDS + LeadCreate + list projection) + time input in LeadDetail follow-up section.
- **Case 20 Duplicate flag**: `check_duplicate()` by phone_digits (active leads) on all 3 creation paths (manual/webhook/facebook); sets is_duplicate + duplicate_of + chatter note; amber "Duplicate" badge in LeadDetail header (links to original) + "Dup" tag in Leads list.
- **Case 22 Attachment eye/view**: eye icon opens an inline preview modal (image/PDF) with close; blob URL revoked on close.
- **Case 23 WhatsApp per-message status**: wa webhook now parses `statuses[]` → updates wa_messages.status/status_at/error + status_history; UI shows Queued/Sent/Delivered/Read/Failed/Received badges per message (outbound w/o status → "Sent").
- **Case 24 Agent status time tracking**: backend already locks start+end+duration on each /agent/status change; added "Show all statuses (full timeline)" toggle in Break Reports (breaks_only=false).
- **Case 21 WhatsApp not working**: PENDING clarification from user — most likely the live-send block (WABA #200 permissions + no phone_number_id). Awaiting exact symptom.


- Root cause of user's "saving but not connecting / no leads": NOT a CRM bug (backend 7/7, frontend 100%). Webhook verify (GET challenge), HMAC-SHA256 signature check, leadgen fetch, and lead mapping all work correctly. Issue is Meta-side: Page not subscribed to `leadgen`, app not in Live mode / no Advanced access to leads_retrieval, or webhook callback URL/verify token mismatch in Meta App Dashboard.
- Added `GET /api/admin/facebook/diagnose` + **"Check connection"** button (Admin → Facebook, `fb-diagnose-button` / `fb-diagnose-result`): live-checks token validity, token↔page match, and whether the Page is actually subscribed to leadgen, returning a specific `next_step`. This is the tool to pinpoint the real problem on production.
- Known minor (not fixed): PATCH /api/admin/settings uses $set only (can't unset keys); Field Mapping dropdown shows blank for legacy 'name' target (canonical is 'contact_name'). Neither blocks FB leads when configured via the UI dropdowns.


- Templates → Email editor now has a labeled **"Email HTML body"** textarea (accepts full HTML: tags, inline styles, links, tables) and a **Live Preview** with a **Rendered / HTML source** toggle. Rendered mode renders the HTML design via dangerouslySetInnerHTML with {{1}}/{{2}}/{{3}} → sample values; source mode shows raw HTML. Email sends already use html=True so HTML delivers correctly.
- testing_agent iteration_10: frontend 100% (41/41). WhatsApp template regression clean (plain-text preview, wa_template_name+lang inputs). Defensive note: templates are admin/manager-authored only; DOMPurify sanitization could be added later if non-admins ever get edit rights.
- Note: "Ozonetel not configured" tooltip on the lead Call button in PREVIEW is expected (telephony API key/campaign not seeded in preview DB); production has it configured.


- Comprehensive test across Cases 1-17: backend 27/27 pytest pass, frontend 100%. No functional bugs found. Suite saved at `/app/backend/tests/test_iter9_full_regression.py`.
- Verified: Case1/3 automations (multi-action, on_stage_set/on_tag_set), Case2 custom fields render+save in lead form, Case4 Facebook test-lead, Case5 click-to-dial (`click-to-dial-button`) + Calls tab recordings, Case6 multi-device auth + Bearer token, Case7 Excel/PDF export, Case9/10 webhook intake + setup guide, Case11 attachments lifecycle, Case12/13 Manage Users, Case14 Marketing, Case15 "New / Unassigned", Case16/17 template editor+preview.
- Polish added this batch: `DELETE /api/users/{id}` (admin-only; blocks self/last-admin/users-with-active-leads) + Delete button in Manage Users (`delete-user-{id}`). Cleaned up leftover test users (1002-1004).
- Still MOCKED/QUEUED pending user action: WhatsApp live send (WABA #200 perms + no phone_number_id) and Gmail email (OAuth not yet connected) — both QUEUE, not bugs.


- Integrated **Gmail API send via Google OAuth 2.0** (`core/gmail_send.py`, `routes/gmail.py`): auth-url → consent → callback stores refresh token in `settings.key=gmail`; auto-refreshes access token; sends MIME email via `users.messages.send`. Endpoints: `/api/admin/gmail/auth-url`, `/api/oauth/gmail/callback`, `/api/admin/gmail/status`, `/api/admin/gmail/disconnect`, `/api/admin/gmail/send-test`.
- Wired live send: lead `send_email` and marketing **email** campaigns now send live via Gmail when connected (subject/body with {{1}}→lead name), else QUEUE.
- New **Admin → Email** tab: Connect Google account, shows required redirect URI to register, status (connected email), test-send, disconnect. Query-param toast on `?gmail=connected`.
- Creds in backend/.env: GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, GMAIL_REDIRECT_URI (preview). Verified: auth-url generates valid Google consent URL; status endpoint works; UI renders.
- ⚠️ ACTION REQUIRED by user to go live: in Google Cloud Console add redirect URI `https://odoo-sync-ready.preview.emergentagent.com/api/oauth/gmail/callback` (and the production one after deploy), enable Gmail API, add gmail.send scope, add account as test user if app in Testing, then click Connect. The previously-registered `homeivf.com/google_account/authentication` URI does NOT work for the CRM. Live send unverified until connected.


- Added `POST /api/admin/whatsapp/sync-odoo-templates` (admin): pulls Odoo `whatsapp.template` records (`template_name`, `lang_code`, `status`, `template_type`) and links them onto CRM `templates_whatsapp` by name → sets `wa_template_name` + `lang` + `status`. Ran it: **54/54 approved templates linked** (e.g. "Appointment Booking 2" → `appointment_booking_2`). UI button: Admin → WhatsApp → "Sync approved templates from Odoo".
- Template editor now shows the approved Meta name pre-filled + live preview.
- ⚠️ Multi-variable templates (e.g. appointment_booking_3 uses {{1}}..{{5}}) — `send_lead_template` currently only auto-fills {{1}} (lead name). Live multi-variable sending will need per-variable→lead-field mapping. Live WA send still blocked on WABA `30291513857161871` permissions (#200) + Phone Number ID.


- **Case 7 — Exports** (`routes/export.py`): `GET /api/export/leads.xlsx` (date range + all lead filters, styled openpyxl, role-scoped) and `GET /api/export/report.pdf` (reportlab summary: totals, conversion rate, by stage/source/agent). UI: Reports page **Export bar** with date pickers + Excel/PDF buttons.
- **Case 11 — Lead attachments** (`routes/attachments.py` + `core/storage.py`): multiple files per lead (medical reports etc.) via Emergent object storage; upload/list/download(soft-auth via cookie/?auth=/Bearer)/soft-delete. UI: **Attachments tab** on LeadDetail with drag-drop dropzone (25MB cap), download & delete.
- **Case 14 — Marketing** (`routes/marketing.py`): campaigns CRUD + `/audience-count` + `/send`. Audience = lead filters (stage/source/tag/city/state). WhatsApp sends live via Cloud API when configured else QUEUES; email always QUEUES (no provider yet). New **/marketing** page + nav (Megaphone).
- **Case 5 — Calls tab** on LeadDetail now shows recording `<audio>` player + duration + disposition (click-to-dial already existed).
- **Case 16/17 — Template editor**: live preview pane (renders {{1}}→sample name); WhatsApp templates gained `wa_template_name` + `lang` fields (used by live Cloud send).
- **Case 15 — "Undefined" lead stage** relabeled to **"New / Unassigned"** in dashboard funnel, trends, and pivot.
- **Case 6 — Robust auth**: Bearer-token fallback — login stores JWT in localStorage (`hivf_token`), axios attaches it as Authorization header so auth survives browsers that block cross-site cookies (Safari ITP / mobile in-app browsers / strict 3p-cookie). Cookie path unchanged.
- **WhatsApp token**: user-provided System User token stored (valid/decrypts) but WABA `30291513857161871` returns Meta (#200) permission errors → needs `whatsapp_business_management`+`whatsapp_business_messaging` perms + System User assigned to WABA + a Phone Number ID. Until then WA marketing/template sends QUEUE.
- **Already complete from prior batches (verified)**: Case 1 & 3 (automation triggers on tag/stage + WA/email/assign/tag actions), Case 2 (drag-drop custom-field builder + typed rendering in lead form), Case 4 (Facebook Page field-mapping + test), Case 9/10 (webhook capture + new setup guide & sample HTML form in Admin→Webhooks), Case 12/13 (Manage Users: create/role/activate/reset-pwd).
- **STILL NEEDS USER INPUT**: email provider for live email (Resend/SendGrid/SMTP) — currently queued; WhatsApp WABA permissions + Phone Number ID for live WA.


- **§6 Agent Productivity & Call Analytics** (`routes/agent.py` GET `/api/agent/analytics?date=`): role-aware daily per-agent metrics from call_events grouped by created_at_ist day — total, connected, missed, outbound, incoming, avg_duration, talk_time, conversions (disposition=Converted), break_seconds (status_logs), connect_rate. Returns {date, is_manager, agents[], totals{}}. Managers/admins see full active-agent roster (zero-activity rows hidden); callers see only their own row.
- **Call Center page** (`CallCenter.jsx`): new tabs — **Agent Analytics** (admin/manager, 6 summary cards + per-agent leaderboard table w/ trophy on top row + date picker), **My Stats** (callers — own analytics), **Pending Queue** (all roles — queued outbound calls awaiting dial via `/api/calls?status=queued`). Manager-only tabs (Agent Analytics, Agent Live Status, Break Reports) hidden from callers.
- **Dedicated test Agent login** created for agent-level functionality testing: agent@homeivf.com / Agent@2026 (role=caller, id 1001). Sample call_events + break status_logs seeded for today (preview only) so dashboards are demonstrable.
- Login bug ("can't login from interface") was NOT reproducible on preview — backend curl + UI login both succeed (200, cookies set). Concluded production-only / stale-deploy; awaiting user confirmation.


## Implemented (2026-06-24, batch 9) — Ozonetel Auto-Dialer Phase 2 (call-center) — 21/21 tests + 6/6 frontend e2e (iteration_6)
- **§5 Agent break/status system** (`routes/agent.py`): statuses Available / On Call / Lunch Break / Washroom Break / Refreshment Break / Meeting / Offline. POST/GET `/api/agent/status`, `/api/agent/me`; `status_logs` collection tracks every status span with durations; break time = time in break statuses. Header **AgentStatusSwitcher** (all roles) persists status.
- **§4 In-call disposition popup**: IncomingCallBanner now logs an outcome — Interested / Not interested / Call back later (+ follow-up datetime) / Converted (+ notes). `POST /api/calls/{id}/disposition` updates the call, tags the lead with the disposition, sets stage "Converted" on Converted, sets follow_up_date on Call back later, and logs to chatter.
- **§7 Call Center page** (`/call-center`, nav added): tabs Call Logs (with recording audio player + disposition), Missed Calls (status=missed), Agent Live Status (admin/manager — live agent grid w/ status + break-today, auto-refresh), Break Reports (admin/manager — per-date break log table). `GET /api/calls` gained a `status` filter; `GET /api/agent/live` & `/api/agent/status-logs`.
- All QA/test artifacts purged. Removed a test that hit the live dialer once campaign was configured.
- **Still TODO (Phase 3 of brief)**: §6 Agent productivity & call analytics dashboard (daily per-agent calls/connected/missed/avg duration/talk time/break time/conversion), and a Pending Queue view (leads pushed to dialer awaiting dial).

## Implemented (2026-06-24, batch 8) — Ozonetel Auto-Dialer Phase 1 (per "Auto Dialer Logic Brief") — 20/20 calls+changes tests pass
Campaign confirmed: **Autocallback_homeivf** (Progressive, Nonagentwise, DID 919262104390) → Ozonetel's own dialer handles FCFS + agent assignment; the CRM feeds leads + records outcomes.
- **§3 Autodialer feed**: `POST /api/calls/push-to-dialer` {lead_ids[]} → AddCampaignData to the campaign (checkDuplicate=true, no agentId since Nonagentwise). Leads page → select leads → **"Push to Dialer"** button (bulk bar). Click-to-dial ("Call" on a lead) now works too (campaign_name set).
- **§1/§2 CDR callback**: `POST /api/calls/ozonetel/cdr` (Ozonetel form-encoded `data` JSON) → enriches the screen-pop call_event (status/duration/TalkTime/recording AudioFile/disposition) by ucid, or creates one; **auto-creates a lead** if the number is new — source "Ozonetel Incoming Call" (answered) / "Ozonetel Missed Call" (NotAnswered, tagged "Missed Call") / "Ozonetel Outbound Call"; logs to chatter with recording link. Lead creation happens at CDR (has duration+recording), NOT on the ring (avoids spam-lead creation).
- catalog `_ensure_catalog` get-or-creates source/tag with max-id+1 (migrated catalogs bypassed the counter).
- campaign_name="Autocallback_homeivf", dial_did="919262104390" seeded in preview settings.
- **Production URLs** (live after redeploy): Screen-Pop (frontend) `https://crm.homeivfmarketing.com/screen-pop?phoneNumber={phoneNumber}&ucid={ucid}&callerID={callerID}&did={did}&agentID={agentID}&phoneName={phoneName}` ; CDR callback (backend) `https://crm.homeivfmarketing.com/api/calls/ozonetel/cdr`.
- **STILL TODO (Phase 2/3 of brief)**: agent status/break system (§5) + Agent Live Status, enhanced agent popup with disposition buttons & notes (§4), agent productivity & call analytics (§6), dedicated tabs (Pending Queue, Call Logs, Missed Calls, Agent Analytics, Break Reports) (§7).

## Bug fix (2026-06-22) — Production "logs in then instantly logs out"
- Root cause: production frontend is served from custom domain https://crm.homeivfmarketing.com but its bundle calls the backend at https://hi-connect-1687.emergent.host (cross-site). Auth cookies were `SameSite=lax`, so the browser set them on login but refused to send them on the background `auth/me`/`refresh` XHR → 401 → redirect to /login (instant logout). Backend auth itself was fine (curl login + auth/me → 200 on both envs).
- Fix: `core/security.set_auth_cookies` now issues cookies with `SameSite=None; Secure` (was lax) so they ride cross-site XHR. CORS already reflects the origin with credentials. Verified on preview: login → auth/me → refresh all 200 with SameSite=None. REQUIRES REDEPLOY to take effect on production.

## Implemented (2026-06-17, batch 7) — Live WhatsApp Cloud API + Facebook app creds — 17/17 + 8/8 backend tests pass
- **WhatsApp Business Cloud API** (`core/whatsapp_cloud.py`, `routes/wa_cloud.py`): live template + session-text sending wired into per-lead WhatsApp send (leads.py), automation `send_whatsapp_template` action (utils.py), and free-text WhatsApp thread (whatsapp.py). Inbound webhook GET/POST `/api/webhooks/whatsapp` (verify handshake + X-Hub-Signature-256 + mirrors to wa thread + logs to matching lead chatter). Admin endpoints: status, phone-numbers, templates, send-test. Admin → WhatsApp tab (config form w/ masked secrets, copy-able callback URL, fetch phone numbers/templates, "Use" to set phone_number_id, send test). Live send gated on access_token+phone_number_id; otherwise safely queues (pending_api_credentials) — no behavior change for unconnected state.
- **Facebook** Admin tab now pre-seeded with user's App ID + App Secret. Lead Ads still needs Page ID + Page Access Token to go live.
- **BLOCKER (user action)**: WhatsApp System User token provided failed Meta validation (OAuth 190 — truncated in paste). Need a clean token + Phone Number ID; and the Facebook Page ID + Page Access Token. Then redeploy.

## Implemented (2026-06-17, batch 6) — Odoo-parity "changes & issues" doc — 14/14 backend tests + 100% frontend e2e (iteration_5)
Production: https://crm.homeivfmarketing.com (built in preview; redeploy to push). Autodialer ON HOLD per user.
- **Case 1/3 — Automations like Odoo (multi-action)**: a rule now runs MULTIPLE actions in order (Admin → Automations → New rule → "+ Add another action"). Action types: Send WhatsApp template, Send Email template, Add tag, Set lead stage, Assign to user. Engine already iterated the actions list; UI now builds it. Per-row testids automation-rule-<id> / automation-delete-<id>.
- **Case 2 — Odoo-Studio drag-drop Form Builder** (`Admin → Custom Fields`): components palette (9 field types: Text, Multiline, Integer, Decimal, Monetary, Date, Date&Time, Checkbox, Dropdown) → drag onto (or click to add into) the "Meta/Google Q&A" or "Custom Fields" section dropzones; drag field cards to reorder (persisted via `sequence` + POST /catalogs/custom-fields/reorder); hard-delete affordance on disabled fields. Lead detail (FieldEditor/fieldDisplay) renders the correct typed input (date/number/checkbox/textarea/select) and value formatting (₹ for monetary, Yes/No for checkbox). `custom_fields` gained `sequence`; create validates field_type; DELETE supports `?hard=true`.
- **Case 4 — Facebook Lead Ads → CRM** (`routes/facebook.py`, ready-to-connect): public GET `/api/webhooks/facebook` (Meta verify handshake), public POST `/api/webhooks/facebook` (validates X-Hub-Signature-256 with App Secret, fetches each lead via Graph API v25.0 + Page Access Token, maps fields → CRM lead, round-robin assigns, fires on_create automations). Admin endpoints: `/admin/facebook/test` (simulate a lead to verify mapping without Meta), `/admin/facebook/subscribe` (subscribe Page to leadgen), `/admin/facebook/status`. Admin → Facebook tab: config form (App ID/Secret/Page ID/Page Token/Verify Token/Graph version — secrets masked), copy-able callback URL, field-mapping editor (FB field → CRM field incl. custom fields), "Send test lead". Config in DB settings key="facebook" (no secrets in source). Unmapped FB answers land in the lead's Q&A card as x_custom_*.
- New tests: tests/test_changes.py (6). All QA artifacts purged; real migrated chatter untouched.
- **User action to go live (Case 4)**: in Admin → Facebook enter your Meta App ID/Secret, Page ID, Page Access Token (perms: leads_retrieval, pages_manage_metadata) + a Verify Token, Save, then in Meta App → Webhooks subscribe the page to `leadgen` using the shown callback URL + verify token (or click "Subscribe Page to leadgen"). Live delivery needs the Meta app reviewed/approved.

## Implemented (2026-06-15, batch 5) — TifTech rebrand + Ozonetel telephony (incoming-call screen-pop) — 8/8 calls tests + 100% frontend e2e (iteration_4)
- **Rebrand**: "Powered by TagQuest" → "Powered by TifTech" everywhere (Login, sidebar, index.html title/meta/og, /api/health). No "TagQuest" string remains.
- **Ozonetel incoming-call integration** (`backend/routes/calls.py`):
  - PUBLIC `GET/POST /api/calls/ozonetel/screenpop` — Ozonetel hits this on each incoming call (params: phoneNumber, ucid, callerID, did, agentID, phoneName, type, campaignID...). Matches caller→lead by phone_digits, matches agent→CRM user (ozonetel_agent_id / ozonetel_phone_name), records call_events, logs "📞 Incoming call … (via Ozonetel)" to lead chatter. Idempotent per ucid.
  - `GET /api/calls/active` (auth) — live incoming call for the logged-in agent (last 45s, matched by mapping/user_id) → powers the floating IncomingCallBanner (polls every 5s, mounted in Layout).
  - `GET /api/calls` (paginated, caller-scoped), `GET /api/calls/lead/{id}` — call history (shown in lead-detail "Calls" tab).
  - `POST /api/calls/dial` (auth) — click-to-dial via Ozonetel AddCampaignData API (https://{domain}/ca_apis/AddCampaignData); guarded → HTTP 400 with clear message until an outbound campaign is configured.
- **Agent mapping**: users gained ozonetel_agent_id / ozonetel_phone_name (users.py UserUpdate); editable in Admin → Telephony.
- **Frontend**: ScreenPop.jsx (PUBLIC route /screen-pop for Ozonetel iframe — matched lead card / no-match / open-in-CRM), IncomingCallBanner.jsx, Admin → Telephony tab (config form, copy-able Screen-Pop URL, agent-mapping table, recent-calls table; API key field masked), LeadDetail Call button + Calls tab.
- **Config** stored in DB settings key="ozonetel" (domain in1-ccaas-api.ozonetel.com, username homeivf, api_key, campaign). Pre-seeded with user's real key/username (campaign blank — user to fill for click-to-dial). NOT hardcoded in source.
- Data hygiene: all QA/test call_events + chatter purged; real migrated Odoo "Incoming call" chatter preserved. New suite: tests/test_calls.py (8 tests).
- Screen-Pop URL to paste in Ozonetel (Admin → Settings → Screen Pop URL): `https://<crm-domain>/screen-pop?phoneNumber={phoneNumber}&ucid={ucid}&callerID={callerID}&did={did}&agentID={agentID}&phoneName={phoneName}`

## Implemented (2026-06-11) — Phase 1 COMPLETE & TESTED (32/32 backend tests, all frontend flows pass)
- JWT auth (cookies + bearer), brute-force lockout, admin seed, change-password
- User management (roles, activate/deactivate, password reset)
- Leads: list (filters: search/stage/tags/caller/source/follow_up/active/dates; sort; pagination on 99.5K), group_counts (Odoo-style group-by incl. tags unwind + day/month), kanban by lead_stage, detail, create, PATCH w/ change-tracking to chatter, lost/restore, bulk (assign/tags/stage/archive/follow_up)
- Chatter: migrated history + notes/logs, activities (schedule/done/cancel, my-queue)
- Follow-ups page (overdue/today/upcoming)
- WhatsApp inbox: 10,936 migrated conversations + threads; sends queue (pending API creds)
- Reports: pivot engine (rows×sub-rows×cols, label resolution, totals) + 8 presets + dashboard (KPIs, 14-day chart, funnel, leaderboard, top dispositions)
- Templates: WA (55) + Email (32) migrated, full CRUD
- Webhooks: public lead-capture endpoints w/ field aliasing, round-robin auto-assign, hit counter
- Automations: on_create/on_tag_set/on_stage_set → send template (queued)/add tag/set stage/assign
- Admin panel: Users/Tags/Dropdowns/Webhooks/Automations/Assignment/Migration tabs
- Saved filters (per-user, shareable)
- Full migration: catalogs, 27 users, templates, 99,516 leads, 16 activities, 10,936 WA channels, ~38.7K WA messages, ~910K lead messages, 96K contacts (background, resumable)
- HomeIVF branding (scraped logo, soft blue/violet, Nunito/Figtree), "Powered by TagQuest", data-testids everywhere

## Implemented (2026-06-11, batch 2) — Drill-downs, Sorting, Audit, Visual Analytics (50/50 tests pass, iteration_2)
- Pivot reports: raw keys returned → EVERY cell/row/child clickable, drills to /leads with combined filters; column-header sorting; FULL filter bar (date/status/caller/tag/stage/source/FU tag/ads platform/campaign/state/city)
- Dashboard fully clickable: KPIs, funnel rows, leaderboard rows, top tags, chart bars → filtered leads
- Leads table: sortable column headers (whitelisted sort fields), FU Tag filter, more filter chips (campaign/ads/state/city/lost_reason)
- Follow-ups: whole row clickable → lead detail; Quick Note modal (note + reschedule + disposition tag) without leaving page
- Migration Audit tool (Admin > Migration): live XML-RPC count comparison Odoo vs CRM per entity with ✓/✗ + explanatory notes; persisted to settings.last_audit. Notes: Odoo keeps growing while team still uses it → rerun migration script (resumable, upserts) to sync deltas before cutover
- Visual Analytics (Reports tab): stacked-area lead volume trend (day/week/month), conversions + conversion-rate dual-axis line, source donut (clickable), DOW×Hour incoming heatmap (90d IST), Caller×Day load heatmap (clickable cells) — recharts + custom CSS heatmap grids
- All Emergent branding removed; title/meta = "HomeIVF CRM | Powered by TagQuest", HomeIVF logo favicon
- Data-completeness facts (verified): all 10,936 WA channels have clean 10-digit phones; 99,532 leads have chatter; Odoo only stores OPEN activities (16) — done activities live in chatter (faithful migration)

## Implemented (2026-06-11, batch 3) — Odoo Delta Sync + Production Audit (54/54 tests pass)
- **Odoo Sync** (Admin > Migration): last-record timestamps (lead activity, chatter — IST), last sync run, full reconciliation counts; "Sync Now" → confirm modal stating exact window ("from X UTC → now") + rules (Odoo wins on conflicts, CRM-created leads untouched); background sync via migration/odoo_sync.py (subprocess, tracked in sync_runs, polled live in UI); completion shows per-entity new/updated + new totals; settings.last_sync persisted. Empty DB → auto FULL import mode (production bootstrap).
- Live-verified delta sync: +93 leads, 95 updated, +454 chatter, +8 WA chats, +46 WA msgs, +68 contacts in 14s; post-sync audit = ALL ENTITIES MATCH (99,609 = 99,609 leads; 910,638 = 910,638 chatter).
- Sync semantics: leads by write_date>=since (15-min overlap buffer); messages/wa_messages/contacts by id>checkpoint; users & templates INSERT-ONLY (CRM-side role/password/template edits preserved); catalogs upsert; open activities upsert.
- **Production audit**: zero hardcoded URLs/dummy/mock/demo code (grep-verified); all config via env fail-fast; only intentional queue behaviors (WhatsApp/email sends pending API creds, clearly labeled); e2e flows (create lead, notes, activities, follow-ups, quick notes, bulk, webhook intake) covered by 54-test suite. Refactor: odoo_migrate.py now exposes get_lead_fields() + transform_lead() shared with sync.
- New endpoints: GET /api/admin/sync/status, POST /api/admin/sync/start (admin-only, 409 if already running, stale-run recovery), GET /api/admin/sync/runs(+/{id}). New tests: tests/test_sync.py.
- ⚠️ DEPLOYMENT NOTE: production (hi-connect-1687.emergent.host) has its OWN empty database — after redeploying these features, click "Sync Now" there once: it auto-detects empty DB and runs the full import into production.

## Implemented (2026-06-12, batch 4) — "CRM Testing Points" PDF: ALL 8 CASES COMPLETE & TESTED (iteration_3: 25/25 case tests pass)
- Case 1: Address (street) + City + State dropdown (36 states) + Country dropdown (19) on lead Contact card — editable, persisted
- Case 2: "New tag" button + popup on lead detail; any user can create disposition tags (matches Odoo); tag auto-added to lead + global catalog
- Case 3: "Meta / Google Q&A" card on lead detail — landing-page/ads questionnaire answers shown separately with heading, editable, for agent confirmation on calls
- Case 4: Custom Fields builder (Admin > Custom Fields tab) — like Odoo Studio: label, text/dropdown type, section (Q&A card or Custom Fields card), webhook/ads aliases for auto-capture from landing pages & Google/Meta lead forms; fields instantly render + editable on every lead; webhook intake maps aliases → lead.custom
- Case 5: WhatsApp template popup on lead (55 templates, search + preview + phone override) → queues to outbound_queue + chatter log (live send once Meta API connected)
- Case 6: Compose Email modal on lead (To/Subject/HTML body, 32 templates, save-as-template) → queues + chatter log (live once SMTP connected)
- Case 7: UTM Source / UTM Medium / UTM Campaign dropdowns on Attribution card (catalogs utm_*, managed in Admin > Dropdowns)
- Case 8: Automation triggers (Admin > Automations): when tag added / lead stage changes / lead created → send WhatsApp template, send email template, add tag, set stage, assign. FIXED bug: on_stage_set now fires on lead_stage change (UI stepper), not only stage_id; bulk add_tags/set_stage/set_lead_stage now fire automations per lead
- Bug fixes: catalogs.py route-ordering (custom-fields PATCH/DELETE 404 — specific routes now before generic /{ctype}/{cid}); reports.py trends + caller_day heatmap 500s (KeyError on missing $group _id keys → .get())
- All TEST_* artifacts purged from DB (50 leads, 22 tags, 13 fields, 10 webhooks)
- New test suite: tests/test_crm_8_cases.py (25 tests)

## Backlog
### P0 (Phase 1.5 — needs user API credentials)
- Meta WhatsApp Business API live send/receive (process outbound_queue, webhook for inbound)
- MyOperator auto-caller/OBD integration + call logging
- SMTP/Gmail outgoing email (welcome emails, templates)
### P1 (Phase 2 — AI, user-approved Emergent LLM key)
- AI insights/recommendations panels per section (lead scoring, next-best-action, caller coaching)
- AI Brain: conversational analytics chat over CRM data (sessions, multi-turn)
### Hotfix 2026-06 — Production stall (team locked out after redeploy)
- Symptom: after redeploy, Leads list + Reports/AI Insights spun forever; whole team blocked.
- Root cause: startup ran ~30+ create_index() SERIALLY with await — on large prod collections (leads 110k, follow_ups 73k) this blocked FastAPI startup/readiness (crash-loop → nothing served); AI /analytics also ran 7 aggregations sequentially.
- Fix: server.py moves ALL index creation into a non-blocking background task (asyncio.create_task(_ensure_indexes())) with per-index try/except (log shows 'Startup complete' before 'Index ensure pass complete'). routes/ai.py /analytics runs aggregations concurrently via asyncio.gather(return_exceptions=True) + maxTimeMS=15000 (fails fast, partial-safe). Verified iteration_48 (100%, suite /app/backend/tests/test_prod_stall_fix.py).

### Phase 2 2026-06 — AI Insights dashboards + AI Brain (LIVE)
- New "AI Insights" page (nav + route /ai-insights, perm 'reports'). Advanced charts via recharts: Conversion Funnel, Leads Trend (30d), Source Performance (leads vs converted), Caller Performance (conversion %), Ad Platform pie, Top States. All from GET /api/ai/analytics (concurrent, index-backed, ~1s). KPIs: total/converted/conversion_rate.
- AI Brain chat: POST /api/ai/brain — GPT-5.5 (openai) via Emergent Universal Key (emergentintegrations LlmChat) translates a plain-English question → JSON query spec → safe indexed aggregation → answer + dynamic chart (bar/line/pie/number). Session-scoped history in db.ai_chats; GET /api/ai/brain/history. Null buckets excluded from answers.
- Files: routes/ai.py (reuses reports DIMS/build_match/resolve_labels), pages/AiInsights.jsx, Layout.jsx nav + AI Brain card, App.js route. Backend key EMERGENT_LLM_KEY in backend/.env.
- Verified iteration_47 (100%, suite /app/backend/tests/test_ai_insights.py): analytics ~1.5s, brain 3–8s, RBAC 403 for caller role, all charts render.

### Perf 2026-06 — Go-live optimization (indexes)
- Root cause of slowness on large prod data (110k leads / 1M msgs / 73k follow_ups): follow_ups & caller_activities had NO index (COLLSCAN on every lead-detail open); several report/dashboard match patterns lacked compound indexes.
- Fix (server.py startup, additive/no logic change): added follow_ups [(lead_id,follow_up_date)], follow_up_date, [(source,lead_id)]; caller_activities [(lead_id,created_at)]; wa_tracking lead_id/campaign_id/wamid; leads [(active,follow_up_date)], [(active,user_id)], source_lead, stage_id. All lists already paginated; dashboard bounds by_day window.
- Verified iteration_46 (100%, regression suite /app/backend/tests/test_perf_sections.py): dashboard 0.26s, leads 0.53s, pivots 0.22s, followups 0.13s. No regressions.

### Feature 2026-06 — Duplicate Lead Cleanup + Odoo follow-up → Follow-up entry
- CASE 1 (Duplicate cleanup, Admin > Migration): scan groups leads by phone_digits, keeps the OLDEST, flags newer duplicates CREATED in a date range (default 1–9 Jul) for deletion. Background scan (POST /admin/duplicates/scan → poll /status), preview table, confirm-modal delete (POST /admin/duplicates/delete) archives to deleted_leads (recoverable) then removes + cleans their follow_ups. UI: dup-cleanup-card in Admin.jsx. NOTE: scan uses an indexed two-step approach (distinct on create_date-index window → chunked $in on phone_digits-index) to avoid MongoDB ExecutionTimeout on the ~110k-lead prod dataset (verified iteration_44, ~4s).
- CASE 2 (Odoo follow-up dates): sync now mirrors each lead's Odoo follow_up_date into a real follow_ups entry (source='odoo', one per lead, idempotent) so it shows in the Follow-ups list/reminders. Covers future syncs (_ensure_followups in sync_leads) + one-time backfill of existing leads (_backfill_followups, guarded by settings.followups_backfilled). Verified iteration_43 (100%): backfill created 73,766 entries, unique ids.

### Bugfix 2026-06 — "Run Audit vs Odoo" error (gateway timeout)
- The audit ran ~15 sequential Odoo search_count calls synchronously in the HTTP request (~18-40s over 110k leads / 1M+ messages) → hit the ingress/gateway timeout → button errored in production.
- Fix: audit is now a BACKGROUND JOB. POST /api/admin/migration/audit starts a thread (using the resilient timeout+retry XML-RPC call()) and returns {status:"running"} in ~0.1s; new GET /api/admin/migration/audit/status returns settings.last_audit; frontend runAudit() polls every 3s until done. Audit table render + mount guarded against missing rows. Verified iteration_42 (100%).

### Bugfix 2026-06 — Sync worker killed by hung XML-RPC (process restart / xmlrpc __request error)
- Two prod symptoms: "sync worker no longer running (process restarted or crashed)" and an xmlrpc/client.py __request error. Cause: the Odoo XML-RPC ServerProxy had NO socket timeout, so a hung Odoo request stalled the worker until the platform killed the process.
- Fix (odoo_migrate.py): timeout-aware transports (_TimeoutTransport/_TimeoutSafeTransport, ODOO_TIMEOUT env, default 120s); _authenticate() 5x retry; call() 6x retry with backoff + re-authenticate on transient failures. Per-batch checkpoints let a re-run resume. Verified iteration_41 (100%). Regression test: /app/backend/tests/test_odoo_sync_regression.py.

### Bugfix 2026-06 — Sync worker crash (pymongo receive_message / AutoReconnect)
- Sync started fine but the worker crashed mid-run on a transient MongoDB connection drop during a large lead-chatter bulk_write (pool.py write_command receive_message).
- Fix: MongoClient now uses retryWrites=True + socketTimeoutMS=180000 (odoo_migrate.py); bulk() retries 4x on AutoReconnect/NetworkTimeout/ConnectionFailure with ordered=False (odoo_sync.py); message batch sizes cut 2000→500. Per-batch checkpoints mean re-running "Sync Now" resumes where it left off. Verified iteration_40 (100%).

### Bugfix 2026-06 — "Sync Now" 500 in production (root cause of "nothing happens")
- Real root cause: sync_status() ran uncapped $max aggregations + count_documents over large prod collections (no index → COLLSCAN → timeout → HTTP 500). Pre-fix the modal was gated on sync-status loading so the 500 left sync=null → "nothing happens". After decoupling the modal, sync_start (which called sync_status internally) surfaced the same 500 on confirm.
- Fix: new cheap _next_since() helper computes the delta window from the tiny last_sync settings doc; sync_status wraps every heavy op in try/except with maxTimeMS=8000 (returns None/0 on failure); sync_start no longer calls sync_status; stuck-run self-heal hardened. Verified iteration_39 (100%, both endpoints 200).

### Bugfix 2026-06 — "Sync Now" dead in production
- Root cause: a sync thread dying mid-run (redeploy/crash) left a sync_runs doc stuck at status "running"; frontend permanently disabled the button, and stale-cleanup only ran inside sync/start (never reached) — deadlock. Modal was also gated on sync-status loading.
- Fix: GET /admin/sync/status now self-heals dead runs via threading.enumerate() liveness check (marks error, returns running=null). POST /admin/sync/start uses same check before 409. Frontend confirm modal decoupled from sync-status; loadSync surfaces errors via toast. Verified (iteration_38, 100%).

### Cutover plan (user-confirmed 2026-06-12)
- NO scheduled auto-sync needed. One final incremental "Sync Now" just before switching off Odoo, then run standalone.
### P2
- Custom lead form builder (hosted forms posting to webhooks)
- Duplicate field cleanup (user deferred), lead dedupe/merge by phone
- CSV export, rate-limiting on public webhook, contacts page UI
- Production deploy to homeivfcrm.com

## Key Endpoints
/api/auth/*, /api/users, /api/leads (+/group_counts, /{id}, /bulk, /{id}/lost|restore|messages|activities), /api/activities, /api/catalogs/{type}, /api/templates/{whatsapp|email}, /api/whatsapp/channels (+messages, send), /api/whatsapp/lead/{id}, /api/reports/{pivot|dashboard}, /api/webhook/lead/{token} (public), /api/webhooks, /api/filters, /api/admin/{migration/status|settings|automations|outbound_queue}

## Test Assets
- /app/backend/tests/test_homeivf_api.py (32-test regression suite, run: cd /app/backend && python -m pytest tests/ -q)
- /app/memory/test_credentials.md, /app/auth_testing.md, /app/test_reports/iteration_1.json
- Odoo discovery dumps: /app/discovery/out/*.json
