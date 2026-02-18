# LinkedIn Batch Resume Downloader (Chrome Extension)

## What it does
- Accepts a text file in popup UI that contains LinkedIn profile URLs (one URL per line).
- Processes the list sequentially and continues on individual failures.
- Uses Chrome DevTools Protocol (CDP) through `chrome.debugger` to click:
  - `More`
  - `Save to PDF`
- Tracks each PDF download through `chrome.downloads` and reports per-URL results.
- Uses the same filename logic as the CDP extension:
  - `https://www.linkedin.com/in/shivam-g-mishra/` -> `shivam-g-mishra.pdf`

## Install (developer mode)
1. Open `chrome://extensions`.
2. Enable **Developer mode**.
3. Click **Load unpacked**.
4. Select folder: `linkedin-profile-extractor`.

## Use
1. Click extension icon.
2. Select a `.txt` file containing one LinkedIn profile URL per line.
3. Click **Start Batch Download**.
4. Watch live progress and final per-URL results in popup.
5. Verify PDFs in Chrome Downloads.

## URL file format
- One LinkedIn profile URL per line.
- Blank lines are ignored.
- Only profile URLs under `https://www.linkedin.com/in/...` are valid.

## Notes
- Assumes you are already logged into LinkedIn.
- CDP selectors are UI-dependent and may need updates when LinkedIn changes labels/layout.
- If one URL fails (invalid URL, missing `Save to PDF`, download interruption), remaining URLs continue.
- Use responsibly and only for data you are authorized to process.
