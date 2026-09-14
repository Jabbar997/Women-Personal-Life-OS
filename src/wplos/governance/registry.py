"""What the Phase 01-05 system actually contains, declared so a machine can check it.

This file describes the code that exists. It does not redesign it, and nothing
was invented here to give a field something to hold. Where the implementation
holds a real duplication, the concepts below are named at the granularity where
ownership is honestly single, and the duplication is reported as a Phase 05G
candidate rather than papered over with a second owner nobody chose.

Every entry is read by :mod:`wplos.governance.checks`, which the architecture
suite runs and ``./scripts/check.sh`` therefore runs. The reviewer approvals
recorded here are the Phase 05 acceptance: the cited document is the one that
says the capability exists without a consumer, and every one of them is due for
re-approval or removal at the phase it names.
"""

from wplos.governance.model import (
    CapabilityStatus,
    ConceptOwner,
    CriticalConcept,
    GovernanceRegistry,
    GovernedCapability,
    GovernedOutput,
    Grounding,
    GroundingKind,
    InternalOnlyExemption,
    NoConsumerReason,
    OutputConsumer,
    ReviewerApproval,
)
from wplos.governance.phases import Phase

PHASE_05_ACCEPTANCE = "Phase 05 acceptance"

_BRIEF = ReviewerApproval(
    reviewer=PHASE_05_ACCEPTANCE,
    citation="AGENTS.md",
    approved_at=Phase.PHASE_05,
)
_GRAPH_WRITE_DOC = ReviewerApproval(
    reviewer=PHASE_05_ACCEPTANCE,
    citation="docs/runtime/graph-write.md",
    approved_at=Phase.PHASE_05,
)
_KERNEL_DOC = ReviewerApproval(
    reviewer=PHASE_05_ACCEPTANCE,
    citation="docs/runtime/integration-kernel.md",
    approved_at=Phase.PHASE_05,
)
_RUNTIME_DOC = ReviewerApproval(
    reviewer=PHASE_05_ACCEPTANCE,
    citation="docs/runtime/orchestrator-runtime.md",
    approved_at=Phase.PHASE_05,
)
_ORCHESTRATOR_ADR = ReviewerApproval(
    reviewer=PHASE_05_ACCEPTANCE,
    citation="docs/adr/ADR-010-stateless-orchestrator.md",
    approved_at=Phase.PHASE_05,
)

ENTRY_PATHS: tuple[GovernedCapability, ...] = (
    GovernedCapability(
        module="wplos.application.orchestrator",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.ENTRY_PATH,
            detail=(
                "OrchestratorRuntime.run is the top of the decision stack. Phase 01-05 "
                "has no HTTP API and no composition root, and AGENTS.md says so "
                "deliberately: the runtime is invoked by calling it."
            ),
        ),
    ),
    GovernedCapability(
        module="wplos.application.graph_write_service",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.ENTRY_PATH,
            detail=(
                "GraphWriteService.apply and apply_runtime_result are the only way a "
                "sanctioned intent becomes a durable change to the graph. Nothing sits "
                "above them yet."
            ),
        ),
    ),
    GovernedCapability(
        module="wplos.integration.kernel",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.ENTRY_PATH,
            detail=(
                "WalkingSkeleton.accept, execute and dispatch_outbox are the durable "
                "action path. No worker or API composes it, so it is entered by being "
                "called."
            ),
        ),
    ),
    GovernedCapability(
        module="wplos.integration.graph_store",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.IMPLEMENTS_PORT,
            references=(
                "wplos.application.graph_write:GraphWriteStore",
                "wplos.integration.graph_store:SQLiteGraphStore",
            ),
            detail=(
                "Dependency inversion: GraphWriteService depends on the GraphWriteStore "
                "port and must never import the adapter, so the adapter has no importer "
                "by design and is reached through the port it satisfies."
            ),
        ),
    ),
)

