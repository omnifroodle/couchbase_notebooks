"""Couchbase Capella plumbing: connect, provision, index, load, search.

Written against the Python SDK 4.x and a Capella Operational cluster. Every
``ensure_*`` function is idempotent -- re-running a notebook cell should be
boring.
"""

from __future__ import annotations

import time
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import timedelta
from typing import Any

import numpy as np

DEFAULT_SCOPE = "demo"


def connect(settings: object | None = None, *, connect_seconds: int = 25):
    """Open a cluster connection, prompting for anything missing first.

    Capella needs TLS (``couchbases://``) and a database access user -- that is
    the credential you create under *Settings -> Database Access*, not your
    Capella login. See ``docs/capella-setup.md``.

    Fails after ``connect_seconds`` with the likely fixes, rather than the SDK's
    default of hanging for two minutes on an unreachable cluster.
    """
    from couchbase.auth import PasswordAuthenticator
    from couchbase.cluster import Cluster
    from couchbase.exceptions import AuthenticationException, CouchbaseException
    from couchbase.options import ClusterOptions, ClusterTimeoutOptions

    if settings is None:
        from cbnb.config import load_settings

        settings = load_settings()
    settings.require_couchbase()  # type: ignore[union-attr]

    options = ClusterOptions(
        PasswordAuthenticator(settings.cb_username, settings.cb_password)  # type: ignore[union-attr]
    )
    # Capella sits behind the public internet; the WAN profile relaxes the
    # operation timeouts that are tuned for a same-datacentre cluster...
    options.apply_profile("wan_development")
    # ...but an unreachable cluster should fail fast, not after 120s.
    options["timeout_options"] = ClusterTimeoutOptions(
        connect_timeout=timedelta(seconds=connect_seconds),
        bootstrap_timeout=timedelta(seconds=connect_seconds),
        kv_timeout=timedelta(seconds=20),
        search_timeout=timedelta(seconds=120),
        management_timeout=timedelta(seconds=120),
    )

    try:
        cluster = Cluster(settings.cb_connection_string, options)  # type: ignore[union-attr]
        cluster.wait_until_ready(timedelta(seconds=connect_seconds))
    except AuthenticationException as exc:
        raise RuntimeError(
            "Couchbase rejected the credentials. CB_USERNAME / CB_PASSWORD must be a "
            "*database access* user (Cluster -> Settings -> Database Access), not your "
            "Capella login."
        ) from exc
    except CouchbaseException as exc:
        raise RuntimeError(
            f"Could not reach Couchbase within {connect_seconds}s. Usually one of:\n"
            f"  - this machine's IP is not on the allow list "
            f"(Cluster -> Settings -> Networking -> Allowed IP Addresses){_public_ip_hint()}\n"
            f"  - the cluster is paused (free-tier clusters pause when idle)\n"
            f"  - CB_CONNECTION_STRING is wrong (Cluster -> Connect -> Public Connection String)"
        ) from exc
    return cluster


def _public_ip_hint() -> str:
    try:
        from urllib.request import urlopen

        with urlopen("https://api.ipify.org", timeout=3) as response:  # noqa: S310
            return f"; your public IP is {response.read().decode().strip()}"
    except Exception:  # noqa: BLE001 - hint only
        return ""


def ensure_collection(cluster, bucket_name: str, scope_name: str, collection_name: str):
    """Create the scope and collection if they are not already there.

    Returns the ``Collection``. Buckets are *not* created -- on Capella you make
    those in the UI (or with the Control Plane API), and the free tier gives you
    one.
    """
    from couchbase.exceptions import (
        BucketNotFoundException,
        CollectionAlreadyExistsException,
        ScopeAlreadyExistsException,
    )

    try:
        bucket = cluster.bucket(bucket_name)
    except BucketNotFoundException as exc:  # pragma: no cover - user setup issue
        raise RuntimeError(
            f"Bucket {bucket_name!r} does not exist. Create it in the Capella UI "
            f"(Data Tools -> Buckets) and set CB_BUCKET to its name."
        ) from exc

    manager = bucket.collections()
    try:
        manager.create_scope(scope_name)
    except ScopeAlreadyExistsException:
        pass
    try:
        manager.create_collection(scope_name, collection_name)
    except CollectionAlreadyExistsException:
        pass
    else:
        # A freshly created collection is not immediately routable.
        time.sleep(3)

    return bucket.scope(scope_name).collection(collection_name)


