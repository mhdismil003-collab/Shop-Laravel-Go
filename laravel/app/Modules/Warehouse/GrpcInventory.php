<?php

namespace App\Modules\Warehouse;

use App\Http\ApiProblem;
use Grpc\ChannelCredentials;
use Grpc\UnaryCall;
use Illuminate\Support\Facades\Log;
use Inventory\V1\AddStockRequest;
use Inventory\V1\GetStockRequest;
use Inventory\V1\InventoryAdminServiceClient;
use Inventory\V1\InventoryServiceClient;
use Inventory\V1\ReleaseRequest;
use Inventory\V1\ReserveItem;
use Inventory\V1\ReserveRequest;

final class GrpcInventory implements Inventory
{
    private readonly InventoryServiceClient $client;

    public function __construct()
    {
        $this->client = new InventoryServiceClient(config('shop.warehouse_address'), [
            'credentials' => ChannelCredentials::createInsecure(),
        ]);
    }

    public function available(string $productId): int
    {
        $request = (new GetStockRequest)->setProductId($productId);

        return $this->reply('GetStock', $this->client->GetStock($request, [], $this->options()))->getAvailable();
    }

    public function addStock(string $productId, int $quantity, string $operationId): void
    {
        $client = new InventoryAdminServiceClient(config('shop.warehouse_admin_address'), [
            'credentials' => ChannelCredentials::createInsecure(),
        ]);
        $request = (new AddStockRequest)->setProductId($productId)
            ->setQuantity($quantity)->setOperationId($operationId);
        $this->reply('AddStock', $client->AddStock($request, [], $this->options()));
    }

    public function reserve(string $orderId, array $lines): ?array
    {
        $items = array_map(static fn (array $line) => (new ReserveItem)
            ->setProductId($line['productId'])->setQuantity($line['quantity']), $lines);
        $request = (new ReserveRequest)->setOrderId($orderId)->setItems($items);
        $reply = $this->reply('Reserve', $this->client->Reserve($request, [], $this->options()));

        if ($reply->getReserved()) {
            return null;
        }

        $shortages = [];
        foreach ($reply->getShortages() as $item) {
            $shortages[] = [
                'productId' => $item->getProductId(),
                'requested' => $item->getRequested(),
                'available' => $item->getAvailable(),
            ];
        }

        return $shortages;
    }

    public function release(string $orderId): void
    {
        $request = (new ReleaseRequest)->setOrderId($orderId);
        $this->reply('Release', $this->client->Release($request, [], $this->options()));
    }

    private function options(): array
    {
        return ['timeout' => config('shop.warehouse_timeout_us')];
    }

    private function reply(string $operation, UnaryCall $call): object
    {
        [$reply, $status] = $call->wait();
        if ($operation === 'AddStock' && $status->code === \Grpc\STATUS_ALREADY_EXISTS) {
            throw new ApiProblem(409, 'products.stock_operation_conflict',
                detail: 'The operation ID was already used with different details.');
        }
        if ($operation === 'AddStock' && $status->code === \Grpc\STATUS_FAILED_PRECONDITION) {
            throw new ApiProblem(409, 'products.stock_capacity', detail: 'Quantity exceeds warehouse capacity.');
        }
        if ($status->code !== \Grpc\STATUS_OK || $reply === null) {
            Log::warning('Warehouse RPC failed.', ['operation' => $operation, 'grpcCode' => $status->code]);
            $timedOut = $status->code === \Grpc\STATUS_DEADLINE_EXCEEDED;
            throw new ApiProblem(503, 'common.service_unavailable',
                detail: $timedOut ? 'Inventory warehouse did not respond in time.' : 'Inventory warehouse is unavailable.',
                userMessage: $timedOut ? 'تأخر رد المستودع. حاول مجددًا بعد قليل.' : null);
        }

        return $reply;
    }
}
