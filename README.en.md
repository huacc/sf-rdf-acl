[English](README.en.md) | [中文](README.md)

SF-RDF-ACL (RDF Anti-Corruption Layer)
======================================

SF-RDF-ACL is the RDF Anti-Corruption Layer for the SemanticForge platform. It offers a consistent, observable, and extensible way to interact with RDF stores (Jena Fuseki): robust HTTP client with retries/circuit breaking, a query DSL with SPARQL builders, named graph management, transactional upsert, batch ingestion, graph projection, result conversion, and RDF* provenance writing.

Highlights
----------

- Resilient client: timeouts, exponential backoff retries, circuit breaker, trace propagation, metrics (`FusekiClient`)
- Query building: structured DSL to SELECT/CONSTRUCT, cursor-based pagination (`QueryDSL`, `SPARQLQueryBuilder`, `CursorPagination`)
- Named graph ops: create, clear, conditional delete, merge, snapshot (`NamedGraphManager`)
- Transactional upsert: s / s+p / custom keys; replace/ignore/append strategies; conflict check and rollback (`UpsertPlanner`, `TransactionManager`)
- Batch ingestion: template-based INSERT DATA, chunking and per-item retries (`BatchOperator`)
- Graph projection: GraphJSON and edge list for visualization/analytics (`GraphProjectionBuilder`)
- Result conversion: CONSTRUCT/Turtle → JSON-LD/simplified JSON; SELECT bindings normalization (`GraphFormatter`, `ResultMapper`)
- Provenance: RDF* assertions with domain metadata (`ProvenanceService`)

Directory Layout
----------------

- `src/sf_rdf_acl/` core library modules (connection, query, transaction, graph, converter, provenance, utils)
- `docs/` Sphinx docs (guides, examples, API reference)
- `tests/` unit/integration tests
- `examples/` runnable scripts
- `pyproject.toml` build and dependencies (Python ≥ 3.12)

Requirements
------------

- Python 3.12+
- Jena Fuseki 4.x (standard HTTP/SPARQL)
- Optional: PostgreSQL (if enabling `AuditLogger`)

Install & Develop
-----------------

Editable install for local development:

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -U pip
.\.venv\Scripts\pip install -e .

# If you also develop sf-common side-by-side
# .\.venv\Scripts\pip install -e ..\sf-common
```

Run tests:

```powershell
.\.venv\Scripts\pip install pytest pytest-cov pytest-asyncio
.\.venv\Scripts\python -m pytest -q
```

Quickstart (Code)
-----------------

1) Connect and query

```python
from sf_rdf_acl.connection.client import FusekiClient

client = FusekiClient(endpoint="http://127.0.0.1:3030", dataset="acl")
res = await client.select("SELECT * WHERE { ?s ?p ?o } LIMIT 10", trace_id="t-1")
print(res["vars"], len(res["bindings"]))

graph = await client.construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o } LIMIT 100")
print(graph["turtle"][:200])
```

2) DSL + pagination

```python
from sf_rdf_acl.query.dsl import QueryDSL, Filter
from sf_rdf_acl.query.builder import SPARQLQueryBuilder
from sf_rdf_acl.query.pagination import CursorPage, CursorPagination

dsl = QueryDSL(type="raw", filters=[Filter(field="rdfs:label", operator="contains", value="demo")])
sparql = SPARQLQueryBuilder().build_select(dsl)

page1 = CursorPage(cursor=None, size=100)
q1 = SPARQLQueryBuilder().build_select_with_cursor(dsl, page1, sort_key="?s")
# Build next page cursor from last item
cursor = CursorPagination.encode_cursor({"s": {"type": "uri", "value": "http://ex/e/100"}}, sort_key="?s")
page2 = CursorPage(cursor=cursor, size=100)
q2 = SPARQLQueryBuilder().build_select_with_cursor(dsl, page2, sort_key="?s")
```

3) Named graph management

```python
from sf_rdf_acl.graph.named_graph import NamedGraphManager
from sf_rdf_acl.query.dsl import GraphRef

