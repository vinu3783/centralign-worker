import { defineConfig } from "@playwright/test";
import os from "node:os";
import path from "node:path";

// Isolated backend + frontend so E2E runs never touch the development database.
const API_PORT = 8100;
const UI_PORT = 5174;
const dataDir = path.join(os.tmpdir(), `centralign-e2e-${process.pid}`);
const backendDir = path.resolve(import.meta.dirname, "..", "backend");
const python = process.env.PYTHON ??
  path.join(backendDir, ".venv", process.platform === "win32" ? "Scripts/python.exe" : "bin/python");

export default defineConfig({
  testDir: "./e2e",
  timeout: 60_000,
  workers: 1, // tests share one CRM database and reset it between tests
  reporter: [["list"]],
  use: { baseURL: `http://127.0.0.1:${UI_PORT}`, trace: "retain-on-failure", screenshot: "only-on-failure" },
  webServer: [
    {
      command: `"${python}" -m uvicorn app.main:app --port ${API_PORT} --app-dir "${backendDir}"`,
      url: `http://127.0.0.1:${API_PORT}/api/health`,
      reuseExistingServer: false,
      env: {
        DATA_DIR: dataDir,
        DATABASE_URL: `sqlite:///${path.join(dataDir, "e2e.db").split(path.sep).join("/")}`,
        CHECKPOINT_DB_PATH: path.join(dataDir, "checkpoints.db"),
        LLM_PROVIDER: "demo",
        RETRY_BACKOFF_BASE: "0.2",
        FRONTEND_URL: `http://127.0.0.1:${UI_PORT}`,
      },
    },
    {
      command: `npx vite --port ${UI_PORT} --strictPort`,
      url: `http://127.0.0.1:${UI_PORT}`,
      reuseExistingServer: false,
      env: { BACKEND_URL: `http://127.0.0.1:${API_PORT}` },
    },
  ],
});
