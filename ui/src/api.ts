import { useSyncExternalStore } from "react";

const ACCESS_KEY_STORAGE = "confession.access-key";
const configuredOrigin = import.meta.env.VITE_ENGINE_URL?.trim().replace(/\/$/, "");

let accessKey = readStoredKey();
const listeners = new Set<() => void>();

export function apiUrl(path: string): string {
  const normalized = path.startsWith("/") ? path : `/${path}`;
  return configuredOrigin ? `${configuredOrigin}${normalized}` : normalized;
}

export function engineWebSocketUrl(): string {
  const origin = configuredOrigin ?? window.location.origin;
  const url = new URL(origin);
  url.protocol = url.protocol === "https:" ? "wss:" : "ws:";
  url.pathname = "/ws";
  url.search = "";
  url.hash = "";
  return url.toString();
}

export function apiFetch(
  path: string,
  init: RequestInit = {},
  options: { mutation?: boolean; requestKey?: string } = {},
): Promise<Response> {
  const headers = new Headers(init.headers);
  headers.set("Accept", "application/json");
  if (accessKey) headers.set("Authorization", `Bearer ${accessKey}`);
  if (options.mutation) {
    headers.set("Idempotency-Key", options.requestKey ?? crypto.randomUUID());
  }
  return fetch(apiUrl(path), { ...init, headers });
}

export function setAccessKey(value: string): void {
  accessKey = value.trim();
  if (accessKey) sessionStorage.setItem(ACCESS_KEY_STORAGE, accessKey);
  else sessionStorage.removeItem(ACCESS_KEY_STORAGE);
  for (const listener of listeners) listener();
}

export function useAccessKey(): string {
  return useSyncExternalStore(
    (listener) => {
      listeners.add(listener);
      return () => listeners.delete(listener);
    },
    () => accessKey,
    () => "",
  );
}

export async function errorMessage(response: Response): Promise<string> {
  const body: unknown = await response.json().catch(() => null);
  if (
    typeof body === "object" &&
    body !== null &&
    typeof (body as { detail?: unknown }).detail === "string"
  ) {
    return (body as { detail: string }).detail;
  }
  return `${response.status} ${response.statusText}`.trim();
}

function readStoredKey(): string {
  try {
    return sessionStorage.getItem(ACCESS_KEY_STORAGE) ?? "";
  } catch {
    return "";
  }
}
