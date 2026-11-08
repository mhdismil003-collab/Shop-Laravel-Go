<?php

namespace App\Modules\Products;

use Carbon\CarbonImmutable;
use Illuminate\Database\Query\Builder;
use Illuminate\Support\Collection;
use Illuminate\Support\Facades\DB;

final class ProductCatalog
{
    public function query(): Builder
    {
        return DB::table('products')->join('categories', 'products.category_id', '=', 'categories.id')
            ->select('products.*', 'categories.name as category_name');
    }

    public function snapshots(array $ids): Collection
    {
        return DB::table('products')->whereIn('id', $ids)->get(['id', 'name', 'price_cents'])->keyBy('id');
    }

    public function response(object $product): array
    {
        return [
            'id' => $product->id,
            'name' => $product->name,
            'description' => $product->description,
            'price' => $product->price_cents / 100,
            'imageUrl' => '/images/products/'.$product->image_name,
            'categoryId' => $product->category_id,
            'categoryName' => $product->category_name,
            'createdAt' => CarbonImmutable::parse($product->created_at)->toIso8601String(),
        ];
    }
}
