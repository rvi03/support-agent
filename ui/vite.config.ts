import { defineConfig } from "vite";
import react from "@vitejs/plugin-react";

// The Demo UI (S13) only serves the page; the browser calls the API (:8000) and
// Keycloak (:8080) through the platform gateway, as the realm and CORS expect.
export default defineConfig({
  plugins: [react()],
  server: { host: "0.0.0.0", port: 5173, strictPort: true },
});
