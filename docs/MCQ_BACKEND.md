# MCQ backend contract and operations

This document is the source of truth for the MCQ domain. Update it in the same pull request as any model, endpoint, import, or queue change.

## Data model

`Event` is an MCQ session owned by this service. `external_event_id` and `external_slot_id` identify the corresponding records in the external event-management service; they are not this service's UUIDs. An external slot can map to only one local event.

`Question` belongs to one event and has exactly four ordered options. `correct_option` is a **zero-based** index (0–3). `User_Question` is the user's assigned copy/reference of a question, with an optional zero-based `answer` and a review flag. `User_Event` is a user's participation record. `User_Result` is the single computed result for one participation record.

Database constraints prevent duplicate user-event, user-question, and user-result rows. They also reject invalid time ranges and answer indexes. Apply the migration only after checking production data for duplicate values, because PostgreSQL correctly refuses to add a uniqueness constraint when existing rows conflict.

## API payloads

All authenticated requests use `Authorization: Bearer <access-token>`.

`GET /api/event/list` returns the user's event participations. `GET /api/question/list/{user_event_id}` assigns questions once, then returns the same assignment on subsequent calls. It rejects events that have not started, ended, or were submitted.

`PATCH /api/question/answer` accepts only the user's own assigned question:

```json
{
  "id": "user-question-uuid",
  "answer": 2,
  "review_status": false
}
```

`answer` may be `null` or an integer from 0 to 3. The endpoint does not expose `correct_option`.

`POST /api/event/submit/{user_event_id}` submits a user's event once. It is intentionally a POST, not a GET, because it changes state. `POST /api/events/submit` is an administrator-only recovery action that recalculates already-finished events.

## Admin and CSV import

In **Admin → Questions**, download the template, fill it with UTF-8 CSV data, then use **Import CSV**. The importer validates every row before it writes any question. Required headers are:

```text
event_id,statement,option_a,option_b,option_c,option_d,correct_option,code,image_url
```

`event_id` is the local Event UUID, not `external_event_id`. Exporting selected questions produces the same format, so it can be edited and re-imported.

## Redis and Celery

Redis database 0 is the Celery broker and database 1 is reserved for task results. Task result retention is one hour and task results are ignored because result scoring is stored durably in PostgreSQL. Redis has an explicit memory cap and `noeviction`: it fails visibly instead of silently dropping queued jobs. Production persists Redis data via append-only storage.

Alert on Redis memory above 80%, failed Celery tasks, and queue depth. If Redis rejects writes, increase capacity or drain/retry work; do not change to an eviction policy because it can lose submissions.

Result tasks are idempotent: retrying a task updates the one result for the user event instead of creating duplicate scores.

## Delivery checks

GitHub Actions runs migration-drift detection, production Django checks, the test suite, and a Docker build on pull requests and pushes to `master` or `staging`. The existing `publish` workflow publishes only from `staging`; publishing should be kept dependent on a passing CI run.
