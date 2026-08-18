import {
  useCallback,
  useEffect,
  useLayoutEffect,
  useMemo,
  useRef,
  useState,
  type FormEvent,
  type PointerEvent as ReactPointerEvent,
  type WheelEvent as ReactWheelEvent
} from "react";

import type {
  AuditResponse,
  GraphNodeProjectionResponse,
  GraphProjectionResponse,
  ProjectResponse
} from "../../api/client";
import {
  describeArchitectureBackendError,
  type ArchitectureBackend
} from "../../api/architectureClient";
import {
  buildConnectionRoute,
  chooseConnectionPorts,
  type BoxRect,
  type ConnectionRoute,
  type Point,
  type PortSide
} from "./connectionRouting";
import {
  addManualNodeToProjection,
  buildArchitectureView,
  createManualNodeProjection,
  nodeTypeLabel,
  removeNodeSubtreeFromProjection,
  slugify,
  type ArchitectureScope,
  type ArchitectureViewModel,
  type HierarchyLine,
  type VisualEdge,
  type VisualFunctionalSubsystem,
  type VisualModule,
  type VisualNode,
  type VisualSubmodule,
  type VisualSystem
} from "./model";
import { referenceGraphProjection } from "./referenceProjection";

type Props = {
  backend: ArchitectureBackend;
};

type ThemeName = "light" | "dark";
type LayoutMode = "hierarchy" | "horizontal";
type DataMode = "reference" | "backend" | "draft";
type OpenMenu = "scope" | "audit" | "more" | null;
type AuditPanel = "setup" | "progress";
type AddFormState = { kind: "system" } | { kind: "fp"; systemId: string } | null;

type MiniShape = {
  id: string;
  className: string;
  left: number;
  top: number;
  width: number;
  height: number;
  selected: boolean;
};

type MiniViewport = {
  left: number;
  top: number;
  width: number;
  height: number;
};

const GRAPH_WIDTH = 1160;
const GRAPH_HEIGHT = 820;
const MIN_ZOOM = 0.55;
const MAX_ZOOM = 1.4;
const TERMINAL_AUDIT_STATUSES = new Set([
  "COMPLETED",
  "COMPLETED_WITH_WARNINGS",
  "FAILED",
  "CANCELLED",
  "INTERRUPTED"
]);
const AUDIT_STEPS = [
  "Индексация репозитория",
  "Поиск компонентов и связей",
  "Построение архитектурного графа"
];

