<?php

namespace App\Modules\Orders;

use App\Modules\Warehouse\Inventory;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Log;
use Throwable;

final class InventoryRecovery
{
    public function __construct(private readonly Inventory $inventory) {}

    public function beginPlacement(string $orderId): void
    {
        DB::table('inventory_recovery')->insert([
            'order_id' => $orderId, 'state' => 'placing', 'due_at' => now()->addSeconds(30),
        ]);
    }

    public function lockPlacement(string $orderId): bool
    {
        return $this->job($orderId)->where('state', 'placing')->lockForUpdate()->first() !== null;
    }

    public function finishPlacement(string $orderId): void
    {
        $this->job($orderId)->where('state', 'placing')->delete();
    }

    public function abandonPlacement(string $orderId): void
    {
        $this->job($orderId)->where('state', 'placing')->update(['state' => 'pending', 'due_at' => now()]);
    }

    public function enqueueCancellation(string $orderId): void
    {
        DB::table('inventory_recovery')->insertOrIgnore([
            'order_id' => $orderId, 'state' => 'pending', 'due_at' => now(),
        ]);
    }

    public function tryRelease(?string $orderId = null): bool
    {
        // The lease is committed before the network call. A placement cannot be finalized once claimed.
        $job = DB::transaction(function () use ($orderId): ?object {
            $job = DB::table('inventory_recovery')->where('due_at', '<=', now())
                ->when($orderId !== null, fn (Builder $query) => $query->where('order_id', $orderId))
                ->orderBy('due_at')->orderBy('order_id')->lock('for update skip locked')->first();
            if ($job === null) {
                return null;
            }

            $job->attempts++;
            $lease = max(5, (int) ceil(config('shop.warehouse_timeout_us') / 1000000) + 3);
            $this->job($job->order_id)->update([
                'state' => 'pending', 'due_at' => now()->addSeconds($lease), 'attempts' => $job->attempts,
            ]);

            return $job;
        });

        if ($job === null) {
            return false;
        }

        $owned = $this->job($job->order_id)->where('attempts', $job->attempts);
        try {
            $this->inventory->release($job->order_id);
        } catch (Throwable $error) {
            $owned->update(['due_at' => now()->addSeconds(min(30, 2 ** min($job->attempts, 5)))]);
            Log::warning('Stock release will be retried.', ['orderId' => $job->order_id, 'attempt' => $job->attempts]);

            return true;
        }

        $owned->delete();

        return true;
    }

    private function job(string $orderId): Builder
    {
        return DB::table('inventory_recovery')->where('order_id', $orderId);
    }
}