mgr = NamedGraphManager()
await mgr.create(GraphRef(model="demo", version="v1", env="dev"), trace_id="t-create")
await mgr.clear(GraphRef(model="demo", version="v1", env="dev"), trace_id="t-clear")
snap = await mgr.snapshot(GraphRef(model="demo", version="v1", env="dev"), trace_id="t-snap")
```

4) Transactional upsert

```python
from sf_rdf_acl.transaction.manager import TransactionManager
from sf_rdf_acl.transaction.upsert import Triple, UpsertRequest
from sf_rdf_acl.query.dsl import GraphRef

mgr = TransactionManager()
req = UpsertRequest(
    graph=GraphRef(model="demo", version="v1", env="dev"),
    triples=[Triple(s="<http://ex/e/1>", p="rdfs:label", o="Demo")],
    upsert_key="s+p",
    merge_strategy="ignore",
)
summary = await mgr.upsert(req, trace_id="t-upsert", actor="alice")
print(summary)
```

5) Graph projection & conversion

```python
from sf_rdf_acl.graph.projection import GraphProjectionBuilder
from sf_rdf_acl.converter.graph_formatter import GraphFormatter
from sf_rdf_acl.query.dsl import GraphRef

payload = await GraphProjectionBuilder().project(GraphRef(model="demo", version="v1", env="dev"), profile="default")
graphjson = payload.graph

formatter = GraphFormatter()
jsonld = formatter.format_graph((await client.construct("CONSTRUCT { ?s ?p ?o } WHERE { ?s ?p ?o }"))["turtle"],
                                format_type="json-ld",
                                context={"sf": "http://semanticforge.ai/ontologies/core#"})
```

6) RDF* provenance

```python
from sf_rdf_acl.provenance.provenance import ProvenanceService
from sf_rdf_acl.transaction.upsert import Triple, Provenance
from sf_rdf_acl.query.dsl import GraphRef

svc = ProvenanceService()
triples = [
    Triple(s="<http://ex/e/1>", p="rdf:type", o="sf:Entity"),
    Triple(s="<http://ex/e/1>", p="rdfs:label", o="Demo"),
]
prov = Provenance(evidence="import", confidence=0.98, source="http://job/123")
result = await svc.annotate(GraphRef(model="demo", version="v1", env="dev"), triples, prov, trace_id="t-prov")
print(result["count"])
```

Settings
--------

Default configuration is read via `common.config.ConfigManager` (YAML/env). Typical fields:

```yaml
rdf:
  endpoint: http://127.0.0.1:3030
  dataset: acl
  timeout: { default: 30, max: 120 }
  retries: { max_attempts: 3, backoff_seconds: 0.5, backoff_multiplier: 2.0, jitter_seconds: 0.1 }
  circuit_breaker: { failureThreshold: 5, recoveryTimeout: 30, recordTimeoutOnly: false }
  auth: { username: "", password: "" }
security:
  trace_header: X-Trace-Id
graph:
  projection_profiles:
    default: { limit: 1000, includeLiterals: false, directed: true, edgePredicates: ["rdf:type"] }
```

Docs & Examples
---------------

- Guides & examples: `docs/guides/*`, `docs/examples/*`
- API reference: `docs/api/*` (Sphinx autodoc + hand-written)
- Build docs locally:

```powershell
sphinx-build -b html docs _build/html
```

Testing & Quality
-----------------

- Tests: `pytest -q`
- Conventions: Conventional Commits; PEP8/Black/Flake8/MyPy (as configured)

License & Compliance
--------------------

- License: Proprietary (see `pyproject.toml`)
- Security: never commit secrets; trace propagation supported; unified error codes in `common.exceptions`

Contributing
------------

- Issues/PRs are welcome. Please include intent, impact scope, and validation notes.
- For code/doc changes, include tests or runnable snippets where reasonable.