INTERNAL_ONLY: tuple[GovernedCapability, ...] = (
    GovernedCapability(
        module="wplos.application.reference_agents",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=InternalOnlyExemption(
            canonical_owner="wplos.application.agent_port",
            reason=(
                "Deterministic stand-ins that exercise the agent port. AGENTS.md is "
                "explicit that the reference minds are not the product, and nothing in "
                "production constructs one."
            ),
            future_consumer=(
                "the provider adapter that will sit behind "
                "wplos.application.agent_port:AgentRuntime"
            ),
            expires_after=Phase.PHASE_06,
            reviewer_approval=_BRIEF,
        ),
    ),
    GovernedCapability(
        module="wplos.events.bus",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=InternalOnlyExemption(
            canonical_owner="wplos.events.envelope",
            reason=(
                "The in-memory transport for domain events. Nothing in production "
                "publishes to it or subscribes to it: the durable path commits events "
                "to the graph outbox instead."
            ),
            future_consumer=(
                "the first projection over the graph outbox, which is where a subscriber will land"
            ),
            expires_after=Phase.PHASE_06,
            reviewer_approval=_GRAPH_WRITE_DOC,
        ),
    ),
    GovernedCapability(
        module="wplos.orchestration.contract",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=InternalOnlyExemption(
            canonical_owner="wplos.application.orchestrator",
            reason=(
                "The Orchestrator's declared contract and its intent routing table. The "
                "runtime routes through wplos.application.routing and reads neither, so "
                "the contract binds the Orchestrator through tests rather than through "
                "the code path."
            ),
            future_consumer=(
                "the runtime, once it enforces its own contract the way enforce_output "
                "enforces an agent's"
            ),
            expires_after=Phase.PHASE_06,
            reviewer_approval=_ORCHESTRATOR_ADR,
        ),
    ),
    GovernedCapability(
        module="wplos.policy.source_authority",
        status=CapabilityStatus.INTERNAL_ONLY,
        exemption=InternalOnlyExemption(
            canonical_owner="wplos.policy.decisions",
            reason=(
                "A Phase 01 policy primitive that no write path consults. "
                "GraphWriteService checks contract, owner, type and revision, and never "
                "which source outranks which."
            ),
            future_consumer=(
                "the connector merge path, where two sources first disagree about one fact"
            ),
            expires_after=Phase.PHASE_06,
            reviewer_approval=_BRIEF,
        ),
    ),
)

CONCEPT_OWNERS: tuple[ConceptOwner, ...] = (
    ConceptOwner(
        concept=CriticalConcept.PLG_ENTITY_MODEL,
        owner="wplos.personal_life_graph.entity:Entity",
        detail=(
            "The canonical record. Storage may serialize it; nothing may define a second shape of "
            "it."
        ),
    ),
    ConceptOwner(
        concept=CriticalConcept.GRAPH_MUTATION_PATH,
        owner="wplos.application.graph_write_service:GraphWriteService",
        detail="The one place a sanctioned intent becomes a durable change to the graph.",
    ),
    ConceptOwner(
        concept=CriticalConcept.DURABLE_GRAPH_STORE,
        owner="wplos.integration.graph_store:SQLiteGraphStore",
        detail=(
            "The only implementation of the GraphWriteStore port; entity versions, outbox and "
            "receipts."
        ),
    ),
    ConceptOwner(
        concept=CriticalConcept.AUTHORIZATION_AUTHORITY,
        owner="wplos.policy.execution:ExecutionPolicy",
        detail="Decides whether an action may execute, and binds consent to its material terms.",
    ),
    ConceptOwner(
        concept=CriticalConcept.GUARDIAN_AUTHORITY,
        owner="wplos.policy.guardian_authority:GuardianAuthority",
        detail="Issues and retires Guardian assessments. Nothing else may mint one.",
    ),
    ConceptOwner(
        concept=CriticalConcept.RUNTIME_ORCHESTRATION,
        owner="wplos.application.orchestrator:OrchestratorRuntime",
        detail=(
            "Routes, coordinates, enforces, composes and records one run. It holds no business "
            "domain."
        ),
    ),
    ConceptOwner(
        concept=CriticalConcept.DOMAIN_EVENT_DEFINITION,
        owner="wplos.events.types:EventType",
        detail="The domain event catalog. Every event type in her history is named here.",
    ),
    ConceptOwner(
        concept=CriticalConcept.DOMAIN_EVENT_PRODUCTION,
        owner="wplos.events.envelope:DomainEvent",
        detail=(
            "Every domain event in the system is constructed by DomainEvent.emit; nothing builds "
            "one another way."
        ),
    ),
    ConceptOwner(
        concept=CriticalConcept.INTEGRATION_EVENT_DEFINITION,
        owner="wplos.integration.specs:IntegrationEventType",
        detail="The kernel's lifecycle vocabulary, kept apart from her history on purpose.",
    ),
    ConceptOwner(
        concept=CriticalConcept.INTEGRATION_EVENT_PRODUCTION,
        owner="wplos.integration.kernel:WalkingSkeleton",
        detail=(
            "The only producer of integration lifecycle events, always inside the action's "
            "transaction."
        ),
    ),
    ConceptOwner(
        concept=CriticalConcept.RUNTIME_ACTION_EXECUTION,
        owner="wplos.application.agent_port:ActionExecutor",
        detail=(
            "The port the runtime executes an authorized action through, in-memory in this phase."
        ),
    ),
    ConceptOwner(
        concept=CriticalConcept.DURABLE_ACTION_EXECUTION,
        owner="wplos.integration.kernel:WalkingSkeleton",
        detail="The durable, outbox-backed execution path, with claims, leases and reconciliation.",
    ),
)