export function ArchitectureWorkspace({ backend }: Props) {
  const [theme, setTheme] = useState<ThemeName>(() => readTheme());
  const [layout, setLayout] = useState<LayoutMode>(() => readLayout());
  const [projection, setProjection] = useState<GraphProjectionResponse>(referenceGraphProjection);
  const [dataMode, setDataMode] = useState<DataMode>("reference");
  const [projects, setProjects] = useState<ProjectResponse[]>([]);
  const [selectedProjectId, setSelectedProjectId] = useState<string | null>(null);
  const [currentAudit, setCurrentAudit] = useState<AuditResponse | null>(null);
  const [runningAuditId, setRunningAuditId] = useState<string | null>(null);
  const [revisionId, setRevisionId] = useState<string | null>(null);
  const [activeScopeId, setActiveScopeId] = useState<string | null>(null);
  const [openMenu, setOpenMenu] = useState<OpenMenu>(null);
  const [auditPanel, setAuditPanel] = useState<AuditPanel>("setup");
  const [addForm, setAddForm] = useState<AddFormState>(null);
  const [pendingDeleteScopeId, setPendingDeleteScopeId] = useState<string | null>(null);
  const [selectedNodeId, setSelectedNodeId] = useState<string | null>(null);
  const [selectedEdgeId, setSelectedEdgeId] = useState<string | null>(null);
  const [zoom, setZoom] = useState(1);
  const [connectionRoutes, setConnectionRoutes] = useState<Record<string, ConnectionRoute>>({});
  const [miniShapes, setMiniShapes] = useState<MiniShape[]>([]);
  const [miniViewport, setMiniViewport] = useState<MiniViewport | null>(null);
  const [apiMessage, setApiMessage] = useState("Локальный шаблон graph projection");

  const scopePickerRef = useRef<HTMLDivElement | null>(null);
  const auditControlRef = useRef<HTMLDivElement | null>(null);
  const moreControlRef = useRef<HTMLDivElement | null>(null);
  const canvasRef = useRef<HTMLDivElement | null>(null);
  const canvasContentRef = useRef<HTMLDivElement | null>(null);
  const canvasInnerRef = useRef<HTMLDivElement | null>(null);
  const rightRailRef = useRef<HTMLElement | null>(null);
  const zoomToolbarRef = useRef<HTMLDivElement | null>(null);
  const minimapSurfaceRef = useRef<HTMLDivElement | null>(null);
  const minimapViewportRef = useRef<HTMLDivElement | null>(null);
  const zoomRef = useRef(1);
  const panStartRef = useRef<{ x: number; y: number; scrollLeft: number; scrollTop: number } | null>(
    null
  );
  const minimapDragRef = useRef<{ offsetX: number; offsetY: number } | null>(null);
  const manualCounterRef = useRef(0);

  const view = useMemo(() => buildArchitectureView(projection), [projection]);
  const activeScope = useMemo(
    () => view.scopes.find((scope) => scope.id === activeScopeId) ?? view.scopes[0] ?? null,
    [activeScopeId, view.scopes]
  );
  const activeSystem = useMemo(
    () =>
      activeScope
        ? view.systems.find((system) => system.id === activeScope.systemId) ?? view.systems[0] ?? null
        : view.systems[0] ?? null,
    [activeScope, view.systems]
  );
  const selectedProject = useMemo(
    () => projects.find((project) => project.project_id === selectedProjectId) ?? null,
    [projects, selectedProjectId]
  );
  const selectedNode = selectedNodeId ? view.nodeById.get(selectedNodeId) ?? null : null;
  const auditProgress = currentAudit ? auditProgressForStatus(currentAudit.status) : 0;
  const activeAuditStep = auditProgress >= 100 ? -1 : auditProgress < 34 ? 0 : auditProgress < 68 ? 1 : 2;
  const repositoryName = selectedProject?.repository_name ?? repositoryNameFromProjection(projection);
  const repositoryMeta = selectedProject
    ? "Репозиторий подключён"
    : dataMode === "backend"
      ? "Graph projection загружен"
      : "Нужен backend project для аудита";
  const canStartAudit = Boolean(selectedProjectId) || dataMode !== "backend";
  const canDeleteActiveScope = Boolean(activeScope && !activeScope.nodeId.startsWith("view-"));
  const deleteDescriptor = activeScope
    ? `${activeScope.kind === "system" ? "АС" : "ФП"} · ${activeScope.label}`
    : "область";
  const pendingDeleteScope = pendingDeleteScopeId
    ? view.scopes.find((scope) => scope.id === pendingDeleteScopeId) ?? null
    : null;

  useEffect(() => {
    document.documentElement.dataset.theme = theme;
    writeStorage("architecture-theme", theme);
  }, [theme]);

  useLayoutEffect(() => {
    document.body.dataset.layout = layout;
    writeStorage("architecture-layout", layout);
  }, [layout]);

  useEffect(() => {
    document.body.dataset.architectureScope = activeScope?.viewScope ?? "empty";
  }, [activeScope]);

  useEffect(() => {
    if (!activeScope || activeScope.id !== activeScopeId) {
      setActiveScopeId(activeScope?.id ?? null);
    }
  }, [activeScope, activeScopeId]);

  useEffect(() => {
    const onDocumentClick = (event: MouseEvent) => {
      const target = event.target as Node;
      if (!scopePickerRef.current?.contains(target) && openMenu === "scope") setOpenMenu(null);
      if (!auditControlRef.current?.contains(target) && openMenu === "audit") setOpenMenu(null);
      if (!moreControlRef.current?.contains(target) && openMenu === "more") {
        setOpenMenu(null);
        setPendingDeleteScopeId(null);
      }
    };
    const onKeyDown = (event: KeyboardEvent) => {
      if (event.key !== "Escape") return;
      setOpenMenu(null);
      setPendingDeleteScopeId(null);
      setSelectedNodeId(null);
      setSelectedEdgeId(null);
    };
    document.addEventListener("click", onDocumentClick);
    document.addEventListener("keydown", onKeyDown);
    return () => {
      document.removeEventListener("click", onDocumentClick);
      document.removeEventListener("keydown", onKeyDown);
    };
  }, [openMenu]);

  const updateRoutes = useCallback(() => {
    const inner = canvasInnerRef.current;
    if (!inner) return;
    const nextRoutes: Record<string, ConnectionRoute> = {};
    const nodeRectsById = new Map<string, BoxRect>();
    const portCentersByNodeAndSide = new Map<string, Point>();

    for (const element of inner.querySelectorAll<HTMLElement>("[data-node]")) {
      const nodeId = element.getAttribute("data-node");
      if (!nodeId) continue;
      nodeRectsById.set(nodeId, getBaseRect(element, inner));
      for (const port of element.querySelectorAll<HTMLElement>("[data-port]")) {
        const side = port.getAttribute("data-port");
        if (!side) continue;
        const rect = getBaseRect(port, inner);
        portCentersByNodeAndSide.set(portCenterKey(nodeId, side), {
          x: rect.x + rect.width / 2,
          y: rect.y + rect.height / 2
        });
      }
    }

    for (const edge of view.relationEdges) {
      const sourceRect = nodeRectsById.get(edge.sourceNodeId);
      const targetRect = nodeRectsById.get(edge.targetNodeId);
      if (!sourceRect || !targetRect) continue;
      const obstacles = [...nodeRectsById.entries()]
        .filter(([nodeId]) => nodeId !== edge.sourceNodeId && nodeId !== edge.targetNodeId)
        .map(([, rect]) => rect);
      const ports =
        edge.sourcePort && edge.targetPort
          ? { sourcePort: edge.sourcePort, targetPort: edge.targetPort }
          : chooseConnectionPorts(sourceRect, targetRect);
      nextRoutes[edge.id] = buildConnectionRoute({
        source: sourceRect,
        target: targetRect,
        sourcePoint: portCentersByNodeAndSide.get(portCenterKey(edge.sourceNodeId, ports.sourcePort)),
        targetPoint: portCentersByNodeAndSide.get(portCenterKey(edge.targetNodeId, ports.targetPort)),
        obstacles,
        sourcePort: ports.sourcePort,
        targetPort: ports.targetPort
      });
    }

    setConnectionRoutes(nextRoutes);
  }, [view.relationEdges]);

  const updateMinimapViewport = useCallback(() => {
    const canvas = canvasRef.current;
    const canvasContent = canvasContentRef.current;
    const surface = minimapSurfaceRef.current;
    if (!canvas || !canvasContent || !surface) return;

    const metrics = minimapMetrics(surface);
    const navigationViewport = getNavigationViewport(canvas, rightRailRef.current, zoomToolbarRef.current);
    const visibleWidth = Math.min(GRAPH_WIDTH, navigationViewport.width / zoomRef.current);
    const visibleHeight = Math.min(GRAPH_HEIGHT, navigationViewport.height / zoomRef.current);
    const maxLeft = Math.max(0, GRAPH_WIDTH - visibleWidth);
    const maxTop = Math.max(0, GRAPH_HEIGHT - visibleHeight);
    const graphLeft = clamp(
      (canvas.scrollLeft + navigationViewport.left - canvasContent.offsetLeft) / zoomRef.current,
      0,
      maxLeft
    );
    const graphTop = clamp(
      (canvas.scrollTop + navigationViewport.top - canvasContent.offsetTop) / zoomRef.current,
      0,
      maxTop
    );

    setMiniViewport({
      left: metrics.offsetX + graphLeft * metrics.scale,
      top: metrics.offsetY + graphTop * metrics.scale,
      width: Math.max(18, visibleWidth * metrics.scale),
      height: Math.max(18, visibleHeight * metrics.scale)
    });
  }, []);

  const updateMinimap = useCallback(() => {
    const inner = canvasInnerRef.current;
    const surface = minimapSurfaceRef.current;
    if (!inner || !surface) return;

    const metrics = minimapMetrics(surface);
    const shapes: MiniShape[] = [];
    for (const element of inner.querySelectorAll<HTMLElement>(".boundary, .service, .event-bus")) {
      const rect = getBaseRect(element, inner);
      if (!rect.width || !rect.height) continue;
      shapes.push({
        id:
          element.getAttribute("data-node") ??
          element.getAttribute("data-boundary") ??
          `${element.className}-${shapes.length}`,
        className: element.classList.contains("boundary") ? "minimap__boundary" : "minimap__node",
        left: metrics.offsetX + rect.x * metrics.scale,
        top: metrics.offsetY + rect.y * metrics.scale,
        width: Math.max(3, rect.width * metrics.scale),
        height: Math.max(3, rect.height * metrics.scale),
        selected: Boolean(
          selectedNodeId &&
            element.getAttribute("data-node") === selectedNodeId &&
            !element.classList.contains("boundary")
        )
      });
    }
    setMiniShapes(shapes);
    updateMinimapViewport();
  }, [selectedNodeId, updateMinimapViewport]);

  const requestCanvasMetricsUpdate = useCallback(() => {
    window.requestAnimationFrame(() => {
      updateRoutes();
      updateMinimap();
    });
  }, [updateMinimap, updateRoutes]);

  useLayoutEffect(() => {
    requestCanvasMetricsUpdate();
  }, [layout, projection, requestCanvasMetricsUpdate, selectedNodeId, zoom]);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const canvasContent = canvasContentRef.current;
    if (canvasContent) {
      // Start with the graph comfortably inside the viewport while preserving
      // scrollable workspace on every side. Hard-coded scroll offsets break on
      // wide monitors because there may be no horizontal overflow.
      canvas.scrollLeft = Math.max(0, canvasContent.offsetLeft - 160);
      canvas.scrollTop = Math.max(0, canvasContent.offsetTop - 100);
    }
    requestCanvasMetricsUpdate();
    const onResize = () => requestCanvasMetricsUpdate();
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, [requestCanvasMetricsUpdate]);

  const loadGraphForAudit = useCallback(
    async (auditId: string, currentRevisionId: string | null, signal?: AbortSignal) => {
      try {
        const graph = await backend.getAuditGraph(auditId, currentRevisionId, { signal });
        setProjection(graph);
        setDataMode("backend");
        setApiMessage(
          currentRevisionId ? "Draft revision загружен из backend" : "Graph projection загружен из backend"
        );
      } catch (error) {
        if (signal?.aborted) return;
        setApiMessage(`Graph snapshot не загружен: ${describeArchitectureBackendError(error)}`);
      }
    },
    [backend]
  );

  const loadLatestProjectGraph = useCallback(
    async (projectId: string, signal?: AbortSignal) => {
      const audits = await backend.listProjectAudits(projectId, { signal });
      const latestAudit =
        [...audits].reverse().find((audit) => TERMINAL_AUDIT_STATUSES.has(audit.status)) ??
        audits[audits.length - 1] ??
        null;
      setCurrentAudit(latestAudit);
      if (!latestAudit) {
        setApiMessage("Backend project загружен · audit history пустая");
        return;
      }
      await loadGraphForAudit(latestAudit.audit_id, revisionId, signal);
    },
    [backend, loadGraphForAudit, revisionId]
  );

  const loadBackendState = useCallback(
    async (signal?: AbortSignal) => {
      try {
        await backend.health({ signal });
        const loadedProjects = await backend.listProjects({ signal });
        setProjects(loadedProjects);
        if (!loadedProjects.length) {
          setApiMessage("Backend доступен · проектов нет");
          return;
        }
        const project = loadedProjects[loadedProjects.length - 1];
        setSelectedProjectId(project.project_id);
        await loadLatestProjectGraph(project.project_id, signal);
      } catch (error) {
        if (signal?.aborted) return;
        setApiMessage(`Backend недоступен · ${describeArchitectureBackendError(error)}`);
        setDataMode("reference");
      }
    },
    [backend, loadLatestProjectGraph]
  );

  useEffect(() => {
    const controller = new AbortController();
    void loadBackendState(controller.signal);
    return () => controller.abort();
  }, [loadBackendState]);

  useEffect(() => {
    if (!runningAuditId) return undefined;
    let cancelled = false;

    const refreshAudit = async () => {
      try {
        const audit = await backend.getAudit(runningAuditId);
        if (cancelled) return;
        setCurrentAudit(audit);
        if (TERMINAL_AUDIT_STATUSES.has(audit.status)) {
          setRunningAuditId(null);
          if (audit.status === "COMPLETED" || audit.status === "COMPLETED_WITH_WARNINGS") {
            await loadGraphForAudit(audit.audit_id, revisionId);
          } else {
            setApiMessage(auditFailureMessage(audit));
          }
        }
      } catch (error) {
        if (cancelled) return;
        setRunningAuditId(null);
        setApiMessage(`Не удалось обновить аудит: ${describeArchitectureBackendError(error)}`);
      }
    };

    void refreshAudit();
    const timer = window.setInterval(() => void refreshAudit(), 700);
    return () => {
      cancelled = true;
      window.clearInterval(timer);
    };
  }, [backend, loadGraphForAudit, revisionId, runningAuditId]);

  const connectRepository = useCallback(async (): Promise<ProjectResponse | null> => {
    const repositoryPath = window.prompt("Укажите абсолютный путь к локальному репозиторию", "");
    if (!repositoryPath?.trim()) return null;
    const projectName = activeScope?.kind === "system" ? activeScope.label : activeSystem?.label ?? "Architecture";

    try {
      setApiMessage("Проверяю репозиторий через backend");
      const project = await backend.createProject({
        name: projectName,
        repository_path: repositoryPath.trim(),
        settings: {}
      });
      setProjects((current) => [project, ...current.filter((item) => item.project_id !== project.project_id)]);
      setSelectedProjectId(project.project_id);
      setApiMessage(`Репозиторий подключён · ${project.repository_name}`);
      return project;
    } catch (error) {
      setApiMessage(`Репозиторий не подключён: ${describeArchitectureBackendError(error)}`);
      return null;
    }
  }, [activeScope, activeSystem, backend]);

  const ensureDraftRevision = useCallback(async (): Promise<string | null> => {
    if (dataMode !== "backend") return null;
    const revision = projection.revision;
    if (
      revision &&
      typeof revision === "object" &&
      "revision_id" in revision &&
      "status" in revision &&
      revision.status === "DRAFT" &&
      typeof revision.revision_id === "string"
    ) {
      setRevisionId(revision.revision_id);
      return revision.revision_id;
    }
    if (revisionId) return revisionId;
    const created = await backend.createGraphRevision(projection.graph_id, {
      title: "UI manual changes",
      created_by: "web"
    });
    setRevisionId(created.revision_id);
    return created.revision_id;
  }, [backend, dataMode, projection.graph_id, projection.revision, revisionId]);

  const addScope = useCallback(
    async (name: string, kind: "system" | "fp", parentSystemId: string | null) => {
      manualCounterRef.current += 1;
      const nodeId = `manual-${kind}-${manualCounterRef.current}-${slugify(name)}`;
      const nodeType = kind === "system" ? "AUTOMATED_SYSTEM" : "FUNCTIONAL_SUBSYSTEM";
      const node = createManualNodeProjection({ nodeId, nodeType, name });

      if (dataMode === "backend") {
        try {
          const draftRevisionId = await ensureDraftRevision();
          if (!draftRevisionId) throw new Error("Draft revision is not available");
          await backend.createGraphOverride(draftRevisionId, {
            operation: "ADD_NODE",
            payload: { node: manualNodePayload(node) },
            reason: "Created from architecture workspace",
            created_by: "web"
          });
          if (parentSystemId) {
            await backend.createGraphOverride(draftRevisionId, {
              operation: "ADD_EDGE",
              payload: {
                edge_type: "CONTAINS",
                source_node_id: parentSystemId,
                target_node_id: node.node_id
              },
              reason: "Attached from architecture workspace",
              created_by: "web"
            });
          }
          await loadGraphForAudit(projection.audit_id, draftRevisionId);
          setActiveScopeId(`scope:${node.node_id}`);
          setApiMessage("Ручное изменение сохранено в draft revision");
          return;
        } catch (error) {
          setApiMessage(`Ручное изменение не сохранено: ${describeArchitectureBackendError(error)}`);
          return;
        }
      }

      setProjection((current) => addManualNodeToProjection(current, node, parentSystemId));
      setDataMode("draft");
      setActiveScopeId(`scope:${node.node_id}`);
      setApiMessage("Локальный draft обновлён");
    },
    [backend, dataMode, ensureDraftRevision, loadGraphForAudit, projection.audit_id]
  );

  const deleteScope = useCallback(async () => {
    const scope = pendingDeleteScope;
    if (!scope) return;
    const node = view.sourceNodeById.get(scope.nodeId);

    if (dataMode === "backend" && node) {
      try {
        const draftRevisionId = await ensureDraftRevision();
        if (!draftRevisionId) throw new Error("Draft revision is not available");
        if (node.origin === "MANUAL") {
          await backend.deleteUnsavedManualNode(draftRevisionId, node.node_id);
        } else {
          await backend.createGraphOverride(draftRevisionId, {
            operation: "SUPPRESS_NODE",
            payload: suppressionPayload(node, scope),
            reason: "Removed from architecture workspace",
            created_by: "web"
          });
        }
        await loadGraphForAudit(projection.audit_id, draftRevisionId);
        setApiMessage("Удаление сохранено в draft revision");
      } catch (error) {
        setApiMessage(`Удаление не сохранено: ${describeArchitectureBackendError(error)}`);
      }
    } else {
      setProjection((current) => removeNodeSubtreeFromProjection(current, scope.nodeId));
      setDataMode("draft");
      setApiMessage("Локальный draft обновлён");
    }

    setSelectedNodeId(null);
    setSelectedEdgeId(null);
    setPendingDeleteScopeId(null);
    setOpenMenu(null);
  }, [
    backend,
    dataMode,
    ensureDraftRevision,
    loadGraphForAudit,
    pendingDeleteScope,
    projection.audit_id,
    view.sourceNodeById
  ]);

  const startAudit = useCallback(async () => {
    const project = selectedProject ?? (await connectRepository());
    if (!project) return;

    try {
      setAuditPanel("progress");
      setOpenMenu("audit");
      setApiMessage("Аудит поставлен в очередь");
      const audit = await backend.startAudit(project.project_id, idempotencyKey());
      setCurrentAudit(audit);
      setRunningAuditId(audit.audit_id);
    } catch (error) {
      setApiMessage(`Аудит не запущен: ${describeArchitectureBackendError(error)}`);
      setAuditPanel("setup");
    }
  }, [backend, connectRepository, selectedProject]);

  const setZoomLevel = useCallback(
    (nextZoom: number, clientX?: number, clientY?: number) => {
      const canvas = canvasRef.current;
      const canvasContent = canvasContentRef.current;
      if (!canvas || !canvasContent) return;
      const normalizedZoom = clamp(nextZoom, MIN_ZOOM, MAX_ZOOM);
      const rect = canvas.getBoundingClientRect();
      const originX = clientX == null ? canvas.clientWidth / 2 : clientX - rect.left;
      const originY = clientY == null ? canvas.clientHeight / 2 : clientY - rect.top;
      const contentX = (canvas.scrollLeft + originX - canvasContent.offsetLeft) / zoomRef.current;
      const contentY = (canvas.scrollTop + originY - canvasContent.offsetTop) / zoomRef.current;

      zoomRef.current = normalizedZoom;
      setZoom(normalizedZoom);
      window.requestAnimationFrame(() => {
        canvas.scrollLeft = canvasContent.offsetLeft + contentX * normalizedZoom - originX;
        canvas.scrollTop = canvasContent.offsetTop + contentY * normalizedZoom - originY;
        requestCanvasMetricsUpdate();
      });
    },
    [requestCanvasMetricsUpdate]
  );

  const selectScope = (scope: ArchitectureScope) => {
    setActiveScopeId(scope.id);
    setOpenMenu(null);
    setAddForm(null);
    setSelectedNodeId(null);
    setSelectedEdgeId(null);
  };

  const selectNode = (nodeId: string) => {
    setSelectedNodeId((current) => (current === nodeId ? null : nodeId));
    setSelectedEdgeId(null);
    if (dataMode === "backend") {
      void backend.getGraphNode(projection.graph_id, nodeId).catch(() => undefined);
    }
  };

  const selectEdge = (edgeId: string) => {
    setSelectedEdgeId((current) => (current === edgeId ? null : edgeId));
    if (dataMode === "backend") {
      void backend.getGraphEdge(projection.graph_id, edgeId).catch(() => undefined);
    }
  };

  const submitAddForm = async (event: FormEvent<HTMLFormElement>) => {
    event.preventDefault();
    const form = event.currentTarget;
    const input = form.elements.namedItem("name");
    if (!(input instanceof HTMLInputElement)) return;
    const name = input.value.trim();
    if (!name || !addForm) {
      input.focus();
      return;
    }
    const systemId = addForm.kind === "fp" ? addForm.systemId : null;
    setAddForm(null);
    await addScope(name, addForm.kind, systemId);
    input.value = "";
  };

  const onCanvasWheel = (event: ReactWheelEvent<HTMLDivElement>) => {
    event.preventDefault();

    // Mouse wheel zooms at the cursor. Panning stays on canvas drag so the
    // desktop interaction is predictable. Shift + wheel remains an explicit
    // horizontal-pan shortcut for wide diagrams.
    if (event.shiftKey && !event.ctrlKey && !event.metaKey) {
      event.currentTarget.scrollLeft += event.deltaX || event.deltaY;
      requestCanvasMetricsUpdate();
      return;
    }

    setZoomLevel(
      zoomRef.current * Math.exp(-event.deltaY * 0.0012),
      event.clientX,
      event.clientY
    );
  };

  const onCanvasPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0 && event.button !== 1) return;
    panStartRef.current = {
      x: event.clientX,
      y: event.clientY,
      scrollLeft: event.currentTarget.scrollLeft,
      scrollTop: event.currentTarget.scrollTop
    };
    event.currentTarget.classList.add("is-panning");
    event.currentTarget.setPointerCapture(event.pointerId);
  };

  const onCanvasPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    const panStart = panStartRef.current;
    if (!panStart) return;
    event.currentTarget.scrollLeft = panStart.scrollLeft - (event.clientX - panStart.x);
    event.currentTarget.scrollTop = panStart.scrollTop - (event.clientY - panStart.y);
  };

  const stopPanning = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!panStartRef.current) return;
    panStartRef.current = null;
    event.currentTarget.classList.remove("is-panning");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const onMinimapPointerDown = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (event.button !== 0) return;
    const viewportRect = minimapViewportRef.current?.getBoundingClientRect();
    const fromViewport = event.target === minimapViewportRef.current;
    minimapDragRef.current = {
      offsetX: fromViewport && viewportRect ? event.clientX - viewportRect.left : (viewportRect?.width ?? 18) / 2,
      offsetY: fromViewport && viewportRect ? event.clientY - viewportRect.top : (viewportRect?.height ?? 18) / 2
    };
    minimapViewportRef.current?.classList.add("is-dragging");
    event.currentTarget.setPointerCapture(event.pointerId);
    moveFromMinimap(event.clientX, event.clientY);
  };

  const onMinimapPointerMove = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!minimapDragRef.current) return;
    moveFromMinimap(event.clientX, event.clientY);
  };

  const stopMinimapDrag = (event: ReactPointerEvent<HTMLDivElement>) => {
    if (!minimapDragRef.current) return;
    minimapDragRef.current = null;
    minimapViewportRef.current?.classList.remove("is-dragging");
    if (event.currentTarget.hasPointerCapture(event.pointerId)) {
      event.currentTarget.releasePointerCapture(event.pointerId);
    }
  };

  const moveFromMinimap = (clientX: number, clientY: number) => {
    const canvas = canvasRef.current;
    const canvasContent = canvasContentRef.current;
    const surface = minimapSurfaceRef.current;
    const viewport = minimapViewportRef.current;
    const drag = minimapDragRef.current;
    if (!canvas || !canvasContent || !surface || !viewport || !drag) return;

    const surfaceRect = surface.getBoundingClientRect();
    const metrics = minimapMetrics(surface);
    const maxLeft = metrics.offsetX + GRAPH_WIDTH * metrics.scale - viewport.offsetWidth;
    const maxTop = metrics.offsetY + GRAPH_HEIGHT * metrics.scale - viewport.offsetHeight;
    const viewportLeft = clamp(
      clientX - surfaceRect.left - drag.offsetX,
      metrics.offsetX,
      Math.max(metrics.offsetX, maxLeft)
    );
    const viewportTop = clamp(
      clientY - surfaceRect.top - drag.offsetY,
      metrics.offsetY,
      Math.max(metrics.offsetY, maxTop)
    );
    const graphLeft = (viewportLeft - metrics.offsetX) / metrics.scale;
    const graphTop = (viewportTop - metrics.offsetY) / metrics.scale;
    const navigationViewport = getNavigationViewport(canvas, rightRailRef.current, zoomToolbarRef.current);
    canvas.scrollLeft = canvasContent.offsetLeft + graphLeft * zoomRef.current - navigationViewport.left;
    canvas.scrollTop = canvasContent.offsetTop + graphTop * zoomRef.current - navigationViewport.top;
    updateMinimapViewport();
  };

  return (
    <main className="app" aria-label="Архитектура">
      <header className="header">
        <BrandMark />
        <div className="header__title">Архитектура</div>
        <div className="header__divider">/</div>
        <div
          className={["scope-picker", openMenu === "scope" ? "is-open" : ""]
            .filter(Boolean)
            .join(" ")}
          ref={scopePickerRef}
        >
          <button
            className="scope-trigger"
            type="button"
            aria-haspopup="menu"
            aria-expanded={openMenu === "scope"}
            onClick={(event) => {
              event.stopPropagation();
              setOpenMenu(openMenu === "scope" ? null : "scope");
              setPendingDeleteScopeId(null);
            }}
          >
            <span className="scope-trigger__label">{activeScope?.displayLabel ?? "Область не выбрана"}</span>
            <ChevronIcon className="scope-trigger__chevron" />
          </button>
          <ScopeMenu
            addForm={addForm}
            scopes={view.scopes}
            systems={view.systems}
            activeScopeId={activeScope?.id ?? null}
            onSelectScope={selectScope}
            onShowAddSystem={() => setAddForm({ kind: "system" })}
            onShowAddFp={(systemId) => setAddForm({ kind: "fp", systemId })}
            onSubmitAddForm={submitAddForm}
          />
        </div>

        <div className="header__spacer" />

        <div className="header__actions">
          <div
            className={["audit-control", openMenu === "audit" ? "is-open" : "", runningAuditId ? "is-running" : ""]
              .filter(Boolean)
              .join(" ")}
            ref={auditControlRef}
          >
            <button
              className="audit-button"
              type="button"
              aria-haspopup="dialog"
              aria-expanded={openMenu === "audit"}
              onClick={(event) => {
                event.stopPropagation();
                setOpenMenu(openMenu === "audit" ? null : "audit");
                setPendingDeleteScopeId(null);
              }}
            >
              Провести аудит
              <ChevronIcon className="audit-button__chevron" />
            </button>
            <AuditMenu
              activeScope={activeScope}
              auditPanel={auditPanel}
              apiMessage={apiMessage}
              auditProgress={auditProgress}
              activeAuditStep={activeAuditStep}
              canStartAudit={canStartAudit}
              currentAudit={currentAudit}
              repositoryMeta={repositoryMeta}
              repositoryName={repositoryName}
              onChooseRepository={() => void connectRepository()}
              onCollapseProgress={() => {
                setOpenMenu(null);
                if (auditProgress >= 100) setAuditPanel("setup");
              }}
              onStartAudit={() => void startAudit()}
            />
          </div>

          <div
            className={["more-control", openMenu === "more" ? "is-open" : ""]
              .filter(Boolean)
              .join(" ")}
            ref={moreControlRef}
          >
            <button
              className="icon-button"
              type="button"
              aria-label="Настройки отображения"
              title="Настройки отображения"
              aria-haspopup="dialog"
              aria-expanded={openMenu === "more"}
              onClick={(event) => {
                event.stopPropagation();
                setOpenMenu(openMenu === "more" ? null : "more");
                if (openMenu === "more") setPendingDeleteScopeId(null);
              }}
            >
              <MoreIcon />
            </button>
            <MoreMenu
              activeScope={activeScope}
              canDeleteScope={canDeleteActiveScope}
              deleteDescriptor={deleteDescriptor}
              layout={layout}
              pendingDeleteScope={pendingDeleteScope}
              theme={theme}
              onAcceptDelete={() => void deleteScope()}
              onCancelDelete={() => setPendingDeleteScopeId(null)}
              onDelete={() => setPendingDeleteScopeId(activeScope?.id ?? null)}
              onLayoutChange={setLayout}
              onToggleTheme={() => setTheme(theme === "dark" ? "light" : "dark")}
            />
          </div>
        </div>
      </header>

      <section className="workspace">
        <div className="stage">
          <div className="scope-empty" aria-live="polite">
            <div className="scope-empty__title">Архитектура ещё не построена</div>
            <div className="scope-empty__text">Добавьте ФП или запустите аудит, чтобы наполнить выбранную область.</div>
          </div>
          <div
            className="canvas"
            ref={canvasRef}
            onPointerDown={onCanvasPointerDown}
            onPointerMove={onCanvasPointerMove}
            onPointerUp={stopPanning}
            onPointerCancel={stopPanning}
            onScroll={updateMinimapViewport}
            onWheel={onCanvasWheel}
          >
            <div
              className="canvas-content"
              ref={canvasContentRef}
              style={{ width: GRAPH_WIDTH * zoom, height: GRAPH_HEIGHT * zoom }}
            >
              <div
                className={["canvas-inner", selectedNodeId ? "has-service-selection" : ""]
                  .filter(Boolean)
                  .join(" ")}
                ref={canvasInnerRef}
                style={{ transform: `translate3d(0, 0, 0) scale(${zoom})` }}
              >
                {activeSystem ? (
                  <SystemCanvas
                    connectionRoutes={connectionRoutes}
                    selectedEdgeId={selectedEdgeId}
                    selectedNodeId={selectedNodeId}
                    system={activeSystem}
                    view={view}
                    onSelectEdge={selectEdge}
                    onSelectNode={selectNode}
                  />
                ) : null}
              </div>
            </div>
          </div>

          <div className="zoom" aria-label="Масштаб" ref={zoomToolbarRef}>
            <button type="button" aria-label="Уменьшить масштаб" onClick={() => setZoomLevel(zoomRef.current - 0.1)}>
              <MinusIcon />
            </button>
            <div className="zoom__value">{Math.round(zoom * 100)}%</div>
            <button type="button" aria-label="Увеличить масштаб" onClick={() => setZoomLevel(zoomRef.current + 0.1)}>
              <PlusIcon />
            </button>
          </div>
        </div>

        <aside className="right-rail" ref={rightRailRef}>
          <Inspector
            selectedEdgeId={selectedEdgeId}
            selectedNode={selectedNode}
            view={view}
            onSelectEdge={selectEdge}
          />
          <section className="panel minimap" aria-label="Навигация по полотну">
            <div
              className="minimap__surface"
              ref={minimapSurfaceRef}
              onPointerDown={onMinimapPointerDown}
              onPointerMove={onMinimapPointerMove}
              onPointerUp={stopMinimapDrag}
              onPointerCancel={stopMinimapDrag}
            >
              <div aria-hidden="true">
                {miniShapes.map((shape) => (
                  <span
                    className={[shape.className, shape.selected ? "is-selected" : ""]
                      .filter(Boolean)
                      .join(" ")}
                    key={shape.id}
                    style={{
                      left: shape.left,
                      top: shape.top,
                      width: shape.width,
                      height: shape.height
                    }}
                  />
                ))}
              </div>
              <div
                className="minimap__viewport"
                ref={minimapViewportRef}
                aria-hidden="true"
                style={
                  miniViewport
                    ? {
                        left: miniViewport.left,
                        top: miniViewport.top,
                        width: miniViewport.width,
                        height: miniViewport.height
                      }
                    : undefined
                }
              />
            </div>
          </section>
        </aside>
      </section>
    </main>
  );
}

