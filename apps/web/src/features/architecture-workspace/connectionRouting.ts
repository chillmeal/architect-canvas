export type PortSide = "left" | "right" | "top" | "bottom";

export type BoxRect = {
  x: number;
  y: number;
  width: number;
  height: number;
};

export type ConnectionRoute = {
  path: string;
  points: readonly Point[];
  sourcePoint: Point;
  targetPoint: Point;
  sourcePort: PortSide;
  targetPort: PortSide;
};

export type Point = {
  x: number;
  y: number;
};

const STUB_LENGTH = 28;
const OBSTACLE_CLEARANCE = 18;
const CORNER_RADIUS = 10;

const SIDE_VECTOR: Record<PortSide, Point> = {
  left: { x: -1, y: 0 },
  right: { x: 1, y: 0 },
  top: { x: 0, y: -1 },
  bottom: { x: 0, y: 1 }
};

export function buildConnectionRoute({
  source,
  target,
  sourcePoint: explicitSourcePoint,
  targetPoint: explicitTargetPoint,
  sourcePort,
  targetPort,
  obstacles = []
}: {
  source: BoxRect;
  target: BoxRect;
  sourcePoint?: Point;
  targetPoint?: Point;
  sourcePort?: PortSide;
  targetPort?: PortSide;
  obstacles?: BoxRect[];
}): ConnectionRoute {
  const ports =
    sourcePort && targetPort ? { sourcePort, targetPort } : chooseConnectionPorts(source, target);
  const sourcePoint = explicitSourcePoint ?? pointForPort(source, ports.sourcePort);
  const targetPoint = explicitTargetPoint ?? pointForPort(target, ports.targetPort);
  const sourceVector = SIDE_VECTOR[ports.sourcePort];
  const targetVector = SIDE_VECTOR[ports.targetPort];
  const startStub = movePoint(sourcePoint, sourceVector, STUB_LENGTH);
  const endStub = movePoint(targetPoint, targetVector, STUB_LENGTH);
  const expandedObstacles = obstacles.map((obstacle) => expandRect(obstacle, OBSTACLE_CLEARANCE));
  const routePoints = chooseOrthogonalRoute(
    sourcePoint,
    startStub,
    endStub,
    targetPoint,
    expandedObstacles
  );

  return {
    path: formatRoundedOrthogonalPath(routePoints),
    points: routePoints,
    sourcePoint,
    targetPoint,
    sourcePort: ports.sourcePort,
    targetPort: ports.targetPort
  };
}

export function chooseConnectionPorts(
  source: BoxRect,
  target: BoxRect
): { sourcePort: PortSide; targetPort: PortSide } {
  const sourceCenter = centerOf(source);
  const targetCenter = centerOf(target);
  const dx = targetCenter.x - sourceCenter.x;
  const dy = targetCenter.y - sourceCenter.y;

  if (Math.abs(dx) >= Math.abs(dy)) {
    return dx >= 0
      ? { sourcePort: "right", targetPort: "left" }
      : { sourcePort: "left", targetPort: "right" };
  }

  return dy >= 0
    ? { sourcePort: "bottom", targetPort: "top" }
    : { sourcePort: "top", targetPort: "bottom" };
}

export function pointForPort(rect: BoxRect, port: PortSide): Point {
  if (port === "left") return { x: rect.x, y: rect.y + rect.height / 2 };
  if (port === "right") return { x: rect.x + rect.width, y: rect.y + rect.height / 2 };
  if (port === "top") return { x: rect.x + rect.width / 2, y: rect.y };
  return { x: rect.x + rect.width / 2, y: rect.y + rect.height };
}

function centerOf(rect: BoxRect): Point {
  return {
    x: rect.x + rect.width / 2,
    y: rect.y + rect.height / 2
  };
}

