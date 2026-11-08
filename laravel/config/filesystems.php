<?php

return [
    'default' => 'public',
    'disks' => [
        'local' => ['driver' => 'local', 'root' => storage_path('app/private'), 'serve' => false],
        'public' => [
            'driver' => 'local',
            'root' => env('IMAGES_ROOT', storage_path('app/public')),
            'throw' => true,
        ],
    ],
];
