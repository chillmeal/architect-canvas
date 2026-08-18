# simple-rest

Artificial fixture repository with two Express services.

- `orders-api` exposes order endpoints and calls `billing-api`.
- `billing-api` exposes invoice lookup endpoint.

Expected confirmed graph: two microservice nodes and one `SYNC_CALL` edge from
`orders-api` to `billing-api`.

Fixture repository placeholder for two services and one confirmed HTTP call.
