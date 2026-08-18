import {
  ApiClient,
  ApiClientError,
  type ApiRequestOptions,
  type AuditResponse,
  type GraphEdgeDetailResponse,
  type GraphOverrideCreateRequest,
  type GraphOverrideResponse,
  type GraphProjectionResponse,
  type GraphRevisionCreateRequest,
  type GraphRevisionResponse,
  type HealthResponse,
  type ProjectCreateRequest,
  type ProjectResponse
} from "./client";

export type ArchitectureBackend = {
  health(options?: ApiRequestOptions<never>): Promise<HealthResponse>;
  listProjects(options?: ApiRequestOptions<never>): Promise<ProjectResponse[]>;
  createProject(
    request: ProjectCreateRequest,
    options?: Omit<ApiRequestOptions<ProjectCreateRequest>, "body">
  ): Promise<ProjectResponse>;
  listProjectAudits(
    projectId: string,
    options?: ApiRequestOptions<never>
  ): Promise<AuditResponse[]>;
  startAudit(
    projectId: string,
    idempotencyKey: string,
    options?: Omit<ApiRequestOptions<never>, "path" | "headers">
  ): Promise<AuditResponse>;
  getAudit(auditId: string, options?: ApiRequestOptions<never>): Promise<AuditResponse>;
  getAuditGraph(
    auditId: string,
    revisionId?: string | null,
    options?: ApiRequestOptions<never>
  ): Promise<GraphProjectionResponse>;
  getGraphNode(
    graphId: string,
    nodeId: string,
    options?: ApiRequestOptions<never>
  ): Promise<unknown>;
  getGraphEdge(
    graphId: string,
    edgeId: string,
    options?: ApiRequestOptions<never>
  ): Promise<GraphEdgeDetailResponse>;
  createGraphRevision(
    graphId: string,
    request: GraphRevisionCreateRequest,
    options?: Omit<ApiRequestOptions<GraphRevisionCreateRequest>, "path" | "body">
  ): Promise<GraphRevisionResponse>;
  createGraphOverride(
    revisionId: string,
    request: GraphOverrideCreateRequest,
    options?: Omit<ApiRequestOptions<GraphOverrideCreateRequest>, "path" | "body">
  ): Promise<GraphOverrideResponse>;
  commitGraphRevision(
    revisionId: string,
    options?: Omit<ApiRequestOptions<never>, "path">
  ): Promise<GraphRevisionResponse>;
  deleteUnsavedManualNode(
    revisionId: string,
    nodeId: string,
    options?: Omit<ApiRequestOptions<never>, "path">
  ): Promise<void>;
};

export class GeneratedArchitectureBackend implements ArchitectureBackend {
  constructor(private readonly client = new ApiClient()) {}

  health(options: ApiRequestOptions<never> = {}): Promise<HealthResponse> {
    return this.client.get_health_api_v1_health_get(options);
  }

  listProjects(options: ApiRequestOptions<never> = {}): Promise<ProjectResponse[]> {
    return this.client.list_projects_api_v1_projects_get(options);
  }

  createProject(
    request: ProjectCreateRequest,
    options: Omit<ApiRequestOptions<ProjectCreateRequest>, "body"> = {}
  ): Promise<ProjectResponse> {
    return this.client.create_project_api_v1_projects_post({
      ...options,
      body: request
    });
  }

  listProjectAudits(
    projectId: string,
    options: ApiRequestOptions<never> = {}
  ): Promise<AuditResponse[]> {
    return this.client.list_project_audits_api_v1_projects__project_id__audits_get({
      ...options,
      path: { ...options.path, project_id: projectId }
    });
  }

  startAudit(
    projectId: string,
    idempotencyKey: string,
    options: Omit<ApiRequestOptions<never>, "path" | "headers"> = {}
  ): Promise<AuditResponse> {
    return this.client.start_audit_api_v1_projects__project_id__audits_post({
      ...options,
      path: { project_id: projectId },
      headers: { "Idempotency-Key": idempotencyKey }
    });
  }

  getAudit(auditId: string, options: ApiRequestOptions<never> = {}): Promise<AuditResponse> {
    return this.client.get_audit_api_v1_audits__audit_id__get({
      ...options,
      path: { ...options.path, audit_id: auditId }
    });
  }

  getAuditGraph(
    auditId: string,
    revisionId: string | null = null,
    options: ApiRequestOptions<never> = {}
  ): Promise<GraphProjectionResponse> {
    return this.client.get_audit_graph_api_v1_audits__audit_id__graph_get({
      ...options,
      path: { ...options.path, audit_id: auditId },
      query: { ...options.query, revision_id: revisionId }
    });
  }

  getGraphNode(
    graphId: string,
    nodeId: string,
    options: ApiRequestOptions<never> = {}
  ): Promise<unknown> {
    return this.client.get_graph_node_api_v1_graphs__graph_id__nodes__node_id__get({
      ...options,
      path: { ...options.path, graph_id: graphId, node_id: nodeId }
    });
  }

  getGraphEdge(
    graphId: string,
    edgeId: string,
    options: ApiRequestOptions<never> = {}
  ): Promise<GraphEdgeDetailResponse> {
    return this.client.get_graph_edge_api_v1_graphs__graph_id__edges__edge_id__get({
      ...options,
      path: { ...options.path, graph_id: graphId, edge_id: edgeId }
    });
  }

  createGraphRevision(
    graphId: string,
    request: GraphRevisionCreateRequest,
    options: Omit<ApiRequestOptions<GraphRevisionCreateRequest>, "path" | "body"> = {}
  ): Promise<GraphRevisionResponse> {
    return this.client.create_graph_revision_api_v1_graphs__graph_id__revisions_post({
      ...options,
      path: { graph_id: graphId },
      body: request
    });
  }

  createGraphOverride(
    revisionId: string,
    request: GraphOverrideCreateRequest,
    options: Omit<ApiRequestOptions<GraphOverrideCreateRequest>, "path" | "body"> = {}
  ): Promise<GraphOverrideResponse> {
    return this.client.create_graph_override_api_v1_revisions__revision_id__overrides_post({
      ...options,
      path: { revision_id: revisionId },
      body: request
    });
  }

  commitGraphRevision(
    revisionId: string,
    options: Omit<ApiRequestOptions<never>, "path"> = {}
  ): Promise<GraphRevisionResponse> {
    return this.client.commit_graph_revision_api_v1_revisions__revision_id__commit_post({
      ...options,
      path: { revision_id: revisionId }
    });
  }

  deleteUnsavedManualNode(
    revisionId: string,
    nodeId: string,
    options: Omit<ApiRequestOptions<never>, "path"> = {}
  ): Promise<void> {
    return this.client.delete_unsaved_manual_node_api_v1_revisions__revision_id__manual_nodes__node_id__delete(
      {
        ...options,
        path: { revision_id: revisionId, node_id: nodeId }
      }
    );
  }
}

export function describeArchitectureBackendError(error: unknown): string {
  if (error instanceof ApiClientError) {
    return `HTTP ${error.status}: ${trimResponse(error.responseText)}`;
  }
  if (error instanceof Error) {
    return error.message;
  }
  return "Неизвестная ошибка";
}

function trimResponse(responseText: string): string {
  const trimmed = responseText.trim();
  if (!trimmed) return "пустой ответ";
  return trimmed.length > 180 ? `${trimmed.slice(0, 177)}...` : trimmed;
}
