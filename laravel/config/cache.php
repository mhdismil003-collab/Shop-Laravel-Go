<?php

return [
    'default' => 'database',
    'stores' => ['database' => ['driver' => 'database', 'table' => 'cache', 'lock_table' => 'cache_locks']],
    'prefix' => 'shop_laravel_cache',
];
