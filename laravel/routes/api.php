<?php

use App\Modules\Notifications\OrderNotifications;
use App\Modules\Orders\OrderController;
use App\Modules\Products\ProductController;
use App\Modules\Users\AuthController;
use Illuminate\Support\Facades\Route;

Route::prefix('v1')->group(function (): void {
    Route::post('/auth/register', [AuthController::class, 'register']);
    Route::post('/auth/login', [AuthController::class, 'login'])->middleware('throttle:shop-login');
    Route::get('/users/me', [AuthController::class, 'me'])->middleware('shop.auth');
    Route::get('/notifications', [OrderNotifications::class, 'index'])->middleware('shop.auth:Customer');
    Route::get('/products', [ProductController::class, 'index']);
    Route::get('/products/{id}', [ProductController::class, 'show'])->whereUuid('id');
    Route::get('/categories', [ProductController::class, 'categories']);
    Route::post('/products', [ProductController::class, 'store'])->middleware('shop.auth:Admin');
    Route::post('/products/{id}/stock-additions', [ProductController::class, 'addStock'])
        ->whereUuid('id')->middleware('shop.auth:Admin');
    Route::post('/orders', [OrderController::class, 'store'])->middleware('shop.auth:Customer');
    Route::get('/orders', [OrderController::class, 'index'])->middleware('shop.auth');
    Route::get('/orders/{id}', [OrderController::class, 'show'])->whereUuid('id')->middleware('shop.auth');
    Route::patch('/orders/{id}/status', [OrderController::class, 'updateStatus'])->whereUuid('id')->middleware('shop.auth:Admin');
});
