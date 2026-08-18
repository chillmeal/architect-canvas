package example;

import org.springframework.kafka.annotation.KafkaListener;

public class Application {
    @KafkaListener(topics = "orders.created", groupId = "inventory-service")
    public void reserveInventory(String orderId) {
        System.out.println("Reserve inventory for " + orderId);
    }

    public static void main(String[] args) {
    }
}
