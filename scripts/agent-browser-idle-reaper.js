#!/usr/bin/env node
// Scheduled cleanup is owned by browser-automation through the registered ST route.
const { runIsolatedCleanup } = require('./agent-browser-isolated-reaper.js');
if (require.main === module) {
  process.exitCode = runIsolatedCleanup({ dryRun: process.argv.includes('--dry-run') });
}
module.exports = { runIsolatedCleanup };