GOVERNED_OUTPUTS: tuple[GovernedOutput, ...] = (
    GovernedOutput(
        name="graph.entity_version",
        producer="wplos.integration.graph_store:SQLiteGraphStore.commit",
        durable=True,
        detail="An append-only row per entity revision, holding the canonical Entity document.",
    ),
    GovernedOutput(
        name="graph.request_receipt",
        producer="wplos.integration.graph_store:SQLiteGraphStore.commit",
        durable=True,
        detail="The durable answer a write request was given, under both of its identities.",
    ),
    GovernedOutput(
        name="graph.domain_event",
        producer="wplos.application.graph_write_service:GraphWriteService",
        durable=True,
        detail=(
            "The event announcing a graph mutation, committed to the graph outbox in the same "
            "transaction."
        ),
        no_consumers_by_design=NoConsumerReason(
            reason=(
                "The outbox is durable and observable and nothing subscribes. "
                "docs/runtime/graph-write.md, 'What is not here', states that there are "
                "no projections and that consumer-effect atomicity is deferred with them."
            ),
            approval=_GRAPH_WRITE_DOC,
        ),
    ),
    GovernedOutput(
        name="graph.run_record",
        producer="wplos.integration.graph_store:SQLiteGraphStore.commit",
        durable=True,
        detail="What one run did, written in the same transaction as its writes.",
        no_consumers_by_design=NoConsumerReason(
            reason=(
                "docs/runtime/graph-write.md, 'The run record', says it exists so a "
                "completed run is recognisable after a restart. GraphWriteStore.run_record "
                "has no production caller: the reader that would recognise it is not built."
            ),
            approval=_GRAPH_WRITE_DOC,
        ),
    ),
    GovernedOutput(
        name="integration.action_record",
        producer="wplos.integration.store:SQLiteIntegrationStore",
        durable=True,
        detail="The stored action, its status, its authorization and its processing claim.",
    ),
    GovernedOutput(
        name="integration.consumer_offset",
        producer="wplos.integration.store:SQLiteIntegrationStore",
        durable=True,
        detail=(
            "The last aggregate version each consumer applied, which is what tells a gap from a "
            "redelivery."
        ),
    ),
    GovernedOutput(
        name="integration.lifecycle_event",
        producer="wplos.integration.kernel:WalkingSkeleton",
        durable=True,
        detail=(
            "An ACTION_* event in the integration outbox, written with the status change it "
            "announces."
        ),
        no_consumers_by_design=NoConsumerReason(
            reason=(
                "ConsumerRegistry is the consumer port and enforces its own declarations. "
                "No production code registers a handler: the only registrations in Phase "
                "01-05 are in the walking-skeleton tests, and a test is not a consumer."
            ),
            approval=_KERNEL_DOC,
        ),
    ),
    GovernedOutput(
        name="runtime.result",
        producer="wplos.application.orchestrator:OrchestratorRuntime",
        durable=False,
        detail="What one run decided: status, plan, sanctioned writes, warnings and trace.",
    ),
    GovernedOutput(
        name="runtime.domain_event",
        producer="wplos.application.orchestrator:OrchestratorRuntime",
        durable=False,
        detail="The domain events a run emits, carried back in RuntimeResult.emitted_events.",
        no_consumers_by_design=NoConsumerReason(
            reason=(
                "docs/runtime/orchestrator-runtime.md, 'Events versus trace', names what a "
                "run emits. Nothing in production reads RuntimeResult.emitted_events, and "
                "only graph mutation events reach an outbox, so a run's own events are not "
                "durable either."
            ),
            approval=_RUNTIME_DOC,
        ),
    ),
)

