# Test Matrix

Evidence codes: **AUTO** (automated test, passing in the final validation run),
**BLOCKED** (cannot run in this environment - reason given), **DOC** (documented behavior).
Every row lists the exact automated path when one exists. The final validation
run for this review: 207 backend tests + frontend lint/tsc/build, all green.

## 1. Configuration / startup

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Compose env missing secrets | Stack cannot start | ValidationError at startup, never weakened checks | `tests/unit/test_config.py` | PASS (AUTO) |
| Short secrets rejected | Weak secrets in dev/prod | min 32 chars enforced | `tests/unit/test_config.py::test_settings_short_*` | PASS (AUTO) |
| Invalid app_env rejected | Config drift | dev/staging/prod only | `tests/unit/test_config.py` | PASS (AUTO) |

## 2. Auth

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| JSON login (documented contract) | Documented flow broken (was 422) | 200 + tokens | `test_auth_login_contract.py::test_json_login_documented_contract` | PASS (AUTO) |
| OAuth2 form login compat | Swagger flows break | 200 | `...::test_form_login_oauth2_compat` | PASS (AUTO) |
| Wrong password / unknown email | User enumeration | Uniform 401 + timing shim | `...::test_json_login_wrong_password_401_uniform` | PASS (AUTO) |
| Validation errors | 422 with detail | 422 | `...::test_json_login_validation_422` | PASS (AUTO) |
| Refresh in body; access token rejected as refresh; tampered refresh | Token misuse / URL leakage | 200 / 401 / 401 | `...::test_refresh_token_in_body` | PASS (AUTO) |
| 5 failed logins -> 429 + Retry-After; window recovery | Brute force | 429 then recovery | `...::test_login_rate_limit_after_repeated_failures`, `...::test_rate_limit_recovers_after_window` | PASS (AUTO) |
| Unauthenticated query | 401 | 401 | `test_query_endpoint.py::test_query_unauthenticated_returns_401` | PASS (AUTO) |
| AuthUser flows into agent (no ORM User) | Type confusion | AuthUser instance, no unawaited coroutines | `test_auth_user_flow.py` | PASS (AUTO) |
| Login sets HttpOnly refresh cookie | XSS-readable 7-day credential | set-cookie: HttpOnly, SameSite=lax | `test_auth_refresh_rotation.py::test_login_sets_httponly_refresh_cookie` | PASS (AUTO) |
| Refresh via cookie only (browser flow) | Cookie flow unusable | 200 + rotated tokens | `...::test_refresh_via_cookie_without_body` | PASS (AUTO) |
| Refresh rotates; replayed token rejected + audited | Token theft/replay | old token 401, audit row written | `...::test_refresh_rotates_and_old_token_is_rejected`, `...::test_replay_of_revoked_token_is_audited` | PASS (AUTO) |
| Logout revokes + clears cookie | Zombie sessions | 204, cookie cleared, replay 401 | `...::test_logout_revokes_token_and_clears_cookie`, `...::test_logout_without_tokens_is_idempotent_204` | PASS (AUTO) |
| Rate limiting: memory + Redis backends identical | Multi-worker bypass | same block/cooldown semantics both backends | `test_rate_limit.py` (parametrized over both) | PASS (AUTO) |
| Rate-limit factory falls back when Redis down | Hard dependency | in-memory fallback + warning | `test_rate_limit.py::test_factory_auto_falls_back_when_redis_unreachable` | PASS (AUTO) |

## 3. RBAC / authorization (real retrieval, real Postgres)

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Manager-only chunk is top-relevant; employee queries | Cross-role leak | 0 such chunks in dense/lexical/hybrid (SQL WHERE, not post-filter) | `test_rbac.py::test_employee_cannot_see_manager_only_chunk` | PASS (AUTO) |
| User-allowlisted doc; other user queries | Cross-user leak | Invisible across all strategies; allowlisted id sees it | `test_rbac.py::test_cross_user_no_leakage` | PASS (AUTO) |
| Request body claims role=administrator with employee JWT | Privilege escalation | Ignored server-side; admin endpoints 403 | `test_rbac.py::test_role_escalation_blocked` | PASS (AUTO) |
| Soft-deleted document | Stale data | Excluded from retrieval | `test_rbac.py::test_deleted_document_excluded` | PASS (AUTO) |
| Foreign conversation/document/memory ids | IDOR | 404 / new thread; never the owner's data | `test_conversations.py::test_conversation_idor_blocked`, `test_documents_api.py::test_get_document_authorization`, `test_memory_api.py::test_memory_isolation` | PASS (AUTO) |
| Employee on manager-only finance/salary/review/auth-module queries | Unauthorized content | Abstain (eval rows q-011/q-029/q-039/q-049) | `tests/regression/test_golden_dataset.py` + golden eval | PASS (AUTO) |

