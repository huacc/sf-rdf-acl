# 函数级覆盖摘要

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\connection\__init__.py

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\connection\client.py
  - 覆盖函数:
    - RDFClient.select
    - RDFClient.construct
    - RDFClient.update
    - RDFClient.health
    - FusekiClient.__init__
    - FusekiClient.select
    - FusekiClient.construct
    - FusekiClient.update
    - FusekiClient.health
    - FusekiClient._execute
    - FusekiClient._resolve_timeout
    - FusekiClient._should_retry
    - FusekiClient._sleep
    - FusekiClient._raise_http_error
    - FusekiClient._ensure_circuit_allows
    - FusekiClient._record_failure
    - FusekiClient._record_success
    - FusekiClient._should_count_failure_status
    - FusekiClient._response_reason
    - FusekiClient._exception_reason
    - FusekiClient._operation_from_path
    - FusekiClient._now

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\converter\graph_formatter.py
  - 覆盖函数:
    - GraphFormatter.__init__
    - GraphFormatter.to_turtle
    - GraphFormatter.format_graph
    - GraphFormatter._to_jsonld
    - GraphFormatter._to_simplified_json
    - GraphFormatter._to_simplified_json.ensure_node

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\graph\__init__.py

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\graph\named_graph.py
  - 覆盖函数:
    - NamedGraphManager.__init__
    - NamedGraphManager.create
    - NamedGraphManager.clear
    - NamedGraphManager.conditional_clear
    - NamedGraphManager.merge
    - NamedGraphManager.snapshot
    - NamedGraphManager.conditional_clear
    - NamedGraphManager._condition_from_filters
    - NamedGraphManager._condition_from_filters._wrap_subject
    - NamedGraphManager._condition_from_filters._wrap_pred
    - NamedGraphManager._condition_from_filters._wrap_object
    - NamedGraphManager._build_conditional_delete
    - NamedGraphManager._estimate_conditional_delete
    - NamedGraphManager._count_matching
    - NamedGraphManager._compose_delete_query
    - NamedGraphManager._build_triple_pattern
    - NamedGraphManager._format_term
    - NamedGraphManager._format_iri
    - NamedGraphManager._is_prefixed
    - NamedGraphManager._is_iri
    - NamedGraphManager._escape_literal
    - NamedGraphManager._create_client
    - NamedGraphManager._resolve_graph
    - NamedGraphManager._compose_snapshot
    - TriplePattern.to_sparql

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\graph\projection.py
  - 覆盖函数:
    - GraphProjectionBuilder.__init__
    - GraphProjectionBuilder.project
    - GraphProjectionBuilder.to_graphjson
    - GraphProjectionBuilder.to_edgelist
    - GraphProjectionBuilder._create_client
    - GraphProjectionBuilder._collect
    - GraphProjectionBuilder._merge_profile
    - GraphProjectionBuilder._resolve_graph
    - GraphProjectionBuilder._build_graphjson
    - GraphProjectionBuilder._build_graph_query
    - GraphProjectionBuilder._extract_term
    - GraphProjectionBuilder._expand_to_iri
    - GraphProjectionBuilder._format_term

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\provenance\__init__.py

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\provenance\provenance.py
  - 覆盖函数:
    - ProvenanceService.__init__
    - ProvenanceService.annotate
    - ProvenanceService._create_client
    - ProvenanceService._build_statements
    - ProvenanceService._render_insert
    - ProvenanceService._format_fragment
    - ProvenanceService._format_iri
    - ProvenanceService._format_possible_iri
    - ProvenanceService._format_object
    - ProvenanceService._format_extra_predicate
    - ProvenanceService._format_extra_literal
    - ProvenanceService._escape_literal
    - ProvenanceService._is_iri

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\query\dsl.py

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\query\pagination.py
  - 覆盖函数:
    - CursorPagination.encode_cursor
    - CursorPagination.decode_cursor
    - CursorPagination.build_cursor_filter

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\transaction\batch.py
  - 覆盖函数:
    - BatchOperator.__init__
    - BatchOperator.apply_template
    - BatchOperator._execute_batch
    - BatchOperator._retry_single

- 文件: D:\coding\OntologyGraph\projects\sf-rdf-acl\src\sf_rdf_acl\transaction\upsert.py
  - 覆盖函数:
    - UpsertPlanner.__init__
    - UpsertPlanner.plan
    - UpsertPlanner._group_triples
    - UpsertPlanner._compose_key
    - UpsertPlanner._build_replace_statement
    - UpsertPlanner._build_ignore_statement
    - UpsertPlanner._build_append_statement
    - UpsertPlanner._render_triple_block
    - UpsertPlanner._render_triple
    - UpsertPlanner._format_subject
    - UpsertPlanner._format_predicate
    - UpsertPlanner._format_object
    - UpsertPlanner._format_value_literal
    - UpsertPlanner._escape_literal
    - UpsertPlanner._is_iri
    - UpsertPlanner._format_iri
    - UpsertPlanner._parse_key

