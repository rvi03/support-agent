import { InMemoryWebStorage, UserManager, WebStorageStateStore, type User } from "oidc-client-ts";
import { config } from "../config";

// PKCE public client `ui` (D25, D52). Tokens stay in memory only; the short-lived
// PKCE state survives the redirect in sessionStorage (the library default).
export const userManager = new UserManager({
  authority: config.issuer,
  client_id: config.clientId,
  redirect_uri: `${window.location.origin}/`,
  post_logout_redirect_uri: `${window.location.origin}/`,
  response_type: "code",
  scope: "openid profile api store contact",
  userStore: new WebStorageStateStore({ store: new InMemoryWebStorage() }),
  automaticSilentRenew: true, // uses the refresh token, no iframe
  monitorSession: false,
});

export type Role = "store_user" | "l1_agent" | "l2_engineer" | "vendor_approver" | "admin";

export interface Who {
  username: string;
  roles: Role[];
  storeId: string | null;
  token: string;
}

function claims(token: string): Record<string, unknown> {
  const part = token.split(".")[1] ?? "";
  const json = atob(part.replace(/-/g, "+").replace(/_/g, "/"));
  return JSON.parse(decodeURIComponent(escape(json))) as Record<string, unknown>;
}

/** The role and store come from the access token the API itself checks. */
export function whoFrom(user: User): Who {
  const c = claims(user.access_token);
  const realm = c.realm_access as { roles?: string[] } | undefined;
  return {
    username: String(c.preferred_username ?? "user"),
    roles: (realm?.roles ?? []) as Role[],
    storeId: typeof c.store_id === "string" ? c.store_id : null,
    token: user.access_token,
  };
}

/**
 * Finish a redirect back from Keycloak, if this page load is one. The code is
 * single-use, so the exchange runs once per page load even when React mounts twice.
 */
let pending: Promise<User | null> | null = null;
export function completeLogin(): Promise<User | null> {
  pending ??= exchange();
  return pending;
}

async function exchange(): Promise<User | null> {
  const url = new URL(window.location.href);
  if (url.searchParams.has("code") && url.searchParams.has("state")) {
    const user = await userManager.signinRedirectCallback();
    window.history.replaceState({}, "", url.pathname);
    return user;
  }
  return userManager.getUser();
}