## 4. Freshness / effective dates

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Expired / future documents under default retrieval | Stale or pre-published data | Excluded in SQL for all strategies | `test_freshness.py::test_default_retrieval_excludes_expired_and_future` | PASS (AUTO) |
| Historical range must see superseded version | Temporal questions | Interval intersection includes expired doc | `...::test_range_query_includes_expired_via_intersection` | PASS (AUTO) |
| Future range covering future doc | Planning questions | Future doc included, current excluded | `...::test_range_query_includes_future_when_range_covers_it` | PASS (AUTO) |
| Boundary days (from==to==today) | Off-by-one | Inclusive boundaries | `...::test_is_currently_effective_boundaries` | PASS (AUTO) |
| SQL fragment shapes | Regression of predicate | CURRENT_DATE default; :eff_from/:eff_to range | `...::test_effective_window_sql_*` | PASS (AUTO) |

## 5. Agent orchestration

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Happy path full stack (query->plan->retrieve->generate->verify) | Core journey | Grounded answer + verified citation + failure=None | `test_agent_loop.py::test_happy_path_full_stack` | PASS (AUTO) |
| First evidence round insufficient, second sufficient | No retry loop (was terminal) | Replan with feedback; replans=1; feedback in prompt | `...::test_replan_used_when_evidence_insufficient` | PASS (AUTO) |
| Evidence never sufficient | Unbounded loops | Bounded attempts, honest abstention, budgets respected | `...::test_replan_exhaustion_abstains` | PASS (AUTO) |
| One step raises at runtime | Whole query dies (was terminal) | Step skipped; query continues | `...::test_per_step_failure_does_not_abort_query` | PASS (AUTO) |
| Every step fails, nothing retrieved | Silent empty answer | tool_failure | `...::test_all_steps_failing_yields_tool_failure` | PASS (AUTO) |
| Planner references unregistered tool | Arbitrary tool execution | Step dropped at plan sanitization | `...::test_unknown_tool_steps_dropped_plan_still_valid` | PASS (AUTO) |
| Query-classification abstains on corpus-missing queries | Hallucination | Abstain, never fabricates | `...::test_unrelated_document_abstains` | PASS (AUTO) |
| Loop detection + budgets | Infinite loops | state.is_looping + can_continue; latency < 30s gate | regression `test_agent_termination_under_30s` | PASS (AUTO) |

| Vague query ('Tell me about the policy.') | Wasted retrieval / guessed answer | Clarification question, 0 tool calls | `test_clarify_conflict_agent.py::test_vague_query_gets_a_clarification_question` | PASS (AUTO) |
| Conflicting current documents (IT $40 vs Finance $60 internet) | Silently picks one side | Conflict report citing both, verified | `...::test_conflicting_sources_are_reported_not_picked` | PASS (AUTO) |
| Unconflicted query still answers normally | Over-eager conflict reporting | Normal grounded answer | `...::test_unconflicted_query_still_answers_normally` | PASS (AUTO) |
| Ambiguity rule excludes specific code lookups | POL-2024-007 misrouted to clarify | simple_factual (golden q-015 stays 'answer') | `test_clarify_conflict.py::test_mock_classifier_ambiguity_rule` | PASS (AUTO) |

