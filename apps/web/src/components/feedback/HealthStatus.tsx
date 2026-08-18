type HealthStatusProps = {
  status: "ready" | "degraded" | "offline";
};

export function HealthStatus({ status }: HealthStatusProps) {
  return (
    <div className="health-status" aria-label="Application health">
      <span className={`health-dot health-dot-${status}`} />
      <span>{status}</span>
    </div>
  );
}
