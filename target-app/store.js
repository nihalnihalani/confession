// Task store: JSON-file persistence with atomic writes.
// The write path writes to a temp file in the same directory, fsyncs, then
// renames over the target — rename is atomic on POSIX, so a crash mid-write can
// never leave a torn tasks.json behind.

import { promises as fs } from "node:fs";
import path from "node:path";
import crypto from "node:crypto";

export const STATUSES = ["todo", "doing", "done"];
export const PRIORITIES = ["low", "medium", "high"];

export class TaskStore {
  constructor(filePath) {
    this.filePath = filePath;
    this.dir = path.dirname(filePath);
    // Serialize writes so concurrent requests can't interleave read-modify-write.
    this._writeChain = Promise.resolve();
  }

  async _readRaw() {
    try {
      const text = await fs.readFile(this.filePath, "utf8");
      const parsed = JSON.parse(text);
      return Array.isArray(parsed) ? parsed : [];
    } catch (err) {
      if (err.code === "ENOENT") return [];
      throw err;
    }
  }

  async _atomicWrite(tasks) {
    await fs.mkdir(this.dir, { recursive: true });
    const tmp = path.join(
      this.dir,
      `.tasks.${process.pid}.${crypto.randomBytes(6).toString("hex")}.tmp`
    );
    const payload = JSON.stringify(tasks, null, 2);
    const handle = await fs.open(tmp, "w");
    try {
      await handle.writeFile(payload, "utf8");
      await handle.sync();
    } finally {
      await handle.close();
    }
    await fs.rename(tmp, this.filePath);
  }

  // Run a read-modify-write transaction with the store's serialized write chain.
  _transaction(mutator) {
    const run = this._writeChain.then(async () => {
      const tasks = await this._readRaw();
      const result = await mutator(tasks);
      await this._atomicWrite(result.tasks);
      return result.value;
    });
    // Keep the chain alive even if this transaction rejects.
    this._writeChain = run.catch(() => {});
    return run;
  }

  async list({ status } = {}) {
    const tasks = await this._readRaw();
    if (status) return tasks.filter((t) => t.status === status);
    return tasks;
  }

  async get(id) {
    const tasks = await this._readRaw();
    return tasks.find((t) => t.id === id) ?? null;
  }

  async create({ title, status, assignee, priority }) {
    const now = new Date().toISOString();
    const task = {
      id: crypto.randomUUID(),
      title,
      status: status ?? "todo",
      assignee: assignee ?? "",
      priority: priority ?? "medium",
      createdAt: now,
      updatedAt: now,
    };
    return this._transaction((tasks) => ({
      tasks: [...tasks, task],
      value: task,
    }));
  }

  async update(id, patch) {
    return this._transaction((tasks) => {
      const idx = tasks.findIndex((t) => t.id === id);
      if (idx === -1) return { tasks, value: null };
      const merged = {
        ...tasks[idx],
        ...patch,
        id: tasks[idx].id,
        createdAt: tasks[idx].createdAt,
        updatedAt: new Date().toISOString(),
      };
      const next = tasks.slice();
      next[idx] = merged;
      return { tasks: next, value: merged };
    });
  }

  async remove(id) {
    return this._transaction((tasks) => {
      const idx = tasks.findIndex((t) => t.id === id);
      if (idx === -1) return { tasks, value: false };
      const next = tasks.slice();
      next.splice(idx, 1);
      return { tasks: next, value: true };
    });
  }
}
