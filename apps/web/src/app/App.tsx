import {
  GeneratedArchitectureBackend,
  type ArchitectureBackend
} from "../api/architectureClient";
import { ArchitectureWorkspace } from "../features/architecture-workspace/ArchitectureWorkspace";

const defaultBackend = new GeneratedArchitectureBackend();

export function App({ backend = defaultBackend }: { backend?: ArchitectureBackend } = {}) {
  return <ArchitectureWorkspace backend={backend} />;
}
