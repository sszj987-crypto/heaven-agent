import { readFileSync, existsSync } from "node:fs";
import { createRequire } from "node:module";
import path from "node:path";
import { fileURLToPath } from "node:url";
import ts from "typescript";
import { createElement } from "react";
import { renderToStaticMarkup } from "react-dom/server";

const root = fileURLToPath(new URL("../../", import.meta.url));

// Compile project TSX in memory using the installed TypeScript compiler. Real
// React SSR exercises component output; only Next's current route is supplied.
export function renderComponent(file, props = {}, pathname = "/") {
  const cache = new Map();
  function load(filename) {
    if (cache.has(filename)) return cache.get(filename).exports;
    const compiled = { exports: {} };
    cache.set(filename, compiled);
    const nativeRequire = createRequire(filename);
    const require = (specifier) => {
      if (specifier === "next/navigation") return { usePathname: () => pathname };
      if (specifier.endsWith(".css")) return {};
      if (!specifier.startsWith(".") && !specifier.startsWith("@/")) return nativeRequire(specifier);
      const base = specifier.startsWith("@/")
        ? path.join(root, specifier.slice(2))
        : path.resolve(path.dirname(filename), specifier);
      const resolved = [base, `${base}.ts`, `${base}.tsx`].find(candidate => existsSync(candidate));
      if (!resolved) throw new Error(`Cannot resolve ${specifier} from ${filename}`);
      return load(resolved);
    };
    const { outputText } = ts.transpileModule(readFileSync(filename, "utf8"), {
      fileName: filename,
      compilerOptions: { module: ts.ModuleKind.CommonJS, jsx: ts.JsxEmit.ReactJSX, esModuleInterop: true },
    });
    new Function("require", "module", "exports", outputText)(require, compiled, compiled.exports);
    return compiled.exports;
  }
  const [filename, exportName = "default"] = file.split("#");
  const Component = load(path.join(root, filename))[exportName];
  return renderToStaticMarkup(createElement(Component, props));
}