function ScopeMenu({
  addForm,
  scopes,
  systems,
  activeScopeId,
  onSelectScope,
  onShowAddFp,
  onShowAddSystem,
  onSubmitAddForm
}: {
  addForm: AddFormState;
  scopes: ArchitectureScope[];
  systems: VisualSystem[];
  activeScopeId: string | null;
  onSelectScope: (scope: ArchitectureScope) => void;
  onShowAddFp: (systemId: string) => void;
  onShowAddSystem: () => void;
  onSubmitAddForm: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <div className="scope-menu" role="menu" aria-label="Выбор области архитектуры">
      <div className="scope-menu__head">Область архитектуры</div>
      {systems.map((system) => {
        const systemScope = scopes.find((scope) => scope.nodeId === system.id);
        const childScopes = scopes.filter(
          (scope) => scope.systemId === system.id && scope.kind === "functional-subsystem"
        );
        return (
          <div className="scope-system" data-system-name={system.label} key={system.id}>
            {systemScope ? (
              <ScopeOption
                active={systemScope.id === activeScopeId}
                scope={systemScope}
                type="АС"
                onSelectScope={onSelectScope}
              />
            ) : null}
            <div className="scope-children">
              {childScopes.map((scope) => (
                <ScopeOption
                  active={scope.id === activeScopeId}
                  key={scope.id}
                  scope={scope}
                  type="ФП"
                  onSelectScope={onSelectScope}
                />
              ))}
              {addForm?.kind === "fp" && addForm.systemId === system.id ? (
                <ScopeAddForm label="Название ФП" onSubmit={onSubmitAddForm} />
              ) : (
                <button className="scope-add" type="button" onClick={() => onShowAddFp(system.id)}>
                  <span className="scope-add__plus">+</span>
                  Добавить ФП
                </button>
              )}
            </div>
          </div>
        );
      })}
      <div className="scope-menu__footer">
        {addForm?.kind === "system" ? (
          <ScopeAddForm label="Название АС" onSubmit={onSubmitAddForm} />
        ) : (
          <button className="scope-add" type="button" onClick={onShowAddSystem}>
            <span className="scope-add__plus">+</span>
            Добавить АС
          </button>
        )}
      </div>
    </div>
  );
}