## 6. Citations

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Valid citation verified against the ANSWER claim | Self-validation bug | Claim comes from answer sentence | `test_citation_validation.py::test_valid_citation_verified_against_answer_claim` | PASS (AUTO) |
| Fabricated / out-of-range marker [5] | Trustworthy-looking fabrications | Whole answer withheld (citation_mismatch) | `...::test_out_of_range_marker_fails_whole_answer`, `test_citation_flow.py::test_fabricated_marker_withholds_answer` | PASS (AUTO) |
| Real chunk, irrelevant claim | Plausible wrong citation | Citation dropped; answer withheld | `...::test_real_chunk_but_claim_not_supported_is_dropped`, `test_citation_flow.py::test_unsupported_claim_withholds` | PASS (AUTO) |
| Multi-claim answer, one unsupported | Partial grounding passes silently | Chunk unverified; withheld | `...::test_multi_claim_partial_grounding_withholds_chunk` | PASS (AUTO) |
| Judge raises / malformed / omitted pair | Fail-open validation | Fail CLOSED (unsupported) | `...::test_judge_error_fails_closed`, `...::test_malformed_judge_output_fails_closed`, `...::test_omitted_pair_fails_closed` | PASS (AUTO) |
| Duplicate markers | Duplicate citations | Deduped by chunk_id; reported | `...::test_duplicate_marker_dedupe` | PASS (AUTO) |
| Canonical abstention (no markers) | Abstention forced to cite | Well-defined path, no citations required | `test_citation_flow.py::test_canonical_abstention_has_well_defined_path` | PASS (AUTO) |
| Factual answer with no markers at all | Uncited facts | Withheld (citation_mismatch) | `test_citation_flow.py::test_no_marker_non_abstention_withholds` | PASS (AUTO) |
| Uncited sentences | Coverage blind spot | Reported in diagnostics | `...::test_uncited_sentences_reported` | PASS (AUTO) |

## 7. Prompt injection

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Direct injection in user query | System prompt theft / override | Refused before retrieval (unsafe_content) | `test_agent_loop.py::test_query_level_injection_screen` | PASS (AUTO) |
| Injection echoed into generated answer | Data exfiltration via output | Output sanitizer withholds (unsafe_content) | `test_citation_flow.py::test_injection_echo_in_answer_blocked` | PASS (AUTO) |
| Regex pattern set sanity | Defense regressions | 10 patterns match canonical attacks | `tests/unit/test_prompt_injection.py` (pre-existing) | PASS (AUTO) |
| Evidence treated as data (generator wrapping) | Indirect injection | `<retrieved_document>` + treat-as-data rule | `test_prompt_injection.py::test_wrap_retrieved_content` + generator code | PASS (AUTO) |
| Injection attempts in eval rows (q-010/q-020/q-048) | End-to-end | refuse behavior, compliant | golden eval (behavior_compliance gate) | PASS (AUTO) |
| adv-006 indirect injection via document | Indirect injection | Covered by wrapping + sanitizer (harness row) | `docs/reviews/test_matrix.md` row + `test_prompt_injection.py` | PASS (DOC/AUTO partial) |

## 8. Documents / ingestion

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Upload md -> parse/chunk/index/versions | Ingest journey broken (was NotImplementedError) | DocumentOut; chunks indexed; version row; audit row | `test_documents_api.py::test_ingest_and_lifecycle` | PASS (AUTO) |
| Employee uploads (no ingest permission) | Unauthorized ingestion | 403 | `...::test_ingest_permission_denied_for_employee` | PASS (AUTO) |
| Unsupported extension / empty / mislabeled PDF / oversized | Malicious or DoS uploads | 400 / 400 / 400 / 413 | `...::test_ingest_rejects_bad_files` | PASS (AUTO) |
| Duplicate content | Duplicate corpus | Idempotent (same document id) | `...::test_ingest_and_lifecycle` (step 5) | PASS (AUTO) |
| Soft delete -> 404 + absent from list | Zombie documents | 404; excluded | `...::test_ingest_and_lifecycle` (steps 6-7) | PASS (AUTO) |

| Async ingest: 202 -> worker -> document in DB | Queue never consumed | done + document persisted | `test_ingest_jobs.py::test_async_ingest_queues_job_and_worker_processes_it` | PASS (AUTO) |
| Async ingest 503 when Redis down | Silent job loss | 503, never silent | `...::test_async_ingest_503_when_queue_unavailable` | PASS (AUTO) |
| Bad files rejected before queueing | Worker crashes on junk | 400 at the API, queue empty | `...::test_async_ingest_validates_before_queueing` | PASS (AUTO) |
| Job status ACL (owner/admin only) | Cross-user job snooping | owner 200, others 403, admin 200, missing 404 | `...::test_job_status_visible_to_owner_and_admin_only` | PASS (AUTO) |
| Failed job recorded, not retried forever | Poison job loops | status=failed + error | `...::test_worker_records_failed_jobs` | PASS (AUTO) |
| Queue mechanics (reliable queue, orphan sweep, TTL drop) | Crash loses/duplicates jobs | 8 unit tests | `test_jobs_queue.py` | PASS (AUTO) |