def upsert_docs(
    collection,
    docs: dict[str, dict[str, Any]],
    *,
    batch_size: int = 200,
    progress: bool = True,
) -> int:
    """Bulk-upsert ``{doc_id: document}``, returning the number written."""
    from couchbase.exceptions import CouchbaseException

    ids = list(docs)
    written = 0
    for start in range(0, len(ids), batch_size):
        batch = {doc_id: docs[doc_id] for doc_id in ids[start : start + batch_size]}
        try:
            result = collection.upsert_multi(batch)
        except CouchbaseException as exc:  # pragma: no cover - surfaced to the user
            raise RuntimeError(f"Upsert failed near document {start}: {exc}") from exc
        failures = getattr(result, "exceptions", None) or {}
        if failures:
            first_id, first_exc = next(iter(failures.items()))
            raise RuntimeError(f"{len(failures)} upserts failed, e.g. {first_id}: {first_exc}")
        written += len(batch)
        if progress:
            print(f"\r  upserted {written}/{len(ids)}", end="", flush=True)
    if progress:
        print()
    return written


def vector_index_definition(
    *,
    index_name: str,
    bucket_name: str,
    scope_name: str,
    collection_name: str,
    vector_field: str,
    dims: int,
    text_fields: Sequence[str] = (),
    keyword_fields: Sequence[str] = (),
    numeric_fields: Sequence[str] = (),
    datetime_fields: Sequence[str] = (),
    similarity: str = "dot_product",
) -> dict[str, Any]:
    """Build a scope-level Search index definition with one vector field.

    Four kinds of field, because the Search service treats them differently:

    * ``text_fields`` are analysed for full-text matching -- split, lowercased
      and stemmed, so a query word can match part of a value.
    * ``keyword_fields`` are indexed verbatim as a single term, which is what
      you want for filtering on a category path or an identifier.
    * ``numeric_fields`` accept ``NumericRangeQuery`` -- prices, counts, years.
    * ``datetime_fields`` accept ``DateRangeQuery``.

    Declaring the field is not optional. A range query against a field that is
    not in the mapping matches **nothing and raises nothing**, which looks like
    an empty result set rather than a mistake. :func:`indexed_fields` reads back
    what an index actually covers, for when a filter mysteriously returns zero
    rows.
    """
    properties: dict[str, Any] = {
        vector_field: {
            "enabled": True,
            "dynamic": False,
            "fields": [
                {
                    "name": vector_field,
                    "type": "vector",
                    "index": True,
                    "dims": dims,
                    "similarity": similarity,
                    "vector_index_optimized_for": "recall",
                }
            ],
        }
    }
    for field in text_fields:
        properties[field] = {
            "enabled": True,
            "dynamic": False,
            "fields": [
                {"name": field, "type": "text", "analyzer": "en", "index": True, "store": True,
                 "include_in_all": True, "include_term_vectors": True}
            ],
        }
    for field in keyword_fields:
        properties[field] = {
            "enabled": True,
            "dynamic": False,
            "fields": [
                {"name": field, "type": "text", "analyzer": "keyword", "index": True,
                 "store": True, "docvalues": True, "include_in_all": False}
            ],
        }
    for field, kind in [*((f, "number") for f in numeric_fields),
                        *((f, "datetime") for f in datetime_fields)]:
        properties[field] = {
            "enabled": True,
            "dynamic": False,
            "fields": [
                {"name": field, "type": kind, "index": True, "store": True,
                 "docvalues": True, "include_in_all": False}
            ],
        }

    return {
        "type": "fulltext-index",
        "name": index_name,
        "sourceType": "gocbcore",
        "sourceName": bucket_name,
        "planParams": {"maxPartitionsPerPIndex": 1024, "indexPartitions": 1},
        "params": {
            "doc_config": {
                "docid_prefix_delim": "",
                "docid_regexp": "",
                "mode": "scope.collection.type_field",
                "type_field": "type",
            },
            "mapping": {
                "analysis": {},
                "default_analyzer": "standard",
                "default_datetime_parser": "dateTimeOptional",
                "default_field": "_all",
                "default_mapping": {"dynamic": False, "enabled": False},
                "default_type": "_default",
                "docvalues_dynamic": False,
                "index_dynamic": False,
                "store_dynamic": False,
                "type_field": "_type",
                "types": {
                    f"{scope_name}.{collection_name}": {
                        "dynamic": False,
                        "enabled": True,
                        "properties": properties,
                    }
                },
            },
            "store": {"indexType": "scorch", "segmentVersion": 16},
        },
        "sourceParams": {},
    }


