import { getJson, postJson } from "./http";
import type { AuthResponse, WebUser } from "./types";

export async function registerWebUser(username: string, password: string): Promise<AuthResponse> {
  return postJson<AuthResponse>("/api/auth/register", {
    username,
    password,
  });
}

export async function loginWebUser(userId: string, password: string): Promise<AuthResponse> {
  return postJson<AuthResponse>("/api/auth/login", {
    user_id: userId,
    password,
  });
}

export async function fetchCurrentWebUser(token: string): Promise<WebUser> {
  const payload = await getJson<{ user: WebUser }>("/api/auth/me", token);
  return payload.user;
}

export async function logoutWebUser(token: string): Promise<void> {
  await postJson<{ revoked: boolean }>("/api/auth/logout", undefined, token);
}
