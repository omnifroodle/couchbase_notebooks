# A cheap fit check: separation among a few ideal results

Scratch spike, 2026-10-29. Not a notebook yet; see the roadmap's `retrieval/` backlog.

N diverse reference queries, one ideal document each, and an index that holds only those N
documents. For each query, **separation** is its own ideal's score minus the mean score of the
other queries' ideals. It is a first screen whose results feed the full evaluation
(`retrieval/04`), not a verdict on its own.

`separation.py` runs on WANDS (40 queries, ideal = each query's first `Exact` label, fixed
independently of the model) with the embeddings `retrieval/04` already cached, so it sends
nothing to a provider once that notebook has run:

```bash
.venv/bin/python spikes/embedding_separation/separation.py
```

## What it found

| | good | bad (mean) | separation | good ranked first |
| --- | --- | --- | --- | --- |
| all-MiniLM-L6-v2 | 0.52 | 0.13 | 0.39 | 92% |
| text-embedding-3-small | 0.53 | 0.22 | 0.31 | 90% |
| Qwen3-Embedding-0.6B | 0.50 | 0.26 | 0.24 | 85% |
| Qwen3, instruction left off | 0.70 | 0.52 | 0.19 | 68% |

- **It catches a broken setup with 4 queries.** Separation ranked Qwen3 with its instruction
  above Qwen3 without it in essentially every one of 2,000 random draws of 4 queries (at least 99.5%). Raw similarity picks the
  broken version, which scores highest (0.70).
- **Raw separation is not comparable across models.** Unrelated pairs sit at 0.13 for MiniLM and
  0.26 for Qwen3. Divided by the spread of the bad scores, 20 queries agree with the
  full-catalogue best model (`retrieval/04`'s nDCG@10) in 90% of draws, and 4 queries in 50%.
- **Diverse queries test topic separation, not near misses.** MiniLM ranks its ideal first most
  often here, yet it has the lowest nDCG@10 across the full catalogue. The hard part of the full
  catalogue is near misses, and an index of a few ideals contains none.

Caveats: one corpus, three models whose nDCG@10 values are within three points of each other,
and ideal documents chosen by a labelling rule rather than a person.
