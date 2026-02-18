# LinkedIn CDP Resume Downloader (Chrome Extension)

## What this extension does
- Accepts a LinkedIn profile URL (`https://www.linkedin.com/in/...`).
- Uses Chrome DevTools Protocol (CDP) through `chrome.debugger`.
- Simulates human-like mouse movement/click actions to:
  - Click the profile header `More` button.
  - Click `Save to PDF` in the opened menu.
- Detects the PDF download via `chrome.downloads` events and reports status back to popup.

## Important behavior
- Automation is strict CDP input dispatch for menu actions; there is no direct DOM `.click()` fallback.
- You must already be logged into LinkedIn in the same Chrome profile.
- If Chrome asks for download confirmation, completion may pause until you approve.
- PDF filename is set from profile URL slug (for example `https://www.linkedin.com/in/shivam-g-mishra` -> `shivam-g-mishra.pdf`).

## Install (Developer mode)
1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select folder: `linkedin-resume-downloader-cdp`.

## How to use
1. Open any LinkedIn profile URL in Chrome.
2. Click the extension icon.
3. Enter/paste the URL (or use prefilled URL).
4. Click **Download Resume (PDF)**.
5. Wait for success/error status in popup and verify file in Downloads.

## Permissions used
- `debugger`: Send CDP commands for human-like input automation.
- `tabs`: Navigate/activate the profile tab.
- `downloads`: Observe and report PDF download status.
- `storage`: Remember last profile URL used in popup.
- Host permission: `https://www.linkedin.com/*`.

## Known constraints
- LinkedIn UI text/layout changes can break selector matching for `More` or `Save to PDF`.
- If a profile does not expose `Save to PDF`, the run fails with an actionable error.
- Slow pages can increase automation time due to waits/retries.

## Manual verification checklist
- Happy path:
  - Logged-in session.
  - Public profile with visible `More` -> `Save to PDF`.
  - Popup reports success and downloaded file appears in Downloads.
- Negative checks:
  - Non-profile URL is rejected.
  - Logged-out tab errors clearly.
  - Missing `Save to PDF` menu item fails with explicit message.
  - Network slowness still retries before timeout.
