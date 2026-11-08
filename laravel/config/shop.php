<?php

return [
    'jwt_key' => env('JWT_SIGNING_KEY'),
    'jwt_issuer' => 'shop-api',
    'jwt_audience' => 'shop-client',
    'jwt_seconds' => 900,
    'login_limit' => (int) env('LOGIN_RATE_LIMIT_PERMIT_LIMIT', 5),
    'admin_email' => env('ADMIN_EMAIL'),
    'admin_password' => env('ADMIN_PASSWORD'),
    'warehouse_address' => env('WAREHOUSE_ADDRESS', '127.0.0.1:50051'),
    'warehouse_admin_address' => env('WAREHOUSE_ADMIN_ADDRESS', '127.0.0.1:50052'),
    'warehouse_timeout_us' => (int) env('WAREHOUSE_TIMEOUT_MS', 2000) * 1000,
];
