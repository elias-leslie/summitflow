#!/usr/bin/env node
// The browser owner performs lifecycle recovery through the registered ST route.
// This caller has no PID discovery, profile selection, or process-killing logic.
const { spawnSync } = require('child_process');
const os = require('os');
const path = require('path');

function runIsolatedCleanup(options = {}) {
  const st = options.st || path.join(os.homedir(), 'bin', 'st');
  const args = ['browser', '--local-ai', 'reap-isolated'];
  if (options.dryRun) args.push('--dry-run');
  // Owner budget is 120s; measured ST startup is <1s. Allow 2s for dispatch/exit.
  const result = spawnSync(st, args, { stdio: 'inherit', timeout: 122000 });
  if (result.error) {
    process.stderr.write(`Browser cleanup owner unavailable: ${result.error.message}\n`);
    return 2;
  }
  return result.status ?? 2;
}

if (require.main === module) {
  process.exitCode = runIsolatedCleanup({ dryRun: process.argv.includes('--dry-run') });
}
module.exports = { runIsolatedCleanup };
