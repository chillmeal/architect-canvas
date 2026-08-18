import express from "express";

const app = express();

app.get("/ledger-payments/:paymentId", (request, response) => {
  response.json({ paymentId: request.params.paymentId, posted: false });
});

app.listen(3200);
