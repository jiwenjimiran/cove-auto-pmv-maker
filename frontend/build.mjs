import { build } from "esbuild";
import { mkdir } from "node:fs/promises";

const outdir = new URL("../src/PmvMaker/dist/", import.meta.url).pathname.replace(/^\/(.:\/)/, "$1");
await mkdir(outdir, { recursive: true });
await build({ entryPoints: ["src/index.jsx"], bundle: true, format: "esm", platform: "browser", target: "es2022",
  outfile: `${outdir}/bundle.js`, external: ["@cove/runtime/react", "@cove/runtime/api"] });
await build({ entryPoints: ["src/style.css"], bundle: true, outfile: `${outdir}/bundle.css` });
