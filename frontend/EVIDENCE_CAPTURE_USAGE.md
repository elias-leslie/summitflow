# EvidenceCaptureModal Usage

The `EvidenceCaptureModal` component has been successfully ported from portfolio-ai to SummitFlow.

## Import

```tsx
import { EvidenceCaptureModal } from "@/components/evidence";
```

## Props

```tsx
interface EvidenceCaptureModalProps {
  open: boolean;              // Modal open state
  onClose: () => void;        // Close handler
  projectId: string;          // SummitFlow project ID (required)
  pageUrl: string;            // URL of the page to capture
  onCaptured: (result: EvidenceCaptureResult) => void; // Success callback
}
```

## Example Usage

```tsx
"use client";

import { useState } from "react";
import { EvidenceCaptureModal } from "@/components/evidence";
import { Button } from "@/components/ui/button";

export function MyComponent() {
  const [modalOpen, setModalOpen] = useState(false);
  const projectId = "your-project-id"; // Get from context or props
  const currentUrl = typeof window !== "undefined" ? window.location.href : "";

  const handleCaptured = (result) => {
    console.log("Evidence captured:", result);
    if (result.success) {
      // Handle success - maybe refetch evidence list
    }
  };

  return (
    <>
      <Button onClick={() => setModalOpen(true)}>
        Capture Evidence
      </Button>

      <EvidenceCaptureModal
        open={modalOpen}
        onClose={() => setModalOpen(false)}
        projectId={projectId}
        pageUrl={currentUrl}
        onCaptured={handleCaptured}
      />
    </>
  );
}
```

## Features

### Three Capture Modes

1. **Quick Debug** - Fast screenshot capture with no DB entry
   - Saves to `data/debug-captures/latest.png`
   - Includes console errors and network failures
   - Claude can read the file directly

2. **New Feature** - Create a new feature and capture evidence
   - Enter feature name and category
   - Creates feature with single UI acceptance criterion
   - Captures screenshot automatically

3. **Existing Feature** - Attach evidence to existing feature/criterion
   - Search and filter features by name, category, or URL match
   - Auto-selects criteria that match current URL
   - Sortable table with URL matching indicators

### Screen Capture API

The component uses the modern Screen Capture API to capture exactly what the user sees:
- Modal closes before capture (doesn't appear in screenshot)
- User selects which tab/window to share
- High-quality PNG screenshot
- Works on localhost and HTTPS

### Client-Side Evidence Gathering

Automatically captures:
- Console errors and warnings
- Failed network requests
- Page title and viewport size
- Scroll position

## API Endpoints Required

The component expects these endpoints to exist in your SummitFlow backend:

- `GET /api/projects/{project_id}/features` - List features
- `POST /api/projects/{project_id}/features/quick` - Quick feature creation
- `POST /api/projects/{project_id}/evidence/viewport-capture` - Capture with DB entry
- `POST /api/projects/{project_id}/evidence/debug-capture` - Debug capture (no DB)

## Differences from Portfolio AI Version

1. **Added `projectId` prop** - SummitFlow is multi-project, portfolio-ai is single-project
2. **Updated API paths** - All endpoints are project-scoped
3. **Updated theme** - Uses SummitFlow's phosphor-green theme
4. **Field name changes** - Snake_case API fields (e.g., `feature_id` vs `featureId`)
5. **Category options** - Updated for SummitFlow categories (Sitemap, Evidence, Vision, etc.)

## Components Added

As part of this port, the following UI components were created:

- `/components/ui/label.tsx` - Form label component
- `/components/ui/scroll-area.tsx` - Scrollable container component

The Toaster component from `sonner` was also added to `app/providers.tsx` for toast notifications.
