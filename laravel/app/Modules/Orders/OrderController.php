<?php

namespace App\Modules\Orders;

use App\Http\ApiHeaders;
use App\Http\ApiProblem;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\Log;

final class OrderController
{
    private const STATUSES = ['Pending', 'Confirmed', 'Shipped', 'Delivered', 'Cancelled'];

    public function __construct(private readonly OrderService $service) {}

    public function store(Request $request): JsonResponse
    {
        $data = $request->validate([
            'lines' => ['required', 'array', 'list', 'min:1', 'max:50'],
            'lines.*' => ['required', 'array:productId,quantity'],
            'lines.*.productId' => ['required', 'uuid', 'distinct:ignore_case'],
            'lines.*.quantity' => ['required', 'integer', 'between:1,1000'],
        ]);
        $lines = array_map(static fn (array $line) => [
            'productId' => strtolower($line['productId']),
            'quantity' => (int) $line['quantity'],
        ], $data['lines']);
        $id = $this->service->place($request->user()->id, $lines);

        return response()->json($this->service->details($this->service->orders()->where('id', $id)->first()),
            201, ['Location' => '/api/v1/orders/'.$id]);
    }

    public function index(Request $request): JsonResponse
    {
        $data = $request->validate([
            'status' => ['sometimes', 'in:'.implode(',', self::STATUSES)],
            'page' => ['sometimes', 'integer', 'min:1', 'max:1000000'],
            'pageSize' => ['sometimes', 'integer', 'between:1,50'],
        ]);
        $page = (int) ($data['page'] ?? 1);
        $size = (int) ($data['pageSize'] ?? 20);
        $user = $request->user();
        $query = $this->service->orders()
            ->when($user->role !== 'Admin', fn ($query) => $query->where('customer_id', $user->id))
            ->when(isset($data['status']), fn ($query) => $query->where('status', $data['status']));
        $count = (clone $query)->count();
        $items = $query->select('orders.*')
            ->selectRaw('(select coalesce(sum(quantity), 0) from order_lines where order_lines.order_id = orders.id) as item_count')
            ->orderByDesc('created_at')->orderByDesc('id')->forPage($page, $size)->get()
            ->map(fn ($order) => $this->service->summary($order) + ['itemCount' => (int) $order->item_count]);

        return response()->json(['items' => $items, 'page' => $page, 'pageSize' => $size, 'totalCount' => $count]);
    }

    public function show(Request $request, string $id): JsonResponse
    {
        $order = $this->service->orders()->where('id', $id)->first();
        $user = $request->user();
        if ($order !== null && $user->role !== 'Admin' && $order->customer_id !== $user->id) {
            Log::warning('Order access denied.', ['orderId' => $id, 'userId' => $user->id, 'traceId' => ApiHeaders::traceId($request)]);
            $order = null;
        }

        if ($order === null) {
            throw new ApiProblem(404, 'orders.not_found', 'Order not found');
        }

        return response()->json($this->service->details($order));
    }

    public function updateStatus(Request $request, string $id): JsonResponse
    {
        $data = $request->validate(['status' => ['required', 'in:'.implode(',', self::STATUSES)]]);
        $this->service->updateStatus($id, $data['status'], $request->user()->id);

        return $this->show($request, $id);
    }
}