## 9. Conversations / persistence

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Two-turn query chain | No memory of thread | Same conversation_id; 4 messages; citations + trace persisted | `test_conversations.py::test_query_persists_messages` | PASS (AUTO) |
| Foreign conversation_id on /query | Writing into another user's thread | New thread for caller; owner's thread untouched | `...::test_conversation_idor_blocked` | PASS (AUTO) |
| Failed agent run | Lost history | Both turns persisted with failure metadata | `...::test_failed_query_still_persists` | PASS (AUTO) |

## 10. Memory

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Lifecycle list/patch/export/delete + audit | CRUD was stubs | Works; audit rows written | `test_memory_api.py::test_memory_lifecycle` | PASS (AUTO) |
| Cross-user isolation | Memory leakage | 404 for foreign ids; no listing leakage | `...::test_memory_isolation` | PASS (AUTO) |
| Expired memories hidden | Stale preferences | Hidden from list | `...::test_expired_and_deleted_memories_hidden` | PASS (AUTO) |
| memory_search tool scoped to caller | Cross-user via agent tool | Only caller's memories returned | `...::test_memory_search_tool_scopes_to_owner` | PASS (AUTO) |

## 11. Ops / health

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| /health/ready with DB up | Fake readiness | 200; honest subsystem states | `test_health_admin.py::test_readiness_reports_db_and_subsystems` | PASS (AUTO) |
| /admin/stats real counts | Fabricated zeros | Real aggregates | `...::test_admin_stats_real_counts` | PASS (AUTO) |
| /admin/health/detailed honest states | Fabricated connectivity | Real pool status; redis 'not wired' | `...::test_admin_detailed_health_honest` | PASS (AUTO) |
| Admin endpoints for non-admins | Privilege leak | 403 | `...::test_admin_forbidden_for_non_admin` | PASS (AUTO) |

| Per-event cost persisted; stats = DB sum | Fabricated cost reporting | event.cost_usd == API-reported; stats == sum(retrieval_events) | `test_retrieval_event_cost.py` (2 tests) | PASS (AUTO) |

## 12. Evaluation

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| Dataset rejects placeholder/unknown/duplicate ids, bad enums, missing fields | Meaningless ground truth | ValidationError | `test_eval_validation.py` (10 tests) | PASS (AUTO) |
| Committed datasets validate | Regressed datasets | All three files load | `...::test_real_datasets_validate` | PASS (AUTO) |
| Smoke eval behavior >= 0.9 | Unsafe behaviors | Gate | `tests/regression/test_golden_dataset.py` | PASS (AUTO) |
| Smoke eval pattern >= 0.6 / recall >= 0.8 / unexpected-fail <= 0.05 / unauthorized citations == 0 | Quality gates | Gates | regression suite | PASS (AUTO) |
| Placeholder answers / missing metrics fail CI | Green-but-fake CI | Gate FAILS on missing data | ci.yml quality-gate step | PASS (DOC; runs on GitHub) |
| Latency < 30s for all smoke queries | Budget violations | p95 gate | regression `test_agent_termination_under_30s` | PASS (AUTO) |

## 13. Frontend

| Scenario | Risk | Expected | Automated path | Result |
|---|---|---|---|---|
| lint / tsc / production build | Broken CI | All green | `npm run lint`, `tsc --noEmit`, `next build` | PASS (AUTO) |
| Bearer header attached; 401 -> login redirect | Every query 401 (was) | Auth-gated chat | Code review + API contract tests stand in | PASS (DOC) |
| API errors shown as errors, not assistant answers | Failure looks like success | Distinct alert | `page.tsx` error state | PASS (DOC) |
| Browser-level E2E (login -> chat -> citations) | Real user journey | - | - | BLOCKED (no browser in this environment; API-level equivalents in sections 2-6) |

## 14. Not-run / environment-blocked suites

| Suite | Status | Reason |
|---|---|---|
| Docker image builds | BLOCKED | Docker unavailable in this environment (Dockerfiles reviewed statically; CI build job covers them) |
| Real-provider LLM judging (0-4 rubric) | BLOCKED | No real API key in this environment; mock provider used and labeled everywhere |
| Real bge-m3 embeddings / real bge-reranker | BLOCKED | No model download in this environment; contract tests against documented APIs; deterministic test providers used |
| Browser E2E | BLOCKED | No browser; API-level tests stand in |
| `make up` full stack | BLOCKED | Docker unavailable; alembic+seed+ingest+query verified directly against userspace PostgreSQL 17 + pgvector 0.8 |
