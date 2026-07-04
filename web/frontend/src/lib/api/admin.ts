import { getJson, postJson } from "./http";
import type { AdminBindingsResponse, LinkCode } from "./types";

export async function fetchAdminBindings(token: string): Promise<AdminBindingsResponse> {
  return getJson<AdminBindingsResponse>("/api/admin/bindings", token);
}

export async function issueLinkCode(token: string): Promise<LinkCode> {
  return postJson<LinkCode>("/api/admin/link-codes", undefined, token);
}
