export function createHandoffs({ state, api, post, esc, icon, date, shell, toast, refreshReview }) {
  let current = null;
  let scope = "assigned";
  let showHistory = false;
  const canRequest = () => ["owner", "editor"].includes(state.session?.user?.role);
  const labels = {
    pending: "Awaiting review", approved: "Approved", changes_requested: "Changes requested",
    superseded: "Newer draft available", withdrawn: "Withdrawn", unavailable: "Reviewer unavailable",
  };
  const badge = (status) => `<span class="handoff-status ${esc(status)}">${labels[status] || esc(status)}</span>`;

  async function loadDocument(id) {
    if (!state.session?.auth_enabled) { current = null; return; }
    const [requests, team] = await Promise.all([
      api(`/api/documents/${id}/review-requests`),
      canRequest() ? api("/api/team") : Promise.resolve({ members: [] }),
    ]);
    if (state.doc?.id !== id) return;
    current = { docId: id, requests: requests.requests, reviewers: team.members.filter((member) =>
      member.active && ["owner", "reviewer"].includes(member.role) && member.id !== state.session.user.id) };
  }

  function panel() {
    if (!state.session?.auth_enabled || current?.docId !== state.doc.id) return "";
    const active = current.requests.find((r) => r.version === state.doc.version && r.status !== "withdrawn");
    return `<div class="detail-card handoff-card"><span class="eyebrow">THE NEXT PAIR OF EYES</span><h3>${active ? "A clear handoff" : "Bring a teammate in"}</h3>${active ? `${badge(active.status)}<p><strong>${esc(active.reviewer.name)}</strong> was asked to review version ${active.version} by ${esc(active.requested_by.name)}.</p>${active.note ? `<blockquote>${esc(active.note)}</blockquote>` : ""}${active.status === "unavailable" ? '<p class="review-warning">This teammate can no longer review. Withdraw this request and choose another active reviewer.</p>' : ""}${canRequest() ? `<button class="text-button" data-handoff="withdraw" data-id="${active.id}">Withdraw request</button>` : ""}` : canRequest() ? current.reviewers.length ? `<form data-handoff-form><div class="field"><label for="handoff-reviewer">Reviewer</label><select name="reviewer_id" id="handoff-reviewer" required><option value="">Choose a teammate</option>${current.reviewers.map((r) => `<option value="${r.id}">${esc(r.name)} · ${esc(r.role)}</option>`).join("")}</select></div><div class="field"><label for="handoff-note">What needs a second look?</label><textarea id="handoff-note" name="note" maxlength="2000" placeholder="e.g. Check the milestones and success measures"></textarea></div><p class="muted">Adds version ${state.doc.version} to their review inbox. No email or model call is sent.${state.doc.approved_version === state.doc.version ? " Requesting another review clears the current approval." : ""}</p><p class="form-error" role="alert" data-handoff-error></p><button class="primary" type="submit">Request review ${icon("arrow")}</button></form>` : '<p>Invite another owner or reviewer to hand off this draft.</p><button class="text-button" data-nav="team">Open team & access</button>' : '<p>An editor or owner can assign this draft for review. You can also leave feedback without an assignment.</p>'}<p class="handoff-policy">One reviewer is assigned per version. Any owner or reviewer may record the team’s decision; this is not a multi-person sign-off requirement.</p></div>`;
  }

  async function inbox() {
    if (!state.session.auth_enabled) {
      shell('<div class="home"><h1>A shared queue for your team.</h1><p>Enable team accounts to request and receive reviews.</p></div>', "Review inbox");
      return;
    }
    const data = await api("/api/review-inbox");
    if (state.page !== "inbox") return;
    const userId = state.session.user.id;
    const assigned = data.requests.filter((r) => r.reviewer.id === userId);
    const sent = data.requests.filter((r) => r.requested_by.id === userId);
    const relevant = scope === "assigned" ? assigned : sent;
    const actionable = (r) => scope === "assigned" ? r.status === "pending" : ["pending", "changes_requested", "unavailable"].includes(r.status);
    const items = showHistory ? relevant : relevant.filter(actionable);
    shell(`<div class="home inbox-page"><div class="eyebrow">A THOUGHTFUL SECOND LOOK</div><section class="hero"><div><h1>Less chasing.<br><em>More moving forward.</em></h1><p>Your review handoffs, in one quiet place.<br>Every request is tied to the draft that was actually shared.</p></div><button class="secondary" data-handoff="refresh">${icon("clock")}Refresh inbox</button></section><div class="inbox-stats"><div><strong>${assigned.filter((r) => r.status === "pending").length}</strong><span>Waiting for your perspective</span></div><div><strong>${sent.filter((r) => r.status === "pending").length}</strong><span>Reviews you’re waiting on</span></div><div><strong>${sent.filter((r) => r.status === "changes_requested").length}</strong><span>Drafts with requested changes</span></div></div><div class="inbox-toolbar"><div class="filters"><button class="filter ${scope === "assigned" ? "active" : ""}" data-handoff="assigned">Assigned to me</button><button class="filter ${scope === "sent" ? "active" : ""}" data-handoff="sent">Requested by me</button></div><button class="text-button" data-handoff="history" aria-pressed="${showHistory}">${showHistory ? "Show active requests" : "Include completed & earlier versions"}</button></div><div class="handoff-list">${items.map((r) => `<article class="handoff-row"><div class="handoff-row-top"><span class="doc-symbol">${icon("file")}</span><div><h2>${esc(r.title)}</h2><p>Version ${r.version}${r.current_version !== r.version ? ` · Current draft is v${r.current_version}` : ""} · ${date(r.created_at)}</p></div>${badge(r.status)}</div><p>${scope === "assigned" ? `Requested by ${esc(r.requested_by.name)}` : `For ${esc(r.reviewer.name)}`}${r.approved_by ? ` · Approved by ${esc(r.approved_by.name)}` : ""}</p>${r.note ? `<blockquote>${esc(r.note)}</blockquote>` : ""}<div class="handoff-row-footer"><span>${r.status === "superseded" ? "A new version needs a fresh review request." : r.status === "unavailable" ? "Choose another reviewer in the document’s Team review tab." : r.status === "changes_requested" ? "Open the discussion, revise the draft, then request a fresh review." : "Read the draft and its decision trail before reviewing."}</span><a class="secondary" href="#/document/${r.document_id}/review">${r.status === "superseded" ? "Open current draft" : "Open review"}${icon("arrow")}</a></div></article>`).join("") || `<div class="empty inbox-empty">${icon("check")}<h2>${showHistory ? "No review handoffs yet." : scope === "assigned" ? "Nothing waiting on you." : "No active requests to follow up."}</h2><p>${scope === "assigned" ? "When a teammate requests your review, it will appear here." : "Open a document’s Team review tab to choose a reviewer and add a note."}</p><button class="secondary" data-nav="library">Browse documents ${icon("arrow")}</button></div>`}</div><p class="inbox-footnote">Showing your latest 200 requests. Use Refresh to pick up teammate updates. All workspace members can still read and discuss documents.</p></div>`, "Review inbox");
  }

  document.addEventListener("submit", async (event) => {
    const form = event.target.closest("[data-handoff-form]");
    if (!form) return;
    event.preventDefault();
    const button = form.querySelector("button[type=submit]");
    if (button.disabled) return;
    button.disabled = true;
    const error = form.querySelector("[data-handoff-error]");
    error.textContent = "";
    try {
      await post(`/api/documents/${state.doc.id}/review-requests`, {
        ...Object.fromEntries(new FormData(form)), expected_version: state.doc.version,
      });
      await refreshReview();
      toast("Review requested. It’s in your teammate’s inbox.");
    } catch (e) {
      if (error.isConnected) error.textContent = e.message;
      else toast(e.message, true);
    } finally { button.disabled = false; }
  });

  document.addEventListener("click", async (event) => {
    const button = event.target.closest("[data-handoff]");
    if (!button || button.disabled) return;
    button.disabled = true;
    try {
      const action = button.dataset.handoff;
      if (action === "withdraw") {
        if (!confirm("Withdraw this review request? The draft and discussion will stay unchanged.")) return;
        await post(`/api/documents/${state.doc.id}/review-requests/${button.dataset.id}/withdraw`);
        await refreshReview();
        toast("Review request withdrawn.");
      } else {
        if (["assigned", "sent"].includes(action)) scope = action;
        if (action === "history") showHistory = !showHistory;
        await inbox();
      }
    } catch (e) { toast(e.message, true); }
    finally { button.disabled = false; }
  });
  return { inbox, panel, loadDocument, reset: () => { current = null; scope = "assigned"; showHistory = false; } };
}