OUTPUT_CONSUMERS: tuple[OutputConsumer, ...] = (
    OutputConsumer(
        output="graph.entity_version",
        consumer="wplos.application.graph_write_service:GraphWriteService",
        detail=(
            "Reads the current version before every REVISE and CLOSE, to check owner, type, status "
            "and revision."
        ),
    ),
    OutputConsumer(
        output="graph.request_receipt",
        consumer="wplos.application.graph_write_service:GraphWriteService",
        detail=(
            "Resolves both durable identities of a request before anything is validated against "
            "graph state."
        ),
    ),
    OutputConsumer(
        output="integration.action_record",
        consumer="wplos.integration.kernel:WalkingSkeleton",
        detail="Reads the stored action to claim it, decide on it, settle it and reconcile it.",
    ),
    OutputConsumer(
        output="integration.consumer_offset",
        consumer="wplos.integration.kernel:WalkingSkeleton",
        detail=(
            "Compares each consumer's last applied version with the event's, to park a "
            "gap and pass a redelivery."
        ),
    ),
    OutputConsumer(
        output="runtime.result",
        consumer="wplos.application.graph_write_service:GraphWriteService",
        detail="apply_runtime_result persists the writes the minds asked for during one run.",
    ),
)

REACHED: tuple[GovernedCapability, ...] = (
    GovernedCapability(
        module="wplos.agents.contracts",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.guardian",),
        ),
    ),
    GovernedCapability(
        module="wplos.agents.guardian",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.registry",),
        ),
    ),
    GovernedCapability(
        module="wplos.agents.life_admin",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.registry",),
        ),
    ),
    GovernedCapability(
        module="wplos.agents.navigator",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.registry",),
        ),
    ),
    GovernedCapability(
        module="wplos.agents.operator",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.registry",),
        ),
    ),
    GovernedCapability(
        module="wplos.agents.radar",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.registry",),
        ),
    ),
    GovernedCapability(
        module="wplos.agents.readiness",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.registry",),
        ),
    ),
    GovernedCapability(
        module="wplos.agents.registry",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write_service",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.agent_port",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.candidates",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.composer",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.composer",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.enforcement",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write_service",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.failure",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.graph_events",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write_service",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.graph_write",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write_service",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.idempotency",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.planning",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.failure",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.priority",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.composer",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.purpose_scopes",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.request",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.result",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.routing",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.trace",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.application.writes",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.attribution",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.core.records",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.capabilities",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.request",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.client",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.idempotency",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.confidence",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.identifiers",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.money",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.personal_life_graph.attributes",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.provenance",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.purpose",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.records",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.roles",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.sensitivity",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.core.temporal",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_write",),
        ),
    ),
    GovernedCapability(
        module="wplos.events.envelope",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.events.payloads",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_events",),
        ),
    ),
    GovernedCapability(
        module="wplos.events.types",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.integration.specs",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.integration.kernel",),
        ),
    ),
    GovernedCapability(
        module="wplos.integration.sqlite_support",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.integration.graph_store",),
        ),
    ),
    GovernedCapability(
        module="wplos.integration.store",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.integration.graph_store",),
        ),
    ),
    GovernedCapability(
        module="wplos.orchestration.conflict",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.candidates",),
        ),
    ),
    GovernedCapability(
        module="wplos.orchestration.handoffs",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.planning",),
        ),
    ),
    GovernedCapability(
        module="wplos.personal_life_graph.attributes",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.life_admin",),
        ),
    ),
    GovernedCapability(
        module="wplos.personal_life_graph.context",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.personal_life_graph.entity",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.graph_events",),
        ),
    ),
    GovernedCapability(
        module="wplos.personal_life_graph.entity_types",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.personal_life_graph.graph",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.personal_life_graph.memory",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.personal_life_graph.relationship",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.personal_life_graph.context",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.decisions",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.orchestrator",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.execution",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.execution_state",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.application.agent_port",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.guardian",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.guardian_authority",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.integration.kernel",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.notification",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.events.payloads",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.permissions",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.contracts",),
        ),
    ),
    GovernedCapability(
        module="wplos.policy.sensitivity_policy",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.personal_life_graph.context",),
        ),
    ),
    GovernedCapability(
        module="wplos.shared.errors",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.agents.registry",),
        ),
    ),
    GovernedCapability(
        module="wplos.shared.json",
        status=CapabilityStatus.REACHABLE,
        grounding=Grounding(
            kind=GroundingKind.USED_BY,
            references=("wplos.core.money",),
        ),
    ),
)

CANONICAL_REGISTRY = GovernanceRegistry(
    capabilities=ENTRY_PATHS + INTERNAL_ONLY + REACHED,
    concept_owners=CONCEPT_OWNERS,
    outputs=GOVERNED_OUTPUTS,
    output_consumers=OUTPUT_CONSUMERS,
)
