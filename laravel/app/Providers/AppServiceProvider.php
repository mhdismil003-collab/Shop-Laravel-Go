<?php

namespace App\Providers;

use App\Http\ApiProblem;
use App\Modules\Warehouse\GrpcInventory;
use App\Modules\Warehouse\Inventory;
use Illuminate\Cache\RateLimiting\Limit;
use Illuminate\Http\Request;
use Illuminate\Support\Facades\RateLimiter;
use Illuminate\Support\ServiceProvider;

final class AppServiceProvider extends ServiceProvider
{
    public function register(): void
    {
        $this->app->singleton(Inventory::class, GrpcInventory::class);
    }

    public function boot(): void
    {
        RateLimiter::for('shop-login', static fn (Request $request) => Limit::perMinute(max(1, config('shop.login_limit')))
            ->by($request->ip() ?? 'unknown')->response(static function (Request $request, array $headers) {
                return (new ApiProblem(429, 'common.too_many_requests', headers: $headers))->response($request);
            }));
    }
}
