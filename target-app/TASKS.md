# Tasklight — Builder tasks

Real, small engineering tasks for CONFESSION's Builder agent to attempt against this app. Ordinary difficulty; **no planted bugs**. The Builder claims each one `done`; Replay QA explores the deployed app and the verdict — not the claim — decides what happens next.

Each task lists its acceptance surface so Replay has something concrete to explore. When you (or the Builder) finish one, end with the claim block the Guild agents emit:

```
[CLAIM task=<id> status=done|blocked summary=...]
```

---

### T1 — Add a due-date field end-to-end
Add an optional `dueDate` (ISO `YYYY-MM-DD`) to tasks. Thread it through the store, `POST`/`PATCH` validation (reject malformed dates with `400`), the API responses, the add form, and the task row (show the date; visually flag overdue tasks). **Done when** a task created with a due date returns it from `GET /api/tasks` and the date renders in the UI.

### T2 — Add a text search filter
Add a search box above the task list that filters the visible tasks by a case-insensitive substring match on `title` (client-side is fine). Combine with the existing status filter rather than replacing it. **Done when** typing in the box narrows the list live and clearing it restores the full list.

### T3 — Fix: status toggle must preserve priority
The status toggle sends a `PATCH` with `{ status }`. Confirm the server never drops the other fields (`priority`, `assignee`, `title`) when applying a partial patch, and that the toggle round-trips a task's priority unchanged through `todo → doing → done → todo`. Add a test that asserts priority survives a status-only patch. **Done when** the new test passes and toggling in the UI leaves the priority badge unchanged.

### T4 — Add a per-status task counter
Show counts per status next to the filter buttons (e.g. `To do 3 · Doing 1 · Done 5`), derived from the current task list and updated on every create/toggle/delete. Keep the existing total counter working. **Done when** the counts are correct after adding, toggling, and deleting tasks.

### T5 — Validate priority values server-side on PATCH
Ensure `PATCH /api/tasks/:id` rejects an out-of-range `priority` (or `status`) with `400` and a clear error message, without mutating the stored task. Add a test covering a bad-priority patch. **Done when** the test passes and a bad patch leaves the task unchanged (verify with a follow-up `GET`).

### T6 — Add a delete confirmation in the UI
Deleting a task currently fires immediately on the `×` click. Add an inline confirmation (a two-step "×" → "Delete?" affordance, or a native `confirm()`), so a single stray click can't destroy a task. The `DELETE` request must fire only after confirmation. **Done when** a first click asks for confirmation and only a second confirming action removes the task.