function ScopeOption({
  active,
  scope,
  type,
  onSelectScope
}: {
  active: boolean;
  scope: ArchitectureScope;
  type: string;
  onSelectScope: (scope: ArchitectureScope) => void;
}) {
  return (
    <button
      className={["scope-option", active ? "is-active" : ""].filter(Boolean).join(" ")}
      type="button"
      role="menuitemradio"
      aria-checked={active}
      onClick={() => onSelectScope(scope)}
    >
      <span className="scope-option__type">{type}</span>
      <span className="scope-option__name">{scope.label}</span>
      <CheckIcon className="scope-option__check" />
    </button>
  );
}

function ScopeAddForm({
  label,
  onSubmit
}: {
  label: string;
  onSubmit: (event: FormEvent<HTMLFormElement>) => void;
}) {
  return (
    <form className="scope-add-form" onSubmit={onSubmit}>
      <input name="name" type="text" maxLength={48} placeholder={label} autoComplete="off" aria-label={label} />
      <button type="submit" aria-label={label}>
        ✓
      </button>
    </form>
  );
}

function AuditMenu({
  activeAuditStep,
  activeScope,
  apiMessage,
  auditPanel,
  auditProgress,
  canStartAudit,
  currentAudit,
  repositoryMeta,
  repositoryName,
  onChooseRepository,
  onCollapseProgress,
  onStartAudit
}: {
  activeAuditStep: number;
  activeScope: ArchitectureScope | null;
  apiMessage: string;
  auditPanel: AuditPanel;
  auditProgress: number;
  canStartAudit: boolean;
  currentAudit: AuditResponse | null;
  repositoryMeta: string;
  repositoryName: string;
  onChooseRepository: () => void;
  onCollapseProgress: () => void;
  onStartAudit: () => void;
}) {
  const progressStatus =
    auditProgress >= 100 ? auditStatusLabel(currentAudit?.status) : auditStatusLabel(currentAudit?.status ?? "QUEUED");

  return (
    <div className="audit-menu" role="dialog" aria-label="Настройка аудита">
      {auditPanel === "setup" ? (
        <div>
          <div className="audit-menu__eyebrow">Аудит архитектуры</div>
          <div className="audit-menu__title">{activeScope?.displayLabel ?? "Область не выбрана"}</div>

          <div className="audit-menu__label">Репозиторий</div>
          <button className="repository-picker" type="button" onClick={onChooseRepository}>
            <FolderIcon />
            <span>
              <span className="repository-picker__name">{repositoryName}</span>
              <span className="repository-picker__meta">{repositoryMeta}</span>
            </span>
            <ChevronRightIcon className="repository-picker__arrow" />
          </button>
          <button className="audit-run" type="button" disabled={!canStartAudit} onClick={onStartAudit}>
            Запустить аудит
          </button>
          <div className="audit-progress__repository">{apiMessage}</div>
        </div>
      ) : (
        <div className="audit-progress" aria-live="polite">
          <div className="audit-progress__header">
            <div>
              <div className="audit-menu__eyebrow">{progressStatus}</div>
              <div className="audit-menu__title">{activeScope?.displayLabel ?? "Область не выбрана"}</div>
            </div>
            <div className="audit-progress__percentage">{Math.round(auditProgress)}%</div>
          </div>
          <div className="audit-progress__track" aria-hidden="true">
            <span className="audit-progress__bar" style={{ width: `${auditProgress}%` }} />
          </div>
          <div className="audit-progress__repository">{repositoryName}</div>
          <div className="audit-steps">
            {AUDIT_STEPS.map((step, index) => (
              <div
                className={[
                  "audit-step",
                  index === activeAuditStep ? "is-active" : "",
                  auditProgress >= 100 || index < activeAuditStep ? "is-done" : ""
                ]
                  .filter(Boolean)
                  .join(" ")}
                key={step}
              >
                <span className="audit-step__marker" />
                <span>{step}</span>
              </div>
            ))}
          </div>
          <button className="audit-progress__action" type="button" onClick={onCollapseProgress}>
            {auditProgress >= 100 ? "Готово" : "Свернуть"}
          </button>
        </div>
      )}
    </div>
  );
}

