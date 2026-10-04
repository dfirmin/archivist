---
title: Primary Database Outage Response
---

# Primary Database Outage Response

Owner: Platform Engineering.

Symptoms: the API returns 503 errors and the "db-primary-down" alert fires.

Impact: customers cannot log in or place orders until the database is back.

Immediately: put the web app in maintenance mode and announce the incident in the status channel.

To diagnose, check the database host's disk usage and the replication lag on the replica. If the
primary cannot be restarted within 10 minutes, promote the replica.

After the incident, write a post-incident review within two business days.