#: When each index definition was last pushed, by index name. A rebuild starts
#: a moment after the update is accepted; until then the old index still
#: answers, and readiness checks would pass too early.
_UPDATED_AT: dict[str, float] = {}

#: Field settings the Search service omits from a stored definition when they
#: hold their default value. Filled back in before comparing definitions.
_FIELD_DEFAULTS = {
    "include_in_all": False,
    "include_term_vectors": False,
    "docvalues": False,
    "store": False,
}


def _normalize_types(types: dict[str, Any] | None) -> dict[str, Any]:
    """A type mapping with omitted defaults restored, so equal means equal."""
    import copy

    normalized = copy.deepcopy(types or {})
    for mapping in normalized.values():
        for prop in (mapping.get("properties") or {}).values():
            for fld in prop.get("fields") or []:
                for key, default in _FIELD_DEFAULTS.items():
                    fld.setdefault(key, default)
    return normalized


def ensure_vector_index(
    cluster,
    *,
    bucket_name: str,
    scope_name: str,
    collection_name: str,
    index_name: str,
    vector_field: str,
    dims: int,
    text_fields: Sequence[str] = (),
    keyword_fields: Sequence[str] = (),
    numeric_fields: Sequence[str] = (),
    datetime_fields: Sequence[str] = (),
    similarity: str = "dot_product",
    recreate: bool = False,
):
    """Create or update the scope-level Search index. Idempotent.

    Returns the scope-level ``SearchIndexManager`` so you can poll it.
    """
    from couchbase.management.search import SearchIndex

    scope = cluster.bucket(bucket_name).scope(scope_name)
    manager = scope.search_indexes()

    definition = vector_index_definition(
        index_name=index_name,
        bucket_name=bucket_name,
        scope_name=scope_name,
        collection_name=collection_name,
        vector_field=vector_field,
        dims=dims,
        text_fields=text_fields,
        keyword_fields=keyword_fields,
        numeric_fields=numeric_fields,
        datetime_fields=datetime_fields,
        similarity=similarity,
    )

    from couchbase.exceptions import SearchIndexNotFoundException

    if recreate:
        try:
            manager.drop_index(index_name)
        except SearchIndexNotFoundException:
            pass

    try:
        existing = manager.get_index(index_name)
    except SearchIndexNotFoundException:
        existing = None

    if existing is not None:
        wanted = _normalize_types(definition["params"]["mapping"]["types"])
        current = _normalize_types((existing.params or {}).get("mapping", {}).get("types"))
        if current == wanted:
            # Unchanged. Re-upserting would rebuild the whole index for nothing,
            # and queries fail with "pindex not available" while it does.
            return manager

    manager.upsert_index(
        SearchIndex(
            name=index_name,
            # The server only accepts an update to an existing index when the
            # request carries that index's current UUID.
            uuid=existing.uuid if existing is not None else None,
            source_name=bucket_name,
            source_type="gocbcore",
            idx_type="fulltext-index",
            params=definition["params"],
            plan_params=definition["planParams"],
        )
    )
    _UPDATED_AT[index_name] = time.time()
    return manager


