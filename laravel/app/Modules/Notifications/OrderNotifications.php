<?php

namespace App\Modules\Notifications;

use Carbon\CarbonImmutable;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\DB;

final class OrderNotifications
{
    public function record(string $customerId, string $orderId, string $status): void
    {
        DB::table('order_notifications')->insert([
            'customer_id' => $customerId,
            'order_id' => $orderId,
            'status' => $status,
            'created_at' => now(),
        ]);
    }

    public function index(Request $request): JsonResponse
    {
        $items = DB::table('order_notifications')->where('customer_id', $request->user()->id)
            ->orderByDesc('id')->limit(20)->get()->map(static fn ($row) => [
                'orderId' => $row->order_id,
                'status' => $row->status,
                'createdAt' => CarbonImmutable::parse($row->created_at)->toIso8601String(),
            ]);

        return response()->json(['items' => $items]);
    }
}
