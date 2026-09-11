"""Tests for usage label helpers."""

from uuid import UUID

from app.services.usage.usage_labels import (
    build_usage_resource_label,
    format_entity_label,
    labels_for_resource_buckets,
    usage_kind_label,
    UsageNameResolver,
)


class _FakeEvaluation:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class _FakeCallImport:
    def __init__(self, id, dataset=None, original_filename=None):
        self.id = id
        self.dataset = dataset
        self.original_filename = original_filename


class _FakeCallImportRow:
    def __init__(self, id, conversation_id):
        self.id = id
        self.conversation_id = conversation_id


class _FakeTTSComparison:
    def __init__(self, id, name=None, simulation_id=None):
        self.id = id
        self.name = name
        self.simulation_id = simulation_id


class _FakeAgent:
    def __init__(self, id, name=None, agent_id=None):
        self.id = id
        self.name = name
        self.agent_id = agent_id


RESULT_ID = UUID("cccccccc-dddd-eeee-ffff-000000000001")
EVALUATOR_ID = UUID("dddddddd-eeee-ffff-0000-111111111111")
PERSONA_ID = UUID("eeeeeeee-ffff-0000-1111-222222222222")
SCENARIO_ID = UUID("ffffffff-0000-1111-2222-333333333333")


class _FakeEvaluatorResult:
    def __init__(
        self,
        id,
        result_id="325494",
        name=None,
        agent_id=None,
        persona_id=None,
        scenario_id=None,
        provider_platform=None,
        timestamp=None,
    ):
        self.id = id
        self.result_id = result_id
        self.name = name
        self.agent_id = agent_id
        self.persona_id = persona_id
        self.scenario_id = scenario_id
        self.provider_platform = provider_platform
        self.timestamp = timestamp


class _FakeEvaluator:
    def __init__(
        self,
        id,
        evaluator_id="112233",
        name=None,
        agent_id=None,
        persona_id=None,
        scenario_id=None,
        suite_id=None,
    ):
        self.id = id
        self.evaluator_id = evaluator_id
        self.name = name
        self.agent_id = agent_id
        self.persona_id = persona_id
        self.scenario_id = scenario_id
        self.suite_id = suite_id


class _FakeCallRecording:
    def __init__(
        self,
        evaluator_result_id,
        call_short_id,
        source="playground",
        provider_platform=None,
    ):
        self.evaluator_result_id = evaluator_result_id
        self.call_short_id = call_short_id
        self.source = source
        self.provider_platform = provider_platform


class _FakePersona:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class _FakeScenario:
    def __init__(self, id, name):
        self.id = id
        self.name = name


class _FakeQuery:
    def __init__(self, rows):
        self._rows = rows

    def filter(self, *args, **kwargs):
        return self

    def join(self, *args, **kwargs):
        return self

    def all(self):
        return self._rows


class _FakeDb:
    def __init__(
        self,
        evaluations=(),
        imports=(),
        rows=(),
        tts_comparisons=(),
        agents=(),
        evaluator_results=(),
        evaluators=(),
        call_recordings=(),
        personas=(),
        scenarios=(),
    ):
        self._evaluations = evaluations
        self._imports = imports
        self._rows = rows
        self._tts_comparisons = tts_comparisons
        self._agents = agents
        self._evaluator_results = evaluator_results
        self._evaluators = evaluators
        self._call_recordings = call_recordings
        self._personas = personas
        self._scenarios = scenarios

    def query(self, *entities):
        if len(entities) == 1:
            model = entities[0]
            if model.__name__ == "CallImportEvaluation":
                return _FakeQuery(self._evaluations)
            if model.__name__ == "CallImport":
                return _FakeQuery(self._imports)
            if model.__name__ == "CallImportRow":
                return _FakeQuery(self._rows)
            if model.__name__ == "TTSComparison":
                return _FakeQuery(self._tts_comparisons)
            if model.__name__ == "Agent":
                return _FakeQuery(self._agents)
            if model.__name__ == "EvaluatorResult":
                return _FakeQuery(self._evaluator_results)
            if model.__name__ == "Evaluator":
                return _FakeQuery(self._evaluators)
            if model.__name__ == "CallRecording":
                return _FakeQuery(self._call_recordings)
            if model.__name__ == "Persona":
                return _FakeQuery(self._personas)
            if model.__name__ == "Scenario":
                return _FakeQuery(self._scenarios)
            raise AssertionError(f"unexpected model {model}")
        return _FakeQuery(())


EVAL_ID = UUID("984039ab-cdef-4567-8901-234567890abc")
IMPORT_ID = UUID("3111d376-e5f6-7890-abcd-ef1234567890")
ROW_ID = UUID("fedcba98-7654-3210-fedc-ba9876543210")
COMP_ID = UUID("aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee")
AGENT_ID = UUID("bbbbbbbb-cccc-dddd-eeee-ffffffffffff")
ORG_ID = UUID("11111111-2222-3333-4444-555555555555")


