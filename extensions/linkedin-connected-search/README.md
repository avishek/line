# LinkedIn Connected Search (Chrome Extension)

## What it does
- Takes a candidate name as input (for example `alex soh`).
- Builds and opens LinkedIn people search URL with:
  - `keywords=<candidate name>`
  - `network=["F","S"]`
  - `origin=FACETED_SEARCH`
- Uses Chrome DevTools Protocol (CDP) through `chrome.debugger` to click the first rendered profile in results.
- On the opened profile page, checks if mutual connections are present.
- Downloads a `.txt` file containing:
  - `query_name`
  - `profile_url`
  - `has_mutual_connections`

## Install (developer mode)
1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select folder: `extensions/linkedin-connected-search`.

## How to use
1. Ensure you are logged into LinkedIn in the same Chrome profile.
2. Click the extension icon.
3. Enter candidate name.
4. Click **Run Connected Search**.
5. Wait for status to show completion.
6. Check Chrome Downloads for file:
   - `linkedin-connected-search-<name>-<timestamp>.txt`

## Notes
- The extension stores the **first searched name** in `chrome.storage.local` and reuses it to prefill popup input.
- LinkedIn UI changes can affect selectors/heuristics used to locate the first result or connection signals.
- The mutual connection signal is considered true if:
  - page text contains `mutual connection(s)`, or
  - top profile card style content indicates a connection block near action controls.

## Manual validation checklist
- Enter `alex soh` and confirm search URL includes encoded keywords and network filter values.
- Confirm first person result is clicked automatically.
- Confirm profile URL captured is under `https://www.linkedin.com/in/...`.
- Confirm output file is downloaded and contains all three required lines.
- Validate both mutual/no-mutual cases on different profiles.
