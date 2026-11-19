import createClient, { type Middleware } from "openapi-fetch";
import type { paths } from "./schema";
import { config } from "../config";

// Typed client generated from docs/openapi.json (`npm run gen:api`).
// The bearer token is read per request, so a silent refresh is picked up at once.
export function makeApi(getToken: () => string | undefined) {
  const api = createClient<paths>({ baseUrl: config.apiUrl });
  const auth: Middleware = {
    onRequest({ request }) {
      const token = getToken();
      if (token) request.headers.set("Authorization", `Bearer ${token}`);
      return request;
    },
  };
  api.use(auth);
  return api;
}

export type Api = ReturnType<typeof makeApi>;
