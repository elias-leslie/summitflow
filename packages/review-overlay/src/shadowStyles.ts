export const shadowStyles = `
:host {
  all: initial;
}

.review-overlay-shell {
  position: fixed;
  top: 32px;
  right: 32px;
  z-index: 2147483000;
  width: min(920px, calc(100vw - 48px));
  max-height: calc(100vh - 48px);
  display: flex;
  flex-direction: column;
  border: 1px solid rgba(71, 85, 105, 0.7);
  border-radius: 20px;
  overflow: hidden;
  background:
    radial-gradient(circle at top left, rgba(34, 211, 238, 0.14), transparent 28%),
    linear-gradient(180deg, rgba(2, 6, 23, 0.98), rgba(15, 23, 42, 0.98));
  box-shadow: 0 24px 80px rgba(2, 6, 23, 0.48);
  color: rgb(226, 232, 240);
  font-family: Inter, ui-sans-serif, system-ui, sans-serif;
}

.review-overlay-shell[data-open="false"] {
  display: none;
}

.review-overlay-header {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  padding: 14px 16px;
  background: rgba(15, 23, 42, 0.92);
  border-bottom: 1px solid rgba(51, 65, 85, 0.8);
  cursor: move;
  user-select: none;
}

.review-overlay-title {
  display: flex;
  flex-direction: column;
  gap: 2px;
}

.review-overlay-title strong {
  font-size: 14px;
  letter-spacing: 0.01em;
}

.review-overlay-title span {
  font-size: 11px;
  color: rgb(148, 163, 184);
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
}

.review-overlay-header-actions,
.review-overlay-sidebar-actions,
.review-overlay-composer-actions {
  display: flex;
  gap: 8px;
  align-items: center;
}

.review-overlay-button,
.review-overlay-button-secondary {
  border: 1px solid rgba(71, 85, 105, 0.7);
  border-radius: 999px;
  padding: 8px 12px;
  background: rgba(15, 23, 42, 0.9);
  color: rgb(226, 232, 240);
  font-size: 12px;
  line-height: 1;
  cursor: pointer;
}

.review-overlay-button:hover,
.review-overlay-button-secondary:hover {
  border-color: rgba(148, 163, 184, 0.9);
}

.review-overlay-button:disabled,
.review-overlay-button-secondary:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.review-overlay-button {
  background: rgba(8, 145, 178, 0.22);
  border-color: rgba(34, 211, 238, 0.36);
  color: rgb(165, 243, 252);
}

.review-overlay-body {
  display: grid;
  grid-template-columns: minmax(0, 1.7fr) minmax(280px, 340px);
  min-height: 520px;
}

.review-overlay-chat {
  min-height: 520px;
  background: rgba(2, 6, 23, 0.72);
}

.review-overlay-chat iframe {
  width: 100%;
  height: 100%;
  min-height: 520px;
  border: 0;
  background: rgba(2, 6, 23, 0.72);
}

.review-overlay-sidebar {
  display: flex;
  flex-direction: column;
  gap: 14px;
  padding: 16px;
  border-left: 1px solid rgba(51, 65, 85, 0.8);
  background: rgba(15, 23, 42, 0.94);
}

.review-overlay-sidebar h3 {
  margin: 0;
  font-size: 12px;
  letter-spacing: 0.16em;
  text-transform: uppercase;
  color: rgb(148, 163, 184);
}

.review-overlay-warning {
  display: none;
  padding: 10px 12px;
  border-radius: 14px;
  border: 1px solid rgba(245, 158, 11, 0.35);
  background: rgba(120, 53, 15, 0.34);
  color: rgb(253, 230, 138);
  font-size: 12px;
  line-height: 1.45;
}

.review-overlay-warning[data-visible="true"] {
  display: block;
}

.review-overlay-composer {
  display: none;
  padding: 12px;
  border-radius: 16px;
  border: 1px solid rgba(59, 130, 246, 0.28);
  background: rgba(15, 23, 42, 0.7);
}

.review-overlay-composer[data-visible="true"] {
  display: block;
}

.review-overlay-composer p {
  margin: 0 0 8px;
  font-size: 12px;
  color: rgb(148, 163, 184);
}

.review-overlay-composer textarea {
  width: 100%;
  min-height: 96px;
  resize: vertical;
  border-radius: 14px;
  border: 1px solid rgba(71, 85, 105, 0.8);
  background: rgba(2, 6, 23, 0.75);
  color: rgb(226, 232, 240);
  padding: 12px;
  box-sizing: border-box;
  font: inherit;
}

.review-overlay-evidence-list {
  display: flex;
  flex-direction: column;
  gap: 10px;
  overflow: auto;
  min-height: 0;
}

.review-overlay-evidence-item {
  border: 1px solid rgba(51, 65, 85, 0.8);
  border-radius: 16px;
  padding: 12px;
  background: rgba(2, 6, 23, 0.55);
}

.review-overlay-evidence-item strong {
  display: block;
  margin-bottom: 6px;
  font-size: 12px;
  color: rgb(148, 163, 184);
}

.review-overlay-evidence-item p {
  margin: 0;
  white-space: pre-wrap;
  font-size: 13px;
  line-height: 1.5;
}

.review-overlay-empty {
  border: 1px dashed rgba(71, 85, 105, 0.8);
  border-radius: 16px;
  padding: 16px;
  color: rgb(148, 163, 184);
  font-size: 12px;
  line-height: 1.5;
}

@media (max-width: 960px) {
  .review-overlay-shell {
    left: 16px;
    right: 16px;
    width: auto;
    top: 16px;
    max-height: calc(100vh - 32px);
  }

  .review-overlay-body {
    grid-template-columns: 1fr;
  }

  .review-overlay-sidebar {
    border-left: 0;
    border-top: 1px solid rgba(51, 65, 85, 0.8);
  }
}
`