function chooseOrthogonalRoute(
  sourcePoint: Point,
  startStub: Point,
  endStub: Point,
  targetPoint: Point,
  obstacles: BoxRect[]
): Point[] {
  const candidates = buildRouteCandidates(sourcePoint, startStub, endStub, targetPoint, obstacles);
  let bestRoute: Point[] | null = null;
  let bestScore = Number.POSITIVE_INFINITY;

  for (const candidate of candidates) {
    const route = normalizeRoute(candidate);
    if (!isOrthogonalRoute(route)) continue;
    if (routeIntersectsObstacles(route, obstacles)) continue;

    const score = routeScore(route);
    if (score < bestScore) {
      bestRoute = route;
      bestScore = score;
    }
  }

  return (
    bestRoute ??
    normalizeRoute([
      sourcePoint,
      startStub,
      { x: endStub.x, y: startStub.y },
      endStub,
      targetPoint
    ])
  );
}

function buildRouteCandidates(
  sourcePoint: Point,
  startStub: Point,
  endStub: Point,
  targetPoint: Point,
  obstacles: BoxRect[]
): Point[][] {
  const xCoords = corridorCoords("x", startStub, endStub, sourcePoint, targetPoint, obstacles);
  const yCoords = corridorCoords("y", startStub, endStub, sourcePoint, targetPoint, obstacles);
  const candidates: Point[][] = [];
  const seen = new Set<string>();

  const add = (points: Point[]) => {
    const key = normalizeRoute(points)
      .map((point) => `${format(point.x)},${format(point.y)}`)
      .join("|");
    if (seen.has(key)) return;
    seen.add(key);
    candidates.push(points);
  };

  add([sourcePoint, startStub, endStub, targetPoint]);
  add([sourcePoint, startStub, { x: endStub.x, y: startStub.y }, endStub, targetPoint]);
  add([sourcePoint, startStub, { x: startStub.x, y: endStub.y }, endStub, targetPoint]);

  for (const x of xCoords) {
    add([
      sourcePoint,
      startStub,
      { x, y: startStub.y },
      { x, y: endStub.y },
      endStub,
      targetPoint
    ]);
  }

  for (const y of yCoords) {
    add([
      sourcePoint,
      startStub,
      { x: startStub.x, y },
      { x: endStub.x, y },
      endStub,
      targetPoint
    ]);
  }

  for (const x of xCoords) {
    for (const y of yCoords) {
      add([
        sourcePoint,
        startStub,
        { x, y: startStub.y },
        { x, y },
        { x: endStub.x, y },
        endStub,
        targetPoint
      ]);
      add([
        sourcePoint,
        startStub,
        { x: startStub.x, y },
        { x, y },
        { x, y: endStub.y },
        endStub,
        targetPoint
      ]);
    }
  }

  return candidates;
}

function corridorCoords(
  axis: "x" | "y",
  startStub: Point,
  endStub: Point,
  sourcePoint: Point,
  targetPoint: Point,
  obstacles: BoxRect[]
): number[] {
  const values = new Set<number>();
  const startValue = axis === "x" ? startStub.x : startStub.y;
  const endValue = axis === "x" ? endStub.x : endStub.y;
  const sourceValue = axis === "x" ? sourcePoint.x : sourcePoint.y;
  const targetValue = axis === "x" ? targetPoint.x : targetPoint.y;
  const lower = Math.min(startValue, endValue, sourceValue, targetValue);
  const upper = Math.max(startValue, endValue, sourceValue, targetValue);

  values.add(startValue);
  values.add(endValue);
  values.add((startValue + endValue) / 2);
  values.add(lower - STUB_LENGTH);
  values.add(upper + STUB_LENGTH);

  for (const obstacle of obstacles) {
    const before = axis === "x" ? obstacle.x : obstacle.y;
    const after = axis === "x" ? obstacle.x + obstacle.width : obstacle.y + obstacle.height;
    values.add(before);
    values.add(after);
  }

  return [...values].sort((left, right) => left - right);
}

function normalizeRoute(points: Point[]): Point[] {
  const withoutDuplicates: Point[] = [];
  for (const point of points) {
    const previous = withoutDuplicates[withoutDuplicates.length - 1];
    if (previous && samePoint(previous, point)) continue;
    withoutDuplicates.push(point);
  }

  const normalized: Point[] = [];
  for (const point of withoutDuplicates) {
    const previous = normalized[normalized.length - 1];
    const beforePrevious = normalized[normalized.length - 2];
    if (beforePrevious && previous && isCollinear(beforePrevious, previous, point)) {
      normalized[normalized.length - 1] = point;
      continue;
    }
    normalized.push(point);
  }
  return normalized;
}

