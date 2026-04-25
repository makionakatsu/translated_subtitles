#!/usr/bin/env node
/**
 * Copy jassub's worker + wasm artefacts into public/jassub/ so Next.js serves
 * them as static assets. Run automatically via predev / prebuild hooks.
 */
import { mkdir, copyFile, readdir } from "node:fs/promises";
import { existsSync } from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const __dirname = path.dirname(fileURLToPath(import.meta.url));
const SRC = path.resolve(__dirname, "..", "node_modules", "jassub", "dist");
const DEST = path.resolve(__dirname, "..", "public", "jassub");

if (!existsSync(SRC)) {
  console.error(
    `[copy-jassub] ${SRC} does not exist. Did you run pnpm install?`
  );
  process.exit(1);
}

await mkdir(DEST, { recursive: true });
const entries = await readdir(SRC);
const wanted = entries.filter(
  (n) =>
    n.startsWith("jassub-worker") ||
    n.endsWith(".woff2") || // bundled fallback font
    n.endsWith(".wasm")
);
for (const name of wanted) {
  await copyFile(path.join(SRC, name), path.join(DEST, name));
}
console.log(`[copy-jassub] copied ${wanted.length} files to ${DEST}`);
