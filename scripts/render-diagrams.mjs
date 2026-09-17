import { createHash } from "node:crypto";
import { existsSync, promises as fs } from "node:fs";
import { basename, dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";
import { execFileSync, spawn } from "node:child_process";

const root = resolve(dirname(fileURLToPath(import.meta.url)), "..");
const sourceDirectory = join(root, "diagrams");
const outputDirectory = join(root, "docs", "assets", "diagrams");
const configPath = join(sourceDirectory, "mermaid-config.json");
const manifestPath = join(outputDirectory, "manifest.json");
const checkOnly = process.argv.includes("--check");
const requiredMermaidVersion = "11.17.0";

async function listMermaidFiles(directory) {
  const entries = await fs.readdir(directory, { withFileTypes: true });
  const files = await Promise.all(
    entries.map(async (entry) => {
      const entryPath = join(directory, entry.name);
      if (entry.isDirectory()) return listMermaidFiles(entryPath);
      return entry.isFile() && entry.name.endsWith(".mmd") ? [entryPath] : [];
    }),
  );
  return files.flat().sort((left, right) => left.localeCompare(right, "en"));
}

function render(source, output) {
  const localCli = join(root, "node_modules", "@mermaid-js", "mermaid-cli", "src", "cli.js");
  const globalRoot =
    process.platform === "win32"
      ? join(process.env.APPDATA ?? "", "npm", "node_modules")
      : execFileSync("npm", ["root", "--global"], {
          encoding: "utf8",
          windowsHide: true,
        }).trim();
  const globalCli = join(globalRoot, "@mermaid-js", "mermaid-cli", "src", "cli.js");
  const globalPackage = join(globalRoot, "@mermaid-js", "mermaid-cli", "package.json");
  const cli = existsSync(localCli) ? localCli : globalCli;
  if (!existsSync(cli)) {
    throw new Error(
      "Mermaid CLI is not installed. Install @mermaid-js/mermaid-cli@11.17.0 globally " +
        "before rendering documentation diagrams.",
    );
  }
  if (!existsSync(localCli)) {
    const installed = execFileSync(
      process.execPath,
      ["-e", `process.stdout.write(require(${JSON.stringify(globalPackage)}).version)`],
      { encoding: "utf8" },
    ).trim();
    if (installed !== requiredMermaidVersion) {
      throw new Error(
        `Mermaid CLI ${requiredMermaidVersion} is required; found ${installed}.`,
      );
    }
  }
  return new Promise((resolveRender, reject) => {
    const child = spawn(
      process.execPath,
      [cli, "-i", source, "-o", output, "-c", configPath, "-b", "transparent"],
      { cwd: root, shell: false, stdio: "inherit" },
    );
    child.on("error", reject);
    child.on("close", (code) => {
      if (code === 0) resolveRender();
      else reject(new Error(`Mermaid rendering failed for ${relative(root, source)} (exit ${code}).`));
    });
  });
}

async function checksum(path) {
  return createHash("sha256").update(await fs.readFile(path)).digest("hex");
}

const files = await listMermaidFiles(sourceDirectory);
if (files.length === 0) throw new Error("No Mermaid sources found in diagrams.");
await fs.mkdir(outputDirectory, { recursive: true });
const configChecksum = await checksum(configPath);
const expectedManifest = {
  mermaidVersion: requiredMermaidVersion,
  configChecksum,
  sources: Object.fromEntries(
    await Promise.all(
      files.map(async (source) => [relative(sourceDirectory, source), await checksum(source)]),
    ),
  ),
};

if (checkOnly) {
  if (!existsSync(manifestPath)) {
    throw new Error("Missing diagram manifest. Render diagrams first.");
  }
  const actualManifest = JSON.parse(await fs.readFile(manifestPath, "utf8"));
  if (JSON.stringify(actualManifest) !== JSON.stringify(expectedManifest)) {
    throw new Error("Diagram sources, configuration, or renderer version are stale.");
  }
}

for (const source of files) {
  const output = join(outputDirectory, `${basename(source, ".mmd")}.png`);
  if (checkOnly) {
    if (!existsSync(output)) throw new Error(`Missing rendered diagram: ${relative(root, output)}`);
  } else {
    await render(source, output);
  }
}

if (!checkOnly) {
  await fs.writeFile(manifestPath, `${JSON.stringify(expectedManifest, null, 2)}\n`);
}