function isOrthogonalRoute(points: Point[]): boolean {
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    if (previous.x !== current.x && previous.y !== current.y) return false;
  }
  return true;
}

function routeIntersectsObstacles(points: Point[], obstacles: BoxRect[]): boolean {
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    if (obstacles.some((obstacle) => segmentIntersectsRect(previous, current, obstacle))) {
      return true;
    }
  }
  return false;
}

function segmentIntersectsRect(start: Point, end: Point, rect: BoxRect): boolean {
  if (start.x === end.x) {
    const x = start.x;
    const top = Math.min(start.y, end.y);
    const bottom = Math.max(start.y, end.y);
    return x > rect.x && x < rect.x + rect.width && bottom > rect.y && top < rect.y + rect.height;
  }
  if (start.y === end.y) {
    const y = start.y;
    const left = Math.min(start.x, end.x);
    const right = Math.max(start.x, end.x);
    return y > rect.y && y < rect.y + rect.height && right > rect.x && left < rect.x + rect.width;
  }
  return true;
}

function routeScore(points: Point[]): number {
  let length = 0;
  let bends = 0;
  for (let index = 1; index < points.length; index += 1) {
    const previous = points[index - 1];
    const current = points[index];
    length += Math.abs(current.x - previous.x) + Math.abs(current.y - previous.y);

    const beforePrevious = points[index - 2];
    if (beforePrevious && !isCollinear(beforePrevious, previous, current)) {
      bends += 1;
    }
  }
  return length + bends * 24;
}

function formatRoundedOrthogonalPath(points: Point[]): string {
  if (!points.length) return "";
  if (points.length === 1) return `M ${format(points[0].x)} ${format(points[0].y)}`;

  let path = `M ${format(points[0].x)} ${format(points[0].y)}`;
  for (let index = 1; index < points.length - 1; index += 1) {
    const previous = points[index - 1];
    const corner = points[index];
    const next = points[index + 1];
    const radius = Math.min(
      CORNER_RADIUS,
      orthogonalDistance(previous, corner) / 2,
      orthogonalDistance(corner, next) / 2
    );
    if (!radius || isCollinear(previous, corner, next)) {
      path += ` L ${format(corner.x)} ${format(corner.y)}`;
      continue;
    }
    const beforeCorner = pointToward(corner, previous, radius);
    const afterCorner = pointToward(corner, next, radius);
    path += ` L ${format(beforeCorner.x)} ${format(beforeCorner.y)}`;
    path += ` Q ${format(corner.x)} ${format(corner.y)} ${format(afterCorner.x)} ${format(afterCorner.y)}`;
  }

  const target = points[points.length - 1];
  path += ` L ${format(target.x)} ${format(target.y)}`;
  return path;
}

function orthogonalDistance(left: Point, right: Point): number {
  return Math.abs(right.x - left.x) + Math.abs(right.y - left.y);
}

function pointToward(from: Point, to: Point, distance: number): Point {
  const total = orthogonalDistance(from, to);
  if (!total) return from;
  return {
    x: from.x + ((to.x - from.x) / total) * distance,
    y: from.y + ((to.y - from.y) / total) * distance
  };
}

function movePoint(point: Point, vector: Point, distance: number): Point {
  return {
    x: point.x + vector.x * distance,
    y: point.y + vector.y * distance
  };
}

function expandRect(rect: BoxRect, clearance: number): BoxRect {
  return {
    x: rect.x - clearance,
    y: rect.y - clearance,
    width: rect.width + clearance * 2,
    height: rect.height + clearance * 2
  };
}

function samePoint(left: Point, right: Point): boolean {
  return left.x === right.x && left.y === right.y;
}

function isCollinear(first: Point, second: Point, third: Point): boolean {
  return (first.x === second.x && second.x === third.x) || (first.y === second.y && second.y === third.y);
}

function format(value: number): string {
  return Number(value.toFixed(2)).toString();
}
