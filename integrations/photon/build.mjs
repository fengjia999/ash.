// Transpile the pinned transport without loading Spectrum's entire SDK type graph.
// The runtime and protocol behavior are covered by the colocated Node tests.
import ts from 'typescript';
import {mkdir, readdir, readFile, writeFile} from 'node:fs/promises';
await mkdir(new URL('./dist/',import.meta.url),{recursive:true});
for(const name of await readdir(new URL('./src/',import.meta.url))){
  if(!name.endsWith('.ts')||name.endsWith('.test.ts'))continue;
  const result=ts.transpileModule(await readFile(new URL('./src/'+name,import.meta.url),'utf8'),{
    fileName:name,reportDiagnostics:true,compilerOptions:{target:ts.ScriptTarget.ES2022,module:ts.ModuleKind.ES2022,isolatedModules:true},
  });
  const errors=(result.diagnostics||[]).filter(item=>item.category===ts.DiagnosticCategory.Error);
  if(errors.length)throw new Error(ts.formatDiagnosticsWithColorAndContext(errors,{getCurrentDirectory:()=>process.cwd(),getCanonicalFileName:value=>value,getNewLine:()=>"\n"}));
  await writeFile(new URL('./dist/'+name.replace(/\.ts$/,'.js'),import.meta.url),result.outputText);
}
console.log('Built bundled iMessage transport.');
