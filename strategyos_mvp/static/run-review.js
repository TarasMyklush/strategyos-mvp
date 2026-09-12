/* A review selection is independent of the latest published executive run. */
(function (root) {
  "use strict";
  function create({element, runId, request, permissions}) {
    let busy = false;
    let record = null;
    let signature = null;
    let comment = "";
    let analysisRequested = false;
    const path = `/reviewer/runs/${encodeURIComponent(runId)}`;
    const node = (tag, text, parent = element) => {
      const item = document.createElement(tag);
      if (text !== undefined) item.textContent = text;
      parent.appendChild(item);
      return item;
    };
    function button(text, action, parent = element) {
      const item = node("button", text, parent);
      item.type = "button";
      item.className = "btn secondary";
      item.disabled = busy;
      item.addEventListener("click", action);
      return item;
    }
    function status(text) {
      const target = element.querySelector('[data-review-status]');
      if (target) target.textContent = text;
    }
    async function perform(action) {
      if (busy || !record) return;
      busy = true;
      element.querySelectorAll("button,textarea").forEach(item => { item.disabled = true; });
      status("Recording the action for this selected run…");
      try {
        if (action === "approve" || action === "reject") {
          await request(`${path}/claim`, {method: "POST"});
          await request(`${path}/${action}`, {method: "POST", body: JSON.stringify({comment})});
        } else {
          await request(`/operator/runs/${encodeURIComponent(runId)}/resume`, {method: "POST"});
        }
        signature = null;
        busy = false;
        if (await refresh()) status("Action completed for this selected run.");
      } catch (error) {
        busy = false;
        render();
        status(error?.message || "The action could not be recorded. Refresh this run before retrying.");
      }
    }
    async function preview(key, target) {
      target.textContent = "Loading the selected run’s artifact…";
      try {
        const artifact = await request(`${path}/artifacts/${encodeURIComponent(key)}`);
        target.textContent = artifact.preview_text || "No text preview is available for this artifact.";
      } catch (error) {
        target.textContent = error?.message || "Artifact unavailable.";
      }
    }
    async function analyzeAgain(sourcePackId) {
      if (busy || analysisRequested || !permissions().operate) return;
      busy = true;
      analysisRequested = true;
      element.querySelectorAll("button,textarea").forEach(item => { item.disabled = true; });
      status("Starting a separate analysis from this run’s registered source…");
      try {
        const receipt = await request('/runs', {method: 'POST',
          body: JSON.stringify({source_pack_id: sourcePackId, sync_artifacts: true})});
        busy = false;
        render();
        status("A separate analysis was requested. This run and its published reports are unchanged. Review and approval remain separate actions.");
        const link = node('a', 'Open the new analysis');
        link.href = typeof receipt.run_id === 'string' && receipt.run_id !== runId
          ? '/runs/review?review_run=' + encodeURIComponent(receipt.run_id) : '/runs/review';
      } catch (error) {
        busy = false;
        render();
        status("The new analysis was not confirmed. Check run history before requesting another analysis. " + (error?.message || ''));
        node('a', 'Check run history').href = '/runs/review';
      }
    }
    function render() {
      element.replaceChildren();
      node("h3", "Selected run review");
      node("p", runId).setAttribute("data-selected-review-run", runId);
      const message = node("p", "Review the evidence for this run before recording a decision.");
      message.setAttribute("data-review-status", "");
      message.setAttribute("role", "status");
      button("Refresh selected run", refresh);
      if (!record) return;
      const approval = record.approval?.approval_status || record.approval_status || "pending";
      node("p", `Stage: ${record.current_stage || record.status || "Unknown"} · Review: ${approval}`);
      const checkpoint = record.latest_checkpoint?.state_json || {};
      const summary = record.summary_json || {};
      const findings = record.review_findings || checkpoint.findings || summary.findings || [];
      node("h4", "Findings in this review");
      if (!findings.length) node("p", "No finding entries are available in this checkpoint.");
      findings.forEach(finding => {
        const detail = node("details");
        node("summary", `${finding.title || finding.pattern_type || finding.finding_id} · ${finding.status || "Unclassified"}`, detail);
        node("p", finding.rationale || finding.summary || finding.description || "", detail);
        node("p", `Recoverable SAR: ${finding.recoverable_sar ?? "Not recorded"}`, detail);
        (finding.citations || []).forEach(citation => {
          node("p", `${citation.source_path || citation.file || "Source"} · ${citation.locator || ""}`, detail);
          node("blockquote", citation.display_excerpt ?? citation.excerpt ?? "", detail);
        });
        node("pre", JSON.stringify(finding.calculation || {}, null, 2), detail);
      });
      const audit = node("details");
      node("summary", "Auditor challenges and responses", audit);
      node("pre", JSON.stringify(checkpoint.audit_events || [], null, 2), audit);
      const artifacts = node("details");
      node("summary", "Report previews for this run", artifacts);
      const previewText = node("pre", "Choose a report. Reports are created after approval and operator resume.", artifacts);
      [["case_file", "Case file"], ["working_capital", "Working capital"], ["qa", "Q&A"], ["audit_log", "Audit log"]]
        .forEach(([key, label]) => button(label, () => preview(key, previewText), artifacts));
      const rights = permissions();
      if (rights.operate && record.status === 'completed' && !analysisRequested
          && typeof summary.source_pack_id === 'string' && summary.source_pack_id) {
        button("Analyze this source again", () => analyzeAgain(summary.source_pack_id));
      }
      const waiting = record.current_stage === "awaiting_review" && record.status !== "completed";
      if (rights.review && waiting && !["approved", "rejected"].includes(approval)) {
        const label = node("label", "Reviewer comment");
        const input = node("textarea", undefined, label);
        input.value = comment;
        input.addEventListener("input", () => { comment = input.value; });
        button("Approve selected run", () => perform("approve"));
        button("Reject selected run", () => perform("reject"));
      }
      if (rights.operate && waiting && approval === "approved") {
        button("Resume selected run", () => perform("resume"));
      }
    }
    async function refresh() {
      if (busy) return;
      busy = true;
      element.querySelectorAll("button").forEach(item => { item.disabled = true; });
      try {
        const next = await request(path);
        if (String(next.run_id || "") !== runId) throw new Error("The returned review does not match the selected run.");
        const nextSignature = JSON.stringify([next, permissions()]);
        record = next;
        busy = false;
        if (nextSignature !== signature) {
          signature = nextSignature;
          render();
        } else {
          element.querySelectorAll("button").forEach(item => { item.disabled = false; });
        }
        return true;
      } catch (error) {
        record = null;
        signature = null;
        busy = false;
        render();
        status(error?.message || "This selected run is unavailable. No other run has been substituted.");
        return false;
      }
    }
    render();
    return {refresh};
  }
  root.KyvernRunReview = {create};
})(typeof window === "undefined" ? globalThis : window);
