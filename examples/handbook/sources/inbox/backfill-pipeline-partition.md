---
title: Backfilling a Pipeline Partition
owner: Data Engineering
---

# Backfilling a Pipeline Partition

## When to use

Use this when a daily partition of a warehouse table is missing or loaded with bad data and must
be rebuilt.

## Before you start

- You have the `de-operator` role in the orchestrator.
- The upstream source data for that day is available.

## Steps

1. Pause the table's scheduled DAG so it does not overwrite your backfill.
2. Run the backfill job for the partition date: `backfill --table <name> --date <YYYY-MM-DD>`.
3. Compare the row count with the source system's count for that day.
4. Unpause the DAG.

## Check it worked

Row counts match within 0.1% and the data quality checks for the partition pass.

## Rollback

If the backfill loads bad data, restore the partition from the previous night's snapshot with
`restore --table <name> --date <YYYY-MM-DD>` and unpause the DAG.
