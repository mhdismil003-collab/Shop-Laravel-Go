<?php

use App\Modules\Orders\InventoryRecovery;
use App\Modules\Users\JwtTokens;
use App\Modules\Users\User;
use Illuminate\Support\Facades\Artisan;
use Illuminate\Support\Facades\Hash;

Artisan::command('shop:seed-admin', function (): int {
    app(JwtTokens::class);
    $email = strtolower((string) config('shop.admin_email'));
    $password = (string) config('shop.admin_password');
    if (! filter_var($email, FILTER_VALIDATE_EMAIL) || strlen($password) < 8 || strlen($password) > 72) {
        $this->error('Set ADMIN_EMAIL and ADMIN_PASSWORD before starting the API.');

        return 1;
    }

    $user = User::firstOrCreate(['email' => $email], ['password' => Hash::make($password), 'role' => 'Admin']);
    if ($user->role !== 'Admin') {
        $this->error('The configured admin email already belongs to a customer.');

        return 1;
    }

    return 0;
})->purpose('Create the configured demo admin and validate the JWT key');

Artisan::command('inventory:recover {--watch}', function (InventoryRecovery $recovery): int {
    do {
        try {
            if (! $recovery->tryRelease()) {
                if (! $this->option('watch')) {
                    return 0;
                }
                sleep(1);
            }
        } catch (Throwable $error) {
            report($error);
            if (! $this->option('watch')) {
                return 1;
            }
            sleep(2);
        }
    } while (true);
})->purpose('Release stock for incomplete or cancelled orders');
