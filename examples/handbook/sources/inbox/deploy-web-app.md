---
title: Deploying the Web App
---

# Deploying the Web App

Owner: Platform Engineering.

Use this when releasing a new version of the customer web app to production. Deployments run on
Tuesdays and Thursdays.

Before you start, make sure the release branch has passed CI and you have deploy rights in the
pipeline.

1. Open the deploy pipeline and choose the release tag.
2. Deploy to staging and run the smoke tests.
3. Promote the same build to production.
4. Watch the error-rate dashboard for 15 minutes.

The deployment is done when the error rate stays below 1% and the smoke tests pass in production.
