// Real HTTP tests: spin up the actual Express app on an ephemeral port with a
// temp data file, then exercise the API with fetch. No network beyond localhost.

import { test, before, after } from "node:test";
import assert from "node:assert/strict";
import { promises as fs } from "node:fs";
import os from "node:os";
import path from "node:path";
import { createApp } from "../server.js";

let server;
let base;
let dataFile;

before(async () => {
  const dir = await fs.mkdtemp(path.join(os.tmpdir(), "tasklight-test-"));
  dataFile = path.join(dir, "tasks.json");
  const app = createApp({ dataFile });
  server = app.listen(0);
  await new Promise((resolve) => server.once("listening", resolve));
  const { port } = server.address();
  base = `http://127.0.0.1:${port}`;
});

after(async () => {
  await new Promise((resolve) => server.close(resolve));
  await fs.rm(path.dirname(dataFile), { recursive: true, force: true });
});

async function json(res) {
  return { status: res.status, body: await res.json().catch(() => null) };
}

test("health reports allowed statuses and priorities", async () => {
  const res = await fetch(`${base}/api/health`);
  const { status, body } = await json(res);
  assert.equal(status, 200);
  assert.deepEqual(body.statuses, ["todo", "doing", "done"]);
  assert.deepEqual(body.priorities, ["low", "medium", "high"]);
});

test("starts with an empty task list", async () => {
  const res = await fetch(`${base}/api/tasks`);
  const { status, body } = await json(res);
  assert.equal(status, 200);
  assert.deepEqual(body.tasks, []);
});

test("creates a task with defaults and returns 201", async () => {
  const res = await fetch(`${base}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Write the pitch" }),
  });
  const { status, body } = await json(res);
  assert.equal(status, 201);
  assert.equal(body.task.title, "Write the pitch");
  assert.equal(body.task.status, "todo");
  assert.equal(body.task.priority, "medium");
  assert.equal(body.task.assignee, "");
  assert.match(body.task.id, /[0-9a-f-]{36}/);
});

test("rejects an empty title with 400", async () => {
  const res = await fetch(`${base}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "   " }),
  });
  const { status, body } = await json(res);
  assert.equal(status, 400);
  assert.ok(body.errors.some((e) => e.includes("title is required")));
});

test("rejects an invalid priority with 400", async () => {
  const res = await fetch(`${base}/api/tasks`, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ title: "Bad priority", priority: "urgent" }),
  });
  const { status, body } = await json(res);
  assert.equal(status, 400);
  assert.ok(body.errors.some((e) => e.includes("priority must be one of")));
});

test("patches status and preserves priority", async () => {
  const created = await (
    await fetch(`${base}/api/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Ship it", priority: "high" }),
    })
  ).json();
  const id = created.task.id;

  const res = await fetch(`${base}/api/tasks/${id}`, {
    method: "PATCH",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ status: "doing" }),
  });
  const { status, body } = await json(res);
  assert.equal(status, 200);
  assert.equal(body.task.status, "doing");
  assert.equal(body.task.priority, "high");
});

test("filters by status", async () => {
  const res = await fetch(`${base}/api/tasks?status=doing`);
  const { status, body } = await json(res);
  assert.equal(status, 200);
  assert.ok(body.tasks.length >= 1);
  assert.ok(body.tasks.every((t) => t.status === "doing"));
});

test("rejects an unknown status filter with 400", async () => {
  const res = await fetch(`${base}/api/tasks?status=nope`);
  const { status } = await json(res);
  assert.equal(status, 400);
});

test("returns 404 for a missing task", async () => {
  const res = await fetch(`${base}/api/tasks/does-not-exist`);
  const { status, body } = await json(res);
  assert.equal(status, 404);
  assert.equal(body.error, "task not found");
});

test("deletes a task and then 404s on re-delete", async () => {
  const created = await (
    await fetch(`${base}/api/tasks`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ title: "Temporary" }),
    })
  ).json();
  const id = created.task.id;

  const del = await fetch(`${base}/api/tasks/${id}`, { method: "DELETE" });
  assert.equal(del.status, 204);

  const again = await fetch(`${base}/api/tasks/${id}`, { method: "DELETE" });
  assert.equal(again.status, 404);
});

test("persists tasks across a fresh store instance (same data file)", async () => {
  const app2 = createApp({ dataFile });
  const server2 = app2.listen(0);
  await new Promise((resolve) => server2.once("listening", resolve));
  const { port } = server2.address();
  try {
    const res = await fetch(`http://127.0.0.1:${port}/api/tasks`);
    const { body } = await json(res);
    assert.ok(body.tasks.some((t) => t.title === "Write the pitch"));
  } finally {
    await new Promise((resolve) => server2.close(resolve));
  }
});