def wait_for_index(
    cluster,
    *,
    bucket_name: str,
    scope_name: str,
    index_name: str,
    expected: int,
    timeout: int = 300,
    poll: int = 3,
    stable_checks: int = 2,
    grace_after_update: int = 10,
) -> int:
    """Block until the index answers queries over all ``expected`` documents.

    Search indexing is asynchronous. Without this, the first query in a
    freshly-run notebook quietly returns nothing -- or, while an index is being
    rebuilt, fails with "pindex not available".

    Readiness is judged by running a match-all query, not by the indexed
    document count: the count stays at its old value during a rebuild, while
    the query fails until every partition is serving. It must succeed
    ``stable_checks`` times in a row, and -- if :func:`ensure_vector_index`
    just changed the definition -- not before ``grace_after_update`` seconds
    have passed, so a rebuild that has not started yet isn't mistaken for a
    finished one.
    """
    import couchbase.search as search
    from couchbase.exceptions import CouchbaseException
    from couchbase.options import SearchOptions

    scope = cluster.bucket(bucket_name).scope(scope_name)
    request = search.SearchRequest.create(search.MatchAllQuery())
    deadline = time.time() + timeout
    count, streak, status = 0, 0, "waiting"
    while time.time() < deadline:
        try:
            result = scope.search(index_name, request, SearchOptions(limit=1))
            list(result.rows())
            metrics = result.metadata().metrics()
            count = metrics.total_rows()
            ready = metrics.error_partition_count() == 0 and count >= expected
            status = "ready" if ready else "indexing"
        except CouchbaseException:
            ready, status = False, "not serving yet"
        settling = time.time() - _UPDATED_AT.get(index_name, 0) < grace_after_update
        if ready and settling:
            ready, status = False, "definition just changed"
        streak = streak + 1 if ready else 0
        print(f"\r  indexed {count}/{expected} ({status})   ", end="", flush=True)
        if streak >= stable_checks:
            print()
            return count
        time.sleep(poll)
    print()
    raise TimeoutError(
        f"Index {index_name!r} was not fully queryable after {timeout}s "
        f"({count}/{expected} documents, last status: {status}). "
        f"Check the index in the Capella UI (Data Tools -> Search)."
    )


def indexed_fields(cluster, *, bucket_name: str, scope_name: str, index_name: str) -> dict[str, str]:
    """What a live Search index actually covers, as ``{field: type}``.

    For the failure that produces no error: a ``TermQuery``, ``NumericRangeQuery``
    or ``DateRangeQuery`` against a field the index does not contain matches
    nothing and reports nothing, so an empty result looks like "no such
    documents" rather than "no such field". When a filter returns zero rows,
    check here first -- a missing name, or a field indexed as ``text`` when the
    query wants ``number``, explains most of it.

        >>> indexed_fields(cluster, bucket_name=b, scope_name=s, index_name=i)
        {'embedding': 'vector', 'text': 'text', 'department': 'text', 'year': 'number'}
    """
    scope = cluster.bucket(bucket_name).scope(scope_name)
    existing = scope.search_indexes().get_index(index_name)
    types = (existing.params or {}).get("mapping", {}).get("types", {})
    found: dict[str, str] = {}
    for mapping in types.values():
        for name, prop in (mapping.get("properties") or {}).items():
            for field in prop.get("fields") or []:
                kind = field.get("type", "unknown")
                # A keyword field is type "text" with the keyword analyzer; reporting
                # only "text" hides the difference that decides whether TermQuery works.
                analyzer = field.get("analyzer")
                if kind == "text" and analyzer:
                    kind = f"text ({analyzer})"
                found[field.get("name", name)] = kind
    return found


@dataclass
class Hit:
    """One vector-search result."""

    id: str
    score: float
    fields: dict[str, Any]

    def __getitem__(self, key: str) -> Any:
        return self.fields[key]


def vector_search(
    cluster,
    *,
    bucket_name: str,
    scope_name: str,
    index_name: str,
    vector_field: str,
    query_vector: np.ndarray | Sequence[float],
    k: int = 5,
    fields: Sequence[str] = ("*",),
    num_candidates: int | None = None,
    prefilter: Any = None,
) -> list[Hit]:
    """Nearest neighbours from a Couchbase Search vector index."""
    import couchbase.search as search
    from couchbase.options import SearchOptions
    from couchbase.vector_search import VectorQuery, VectorSearch

    vector = np.asarray(query_vector, dtype=np.float32).ravel().tolist()
    kwargs: dict[str, Any] = {"num_candidates": num_candidates or max(k, 10)}
    if prefilter is not None:
        kwargs["prefilter"] = prefilter

    vector_query = VectorQuery.create(vector_field, vector, **kwargs)
    request = search.SearchRequest.create(VectorSearch.from_vector_query(vector_query))

    scope = cluster.bucket(bucket_name).scope(scope_name)
    result = scope.search(index_name, request, SearchOptions(limit=k, fields=list(fields)))
    return [Hit(id=row.id, score=row.score, fields=row.fields or {}) for row in result.rows()]


