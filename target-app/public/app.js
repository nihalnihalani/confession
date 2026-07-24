// Tasklight frontend — talks to the REST API, renders the task list.
const STATUS_ORDER = ["todo", "doing", "done"];
const NEXT_STATUS = { todo: "doing", doing: "done", done: "todo" };

const state = {
  tasks: [],
  filter: "all",
};

const el = {
  form: document.getElementById("add-form"),
  title: document.getElementById("title"),
  assignee: document.getElementById("assignee"),
  priority: document.getElementById("priority"),
  formError: document.getElementById("form-error"),
  list: document.getElementById("task-list"),
  empty: document.getElementById("empty"),
  counter: document.getElementById("counter"),
  filters: document.querySelectorAll(".filter"),
};

async function api(path, options) {
  const res = await fetch(path, {
    headers: { "Content-Type": "application/json" },
    ...options,
  });
  if (res.status === 204) return null;
  const body = await res.json().catch(() => ({}));
  if (!res.ok) {
    const message =
      body.error || (body.errors && body.errors.join(", ")) || res.statusText;
    throw new Error(message);
  }
  return body;
}

function showFormError(message) {
  if (!message) {
    el.formError.hidden = true;
    el.formError.textContent = "";
    return;
  }
  el.formError.hidden = false;
  el.formError.textContent = message;
}

function visibleTasks() {
  const tasks =
    state.filter === "all"
      ? state.tasks
      : state.tasks.filter((t) => t.status === state.filter);
  return tasks
    .slice()
    .sort(
      (a, b) =>
        STATUS_ORDER.indexOf(a.status) - STATUS_ORDER.indexOf(b.status) ||
        new Date(a.createdAt) - new Date(b.createdAt)
    );
}

function render() {
  const tasks = visibleTasks();
  el.counter.textContent = String(state.tasks.length);
  el.list.innerHTML = "";
  el.empty.hidden = tasks.length > 0;

  for (const task of tasks) {
    const li = document.createElement("li");
    li.className = "task" + (task.status === "done" ? " is-done" : "");
    li.dataset.id = task.id;

    const toggle = document.createElement("button");
    toggle.className = "status-toggle";
    toggle.textContent = task.status;
    toggle.title = "Click to advance status";
    toggle.addEventListener("click", () => advanceStatus(task));

    const main = document.createElement("div");
    main.className = "task-main";
    const titleDiv = document.createElement("div");
    titleDiv.className = "task-title";
    titleDiv.textContent = task.title;
    const meta = document.createElement("div");
    meta.className = "task-meta";
    meta.textContent = task.assignee ? `Assigned to ${task.assignee}` : "Unassigned";
    main.append(titleDiv, meta);

    const badge = document.createElement("span");
    badge.className = `badge badge-${task.priority}`;
    badge.textContent = task.priority;

    const del = document.createElement("button");
    del.className = "delete";
    del.setAttribute("aria-label", `Delete task: ${task.title}`);
    del.textContent = "×";
    del.addEventListener("click", () => removeTask(task));

    li.append(toggle, main, badge, del);
    el.list.append(li);
  }
}

async function load() {
  try {
    const body = await api("/api/tasks");
    state.tasks = body.tasks;
    render();
  } catch (err) {
    showFormError(`Could not load tasks: ${err.message}`);
  }
}

async function addTask(event) {
  event.preventDefault();
  showFormError("");
  const title = el.title.value.trim();
  if (!title) {
    showFormError("Title is required.");
    el.title.focus();
    return;
  }
  try {
    const body = await api("/api/tasks", {
      method: "POST",
      body: JSON.stringify({
        title,
        assignee: el.assignee.value.trim(),
        priority: el.priority.value,
      }),
    });
    state.tasks.push(body.task);
    el.form.reset();
    el.priority.value = "medium";
    el.title.focus();
    render();
  } catch (err) {
    showFormError(err.message);
  }
}

async function advanceStatus(task) {
  const status = NEXT_STATUS[task.status] ?? "todo";
  try {
    const body = await api(`/api/tasks/${task.id}`, {
      method: "PATCH",
      body: JSON.stringify({ status }),
    });
    Object.assign(task, body.task);
    render();
  } catch (err) {
    showFormError(err.message);
  }
}

async function removeTask(task) {
  try {
    await api(`/api/tasks/${task.id}`, { method: "DELETE" });
    state.tasks = state.tasks.filter((t) => t.id !== task.id);
    render();
  } catch (err) {
    showFormError(err.message);
  }
}

function setFilter(filter) {
  state.filter = filter;
  for (const button of el.filters) {
    button.classList.toggle("is-active", button.dataset.filter === filter);
  }
  render();
}

el.form.addEventListener("submit", addTask);
for (const button of el.filters) {
  button.addEventListener("click", () => setFilter(button.dataset.filter));
}

load();