function MoreMenu({
  activeScope,
  canDeleteScope,
  deleteDescriptor,
  layout,
  pendingDeleteScope,
  theme,
  onAcceptDelete,
  onCancelDelete,
  onDelete,
  onLayoutChange,
  onToggleTheme
}: {
  activeScope: ArchitectureScope | null;
  canDeleteScope: boolean;
  deleteDescriptor: string;
  layout: LayoutMode;
  pendingDeleteScope: ArchitectureScope | null;
  theme: ThemeName;
  onAcceptDelete: () => void;
  onCancelDelete: () => void;
  onDelete: () => void;
  onLayoutChange: (layout: LayoutMode) => void;
  onToggleTheme: () => void;
}) {
  return (
    <div className="more-menu" role="dialog" aria-label="Настройки отображения">
      {pendingDeleteScope ? (
        <div className="delete-confirm">
          <div className="settings-title">Подтверждение</div>
          <div className="delete-confirm__title">
            Удалить {pendingDeleteScope.kind === "system" ? "АС" : "ФП"}?
          </div>
          <div className="delete-confirm__text">
            Область <span className="delete-confirm__name">{pendingDeleteScope.label}</span> и её содержимое будут
            удалены из текущей схемы.
          </div>
          <div className="delete-confirm__actions">
            <button className="delete-cancel" type="button" onClick={onCancelDelete}>
              Отмена
            </button>
            <button className="delete-accept" type="button" onClick={onAcceptDelete}>
              Удалить
            </button>
          </div>
        </div>
      ) : (
        <div>
          <div className="settings-title">Интерфейс</div>
          <div className="settings-row">
            <span>
              <span className="settings-row__label">Тема интерфейса</span>
              <span className="settings-row__meta">{theme === "dark" ? "Тёмная" : "Светлая"}</span>
            </span>
            <button
              className="theme-switch"
              type="button"
              role="switch"
              aria-checked={theme === "dark"}
              aria-label={theme === "dark" ? "Выключить тёмную тему" : "Включить тёмную тему"}
              onClick={onToggleTheme}
            />
          </div>

          <div className="settings-divider" />
          <div className="settings-title">Представление графа</div>
          <div className="layout-options" role="radiogroup" aria-label="Режим отображения архитектуры">
            <LayoutOption active={layout === "hierarchy"} layout="hierarchy" onLayoutChange={onLayoutChange} />
            <LayoutOption active={layout === "horizontal"} layout="horizontal" onLayoutChange={onLayoutChange} />
          </div>

          <div className="settings-divider" />
          <button className="settings-delete" type="button" disabled={!canDeleteScope} onClick={onDelete}>
            <TrashIcon />
            <span className="settings-delete__copy">
              <span className="settings-delete__title">Удалить {deleteDescriptor}</span>
              <span className="settings-delete__meta">
                {canDeleteScope ? "Потребуется подтверждение" : "Служебная группировка отображения"}
              </span>
            </span>
          </button>
        </div>
      )}
    </div>
  );
}

