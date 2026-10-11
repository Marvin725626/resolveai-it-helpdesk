const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const ts = require('typescript');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '../src/csv.ts'), 'utf8');
const { outputText } = ts.transpileModule(source, { compilerOptions: { module: ts.ModuleKind.CommonJS } });
const sandbox = { exports: {} };
vm.runInNewContext(outputText, sandbox);
const { ticketCsv } = sandbox.exports;
assert.equal(ticketCsv([['问题', '描述'], ['VPN', '含"引号",和逗号\n换行']]), '\uFEFF"问题","描述"\r\n"VPN","含""引号"",和逗号\n换行"');
for (const prefix of ['=SUM(1,2)', '+cmd', '-1+2', '@SUM(A1)', '  =HYPERLINK("x")', '\t=SUM(A1)']) {
  assert(ticketCsv([[prefix]]).startsWith('\uFEFF"\''), 'formula prefix must be neutralized');
}
assert.equal(ticketCsv([['普通文本', '2026-10-12', '']]), '\uFEFF"普通文本","2026-10-12",""');
console.log('CSV export checks passed: Unicode/quotes/newlines, formula prefixes, plain text.');
