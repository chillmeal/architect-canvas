import express from "express";

const app = express();

app.get("/invoices/:orderId", (request, response) => {
  response.json({ orderId: request.params.orderId, status: "OPEN" });
});

app.listen(3001);