function LayoutOption({
  active,
  layout,
  onLayoutChange
}: {
  active: boolean;
  layout: LayoutMode;
  onLayoutChange: (layout: LayoutMode) => void;
}) {
  return (
    <button
      className={["layout-option", active ? "is-active" : ""].filter(Boolean).join(" ")}
      type="button"
      role="radio"
      aria-checked={active}
      onClick={() => onLayoutChange(layout)}
    >
      {layout === "hierarchy" ? <HierarchyPreviewIcon /> : <HorizontalPreviewIcon />}
      <span className="layout-option__name">{layout === "hierarchy" ? "Иерархия" : "По уровням"}</span>
    </button>
  );
}

function SystemCanvas({
  connectionRoutes,
  selectedEdgeId,
  selectedNodeId,
  system,
  view,
  onSelectEdge,
  onSelectNode
}: {
  connectionRoutes: Record<string, ConnectionRoute>;
  selectedEdgeId: string | null;
  selectedNodeId: string | null;
  system: VisualSystem;
  view: ArchitectureViewModel;
  onSelectEdge: (edgeId: string) => void;
  onSelectNode: (nodeId: string) => void;
}) {
  const relatedNodeIds = relatedNodes(view.relationEdges, selectedNodeId);
  const highlightedNodeIds = highlightedNodes(view.relationEdges, selectedNodeId, selectedEdgeId);
  const selectedPortsByNodeId = selectedConnectionPorts(
    view.relationEdges,
    connectionRoutes,
    selectedEdgeId
  );

  return (
    <>
      <section className="boundary system" data-boundary={system.id}>
        <div className="system__head">
          <div className="system__eyebrow">АС</div>
          <div className="system__title">{system.label}</div>
          <div className="system__meta">{system.meta}</div>
        </div>
        {system.subsystems.map((subsystem) => (
          <FunctionalSubsystemView
            highlightedNodeIds={highlightedNodeIds}
            key={subsystem.id}
            relatedNodeIds={relatedNodeIds}
            selectedPortsByNodeId={selectedPortsByNodeId}
            selectedNodeId={selectedNodeId}
            subsystem={subsystem}
            onSelectNode={onSelectNode}
          />
        ))}
        {system.eventNodes.map((node) => (
          <GraphNodeButton
            highlightedNodeIds={highlightedNodeIds}
            key={node.id}
            node={node}
            relatedNodeIds={relatedNodeIds}
            selectedPort={selectedPortsByNodeId.get(node.id) ?? null}
            selectedNodeId={selectedNodeId}
            onSelectNode={onSelectNode}
          />
        ))}
      </section>
      <svg className="relations" viewBox={`0 0 ${GRAPH_WIDTH} ${GRAPH_HEIGHT}`} aria-hidden="true">
        <defs>
          <marker id="arrow-green" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L8 4L0 8Z" fill="var(--green)" />
          </marker>
          <marker id="arrow-gray" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L8 4L0 8Z" fill="var(--line)" />
          </marker>
          <marker id="arrow-yellow" viewBox="0 0 8 8" refX="8" refY="4" markerWidth="7" markerHeight="7" orient="auto-start-reverse">
            <path d="M0 0L8 4L0 8Z" fill="var(--yellow)" />
          </marker>
        </defs>
        {view.relationEdges.map((edge) => {
          const route = connectionRoutes[edge.id];
          const path = route?.path ?? "";
          const selected = edge.id === selectedEdgeId;
          const related = selectedNodeId ? edge.sourceNodeId === selectedNodeId || edge.targetNodeId === selectedNodeId : false;
          const marker = selected
            ? "arrow-yellow"
            : related
              ? "arrow-green"
              : "arrow-gray";
          return (
            <g key={edge.id}>
              <path
                className={[
                  "relation",
                  related ? "is-related" : "",
                  selected ? "connection-selected" : ""
                ]
                  .filter(Boolean)
                  .join(" ")}
                d={path}
                data-edge={edge.id}
                data-protocol={edge.protocolLabel}
                data-scope={edge.scopeKey}
                data-source={edge.sourceNodeId}
                data-source-port={route?.sourcePort ?? edge.sourcePort}
                data-target={edge.targetNodeId}
                data-target-port={route?.targetPort ?? edge.targetPort}
                markerEnd={`url(#${marker})`}
              />
              <path
                className="relation-hitbox"
                d={path}
                onClick={() => onSelectEdge(edge.id)}
                onPointerDown={(event) => {
                  if (event.button === 0) event.stopPropagation();
                }}
              />
            </g>
          );
        })}
      </svg>
    </>
  );
}

function FunctionalSubsystemView({
  highlightedNodeIds,
  relatedNodeIds,
  selectedPortsByNodeId,
  selectedNodeId,
  subsystem,
  onSelectNode
}: {
  highlightedNodeIds: Set<string>;
  relatedNodeIds: Set<string>;
  selectedPortsByNodeId: Map<string, PortSide>;
  selectedNodeId: string | null;
  subsystem: VisualFunctionalSubsystem;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section className={`boundary ${subsystem.className}`} data-boundary={subsystem.id}>
      <div className="boundary__label">ФП · {subsystem.label}</div>
      {subsystem.modules.map((module) => (
        <ModuleView
          highlightedNodeIds={highlightedNodeIds}
          key={module.id}
          module={module}
          relatedNodeIds={relatedNodeIds}
          selectedPortsByNodeId={selectedPortsByNodeId}
          selectedNodeId={selectedNodeId}
          onSelectNode={onSelectNode}
        />
      ))}
      {subsystem.services.map((node) => (
        <GraphNodeButton
          highlightedNodeIds={highlightedNodeIds}
          key={node.id}
          node={node}
          relatedNodeIds={relatedNodeIds}
          selectedPort={selectedPortsByNodeId.get(node.id) ?? null}
          selectedNodeId={selectedNodeId}
          onSelectNode={onSelectNode}
        />
      ))}
    </section>
  );
}

function ModuleView({
  highlightedNodeIds,
  module,
  relatedNodeIds,
  selectedPortsByNodeId,
  selectedNodeId,
  onSelectNode
}: {
  highlightedNodeIds: Set<string>;
  module: VisualModule;
  relatedNodeIds: Set<string>;
  selectedPortsByNodeId: Map<string, PortSide>;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section className={`boundary ${module.className}`} data-boundary={module.id}>
      <div className="boundary__label">МОДУЛЬ · {module.label}</div>
      {module.submodules.map((submodule) => (
        <SubmoduleView
          highlightedNodeIds={highlightedNodeIds}
          key={submodule.id}
          relatedNodeIds={relatedNodeIds}
          selectedPortsByNodeId={selectedPortsByNodeId}
          selectedNodeId={selectedNodeId}
          submodule={submodule}
          onSelectNode={onSelectNode}
        />
      ))}
      {module.services.map((node) => (
        <GraphNodeButton
          highlightedNodeIds={highlightedNodeIds}
          key={node.id}
          node={node}
          relatedNodeIds={relatedNodeIds}
          selectedPort={selectedPortsByNodeId.get(node.id) ?? null}
          selectedNodeId={selectedNodeId}
          onSelectNode={onSelectNode}
        />
      ))}
    </section>
  );
}

