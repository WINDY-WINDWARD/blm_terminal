# Updater Configuration

**CURRENTLY CONFIGURED FOR LOCALHOST TESTING.**

Before releasing to production or pushing tags for public/remote distribution, you MUST change the `publish` provider in `electron-builder.json` back to GitHub (or configure your private production update server):

```json
"publish": [
  {
    "provider": "github",
    "owner": "WINDY-WINDWARD",
    "repo": "blm_terminal"
  }
]
```

### Local Testing Workflow
- The app checks `http://127.0.0.1:8080/latest.yml` for updates.
- Serve `dist-desktop` via HTTP:
  ```powershell
  python -m http.server 8080 --directory dist-desktop
  ```
- Any new build whose version in `latest.yml` exceeds the currently installed app version will download and prompt to install.
