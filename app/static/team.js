export function createTeamUI({ state, api, post, esc, icon, date, shell, toast, onSession, onLogout, renderDocument, handoffs }) {
  const owner = () => state.session?.user?.role === "owner";
  const canReview = () => ["owner", "reviewer"].includes(state.session?.user?.role);
  const initials = (name) => name.split(/\s+/).slice(0, 2).map((s) => s[0]).join("").toUpperCase();
  let reviewData = null;
  let showOlder = false;
  const input = (name, label, type = "text", attrs = "") => `<div class="field"><label for="account-${name}">${label}</label><input id="account-${name}" name="${name}" type="${type}" ${attrs} required></div>`;
  const error = '<p class="form-error" role="alert" data-form-error></p>';

  function authScreen() {
    const joinToken = location.hash.startsWith("#/join/") ? location.hash.slice(7) : null;
    const mode = joinToken ? "join" : state.session?.setup_required ? "setup" : "login";
    const heading = { setup: "A room for your best work.", join: "Good work is a team sport.", login: "Welcome back to your room." }[mode];
    const subtitle = { setup: "Create the first owner account. Your existing documents will be waiting inside.", join: "Accept your invitation using the email address your workspace owner invited.", login: "Sign in to pick up a draft, leave a thoughtful review, or make something new." }[mode];
    document.querySelector("#app").innerHTML = `<main class="auth-page" id="main"><section class="auth-story"><a class="brand" href="#/home"><span class="brand-mark">b.</span>briefroom</a><div><div class="eyebrow">THOUGHTFUL WORK. SHARED.</div><h1>From one good idea<br>to <em>our best work.</em></h1><p>A private home for briefs, drafts, and the conversations that make them better.</p><div class="auth-principles"><span>${icon("branch")}A visible process</span><span>${icon("layers")}Every version kept</span><span>${icon("shield")}Your team’s final say</span></div></div><small>One workspace. A little more room to think together.</small></section><section class="auth-form-wrap"><div class="auth-card"><span class="eyebrow">${mode === "setup" ? "MAKE YOURSELF AT HOME" : mode === "join" ? "YOU’RE INVITED" : "YOUR WORKSPACE AWAITS"}</span><h2>${heading}</h2><p>${subtitle}</p>${joinToken && state.session?.user ? `<div class="privacy-note">You’re signed in as ${esc(state.session.user.email)}. Sign out before accepting an invitation for another account.</div><button class="primary" data-team="logout">Sign out to join</button>` : `<form data-team-form="${mode}">${mode !== "login" ? input("name", "Your name", "text", 'minlength="2" maxlength="80" autocomplete="name"') : ""}${mode === "setup" ? input("workspace_name", "Workspace name", "text", 'minlength="2" maxlength="80" placeholder="e.g. Northstar Studio"') : ""}${input("email", "Email address", "email", 'maxlength="254" autocomplete="username"')}${input("password", mode === "login" ? "Password" : "Choose a password", "password", `minlength="${mode === "login" ? 1 : 12}" maxlength="128" autocomplete="${mode === "login" ? "current-password" : "new-password"}"`)}${mode !== "login" ? '<small class="muted">Use at least 12 characters. A memorable passphrase works well.</small>' : ""}${mode === "setup" ? `${input("setup_token", "One-time setup key", "password", 'minlength="20" maxlength="200" autocomplete="off"')}<p class="auth-hint">On the server, open <code>outputs/.setup-token</code>. This key is removed after setup and prevents someone else claiming your workspace.</p>` : ""}${error}<button class="primary auth-submit" type="submit">${mode === "setup" ? "Create your workspace" : mode === "join" ? "Join the workspace" : "Sign in"}${icon("arrow")}</button></form>`}<p class="auth-foot">${mode === "login" ? "Invite-only access. Ask your workspace owner for an invitation. There is no email password recovery in this release." : 'Your account belongs to this workspace, not to the model provider.'}</p>${mode === "join" ? '<a class="text-button" href="#/home">Already a member? Sign in</a>' : ""}</div></section></main>`;
  }

  async function page() {
    if (!state.session.auth_enabled) {
      shell('<div class="home"><h1>Team accounts are turned off.</h1><p>Enable AUTH_ENABLED in your server configuration and restart to set up your team.</p></div>', "Team");
      return;
    }
    const data = await api("/api/team");
    if (state.page !== "team") return;
    shell(`<div class="home team-page"><div class="eyebrow">BETTER, TOGETHER</div><section class="hero"><div><h1>A shared space.<br><em>A stronger point of view.</em></h1><p>${esc(data.name)} · ${data.members.filter((m) => m.active).length} active members.<br>Different roles. One considered result.</p></div></section><div class="team-columns"><section><div class="section-title"><h2>The people in your room</h2><button class="text-button" data-team="refresh">Refresh</button></div><div class="member-list">${data.members.map((m) => `<div class="member-row ${m.active ? "" : "inactive"}"><span class="profile-avatar">${esc(initials(m.name))}</span><div class="member-details"><strong>${esc(m.name)}${m.id === state.session.user.id ? ' <span class="muted">(you)</span>' : ""}</strong><small>${esc(m.email)}</small><span class="role-tag">${esc(m.role)}${m.active ? "" : " · Deactivated"}</span></div>${owner() ? `<form data-team-form="access" data-member="${m.id}"><select name="role" aria-label="Role for ${esc(m.name)}">${["owner", "editor", "reviewer"].map((r) => `<option ${r === m.role ? "selected" : ""}>${r}</option>`).join("")}</select><label class="check-label"><input type="checkbox" name="active" ${m.active ? "checked" : ""}>Active</label><button class="secondary" type="submit">Save</button>${error}</form>` : ""}</div>`).join("")}</div>${owner() ? `<section class="detail-card invite-history"><h3>Invitations</h3>${data.invitations.length ? data.invitations.map((i) => `<div class="invitation-row"><div><strong>${esc(i.email)}</strong><small>${esc(i.role)} · ${esc(i.status)}</small></div>${i.status === "pending" ? `<button class="text-button danger" data-team="revoke" data-id="${i.id}">Revoke</button>` : ""}</div>`).join("") : '<p class="muted">No invitations yet.</p>'}</section>` : ""}</section><aside>${owner() ? `<div class="detail-card invite-card"><span class="eyebrow">PULL UP A CHAIR</span><h2>Invite a teammate</h2><p>Invite by email, then share their private link yourself. No email is sent automatically.</p><form data-team-form="invite">${input("email", "Their email", "email", 'maxlength="254"')}<div class="field"><label for="invite-role">Their role</label><select id="invite-role" name="role"><option value="reviewer">Reviewer — discuss & approve</option><option value="editor">Editor — create & edit</option></select></div>${error}<button class="primary" type="submit">Create invitation ${icon("plus")}</button></form><div id="invite-result" role="status"></div></div>` : ""}<div class="detail-card role-guide"><h3>A role for every contribution</h3><p><strong>Owners</strong> manage access, create, edit, and approve.</p><p><strong>Editors</strong> turn briefs into drafts, edit, and restore versions.</p><p><strong>Reviewers</strong> discuss the details and approve or request changes.</p><p class="muted">Everyone can read, comment, resolve discussions, and export. All documents in this workspace are shared with all active members.</p></div></aside></div></div>`, "Team");
  }

  function reviewContent() {
    if (!state.doc.artifact) return '<div class="detail-panel"><h2>The conversation starts with a draft.</h2><p>Review tools appear when the document is ready.</p></div>';
    if (!reviewData || reviewData.docId !== state.doc.id) return '<div class="detail-panel"><p>Loading team review…</p></div>';
    const d = state.doc;
    const current = reviewData.threads.filter((t) => t.version === d.version);
    const open = current.filter((t) => !t.resolved).length;
    const threads = showOlder ? reviewData.threads : current;
    return `<div class="detail-panel review-panel"><div class="review-heading"><div><div class="eyebrow">MAKE THE WORK BETTER</div><h2>A conversation, not a handoff.</h2><p>Version ${d.version} · ${open} open discussion${open === 1 ? "" : "s"}. Comments stay with the version they reviewed.</p></div><button class="secondary" data-team="review-refresh">Refresh</button></div><div class="review-columns"><section><div class="detail-card"><h3>Leave a thoughtful note</h3><form data-team-form="comment"><div class="field"><label for="comment-section">About</label><select name="section" id="comment-section"><option value="">The whole document</option>${d.artifact.draft.sections.map((s, i) => `<option value="${i}">${esc(s.heading)}</option>`).join("")}</select></div><div class="field"><label for="comment-body">Your comment</label><textarea id="comment-body" name="body" required maxlength="4000" placeholder="A question, a suggestion, or a detail to check…"></textarea></div>${error}<button class="primary" type="submit">Add comment ${icon("arrow")}</button></form></div><div class="review-filter"><h3>Discussions <span class="muted">${threads.length}</span></h3><button class="text-button" data-team="older" aria-pressed="${showOlder}">${showOlder ? "Show current version only" : "Include earlier versions"}</button></div>${threads.map((t) => `<article class="detail-card discussion ${t.resolved ? "resolved" : ""}"><div class="discussion-heading"><span class="profile-avatar">${esc(initials(t.author.name))}</span><div><strong>${esc(t.author.name)}</strong><small>${date(t.created_at)} · Version ${t.version}</small></div><span class="role-tag">${t.resolved ? "Resolved" : "Open"}</span></div><div class="discussion-anchor">${esc(t.section_title || "Whole document")}</div><p class="comment-body">${esc(t.body)}</p>${t.replies.map((r) => `<div class="reply"><strong>${esc(r.author.name)}</strong><small>${date(r.created_at)}</small><p class="comment-body">${esc(r.body)}</p></div>`).join("")}<div class="discussion-actions"><button class="text-button" data-team="resolve" data-id="${t.id}" data-resolved="${!t.resolved}">${t.resolved ? "Reopen discussion" : "Mark resolved"}</button>${t.resolved_by ? `<small>Resolved by ${esc(t.resolved_by.name)}</small>` : ""}</div>${!t.resolved ? `<form class="reply-form" data-team-form="reply" data-thread="${t.id}"><label class="sr-only" for="reply-${t.id}">Reply to ${esc(t.author.name)}</label><textarea id="reply-${t.id}" name="body" required maxlength="4000" placeholder="Add to the conversation…"></textarea><button class="secondary" type="submit">Reply</button>${error}</form>` : ""}</article>`).join("") || '<div class="detail-card empty-discussions"><h3>A fresh pair of eyes makes a difference.</h3><p>No discussions on this version yet. What needs a second look?</p></div>'}</section><aside><div class="detail-card review-decision"><span class="eyebrow">THE HUMAN CHECKPOINT</span><h3>${d.approved_version === d.version ? "This version is approved" : "Ready for a decision?"}</h3><p>${d.approved_version === d.version ? `${esc(d.approved_by?.name || "A reviewer")} approved version ${d.version}.` : "Approval applies to this version only. Saving an edit or reopening a discussion clears it."}</p>${canReview() ? `<form data-team-form="decision"><div class="field"><label for="review-decision">Decision</label><select name="decision" id="review-decision"><option value="approved">Approve this version</option><option value="changes_requested">Request changes</option></select></div><div class="field"><label for="review-note">Review note</label><textarea id="review-note" name="note" maxlength="2000" placeholder="Required when requesting changes"></textarea></div>${open ? `<p class="review-warning">Resolve ${open} open discussion${open === 1 ? "" : "s"} before approving.</p>` : ""}${error}<button class="primary" type="submit">Submit review ${icon("check")}</button></form>` : '<p class="muted">An owner or reviewer can submit a decision. You can still comment and resolve discussions.</p>'}</div><div class="detail-card"><h3>Review history</h3>${reviewData.decisions.map((r) => `<div class="review-history-item"><strong>${esc(r.author.name)}</strong><span>${esc(r.decision.replaceAll("_", " "))} · v${r.version}</span>${r.note ? `<p class="comment-body">${esc(r.note)}</p>` : ""}<small>${date(r.created_at)}</small></div>`).join("") || '<p class="muted">Decisions will appear here.</p>'}</div></aside></div></div>`;
  }

  async function loadReview() {
    const id = state.doc.id;
    const [doc, review] = await Promise.all([api(`/api/documents/${id}`), api(`/api/documents/${id}/review`), handoffs.loadDocument(id)]);
    if (state.page !== "document" || state.doc?.id !== id || state.tab !== "review") return;
    state.doc = doc;
    reviewData = { ...review, docId: id };
    renderDocument();
  }

  const accountSettings = () => state.session.auth_enabled ? `<hr class="version-divider"><div class="settings-line"><span>Signed in as</span><strong>${esc(state.session.user.name)} · ${esc(state.session.user.role)}</strong></div><details class="password-settings"><summary>Change your password</summary><form data-team-form="password">${input("current_password", "Current password", "password", 'autocomplete="current-password" maxlength="128"')}${input("new_password", "New password", "password", 'autocomplete="new-password" minlength="12" maxlength="128"')}<small class="muted">At least 12 characters. This signs out your other sessions.</small>${error}<button class="secondary" type="submit">Update password</button></form></details><button class="secondary danger" data-team="logout">Sign out</button>` : "";

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-team-form]");
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector('[type="submit"]');
    if (button.disabled) return;
    button.disabled = true;
    const message = form.querySelector("[data-form-error]");
    message.textContent = "";
    const data = Object.fromEntries(new FormData(form));
    const kind = form.dataset.teamForm;
    try {
      if (["login", "setup", "join"].includes(kind)) {
        if (kind === "join") data.token = location.hash.slice(7);
        const session = await post(`/api/auth/${kind}`, data);
        form.reset();
        history.replaceState(null, "", "#/home");
        await onSession(session);
      } else if (kind === "invite") {
        const invitation = await post("/api/team/invitations", data);
        await page();
        document.querySelector("#invite-result").innerHTML = `<div class="invite-success"><strong>One seat, saved for ${esc(data.email)}.</strong><p>Copy this private, single-use link now. It expires in 7 days and won’t be shown again.</p><label for="invitation-link">Invitation link</label><input id="invitation-link" readonly value="${esc(location.origin + invitation.join_path)}"><button class="secondary" data-team="copy">Copy link</button><small>Share only with the invited person. A localhost link works only on this computer; remote access needs a reachable, HTTPS-protected server.</small></div>`;
      } else if (kind === "access") {
        if (!confirm("Apply this access change? The member’s existing sessions will be signed out.")) return;
        await api(`/api/team/members/${form.dataset.member}`, { method: "PUT", body: JSON.stringify({ role: data.role, active: data.active === "on" }) });
        if (form.dataset.member === state.session.user.id) { await onLogout(); return; }
        await page(); toast("Team access updated.");
      } else if (kind === "password") {
        state.session = await post("/api/auth/password", data);
        form.reset(); document.querySelector("#settings").close(); toast("Password updated. Other sessions were signed out.");
      } else {
        const base = `/api/documents/${state.doc.id}`;
        if (kind === "comment") await post(base + "/comments", { ...data, section: data.section === "" ? null : Number(data.section), expected_version: state.doc.version });
        if (kind === "reply") await post(`${base}/comments/${form.dataset.thread}/replies`, data);
        if (kind === "decision") await post(base + "/review", { ...data, expected_version: state.doc.version });
        await loadReview(); toast(kind === "decision" ? "Your review is recorded." : "Your note is saved.");
      }
    } catch (e) {
      if (form.isConnected) message.textContent = e.message;
      else toast(e.message, true);
    } finally { button.disabled = false; }
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-team]");
    if (!button) return;
    if (button.disabled) return;
    button.disabled = true;
    try {
      const action = button.dataset.team;
      if (action === "logout") {
        if (state.editing && !confirm("Discard unsaved edits and sign out?")) return;
        await post("/api/auth/logout"); await onLogout();
      }
      if (action === "refresh") await page();
      if (action === "revoke" && confirm("Revoke this invitation? Its link will stop working.")) { await post(`/api/team/invitations/${button.dataset.id}/revoke`); await page(); }
      if (action === "copy") {
        const field = document.querySelector("#invitation-link");
        try { await navigator.clipboard.writeText(field.value); toast("Invitation link copied."); }
        catch { field.select(); toast("Select and copy the invitation link."); }
      }
      if (action === "review-refresh") await loadReview();
      if (action === "older") { showOlder = !showOlder; renderDocument(); }
      if (action === "resolve") { await post(`/api/documents/${state.doc.id}/comments/${button.dataset.id}/resolve`, { resolved: button.dataset.resolved === "true" }); await loadReview(); }
    } catch (e) { toast(e.message, true); }
    finally { button.disabled = false; }
  });
  return { authScreen, page, reviewContent, loadReview, accountSettings, initials,
    reset: () => { reviewData = null; showOlder = false; },
  };
}
