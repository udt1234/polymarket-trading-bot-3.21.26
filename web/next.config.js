// Load the repo-root .env (one level up) for local dev so SUPABASE_URL /
// SUPABASE_SERVICE_KEY / NEXT_PUBLIC_API_URL don't need duplicating in web/.
// On Railway these come from service variables and the file simply won't exist.
const fs = require("fs");
const path = require("path");

const rootEnv = path.join(__dirname, "..", ".env");
if (fs.existsSync(rootEnv)) {
  for (const line of fs.readFileSync(rootEnv, "utf8").split(/\r?\n/)) {
    const m = line.match(/^\s*([A-Za-z_][A-Za-z0-9_]*)\s*=\s*(.*)\s*$/);
    if (m && process.env[m[1]] === undefined) {
      process.env[m[1]] = m[2].replace(/^["']|["']$/g, "");
    }
  }
}

/** @type {import('next').NextConfig} */
const nextConfig = {
  output: "standalone",
};

module.exports = nextConfig;
