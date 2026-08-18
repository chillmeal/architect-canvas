# ambiguous-architecture

Artificial fixture repository for similar service names, false imports, and insufficient evidence.

- `payment-api` and `payments-api` are intentionally similar names.
- `payment-api` imports a shared type named `PaymentsApiClient`, but never performs a runtime call.
- `shared/payments-api-client.ts` is a DTO-only module and must not create a confirmed service edge.

Expected graph: two distinct microservice nodes and a review issue for insufficient
evidence. There is no confirmed edge between the services.
