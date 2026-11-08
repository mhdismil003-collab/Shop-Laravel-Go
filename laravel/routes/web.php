<?php

use App\Modules\Products\ProductController;
use Illuminate\Support\Facades\Route;

Route::get('/images/products/{name}', [ProductController::class, 'image'])
    ->where('name', '[0-9a-f-]{36}\.(?:jpg|png|webp)');
Route::get('/', fn () => response()->file(resource_path('shop.html')));
Route::get('/docs', fn () => response()->file(resource_path('api-docs.html')));
Route::get('/openapi/v1.json', fn () => response()->file(resource_path('openapi-v1.json'), ['Content-Type' => 'application/json']));
