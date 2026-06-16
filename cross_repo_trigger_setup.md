# Cross-Repo Trigger Setup

## Overview

The Health Tracker consolidation workflow needs to run automatically whenever
either upstream source file is updated.  GitHub Actions does not natively
support cross-repository push triggers, so we use the `repository_dispatch`
API event pattern.

Each upstream repository's workflow is modified to send an HTTP POST to the
Health Tracker repo after a successful data update.

---

## How It Works

```
[whoop-data] daily_sync.yml completes
    ↓
Sends POST to Health Tracker /dispatches (event_type: "whoop_updated")
    ↓
Health Tracker consolidate.yml triggers

[MyFitnessClone] generate_dashboard.yml completes
    ↓
Sends POST to Health Tracker /dispatches (event_type: "meal_updated")
    ↓
Health Tracker consolidate.yml triggers
```

Even without the dispatch events, the scheduled cron at 13:30 UTC acts as a
guaranteed daily fallback.

---

## Step 1 — Create a Dispatch PAT

You need a GitHub Personal Access Token that has permission to trigger
workflows in the `health-tracker` repository.

1. Go to: https://github.com/settings/tokens?type=beta
2. Click **Generate new token**
3. Name: `health-tracker-dispatch`
4. Repository access: Select only `health-tracker`
5. Permissions:
   - **Actions** → Read and write
6. Generate and **copy the token** (shown only once)

> The same `GH_PAT` used in `whoop-data` likely already has this permission
> if it was given repo-wide Actions write access.  You can reuse it.

---

## Step 2 — Add the PAT as a Secret in Each Upstream Repo

### In `whoop-data`:
- Settings → Secrets and variables → Actions → New repository secret
- Name: `HEALTH_TRACKER_DISPATCH_TOKEN`
- Value: the PAT from Step 1

### In `MyFitnessClone`:
- Same process
- Name: `HEALTH_TRACKER_DISPATCH_TOKEN`
- Value: same PAT

---

## Step 3 — Add Dispatch Step to whoop-data daily_sync.yml

Add this step **after** the "Commit and push updated CSVs" step:

```yaml
      - name: Trigger Health Tracker consolidation
        if: success()
        env:
          DISPATCH_TOKEN: ${{ secrets.HEALTH_TRACKER_DISPATCH_TOKEN }}
          GH_USERNAME:    ${{ secrets.GH_USERNAME }}
        run: |
          curl -s -o /dev/null -w "%{http_code}" \
            -X POST \
            -H "Accept: application/vnd.github+json" \
            -H "Authorization: Bearer $DISPATCH_TOKEN" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            https://api.github.com/repos/$GH_USERNAME/health-tracker/dispatches \
            -d '{"event_type": "whoop_updated"}' \
          | grep -q "204" && echo "Dispatch sent successfully." \
                          || echo "WARNING: Dispatch failed — Health Tracker scheduled fallback will run."
```

---

## Step 4 — Add Dispatch Step to MyFitnessClone generate_dashboard.yml

Add this step **after** the "Push changes" step:

```yaml
      - name: Trigger Health Tracker consolidation
        if: success()
        env:
          DISPATCH_TOKEN: ${{ secrets.HEALTH_TRACKER_DISPATCH_TOKEN }}
          GH_USERNAME:    ${{ secrets.GH_USERNAME }}
        run: |
          curl -s -o /dev/null -w "%{http_code}" \
            -X POST \
            -H "Accept: application/vnd.github+json" \
            -H "Authorization: Bearer $DISPATCH_TOKEN" \
            -H "X-GitHub-Api-Version: 2022-11-28" \
            https://api.github.com/repos/$GH_USERNAME/health-tracker/dispatches \
            -d '{"event_type": "meal_updated"}' \
          | grep -q "204" && echo "Dispatch sent successfully." \
                          || echo "WARNING: Dispatch failed — Health Tracker scheduled fallback will run."
```

---

## Notes

- If the dispatch fails (network issue, expired token), the 13:30 UTC schedule
  guarantees the consolidation still runs daily.
- The dispatch uses `if: success()` so it only fires when the upstream job
  actually produced updated data.
- The `GH_USERNAME` secret should already exist in both upstream repos
  from the Health Tracker setup.  If not, add it as a secret there too.
- HTTP 204 = success from the dispatches endpoint.  Any other code is logged
  as a warning but does not fail the upstream workflow.
