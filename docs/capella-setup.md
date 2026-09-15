# Capella setup (about five minutes)

Every notebook here talks to a Couchbase [Capella](https://cloud.couchbase.com)
cluster. The free tier is enough for all of them.

## 1. Create a cluster

Sign up, then create an **Operational** cluster. The free tier gives you one
cluster with the Data, Query, Index and **Search** services. Search is the one
that matters — it holds the vector indexes.

## 2. Create a bucket

*Data Tools → Buckets → Create Bucket*. Name it `demos` (or anything, and set
`CB_BUCKET` to match). The notebooks create their own scopes and collections
inside it, so one bucket covers every demo.

## 3. Create a database access user

*Settings → Database Access → Create Database Access*.

This is **not** your Capella login. It is a separate credential the SDK uses.
Give it **read/write on all buckets** — the notebooks create scopes,
collections and Search indexes.

Record the username and password as `CB_USERNAME` / `CB_PASSWORD`.

## 4. Allow your IP

*Settings → Networking → Allowed IP Addresses → Add Allowed IP*.

- Running locally: click **Add Current IP Address**.
- Running on Colab: the runtime's IP changes and is not knowable in advance,
  so you need `0.0.0.0/0`. That opens the cluster to the internet, protected
  only by the database credential — fine for a throwaway demo cluster with
  public data, not for anything else. Delete the rule when you are done.

## 5. Copy the connection string

*Cluster → Connect → Public Connection String*. It looks like:

```
couchbases://cb.xxxxxxxx.cloud.couchbase.com
```

Keep the `couchbases://` scheme — Capella requires TLS, and the Python SDK
bundles the certificate, so nothing else is needed.

## 6. Point the notebooks at it

Locally, `cp .env.example .env` and fill it in.

On Colab, open the **key icon** in the left sidebar and add secrets named
`CB_CONNECTION_STRING`, `CB_USERNAME`, `CB_PASSWORD`, `CB_BUCKET`, and your
model provider's API key. Grant the notebook access to each one. Any other name from
[`.env.example`](../.env.example) works the same way — for example `CBNB_LLM_PROVIDER` and
`CBNB_LLM_MODEL` to use something other than OpenAI. The setup cell lists which names it
loaded.

If you skip both, the notebooks prompt for what they need — passwords via
`getpass`, so nothing sensitive lands in a stored output.

## Troubleshooting

| Symptom | Cause |
| --- | --- |
| `UnAmbiguousTimeoutException` on connect | IP not on the allow list, or the cluster is paused |
| `AuthenticationException` | Using the Capella login instead of a database access user |
| `BucketNotFoundException` | `CB_BUCKET` does not match a bucket you created |
| Search returns nothing right after loading | The index is still ingesting; `wait_for_index` handles this |
| `PlanningFailureException` on index create | The cluster has no Search service — recreate it with Search enabled |