def test_format_entity_label_custom_name_and_default():
    assert format_entity_label("test", EVAL_ID, "Evaluation") == "test-984039ab"
    assert format_entity_label(None, EVAL_ID, "Evaluation") == "Evaluation-984039ab"


def test_call_import_label_includes_dataset_and_tags():
    db = _FakeDb(
        imports=[
            _FakeCallImport(
                IMPORT_ID,
                dataset="QA batch",
                original_filename="4 manual recordings",
            )
        ]
    )
    # Extend fake db for tag query
    class _TagQuery:
        def join(self, *args, **kwargs):
            return self

        def filter(self, *args, **kwargs):
            return self

        def all(self):
            return [(IMPORT_ID, "support")]

    def query_router(*entities):
        if len(entities) == 1:
            model = entities[0]
            if model.__name__ == "CallImportTagAssignment":
                return _TagQuery()
            if model.__name__ == "CallImportEvaluation":
                return _FakeQuery(())
            if model.__name__ == "CallImport":
                return _FakeQuery(db._imports)
            if model.__name__ == "CallImportRow":
                return _FakeQuery(())
        return _TagQuery()

    db.query = query_router  # type: ignore[method-assign]

    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload([{"call_import_id": str(IMPORT_ID)}])
    label = resolver.call_import_name(str(IMPORT_ID))
    assert "4 manual recordings" in label
    assert "QA batch" in label
    assert "support" in label


