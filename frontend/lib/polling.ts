/**
 * Centralized polling intervals and timeout constants.
 *
 * All durations in milliseconds. Import from here instead of scattering
 * magic numbers across hooks and components.
 */

// --- Polling intervals ---
/** Standard refresh for dashboard-level data (activity, health, quality). */
export const POLL_STANDARD = 15_000

/** Fast refresh for system stats and actively-changing data. */
export const POLL_FAST = 5_000

/** Slow refresh for background/infrequent data (git status, file explorer). */
export const POLL_SLOW = 60_000

/** Notification count polling interval. */
export const POLL_NOTIFICATIONS = 30_000

// --- Stale times ---
/** Default stale time matching standard poll cadence. */
export const STALE_STANDARD = 15_000

/** Fast stale time for system-level metrics. */
export const STALE_FAST = 4_000

/** Git-level stale time. */
export const STALE_GIT = 30_000

// --- UI feedback timeouts ---
/** Duration to show copy-to-clipboard / save confirmation feedback. */
export const FEEDBACK_TIMEOUT = 2_000

/** Duration to show push notification timeout warnings. */
export const PUSH_NOTIFICATION_TIMEOUT = 10_000
