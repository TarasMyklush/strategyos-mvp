(async function () {
  "use strict";
  const status = document.getElementById('review-queue-status');
  async function request(url, options = {}) {
    const response = await fetch(url, {...options, credentials: 'same-origin',
      headers: {'Accept': 'application/json', ...(options.body ? {'Content-Type': 'application/json'} : {})}});
    if (!response.ok) throw new Error(`Run review request failed (${response.status}). Refresh or sign in with the required authority.`);
    return response.json();
  }
  try {
    const session = await request('/ui/session');
    const role = session.role;
    const rights = {review: session.auth_disabled || ['reviewer', 'tenant_admin', 'system'].includes(role),
      operate: session.auth_disabled || ['operator', 'tenant_admin', 'system'].includes(role)};
    const runs = await request('/reviewer/runs?limit=100');
    const list = document.getElementById('review-run-list');
    (runs.items || []).forEach(run => {
      const link = document.createElement('a');
      link.href = '/runs/review?review_run=' + encodeURIComponent(run.run_id);
      link.textContent = `${run.run_id} · ${run.current_stage || run.status || ''} · ${run.approval_status || 'pending'}`;
      list.appendChild(link);
    });
    status.textContent = runs.store_status === 'failed' ? 'The run list is currently unavailable.' : 'Select a run to inspect its evidence and available actions.';
    const runId = new URLSearchParams(location.search).get('review_run');
    if (runId) {
      const review = window.KyvernRunReview.create({element: document.getElementById('selected-run-review'),
        runId, request, permissions: () => rights});
      await review.refresh();
    }
  } catch (error) {status.textContent = error.message || 'Run review is unavailable.';}
})();
