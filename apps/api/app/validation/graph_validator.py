from __future__ import annotations

from dataclasses import dataclass
from uuid import uuid4

from app.contracts.graph import GraphEdge, GraphNode, GraphSnapshot, ValidationIssue
from app.domain.enums import EdgeType, NodeType, ReasonCode, ValidationState


@dataclass(frozen=True)
class GraphValidationInput:
    snapshot: GraphSnapshot
    suppressed_node_ids: frozenset[str] = frozenset()
    previous_confirmed_stable_keys: frozenset[str] = frozenset()
    max_confirmed_disappearance_ratio: float = 0.5


@dataclass(frozen=True)
class GraphValidationOutcome:
    issues: tuple[ValidationIssue, ...]
    auto_publish_allowed: bool

    @property
    def valid(self) -> bool:
        return not self.issues


class GraphLevelValidator:
    validator_name = "graph_level"

    def validate(self, validation_input: GraphValidationInput) -> GraphValidationOutcome:
        snapshot = validation_input.snapshot
        issues: list[ValidationIssue] = []
        nodes_by_id = {node.node_id: node for node in snapshot.nodes}
        issues.extend(self._duplicate_nodes(snapshot.nodes))
        issues.extend(self._duplicate_edges(snapshot.edges))
        issues.extend(self._missing_edge_nodes(snapshot.edges, nodes_by_id))
        issues.extend(self._edges_on_suppressed_nodes(snapshot.edges, validation_input.suppressed_node_ids))
        issues.extend(self._impossible_edge_types(snapshot.edges, nodes_by_id))
        issues.extend(self._one_active_parent(snapshot.edges))
        issues.extend(self._acyclic_containment(snapshot.edges))
        issues.extend(self._required_hierarchy(snapshot.nodes, snapshot.edges))
        issues.extend(self._orphan_nodes(snapshot.nodes, snapshot.edges))
        disappearance_issue = self._mass_disappearance_issue(
            snapshot.nodes,
            validation_input.previous_confirmed_stable_keys,
            validation_input.max_confirmed_disappearance_ratio,
        )
        if disappearance_issue is not None:
            issues.append(disappearance_issue)
        auto_publish_allowed = not any(issue.state == ValidationState.REJECTED for issue in issues)
        if disappearance_issue is not None:
            auto_publish_allowed = False
        return GraphValidationOutcome(issues=tuple(issues), auto_publish_allowed=auto_publish_allowed)

    def _duplicate_nodes(self, nodes: tuple[GraphNode, ...]) -> list[ValidationIssue]:
        seen: set[str] = set()
        duplicates: set[str] = set()
        for node in nodes:
            if node.stable_key in seen:
                duplicates.add(node.stable_key)
            seen.add(node.stable_key)
        return [
            _issue(
                ReasonCode.DUPLICATE_NODE,
                ValidationState.REJECTED,
                f"Duplicate node stable_key: {stable_key}",
                {"stable_key": stable_key},
            )
            for stable_key in sorted(duplicates)
        ]

    def _duplicate_edges(self, edges: tuple[GraphEdge, ...]) -> list[ValidationIssue]:
        seen: set[tuple[str, str, EdgeType]] = set()
        duplicates: set[tuple[str, str, EdgeType]] = set()
        for edge in edges:
            key = (edge.source_node_id, edge.target_node_id, edge.edge_type)
            if key in seen:
                duplicates.add(key)
            seen.add(key)
        return [
            _issue(
                ReasonCode.DUPLICATE_EDGE,
                ValidationState.REJECTED,
                "Duplicate edge",
                {"source_node_id": source, "target_node_id": target, "edge_type": edge_type.value},
            )
            for source, target, edge_type in sorted(duplicates, key=lambda item: (item[0], item[1], item[2].value))
        ]

    def _missing_edge_nodes(
        self,
        edges: tuple[GraphEdge, ...],
        nodes_by_id: dict[str, GraphNode],
    ) -> list[ValidationIssue]:
        issues = []
        for edge in edges:
            if edge.source_node_id not in nodes_by_id or edge.target_node_id not in nodes_by_id:
                issues.append(
                    _issue(
                        ReasonCode.SOURCE_TARGET_MISSING,
                        ValidationState.REJECTED,
                        "Edge source or target is missing",
                        {"edge_id": edge.edge_id},
                    )
                )
        return issues

    def _edges_on_suppressed_nodes(
        self,
        edges: tuple[GraphEdge, ...],
        suppressed_node_ids: frozenset[str],
    ) -> list[ValidationIssue]:
        return [
            _issue(
                ReasonCode.HARD_INVARIANT_VIOLATION,
                ValidationState.REJECTED,
                "Edge references suppressed node",
                {"edge_id": edge.edge_id},
            )
            for edge in edges
            if edge.source_node_id in suppressed_node_ids or edge.target_node_id in suppressed_node_ids
        ]

    def _impossible_edge_types(
        self,
        edges: tuple[GraphEdge, ...],
        nodes_by_id: dict[str, GraphNode],
    ) -> list[ValidationIssue]:
        issues = []
        for edge in edges:
            source = nodes_by_id.get(edge.source_node_id)
            target = nodes_by_id.get(edge.target_node_id)
            if source is None or target is None:
                continue
            if edge.edge_type in {EdgeType.DATA_READ, EdgeType.DATA_WRITE} and target.node_type != NodeType.DATABASE:
                issues.append(
                    _issue(
                        ReasonCode.INVALID_EDGE_DIRECTION,
                        ValidationState.REJECTED,
                        "DATA edge target must be DATABASE",
                        {"edge_id": edge.edge_id},
                    )
                )
            if edge.edge_type in {EdgeType.ASYNC_PUBLISH, EdgeType.ASYNC_SUBSCRIBE} and target.node_type != NodeType.TOPIC:
                issues.append(
                    _issue(
                        ReasonCode.INVALID_EDGE_DIRECTION,
                        ValidationState.REJECTED,
                        "ASYNC edge target must be TOPIC",
                        {"edge_id": edge.edge_id},
                    )
                )
        return issues

    def _one_active_parent(self, edges: tuple[GraphEdge, ...]) -> list[ValidationIssue]:
        parents_by_child: dict[str, set[str]] = {}
        for edge in edges:
            if edge.edge_type != EdgeType.CONTAINS:
                continue
            parents_by_child.setdefault(edge.target_node_id, set()).add(edge.source_node_id)
        return [
            _issue(
                ReasonCode.HARD_INVARIANT_VIOLATION,
                ValidationState.REJECTED,
                "Node has more than one active CONTAINS parent",
                {"node_id": child_id, "parent_ids": sorted(parent_ids)},
            )
            for child_id, parent_ids in sorted(parents_by_child.items())
            if len(parent_ids) > 1
        ]

    def _acyclic_containment(self, edges: tuple[GraphEdge, ...]) -> list[ValidationIssue]:
        children_by_parent: dict[str, list[str]] = {}
        for edge in edges:
            if edge.edge_type == EdgeType.CONTAINS:
                children_by_parent.setdefault(edge.source_node_id, []).append(edge.target_node_id)
        visiting: set[str] = set()
        visited: set[str] = set()
        cycle_nodes: set[str] = set()

        def visit(node_id: str) -> None:
            if node_id in visiting:
                cycle_nodes.add(node_id)
                return
            if node_id in visited:
                return
            visiting.add(node_id)
            for child_id in children_by_parent.get(node_id, ()):
                visit(child_id)
            visiting.remove(node_id)
            visited.add(node_id)

        for node_id in children_by_parent:
            visit(node_id)
        if not cycle_nodes:
            return []
        return [
            _issue(
                ReasonCode.CONTAINMENT_CYCLE,
                ValidationState.REJECTED,
                "Containment graph has a cycle",
                {"node_ids": sorted(cycle_nodes)},
            )
        ]

    def _required_hierarchy(
        self,
        nodes: tuple[GraphNode, ...],
        edges: tuple[GraphEdge, ...],
    ) -> list[ValidationIssue]:
        if not nodes:
            return []
        if any(node.node_type == NodeType.AUTOMATED_SYSTEM for node in nodes):
            return []
        roots = _root_node_ids(nodes, edges)
        if len(roots) == 1:
            root = next(node for node in nodes if node.node_id in roots)
            if root.node_type in {NodeType.FUNCTIONAL_SUBSYSTEM, NodeType.MODULE}:
                return []
        return [
            _issue(
                ReasonCode.HARD_INVARIANT_VIOLATION,
                ValidationState.REVIEW_REQUIRED,
                "Graph has no explicit root hierarchy node",
                {"root_node_ids": sorted(roots)},
            )
        ]

    def _orphan_nodes(
        self,
        nodes: tuple[GraphNode, ...],
        edges: tuple[GraphEdge, ...],
    ) -> list[ValidationIssue]:
        root_ids = _root_node_ids(nodes, edges)
        orphan_nodes = [
            node
            for node in nodes
            if node.node_id in root_ids
            and node.node_type
            not in {NodeType.AUTOMATED_SYSTEM, NodeType.FUNCTIONAL_SUBSYSTEM, NodeType.MODULE}
        ]
        return [
            _issue(
                ReasonCode.HARD_INVARIANT_VIOLATION,
                ValidationState.REVIEW_REQUIRED,
                "Node has no hierarchy parent",
                {"node_id": node.node_id},
            )
            for node in orphan_nodes
        ]

    def _mass_disappearance_issue(
        self,
        nodes: tuple[GraphNode, ...],
        previous_confirmed_stable_keys: frozenset[str],
        max_ratio: float,
    ) -> ValidationIssue | None:
        if not previous_confirmed_stable_keys:
            return None
        current_stable_keys = {node.stable_key for node in nodes}
        disappeared = previous_confirmed_stable_keys - current_stable_keys
        ratio = len(disappeared) / len(previous_confirmed_stable_keys)
        if ratio <= max_ratio:
            return None
        return _issue(
            ReasonCode.REVIEW_REQUIRED,
            ValidationState.REVIEW_REQUIRED,
            "Mass disappearance of previously confirmed graph objects",
            {"disappeared_count": len(disappeared), "previous_count": len(previous_confirmed_stable_keys), "ratio": ratio},
        )


def _root_node_ids(nodes: tuple[GraphNode, ...], edges: tuple[GraphEdge, ...]) -> set[str]:
    node_ids = {node.node_id for node in nodes}
    children = {edge.target_node_id for edge in edges if edge.edge_type == EdgeType.CONTAINS}
    return node_ids - children


def _issue(
    reason_code: ReasonCode,
    state: ValidationState,
    message: str,
    metadata: dict[str, object],
) -> ValidationIssue:
    return ValidationIssue(
        issue_id=str(uuid4()),
        reason_code=reason_code,
        state=state,
        message=message,
        metadata=metadata,
    )