function SubmoduleView({
  highlightedNodeIds,
  relatedNodeIds,
  selectedPortsByNodeId,
  selectedNodeId,
  submodule,
  onSelectNode
}: {
  highlightedNodeIds: Set<string>;
  relatedNodeIds: Set<string>;
  selectedPortsByNodeId: Map<string, PortSide>;
  selectedNodeId: string | null;
  submodule: VisualSubmodule;
  onSelectNode: (nodeId: string) => void;
}) {
  return (
    <section className={`boundary submodule ${submodule.className}`} data-boundary={submodule.id}>
      <div className="boundary__label">ПОДМОДУЛЬ · {submodule.label}</div>
      {submodule.services.map((node) => (
        <GraphNodeButton
          highlightedNodeIds={highlightedNodeIds}
          key={node.id}
          node={node}
          relatedNodeIds={relatedNodeIds}
          selectedPort={selectedPortsByNodeId.get(node.id) ?? null}
          selectedNodeId={selectedNodeId}
          onSelectNode={onSelectNode}
        />
      ))}
    </section>
  );
}

function GraphNodeButton({
  highlightedNodeIds,
  node,
  relatedNodeIds,
  selectedPort,
  selectedNodeId,
  onSelectNode
}: {
  highlightedNodeIds: Set<string>;
  node: VisualNode;
  relatedNodeIds: Set<string>;
  selectedPort: PortSide | null;
  selectedNodeId: string | null;
  onSelectNode: (nodeId: string) => void;
}) {
  const className = [
    node.kind === "event" ? "event-bus" : "service",
    node.className,
    selectedNodeId === node.id ? "selected" : "",
    relatedNodeIds.has(node.id) ? "is-related" : "",
    highlightedNodeIds.has(node.id) ? "connection-highlighted" : ""
  ]
    .filter(Boolean)
    .join(" ");
  return (
    <button
      className={className}
      data-node={node.id}
      style={node.position}
      type="button"
      onClick={() => onSelectNode(node.id)}
      onPointerDown={(event) => {
        if (event.button === 0) event.stopPropagation();
      }}
    >
      {node.name}
      {node.ports.map((port) => (
        <i
          className={["port", `port--${port}`, selectedPort === port ? "is-connection-selected" : ""]
            .filter(Boolean)
            .join(" ")}
          data-port={port}
          key={port}
        />
      ))}
    </button>
  );
}

function Inspector({
  selectedEdgeId,
  selectedNode,
  view,
  onSelectEdge
}: {
  selectedEdgeId: string | null;
  selectedNode: VisualNode | null;
  view: ArchitectureViewModel;
  onSelectEdge: (edgeId: string) => void;
}) {
  const connections = selectedNode
    ? view.relationEdges.filter(
        (edge) => edge.sourceNodeId === selectedNode.id || edge.targetNodeId === selectedNode.id
      )
    : [];
  const hierarchy = selectedNode ? view.hierarchyLinesByNodeId.get(selectedNode.id) ?? [] : [];

  return (
    <section className={["panel inspector", selectedNode ? "" : "is-hidden"].filter(Boolean).join(" ")}>
      <div className="overline">{selectedNode?.kind === "event" ? "Выбранная точка обмена" : "Выбранный сервис"}</div>
      <div className="inspector__title-row">
        <div className="inspector__title">{selectedNode?.name ?? "Сервис не выбран"}</div>
        <span className="badge">{selectedNode ? nodeTypeLabel(selectedNode.nodeType).toLowerCase() : "service"}</span>
      </div>
      <div className="section-title">Иерархия</div>
      <div className="hierarchy">
        {hierarchy.map((line, index) => (
          <HierarchyTextLine index={index} key={`${line.text}-${index}`} line={line} />
        ))}
      </div>
      <div className="section-title">Связи</div>
      <div className="connection-list">
        {selectedNode && connections.length ? (
          connections.map((edge) => (
            <ConnectionItem
              active={edge.id === selectedEdgeId}
              edge={edge}
              key={edge.id}
              otherNode={otherEndpoint(edge, selectedNode.id, view)}
              outgoing={edge.sourceNodeId === selectedNode.id}
              onSelectEdge={onSelectEdge}
            />
          ))
        ) : (
          <div className="connection-list__empty">Связи не найдены</div>
        )}
      </div>
    </section>
  );
}

function HierarchyTextLine({ index, line }: { index: number; line: HierarchyLine }) {
  return (
    <>
      {index ? <br /> : null}
      <span className={line.selected ? "hierarchy__selected" : undefined}>{line.text}</span>
    </>
  );
}

function ConnectionItem({
  active,
  edge,
  otherNode,
  outgoing,
  onSelectEdge
}: {
  active: boolean;
  edge: VisualEdge;
  otherNode: VisualNode | null;
  outgoing: boolean;
  onSelectEdge: (edgeId: string) => void;
}) {
  return (
    <button
      className={["connection-item", active ? "is-active" : ""].filter(Boolean).join(" ")}
      data-edge={edge.id}
      type="button"
      onClick={() => onSelectEdge(edge.id)}
    >
      <RelationIcon />
      <span>
        <span className="connection-item__name">{otherNode?.name ?? edge.targetNodeId}</span>
        <span className="connection-item__meta">{edge.protocolLabel}</span>
      </span>
      <span className={["connection-item__tag", outgoing ? "" : "neutral"].filter(Boolean).join(" ")}>
        {outgoing ? "Исходящая" : "Входящая"}
      </span>
    </button>
  );
}

function relatedNodes(edges: VisualEdge[], selectedNodeId: string | null): Set<string> {
  const nodeIds = new Set<string>();
  if (!selectedNodeId) return nodeIds;
  for (const edge of edges) {
    if (edge.sourceNodeId === selectedNodeId) nodeIds.add(edge.targetNodeId);
    if (edge.targetNodeId === selectedNodeId) nodeIds.add(edge.sourceNodeId);
  }
  return nodeIds;
}

function highlightedNodes(
  edges: VisualEdge[],
  selectedNodeId: string | null,
  selectedEdgeId: string | null
): Set<string> {
  const nodeIds = new Set<string>();
  if (!selectedNodeId || !selectedEdgeId) return nodeIds;
  const edge = edges.find((item) => item.id === selectedEdgeId);
  if (!edge) return nodeIds;
  if (edge.sourceNodeId === selectedNodeId) nodeIds.add(edge.targetNodeId);
  if (edge.targetNodeId === selectedNodeId) nodeIds.add(edge.sourceNodeId);
  return nodeIds;
}

function selectedConnectionPorts(
  edges: VisualEdge[],
  routes: Record<string, ConnectionRoute>,
  selectedEdgeId: string | null
): Map<string, PortSide> {
  const ports = new Map<string, PortSide>();
  if (!selectedEdgeId) return ports;
  const edge = edges.find((item) => item.id === selectedEdgeId);
  const route = routes[selectedEdgeId];
  if (!edge || !route) return ports;
  ports.set(edge.sourceNodeId, route.sourcePort);
  ports.set(edge.targetNodeId, route.targetPort);
  return ports;
}

function otherEndpoint(edge: VisualEdge, selectedNodeId: string, view: ArchitectureViewModel): VisualNode | null {
  const otherNodeId = edge.sourceNodeId === selectedNodeId ? edge.targetNodeId : edge.sourceNodeId;
  return view.nodeById.get(otherNodeId) ?? null;
}

function portCenterKey(nodeId: string, side: string): string {
  return `${nodeId}:${side}`;
}

function getBaseRect(element: HTMLElement, root: HTMLElement): BoxRect {
  const rootRect = root.getBoundingClientRect();
  const elementRect = element.getBoundingClientRect();
  const measuredScaleX = root.offsetWidth ? rootRect.width / root.offsetWidth : 1;
  const measuredScaleY = root.offsetHeight ? rootRect.height / root.offsetHeight : 1;
  const scaleX = Number.isFinite(measuredScaleX) && measuredScaleX > 0 ? measuredScaleX : 1;
  const scaleY = Number.isFinite(measuredScaleY) && measuredScaleY > 0 ? measuredScaleY : 1;

  return {
    x: (elementRect.left - rootRect.left) / scaleX,
    y: (elementRect.top - rootRect.top) / scaleY,
    width: elementRect.width / scaleX,
    height: elementRect.height / scaleY
  };
}

function minimapMetrics(surface: HTMLElement) {
  const width = surface.clientWidth;
  const height = surface.clientHeight;
  const padding = 9;
  const scale = Math.min((width - padding * 2) / GRAPH_WIDTH, (height - padding * 2) / GRAPH_HEIGHT);
  return {
    width,
    height,
    padding,
    scale,
    offsetX: (width - GRAPH_WIDTH * scale) / 2,
    offsetY: (height - GRAPH_HEIGHT * scale) / 2
  };
}

