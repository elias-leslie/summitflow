#!/usr/bin/env node
// Scheduled cleanup is owned by browser-automation through the registered ST route.
// The same timer closes managed browser sessions nobody uses (idle, ended owner,
// paused too long) and stops orphaned VM Chromes; profiles are kept.
const { spawnSync } = require('child_process');
const os = require('os');
const path = require('path');
const { runIsolatedCleanup } = require('./agent-browser-isolated-reaper.js');

function runSessionReap(options = {}) {
  const st = options.st || path.join(os.homedir(), 'bin', 'st');
  const args = ['browser', 'session', 'reap'];
  if (options.dryRun) args.push('--dry-run');
  const result = spawnSync(st, args, { stdio: 'inherit', timeout: 240000 });
  if (result.error) {
    process.stderr.write(`Browser session reaper unavailable: ${result.error.message}\n`);
    return 2;
  }
  return result.status ?? 2;
}

if (require.main === module) {
  const dryRun = process.argv.includes('--dry-run');
  const isolated = runIsolatedCleanup({ dryRun });
  const sessions = runSessionReap({ dryRun });
  process.exitCode = isolated || sessions;
}
module.exports = { runIsolatedCleanup, runSessionReap };
