"""langgraph-xai: a provider-neutral explainability layer for LangGraph applications."""

from importlib.metadata import PackageNotFoundError, version

from .attribution import EvidenceAttribution, HybridAttribution, RuleBasedAttribution
from .config import XAIConfig
from .core import (
    AttributionEngine,
    AttributionResult,
    Audience,
    CanonicalEvent,
    CaptureMode,
    CapturePolicy,
    Decision,
    DecisionFactor,
    DecisionType,
    Evidence,
    EvidenceType,
    Execution,
    ExecutionContext,
    ExecutionStatus,
    Explanation,
    ExplanationContext,
    ExplanationEngine,
    FailureMode,
    HumanInteraction,
    HumanInteractionType,
    InterruptEvent,
    MemoryOperation,
    NodeExecution,
    ObservabilityProvider,
    PolicyAction,
    PolicyDecision,
    PolicyProvider,
    ProvenanceLink,
    ProvenanceStore,
    RetrievedDocument,
    SourceReference,
    StateTransition,
    ToolExecution,
    ToolStatus,
)
from .explanation import LLMExplanationEngine, StructuredExplanationEngine
from .instrumentation import InstrumentedGraph
from .observability import (
    LangfuseObservability,
    LangSmithObservability,
    NoOpObservability,
    OpenTelemetryObservability,
)
from .plugins import PluginManager, SemanticArtifact, XAIPlugin
from .policy import DefaultCapturePolicy, DefaultPolicyProvider
from .runtime import RUN_ID_METADATA_KEY, Registry, Run, XAIInstrumentationError, XAIRuntime
from .storage import InMemoryProvenanceStore, StoreFilter

try:
    __version__ = version("langgraph-xai")
except PackageNotFoundError:  # pragma: no cover - only when imported from a source tree
    __version__ = "0.0.0"

__all__ = [
    "RUN_ID_METADATA_KEY",
    "AttributionEngine",
    "AttributionResult",
    "Audience",
    "CanonicalEvent",
    "CaptureMode",
    "CapturePolicy",
    "Decision",
    "DecisionFactor",
    "DecisionType",
    "DefaultCapturePolicy",
    "DefaultPolicyProvider",
    "Evidence",
    "EvidenceAttribution",
    "EvidenceType",
    "Execution",
    "ExecutionContext",
    "ExecutionStatus",
    "Explanation",
    "ExplanationContext",
    "ExplanationEngine",
    "FailureMode",
    "HumanInteraction",
    "HumanInteractionType",
    "HybridAttribution",
    "InMemoryProvenanceStore",
    "InstrumentedGraph",
    "InterruptEvent",
    "LLMExplanationEngine",
    "LangSmithObservability",
    "LangfuseObservability",
    "MemoryOperation",
    "NoOpObservability",
    "NodeExecution",
    "ObservabilityProvider",
    "OpenTelemetryObservability",
    "PluginManager",
    "PolicyAction",
    "PolicyDecision",
    "PolicyProvider",
    "ProvenanceLink",
    "ProvenanceStore",
    "Registry",
    "RetrievedDocument",
    "RuleBasedAttribution",
    "Run",
    "SemanticArtifact",
    "SourceReference",
    "StateTransition",
    "StoreFilter",
    "StructuredExplanationEngine",
    "ToolExecution",
    "ToolStatus",
    "XAIConfig",
    "XAIInstrumentationError",
    "XAIPlugin",
    "XAIRuntime",
    "__version__",
]