def test_call_import_label_prefers_filename_over_dataset():
    db = _FakeDb(
        imports=[
            _FakeCallImport(
                IMPORT_ID,
                dataset="calls",
                original_filename="unauthenticated sheet.xlsx",
            )
        ]
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload([{"call_import_id": str(IMPORT_ID)}])
    assert resolver.call_import_name(str(IMPORT_ID)) == (
        "unauthenticated sheet.xlsx (calls)-3111d376"
    )


def test_build_usage_resource_label_hierarchical():
    db = _FakeDb(
        evaluations=[_FakeEvaluation(EVAL_ID, "March QA pass")],
        imports=[
            _FakeCallImport(
                IMPORT_ID,
                dataset="calls",
                original_filename="unauthenticated sheet.xlsx",
            )
        ],
        rows=[_FakeCallImportRow(ROW_ID, "ext-call-8842")],
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "evaluation_id": str(EVAL_ID),
                "call_import_id": str(IMPORT_ID),
                "call_import_row_id": str(ROW_ID),
                "resource_type": "call_import_evaluation",
                "resource_id": str(EVAL_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {
            "evaluation_id": str(EVAL_ID),
            "call_import_id": str(IMPORT_ID),
            "call_import_row_id": str(ROW_ID),
            "resource_type": "call_import_evaluation",
            "resource_id": str(EVAL_ID),
        },
        "call_import_evaluation",
        resolver,
    )
    assert label == (
        "unauthenticated sheet.xlsx (calls)-3111d376 / March QA pass-984039ab / ext-call-8842"
    )


def test_build_usage_resource_label_default_evaluation_name():
    db = _FakeDb(evaluations=[_FakeEvaluation(EVAL_ID, None)])
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "evaluation_id": str(EVAL_ID),
                "resource_type": "call_import_evaluation",
                "resource_id": str(EVAL_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {"evaluation_id": str(EVAL_ID)},
        "call_import_evaluation",
        resolver,
    )
    assert label == "Evaluation-984039ab"


def test_build_usage_resource_label_tts_comparison_with_simulation_id():
    db = _FakeDb(
        tts_comparisons=[
            _FakeTTSComparison(
                COMP_ID,
                name="elevenlabs benchmark",
                simulation_id="781879",
            )
        ]
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "resource_type": "tts_comparison",
                "resource_id": str(COMP_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {
            "resource_type": "tts_comparison",
            "resource_id": str(COMP_ID),
        },
        "tts_comparison",
        resolver,
    )
    assert label == "elevenlabs benchmark"


def test_build_usage_resource_label_agent_with_short_id():
    db = _FakeDb(
        agents=[_FakeAgent(AGENT_ID, name="Support bot", agent_id="482910")]
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "resource_type": "agent",
                "resource_id": str(AGENT_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {"resource_type": "agent", "resource_id": str(AGENT_ID)},
        "agent",
        resolver,
    )
    assert label == "Support bot"


def test_labels_for_resource_buckets_empty_context_uses_bucket_id():
    db = _FakeDb(
        agents=[_FakeAgent(AGENT_ID, name="Support bot", agent_id="482910")]
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload([{"resource_type": "agent", "resource_id": str(AGENT_ID)}])
    labels = labels_for_resource_buckets(
        [(str(AGENT_ID), "agent", [{}])],
        resolver,
    )
    assert labels[str(AGENT_ID)] == "Support bot"


def test_usage_kind_label():
    assert usage_kind_label("stt") == "STT"
    assert usage_kind_label("llm") == "LLM"
    assert usage_kind_label("tts") == "TTS"


def test_build_usage_resource_label_evaluator_result_prefers_run_over_agent_only():
    db = _FakeDb(
        agents=[_FakeAgent(AGENT_ID, name="Customer BOT Test", agent_id="567356")],
        evaluator_results=[
            _FakeEvaluatorResult(RESULT_ID, result_id="325494", agent_id=AGENT_ID)
        ],
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "resource_type": "evaluator_result",
                "resource_id": str(RESULT_ID),
                "agent_id": str(AGENT_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {
            "resource_type": "evaluator_result",
            "resource_id": str(RESULT_ID),
            "agent_id": str(AGENT_ID),
        },
        "evaluator_result",
        resolver,
    )
    assert label == "Customer BOT Test · Run #325494"


def test_build_usage_resource_label_evaluator_result_uses_call_short_id_when_linked():
    db = _FakeDb(
        agents=[_FakeAgent(AGENT_ID, name="Customer BOT Test", agent_id="567356")],
        evaluator_results=[
            _FakeEvaluatorResult(RESULT_ID, result_id="325494", agent_id=AGENT_ID)
        ],
        call_recordings=[
            _FakeCallRecording(RESULT_ID, "482931", source="playground", provider_platform="retell"),
        ],
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "resource_type": "evaluator_result",
                "resource_id": str(RESULT_ID),
                "agent_id": str(AGENT_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {
            "resource_type": "evaluator_result",
            "resource_id": str(RESULT_ID),
            "agent_id": str(AGENT_ID),
        },
        "evaluator_result",
        resolver,
    )
    assert label == "Customer BOT Test · Playground · Retell"


def test_build_usage_resource_label_evaluator_suite_includes_evaluator_short_id():
    db = _FakeDb(
        agents=[_FakeAgent(AGENT_ID, name="Customer BOT Test", agent_id="567356")],
        evaluators=[
            _FakeEvaluator(EVALUATOR_ID, evaluator_id="998877", name="QA suite", agent_id=AGENT_ID)
        ],
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "resource_type": "evaluator",
                "resource_id": str(EVALUATOR_ID),
                "agent_id": str(AGENT_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {
            "resource_type": "evaluator",
            "resource_id": str(EVALUATOR_ID),
            "agent_id": str(AGENT_ID),
        },
        "evaluator",
        resolver,
    )
    assert label == "Customer BOT Test · QA suite"


def test_build_usage_resource_label_evaluator_result_uses_friendly_name():
    db = _FakeDb(
        agents=[_FakeAgent(AGENT_ID, name="Customer BOT Test", agent_id="567356")],
        evaluator_results=[
            _FakeEvaluatorResult(
                RESULT_ID,
                result_id="325494",
                agent_id=AGENT_ID,
                name="Voice AI Call - Customer BOT Test",
            )
        ],
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "resource_type": "evaluator_result",
                "resource_id": str(RESULT_ID),
                "agent_id": str(AGENT_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {
            "resource_type": "evaluator_result",
            "resource_id": str(RESULT_ID),
            "agent_id": str(AGENT_ID),
        },
        "evaluator_result",
        resolver,
    )
    assert label == "Customer BOT Test · Voice AI Call"


def test_build_usage_resource_label_evaluator_result_uses_persona_and_scenario():
    db = _FakeDb(
        agents=[_FakeAgent(AGENT_ID, name="Customer BOT Test", agent_id="567356")],
        evaluator_results=[
            _FakeEvaluatorResult(
                RESULT_ID,
                result_id="325494",
                agent_id=AGENT_ID,
                persona_id=PERSONA_ID,
                scenario_id=SCENARIO_ID,
            )
        ],
        personas=[_FakePersona(PERSONA_ID, "Angry customer")],
        scenarios=[_FakeScenario(SCENARIO_ID, "Billing dispute")],
    )
    resolver = UsageNameResolver(db, ORG_ID)
    resolver.preload(
        [
            {
                "resource_type": "evaluator_result",
                "resource_id": str(RESULT_ID),
                "agent_id": str(AGENT_ID),
            }
        ]
    )
    label = build_usage_resource_label(
        {
            "resource_type": "evaluator_result",
            "resource_id": str(RESULT_ID),
            "agent_id": str(AGENT_ID),
        },
        "evaluator_result",
        resolver,
    )
    assert label == "Customer BOT Test · Angry customer · Billing dispute"
