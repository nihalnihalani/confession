import { useEffect, useState } from "react";
import { apiFetch } from "./api";
import type { TaskOption } from "./types";

let taskRequest: Promise<TaskOption[]> | null = null;

function loadTasks(): Promise<TaskOption[]> {
  taskRequest ??= apiFetch("/api/tasks")
    .then(async (response) => {
      if (!response.ok) throw new Error(`tasks ${response.status}`);
      const body: unknown = await response.json();
      if (!Array.isArray(body)) return [];
      return body.filter(
        (task): task is TaskOption =>
          typeof task === "object" &&
          task !== null &&
          typeof (task as TaskOption).id === "string" &&
          typeof (task as TaskOption).title === "string",
      );
    })
    .catch(() => []);
  return taskRequest;
}

export function useTasks(): TaskOption[] {
  const [tasks, setTasks] = useState<TaskOption[]>([]);

  useEffect(() => {
    let active = true;
    void loadTasks().then((next) => {
      if (active) setTasks(next);
    });
    return () => {
      active = false;
    };
  }, []);

  return tasks;
}
