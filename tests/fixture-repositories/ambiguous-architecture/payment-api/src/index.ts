import express from "express";
import type { PaymentsApiClient } from "../../shared/payments-api-client";

const app = express();

app.get("/payments/:paymentId", (request, response) => {
  const metadata: PaymentsApiClient = { displayName: "payments-api" };
  response.json({ paymentId: request.params.paymentId, metadata });
});

app.listen(3100);
