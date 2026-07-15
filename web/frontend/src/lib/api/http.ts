export const apiBaseUrl = normalizeBaseUrl(import.meta.env.VITE_API_BASE_URL);

export async function getJson<T>(path: string, token?: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    headers: buildHeaders(token),
  });
  return parseJsonResponse<T>(response);
}

export async function postJson<T>(path: string, body?: unknown, token?: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: "POST",
    headers: buildHeaders(token, body),
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  return parseJsonResponse<T>(response);
}

export async function patchJson<T>(path: string, body: unknown, token?: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: "PATCH",
    headers: buildHeaders(token, body),
    body: JSON.stringify(body),
  });
  return parseJsonResponse<T>(response);
}

export async function deleteJson<T>(path: string, token?: string): Promise<T> {
  const response = await fetch(`${apiBaseUrl}${path}`, {
    method: "DELETE",
    headers: buildHeaders(token),
  });
  return parseJsonResponse<T>(response);
}

export function buildHeaders(token?: string, body?: unknown): HeadersInit {
  // Web 聊天和管理后台都用 Bearer token，后端再按绑定关系做数据隔离。
  const headers: Record<string, string> = {};
  if (body !== undefined) {
    headers["content-type"] = "application/json";
  }
  if (token) {
    headers.authorization = `Bearer ${token}`;
  }
  return headers;
}

async function parseJsonResponse<T>(response: Response): Promise<T> {
  if (!response.ok) {
    let detail = response.statusText;
    try {
      const payload = (await response.json()) as { detail?: unknown };
      if (typeof payload.detail === "string") {
        detail = payload.detail;
      }
    } catch {
      // 响应体不是 JSON 时退回使用 HTTP 状态文本。
    }
    throw new Error(`请求失败：${response.status} ${detail}`);
  }
  return response.json() as Promise<T>;
}

function normalizeBaseUrl(value: string | undefined): string {
  if (!value) {
    return "";
  }
  return value.replace(/\/$/, "");
}
