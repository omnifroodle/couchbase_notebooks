# Datasets

Every dataset this project has used or considered, with its licence and the reason for the
verdict. It is here so nobody has to repeat a licence check, and because finding a usable
dataset is often harder than the technique a notebook teaches.

**How a dataset qualifies.** This repo is public and Apache 2.0, and commits small samples of
its data. So a dataset has to allow commercial use and redistribution. Share-alike licences
are usable with care, because the committed sample then carries the share-alike terms.
"Research only", "non-commercial" and no stated licence all rule a dataset out. Read the licence
file itself, not a README's summary of it or a mirror's tag. The HuggingFace BEIR mirrors, for
example, contradict their upstream terms.

This page is not legal advice. Licences change, so check the source before relying on one.
The **Checked** column says when each was last read; a dash means not re-read since the dataset was adopted.

## In use

| Dataset | Licence | What it is | Used by | Checked |
| --- | --- | --- | --- | --- |
| [WANDS](https://github.com/wayfair/WANDS) (Wayfair) | MIT | 43k real product listings, a 1,623-path category taxonomy, 480 search queries, 233k relevance judgements | `retrieval/*`, `enrich/01` | — |
| [CUAD](https://www.atticusprojectai.org/cuad) | CC BY 4.0 (annotations) | 510 commercial contracts from SEC filings, with lawyer-annotated clause spans. The authors do not warrant the licence status of the underlying EDGAR filings. | `flows/01`, `data-model/*`, `enrich/02` | — |
| Synthetic customer profiles | Apache 2.0 (generated here by [`cbnb/profiles.py`](../cbnb/profiles.py)) | 1,000 known customers and 400 incoming records with known owners, including deliberate lookalikes. Real names, invented people. | `experiments/02` | — |
| [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii) (UCI) | CC BY 4.0 | 1.07M invoice lines from a UK online gift shop, Dec 2009 – Dec 2011, with a customer ID, country and timestamp. Many customers are wholesalers. | `experiments/03` | 2026-09-29 |

## Considered

### People and entity resolution

No public dataset found so far links one real person's two identities, and none has
households. Anything testing those has to be synthetic, and has to say so.

| Dataset | Licence | Verdict | Checked |
| --- | --- | --- | --- |
| [Splink `fake_1000`](https://github.com/moj-analytical-services/splink_datasets) | MIT | **Usable.** 1,000 synthetic records of 250 people, labelled. Someone else's noise model, so a useful check on ours. Some labelled matches are implausible, such as a birth date a year and a month off with a different first name. | 2026-09-29 |
| [Splink `historical_50k`](https://github.com/moj-analytical-services/splink_datasets) | MIT (built from Wikidata, CC0) | **Usable, with a caveat.** 50,000 records of 5,156 historical figures with injected errors. A language model may recognise famous people, which would flatter a model-based matcher. | 2026-09-29 |
| Febrl 1–4 (via `recordlinkage` and Splink) | Unclear | **Not used.** Synthetic person records with duplicates. It is redistributed by MIT-licensed projects, but no licence for the data itself was found. | 2026-09-29 |
| Voter registration extracts (e.g. North Carolina) | Public record | **Not used.** These are real people. | 2026-09-29 |

### Clickstreams and purchase histories

| Dataset | Licence | Verdict | Checked |
| --- | --- | --- | --- |
| [Online Retail II](https://archive.ics.uci.edu/dataset/502/online+retail+ii) | CC BY 4.0 | **In use**, see above. | 2026-09-29 |
| [OTTO session dataset](https://github.com/otto-de/recsys-dataset) | CC BY 4.0 (code MIT) | **Usable.** Clicks, basket adds and orders from 12.9M users of a German retailer. Each "session" is all of one user's activity in the period. Too large to commit; it would need a download step and a sample. | 2026-09-29 |
| [RetailRocket](https://www.kaggle.com/datasets/retailrocket/ecommerce-dataset) | CC BY-NC-SA 4.0 | **Not usable:** non-commercial. | 2026-09-29 |
| REES46 multi-category store and cosmetics shop (Kaggle) | "© Original Authors" | **Not usable:** no licence granted. | 2026-09-29 |
| [Coveo SIGIR eCom 2021](https://github.com/coveooss/SIGIR-ecom-data-challenge) | Research-only terms, behind registration | **Not usable.** Sessions also reset after 30 minutes, so there is no user history. | 2026-09-29 |
| YooChoose (RecSys Challenge 2015), Diginetica (CIKM Cup 2016) | None found | **Not used** until a written licence turns up. | 2026-09-29 |

No openly licensed dataset found has IP addresses or device fingerprints. Those are personal
data, which is presumably why.

### Retrieval and question answering

From the corpus decision in [`roadmap.md`](roadmap.md#decisions).

| Dataset | Licence | Verdict |
| --- | --- | --- |
| MS MARCO (and the TREC RAG track built on it) | Non-commercial research only | **Not usable.** The restriction spreads to everything built on it. |
| RAGBench | Tagged CC BY 4.0 | **Not usable.** Its components include MS MARCO. |
| SciFact | CC BY-NC | **Not usable.** |
| NFCorpus, FiQA | Non-commercial | **Not usable.** |
| HotpotQA | CC BY-SA 4.0 | **Usable runner-up** (share-alike). |
| Natural Questions | CC BY-SA 3.0 | **Usable runner-up** (share-alike). |
| BEIR HuggingFace mirrors | Tags contradict upstream | **Check upstream**, never the mirror's tag. |

## Still looking for

- **People with known duplicates and households**: real, or synthetic from a published
  generator other than ours.
- **Conversations**, for chat with memory (`flows/02`).
- **Multilingual text** with a clean licence. See the roadmap's warning on translation corpora.

Found one? Add a row here with the licence and the date you read it, even if the verdict is no.
