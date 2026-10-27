import { readFileSync } from 'node:fs';
import { createRequire } from 'node:module';
import { dirname, resolve } from 'node:path';
import { runInThisContext } from 'node:vm';
import ts from 'typescript';

const cache = new Map();

/** Compile source in memory using the existing TypeScript dependency; write no test build files. */
export function loadTs(path) {
  path = resolve(path);
  if (cache.has(path)) return cache.get(path).exports;
  const module = { exports: {} }; cache.set(path, module);
  const require = createRequire(path);
  const localRequire = spec => spec.startsWith('.') && !spec.endsWith('.json')
    ? loadTs(resolve(dirname(path), `${spec}.ts`)) : require(spec);
  const { outputText } = ts.transpileModule(readFileSync(path, 'utf8'), {
    compilerOptions: { module: ts.ModuleKind.CommonJS, target: ts.ScriptTarget.ES2022, esModuleInterop: true },
  });
  runInThisContext(`(function(exports, require, module) {\n${outputText}\n})`, { filename: path })(module.exports, localRequire, module);
  return module.exports;
}
