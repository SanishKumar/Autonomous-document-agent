export function comparisonPicker(versions) {
  if (versions.length < 2) return "";
  const options = (selected) => versions.map(v => `<option value="${v.number}" ${v.number === selected ? "selected" : ""}>Version ${v.number}</option>`).join("");
  return `<section class="detail-card"><h3>Compare saved drafts</h3><p>Text changes only. Comparing does not edit, restore, or approve either version.</p><div class="comparison-controls"><label>From <select id="compare-from">${options(versions[1].number)}</select></label><label>To <select id="compare-to">${options(versions[0].number)}</select></label><button class="secondary" data-action="compare-versions">Compare versions</button></div><div id="comparison-result" aria-live="polite"></div></section>`;
}

export function comparisonResult(result, esc) {
  const blocks = result.changes.map(change => {
    if (change.kind === "equal") return `<details><summary>${change.before.length} unchanged blocks</summary>${change.before.map(line => `<p>${esc(line)}</p>`).join("")}</details>`;
    return `<div class="comparison-change">${change.before.map(line => `<p class="comparison-removed"><strong>Removed</strong> <del>${esc(line)}</del></p>`).join("")}${change.after.map(line => `<p class="comparison-added"><strong>Added</strong> <ins>${esc(line)}</ins></p>`).join("")}</div>`;
  }).join("");
  return `<h4>Version ${result.from_version} → Version ${result.to_version}</h4><p>${result.added} added blocks · ${result.removed} removed blocks${!result.added && !result.removed ? " · No text changes" : ""}</p>${blocks}`;
}
