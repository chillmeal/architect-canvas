# kafka-services

Artificial fixture repository with a Kafka producer and consumer.

- `order-service` publishes `orders.created`.
- `inventory-service` consumes `orders.created`.

Expected confirmed graph: producer service, consumer service, topic node, one
`ASYNC_PUBLISH` edge, and one `ASYNC_SUBSCRIBE` edge.

Fixture repository placeholder for a producer, a consumer, and a topic.
