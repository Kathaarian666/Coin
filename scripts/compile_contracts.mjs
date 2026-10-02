// Compiles contracts/*.sol with solc-js and writes ABI + bytecode to contracts/build.
// Usage: npm install --no-save solc@0.8.26 && node scripts/compile_contracts.mjs
import fs from "node:fs";
import path from "node:path";
import { createRequire } from "node:module";

const require = createRequire(import.meta.url);
const solc = require("solc");

const root = path.resolve(path.dirname(new URL(import.meta.url).pathname), "..");
const sources = {
  "HoneypotProbe.sol": "contracts/HoneypotProbe.sol",
  "test/Mocks.sol": "contracts/test/Mocks.sol",
};

const input = {
  language: "Solidity",
  sources: Object.fromEntries(
    Object.entries(sources).map(([name, file]) => [
      name,
      { content: fs.readFileSync(path.join(root, file), "utf8") },
    ]),
  ),
  settings: {
    optimizer: { enabled: true, runs: 200 },
    viaIR: true,
    // Robinhood Chain (Arbitrum Nitro) accepts Cancun opcodes; paris keeps it portable.
    evmVersion: "paris",
    outputSelection: { "*": { "*": ["abi", "evm.bytecode.object", "evm.deployedBytecode.object"] } },
  },
};

const output = JSON.parse(solc.compile(JSON.stringify(input)));
const errors = (output.errors || []).filter((e) => e.severity === "error");
for (const e of output.errors || []) console.error(e.formattedMessage);
if (errors.length) process.exit(1);

const outDir = path.join(root, "contracts/build");
fs.mkdirSync(outDir, { recursive: true });
for (const [, contracts] of Object.entries(output.contracts)) {
  for (const [name, c] of Object.entries(contracts)) {
    if (!c.evm.bytecode.object) continue; // interfaces
    const artifact = {
      contractName: name,
      compiler: solc.version(),
      abi: c.abi,
      bytecode: "0x" + c.evm.bytecode.object,
      deployedBytecode: "0x" + c.evm.deployedBytecode.object,
    };
    fs.writeFileSync(path.join(outDir, `${name}.json`), JSON.stringify(artifact, null, 2) + "\n");
    console.log(`wrote contracts/build/${name}.json`);
  }
}
