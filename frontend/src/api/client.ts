// Minimal API client for the demo. Reads the dev token from
// localStorage; production deployments swap this for a real
// auth flow.

import type {
  APIResponse,
  ProgressEvent,
  QueryRequest,
  QueryResponse,
} from "../types/api";

const TOKEN_KEY = "maisys.access_token";

export function getToken(): string | null {
  return localStorage.getItem(TOKEN_KEY);
}

export function setToken(token: string): void {
  localStorage.setItem(TOKEN_KEY, token);
}

export async function login(email: string, password: string): Promise<string> {
  const resp = await fetch("/auth/login", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ email, password }),
  });
  if (!resp.ok) {
    throw new Error(`Login failed: ${resp.status}`);
  }
  const body = (await resp.json()) as APIResponse<{ access_token: string }>;
  if (!body.success || !body.data) {
    throw new Error(body.error?.message ?? "Login response unexpected");
  }
  setToken(body.data.access_token);
  return body.data.access_token;
}

export async function submitQuery(req: QueryRequest): Promise<QueryResponse> {
  const token = getToken();
  if (!token) throw new Error("Not authenticated");

  const resp = await fetch("/drugs/query", {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${token}`,
    },
    body: JSON.stringify(req),
  });
  if (!resp.ok) {
    let detail = "";
    try {
      detail = JSON.stringify(await resp.json());
    } catch {
      /* ignore */
    }
    throw new Error(`Query failed: ${resp.status} ${detail}`);
  }
  const body = (await resp.json()) as APIResponse<QueryResponse>;
  if (!body.success || !body.data) {
    throw new Error(body.error?.message ?? "Query response unexpected");
  }
  return body.data;
}

export function generateJobId(): string {
  // browser-native UUID generator (crypto.randomUUID() is available in
  // modern browsers; fall back to Math.random for older targets)
  if (typeof crypto !== "undefined" && "randomUUID" in crypto) {
    return crypto.randomUUID().replace(/-/g, "");
  }
  return Math.random().toString(36).slice(2) + Date.now().toString(36);
}

export function subscribeProgress(
  jobId: string,
  onEvent: (event: ProgressEvent) => void,
  onClose: (reason: "completed" | "failed" | "disconnect") => void,
): () => void {
  const token = getToken();
  if (!token) throw new Error("Not authenticated");

  const wsProtocol = window.location.protocol === "https:" ? "wss:" : "ws:";
  const url = `${wsProtocol}//${window.location.host}/ws/drugs/query/${jobId}?token=${encodeURIComponent(token)}`;
  const ws = new WebSocket(url);

  ws.onmessage = (msg) => {
    try {
      const event = JSON.parse(msg.data) as ProgressEvent;
      onEvent(event);
      if (event.status === "completed" || event.status === "failed") {
        onClose(event.status);
      }
    } catch (err) {
      console.warn("Failed to parse WS event", err);
    }
  };
  ws.onclose = () => onClose("disconnect");
  ws.onerror = (err) => {
    console.warn("WS error", err);
  };

  return () => {
    if (ws.readyState === WebSocket.OPEN || ws.readyState === WebSocket.CONNECTING) {
      ws.close();
    }
  };
}