function getNavigationViewport(
  canvas: HTMLElement,
  rightRail: HTMLElement | null,
  zoomToolbar: HTMLElement | null
) {
  const canvasRect = canvas.getBoundingClientRect();
  const railRect = rightRail?.getBoundingClientRect();
  const zoomRect = zoomToolbar?.getBoundingClientRect();
  const top = railRect ? Math.max(0, railRect.top - canvasRect.top) : 0;
  const right = railRect ? Math.max(0, canvasRect.right - railRect.left + 18) : 0;
  const bottom = zoomRect ? Math.max(0, canvasRect.bottom - zoomRect.top + 12) : 0;
  return {
    left: 0,
    top,
    width: Math.max(1, canvas.clientWidth - right),
    height: Math.max(1, canvas.clientHeight - top - bottom)
  };
}

function manualNodePayload(node: GraphNodeProjectionResponse) {
  return {
    node_id: node.node_id,
    stable_key: node.stable_key,
    node_type: node.node_type,
    name: node.name,
    origin: "MANUAL",
    validation_state: "CONFIRMED",
    confidence: 1,
    evidence: [],
    validation_record: null,
    metadata: {}
  };
}

function suppressionPayload(node: GraphNodeProjectionResponse, scope: ArchitectureScope) {
  return {
    node_id: node.node_id,
    confirm_children_strategy: scope.kind === "system" || scope.kind === "functional-subsystem" ? "SUPPRESS_DESCENDANTS" : null,
    confirm_incident_edges: true,
    confirm_high_impact: scope.kind === "system" || node.node_type === "AUTOMATED_SYSTEM"
  };
}

function repositoryNameFromProjection(projection: GraphProjectionResponse): string {
  const source = projection.summary.repository_name;
  return typeof source === "string" ? source : "payments-platform";
}

function auditFailureMessage(audit: AuditResponse): string {
  const rawError = audit.summary.error;
  if (rawError && typeof rawError === "object" && !Array.isArray(rawError)) {
    const message = (rawError as Record<string, unknown>).message;
    if (typeof message === "string" && message.trim()) {
      return `Аудит ${audit.status.toLowerCase()} · ${message}`;
    }
  }
  return `Аудит завершился со статусом ${audit.status}`;
}

function auditProgressForStatus(status: string): number {
  const progressByStatus: Record<string, number> = {
    QUEUED: 4,
    SCANNING: 22,
    DISCOVERING: 42,
    ANALYZING: 58,
    VALIDATING: 76,
    ASSEMBLING: 90,
    PARTIAL: 100,
    COMPLETED: 100,
    COMPLETED_WITH_WARNINGS: 100,
    FAILED: 100,
    CANCELLED: 100,
    INTERRUPTED: 100
  };
  return progressByStatus[status] ?? 0;
}

function auditStatusLabel(status: string | undefined): string {
  const labels: Record<string, string> = {
    QUEUED: "Аудит поставлен в очередь",
    SCANNING: "Индексируем репозиторий",
    DISCOVERING: "Находим компоненты и связи",
    ANALYZING: "Анализируем компоненты",
    VALIDATING: "Проверяем evidence",
    ASSEMBLING: "Собираем архитектурный граф",
    PARTIAL: "Аудит завершён частично",
    COMPLETED: "Аудит завершён",
    COMPLETED_WITH_WARNINGS: "Аудит завершён с предупреждениями",
    FAILED: "Аудит завершился ошибкой",
    CANCELLED: "Аудит отменён",
    INTERRUPTED: "Аудит прерван"
  };
  return labels[status ?? ""] ?? "Подготовка аудита";
}

function idempotencyKey(): string {
  if (globalThis.crypto?.randomUUID) return globalThis.crypto.randomUUID();
  return `audit-${Math.random().toString(36).slice(2)}`;
}

function readTheme(): ThemeName {
  return readStorage("architecture-theme", "dark") === "light" ? "light" : "dark";
}

function readLayout(): LayoutMode {
  return readStorage("architecture-layout", "hierarchy") === "horizontal" ? "horizontal" : "hierarchy";
}

function readStorage(key: string, fallback: string): string {
  try {
    return window.localStorage.getItem(key) ?? fallback;
  } catch {
    return fallback;
  }
}

function writeStorage(key: string, value: string): void {
  try {
    window.localStorage.setItem(key, value);
  } catch {
    // Local storage can be disabled in embedded browser contexts.
  }
}

function clamp(value: number, min: number, max: number): number {
  return Math.min(max, Math.max(min, value));
}

function BrandMark() {
  return (
    <svg className="brand-mark" viewBox="0 0 180 180" fill="none" aria-hidden="true">
      <defs>
        <linearGradient id="header-logo-flow" x1="139" y1="27" x2="48" y2="149" gradientUnits="userSpaceOnUse">
          <stop offset="0" stopColor="#159FEA" />
          <stop offset=".52" stopColor="#21B77A" />
          <stop offset="1" stopColor="#B9D92B" />
        </linearGradient>
      </defs>
      <path
        d="M147 35C164 56 168 82 159 106C146 138 113 156 79 150C45 144 22 116 25 82C28 48 56 24 89 26C117 27 138 48 139 75C140 99 122 120 98 123C75 126 55 110 53 88C51 68 65 51 84 48C101 46 116 57 118 73C120 87 111 99 98 101C87 103 77 96 76 86"
        stroke="url(#header-logo-flow)"
        strokeLinecap="round"
        strokeLinejoin="round"
        strokeWidth="14"
      />
    </svg>
  );
}

function FolderIcon() {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M3.5 7.5h6l1.6 2H20.5v8.5a2 2 0 0 1-2 2h-13a2 2 0 0 1-2-2V7.5Z" stroke="currentColor" strokeLinejoin="round" strokeWidth="1.5" />
      <path d="M3.5 10h17" stroke="currentColor" strokeWidth="1.5" />
    </svg>
  );
}

function MoreIcon() {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <circle cx="5" cy="12" r="1.6" fill="currentColor" />
      <circle cx="12" cy="12" r="1.6" fill="currentColor" />
      <circle cx="19" cy="12" r="1.6" fill="currentColor" />
    </svg>
  );
}

function TrashIcon() {
  return (
    <svg viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M4.5 7h15M9 7V4.8h6V7M7 7l.7 12h8.6L17 7M10 10.5v5M14 10.5v5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.5" />
    </svg>
  );
}

function ChevronIcon({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 20 20" fill="none" aria-hidden="true">
      <path d="m6 8 4 4 4-4" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.6" />
    </svg>
  );
}

function ChevronRightIcon({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 16 16" fill="none" aria-hidden="true">
      <path d="M6 4.5 9.5 8 6 11.5" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.4" />
    </svg>
  );
}

function CheckIcon({ className }: { className: string }) {
  return (
    <svg className={className} viewBox="0 0 18 18" fill="none" aria-hidden="true">
      <path d="m5 9 2.5 2.5L13 6" stroke="currentColor" strokeLinecap="round" strokeLinejoin="round" strokeWidth="1.7" />
    </svg>
  );
}

function MinusIcon() {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M6 12h12" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </svg>
  );
}

function PlusIcon() {
  return (
    <svg className="icon" viewBox="0 0 24 24" fill="none" aria-hidden="true">
      <path d="M12 6v12M6 12h12" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
    </svg>
  );
}

function RelationIcon() {
  return (
    <svg className="relation-icon" viewBox="0 0 32 18" fill="none" aria-hidden="true">
      <circle cx="6" cy="9" r="4" fill="var(--surface)" stroke="currentColor" strokeWidth="1.8" />
      <path d="M10 9H23" stroke="currentColor" strokeLinecap="round" strokeWidth="1.8" />
      <circle cx="26" cy="9" r="4" fill="var(--surface)" stroke="currentColor" strokeWidth="1.8" />
    </svg>
  );
}

function HierarchyPreviewIcon() {
  return (
    <svg className="layout-option__preview" viewBox="0 0 120 42" fill="none" aria-hidden="true">
      <rect x="3" y="3" width="114" height="36" rx="10" stroke="currentColor" opacity=".45" />
      <rect x="12" y="11" width="45" height="20" rx="6" stroke="currentColor" />
      <rect x="64" y="11" width="44" height="20" rx="6" stroke="currentColor" />
      <rect x="18" y="17" width="15" height="8" rx="4" fill="currentColor" opacity=".55" />
      <rect x="37" y="17" width="14" height="8" rx="4" fill="currentColor" opacity=".55" />
      <rect x="71" y="17" width="29" height="8" rx="4" fill="currentColor" opacity=".55" />
    </svg>
  );
}

function HorizontalPreviewIcon() {
  return (
    <svg className="layout-option__preview" viewBox="0 0 120 42" fill="none" aria-hidden="true">
      <rect x="4" y="4" width="112" height="14" rx="5" stroke="currentColor" />
      <rect x="15" y="24" width="90" height="14" rx="5" stroke="currentColor" opacity=".62" />
      <path d="M16 11h17M41 11h17M66 11h17M91 11h13M27 31h17M52 31h17M77 31h16" stroke="currentColor" strokeLinecap="round" strokeWidth="4" opacity=".55" />
    </svg>
  );
}
