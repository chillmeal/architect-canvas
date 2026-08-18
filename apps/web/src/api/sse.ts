export function createEventSource(path: string): EventSource {
  return new EventSource(path);
}
