import express from "express";
import fetch from "node-fetch";

const app = express();
const billingBaseUrl = process.env.BILLING_API_URL ?? "http://billing-api:3001";

app.get("/orders/:orderId", async (request, response) => {
  const invoice = await fetch(`${billingBaseUrl}/invoices/${request.params.orderId}`);
  response.json({ orderId: request.params.orderId, invoiceStatus: invoice.status });
});

app.listen(3000);
