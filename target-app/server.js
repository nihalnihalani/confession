// Tasklight — a small team task tracker.
// REST API over a JSON-file store, plus a static single-page frontend.
// This is the real app CONFESSION's Builder agent works on and Replay QA explores.

import express from "express";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { TaskStore, STATUSES, PRIORITIES } from "./store.js";

const __dirname = path.dirname(fileURLToPath(import.meta.url));

export function createApp({ dataFile } = {}) {
  const store = new TaskStore(
    dataFile ?? path.join(__dirname, "data", "tasks.json")
  );

  const app = express();
  app.use(express.json());
  app.use(express.static(path.join(__dirname, "public")));

  // --- validation helpers ---------------------------------------------------

  function validateNewTask(body) {
    const errors = [];
    const title = typeof body.title === "string" ? body.title.trim() : "";
    if (!title) errors.push("title is required");
    if (title.length > 200) errors.push("title must be 200 characters or fewer");

    const status = body.status ?? "todo";
    if (!STATUSES.includes(status))
      errors.push(`status must be one of: ${STATUSES.join(", ")}`);

    const priority = body.priority ?? "medium";
    if (!PRIORITIES.includes(priority))
      errors.push(`priority must be one of: ${PRIORITIES.join(", ")}`);

    const assignee =
      typeof body.assignee === "string" ? body.assignee.trim() : "";
    if (assignee.length > 80)
      errors.push("assignee must be 80 characters or fewer");

    return { errors, value: { title, status, assignee, priority } };
  }

  function validatePatch(body) {
    const errors = [];
    const patch = {};
    if ("title" in body) {
      const title = typeof body.title === "string" ? body.title.trim() : "";
      if (!title) errors.push("title cannot be empty");
      else if (title.length > 200)
        errors.push("title must be 200 characters or fewer");
      else patch.title = title;
    }
    if ("status" in body) {
      if (!STATUSES.includes(body.status))
        errors.push(`status must be one of: ${STATUSES.join(", ")}`);
      else patch.status = body.status;
    }
    if ("priority" in body) {
      if (!PRIORITIES.includes(body.priority))
        errors.push(`priority must be one of: ${PRIORITIES.join(", ")}`);
      else patch.priority = body.priority;
    }
    if ("assignee" in body) {
      const assignee =
        typeof body.assignee === "string" ? body.assignee.trim() : "";
      if (assignee.length > 80)
        errors.push("assignee must be 80 characters or fewer");
      else patch.assignee = assignee;
    }
    return { errors, patch };
  }

  // --- routes ---------------------------------------------------------------

  app.get("/api/health", (_req, res) => {
    res.json({ ok: true, statuses: STATUSES, priorities: PRIORITIES });
  });

  app.get("/api/tasks", async (req, res, next) => {
    try {
      const { status } = req.query;
      if (status && !STATUSES.includes(status)) {
        return res
          .status(400)
          .json({ error: `unknown status filter: ${status}` });
      }
      const tasks = await store.list({ status });
      res.json({ tasks });
    } catch (err) {
      next(err);
    }
  });

  app.get("/api/tasks/:id", async (req, res, next) => {
    try {
      const task = await store.get(req.params.id);
      if (!task) return res.status(404).json({ error: "task not found" });
      res.json({ task });
    } catch (err) {
      next(err);
    }
  });

  app.post("/api/tasks", async (req, res, next) => {
    try {
      const { errors, value } = validateNewTask(req.body ?? {});
      if (errors.length) return res.status(400).json({ errors });
      const task = await store.create(value);
      res.status(201).json({ task });
    } catch (err) {
      next(err);
    }
  });

  app.patch("/api/tasks/:id", async (req, res, next) => {
    try {
      const { errors, patch } = validatePatch(req.body ?? {});
      if (errors.length) return res.status(400).json({ errors });
      if (Object.keys(patch).length === 0)
        return res.status(400).json({ error: "no valid fields to update" });
      const task = await store.update(req.params.id, patch);
      if (!task) return res.status(404).json({ error: "task not found" });
      res.json({ task });
    } catch (err) {
      next(err);
    }
  });

  app.delete("/api/tasks/:id", async (req, res, next) => {
    try {
      const removed = await store.remove(req.params.id);
      if (!removed) return res.status(404).json({ error: "task not found" });
      res.status(204).end();
    } catch (err) {
      next(err);
    }
  });

  // JSON 404 for unknown API routes (static/frontend handled above).
  app.use("/api", (_req, res) => {
    res.status(404).json({ error: "not found" });
  });

  // eslint-disable-next-line no-unused-vars
  app.use((err, _req, res, _next) => {
    console.error(err);
    res.status(500).json({ error: "internal server error" });
  });

  return app;
}

// Start a server only when run directly (not when imported by tests).
const isDirectRun =
  process.argv[1] && path.resolve(process.argv[1]) === fileURLToPath(import.meta.url);

if (isDirectRun) {
  const port = Number(process.env.PORT) || 4000;
  const app = createApp();
  app.listen(port, () => {
    console.log(`Tasklight listening on http://localhost:${port}`);
  });
}
