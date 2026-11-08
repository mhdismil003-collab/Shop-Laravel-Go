<?php

namespace App\Modules\Orders;

use App\Http\ApiProblem;
use App\Modules\Notifications\OrderNotifications;
use App\Modules\Products\ProductCatalog;
use App\Modules\Warehouse\Inventory;
use Carbon\CarbonImmutable;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Str;
use Throwable;

final class OrderService
{
    private const TRANSITIONS = [
        'Pending' => ['Confirmed', 'Cancelled'],
        'Confirmed' => ['Shipped', 'Cancelled'],
        'Shipped' => ['Delivered'],
        'Delivered' => [],
        'Cancelled' => [],
    ];

    public function __construct(
        private readonly ProductCatalog $catalog,
        private readonly Inventory $inventory,
        private readonly InventoryRecovery $recovery,
        private readonly OrderNotifications $notifications,
    ) {}

    public function place(string $customerId, array $lines): string
    {
        $orderId = (string) Str::uuid7();
        $products = $this->catalog->snapshots(array_column($lines, 'productId'));
        $records = [];
        $total = 0;
        $errors = [];
        foreach ($lines as $index => $line) {
            $product = $products->get($line['productId']);
            if ($product === null) {
                $errors["lines.$index.productId"] = ['The product does not exist.'];

                continue;
            }

            $records[] = [
                'order_id' => $orderId, 'product_id' => $product->id, 'product_name' => $product->name,
                'unit_price_cents' => $product->price_cents, 'quantity' => $line['quantity'],
            ];
            $total += $product->price_cents * $line['quantity'];
        }

        if ($errors !== []) {
            throw new ApiProblem(422, 'common.validation_failed', extra: ['errors' => $errors]);
        }

        $this->recovery->beginPlacement($orderId);
        try {
            $shortages = $this->inventory->reserve($orderId, $lines);
            if ($shortages !== null) {
                $this->recovery->finishPlacement($orderId);
            } else {
                DB::transaction(function () use ($orderId, $customerId, $total, $records): void {
                    if (! $this->recovery->lockPlacement($orderId)) {
                        throw new ApiProblem(503, 'common.service_unavailable', detail: 'The reservation expired before the order was saved.',
                            userMessage: 'انتهت صلاحية الحجز قبل حفظ الطلب. أعد مراجعة السلة وحاول مجددًا.');
                    }

                    $now = now();
                    DB::table('orders')->insert([
                        'id' => $orderId, 'customer_id' => $customerId, 'status' => 'Pending',
                        'total_cents' => $total, 'created_at' => $now, 'updated_at' => $now,
                    ]);
                    DB::table('order_lines')->insert($records);
                    $this->appendHistory($orderId, null, 'Pending', $customerId);
                    $this->notifications->record($customerId, $orderId, 'Pending');
                    $this->recovery->finishPlacement($orderId);
                });
            }
        } catch (Throwable $error) {
            try {
                // If the order COMMIT succeeded, its intent was deleted in the same transaction.
                $this->recovery->abandonPlacement($orderId);
                if (! ($error instanceof ApiProblem && $error->status === 503)) {
                    $this->recovery->tryRelease($orderId);
                }
            } catch (Throwable $recoveryError) {
                report($recoveryError);
            }
            throw $error;
        }

        if ($shortages !== null) {
            throw new ApiProblem(409, 'orders.insufficient_stock', 'Insufficient stock',
                'Not enough stock is available for one or more products.', ['shortages' => $shortages]);
        }

        return $orderId;
    }

    public function updateStatus(string $id, string $next, string $adminId): void
    {
        DB::transaction(function () use ($id, $next, $adminId): void {
            $order = $this->orders()->where('id', $id)->lockForUpdate()->first();
            if ($order === null) {
                throw new ApiProblem(404, 'orders.not_found', 'Order not found');
            }

            if (! in_array($next, self::TRANSITIONS[$order->status], true)) {
                throw new ApiProblem(409, 'orders.invalid_status_transition', detail: "An order in status {$order->status} can't move to $next.");
            }

            $this->orders()->where('id', $id)->update(['status' => $next, 'updated_at' => now()]);
            $this->appendHistory($id, $order->status, $next, $adminId);
            $this->notifications->record($order->customer_id, $id, $next);
            if ($next === 'Cancelled') {
                $this->recovery->enqueueCancellation($id);
            }
        });

        if ($next === 'Cancelled') {
            try {
                $this->recovery->tryRelease($id);
            } catch (Throwable $error) {
                report($error);
            }
        }
    }

    public function orders(): Builder
    {
        return DB::table('orders');
    }

    public function summary(object $order): array
    {
        return [
            'id' => $order->id,
            'customerId' => $order->customer_id,
            'status' => $order->status,
            'total' => $order->total_cents / 100,
            'createdAt' => CarbonImmutable::parse($order->created_at)->toIso8601String(),
            'updatedAt' => CarbonImmutable::parse($order->updated_at)->toIso8601String(),
        ];
    }

    public function details(object $order): array
    {
        $lines = DB::table('order_lines')->where('order_id', $order->id)->orderBy('product_id')->get()->map(static fn ($line) => [
            'productId' => $line->product_id, 'productName' => $line->product_name,
            'unitPrice' => $line->unit_price_cents / 100, 'quantity' => $line->quantity,
            'lineTotal' => ($line->unit_price_cents * $line->quantity) / 100,
        ]);
        $history = DB::table('order_history')->where('order_id', $order->id)->orderBy('id')->get()->map(static fn ($change) => [
            'fromStatus' => $change->from_status, 'toStatus' => $change->to_status,
            'changedBy' => $change->changed_by, 'changedAt' => CarbonImmutable::parse($change->changed_at)->toIso8601String(),
        ]);

        return $this->summary($order) + ['lines' => $lines, 'history' => $history];
    }

    private function appendHistory(string $id, ?string $previous, string $next, string $changedBy): void
    {
        DB::table('order_history')->insert([
            'order_id' => $id, 'from_status' => $previous, 'to_status' => $next,
            'changed_by' => $changedBy, 'changed_at' => now(),
        ]);
    }
}
