<?php

namespace App\Modules\Warehouse;

interface Inventory
{
    public function available(string $productId): int;

    public function addStock(string $productId, int $quantity, string $operationId): void;

    /** Returns null on success, or a list of shortages when the warehouse rejected the reservation. */
    public function reserve(string $orderId, array $lines): ?array;

    public function release(string $orderId): void;
}