def text_search(
    cluster,
    *,
    bucket_name: str,
    scope_name: str,
    index_name: str,
    text_query: Any,
    k: int = 5,
    fields: Sequence[str] = ("*",),
) -> list[Hit]:
    """Plain full-text search: the lexical half on its own.

    Scored by BM25 over the analysed fields, which is the baseline any vector
    retrieval has to beat to be worth its cost.
    """
    import couchbase.search as search
    from couchbase.options import SearchOptions

    request = search.SearchRequest.create(text_query)
    scope = cluster.bucket(bucket_name).scope(scope_name)
    result = scope.search(index_name, request, SearchOptions(limit=k, fields=list(fields)))
    return [Hit(id=row.id, score=row.score, fields=row.fields or {}) for row in result.rows()]


def hybrid_search(
    cluster,
    *,
    bucket_name: str,
    scope_name: str,
    index_name: str,
    vector_field: str,
    query_vector: np.ndarray | Sequence[float],
    text_query: Any,
    k: int = 5,
    fields: Sequence[str] = ("*",),
    num_candidates: int | None = None,
    prefilter: Any = None,
) -> list[Hit]:
    """Combine a full-text query with a vector query in one Search request.

    ``prefilter`` narrows the vector half before the nearest-neighbour search,
    so the candidates it returns are drawn only from documents that match it.
    """
    import couchbase.search as search
    from couchbase.options import SearchOptions
    from couchbase.vector_search import VectorQuery, VectorSearch

    vector = np.asarray(query_vector, dtype=np.float32).ravel().tolist()
    kwargs: dict[str, Any] = {"num_candidates": num_candidates or max(k, 10)}
    if prefilter is not None:
        kwargs["prefilter"] = prefilter

    request = search.SearchRequest.create(text_query).with_vector_search(
        VectorSearch.from_vector_query(VectorQuery.create(vector_field, vector, **kwargs))
    )
    scope = cluster.bucket(bucket_name).scope(scope_name)
    result = scope.search(index_name, request, SearchOptions(limit=k, fields=list(fields)))
    return [Hit(id=row.id, score=row.score, fields=row.fields or {}) for row in result.rows()]


def get_docs(collection, ids: Sequence[str]) -> dict[str, dict[str, Any]]:
    """Fetch documents by key, skipping any that are gone.

    A Search index returns what it was told to store, which is rarely the whole
    document -- storing a field only so it can be displayed makes the index
    bigger for no search benefit. The usual shape is therefore: search for ids,
    then read the documents themselves from the data service, which is a key
    lookup and the fastest thing Couchbase does.
    """
    from couchbase.exceptions import DocumentNotFoundException

    keys = list(ids)
    if not keys:
        return {}
    try:
        # One round trip for the batch. Fetching a 50-document shortlist one key
        # at a time is ten times slower, and it is the kind of slow that looks
        # like the model's fault.
        result = collection.get_multi(keys)
        return {
            key: value.content_as[dict]
            for key, value in result.results.items()
            if getattr(value, "success", True)
        }
    except (AttributeError, NotImplementedError):  # pragma: no cover - older SDKs
        found: dict[str, dict[str, Any]] = {}
        for doc_id in keys:
            try:
                found[doc_id] = collection.get(doc_id).content_as[dict]
            except DocumentNotFoundException:
                continue
        return found


def drop_demo_data(cluster, bucket_name: str, scope_name: str) -> None:
    """Remove everything a notebook created. Handy at the end of a demo."""
    from couchbase.exceptions import ScopeNotFoundException

    try:
        cluster.bucket(bucket_name).collections().drop_scope(scope_name)
    except ScopeNotFoundException:
        pass
