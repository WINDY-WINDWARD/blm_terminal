# Widget screenshots

These PNG files are captured from the installed BLM Terminal desktop app through CDP.
Regenerate them after a widget layout change:

```powershell
npm run docs:screenshots
```

Use `-- --only=CHART,ORDER` to recapture a subset.

ORDER has no screenshot. The order deck shows only a gateway error until OpenAlgo is
configured, so its DOCS page is text only.

POS needs `$env:BLM_SCREENSHOT_SEED_POS="1"` to seed three paper trades for the capture.
The script deletes those trades after the screenshot.
