package example;

import org.springframework.kafka.core.KafkaTemplate;

public class Application {
    private final KafkaTemplate<String, String> kafkaTemplate;

    public Application(KafkaTemplate<String, String> kafkaTemplate) {
        this.kafkaTemplate = kafkaTemplate;
    }

    public void publishOrderCreated(String orderId) {
        kafkaTemplate.send("orders.created", orderId);
    }

    public static void main(String[] args) {
    }
}
