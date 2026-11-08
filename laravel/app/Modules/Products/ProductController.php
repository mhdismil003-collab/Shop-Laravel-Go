<?php

namespace App\Modules\Products;

use App\Http\ApiProblem;
use App\Modules\Warehouse\Inventory;
use Illuminate\Http\JsonResponse;
use Illuminate\Http\Request;
use Illuminate\Http\UploadedFile;
use Illuminate\Support\Facades\DB;
use Illuminate\Support\Facades\Storage;
use Illuminate\Support\Str;
use Symfony\Component\HttpFoundation\StreamedResponse;
use Throwable;

final class ProductController
{
    public function __construct(private readonly ProductCatalog $catalog) {}

    public function index(Request $request): JsonResponse
    {
        $data = $request->validate([
            'category' => ['sometimes', 'required', 'uuid'],
            'page' => ['sometimes', 'integer', 'min:1', 'max:1000000'],
            'pageSize' => ['sometimes', 'integer', 'between:1,50'],
        ]);
        $page = (int) ($data['page'] ?? 1);
        $size = (int) ($data['pageSize'] ?? 20);
        $query = $this->catalog->query()->when(isset($data['category']), fn ($query) => $query->where('category_id', $data['category']));
        $count = (clone $query)->count();
        $items = $query->orderByDesc('products.created_at')->orderBy('products.id')
            ->forPage($page, $size)->get()->map($this->catalog->response(...));

        return response()->json(['items' => $items, 'page' => $page, 'pageSize' => $size, 'totalCount' => $count]);
    }

    public function show(string $id, Inventory $inventory): JsonResponse
    {
        $product = $this->catalog->query()->where('products.id', $id)->first();
        if ($product === null) {
            throw new ApiProblem(404, 'products.not_found', 'Product not found');
        }

        return response()->json($this->catalog->response($product) + ['availableQuantity' => $inventory->available($id)]);
    }

    public function categories(): JsonResponse
    {
        return response()->json(DB::table('categories')->orderBy('name')->get(['id', 'name']));
    }

    public function store(Request $request): JsonResponse
    {
        $contentType = strtolower(trim(explode(';', (string) $request->header('Content-Type'), 2)[0]));
        if ($contentType !== 'multipart/form-data') {
            throw new ApiProblem(415, 'common.unsupported_media_type', detail: 'Use multipart/form-data to upload a product image.');
        }

        $image = $request->file('image');
        if ($image instanceof UploadedFile && (
            in_array($image->getError(), [UPLOAD_ERR_INI_SIZE, UPLOAD_ERR_FORM_SIZE], true)
            || ($image->isValid() && $image->getSize() > 2 * 1024 * 1024)
        )) {
            throw new ApiProblem(413, 'products.image_too_large', detail: 'Product images may not exceed 2 MiB.');
        }

        $data = $request->validate([
            'name' => ['required', 'string', 'max:160', 'not_regex:/\x00/'],
            'description' => ['required', 'string', 'max:4000', 'not_regex:/\x00/'],
            'price' => ['required', 'numeric', 'min:0.01', 'regex:/^\d{1,9}(?:\.\d{1,2})?$/'],
            'categoryId' => ['bail', 'required', 'uuid', 'exists:categories,id'],
            'image' => ['required', 'file'],
        ]);
        $info = @getimagesize($data['image']->getPathname());
        $extension = match ($info[2] ?? null) {
            IMAGETYPE_JPEG => 'jpg',
            IMAGETYPE_PNG => 'png',
            IMAGETYPE_WEBP => 'webp',
            default => null,
        };
        if ($extension === null || $info[0] < 1 || $info[1] < 1 || $info['mime'] !== $data['image']->getMimeType()) {
            throw new ApiProblem(415, 'products.unsupported_image_type', detail: 'Use a valid JPEG, PNG or WebP image.');
        }
        $id = (string) Str::uuid7();
        $name = $id.'.'.$extension;
        $disk = Storage::disk('public');
        $disk->putFileAs('products', $data['image'], $name);
        [$whole, $fraction] = array_pad(explode('.', (string) $data['price'], 2), 2, '');

        try {
            DB::table('products')->insert([
                'id' => $id, 'name' => $data['name'], 'description' => $data['description'],
                'price_cents' => (int) $whole * 100 + (int) str_pad($fraction, 2, '0'),
                'category_id' => $data['categoryId'], 'image_name' => $name, 'created_at' => now(),
            ]);
        } catch (Throwable $error) {
            try {
                if (! DB::table('products')->where('id', $id)->exists()) {
                    $disk->delete('products/'.$name);
                }
            } catch (Throwable $cleanupError) {
                report($cleanupError);
            }
            throw $error;
        }

        return response()->json($this->catalog->response($this->catalog->query()->where('products.id', $id)->first()),
            201, ['Location' => '/api/v1/products/'.$id]);
    }

    public function addStock(Request $request, string $id, Inventory $inventory): JsonResponse
    {
        $data = $request->validate([
            'quantity' => ['required', 'integer', 'between:1,2147483647'],
            'operationId' => ['required', 'uuid', 'not_in:00000000-0000-0000-0000-000000000000'],
        ]);
        if (! DB::table('products')->where('id', $id)->exists()) {
            throw new ApiProblem(404, 'products.not_found');
        }

        $operationId = strtolower($data['operationId']);
        $inventory->addStock($id, (int) $data['quantity'], $operationId);

        return response()->json(['operationId' => $operationId]);
    }

    public function image(string $name): StreamedResponse
    {
        $path = 'products/'.$name;
        $disk = Storage::disk('public');
        if (! $disk->exists($path)) {
            throw new ApiProblem(404, 'products.image_not_found');
        }

        return $disk->response($path);
    }
}
