// Public endpoints only; the UI holds no secrets (PKCE public client `ui`, D25).
export const config = {
  apiUrl: import.meta.env.VITE_API_URL ?? "http://localhost:8000",
  issuer: import.meta.env.VITE_KEYCLOAK_ISSUER ?? "http://localhost:8080/realms/servewell",
  clientId: "ui",
  pollMs: 2000,
} as const;
